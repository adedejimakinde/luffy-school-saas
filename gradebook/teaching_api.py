"""HTTP for the office's teaching setup: subjects, this term's papers, and class teachers.

The screen at `/teaching/` and nothing else reads these. Tenant-host only; there is no school
slug in any path, for the reason `gradebook/api.py` gives. **Every route asks who is asking
before it looks anything up** (the oracle rule), with one sentence for every refusal, so
"you may not" and "there is no such subject" cannot be told apart by their wording.
`gradebook.curriculum` holds every rule.
"""

from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import ClassGroup
from accounts.models import Membership, Role
from accounts.session import session_auth

from . import curriculum
from .models import Assessment, Score, Subject

router = Router(auth=session_auth)

_MAY_NOT = (
    "Subjects, papers and class teachers are set by a principal or an administrator of the school."
)


class MessageOut(Schema):
    detail: str


class PaperOut(Schema):
    assessment_id: int
    name: str
    max_score: int
    #: Whether anybody has a mark in it: if so, what it is out of cannot change and it cannot go.
    has_marks: bool


class SubjectOut(Schema):
    subject_id: int
    name: str
    code: str
    is_active: bool
    #: This term's papers, in print order.
    papers: List[PaperOut]
    #: Papers in every term. Above zero, the subject can only be retired, not removed.
    papers_ever: int


class TeacherOut(Schema):
    membership_id: int
    name: str


class ClassOut(Schema):
    class_group_id: int
    name: str
    class_teacher_id: Optional[int] = None


class TeachingOut(Schema):
    term_id: Optional[int] = None
    term: Optional[str] = None
    subjects: List[SubjectOut]
    classes: List[ClassOut]
    teachers: List[TeacherOut]


class SubjectIn(Schema):
    name: str
    code: str
    is_active: bool = True


class PaperIn(Schema):
    name: str
    max_score: int


class TeacherIn(Schema):
    membership_id: int


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No teaching setup on this host.")
    return school


def _gate(request):
    """`(school, None)` for the office, `(school, refusal)` for anybody else."""
    school = _school_of(request)
    if not curriculum.can_shape(request.user, school):
        return school, (403, MessageOut(detail=_MAY_NOT))
    return school, None


def _subjects(term):
    papers = {}
    if term is not None:
        marked = set(
            Score.objects.filter(assessment__term=term).values_list("assessment_id", flat=True).distinct()
        )
        for a in Assessment.objects.filter(term=term):
            papers.setdefault(a.subject_id, []).append(
                PaperOut(assessment_id=a.pk, name=a.name, max_score=a.max_score, has_marks=a.pk in marked)
            )
    ever = {}
    for subject_id in Assessment.objects.values_list("subject_id", flat=True):
        ever[subject_id] = ever.get(subject_id, 0) + 1
    return [
        SubjectOut(
            subject_id=s.pk, name=s.name, code=s.code, is_active=s.is_active,
            papers=papers.get(s.pk, []), papers_ever=ever.get(s.pk, 0),
        )
        for s in Subject.objects.order_by("name")
    ]


def _overview(school):
    term = curriculum.current_term()
    teachers = curriculum.teachers_of(school)
    assigned = curriculum.class_teacher_ids(term) if term is not None else {}
    return TeachingOut(
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        subjects=_subjects(term),
        classes=[
            ClassOut(class_group_id=g.pk, name=g.name, class_teacher_id=assigned.get(g.pk))
            for g in ClassGroup.objects.filter(is_active=True)
        ],
        teachers=[TeacherOut(membership_id=m.pk, name=name) for m, name in teachers],
    )


@router.get("/", response={200: TeachingOut, 403: MessageOut})
def overview(request):
    school, refused = _gate(request)
    if refused:
        return refused
    return 200, _overview(school)


def _doing(request, act):
    """Run a write, and say what the school's rules said. Returns `(status, body)`."""
    try:
        act()
    except curriculum.NotAllowedToShapeTheCurriculum:
        return 403, MessageOut(detail=_MAY_NOT)
    except curriculum.CurriculumRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return None


_WRITE = {200: TeachingOut, 403: MessageOut, 404: MessageOut, 422: MessageOut}


@router.post("/subjects/", response=_WRITE)
def add_subject(request, payload: SubjectIn):
    school, refused = _gate(request)
    if refused:
        return refused
    failed = _doing(request, lambda: curriculum.create_subject_as(request.user, school, payload.name, payload.code))
    return failed or (200, _overview(school))


@router.put("/subjects/{int:subject_id}/", response=_WRITE)
def change_subject(request, subject_id: int, payload: SubjectIn):
    school, refused = _gate(request)
    if refused:
        return refused
    subject = get_object_or_404(Subject, pk=subject_id)
    failed = _doing(
        request,
        lambda: curriculum.update_subject_as(
            request.user, school, subject, payload.name, payload.code, payload.is_active
        ),
    )
    return failed or (200, _overview(school))


@router.delete("/subjects/{int:subject_id}/", response=_WRITE)
def remove_subject(request, subject_id: int):
    school, refused = _gate(request)
    if refused:
        return refused
    subject = get_object_or_404(Subject, pk=subject_id)
    failed = _doing(request, lambda: curriculum.delete_subject_as(request.user, school, subject))
    return failed or (200, _overview(school))


@router.post("/subjects/{int:subject_id}/papers/", response=_WRITE)
def add_paper(request, subject_id: int, payload: PaperIn):
    school, refused = _gate(request)
    if refused:
        return refused
    subject = get_object_or_404(Subject, pk=subject_id)
    failed = _doing(
        request, lambda: curriculum.create_paper_as(request.user, school, subject, payload.name, payload.max_score)
    )
    return failed or (200, _overview(school))


@router.put("/papers/{int:assessment_id}/", response=_WRITE)
def change_paper(request, assessment_id: int, payload: PaperIn):
    school, refused = _gate(request)
    if refused:
        return refused
    paper = get_object_or_404(Assessment, pk=assessment_id)
    failed = _doing(
        request, lambda: curriculum.update_paper_as(request.user, school, paper, payload.name, payload.max_score)
    )
    return failed or (200, _overview(school))


@router.delete("/papers/{int:assessment_id}/", response=_WRITE)
def remove_paper(request, assessment_id: int):
    school, refused = _gate(request)
    if refused:
        return refused
    paper = get_object_or_404(Assessment, pk=assessment_id)
    failed = _doing(request, lambda: curriculum.delete_paper_as(request.user, school, paper))
    return failed or (200, _overview(school))


@router.put("/classes/{int:class_group_id}/teacher/", response=_WRITE)
def set_class_teacher(request, class_group_id: int, payload: TeacherIn):
    school, refused = _gate(request)
    if refused:
        return refused
    group = get_object_or_404(ClassGroup, pk=class_group_id)
    # Looked up in this school's own memberships, so another school's teacher is simply not found.
    teacher = Membership.objects.with_access().filter(
        pk=payload.membership_id, school=school, role=Role.TEACHER
    ).first()
    if teacher is None:
        return 422, MessageOut(detail="That is not one of this school's teachers.")
    failed = _doing(
        request, lambda: curriculum.assign_class_teacher_as(request.user, school, group, teacher)
    )
    return failed or (200, _overview(school))


@router.delete("/classes/{int:class_group_id}/teacher/", response=_WRITE)
def clear_class_teacher(request, class_group_id: int):
    school, refused = _gate(request)
    if refused:
        return refused
    group = get_object_or_404(ClassGroup, pk=class_group_id)
    failed = _doing(request, lambda: curriculum.clear_class_teacher_as(request.user, school, group))
    return failed or (200, _overview(school))


__all__ = ["router"]
