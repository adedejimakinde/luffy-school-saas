"""The platform admin screen's API: every school, and a way to make another.

**For platform staff and nobody else.** A school's own administrator is staff of
*that school*; this lists every customer and makes new ones, which is the
platform operator's act (`create_school()` refuses anyone who is not platform
staff, and this asks first, before it reads a table). A refusal is a 403 with
one sentence and no detail about what the screen holds.

**On the portal host only**, like sign-in: the schools are rows in the shared
schema, and a school's host is scoped to that one school. Asked on a school's
host the route does not exist (404).

**Making a school is `schools.onboarding.create_school()`**, reused as it is, so
the screen and `manage.py create_school` cannot disagree about a subdomain, a
reserved name or a half-made school. That is seconds of DDL in a web request;
the rest of the platform keeps schema creation at a shell for that reason, and
this screen is the one exception, chosen by the operator. The response says what
happened to the invitation: emailed, or (no email address, or no email provider)
a link for the operator to hand over. The link is a credential and is returned
once, to platform staff, exactly as the command prints it once to a terminal.
"""

from typing import List, Optional

from django.db.models import Count, Q
from django.http import Http404
from ninja import Router, Schema

from accounts.models import LIVE_STATUSES, Membership, Role
from accounts.session import session_auth

from .delivery import DeliveryFailed, DeliveryNotConfigured, NoDeliveryAddress
from .models import Domain, InvitationError, School
from .onboarding import OnboardingError, create_school

router = Router(auth=session_auth)

_NOT_YOURS = "This screen is for the platform's own staff."


class MessageOut(Schema):
    detail: str


class SchoolRowOut(Schema):
    name: str
    subdomain: str
    host: Optional[str] = None
    #: Children currently enrolled: live student memberships, not ended history.
    students: int
    is_active: bool
    created_on: str


class SchoolListOut(Schema):
    schools: List[SchoolRowOut]


class NewSchoolIn(Schema):
    name: str
    subdomain: str
    admin_name: str = ""
    admin_email: str = ""
    admin_phone: str = ""


class CreatedOut(Schema):
    school: SchoolRowOut
    #: Where the invitation went: the address or number it was made for.
    invited: str
    #: True when it was emailed. False means nothing was sent.
    emailed: bool
    #: True when it was texted, to an administrator known only by phone.
    texted: bool = False
    #: When nothing was sent: the accept link, for the operator to hand over.
    link_to_hand_over: Optional[str] = None
    link_expires_at: Optional[str] = None


def _portal_only(request):
    if getattr(request, "school", None) is not None:
        raise Http404("This screen is on the portal host.")


def _is_platform_staff(request):
    return bool(getattr(request.user, "is_platform_staff", False))


def _rows(schools):
    """One row per school, with student counts from a single grouped query."""
    counts = dict(
        Membership.objects.filter(
            role=Role.STUDENT, status__in=LIVE_STATUSES, school__in=schools
        )
        .order_by()
        .values_list("school_id")
        .annotate(n=Count("pk"))
    )
    hosts = {}
    for domain in Domain.objects.filter(tenant__in=schools).order_by("-is_primary", "pk"):
        hosts.setdefault(domain.tenant_id, domain.domain)
    return [
        SchoolRowOut(
            name=school.name,
            subdomain=school.slug,
            host=hosts.get(school.pk),
            students=counts.get(school.pk, 0),
            is_active=school.is_active,
            created_on=school.created_at.date().isoformat(),
        )
        for school in schools
    ]


def _customers():
    """Every school that is a customer: the portal's own row is not one."""
    return list(School.objects.exclude(schema_name="public"))


@router.get("/schools/", response={200: SchoolListOut, 403: MessageOut})
def list_schools(request):
    """Every school with how many children it has enrolled."""
    _portal_only(request)
    if not _is_platform_staff(request):
        return 403, MessageOut(detail=_NOT_YOURS)
    return SchoolListOut(schools=_rows(_customers()))


@router.post("/schools/", response={201: CreatedOut, 403: MessageOut, 422: MessageOut, 502: MessageOut})
def add_school(request, payload: NewSchoolIn):
    """Make a school and invite its first administrator. All of it or none."""
    _portal_only(request)
    if not _is_platform_staff(request):
        return 403, MessageOut(detail=_NOT_YOURS)
    try:
        created = create_school(
            slug=payload.subdomain,
            name=payload.name,
            admin_email=payload.admin_email,
            admin_phone=payload.admin_phone,
            admin_name=payload.admin_name,
            operator=request.user,
        )
    except OnboardingError as exc:
        return 422, MessageOut(detail=str(exc))
    except (DeliveryNotConfigured, NoDeliveryAddress, InvitationError) as exc:
        return 422, MessageOut(detail=f"Nothing was created: {exc}")
    except DeliveryFailed as exc:
        return 502, MessageOut(
            detail=f"The school was made but its invitation could not be sent: {exc}"
        )

    handed = created.link_to_hand_over
    return 201, CreatedOut(
        school=_rows([created.school])[0],
        invited=created.invitation.sent_to,
        emailed=handed is None and not created.texted,
        texted=created.texted,
        link_to_hand_over=handed,
        link_expires_at=created.invitation.expires_at.isoformat() if handed else None,
    )
