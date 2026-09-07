"""Holding a released card back from a family over fees. `docs/withholding.md`.

## The freeze is never conditional

Nothing in this module touches `release()`, `cards.freeze_for_release()`, or any
frozen table. **The card is frozen at release for every child, unconditionally.**
What fees gate is whether the card is *served*.

Making the freeze conditional on payment would leave an unpaid child with no
frozen record of that term, permanently — the exact failure #31, #33 and #34
converged on, and it must not come back through the fee door.
`results/tests/test_withholding.py` pins it, because it is the kind of rule that
reads as an optimisation to somebody who has not met the issues behind it.

## The serving path never touches the books

`is_withheld()` reads a settings row and a decision row. It does not go near
`fees`, so a ledger that is locked, slow or mid-import cannot affect a single
card. **`fees` is therefore imported inside `withhold()` and `lift()`, not at
module scope** — there is no import cycle to avoid and the reason is honesty
about the dependency surface: a module-level `import fees` would make the
sentence above a claim about queries that the imports contradict at a glance.
`services.release()` already imports its freeze modules inside the function, so
the shape is precedented.

## The switch is asked before the decisions are

That ordering is the composition and it is the point. A school turning the
feature off serves every card immediately, without walking back four hundred
rows; the rows survive, so turning it back on restores the state rather than
having lost it.

## The balance never gates

It is frozen onto the decision row and read by nobody. A rule like *withhold
while balance > 0* would withhold from a family a few hundred naira short on a
payment plan, and part-payment is the normal case. A person decides; the number
is there so the row explains itself in a year.

The read lives here rather than in `card_api`'s private helpers because there
are **two** serving surfaces — the JSON card and the PDF — and a gate reachable
from only one of them is a gate a family gets past by adding four characters to
a URL.
"""

from typing import Optional

from accounts.models import Membership, Role
from accounts.students import why_not_a_student_here

from . import ratings
from .models import (
    ReportCardSettings,
    WithholdingDecision,
    WithholdingStatus,
)
from .services import (  # noqa: PLC2701
    ResultsError,
    _require_authority,
)

#: Who may hold a card back, and who may let one go.
#:
#: **Its own constant, never imported from `RELEASING_ROLES` or from
#: `card_api.CARD_VIEWING_ROLES`.** They coincide on `principal` today and answer
#: different questions; tying them together would mean a later widening of one
#: silently widened the others.
#:
#: **Both roles, deliberately.** Principal-only is the tempting answer, because
#: Phase 1 narrowed `RELEASING_ROLES` on purpose, and it is wrong-shaped here:
#: the principal is not the person who knows the ledger. A principal-only lever
#: means the bursar walks to the principal's office for every withheld child,
#: which in practice means the lever gets used from the principal's login by the
#: bursar — and then the audit names the wrong person, which is worse than
#: granting it honestly. Bursar-only is also wrong: withholding a report card
#: carries academic weight and a principal must be able to override.
#:
#: The append-only log is what makes "both" safe. A principal lifting what a
#: bursar withheld writes a second row, and both acts stand with both names on
#: them.
WITHHOLDING_ROLES = frozenset({Role.PRINCIPAL.value, Role.BURSAR.value})


class WithholdingError(ResultsError):
    """Something about holding a card back could not be done.

    Subclasses `results.services.ResultsError` rather than starting a hierarchy
    of its own, for `RatingsError`'s reason: a caller wrapping "get this class's
    results out" in `except ResultsError` should not have to learn a new base
    class per submodule. Every other `results` submodule does the same —
    `CommentsError`, `SessionsError`, `CardsError`, `RatingsError`,
    `GradesError`, `RevisionError`.

    A bare `ValueError` here would sit outside that hierarchy, so every
    `except ResultsError` would miss a refusal this module raises on purpose.
    """


class NotThisSchoolsStudent(WithholdingError):
    """The membership named is not a student of the school being written to.

    Its own type in this module for the reason `fees`, `gradebook` and `ratings`
    each keep one: `accounts.students.why_not_a_student_here()` defines the rule
    and returns a sentence, and each app raises it in its own words and its own
    hierarchy.
    """


class CardWithheld(Exception):
    """This school is holding this card back from this family.

    Carries what the 403 has to say and nothing else. Not the balance — a
    parent-facing number is a support burden and a correctness risk, and a family
    will dispute a figure the bursar has not reconciled — and **not `reason`**,
    which is the bursar's internal note.

    It exists because every 403 in this codebase is
    `ninja.errors.HttpError(403, str)`, whose body is `{"detail": ...}` and
    cannot carry a field. `contact` is the entire reason `withholding_contact`
    and its constraint exist, so a plain-string refusal would drop the one thing
    the design is for. `api.py` renders this into `card_api.WithheldOut`.

    `school_name` comes from the card's **frozen copy**, never a live join to
    `School` — operating rule 2. The card that went home says which school sent
    it, including where the school has since been renamed.
    """

    def __init__(self, *, school_name: str, contact: str):
        self.school_name = school_name
        self.contact = contact
        super().__init__(f"{school_name} is holding this report card.")


# -- policy ------------------------------------------------------------------


def settings() -> ReportCardSettings:
    """This school's card settings. Never writes.

    Deliberately `ratings.settings()` itself and not a second reader of the same
    row: one `pk=1` lookup, falling back to an **unsaved default** where the row
    is missing rather than creating it. That default has the switch off, which
    is the right answer for a schema with no row — and reading a report card
    must not write to the database.
    """
    return ratings.settings()


def set_policy(*, enabled: bool, contact: Optional[str] = None) -> ReportCardSettings:
    """Turn the fee gate on or off, and say who a family should call.

    Both in one call, because they are one decision. Two setters would offer a
    path that leaves the row in the state the constraint refuses — switch on,
    nobody to call — and the whole reason the constraint exists is that the
    dead end is reachable from more than one direction.

    `contact=None` means *leave it as it is*, so turning the gate off keeps the
    number: a school that pauses withholding for a term has not forgotten its
    own bursar's phone. Turning it **on** at a school that has never set one
    therefore hits `a_withholding_school_names_who_to_call`, which is the
    refusal working rather than a gap in this function.
    """
    row, _ = ReportCardSettings.objects.get_or_create(pk=1)
    row.withhold_for_fees_enabled = bool(enabled)
    if contact is not None:
        row.withholding_contact = contact

    # The service refuses what the table would refuse, which is
    # `ratings._require_a_trait_name()`'s rule and for its reasons: the
    # constraint is what actually holds, but a service that leaves it to fire
    # hands the caller a raw `IntegrityError` — outside `ResultsError`, so every
    # `except ResultsError` misses it, and fatal to an enclosing `atomic()` with
    # no savepoint under it. A bursar who typed spaces into a form gets a 500
    # where a sentence would do.
    if row.withhold_for_fees_enabled and not row.withholding_contact.strip():
        raise WithholdingError(
            "Withholding cannot be turned on without saying who a family should "
            "call. A school that holds cards back and tells nobody where to ring "
            "has built a dead end for the parent standing at it."
        )

    row.save(
        update_fields=[
            "withhold_for_fees_enabled",
            "withholding_contact",
            "updated_at",
        ]
    )
    return row


def set_policy_as(actor, *, enabled: bool, contact: Optional[str] = None):
    """`set_policy()` for a caller with a request behind it."""
    _require_withholding_authority(actor, "set the withholding policy for")
    return set_policy(enabled=enabled, contact=contact)


# -- the read, on the serving path -------------------------------------------


def latest_decision(student_membership_id: int, term) -> Optional[WithholdingDecision]:
    """The row that holds for this child in this term, or `None`.

    `Meta.ordering` is what makes "latest" total — `-decided_at` then `-id`, so
    two decisions written in one request do not resolve arbitrarily.

    Takes a `Term` **or its id**, because the serving path holds a card and
    `card.term_id` is a column it already has — asking it to fetch a `Term` to
    pass one in would be a join to satisfy a signature. `term_id=` rather than
    `term=` keeps the query on local columns, which is the same rule
    `Meta.ordering` follows and for the same reason.
    """
    return (
        WithholdingDecision.objects.filter(
            student_membership_id=student_membership_id,
            term_id=getattr(term, "pk", term),
        )
        .order_by("-decided_at", "-id")
        .first()
    )


def is_withheld(student_membership_id: int, term) -> bool:
    """Is this school holding this child's card for this term?

    **Step one before step two**, and that is the composition rather than an
    early return for speed: the switch gates whether decisions are consulted at
    all, so a school with the feature off serves every card without the rows
    being touched or lost.
    """
    if not settings().withhold_for_fees_enabled:
        return False

    row = latest_decision(student_membership_id, term)
    return row is not None and row.status == WithholdingStatus.WITHHELD


# -- the write, and the one place `results` reads `fees` ---------------------


def _require_withholding_authority(actor, step: str):
    """Authority for a withholding act, resolved from the connection's school.

    `services._require_authority()` already refuses an unauthenticated actor
    with a readable message and reads the school off the connection rather than
    taking a second opinion about which school this is.

    **`step` is a fragment, not a sentence**, and it has to read into that
    function's two templates: *{actor} may not {step} results at {school}.* and
    *Signing in is required to {step} results.* The existing callers pass
    `revise` and `open a sheet for` for exactly that reason. A fragment naming
    its own object — *withhold a report card at* — produces "may not withhold a
    report card at results at St Mary's", which is the refusal arriving as
    gibberish at the person least able to act on it.
    """
    return _require_authority(actor, WITHHOLDING_ROLES, step)


def _require_student_of_this_school(student_membership_id: int) -> Membership:
    """Refuse a membership that is not a student here, before anything is written.

    **This is what earns the bare `student_membership_id`.** The column carries
    no foreign key (`docs/tenancy.md`), so it accepts any integer — a teacher's
    membership, a child at another school, or simply the wrong child at this
    one. Nothing about the row would look wrong afterwards: it would sit in St
    Mary's tables and name a child St Mary's has never taught.

    It matters more here than at most call sites, because this table is
    **append-only in three places** — `save()`, `delete()` and a Postgres
    trigger. A withholding written against the wrong child cannot be corrected,
    only masked by appending a `lifted` row beside it, and in the
    wrong-child-same-school case the mistake silently holds a paid family's card
    until somebody notices.

    The rule lives in `accounts.students.why_not_a_student_here()`, which every
    tenant app that stores a bare student id already asks — `fees.services`,
    `gradebook.services`, `academics.services`, `results.comments`,
    `results.sessions`, `results.ratings`. What stays here is the raising, so
    that `except ResultsError` still means "the decision was not recorded".
    """
    membership = (
        Membership.objects.select_related("school", "user")
        .filter(pk=student_membership_id)
        .first()
    )
    if membership is None:
        raise NotThisSchoolsStudent(
            f"There is no membership {student_membership_id}. A withholding is "
            f"keyed on a student's STUDENT membership, which is what pins both "
            f"the child and their school."
        )

    reason = why_not_a_student_here(
        membership, subject="a withholding", holder="report cards"
    )
    if reason:
        raise NotThisSchoolsStudent(reason)
    return membership


def _balance_now(student_membership_id: int) -> Optional[int]:
    """Everything this child owes, in kobo, at this instant.

    **Not this term only.** A child carrying arrears from last term is exactly
    who a school withholds over, so there is no `for_term()` here.

    `fees` is imported inside the function — see the module docstring. The
    alternative was a `balance_kobo` parameter passed in by the bursar's screen,
    which removes the coupling entirely and was rejected: the number on an audit
    row would then be the caller's word rather than the books', which is the one
    thing that row exists to prevent.

    **`None` where the ledger has no entry for this child at all**, which is
    what makes the nullable column mean what it says. `balance()` ends
    `... or 0` (`fees/models.py`), so it answers `0` for a child with no rows —
    and returning that would write "this family owed nothing" onto the audit of
    a school that keeps its fees on paper and has never posted an entry. The
    column's own docstring refuses that reading: a decision can be recorded
    where the ledger has nothing to say, and naming a fictional zero is a claim
    nobody made. A real zero — charged and paid in full — still writes `0`, and
    the two are different facts.
    """
    from fees.models import FeeLedgerEntry

    entries = FeeLedgerEntry.objects.for_student(student_membership_id)
    if not entries.exists():
        return None
    return entries.balance()


def withhold(student_membership_id: int, term, *, actor, reason: str) -> WithholdingDecision:
    """Hold this child's card back from the family, and say why.

    `reason` is required, and refused here with a sentence as well as by the
    constraint — the constraint is what holds it, this is what a person can act
    on.
    """
    _require_withholding_authority(actor, "withhold")
    if not reason or not reason.strip():
        raise WithholdingError(
            "A withholding has to say why. The reason is staff-only — it is "
            "never shown to the family — and it is what the next person to "
            "look at this child reads."
        )
    return _record(
        student_membership_id,
        term,
        status=WithholdingStatus.WITHHELD,
        reason=reason,
        actor=actor,
    )


def lift(student_membership_id: int, term, *, actor, reason: str = "") -> WithholdingDecision:
    """Let this child's card go to the family. A second row; the first stands.

    `reason` is optional, unlike `withhold()`. A school that has been paid does
    not owe an explanation for handing over the card it was always going to
    hand over.
    """
    _require_withholding_authority(actor, "release withheld")
    return _record(
        student_membership_id,
        term,
        status=WithholdingStatus.LIFTED,
        reason=reason,
        actor=actor,
    )


def _record(student_membership_id, term, *, status, reason, actor) -> WithholdingDecision:
    """One row, with the books' own number frozen onto it.

    No lock and nothing to race on, which is worth stating so the absence reads
    as a decision. `fees.reverse_entry()` locks because it defends an
    at-most-once rule; there is no such rule here. Two people deciding at the
    same instant write two rows, both stand, and the ordering resolves which
    holds.
    """
    _require_student_of_this_school(student_membership_id)
    return WithholdingDecision.objects.create(
        student_membership_id=student_membership_id,
        # `term_id=`, and a `Term` or its id either way, so that the write side
        # takes what `latest_decision()` documents itself as taking. The read
        # path deliberately accepts `card.term_id` — a column the serving path
        # already holds — and a caller who read that signature and passed the
        # same value to `withhold()` would otherwise be told
        # `must be a "Term" instance` by the write it never saw coming.
        term_id=getattr(term, "pk", term),
        status=status,
        reason=reason,
        balance_kobo_at_decision=_balance_now(student_membership_id),
        decided_by_id=getattr(actor, "pk", None),
    )


__all__ = [
    "WITHHOLDING_ROLES",
    "CardWithheld",
    "NotThisSchoolsStudent",
    "WithholdingError",
    "is_withheld",
    "latest_decision",
    "lift",
    "set_policy",
    "set_policy_as",
    "settings",
    "withhold",
]
