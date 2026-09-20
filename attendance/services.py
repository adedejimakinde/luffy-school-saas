"""Taking a register, amending one, and reading what a group was marked.

**The interaction decides the shape of everything here.** Forty-five students in
under thirty seconds is two thirds of a second each, which rules out a screen
where every child is touched and rules out the write pattern this codebase
currently has — `gradebook.save_score()` is one mark per request, "what a blur
calls", and forty-five conditional PUTs on a phone is not a register, it is a
network test.

So a register opens with the roster present and the teacher taps the absentees.
`take_register()` takes the absentees and the roster the screen was showing, and
writes the whole register in one transaction.

## The roster the screen showed is not necessarily the roster now

A child placed or moved between the screen loading and the teacher submitting is
a real event, and there are three ways it bites:

- a child **appeared** on the roster after the screen loaded. Nobody looked at
  her. Marking her present would invent an observation, and `AttendanceStatus`
  is explicit that this system does not do that, so she is left unmarked and
  named in the answer.
- a child **vanished** from the roster. Whatever the screen showed, she is not
  in this group now, so nothing is written for her.
- an absentee **is not on the roster at all** — tapped, then moved out. Writing
  that mark would file attendance for a child this group no longer has, so it
  is refused for that child alone and named in the answer.

None of the three is an error. They are all reports, because a teacher standing
in front of a class should not have a register refused wholesale over one child
the office moved while they were marking.
"""

from dataclasses import dataclass, field
from datetime import date as date_type

from django.db import IntegrityError, transaction
from django.utils import timezone

from academics.models import ClassPlacement
from accounts.models import Role

from .models import AttendanceMark, AttendanceStatus, Register


class AttendanceError(Exception):
    """Something refused to write a register. The base of every refusal here."""


class NotAllowedToMarkAttendance(AttendanceError):
    """The actor holds no role at this school that may take a register.

    Under `AttendanceError` like every other refusal, so `except
    AttendanceError` still means "nothing was written". Callers that need to
    tell a refusal of *authority* from a refusal of *state* — an HTTP layer
    choosing between 403 and everything else — catch this one first, which is
    the shape `gradebook.services.NotAllowedToMark` set.
    """


class DayOutsideTheTerm(AttendanceError):
    """The date is not inside the term the register was filed under.

    **This rule cannot be a database constraint and the absence is a decision,
    not an oversight.** A `CheckConstraint` on `attendance_register` cannot
    reference `academics_term.starts_on`, because a check constraint sees one
    row of one table. So it lives here, with its own name, and
    `docs/attendance.md` says so rather than implying a guarantee the schema
    does not give — this repository has made the opposite mistake before, and a
    bound stated in prose with nothing behind it is the mistake.
    """


class NoRoster(AttendanceError):
    """The group has nobody placed in it for this term, so there is no register.

    Separate from an empty submission: a register with every child present is
    forty-five marks, and a register for a group with no children is not a
    register at all. Writing an empty `Register` row would record that somebody
    marked nothing, which is indistinguishable from the admin gap `days_open`
    exists to measure.
    """


#: Roles that may take a register at their own school.
#:
#: The same set as `gradebook.services.MARK_ENTERING_ROLES` and for the same
#: argument. A teacher marks the children in front of them; a principal and an
#: administrator are here because entering a week of paper registers is office
#: work in most schools, and a system that refused it would be worked around
#: with a borrowed teacher login — which is strictly worse, because then
#: `taken_by_id` names the wrong person on every row it touches.
#:
#: The load-bearing half is who is absent. A bursar keeps the books and does not
#: mark; a parent and a student are the *subjects* of this data, and a STUDENT
#: membership is the very thing an `AttendanceMark` is keyed on.
MARKING_ROLES = frozenset(
    {Role.TEACHER.value, Role.PRINCIPAL.value, Role.ADMIN.value}
)


@dataclass(frozen=True)
class RegisterTaken:
    """What a register write actually did, which is more than "ok".

    Four lists rather than a count, because each one is a different sentence a
    teacher may need to read, and a screen that showed only a total could not
    tell them apart. `appeared` and `not_on_the_roster` are the two that need
    saying out loud; `present` and `absent` are what was written.
    """

    register: Register
    present: list[int] = field(default_factory=list)
    absent: list[int] = field(default_factory=list)
    #: On the roster now, not on the screen then, and therefore **not marked**.
    appeared: list[int] = field(default_factory=list)
    #: Submitted as absent, not on the roster now. Nothing written for them.
    not_on_the_roster: list[int] = field(default_factory=list)

    @property
    def marked(self) -> int:
        return len(self.present) + len(self.absent)


def _stamp(by):
    """A user, a pk, or None — all three spellings a caller might reach for."""
    return getattr(by, "pk", by)


# There is no `_require_student_of_this_school()` here, and its absence is the
# decision rather than the omission. Every other table following the bare-id
# policy takes a membership from its caller and must check it — `gradebook.Score`
# and `academics.ClassPlacement` both do. This one never writes an id a caller
# supplied: `take_register()` intersects the submission with the roster, and the
# roster is `ClassPlacement`, whose rows `academics.services.place_student()`
# already checked. An id that is not a student of this school cannot reach a
# mark, because it cannot survive the intersection. That is a stronger guarantee
# than a check and it is why `not_on_the_roster` is a report rather than a raise.


def _require_the_day_is_in_the_term(term, on):
    if not (term.starts_on <= on <= term.ends_on):
        raise DayOutsideTheTerm(
            f"{on} is not inside {term}, which runs {term.starts_on} to "
            f"{term.ends_on}. A register belongs to the term it was taken in."
        )


def roster_ids(class_group, term) -> list[int]:
    """Who to show the teacher: the group's roster **as it stands now**.

    Deliberately `ClassPlacement` and deliberately live. This is the one
    question that table is the right answer to — see `Register` for the one it
    is the wrong answer to.
    """
    return ClassPlacement.objects.student_ids(class_group, term)


def register_for(class_group, on, period) -> Register | None:
    """The register for one group, one day, one period, or None."""
    return Register.objects.filter(
        class_group=class_group, taken_on=on, period=period
    ).first()


def day_registers(class_group, on):
    """Every period taken for this group on this date, earliest first."""
    return Register.objects.on_day(class_group, on)


def group_that_marked(mark) -> int:
    """Which class group took this mark. **The register's, never the placement's.**

    One line, and it exists so that D2 is a branch something can be aimed at
    rather than a property of a column that no test can break. The rejected
    design is exactly one substitution away — `placement_of(...).class_group_id`
    — and it reads identically until a child moves, which is the whole failure:
    a mark taken in JSS 1A in September, filed under JSS 1B because she moved in
    October, silently, against a number already printed on a card.

    Slice 2 needs this accessor anyway; the summary groups a term's marks by the
    group that took them.
    """
    return mark.register.class_group_id


def marks_in(register) -> dict[int, str]:
    """`student_membership_id -> status` for one register."""
    return dict(
        AttendanceMark.objects.filter(register=register).values_list(
            "student_membership_id", "status"
        )
    )


@transaction.atomic
def take_register(
    class_group,
    term,
    *,
    on: date_type,
    period: int = 1,
    absent_ids=(),
    shown_ids=None,
    by=None,
) -> RegisterTaken:
    """Mark a whole group for one period of one day. Returns what was written.

    `absent_ids` is what the teacher tapped. Everyone else on the roster they
    were shown is present — the default this whole screen is built around.

    `shown_ids` is the roster the screen was displaying. `None` means "whatever
    the roster is now", which is the right default for a caller with no screen
    behind it — an import, a test, a shell — and the wrong one for a phone,
    which knows exactly which forty-five names it drew and should say so.

    **Taking a register that already exists amends it.** That is not a second
    register: `one_register_per_group_per_period` forbids one, and a teacher who
    submits twice because the first answer was slow has not taken two registers.
    The row is locked for the duration so that two submissions racing serialise
    rather than interleaving into a half-amended register.
    """
    _require_the_day_is_in_the_term(term, on)

    roster = roster_ids(class_group, term)
    if not roster:
        raise NoRoster(
            f"Nobody is placed in {class_group} for {term}, so there is no "
            f"register to take. Place the children first."
        )

    roster_set = set(roster)
    absent_set = set(absent_ids)
    shown = roster_set if shown_ids is None else set(shown_ids)

    looked_at = roster_set & shown
    absent = sorted(absent_set & looked_at)
    present = sorted(looked_at - absent_set)
    appeared = sorted(roster_set - shown)
    not_on_the_roster = sorted(absent_set - roster_set)

    register = _locked_register(class_group, term, on, period, by)
    _write_marks(register, present, absent, by)

    return RegisterTaken(
        register=register,
        present=present,
        absent=absent,
        appeared=appeared,
        not_on_the_roster=not_on_the_roster,
    )


def _locked_register(class_group, term, on, period, by) -> Register:
    """The register row for this slot, created if new, locked either way.

    `select_for_update()` on the existing row and the unique constraint on the
    insert are two halves of one answer: the lock serialises amendments to a
    register that exists, and the constraint is what stops two first-takes both
    landing. A caller that raced and lost re-reads under the lock rather than
    failing, because losing that race means somebody else created exactly the
    row this one wanted.
    """
    existing = (
        Register.objects.select_for_update()
        .filter(class_group=class_group, taken_on=on, period=period)
        .first()
    )
    if existing is not None:
        return existing

    try:
        with transaction.atomic():
            return Register.objects.create(
                class_group=class_group,
                term=term,
                taken_on=on,
                period=period,
                taken_by_id=_stamp(by),
            )
    except IntegrityError as exc:
        if not _is_a_duplicate_register(exc):
            raise
        return (
            Register.objects.select_for_update()
            .filter(class_group=class_group, taken_on=on, period=period)
            .get()
        )


def _is_a_duplicate_register(exc) -> bool:
    """Was this the unique constraint on the register, and not another one?

    Named rather than caught on `IntegrityError` alone, for the reason issue
    #89 is about: the bare class cannot say *which* rule refused, so recovering
    on it would swallow a foreign key violation and a not-null exactly the way
    it swallows the collision this is meant to recover from.
    """
    return "one_register_per_group_per_period" in str(exc)


def _write_marks(register, present, absent, by):
    """Insert what is new and update only what actually changed.

    Three queries rather than one `update_or_create()` per child, because per
    child is forty-five round trips inside a lock. No lock is taken here: the
    `Register` row above is already locked for the whole transaction, and every
    writer of these marks has to pass through it, so a second lock on the marks
    would be one this codebase has twice decided it does not need. Rows whose status is already
    what the submission says are left alone entirely: re-submitting an unchanged
    register should not touch `updated_at` on forty-five rows and should not
    make a no-op look, in the audit, like somebody re-marked the class.
    """
    marked_by_id = _stamp(by)
    wanted = {sid: AttendanceStatus.PRESENT.value for sid in present}
    wanted.update({sid: AttendanceStatus.ABSENT.value for sid in absent})

    existing = {
        mark.student_membership_id: mark
        for mark in AttendanceMark.objects.filter(
            register=register, student_membership_id__in=list(wanted)
        )
    }

    new_rows = [
        AttendanceMark(
            register=register,
            student_membership_id=sid,
            status=status,
            marked_by_id=marked_by_id,
        )
        for sid, status in wanted.items()
        if sid not in existing
    ]
    changed = []
    for sid, status in wanted.items():
        mark = existing.get(sid)
        if mark is not None and mark.status != status:
            mark.status = status
            mark.marked_by_id = marked_by_id
            changed.append(mark)

    if new_rows:
        AttendanceMark.objects.bulk_create(new_rows)
    if changed:
        # `updated_at` is set by hand and listed, because **`bulk_update()` does
        # not run `pre_save`** and `auto_now` is implemented in `pre_save`. Left
        # to itself the column would never move, so every amendment to a
        # register would be invisible in the audit and "when was this last
        # touched" would answer with the day it was first taken.
        #
        # `academics.services.move_student()` carries the other half of this
        # note: `save(update_fields=...)` *does* run `pre_save`, so there the
        # field only has to be named. Two spellings, one of which is a silent
        # no-op, is exactly the trap `gradebook.services._update_the_mark_shown()`
        # was written to avoid.
        #
        # A control that makes this branch fire for unchanged rows is what
        # caught it: with `updated_at` left alone the control reddened nothing,
        # because the test it was aimed at was comparing a column the code could
        # not move.
        stamped_at = timezone.now()
        for mark in changed:
            mark.updated_at = stamped_at
        AttendanceMark.objects.bulk_update(
            changed, ["status", "marked_by_id", "updated_at"]
        )


@transaction.atomic
def discard_register(class_group, on, period) -> bool:
    """Take back a register taken for the wrong slot. True if a row went.

    Both tables, in the order `PROTECT` requires. Returns False rather than
    raising when there was nothing there, on the same reasoning as
    `academics.services.remove_placement()` and `gradebook.services.clear_score()`:
    the end state asked for is the end state that holds.

    This is not how a wrong *mark* is fixed — that is `take_register()` again,
    which amends. This is for a register filed against the wrong day or the
    wrong period, where every mark in it is about a lesson that did not happen.
    """
    register = (
        Register.objects.select_for_update()
        .filter(class_group=class_group, taken_on=on, period=period)
        .first()
    )
    if register is None:
        return False
    AttendanceMark.objects.filter(register=register).delete()
    register.delete()
    return True


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


def can_mark_attendance(actor, school) -> bool:
    """May `actor` take a register at `school`?

    Access-scoped like every other authority question in this codebase: an
    invited or suspended teacher has a membership and no authority, because
    `roles_at()` is scoped to ACCESS_STATUSES.

    Platform staff are **not** admitted, on the reasoning
    `gradebook.services.can_enter_marks()` and
    `academics.services.can_place_students()` both set out: marking a register
    is the school's own act, it is what a parent-facing number is computed from,
    and `taken_by_id` would name a platform operator on the row.
    """
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & MARKING_ROLES)


def _require_marking_authority(actor, school):
    if not can_mark_attendance(actor, school):
        raise NotAllowedToMarkAttendance(
            f"{actor} may not take a register at {school}. A register is taken "
            f"by a teacher, a principal or an administrator of the school."
        )


def take_register_as(actor, class_group, term, *, school, by=None, **kwargs):
    """`take_register()` for a caller with a request behind it."""
    _require_marking_authority(actor, school)
    return take_register(
        class_group, term, by=actor if by is None else by, **kwargs
    )


def discard_register_as(actor, class_group, *, school, on, period) -> bool:
    """`discard_register()` for a caller with a request behind it."""
    _require_marking_authority(actor, school)
    return discard_register(class_group, on, period)


__all__ = [
    "MARKING_ROLES",
    "AttendanceError",
    "DayOutsideTheTerm",
    "NoRoster",
    "NotAllowedToMarkAttendance",
    "RegisterTaken",
    "can_mark_attendance",
    "day_registers",
    "group_that_marked",
    "discard_register",
    "discard_register_as",
    "marks_in",
    "register_for",
    "roster_ids",
    "take_register",
    "take_register_as",
]
