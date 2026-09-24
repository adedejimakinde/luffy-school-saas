"""The rules for the bell schedule and the timetable. T1, decided 2026-09-24.

Every write goes through here, so an import and a management command meet the
same rules as the screen. The two that hold whoever writes are in the database
— periods do not overlap, and a teacher teaches one subject at a time — and this
module's job for those is to turn the refusal into a sentence that says what
clashed with what.

**Who** is asked here too, but only by the `*_as` functions and the API: a
management command has no actor. Admin and the vice principal (academic)
edit; every teacher, the principal, the vice principal and the administrator
read; everybody else gets the flat 404 at the API.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from academics.models import Term
from accounts.models import Membership, Role
from accounts.staff import why_not_a_teacher_here

from .models import Period, TimetableSlot

#: Who may read a timetable: every teacher, and the people who run the school.
READING_ROLES = frozenset(
    {
        Role.TEACHER.value,
        Role.PRINCIPAL.value,
        Role.VICE_PRINCIPAL_ACADEMIC.value,
        Role.ADMIN.value,
    }
)

#: Who may change the bell schedule and the timetable. Decided 2026-09-24.
EDITING_ROLES = frozenset({Role.ADMIN.value, Role.VICE_PRINCIPAL_ACADEMIC.value})


class TimetableError(Exception):
    """Base for every refusal here. The message is a sentence for the person
    who asked."""


class TeacherIsElsewhere(TimetableError):
    """The teacher is already teaching a different subject in that period —
    `a_teacher_teaches_one_subject_at_a_time`. The same subject is not a clash:
    that is one lesson given to two classes at once."""


class PeriodsOverlap(TimetableError):
    """`periods_do_not_overlap`, or a period that ends before it starts."""


class PeriodInUse(TimetableError):
    """A period some class has a lesson in cannot be removed. Clear the lessons
    first, so nobody's timetable loses a row without somebody deciding it."""


class NotThisSchoolsTeacher(TimetableError):
    """The membership is not a live TEACHER membership of this school."""


class NotTaughtHere(TimetableError):
    """The subject or the class is no longer in use at the school."""


class TimetableNotEmpty(TimetableError):
    """Copying last term fills an empty term and never writes over one."""


class NoEarlierTerm(TimetableError):
    """There is no term before this one to copy from."""


def _constraint_of(exc):
    cause = getattr(exc, "__cause__", None)
    return getattr(getattr(cause, "diag", None), "constraint_name", None)


# -- who ----------------------------------------------------------------------


def may_read(actor, school) -> bool:
    """Access-scoped, like every authority question here: an invited or
    suspended teacher reads nothing (`roles_at()`)."""
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & READING_ROLES)


def may_edit(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & EDITING_ROLES)


# -- the bell schedule --------------------------------------------------------


def _save_period(period):
    try:
        with transaction.atomic():
            period.save()
    except IntegrityError as exc:
        if _constraint_of(exc) in {"periods_do_not_overlap", "a_period_ends_after_it_starts"}:
            raise PeriodsOverlap(
                "A period has to end after it starts, and cannot overlap another "
                "period. Check the times against the rest of the day."
            ) from exc
        raise
    return period


def add_period(starts_at, ends_at, label=""):
    return _save_period(Period(starts_at=starts_at, ends_at=ends_at, label=label.strip()))


def change_period(period, *, starts_at, ends_at, label=""):
    """Moves the period for every term, past ones included: a timetable is a
    working record, and last term's lessons were in "Period 3" whatever time
    the bell now rings for it."""
    period.starts_at, period.ends_at, period.label = starts_at, ends_at, label.strip()
    return _save_period(period)


def remove_period(period):
    if TimetableSlot.objects.filter(period=period).exists():
        raise PeriodInUse(
            "Some class has a lesson in this period. Clear those lessons first, "
            "then remove the period."
        )
    period.delete()


# -- the timetable ------------------------------------------------------------


def _require_teacher(membership):
    reason = why_not_a_teacher_here(membership, subject="a timetabled lesson", holder="timetable")
    if reason:
        raise NotThisSchoolsTeacher(reason)
    if not membership.is_live():
        raise NotThisSchoolsTeacher(
            f"{membership.name} no longer teaches here, so cannot be timetabled."
        )
    return membership


def _clash_sentence(term, weekday, period, teacher_membership_id, subject):
    other = (
        TimetableSlot.objects.select_related("class_group", "subject")
        .filter(term=term, weekday=weekday, period=period, teacher_membership_id=teacher_membership_id)
        .exclude(subject=subject)
        .first()
    )
    if other is None:
        # The other row went between the refusal and this read. Still a clash.
        return "That teacher is teaching something else in that period."
    return (
        f"That teacher is teaching {other.subject} to {other.class_group} in "
        f"that period. A teacher can take two classes at once only for the "
        f"same subject."
    )


def set_lesson(term, class_group, weekday, period, subject, teacher, *, by=None):
    """Put `subject`, taught by `teacher`, in this class's slot. Replaces what
    was there. Returns `(slot, created)`.

    Refused with `TeacherIsElsewhere` when the teacher is teaching a different
    subject in the same period — the database's
    `a_teacher_teaches_one_subject_at_a_time`, which sees two writers racing as
    well as one. The same subject is allowed: a combined lesson.
    """
    _require_teacher(teacher)
    if not subject.is_active or not class_group.is_active:
        raise NotTaughtHere(
            f"{subject if not subject.is_active else class_group} is no longer "
            f"in use at the school, so no lesson can be put there."
        )
    try:
        with transaction.atomic():
            return TimetableSlot.objects.update_or_create(
                term=term,
                class_group=class_group,
                weekday=weekday,
                period=period,
                defaults={
                    "subject": subject,
                    "teacher_membership_id": teacher.pk,
                    "set_by_id": getattr(by, "pk", by),
                },
            )
    except IntegrityError as exc:
        if _constraint_of(exc) == "a_teacher_teaches_one_subject_at_a_time":
            raise TeacherIsElsewhere(
                _clash_sentence(term, weekday, period, teacher.pk, subject)
            ) from exc
        raise


def clear_lesson(term, class_group, weekday, period) -> bool:
    """Make it a free period. True if there was a lesson to clear."""
    deleted, _ = TimetableSlot.objects.filter(
        term=term, class_group=class_group, weekday=weekday, period=period
    ).delete()
    return bool(deleted)


def previous_term(term):
    """The term that started most recently before this one, across sessions."""
    return (
        Term.objects.filter(starts_on__lt=term.starts_on)
        .order_by("-starts_on", "-pk")
        .first()
    )


@dataclass(frozen=True)
class Copied:
    """What `copy_last_term()` did, in the terms the screen reports it."""

    from_term: Term
    copied: int
    #: Lessons left behind, and why — a class or subject no longer in use, or
    #: a teacher who no longer teaches here. Counted rather than silently
    #: dropped, so the office knows which gaps to fill.
    skipped_class: int
    skipped_subject: int
    skipped_teacher: int


def copy_last_term(term, *, by=None) -> Copied:
    """Fill an empty term with the previous term's timetable.

    **Only an empty term.** `TimetableNotEmpty` otherwise: a copy that wrote
    over lessons somebody had already set would destroy work nobody asked to
    lose. **Only what still exists**: a lesson whose class or subject has been
    retired, or whose teacher has left, is not copied, and is counted.

    One statement for the copy, inside one transaction, so a term is either
    filled or left empty. The copies cannot clash with each other: they are the
    previous term's rows, which already satisfied every constraint, minus some.
    """
    source = previous_term(term)
    if source is None:
        raise NoEarlierTerm("There is no earlier term to copy a timetable from.")

    with transaction.atomic():
        # Locks the target term's row, so two copies into it cannot both see it empty.
        Term.objects.select_for_update().filter(pk=term.pk).first()
        if TimetableSlot.objects.filter(term=term).exists():
            raise TimetableNotEmpty(
                f"{term} already has lessons. Copying only fills an empty term; "
                f"clear it first if you mean to start again."
            )

        rows = list(
            TimetableSlot.objects.filter(term=source).select_related("class_group", "subject")
        )
        teachers = set(
            Membership.objects.filter(
                pk__in={r.teacher_membership_id for r in rows},
                role=Role.TEACHER.value,
            )
            .live()
            .values_list("pk", flat=True)
        )
        keep, skipped = [], {"class": 0, "subject": 0, "teacher": 0}
        for row in rows:
            if not row.class_group.is_active:
                skipped["class"] += 1
            elif not row.subject.is_active:
                skipped["subject"] += 1
            elif row.teacher_membership_id not in teachers:
                skipped["teacher"] += 1
            else:
                keep.append(
                    TimetableSlot(
                        term=term,
                        class_group=row.class_group,
                        weekday=row.weekday,
                        period_id=row.period_id,
                        subject=row.subject,
                        teacher_membership_id=row.teacher_membership_id,
                        set_by_id=getattr(by, "pk", by),
                    )
                )
        TimetableSlot.objects.bulk_create(keep)

    return Copied(
        from_term=source,
        copied=len(keep),
        skipped_class=skipped["class"],
        skipped_subject=skipped["subject"],
        skipped_teacher=skipped["teacher"],
    )


def teacher_names(membership_ids, school):
    """`{membership_id: name}` for TEACHER memberships at this school — scoped
    in the query, so a bare id from another school names nobody."""
    return {
        row["pk"]: row["display_name"] or row["user__full_name"] or ""
        for row in Membership.objects.filter(
            pk__in=set(membership_ids), school=school, role=Role.TEACHER.value
        ).values("pk", "display_name", "user__full_name")
    }


__all__ = [
    "Copied",
    "EDITING_ROLES",
    "NoEarlierTerm",
    "NotTaughtHere",
    "NotThisSchoolsTeacher",
    "PeriodInUse",
    "PeriodsOverlap",
    "READING_ROLES",
    "TeacherIsElsewhere",
    "TimetableError",
    "TimetableNotEmpty",
    "add_period",
    "change_period",
    "clear_lesson",
    "copy_last_term",
    "may_edit",
    "may_read",
    "previous_term",
    "remove_period",
    "set_lesson",
    "teacher_names",
]
