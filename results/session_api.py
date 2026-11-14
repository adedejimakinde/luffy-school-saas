"""How a school reckons a year, over HTTP: the term weighting and the pass mark.

`results/sessions.py` has always held the rules and the two settings; until the
audit's finding G-04 nothing called them, so every school averaged its terms
equally and suggested promotion at fifty. This is the door the promotion page's
settings screen uses.

Both routes are for `sessions.CONFIGURING_ROLES`, the principal and the
administrator, asked **before** anything is read. The pass mark decides what
Classnode *suggests*; who is promoted is the principal's decision
(`academics/promotion_api.py`).

**What a change reaches.** The weighting is read when a third term is released
and is frozen on each card's year summary. The pass mark is read when a
decision is recorded and is kept beside it. So neither reaches a card that has
gone home or a decision already made, and the answer says so.
"""

from typing import Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth

from . import sessions
from .models import SessionAveraging

router = Router(auth=session_auth)

_MAY_NOT = (
    "How the year is averaged and the pass mark are set by a principal or an "
    "administrator of the school."
)


class MessageOut(Schema):
    detail: str


class YearSettingsOut(Schema):
    #: "equal" (a straight mean of the terms a child has a card for) or "weighted".
    averaging: str
    #: The three weights, as text; null under a straight mean.
    first_weight: Optional[str] = None
    second_weight: Optional[str] = None
    third_weight: Optional[str] = None
    pass_mark: str


class YearSettingsIn(Schema):
    #: Omitted means leave it as it is.
    averaging: Optional[str] = None
    first_weight: Optional[str] = None
    second_weight: Optional[str] = None
    third_weight: Optional[str] = None
    pass_mark: Optional[str] = None


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No session settings on this host.")
    return school


def _text(value) -> Optional[str]:
    if value is None:
        return None
    text = f"{value}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def payload(row=None) -> YearSettingsOut:
    row = row or sessions.settings()
    return YearSettingsOut(
        averaging=row.averaging,
        first_weight=_text(row.first_weight),
        second_weight=_text(row.second_weight),
        third_weight=_text(row.third_weight),
        pass_mark=_text(row.pass_mark),
    )


@router.get("/year-settings/", response={200: YearSettingsOut, 403: MessageOut})
def year_settings(request):
    """The weighting and the pass mark as they are now."""
    school = _school_of(request)
    if not sessions.can_configure_sessions(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT)
    return 200, payload()


@router.put(
    "/year-settings/",
    response={200: YearSettingsOut, 403: MessageOut, 422: MessageOut},
)
def set_year_settings(request, body: YearSettingsIn):
    """Change the weighting, the pass mark, or both; refused whole if either is wrong."""
    school = _school_of(request)
    if not sessions.can_configure_sessions(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT)
    weights = None
    if body.averaging == SessionAveraging.WEIGHTED:
        weights = (body.first_weight, body.second_weight, body.third_weight)
    try:
        row = sessions.configure_as(
            request.user,
            averaging=body.averaging,
            weights=weights,
            pass_mark=body.pass_mark,
        )
    except sessions.NotAllowedToConfigureSessions:
        return 403, MessageOut(detail=_MAY_NOT)
    except sessions.SessionsError as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, payload(row)
