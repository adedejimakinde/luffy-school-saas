"""HTTP for the notices settings screen: three switches, and who gets the summary.

Gated on the terms `services.require_settings_authority()` already checks —
the principal or an administrator, `notices.services.SETTINGS_ROLES`. A flat
404 on the portal, the same refusal `fees.api` gives, since there is no
school's settings row there; a 403 with a sentence for anybody signed in who
may not read or change these, since they already know the school exists.
"""

from typing import List, Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth
from schools.invitations import active_staff

from . import services

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class StaffOut(Schema):
    membership_id: int
    name: str
    email: str
    role: str
    role_display: str


class SettingsOut(Schema):
    payment_receipts: bool
    absence_alerts: bool
    daily_money_summary: bool
    #: Nobody by default (D15, extended) — the note on the page names this.
    money_summary_recipient_ids: List[int]
    #: This school's own live staff, to pick recipients from.
    staff: List[StaffOut]


class SettingsIn(Schema):
    payment_receipts: Optional[bool] = None
    absence_alerts: Optional[bool] = None
    daily_money_summary: Optional[bool] = None
    money_summary_recipient_ids: Optional[List[int]] = None


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No settings on this host.")
    return school


def _staff_out(school) -> List[StaffOut]:
    return [
        StaffOut(
            membership_id=m.pk,
            name=m.name,
            email=m.user.email or "",
            role=m.role,
            role_display=m.get_role_display(),
        )
        for m in active_staff(school).order_by("user__full_name")
    ]


def _settings_out(school) -> SettingsOut:
    row = services.offered()
    return SettingsOut(
        payment_receipts=row.payment_receipts,
        absence_alerts=row.absence_alerts,
        daily_money_summary=row.daily_money_summary,
        money_summary_recipient_ids=services.money_summary_recipient_ids(),
        staff=_staff_out(school),
    )


@router.get("/settings/", response={200: SettingsOut, 403: MessageOut, 404: MessageOut})
def get_settings(request):
    school = _school_of(request)
    try:
        services.require_settings_authority(request.user, school)
    except services.NotAllowed as e:
        return 403, MessageOut(detail=str(e))
    return _settings_out(school)


@router.post("/settings/", response={200: SettingsOut, 403: MessageOut, 404: MessageOut})
def update_settings(request, payload: SettingsIn):
    school = _school_of(request)
    try:
        services.set_offered_as(
            request.user,
            payment_receipts=payload.payment_receipts,
            absence_alerts=payload.absence_alerts,
            daily_money_summary=payload.daily_money_summary,
        )
        if payload.money_summary_recipient_ids is not None:
            services.set_money_summary_recipients(
                request.user, payload.money_summary_recipient_ids
            )
    except services.NotAllowed as e:
        return 403, MessageOut(detail=str(e))
    return _settings_out(school)


__all__ = ["router"]
