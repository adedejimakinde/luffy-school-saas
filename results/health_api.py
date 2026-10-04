"""HTTP for a child's physical development and health. `results.health`.

Its own router, beside the card's and the comments' and imported by neither,
so no schema of theirs can grow a slot for it. The comments page's child view
is served to every teacher at the school; a health record is not, which is why
it is fetched from here when a child is opened and never rides on that answer.

**Every refusal is a flat 404**, the card routes' convention: a 403 would tell
somebody with no claim which children have a record, in which term.
"""

from typing import Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import Term
from accounts.models import Membership, Role
from accounts.session import session_auth

from . import health, ogun
from .models import HealthLocked

router = Router(auth=session_auth)

_NOT_FOUND = "No such health record."


class MessageOut(Schema):
    detail: str


class HealthOut(Schema):
    student_membership_id: int
    term_id: int
    #: Decimal strings ("1.42", "38.5") rather than floats, for the reason
    #: the card's percentages are strings: nothing rounds them on the way.
    height_start_m: Optional[str] = None
    height_end_m: Optional[str] = None
    weight_start_kg: Optional[str] = None
    weight_end_kg: Optional[str] = None
    days_absent_ill: Optional[int] = None
    illness: str = ""
    #: The class teacher, before the card goes home.
    may_edit: bool
    #: The card for this term has gone home, so nothing here changes.
    locked: bool
    #: Whether the school prints the section (the Ogun State card).
    printed: bool


class HealthIn(Schema):
    height_start_m: Optional[str] = None
    height_end_m: Optional[str] = None
    weight_start_kg: Optional[str] = None
    weight_end_kg: Optional[str] = None
    days_absent_ill: Optional[str] = None
    illness: str = ""


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No health records on this host.")
    return school


def _child_and_term(request, school, student_membership_id, term_id):
    child = Membership.objects.filter(
        pk=student_membership_id, school=school, role=Role.STUDENT
    ).first()
    term = (
        Term.objects.filter(pk=term_id).first()
        if term_id is not None
        else Term.objects.filter(is_current=True).first()
    )
    if child is None or term is None or not health.may_see(request.user, school, child, term):
        raise Http404(_NOT_FOUND)
    return child, term


def _text(value):
    return None if value is None else f"{value}"


def _out(request, school, child, term) -> HealthOut:
    row = health.record_for(child, term)
    locked = health.is_released(child, term)
    return HealthOut(
        student_membership_id=child.pk,
        term_id=term.pk,
        height_start_m=_text(row.height_start_m) if row else None,
        height_end_m=_text(row.height_end_m) if row else None,
        weight_start_kg=_text(row.weight_start_kg) if row else None,
        weight_end_kg=_text(row.weight_end_kg) if row else None,
        days_absent_ill=row.days_absent_ill if row else None,
        illness=row.illness if row else "",
        may_edit=not locked and health.may_record(request.user, school, child, term),
        locked=locked,
        printed=ogun.is_ogun(),
    )


@router.get("/health/{int:student_membership_id}/", response={200: HealthOut, 404: MessageOut})
def read(request, student_membership_id: int, term_id: Optional[int] = None):
    """One child's record for a term: the current one unless `term_id` says."""
    school = _school_of(request)
    child, term = _child_and_term(request, school, student_membership_id, term_id)
    return 200, _out(request, school, child, term)


@router.put(
    "/health/{int:student_membership_id}/",
    response={200: HealthOut, 404: MessageOut, 422: MessageOut, 423: MessageOut},
)
def write(request, student_membership_id: int, payload: HealthIn):
    """The class teacher records this term's. Blank clears a box."""
    school = _school_of(request)
    child, term = _child_and_term(request, school, student_membership_id, None)
    try:
        values = health.read(**payload.dict())
        health.record_as(request.user, school, child, term, values)
    except health.NotAllowedToRecordHealth:
        # Somebody who may read it (the office) but not write it. They know it
        # exists, so a 404 would only confuse; they are told who writes it.
        return 422, MessageOut(detail="A child's health is recorded by their class teacher.")
    except HealthLocked as exc:
        return 423, MessageOut(detail=str(exc))
    except health.HealthRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _out(request, school, child, term)
