"""Taking a child off the roll mid-session. Audit finding G-16.

Before this, a child who left in October stayed on the roll and in their class
until the end-of-session promotion: counted in the class size, listed as
unmarked at every release, charged by every bill applied to the class, and sent
fee reminders. The only callers of `release_student()` were promotion and the
onboarding reset.

## The act

`take_off_the_roll_as(actor, student, reason=..., left_on=...)`, in one
transaction:

1. **The principal's decision**, and nobody else's: `PRINCIPAL` at the child's
   school, with access. Not the administrator, who admits; not platform staff.
   A child leaving is a decision about the child, like promotion.
2. **A reason, and a day**: the reason is required (and the table refuses a
   blank one); the day defaults to today, may not be in the future, and may not
   be before the enrolment started.
3. **Out of every class of every term they had not finished.** Each placement in
   a term that had not ended by the day they left is removed, so they are on no
   roster from then on: not in the class size, not on a register, not charged by
   a bill, not reminded about fees, not "left out" of a release. **Except** a
   term whose card went home to them (`results.cards.a_card_went_home()`): that
   placement is what the card was reckoned from and it stays. Placements in
   terms already over are untouched; they are where the child sat. Refused,
   with nothing written, while a class they would leave has results with a
   signatory (submitted, checked or approved: F-01's rule, the same guard a
   move meets).
4. **The enrolment ends** (`release_student(..., keep_family_access=True)`):
   the membership is ended, never deleted, and the guardian links are kept.
5. **The family keeps its way in.** A guardian's PARENT membership is left as it
   was, so the cards that went home stay readable (`card_api` serves an ended
   child's released cards to their guardian) and nothing they could read before
   is taken away. Their marks, attendance, ledger and past placements are rows
   nobody deletes.
6. **Written down**: a `Departure` row, append-only, carrying who decided, the
   day, the reason, the child's name and each class and term they were taken
   out of (`docs/operating-rules.md` rule 8: an act that leaves an absence needs
   its own record).

What it does not do: move the child to another Classnode school. That is the
transfer handshake, which has no route yet (`accounts/transfers.py`, and the
reasons in `docs/membership.md`).
"""

from datetime import date

from django.db import connection, transaction
from django.utils import timezone

from accounts.models import Membership, Role

from .models import ClassPlacement, Departure
from .services import AcademicsError, _require_results_not_in_the_chain

#: The longest reason kept; a paragraph, not an essay.
MAX_REASON = 1000


class LeavingRefused(AcademicsError):
    """The child cannot be taken off the roll as asked. The sentence says why."""


class NotThePrincipal(LeavingRefused):
    """Only the principal of the child's school takes a child off the roll."""


def may_take_off_the_roll(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return Role.PRINCIPAL.value in set(actor.roles_at(school))


def _the_day(left_on, student) -> date:
    today = timezone.localdate()
    if left_on is None:
        return today
    if isinstance(left_on, str):
        try:
            left_on = date.fromisoformat(left_on)
        except ValueError:
            raise LeavingRefused(f"{left_on!r} is not a date.") from None
    if left_on > today:
        raise LeavingRefused("The day they left cannot be after today.")
    if student.started_on and left_on < student.started_on:
        raise LeavingRefused(
            f"The day they left cannot be before they joined, on {student.started_on:%d %B %Y}."
        )
    return left_on


@transaction.atomic
def take_off_the_roll_as(actor, student, *, reason, left_on=None) -> Departure:
    """End `student`'s enrolment here on the principal's decision. Returns the record.

    The module docstring is the contract. Raises `NotThePrincipal`,
    `LeavingRefused`, or `ResultsInTheChain` (an `AcademicsError`), each with
    nothing written.
    """
    from accounts.services import release_student
    from results.cards import a_card_went_home

    school = student.school
    if not may_take_off_the_roll(actor, school):
        raise NotThePrincipal("A child is taken off the roll by the principal of the school.")
    if student.role != Role.STUDENT or school.schema_name != connection.schema_name:
        raise LeavingRefused("That is not a child on this school's roll.")

    # The row this changes, locked: two principals pressing at once write one
    # record, and the second is told the child has already left.
    student = (
        Membership.objects.select_for_update()
        .order_by()
        .select_related("user")
        .get(pk=student.pk)
    )
    student.school = school
    if not student.is_live:
        raise LeavingRefused(f"{student.name} has already left this school.")

    reason = " ".join((reason or "").split())
    if not reason:
        raise LeavingRefused("Say why they are leaving. The reason is kept with the record.")
    if len(reason) > MAX_REASON:
        raise LeavingRefused(f"Keep the reason under {MAX_REASON} characters.")
    day = _the_day(left_on, student)

    leaving = [
        placement
        # `of=("self",)`: lock the placements, not the terms and classes joined in.
        for placement in ClassPlacement.objects.select_for_update(of=("self",))
        .filter(student_membership_id=student.pk, term__ends_on__gte=day)
        .select_related("class_group", "term")
        .order_by("term__starts_on", "pk")
        if not a_card_went_home(student, placement.term)
    ]
    for placement in leaving:
        _require_results_not_in_the_chain(placement.term, placement.class_group_id)
    classes_left = "; ".join(f"{p.class_group.name}, {p.term}" for p in leaving)
    ClassPlacement.objects.filter(pk__in=[p.pk for p in leaving]).delete()

    release_student(student, on=day, keep_family_access=True)

    return Departure.objects.create(
        student_membership_id=student.pk,
        left_on=day,
        reason=reason,
        decided_by_id=actor.pk,
        student_name=student.name,
        classes_left=classes_left,
    )


__all__ = [
    "Departure",
    "LeavingRefused",
    "MAX_REASON",
    "NotThePrincipal",
    "may_take_off_the_roll",
    "take_off_the_roll_as",
]
