"""Applying a bill to a class: forty-five children charged in one transaction.

One public function. It takes a `FeeSchedule` — the template — and posts the
CHARGE entries it describes, plus a DISCOUNT for every active concession the
children on that roster hold.

Four decisions shape it, and each of them is a bug this codebase has already
paid for once.

**Idempotent by skipping, not by refusing.** Re-running is the normal case, not
the error case: a school charges in week one, three children are admitted in
week three, and somebody clicks the same button again. So a child who already
has this line's charge is skipped, and the bursar is told "42 skipped, 3
charged" rather than handed an `IntegrityError`. The unique indexes on
`FeeLedgerEntry` are the backstop for the race; this is the mechanism for the
ordinary case, and the difference between the two is the difference between a
readable result and a stack trace.

**One roster read.** Issue #43 is the lesson: a release read the roster four
times, the office committed a placement between two of them, and the release
died. The hazard is smaller here — there is no dependent write chain — but "who
is being billed" is a question that should be decided once, and a second read is
a second answer. The roster is read once and reused for both the charges and the
concessions.

**Locked on the schedule row.** Two bursars clicking "Charge JSS 1A" at the same
instant both pass an unlocked skip-check before either commits, which is
`reverse_entry()`'s race exactly. `select_for_update()` on the schedule
serialises applications of *that bill* and nothing else.

**And "nothing else" is a real limit, not a boast.** The charge key is a line,
and a line belongs to one bill, so every charge collision is inside the bill this
lock holds. The *concession* key spans the term, so two runs of two different
bills can collide on it — see the `IntegrityError` handled at the foot of
`apply_to_class()`, which is the only place this module treats a database refusal
as an outcome rather than a bug.

**One transaction for the whole class**, because a half-applied bill is worse
than no bill: nobody can tell by looking whether it finished, and the repair is
to work out which children were reached. A class is bounded, so the transaction
is bounded.

**No run table**, and this is `docs/operating-rules.md` rule 8 read forwards.
Who applied a bill and when is already on every entry it produced —
`recorded_by_id`, `effective_on`, `recorded_at`, `source_line`. A run row would
be a second answer to a question the entries already answer, and the two would
eventually disagree.

`academics` is read directly rather than through `results.positions`: `fees` has
no business importing `results`, and `academics` sits under both.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from academics.models import ClassPlacement
from accounts.models import Membership

from . import services
from .models import FeeConcession, FeeEntryKind, FeeLedgerEntry, FeeSchedule


#: The index a concurrent application of a *different* bill can trip.
_CONCESSION_COLLISION = "a_concession_discounts_a_child_once_per_term"

#: Postgres' unique violation. `academics.services` and `gradebook.services`
#: both check this alongside the name; `accounts.throttling` checks the name
#: alone. This is the stricter of the two forms, deliberately — see below.
_UNIQUE_VIOLATION = "23505"


def _is_the_concession_colliding(exc) -> bool:
    """Did another bill in this term post this discount, or did something else fail?

    Asked of the failure itself, on `accounts.throttling`'s idiom: Postgres names
    the constraint that refused the row, and inferring it from "is there a row
    now?" is wrong in both directions under concurrency. A cause carrying no
    diagnostics counts as *not* a collision, so an unrecognised failure is raised
    rather than swallowed.

    **Both halves, `pgcode` and the name**, which is the form `academics` and
    `gradebook` use and the one this copy should have started as. The name alone
    would also accept a *non*-unique failure that happened to cite this index —
    a deferred check or a future exclusion constraint carrying the same name —
    and the whole point of the narrowing is that only the one known race is a
    skip. Four copies of this predicate now exist with two definitions between
    them; consolidating them is issue #81, and until then the stricter form is
    the one a fifth caller should copy.
    """
    cause = getattr(exc, "__cause__", None)
    diag = getattr(cause, "diag", None)
    return (
        getattr(cause, "pgcode", None) == _UNIQUE_VIOLATION
        and getattr(diag, "constraint_name", None) == _CONCESSION_COLLISION
    )


class EmptySchedule(services.FeeLedgerError):
    """A bill with no lines was applied to a class.

    Refused rather than reported as "0 charged", because a silent no-op is the
    failure this project keeps finding: a bursar who has not finished itemising
    the bill clicks Charge, sees no error, and believes the class has been
    billed. The refusal names the thing to fix.

    Note it is asked *before* concessions, so an unitemised bill cannot post
    discounts against charges that were never raised.
    """


class UnknownStudent(services.FeeLedgerError):
    """The roster names a membership that no longer exists.

    A placement pointing at a missing membership is a broken invariant rather
    than an ordinary skip, and it is refused for the reason the whole run is one
    transaction: a bill applied to most of a class, with one child silently
    absent from it, is the state nobody can detect by looking.
    """


@dataclass(frozen=True)
class AppliedSummary:
    """What one application did, in the terms a bursar's screen reports it.

    Counts of *entries*, not of children: a bill with three lines charges one
    child three times, and "3 charged" against a one-child class is the honest
    number for what was posted.
    """

    students: int
    #: On the roster but not billed, their membership having ended. Counted so
    #: that the skip is reported rather than silent — see `apply_to_class()`.
    students_skipped: int
    lines: int
    charges_posted: int
    charges_skipped: int
    charged_kobo: int
    discounts_posted: int
    discounts_skipped: int
    discounted_kobo: int

    def __str__(self):
        left = (
            f"; {self.students_skipped} no longer enrolled"
            if self.students_skipped
            else ""
        )
        return (
            f"{self.charges_posted} charged, {self.charges_skipped} skipped; "
            f"{self.discounts_posted} discounts, {self.discounts_skipped} skipped"
            f"{left}"
        )


@transaction.atomic
def apply_to_class(schedule, *, by, effective_on=None) -> AppliedSummary:
    """Post this bill to everyone on the class's roster for its term.

    `by` is the user doing it, and it lands on every entry as `recorded_by_id`.
    `effective_on` is the date the entries count for, defaulting to today — a
    bill typed in on Monday for a term that began on Friday belongs to Friday,
    which is the distinction `FeeLedgerEntry.effective_on` exists for.

    Returns an `AppliedSummary`. Raises `EmptySchedule` for a bill with no lines,
    `UnknownStudent` for a roster naming a membership that has gone, and
    `NotThisSchoolsStudent` for one naming a child of another school — all of
    them subclasses of `FeeLedgerError`, so `except FeeLedgerError` still means
    "nothing was posted".
    """
    # The lock first, before anything is read that a concurrent run could
    # change. **No `select_related()` here**: `select_for_update()` locks every
    # table it joins, so pulling `term` and `class_group` into this query would
    # have a billing run holding locks on rows it never writes. They are fetched
    # separately below, unlocked, which is the point.
    locked = FeeSchedule.objects.select_for_update().get(pk=schedule.pk)

    lines = list(locked.lines.all())
    if not lines:
        raise EmptySchedule(
            f"{locked} has no lines, so applying it would charge nobody "
            f"anything. Add what the class is being billed for first."
        )

    term = locked.term
    class_group = locked.class_group

    # Read once, reused by both halves. `student_ids()` returns the ids in the
    # placement table's own order; the sort makes the run deterministic, which
    # is what lets two runs of the same bill be compared entry for entry.
    student_ids = sorted(ClassPlacement.objects.student_ids(class_group, term))

    # `order_by()` rather than inheriting `Membership.Meta`, whose ordering is
    # `["school__name", "role", "user__full_name"]` — two relations, which
    # compile to an INNER JOIN on `schools_school` and another on `accounts_user`
    # for a lookup that wants neither. docs/membership.md records the sharper
    # version of the same fact: those joins under a `FOR UPDATE` put an exclusive
    # lock on rows the query never writes. There is no lock here, so this is only
    # two joins of waste — but the fix is the same one word either way. The dict
    # discards order anyway, so the ordering is cleared rather than replaced.
    #
    # `select_related("user", "school")` because both are read per child and
    # neither is optional: `snapshot_student()` reads `membership.name`, which
    # falls through to `user.full_name` whenever `display_name` is blank — its
    # default — and `why_not_a_student_here()` reads `school.schema_name`. Lazily
    # that is two queries per child, ninety for a class of forty-five, every one
    # of them inside the transaction holding the schedule lock. Joined once here
    # it is the same two joins the paragraph above declines to pay per *sort*,
    # paid once for a thing actually needed.
    # **What this read must not lose is `status`, and that is not the join.**
    # The skip below is `memberships[sid].is_live` -- a Python property that
    # returns `self.status in LIVE_STATUSES` and reads nothing else. So
    # `select_related()` buys queries here and not correctness: take it away and
    # every leaver test stays green. Take away the *loaded* `status` -- an
    # `.only()` or a `.defer("status")` added by someone tightening this read --
    # and the property becomes a lazy refetch of a row this function has already
    # read, issued later and inside the schedule lock. The decision is then taken
    # on the later of two reads that can disagree, and a child who was enrolled
    # when the roster was read is silently dropped from the bill: no error, no
    # row, nobody the wiser until a parent asks why no invoice came.
    #
    # This is written out because the instinct when hardening a read is to reach
    # for `select_related` first, which would leave the actual guard untouched.
    # `LeaverReadTests` pins it, and its control is that exact failure.
    memberships = {
        m.pk: m
        for m in Membership.objects.filter(pk__in=student_ids)
        .select_related("user", "school")
        .order_by()
    }
    missing = [sid for sid in student_ids if sid not in memberships]
    if missing:
        raise UnknownStudent(
            f"{class_group} has placements naming memberships that no longer "
            f"exist: {missing}. The roster has to name real students before the "
            f"class can be billed."
        )

    # **A child whose membership has ended is not billed**, and this is the same
    # call `academics.services` already made. `place_student()` deliberately
    # allows an ended child to be placed — entering last term's roster after the
    # fact is real work and those children have often left — and its docstring
    # says why the automated path must not follow: it is the one "that would
    # repeat such a mistake silently across a whole school".
    # `carry_forward_placements()` filters them out and calls that "a correctness
    # rule and not a tidiness one". Applying a bill is the same kind of path:
    # nothing deletes a `ClassPlacement` when a membership ends, so a child
    # released in December is still on JSS 1A's roster in January, and a bursar
    # adding one line to that term's bill and re-running would charge them.
    #
    # Skipped rather than refused, because refusing is the forty-five-children
    # outcome again: one child having left must not stop the class being billed.
    # Counted, though — `students_skipped` — because a skip nobody is told about
    # is the silent no-op this module refuses everywhere else.
    # Decided from the read above, whose `status` is loaded -- see that comment
    # for why the loading, and not the join, is what makes this correct.
    billable_ids = [sid for sid in student_ids if memberships[sid].is_live]
    students_skipped = len(student_ids) - len(billable_ids)
    student_ids = billable_ids

    # Both skip-sets in one query each, and both are read *after* the lock, so a
    # concurrent application of this bill has either not started or has finished.
    # `order_by()` with no arguments on both: these collapse into a `set()`, and
    # `FeeLedgerEntry.Meta.ordering` would otherwise have Postgres sort every
    # matching row by `-effective_on, -id` for an answer that discards the order.
    already_charged = set(
        FeeLedgerEntry.objects.filter(
            kind=FeeEntryKind.CHARGE,
            source_line__in=lines,
            student_membership_id__in=student_ids,
        )
        .order_by()
        .values_list("student_membership_id", "source_line_id")
    )

    # **`order_by()` explicitly, because this one carries a concurrency
    # guarantee.** Two runs of two *different* schedules in one term can both
    # reach the same `(child, term, concession)` row — that is the collision the
    # foot of this function handles. If they reach *several* such rows in
    # different orders, Postgres does not hand back a unique violation; it hands
    # back a deadlock, SQLSTATE `40P01`, which arrives as `OperationalError` and
    # not as `IntegrityError`. The handler below cannot see it, so the loser's
    # whole transaction dies and the class goes unbilled — the outcome the skip
    # exists to prevent, reached by the one route the skip cannot cover.
    #
    # A total order shared by every run is what makes the cycle impossible. That
    # order is `FeeConcession.Meta.ordering` and this queryset inherited it
    # silently, so the guarantee held by accident and one `Meta` edit would have
    # removed it with nothing going red. Named here, and pinned by
    # `test_the_concession_read_is_ordered_so_two_bills_cannot_deadlock`.
    concessions = list(
        FeeConcession.objects.filter(
            is_active=True, student_membership_id__in=student_ids
        ).order_by("student_membership_id", "id")
    )
    already_discounted = set(
        FeeLedgerEntry.objects.filter(
            kind=FeeEntryKind.DISCOUNT,
            term=term,
            source_concession__in=concessions,
            student_membership_id__in=student_ids,
        )
        .order_by()
        .values_list("student_membership_id", "source_concession_id")
    )

    charges_posted = charges_skipped = charged_kobo = 0
    discounts_posted = discounts_skipped = discounted_kobo = 0

    # **This loop opens a savepoint per entry, and that is filed, not fixed.**
    # `services.charge()` is `@transaction.atomic`, so a 45-child three-line bill
    # opens ~135 subtransactions inside this one transaction -- past the 64 that
    # Postgres caches per backend, after which visibility checks fall back to
    # `pg_subtrans` SLRU lookups and the cost is paid cluster-wide, by every
    # school, for as long as this transaction stays open. The savepoints are
    # load-bearing for the *discount* loop below, whose collision handler needs
    # to roll back to one; for charges they buy nothing. Issue #82,
    # `must-fix-before-pilot` -- it changes how charges post, so it is a design
    # decision rather than a patch.
    for student_id in student_ids:
        membership = memberships[student_id]
        for line in lines:
            if (student_id, line.pk) in already_charged:
                charges_skipped += 1
                continue
            services.charge(
                membership,
                term,
                line.amount_kobo,
                # Copied, not joined to. The line is an editable template and
                # this is the record: renaming "PTA levy" next year must not
                # relabel a charge already posted. `docs/operating-rules.md`
                # rule 2.
                narration=line.description,
                effective_on=effective_on,
                recorded_by=by,
                source_line=line,
            )
            charges_posted += 1
            charged_kobo += line.amount_kobo

    for concession in concessions:
        key = (concession.student_membership_id, concession.pk)
        if key in already_discounted:
            discounts_skipped += 1
            continue
        try:
            services.discount(
                memberships[concession.student_membership_id],
                term,
                concession.amount_kobo,
                narration=concession.reason,
                effective_on=effective_on,
                recorded_by=by,
                source_concession=concession,
            )
        except IntegrityError as collision:
            # **The one race the schedule lock does not cover.** That lock
            # serialises applications of *this bill*; the concession index spans
            # every bill in the term. A child who moves class mid-term can be on
            # one bursar's roster snapshot and another's at the same moment — the
            # `ClassPlacement` rewrite window issue #43 records — so two runs of
            # two *different* schedules can both pass this skip-check and both
            # post the same child's discount.
            #
            # Without this, the loser's whole run dies: one transaction for the
            # class means forty-five children go unbilled because one discount
            # collided, which is the outcome the skip exists to prevent.
            #
            # Treated as a skip, because that is what it is — somebody else
            # posted it, and the child has their concession either way.
            # `services.discount()` is itself atomic, so the failure rolls back
            # to its savepoint and this transaction stays usable.
            #
            # **The narrowing is complete for this path, not merely for the case
            # that was found.** Of the ten constraints on `FeeLedgerEntry`,
            # exactly one is reachable from a concession discount: the amount is
            # a checked magnitude and always negative, `kind` is DISCOUNT,
            # `reverses` is null, and `source_line` is null — which satisfies
            # every other check and excludes this row from every other partial
            # index. What is left is a foreign-key failure, which means the
            # concession was deleted underneath us, and that is not a skip: the
            # predicate refuses it and the run dies, which is correct.
            #
            # Ten and not eleven. The eleventh refusal that table can produce is
            # `fees_ledger_append_only`, migration `0002` — a **trigger** and not
            # a constraint, which is not a quibble here: it fires `BEFORE UPDATE
            # OR DELETE` and this is an INSERT, so it is unreachable from this
            # path. Were it ever to fire it raises `ERRCODE = restrict_violation`
            # with no `constraint_name` at all, which the predicate reads as "not
            # a collision" and re-raises — right, and for a reason worth keeping
            # separate from the count.
            if not _is_the_concession_colliding(collision):
                raise
            discounts_skipped += 1
            continue
        discounts_posted += 1
        discounted_kobo += concession.amount_kobo

    return AppliedSummary(
        students=len(student_ids),
        students_skipped=students_skipped,
        lines=len(lines),
        charges_posted=charges_posted,
        charges_skipped=charges_skipped,
        charged_kobo=charged_kobo,
        discounts_posted=discounts_posted,
        discounts_skipped=discounts_skipped,
        discounted_kobo=discounted_kobo,
    )


__all__ = ["AppliedSummary", "EmptySchedule", "UnknownStudent", "apply_to_class"]
