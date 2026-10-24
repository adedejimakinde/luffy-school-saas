"""HTTP for exam slips and exam officers: the `/exam-slips/` screen and nothing else.

Tenant-host only, with no school slug in any path, for the reason `gradebook/api.py`
gives. **Every route asks who is asking before it looks anything up** (the oracle rule),
and answers anybody it refuses with one sentence: the slips are the principal's, the
administrator's and an exam officer's (`access.can_print()`), and naming or ending an
exam officer is the principal's (`access.can_name()`). `cbt.pins` and `cbt.officers`
ask again and hold every rule.

Nothing here serves a question, a bank or a test: there are none in step 2.

## The PDF is the only copy

A print answers with the PDF itself, rendered in the request that minted its PINs and
in the same transaction (a render that fails mints and cancels nothing). It is never
written to disk or storage, and `Cache-Control: no-store` with `Pragma: no-cache` keeps
a shared computer's browser and any proxy from keeping it either. The offline worker
never touches `/api/` (`sync/worker.js`).
"""

from typing import List, Optional

from django.db import transaction
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from ninja import Router, Schema

from academics.models import ClassGroup, ClassPlacement, TermName
from accounts.models import Membership, Role
from accounts.session import session_auth

from . import access, officers, pdf, pins
from .models import ExamOfficerGrant, PinSlipPrint

router = Router(auth=session_auth)

_MAY_NOT_PRINT = "Exam slips are printed by the principal, the administrator or an exam officer."
_MAY_NOT_NAME = "Exam officers are named by the principal."

#: How many of the latest prints and officer changes the page lists.
SHOWN = 20


class MessageOut(Schema):
    detail: str


class LastPrintOut(Schema):
    at: str
    by: str


class ClassOut(Schema):
    id: int
    name: str
    #: Students placed in it this term who can act here.
    students: int
    #: How many of them hold a live exam PIN this term.
    with_a_pin: int
    last_print: Optional[LastPrintOut] = None


class OfficerOut(Schema):
    membership_id: int
    name: str
    role: str
    named_by: str
    named_at: str
    #: False while their membership here is suspended or ended: no officer while so.
    can_act: bool


class CandidateOut(Schema):
    membership_id: int
    name: str
    role: str


class PrintOut(Schema):
    kind: str
    class_group: str
    student: str
    count: int
    cancelled: int
    without_a_number: int
    by: str
    at: str


class OfficerChangeOut(Schema):
    kind: str
    name: str
    role: str
    by: str
    note: str
    at: str


class OverviewOut(Schema):
    term_id: Optional[int] = None
    term: Optional[str] = None
    #: Is this login the principal, who names and ends exam officers?
    may_name: bool
    classes: List[ClassOut]
    officers: List[OfficerOut]
    #: Who the principal could name now; empty for anybody else.
    candidates: List[CandidateOut]
    prints: List[PrintOut]
    officer_changes: List[OfficerChangeOut]


class StudentOut(Schema):
    id: int
    name: str
    admission_number: str
    has_pin: bool


class ClassSlipsOut(Schema):
    id: int
    name: str
    term: str
    students: List[StudentOut]


class NameIn(Schema):
    membership_id: int
    note: str = ""


class EndIn(Schema):
    note: str = ""


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No exam slips on this host.")
    return school


def _worded(at) -> str:
    return timezone.localtime(at).strftime("%-d %b %Y, %H:%M")


def _role_label(role) -> str:
    try:
        return Role(role).label
    except ValueError:
        return role


def _member_name(m) -> str:
    return m.display_name or m.user.full_name or m.user.username


def _term_label(term) -> str:
    return f"{TermName(term.name).label}, {term.session}"


def _overview(request, school) -> OverviewOut:
    term = pins.current_term()
    may_name = access.can_name(request.user, school)
    classes = list(ClassGroup.objects.filter(is_active=True))
    class_rows = []
    if term is not None:
        placed = {}
        for group_id, sid in ClassPlacement.objects.filter(term=term, class_group__in=classes).values_list(
            "class_group_id", "student_membership_id"
        ):
            placed.setdefault(group_id, set()).add(sid)
        everyone = set().union(*placed.values()) if placed else set()
        acting = set(
            Membership.objects.with_access().filter(school=school, pk__in=everyone).values_list("pk", flat=True)
        )
        holding = pins.live_pin_holders(term, acting)
        last = {}
        for row in PinSlipPrint.objects.filter(term=term).order_by("-id"):
            last.setdefault(row.class_group_id, row)
        for group in classes:
            here = placed.get(group.pk, set()) & acting
            row = last.get(group.pk)
            class_rows.append(
                ClassOut(
                    id=group.pk,
                    name=group.name,
                    students=len(here),
                    with_a_pin=len(here & holding),
                    last_print=LastPrintOut(at=_worded(row.at), by=row.printed_by_name) if row else None,
                )
            )

    named_ids = access.officer_memberships(
        ExamOfficerGrant.objects.values_list("membership_id", flat=True).distinct()
    )
    members = {
        m.pk: m
        for m in Membership.objects.filter(school=school, pk__in=named_ids).select_related("user")
    }
    latest_named = {}
    for grant in ExamOfficerGrant.objects.filter(membership_id__in=named_ids, kind=ExamOfficerGrant.Kind.NAMED):
        latest_named.setdefault(grant.membership_id, grant)
    officer_rows = sorted(
        (
            OfficerOut(
                membership_id=mid,
                name=_member_name(members[mid]) if mid in members else latest_named[mid].membership_name,
                role=_role_label(members[mid].role if mid in members else latest_named[mid].role),
                named_by=latest_named[mid].by_name,
                named_at=_worded(latest_named[mid].at),
                can_act=bool(mid in members and members[mid].grants_access),
            )
            for mid in named_ids
            if mid in latest_named
        ),
        key=lambda o: (o.name.casefold(), o.membership_id),
    )
    candidates = []
    if may_name:
        candidates = sorted(
            (
                CandidateOut(membership_id=m.pk, name=_member_name(m), role=_role_label(m.role))
                for m in Membership.objects.with_access()
                .filter(school=school, role__in=access.OFFICER_ROLES)
                .exclude(pk__in=named_ids)
                .select_related("user")
            ),
            key=lambda c: (c.name.casefold(), c.membership_id),
        )
    return OverviewOut(
        term_id=term.pk if term else None,
        term=_term_label(term) if term else None,
        may_name=may_name,
        classes=class_rows,
        officers=officer_rows,
        candidates=candidates,
        prints=[
            PrintOut(
                kind=p.kind,
                class_group=p.class_group_name,
                student=p.student_name,
                count=p.count,
                cancelled=p.cancelled_count,
                without_a_number=p.without_a_number,
                by=p.printed_by_name,
                at=_worded(p.at),
            )
            for p in (PinSlipPrint.objects.filter(term=term)[:SHOWN] if term else [])
        ],
        officer_changes=[
            OfficerChangeOut(
                kind=g.kind, name=g.membership_name, role=_role_label(g.role), by=g.by_name, note=g.note, at=_worded(g.at)
            )
            for g in ExamOfficerGrant.objects.all()[:SHOWN]
        ],
    )


@router.get("/slips/", response={200: OverviewOut, 403: MessageOut})
def overview(request):
    school = _school_of(request)
    if not access.can_print(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_PRINT)
    return 200, _overview(request, school)


@router.get("/slips/classes/{int:class_group_id}/", response={200: ClassSlipsOut, 403: MessageOut, 404: MessageOut, 409: MessageOut})
def class_slips(request, class_group_id: int):
    """One class's students this term, each with whether they hold a live PIN. No PINs."""
    school = _school_of(request)
    if not access.can_print(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_PRINT)
    term = pins.current_term()
    if term is None:
        return 409, MessageOut(detail="No term is open. The current term is set on the Setup page.")
    group = ClassGroup.objects.filter(pk=class_group_id).first()
    if group is None:
        return 404, MessageOut(detail="There is no such class here.")
    students = pins.roster(school, group, term)
    holding = pins.live_pin_holders(term, [s.pk for s in students])
    return 200, ClassSlipsOut(
        id=group.pk,
        name=group.name,
        term=_term_label(term),
        students=[
            StudentOut(
                id=s.pk,
                name=_member_name(s),
                admission_number=pins._typed_number(s.reference),
                has_pin=s.pk in holding,
            )
            for s in students
        ],
    )


def _pdf_response(request, slips, filename) -> HttpResponse:
    response = HttpResponse(pdf.render_slips(slips, f"{request.get_host()}/sit/"), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{slugify(filename)}.pdf"'
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    return response


_PRINT = {200: None, 403: MessageOut, 404: MessageOut, 422: MessageOut}


@router.post("/slips/classes/{int:class_group_id}/print/", response=_PRINT)
def print_class(request, class_group_id: int):
    """A new slip for every student in the class this term. Their old PINs stop working."""
    school = _school_of(request)
    if not access.can_print(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_PRINT)
    try:
        with transaction.atomic():
            slips = pins.print_class_as(request.user, school, class_group_id)
            response = _pdf_response(request, slips, f"exam slips {slips.class_group_name} {slips.term_label} {slips.session}")
    except pins.NotAllowedToPrint:
        return 403, MessageOut(detail=_MAY_NOT_PRINT)
    except pins.PrintRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return response


@router.post("/slips/classes/{int:class_group_id}/students/{int:membership_id}/print/", response=_PRINT)
def print_student(request, class_group_id: int, membership_id: int):
    """A new slip for one student, for a lost one. Only their old PIN stops working."""
    school = _school_of(request)
    if not access.can_print(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_PRINT)
    try:
        with transaction.atomic():
            slips = pins.print_student_as(request.user, school, class_group_id, membership_id)
            name = slips.slips[0].student_name if slips.slips else "student"
            response = _pdf_response(request, slips, f"exam slip {name} {slips.class_group_name}")
    except pins.NotAllowedToPrint:
        return 403, MessageOut(detail=_MAY_NOT_PRINT)
    except pins.PrintRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return response


_WRITE = {200: OverviewOut, 403: MessageOut, 422: MessageOut}


@router.post("/officers/", response=_WRITE)
def name_officer(request, payload: NameIn):
    school = _school_of(request)
    if not access.can_name(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_NAME)
    try:
        officers.name_as(request.user, school, payload.membership_id, payload.note)
    except officers.NotAllowedToName:
        return 403, MessageOut(detail=_MAY_NOT_NAME)
    except officers.OfficerRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _overview(request, school)


@router.post("/officers/{int:membership_id}/end/", response=_WRITE)
def end_officer(request, membership_id: int, payload: EndIn):
    school = _school_of(request)
    if not access.can_name(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_NAME)
    try:
        officers.end_as(request.user, school, membership_id, payload.note)
    except officers.NotAllowedToName:
        return 403, MessageOut(detail=_MAY_NOT_NAME)
    except officers.OfficerRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _overview(request, school)


__all__ = ["router"]
