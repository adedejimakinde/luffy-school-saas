"""Posting to the fee ledger. The only supported way to write one.

Four functions, one per thing that can happen to a family's account: they are
charged, they pay, they are given a discount, or somebody made a mistake and it
is undone. There is deliberately no general "adjust" — see `reverse_entry()`.

Everything here takes the caller's *student membership id* rather than a
`Membership` object, because the ledger stores a bare id and the two must not
drift apart. `snapshot_student()` is the one place that turns a live membership
into the frozen identity an entry carries.

No screens, no HTTP. This is the data layer the eventual bursar's screen will
call, and keeping the rules here rather than in a view is what makes them true
for an import and a management command too.
"""

from django.db import transaction
from django.utils import timezone

from accounts.students import why_not_a_student_here

from .models import FeeEntryKind, FeeLedgerEntry, LedgerIsAppendOnly


class FeeLedgerError(Exception):
    """A ledger entry could not be posted as asked.

    One base class for the whole module, for the same reason
    `schools.models.InvitationError` is one for the invitation flow: a caller
    that writes `except FeeLedgerError` should catch every refusal this module
    makes, not the half it happened to import.
    """


class NotPositive(FeeLedgerError):
    """An amount was zero or negative where a magnitude was wanted.

    Every function here takes the amount as a plain positive number of kobo and
    applies the sign itself. Letting a caller pass a negative to `charge()`
    would make the sign a caller's choice, and the sign is the ledger's whole
    grammar.
    """


class AlreadyReversed(FeeLedgerError):
    """That entry has been undone once already."""


class CannotReverse(FeeLedgerError):
    """That entry is not one that can be undone."""


class NotThisTermsLine(FeeLedgerError):
    """The schedule line named belongs to a different term than the charge.

    `a_schedule_line_charges_a_child_once` is keyed on
    `(student_membership_id, source_line)` and carries no term, on the argument
    that a line belongs to a schedule which belongs to exactly one term, so the
    pair is already term-scoped. That is true of the *line* and false of the
    *caller*: nothing stopped a hand-typed charge naming this term and last
    term's line. The index then reads that entry as this line's charge for the
    child, and the next `apply_to_class()` run reports their tuition as
    **skipped** and never bills it -- silent under-billing, discovered when a
    parent asks why their invoice is short.

    No constraint can express this: the rule spans `FeeLedgerEntry`,
    `FeeScheduleLine` and `FeeSchedule`, so it has to be asked in code.
    """


class NotThisStudentsConcession(FeeLedgerError):
    """The concession named belongs to a different child than the discount.

    The mirror of `NotThisTermsLine` on the other new column, and the one that
    corrupts a *question* rather than a balance:
    `a_concession_discounts_a_child_once_per_term` is keyed per student, so
    Chidi's bursary posted against Ada's account is accepted by the index, and
    "everything this concession did" then answers with two children -- while
    Chidi's own discount still posts later, because that pair is untaken.

    `_require_student_of_this_school()` already guards the child half of every
    entry this carefully. This is the same guard for the source half.
    """


class NotThisSchoolsStudent(FeeLedgerError):
    """The membership named is not a student of the school whose books these are.

    This is the check that earns the bare id. `student_membership_id` has no
    foreign key — see docs/tenancy.md for why — which means the database will
    happily store *any* integer there, including the id of a child at another
    school entirely. Nothing about that would be visible: the entry would sit in
    St Mary's ledger, count towards a St Mary's balance, and name a student St
    Mary's has never taught.

    A foreign key would not have caught it either, note. `Membership` is shared,
    so a foreign key into it constrains only that the row *exists* — every
    school's students are in the same table. The school half of the question has
    to be asked in code whichever way the column is declared.
    """


def _require_student_of_this_school(membership):
    """Refuse a membership that is not a student here, before anything is written.

    The rule itself now lives in `accounts.students` — see the note on
    `NotThisSchoolsStudent` above, which said it would move there once a third
    tenant app asked the same question. What stays here is the *raising*, so
    that `except FeeLedgerError` still means "the entry was not posted".
    """
    reason = why_not_a_student_here(
        membership, subject="a fee entry", holder="books"
    )
    if reason:
        raise NotThisSchoolsStudent(reason)
    return membership


def snapshot_student(membership):
    """The identity fields an entry freezes, taken from a live membership.

    Kept in one place because getting it wrong is silent: an entry posted with
    a blank name is unreadable a year later, and one posted by joining to the
    live row rewrites itself when a school corrects a spelling.
    """
    return {
        "student_membership_id": membership.pk,
        "student_name": membership.name,
        "student_reference": membership.reference,
    }


def _post(*, membership, term, kind, amount_kobo, narration, effective_on,
          reference="", recorded_by=None, reverses=None, source_line=None,
          source_concession=None):
    """Create one entry. Every public function below funnels through here."""
    _require_student_of_this_school(membership)
    entry = FeeLedgerEntry(
        term=term,
        kind=kind,
        amount_kobo=amount_kobo,
        narration=narration,
        reference=reference,
        effective_on=effective_on or timezone.localdate(),
        recorded_by_id=getattr(recorded_by, "pk", recorded_by),
        reverses=reverses,
        source_line=source_line,
        source_concession=source_concession,
        **snapshot_student(membership),
    )
    # `full_clean()` rather than a bare save: the cross-row rules for a reversal
    # live in `Model.clean()` because no check constraint can express "equal and
    # opposite to another row". Excluding nothing, so the field-level rules are
    # asked here too rather than only at the database.
    entry.full_clean(exclude=None, validate_unique=False, validate_constraints=False)
    entry.save()
    return entry


def _magnitude(amount_kobo):
    if not isinstance(amount_kobo, int) or isinstance(amount_kobo, bool):
        raise NotPositive(
            f"Amounts are whole kobo as an int, not {type(amount_kobo).__name__}. "
            f"A float cannot hold a naira amount exactly, which is the reason "
            f"this column is kobo in the first place."
        )
    if amount_kobo <= 0:
        raise NotPositive(
            f"Pass the amount as a positive number of kobo; the ledger applies "
            f"the sign. Got {amount_kobo}."
        )
    return amount_kobo


@transaction.atomic
def charge(membership, term, amount_kobo, *, narration, effective_on=None,
           reference="", recorded_by=None, source_line=None):
    """Bill a student. Increases what the family owes.

    `source_line` is passed by `fees.schedules` and left null by every hand-typed
    charge. It is what makes "everything this line of the bill did" a question
    with an answer, and what the idempotency index keys on.

    **A caller passing `source_line` must hold the schedule's row lock**, the way
    `schedules.apply_to_class()` does. `a_schedule_line_charges_a_child_once`
    refuses a second charge for one child and line, and outside that lock two
    writers can both pass a skip-check and one will meet the index. Today this
    module has exactly one such caller, so the race is not reachable; the note is
    here because the second caller is the one that will not know.

    Raises `NotThisTermsLine` if the line belongs to another term's bill.
    """
    # Asked here rather than left to a constraint, because no constraint can
    # reach across three tables to ask it. Free in the hot path:
    # `apply_to_class()` reads its lines through `locked.lines.all()`, and a
    # reverse manager primes each line's `schedule` from the instance it came
    # from, so this compares two integers already in memory.
    if source_line is not None and source_line.schedule.term_id != term.pk:
        raise NotThisTermsLine(
            f"Line {source_line.pk} belongs to {source_line.schedule}, which is "
            f"another term's bill; this charge is for {term}. Charging it here "
            f"would fill that child's slot in "
            f"a_schedule_line_charges_a_child_once, and the run that should "
            f"bill them would report a skip instead."
        )
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.CHARGE,
        amount_kobo=_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        reference=reference,
        recorded_by=recorded_by,
        source_line=source_line,
    )


@transaction.atomic
def record_payment(membership, term, amount_kobo, *, narration="Payment received",
                   effective_on=None, reference="", recorded_by=None):
    """Record money received. Reduces what the family owes."""
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.PAYMENT,
        amount_kobo=-_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        reference=reference,
        recorded_by=recorded_by,
    )


@transaction.atomic
def discount(membership, term, amount_kobo, *, narration, effective_on=None,
             recorded_by=None, source_concession=None):
    """Reduce what is owed without money changing hands.

    A bursary, a staff child's concession, a sibling discount. Its own kind
    rather than a negative charge, because "we waived it" and "they paid it" are
    different facts and a school's books have to be able to tell them apart.

    Raises `NotThisStudentsConcession` if the concession is another child's.
    """
    if (
        source_concession is not None
        and source_concession.student_membership_id != membership.pk
    ):
        raise NotThisStudentsConcession(
            f"Concession {source_concession.pk} belongs to membership "
            f"{source_concession.student_membership_id}, not to {membership.pk}. "
            f"The index is keyed per student, so this would post, and "
            f"'everything this concession did' would answer with two children."
        )
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.DISCOUNT,
        amount_kobo=-_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        recorded_by=recorded_by,
        source_concession=source_concession,
    )


@transaction.atomic
def refund(membership, term, amount_kobo, *, narration="Refund", effective_on=None,
           reference="", recorded_by=None):
    """Hand money back. Increases what the family owes, back towards zero.

    The sign is the surprising half and it is right: a family sitting at −₦50,000
    who are handed ₦50,000 in cash are square, not −₦100,000. A refund moves the
    balance the same direction a charge does, which is why `INCREASES_DEBT` names
    both.

    **Not the default answer to a mid-term withdrawal.** Money is carried, not
    returned: the credit simply stands against the child, which needs no
    machinery at all and is what most schools do. This exists so that a school
    which *does* return cash can say so, rather than posting a REVERSAL of a
    payment that was genuinely received — those are different facts, the same way
    a discount and a payment are.

    A school that pro-rates a withdrawal posts a REVERSAL or a DISCOUNT by hand.
    The ledger records what happened; it holds no refund policy.
    """
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.REFUND,
        amount_kobo=_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        reference=reference,
        recorded_by=recorded_by,
    )


#: The narration column's own width, read from the field so the two cannot
#: drift apart.
_NARRATION_MAX = FeeLedgerEntry._meta.get_field("narration").max_length


def _inherited_narration(narration):
    """`"Reversal of: X"`, trimmed to the column rather than failing to save.

    `FeeScheduleLine.description` and `FeeLedgerEntry.narration` are both 255,
    and `apply_to_class()` copies one into the other verbatim -- so a line
    described in 243 characters or more posts a charge whose reversal is
    thirteen characters too long. That was unreachable while every narration was
    hand-typed, and this PR made it reachable.

    It matters more than a truncation usually would, because of *how* it failed:
    `full_clean()` raises `ValidationError`, which is not a `FeeLedgerError`. A
    caller writing `except FeeLedgerError` -- the contract this module's
    docstring insists on -- would not have caught it, and the charge simply
    could not be undone. Trimming keeps the prefix, which is the part a reader
    needs, and marks the cut so nobody reads the tail as the whole description.
    """
    inherited = f"Reversal of: {narration}"
    if len(inherited) <= _NARRATION_MAX:
        return inherited
    return inherited[: _NARRATION_MAX - 1] + "\u2026"


@transaction.atomic
def reverse_entry(entry, *, narration=None, effective_on=None, recorded_by=None,
                  membership=None):
    """Undo `entry` by posting its exact opposite. Returns the new entry.

    The only correction there is, and deliberately the only one. There is no
    "edit the amount" and no free-form adjustment: a charge raised for the wrong
    amount is reversed in full and the right one posted fresh, which leaves both
    the mistake and the fix legible a year later. An adjustment of "-30,000
    because the first number was wrong" tells a reader the difference and never
    what actually happened.

    The identity snapshot is taken from `entry` rather than from a live lookup,
    unless a `membership` is passed. A reversal is part of the original story and
    should read the way the original read — including when the student has since
    left and their membership has ended.

    **And it inherits the source**, for the same reason it inherits `reference`:
    a reversal of a schedule charge is still *about* that line of the bill, so
    "everything this line did" has to return the mistake and the fix together.
    The uniqueness indexes are conditioned on `kind` precisely so that carrying
    the source across does not collide with the entry being undone.
    """
    # Locked and re-read before deciding, because "has this been reversed
    # already?" is a question about the present, and two bursars clicking undo
    # on the same charge is exactly the race this guards. `select_for_update()`
    # on the entry itself; `.order_by()` is not needed here because
    # `FeeLedgerEntry.Meta.ordering` sorts by its own columns and joins nothing —
    # the trap docs/membership.md records for `Membership` does not apply.
    #
    # **And no `select_related("term")`.** `select_for_update()` locks every
    # table it joins, so that took `FOR UPDATE` on the `academics_term` row.
    # Issue #78 scoped the joined lock as waste; `apply_to_class()` is what turns
    # it into contention. Every entry that run inserts takes `FOR KEY SHARE` on
    # the same term row for its foreign-key check and holds it to commit, and
    # `FOR KEY SHARE` conflicts with `FOR UPDATE`: one bursar clicking undo on an
    # unrelated payment blocks for the length of a forty-five-child billing run,
    # and in the other order the billing run stalls on its first insert. The
    # reversal needs the term's *id*, which the locked row already carries, so
    # the join bought nothing at all.
    locked = FeeLedgerEntry.objects.select_for_update().get(pk=entry.pk)

    if locked.kind == FeeEntryKind.REVERSAL:
        raise CannotReverse(
            "That entry is itself a reversal. Reverse the original entry, or "
            "post a fresh one — undoing an undo is a way to lose track of what "
            "actually happened."
        )
    if FeeLedgerEntry.objects.filter(reverses=locked).exists():
        raise AlreadyReversed(
            f"Ledger entry {locked.pk} has already been reversed. Post a new "
            f"entry if something further needs correcting."
        )

    if membership is not None:
        identity = {}
        snapshot = membership
    else:
        identity = {
            "student_membership_id": locked.student_membership_id,
            "student_name": locked.student_name,
            "student_reference": locked.student_reference,
        }
        snapshot = None

    reversal = FeeLedgerEntry(
        # `term_id`, not `term`: the id is already on the locked row, and
        # touching `.term` would spend a query fetching a row nothing here reads.
        term_id=locked.term_id,
        kind=FeeEntryKind.REVERSAL,
        amount_kobo=-locked.amount_kobo,
        narration=narration or _inherited_narration(locked.narration),
        reference=locked.reference,
        source_line_id=locked.source_line_id,
        source_concession_id=locked.source_concession_id,
        effective_on=effective_on or timezone.localdate(),
        recorded_by_id=getattr(recorded_by, "pk", recorded_by),
        reverses=locked,
        **(identity if snapshot is None else snapshot_student(snapshot)),
    )
    reversal.full_clean(exclude=None, validate_unique=False, validate_constraints=False)
    reversal.save()
    return reversal


__all__ = [
    "AlreadyReversed",
    "CannotReverse",
    "FeeLedgerError",
    "LedgerIsAppendOnly",
    "NotPositive",
    "NotThisSchoolsStudent",
    "NotThisStudentsConcession",
    "NotThisTermsLine",
    "charge",
    "discount",
    "record_payment",
    "refund",
    "reverse_entry",
    "snapshot_student",
]
