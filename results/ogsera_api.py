"""HTTP for filling an OGSERA template. `results.ogsera` holds every rule.

Multipart, as the roll import is: the workbook is sent with each step and
never stored. Host, then authority, then the file: the order every route in
this codebase keeps. A school not on the Ogun State template is told so (409).
"""

from typing import Dict, List, Optional

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from ninja import Router, Schema

from academics.models import ClassGroup, Term
from accounts.session import session_auth
from gradebook.models import Subject

from . import ogsera

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class ChoiceOut(Schema):
    key: str
    label: str


class MappedOut(Schema):
    heading: str
    field: str


class PickOut(Schema):
    id: int
    name: str


class DoorOut(Schema):
    term: Optional[str]
    fields: List[ChoiceOut]
    mapping: List[MappedOut]
    classes: List[PickOut]
    subjects: List[PickOut]


class HeadingOut(Schema):
    column: str
    heading: str
    field: str


class CheckOut(Schema):
    sheet_name: str
    header_row: int
    headings: List[HeadingOut]
    unmatched: List[dict]
    missing_id: List[dict]
    not_in_file: List[str]
    no_learner_id: List[str]
    missing_values: List[str]
    matched: int
    filled: int
    kept: int
    may_download: bool


class MappingIn(Schema):
    #: Heading as the template writes it -> field key, or "" to leave it.
    columns: Dict[str, str]


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No OGSERA templates on this host.")
    return school


def _gate(request):
    school = _school_of(request)
    try:
        ogsera.require_office_at_an_ogun_school(request.user, school)
    except ogsera.NotAllowed as exc:
        return school, (403, MessageOut(detail=str(exc)))
    except ogsera.OgseraRefused as exc:
        return school, (409, MessageOut(detail=str(exc)))
    return school, None


def _file(request):
    upload = request.FILES.get("file")
    if upload is None:
        return None, (422, MessageOut(detail="Choose the Excel file OGSERA gave you."))
    if upload.size > ogsera.MAX_FILE_BYTES:
        return None, (422, MessageOut(detail="That file is over 5 MB. An OGSERA template is far smaller."))
    return upload, None


def _check_out(check) -> CheckOut:
    return CheckOut(may_download=check.may_download, **{k: v for k, v in check.__dict__.items()})


_RESPONSES = {200: CheckOut, 403: MessageOut, 409: MessageOut, 422: MessageOut}


@router.get("/ogsera/", response={200: DoorOut, 403: MessageOut, 409: MessageOut})
def door(request):
    school, refused = _gate(request)
    if refused:
        return refused
    term = Term.objects.filter(is_current=True).first()
    saved = ogsera.mapping()
    return 200, DoorOut(
        term=str(term) if term else None,
        fields=[ChoiceOut(key=k, label=v) for k, v in ogsera.field_choices()],
        mapping=[MappedOut(heading=saved.headings.get(k, k), field=v) for k, v in saved.columns.items()],
        classes=[PickOut(id=g.pk, name=g.name) for g in ClassGroup.objects.filter(is_active=True)],
        subjects=[PickOut(id=s.pk, name=s.name) for s in Subject.objects.filter(is_active=True)],
    )


@router.post("/ogsera/headings/", response=_RESPONSES)
def read_headings(request):
    school, refused = _gate(request)
    if refused:
        return refused
    upload, problem = _file(request)
    if problem:
        return problem
    try:
        return 200, _check_out(ogsera.headings(request.user, school, upload.read()))
    except ogsera.OgseraRefused as exc:
        return 422, MessageOut(detail=str(exc))


@router.put("/ogsera/mapping/", response={200: DoorOut, 403: MessageOut, 409: MessageOut, 422: MessageOut})
def save_mapping(request, payload: MappingIn):
    school, refused = _gate(request)
    if refused:
        return refused
    try:
        ogsera.save_mapping_as(request.user, school, payload.columns, {h: h for h in payload.columns})
    except ogsera.OgseraRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return door(request)


def _run(request, *, fill):
    school, refused = _gate(request)
    if refused:
        return refused
    upload, problem = _file(request)
    if problem:
        return problem
    group = get_object_or_404(ClassGroup, pk=request.POST.get("class_group_id") or 0)
    subject_id = request.POST.get("subject_id") or None
    subject = get_object_or_404(Subject, pk=subject_id) if subject_id else None
    replace = request.POST.get("replace") in ("1", "true", "on")
    try:
        check, content = ogsera.run(
            request.user, school, upload.read(), class_group=group, subject=subject, replace=replace, fill=fill
        )
    except ogsera.OgseraRefused as exc:
        return 422, MessageOut(detail=str(exc))
    if not fill:
        return 200, _check_out(check)
    name = (upload.name or "ogsera.xlsx").rsplit(".", 1)[0]
    response = HttpResponse(
        content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{slugify(name)}-filled.xlsx"'
    response["Cache-Control"] = "private, no-store"
    return response


@router.post("/ogsera/check/", response=_RESPONSES)
def check(request):
    """Step 2: what would be filled, and what stands in the way. Writes nothing."""
    return _run(request, fill=False)


@router.post("/ogsera/fill/", response={200: None, 403: MessageOut, 409: MessageOut, 422: MessageOut})
def fill(request):
    """Step 3: the filled workbook. Refused while a row is unmatched or has no ID."""
    return _run(request, fill=True)
