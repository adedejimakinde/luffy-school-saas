"""HTTP for the bell schedule and the timetable. T1.

**Two refusals, as the books and the absence list have them.** Anybody who may
not read a timetable — a bursar, a parent, a student — gets a flat 404 before
anything is looked up. The principal reads it and may not change it, so they
are told so in a sentence (403): the timetable's existence is not news to them.

**A clash is a 409 with a sentence that names what it clashed with** — the
subject and the class the teacher is already in. The database decides it
(`a_teacher_teaches_one_subject_at_a_time`); this only reports it.
"""

from datetime import time
from typing import List, Optional

from django.http import Http404
from ninja import Router, Schema

from academics.models import ClassGroup, Term
from accounts.models import Membership, Role
from accounts.session import session_auth
from gradebook.models import Subject

from . import services
from .models import Period, TimetableSlot, Weekday

router = Router(auth=session_auth)


# -- shapes -------------------------------------------------------------------


class MessageOut(Schema):
    detail: str


class TermOut(Schema):
    term_id: int
    term: str
    is_current: bool


class ClassOut(Schema):
    class_group_id: int
    class_group: str


class SubjectOut(Schema):
    subject_id: int
    subject: str
    code: str


class TeacherOut(Schema):
    teacher_membership_id: int
    teacher: str


class PeriodOut(Schema):
    period_id: int
    starts_at: str
    ends_at: str
    label: str


class DayOut(Schema):
    weekday: int
    day: str


class IndexOut(Schema):
    """Everything the page needs before it draws a week: the terms, the
    classes, the day's periods, and — for somebody who may edit — the subjects
    and teachers a lesson can be made of."""

    terms: List[TermOut]
    term_id: Optional[int]
    classes: List[ClassOut]
    periods: List[PeriodOut]
    days: List[DayOut]
    may_edit: bool
    subjects: List[SubjectOut]
    teachers: List[TeacherOut]
    #: Whether the chosen term has any lesson yet, and whether there is a term
    #: before it — together, whether "copy last term" can be offered.
    term_is_empty: bool
    has_earlier_term: bool


class LessonOut(Schema):
    weekday: int
    period_id: int
    subject_id: int
    subject: str
    code: str
    teacher_membership_id: int
    teacher: str


class WeekOut(Schema):
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    lessons: List[LessonOut]


class LessonIn(Schema):
    term_id: int
    weekday: int
    period_id: int
    subject_id: int
    teacher_membership_id: int


class PeriodIn(Schema):
    starts_at: time
    ends_at: time
    label: str = ""


class CopiedOut(Schema):
    from_term: str
    copied: int
    skipped_class: int
    skipped_subject: int
    skipped_teacher: int


# -- the pieces every route needs --------------------------------------------


def _school_of(request):
    """`None` is the portal, where these tables do not exist — the same flat
    404 as a refusal."""
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No timetable on this host.")
    return school


def _require_reader(actor, school):
    """The flat 404, before any read."""
    if not services.may_read(actor, school):
        raise Http404("No such timetable.")


_MAY_NOT_EDIT = "The timetable is set by an administrator or the vice principal (academic)."


def _refuse_non_editor(actor, school):
    if not services.may_edit(actor, school):
        return 403, MessageOut(detail=_MAY_NOT_EDIT)
    return None


def _clock(t) -> str:
    return t.strftime("%H:%M")


def _period_out(p) -> PeriodOut:
    return PeriodOut(period_id=p.pk, starts_at=_clock(p.starts_at), ends_at=_clock(p.ends_at), label=p.label)


def _term_or_404(term_id) -> Term:
    term = Term.objects.filter(pk=term_id).first()
    if term is None:
        raise Http404("No such timetable.")
    return term


def _class_or_404(class_group_id) -> ClassGroup:
    group = ClassGroup.objects.filter(pk=class_group_id).first()
    if group is None:
        raise Http404("No such timetable.")
    return group


# -- reading ------------------------------------------------------------------


@router.get("/", response=IndexOut)
def index(request, term_id: Optional[int] = None):
    school = _school_of(request)
    _require_reader(request.user, school)

    terms = list(Term.objects.order_by("-starts_on", "-pk"))
    if term_id is not None:
        term = next((t for t in terms if t.pk == term_id), None)
        if term is None:
            raise Http404("No such timetable.")
    else:
        term = next((t for t in terms if t.is_current), terms[0] if terms else None)

    editing = services.may_edit(request.user, school)
    subjects, teachers = [], []
    if editing:
        subjects = [
            SubjectOut(subject_id=s.pk, subject=s.name, code=s.code)
            for s in Subject.objects.filter(is_active=True).order_by("name")
        ]
        names = {
            row["pk"]: row["display_name"] or row["user__full_name"] or ""
            for row in Membership.objects.filter(school=school, role=Role.TEACHER.value)
            .live()
            .values("pk", "display_name", "user__full_name")
        }
        teachers = sorted(
            (TeacherOut(teacher_membership_id=pk, teacher=name) for pk, name in names.items()),
            key=lambda t: (t.teacher.lower(), t.teacher_membership_id),
        )

    return IndexOut(
        terms=[TermOut(term_id=t.pk, term=str(t), is_current=t.is_current) for t in terms],
        term_id=term.pk if term else None,
        classes=[
            ClassOut(class_group_id=g.pk, class_group=str(g))
            for g in ClassGroup.objects.filter(is_active=True).order_by("level", "name")
        ],
        periods=[_period_out(p) for p in Period.objects.all()],
        days=[DayOut(weekday=d.value, day=d.label) for d in Weekday],
        may_edit=editing,
        subjects=subjects,
        teachers=teachers,
        term_is_empty=not TimetableSlot.objects.filter(term=term).exists() if term else True,
        has_earlier_term=bool(term and services.previous_term(term)),
    )


@router.get("/classes/{int:class_group_id}/", response=WeekOut)
def week(request, class_group_id: int, term_id: int):
    """One class's week: every lesson, by weekday and period. Two reads for
    the lessons and one for the names, whatever the size of the week."""
    school = _school_of(request)
    _require_reader(request.user, school)
    group = _class_or_404(class_group_id)
    term = _term_or_404(term_id)

    slots = list(
        TimetableSlot.objects.filter(term=term, class_group=group).select_related("subject", "period")
    )
    names = services.teacher_names((s.teacher_membership_id for s in slots), school)
    return WeekOut(
        class_group_id=group.pk,
        class_group=str(group),
        term_id=term.pk,
        term=str(term),
        lessons=[
            LessonOut(
                weekday=s.weekday,
                period_id=s.period_id,
                subject_id=s.subject_id,
                subject=s.subject.name,
                code=s.subject.code,
                teacher_membership_id=s.teacher_membership_id,
                teacher=names.get(s.teacher_membership_id, ""),
            )
            for s in slots
        ],
    )


# -- writing: the timetable ---------------------------------------------------


@router.put(
    "/classes/{int:class_group_id}/lessons/",
    response={201: LessonOut, 200: LessonOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def put_lesson(request, class_group_id: int, payload: LessonIn):
    """Put a lesson in one slot of a class's week, replacing what was there.
    201 when the slot was free, 200 when a lesson was replaced."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_editor(request.user, school)
    if refusal:
        return refusal
    group = _class_or_404(class_group_id)
    term = _term_or_404(payload.term_id)

    if payload.weekday not in Weekday.values:
        return 422, MessageOut(detail="Choose a day from Monday to Friday.")
    period = Period.objects.filter(pk=payload.period_id).first()
    subject = Subject.objects.filter(pk=payload.subject_id).first()
    # Scoped to this school in the query: another school's teacher is not
    # "found and refused", they are not found — and not named.
    teacher = (
        Membership.objects.select_related("user", "school")
        .filter(pk=payload.teacher_membership_id, school=school, role=Role.TEACHER.value)
        .first()
    )
    if period is None:
        return 422, MessageOut(detail="Choose one of the school's periods.")
    if subject is None:
        return 422, MessageOut(detail="Choose one of the school's subjects.")
    if teacher is None:
        return 422, MessageOut(detail="Choose one of the school's teachers.")

    try:
        slot, created = services.set_lesson(
            term, group, payload.weekday, period, subject, teacher, by=request.user
        )
    except services.TeacherIsElsewhere as exc:
        return 409, MessageOut(detail=str(exc))
    except (services.NotThisSchoolsTeacher, services.NotTaughtHere) as exc:
        return 422, MessageOut(detail=str(exc))

    return (201 if created else 200), LessonOut(
        weekday=slot.weekday,
        period_id=slot.period_id,
        subject_id=subject.pk,
        subject=subject.name,
        code=subject.code,
        teacher_membership_id=teacher.pk,
        teacher=teacher.name,
    )


@router.delete(
    "/classes/{int:class_group_id}/lessons/",
    response={204: None, 403: MessageOut},
)
def clear_lesson(request, class_group_id: int, term_id: int, weekday: int, period_id: int):
    """Make a slot a free period. 204 whether or not there was a lesson: either
    way it is free now."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_editor(request.user, school)
    if refusal:
        return refusal
    group = _class_or_404(class_group_id)
    term = _term_or_404(term_id)
    services.clear_lesson(term, group, weekday, period_id)
    return 204, None


@router.post(
    "/terms/{int:term_id}/copy/",
    response={201: CopiedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def copy_last_term(request, term_id: int):
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_editor(request.user, school)
    if refusal:
        return refusal
    term = _term_or_404(term_id)
    try:
        done = services.copy_last_term(term, by=request.user)
    except services.TimetableNotEmpty as exc:
        return 409, MessageOut(detail=str(exc))
    except services.NoEarlierTerm as exc:
        return 422, MessageOut(detail=str(exc))
    return 201, CopiedOut(
        from_term=str(done.from_term),
        copied=done.copied,
        skipped_class=done.skipped_class,
        skipped_subject=done.skipped_subject,
        skipped_teacher=done.skipped_teacher,
    )


# -- writing: the bell schedule -----------------------------------------------


@router.post("/periods/", response={201: PeriodOut, 403: MessageOut, 422: MessageOut})
def add_period(request, payload: PeriodIn):
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_editor(request.user, school)
    if refusal:
        return refusal
    try:
        period = services.add_period(payload.starts_at, payload.ends_at, payload.label)
    except services.PeriodsOverlap as exc:
        return 422, MessageOut(detail=str(exc))
    return 201, _period_out(period)


@router.put("/periods/{int:period_id}/", response={200: PeriodOut, 403: MessageOut, 422: MessageOut})
def change_period(request, period_id: int, payload: PeriodIn):
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_editor(request.user, school)
    if refusal:
        return refusal
    period = Period.objects.filter(pk=period_id).first()
    if period is None:
        raise Http404("No such timetable.")
    try:
        services.change_period(
            period, starts_at=payload.starts_at, ends_at=payload.ends_at, label=payload.label
        )
    except services.PeriodsOverlap as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _period_out(period)


@router.delete("/periods/{int:period_id}/", response={204: None, 403: MessageOut, 409: MessageOut})
def remove_period(request, period_id: int):
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_editor(request.user, school)
    if refusal:
        return refusal
    period = Period.objects.filter(pk=period_id).first()
    if period is None:
        raise Http404("No such timetable.")
    try:
        services.remove_period(period)
    except services.PeriodInUse as exc:
        return 409, MessageOut(detail=str(exc))
    return 204, None


__all__ = ["router"]
