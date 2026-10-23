"""HTTP for "who teaches what": read the term's subject teachers, add one, take one away.

The screen at `/subject-teachers/` and nothing else reads these. Tenant-host only, with
no school slug in any path, for the reason `gradebook/api.py` gives. **Every route asks
who is asking before it looks anything up** (the oracle rule): reading is the
principal's, the vice principal's and the administrator's, and writing is the
principal's alone, each refused with one sentence. Every write answers with the whole
overview, so the page redraws from the school's answer. `gradebook.assignments` holds
every rule.
"""

from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema

from academics.models import ClassGroup
from accounts.models import Membership, Role
from accounts.session import session_auth

from . import assignments, curriculum
from .models import Subject, SubjectTeacher, SubjectTeacherChange

router = Router(auth=session_auth)

_MAY_NOT_READ = "Who teaches what is shown to the principal, the vice principal and the administrator."
_MAY_NOT_CHANGE = "Who teaches what is set by the principal."

#: How many of the latest changes the page lists.
CHANGES_SHOWN = 20


class MessageOut(Schema):
    detail: str


class NamedOut(Schema):
    id: int
    name: str


class AssignmentOut(Schema):
    id: int
    class_group_id: int
    class_group: str
    subject_id: int
    subject: str
    teacher_membership_id: int
    teacher: str


class ChangeOut(Schema):
    kind: str
    teacher: str
    subject: str
    class_group: str
    by: str
    #: In the school's time, already worded: "23 Oct 2026, 10:04".
    at: str


class OverviewOut(Schema):
    term_id: Optional[int] = None
    term: Optional[str] = None
    #: Is this login the principal, who may change these?
    may_change: bool
    #: Has the term any assignment, so that teachers' marking is narrowed?
    in_force: bool
    classes: List[NamedOut]
    #: Subjects still taught, which are the ones that can be given to somebody.
    subjects: List[NamedOut]
    teachers: List[NamedOut]
    assignments: List[AssignmentOut]
    changes: List[ChangeOut]


class AssignIn(Schema):
    class_group_id: int
    subject_id: int
    membership_id: int


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No subject teachers on this host.")
    return school


def _names(school, ids) -> dict:
    rows = Membership.objects.filter(pk__in=set(ids), school=school).select_related("user")
    return {m.pk: m.display_name or m.user.full_name or m.user.username for m in rows}


def _worded(at) -> str:
    return timezone.localtime(at).strftime("%-d %b %Y, %H:%M")


def _overview(request, school):
    term = curriculum.current_term()
    rows = (
        list(SubjectTeacher.objects.filter(term=term).select_related("class_group", "subject"))
        if term is not None
        else []
    )
    names = _names(school, [r.teacher_membership_id for r in rows])
    rows.sort(key=lambda r: (r.class_group.level, r.class_group.name, r.subject.name, names.get(r.teacher_membership_id, "")))
    changes = (
        SubjectTeacherChange.objects.filter(term=term)[:CHANGES_SHOWN] if term is not None else []
    )
    return OverviewOut(
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        may_change=assignments.can_assign(request.user, school),
        in_force=bool(rows),
        classes=[NamedOut(id=g.pk, name=g.name) for g in ClassGroup.objects.filter(is_active=True)],
        subjects=[NamedOut(id=s.pk, name=s.name) for s in Subject.objects.filter(is_active=True).order_by("name")],
        teachers=[NamedOut(id=m.pk, name=name) for m, name in curriculum.teachers_of(school)],
        assignments=[
            AssignmentOut(
                id=r.pk,
                class_group_id=r.class_group_id,
                class_group=r.class_group.name,
                subject_id=r.subject_id,
                subject=r.subject.name,
                teacher_membership_id=r.teacher_membership_id,
                teacher=names.get(r.teacher_membership_id, "A former teacher"),
            )
            for r in rows
        ],
        changes=[
            ChangeOut(
                kind=c.kind,
                teacher=c.teacher_name,
                subject=c.subject_name,
                class_group=c.class_group_name,
                by=c.by_name,
                at=_worded(c.at),
            )
            for c in changes
        ],
    )


_WRITE = {200: OverviewOut, 403: MessageOut, 404: MessageOut, 422: MessageOut}


@router.get("/", response={200: OverviewOut, 403: MessageOut})
def overview(request):
    school = _school_of(request)
    if not assignments.can_view(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_READ)
    return 200, _overview(request, school)


@router.post("/", response=_WRITE)
def assign(request, payload: AssignIn):
    school = _school_of(request)
    if not assignments.can_assign(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_CHANGE)
    group = get_object_or_404(ClassGroup, pk=payload.class_group_id)
    subject = get_object_or_404(Subject, pk=payload.subject_id)
    # Looked up in this school's own memberships, so another school's teacher is simply not found.
    teacher = (
        Membership.objects.with_access()
        .filter(pk=payload.membership_id, school=school, role=Role.TEACHER)
        .select_related("user", "school")
        .first()
    )
    if teacher is None:
        return 422, MessageOut(detail="That is not one of this school's teachers.")
    try:
        assignments.assign_as(request.user, school, curriculum.current_term(), group, subject, teacher)
    except assignments.NotAllowedToAssign:
        return 403, MessageOut(detail=_MAY_NOT_CHANGE)
    except assignments.AssignmentRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _overview(request, school)


@router.delete("/{int:assignment_id}/", response=_WRITE)
def unassign(request, assignment_id: int):
    school = _school_of(request)
    if not assignments.can_assign(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_CHANGE)
    try:
        assignments.unassign_as(request.user, school, assignment_id)
    except assignments.NotAllowedToAssign:
        return 403, MessageOut(detail=_MAY_NOT_CHANGE)
    # Already gone is the end state asked for, so the answer is the overview either way.
    return 200, _overview(request, school)


__all__ = ["router"]
