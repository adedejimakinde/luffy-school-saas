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

from datetime import datetime
from typing import List, Optional

from django.db.models import Count, Q
from django.http import Http404
from ninja import Router, Schema

from accounts.models import LIVE_STATUSES, Membership, Role
from accounts.session import session_auth

from .delivery import DeliveryFailed, DeliveryNotConfigured, NoDeliveryAddress
from .models import Domain, InvitationError, School, UnroutedPayment
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


class UnroutedOut(Schema):
    reference: str
    amount_kobo: int
    account_number: str
    received_at: datetime


class UnroutedListOut(Schema):
    payments: List[UnroutedOut]


@router.get("/unrouted/", response={200: UnroutedListOut, 403: MessageOut})
def list_unrouted(request):
    """Money Paystack confirmed for an account number no school owns, newest first.

    Nobody's bursar can see these (`schools.UnroutedPayment` has no school), so
    they are the platform's to look into. Read only: it is listed and never
    placed, and platform staff cannot put it on a child, which is a school's books.
    """
    _portal_only(request)
    if not _is_platform_staff(request):
        return 403, MessageOut(detail=_NOT_YOURS)
    return UnroutedListOut(
        payments=[
            UnroutedOut(
                reference=p.reference,
                amount_kobo=p.amount_kobo,
                account_number=p.account_number,
                received_at=p.received_at,
            )
            for p in UnroutedPayment.objects.order_by("-id")
        ]
    )


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


# -- storage ------------------------------------------------------------------
#
# What each school keeps on the server's disk (`files`), against its quota,
# and how full the disk is. The figures are read from each school's own
# schema, one aggregate each; there is no running total to drift.


class StorageRowOut(Schema):
    name: str
    subdomain: str
    bytes: int
    files: int
    quota_bytes: int
    #: True when the school has no quota of its own and has the default.
    default_quota: bool
    percent: float


class DiskOut(Schema):
    used_bytes: int
    total_bytes: int
    percent: float
    warn_percent: float
    refuse_percent: float


class StorageOut(Schema):
    disk: DiskOut
    schools: List[StorageRowOut]
    #: Classnode's own blog's pictures, in the platform's schema.
    platform_bytes: int
    default_quota_bytes: int


class QuotaIn(Schema):
    #: Megabytes. Null or 0 goes back to the platform's default.
    quota_mb: Optional[int] = None


def _storage():
    from django.conf import settings

    from files import storage
    from files.management.commands.check_storage import school_usage

    used, total = storage.disk_usage()
    rows, blog = school_usage()
    return StorageOut(
        disk=DiskOut(
            used_bytes=used,
            total_bytes=total,
            percent=round(100.0 * used / total, 1) if total else 0.0,
            warn_percent=settings.FILES_DISK_WARN_PERCENT,
            refuse_percent=settings.FILES_DISK_REFUSE_PERCENT,
        ),
        schools=[
            StorageRowOut(
                name=school.name,
                subdomain=school.slug,
                bytes=usage["bytes"],
                files=usage["files"],
                quota_bytes=quota,
                default_quota=school.storage_quota_bytes is None,
                percent=round(100.0 * usage["bytes"] / quota, 1) if quota else 0.0,
            )
            for school, usage, quota in rows
        ],
        platform_bytes=blog["bytes"],
        default_quota_bytes=settings.FILES_DEFAULT_QUOTA_BYTES,
    )


@router.get("/storage/", response={200: StorageOut, 403: MessageOut})
def storage_totals(request):
    """Every school's files against its quota, and how full the disk is."""
    _portal_only(request)
    if not _is_platform_staff(request):
        return 403, MessageOut(detail=_NOT_YOURS)
    return 200, _storage()


#: The most a quota may be set to, so a typo cannot promise a school the disk.
MAX_QUOTA_MB = 50 * 1024


@router.put(
    "/schools/{subdomain}/quota/",
    response={200: StorageOut, 403: MessageOut, 404: MessageOut, 422: MessageOut},
)
def set_quota(request, subdomain: str, payload: QuotaIn):
    """Set one school's quota, in megabytes; empty goes back to the default."""
    _portal_only(request)
    if not _is_platform_staff(request):
        return 403, MessageOut(detail=_NOT_YOURS)
    school = School.objects.exclude(schema_name="public").filter(slug=subdomain).first()
    if school is None:
        return 404, MessageOut(detail="No school has that subdomain.")
    mb = payload.quota_mb or 0
    if mb < 0 or mb > MAX_QUOTA_MB:
        return 422, MessageOut(detail=f"A quota is between 1 MB and {MAX_QUOTA_MB // 1024} GB.")
    School.objects.filter(pk=school.pk).update(storage_quota_bytes=mb * 1024 * 1024 if mb else None)
    return 200, _storage()
