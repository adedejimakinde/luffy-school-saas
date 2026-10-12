"""New school handover: what is done and what is left for each new school.

For the platform's own staff on the portal, and nobody else. A school never
sees this page or anything on it: it is routed on the portal host alone
(`urls_public.py`), and refuses anybody who is not platform staff before it
reads a table.

## Five checks, four of them read from the data

1. School created: the school row.
2. Administrator invited: the school's first administrator invitation.
3. Administrator signed in once: that administrator's `first_signed_in_at`.
4. Setup progress: `onboarding.progress`, read in the school's own schema.
5. Pilot agreement signed: the one thing no table of ours can know, so a
   member of platform staff records the date the signed copy came back. Who
   recorded it and when are kept with it, and the date cannot be in the
   future: `record_pilot_agreement()` refuses one, and the
   `pilot_agreement_is_not_signed_after_it_was_recorded` constraint refuses
   it again under any write that goes around the service.

## The welcome message

Text for the operator to copy into WhatsApp or an email to the new
administrator. It greets them by name, points at step 1 in plain words, and
never carries an invitation link: an invitation link is a credential, and a
message that is copied and forwarded is no place for one.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from accounts.models import LIVE_STATUSES, Membership, Role
from schools.models import Domain, Invitation, School

from . import help as tips
from .progress import progress_for


class HandoverRefused(Exception):
    """A pilot agreement date that cannot be recorded. Nothing was written."""


def is_platform_staff(user) -> bool:
    return bool(user is not None and user.is_authenticated and getattr(user, "is_platform_staff", False))


def record_pilot_agreement(actor, school: School, signed_on: date) -> School:
    """Record the day the signed pilot agreement came back, with who and when."""
    if not is_platform_staff(actor):
        raise HandoverRefused("Only platform staff record a pilot agreement.")
    if not isinstance(signed_on, date):
        raise HandoverRefused("Give the date the agreement was signed.")
    if signed_on > timezone.localdate():
        raise HandoverRefused("The date the agreement was signed cannot be in the future.")
    with transaction.atomic():
        School.objects.filter(pk=school.pk).update(
            pilot_agreement_signed_on=signed_on,
            pilot_agreement_recorded_by=actor,
            pilot_agreement_recorded_at=timezone.now(),
        )
    school.refresh_from_db()
    return school


@dataclass
class Check:
    key: str
    title: str
    done: bool
    detail: str


@dataclass
class Handover:
    school: School
    host: Optional[str]
    checks: list
    progress: object
    admin_name: str
    welcome: str

    @property
    def done(self):
        return sum(c.done for c in self.checks)

    @property
    def total(self):
        return len(self.checks)


def _on(moment) -> str:
    return timezone.localtime(moment).strftime("%A %-d %B %Y") if moment else ""


def _first_admin(school):
    """The school's first administrator membership that is still live."""
    return (
        Membership.objects.filter(school=school, role=Role.ADMIN, status__in=LIVE_STATUSES)
        .select_related("user")
        .order_by("pk")
        .first()
    )


def welcome_message(*, admin_name: str, school_name: str, host: Optional[str], sent_to: str, portal: Optional[str]) -> str:
    """What the operator sends the new administrator. Never an invitation link."""
    lines = [f"Hello {admin_name}," if admin_name else "Hello,", ""]
    address = f" Your school's address is https://{host}/" if host else ""
    lines.append(f"{school_name} is now on Classnode.{address}")
    lines.append("")
    lines.append(
        f"1. Open the invitation we sent to {sent_to} and choose your password."
        if sent_to
        else "1. Open the invitation we gave you and choose your password."
    )
    sign_in = f" at https://{portal}/staff-sign-in/" if portal else ""
    lines.append(f"2. Sign in{sign_in}. Classnode opens Start here, which shows your next step.")
    lines.append("3. Step 1 is your school's contact email and crest. It takes about two minutes.")
    lines.append("")
    lines.append("Each step says what to do, and you can stop and come back at any time.")
    lines.append("")
    lines.append(f"If you get stuck, write to {tips.SUPPORT_EMAIL}. {tips.SUPPORT_PROMISE}")
    lines.append("")
    lines.append("The Classnode team")
    return "\n".join(lines)


def handover_for(school: School, *, host: Optional[str] = None, portal: Optional[str] = None) -> Handover:
    admin = _first_admin(school)
    invitation = None
    if admin is not None:
        invitation = Invitation.objects.filter(membership=admin).order_by("created_at", "pk").first()
    progress = progress_for(school)
    signed_in_at = admin.user.first_signed_in_at if admin is not None else None
    finished = school.setup_completed_at is not None or progress.complete
    checks = [
        Check("created", "School created", True, f"{_on(school.created_at)}{f', {host}' if host else ''}"),
        Check(
            "invited",
            "Administrator invited",
            invitation is not None,
            (f"{invitation.sent_to or 'Link handed over'}, {_on(invitation.created_at)}" if invitation else "No administrator invitation yet"),
        ),
        Check(
            "signed-in",
            "Administrator signed in once",
            signed_in_at is not None,
            f"First signed in {_on(signed_in_at)}" if signed_in_at else "Not signed in yet",
        ),
        Check(
            "setup",
            "Setup progress",
            finished,
            "Setup finished"
            if finished
            else f"{progress.done} of {progress.total} steps done. Next: {progress.next.step.title}"
            if progress.next
            else f"{progress.done} of {progress.total} steps done",
        ),
        Check(
            "pilot",
            "Pilot agreement signed",
            school.pilot_agreement_signed_on is not None,
            (
                f"Signed {school.pilot_agreement_signed_on.strftime('%A %-d %B %Y')}, recorded by "
                f"{school.pilot_agreement_recorded_by.full_name} on {_on(school.pilot_agreement_recorded_at)}"
            )
            if school.pilot_agreement_signed_on
            else "Record the date the signed copy came back",
        ),
    ]
    admin_name = admin.user.full_name if admin is not None else ""
    return Handover(
        school=school,
        host=host,
        checks=checks,
        progress=progress,
        admin_name=admin_name,
        welcome=welcome_message(
            admin_name=admin_name,
            school_name=school.name,
            host=host,
            sent_to=invitation.sent_to if invitation else "",
            portal=portal,
        ),
    )


def customers():
    """Every school that is a customer: the portal's own row is not one."""
    return list(
        School.objects.exclude(schema_name="public").select_related("pilot_agreement_recorded_by").order_by("created_at", "pk")
    )


def hosts_of(schools) -> dict:
    hosts = {}
    for domain in Domain.objects.filter(tenant__in=schools).order_by("-is_primary", "pk"):
        hosts.setdefault(domain.tenant_id, domain.domain)
    return hosts


__all__ = [
    "Handover",
    "HandoverRefused",
    "customers",
    "handover_for",
    "hosts_of",
    "is_platform_staff",
    "record_pilot_agreement",
    "welcome_message",
]
