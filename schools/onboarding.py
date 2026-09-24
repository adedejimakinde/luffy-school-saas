"""Bringing the portal, and then a school, onto the platform.

Two acts, run by the operator at a shell on the server (`setup_portal`,
`create_school`), not from the admin: making a school builds and migrates a
Postgres schema, which is seconds of DDL that has no business inside a web
request behind a proxy with a timeout.

## Every host is one label under the platform domain

`check_host()` is the rule both acts go through, and it is three facts about
the deployment, not a style preference:

- **Under `PLATFORM_DOMAIN`**, because one session cookie spans the portal and
  every school (`SESSION_COOKIE_DOMAIN`). A school on a host outside it would
  have staff who sign in on the portal and arrive at their school as strangers.
- **Exactly one label deep**, because the wildcard certificate covers
  `*.PLATFORM_DOMAIN` and nothing deeper: `a.b.classnode.africa` would be served
  with a certificate that does not match it.
- **A valid DNS label**, which is also what makes the slug a safe schema name.

## A school arrives with its first administrator invited, or not at all

The school, its schema, its `Domain` row and the invitation to its first ADMIN
are one transaction.

**With an email provider, the invitation is emailed**, as every other one is.
**Without one — a deployment that has not signed up for one yet — the operator
is the delivery** (decided 2026-09-24): the invitation is issued by hand and its
link comes back to be printed and handed over. What still refuses the whole
school is having no accept page to link to, because then there is nothing to
hand over either, and a school nobody can get into is not created.
"""

import re
from typing import NamedTuple, Optional

from django.conf import settings
from django.db import transaction

from accounts.models import Role
from schools import invitations
from schools.delivery import DeliveryNotConfigured, get_channel
from schools.models import Domain, Invitation, School

#: A DNS label: lowercase letters, digits and inner hyphens, at most 63.
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

#: Subdomains a school may not take: the portal's, and the ones a platform
#: needs for itself sooner or later.
RESERVED = frozenset({"app", "www", "api", "admin", "mail", "static", "portal", "public"})


class OnboardingError(Exception):
    """The portal or a school cannot be set up as asked. Nothing was written."""


class CreatedSchool(NamedTuple):
    school: School
    host: str
    invitation: Invitation
    #: The accept link, when there was no email provider to send it and the
    #: operator has to hand it over. None when it was emailed — and then it is
    #: nobody's to print: it is a credential, and it went where it belongs.
    link_to_hand_over: Optional[str]


def email_provider_configured():
    """Whether the configured channel can send at all.

    Asked of the channel itself (`check_configured()`), the same question
    `invitations._deliver()` asks before it sends, so "configured" cannot mean
    one thing here and another there. A channel that defines no such check —
    a test double — is taken at its word.
    """
    check = getattr(get_channel(), "check_configured", None)
    if check is None:
        return True
    try:
        check()
    except DeliveryNotConfigured:
        return False
    return True


def check_host(host):
    """`(host, label)` if `host` is one valid label under `PLATFORM_DOMAIN`."""
    domain = settings.PLATFORM_DOMAIN
    if not domain:
        raise OnboardingError(
            "PLATFORM_DOMAIN is not set, so there is no parent domain for this "
            "host to live under. Set it in deploy/production.env."
        )
    host = (host or "").strip().lower()
    suffix = f".{domain}"
    if not host.endswith(suffix):
        raise OnboardingError(
            f"{host!r} is not under {domain}. Every host on the platform must be, "
            f"or the session cookie set at sign-in never reaches it."
        )
    label = host[: -len(suffix)]
    if "." in label:
        raise OnboardingError(
            f"{host!r} is more than one label under {domain}. The certificate "
            f"covers *.{domain} and nothing deeper."
        )
    if not _LABEL.match(label):
        raise OnboardingError(
            f"{label!r} is not a usable subdomain: lowercase letters, digits and "
            f"hyphens only, not starting or ending with a hyphen, at most 63."
        )
    return host, label


def setup_portal():
    """The public schema's tenant row and its `Domain`, on `PORTAL_HOST`. Idempotent.

    The portal is the public schema — it has no schema of its own to build — so
    this writes two rows and no DDL.
    """
    host, _ = check_host(settings.PORTAL_HOST or "")
    with transaction.atomic():
        portal = School.objects.filter(schema_name="public").first()
        if portal is None:
            portal = School(name="Portal", slug="portal", schema_name="public")
            # `public` exists already; saving must not try to build it.
            portal.auto_create_schema = False
            portal.save()
        existing = Domain.objects.filter(domain=host).first()
        if existing is not None and existing.tenant_id != portal.pk:
            raise OnboardingError(f"{host!r} already belongs to {existing.tenant}.")
        if existing is None:
            Domain.objects.create(tenant=portal, domain=host, is_primary=True)
    return portal, host


def create_school(*, slug, name, admin_email, operator, admin_name=""):
    """Make a school: its schema, its host, and its first administrator's invitation.

    Returns a `CreatedSchool`. Everything is checked before anything is
    written, and everything is written in one transaction. Whether the
    invitation is emailed or handed back is `email_provider_configured()`.
    """
    slug = (slug or "").strip().lower()
    name = (name or "").strip()
    if not name:
        raise OnboardingError("A school needs a name.")
    host, label = check_host(f"{slug}.{settings.PLATFORM_DOMAIN}")
    portal_label = (settings.PORTAL_HOST or "").split(".", 1)[0]
    if label in RESERVED or label == portal_label:
        raise OnboardingError(f"{label!r} is reserved for the platform itself.")
    schema_name = label.replace("-", "_")
    if schema_name.startswith("pg_"):
        raise OnboardingError(f"{label!r} would make a schema name Postgres reserves.")
    if School.objects.filter(slug=label).exists() or School.objects.filter(
        schema_name=schema_name
    ).exists():
        raise OnboardingError(f"There is already a school at {label!r}.")
    if Domain.objects.filter(domain=host).exists():
        raise OnboardingError(f"{host!r} already belongs to a school.")
    if not getattr(operator, "is_platform_staff", False):
        raise OnboardingError(
            f"{operator} is not platform staff. Schools are created by the "
            f"platform's operators, not by any school's staff."
        )

    by_hand = not email_provider_configured()
    with transaction.atomic():
        school = School(name=name, slug=label, schema_name=schema_name)
        school.save()  # creates and migrates the schema
        Domain.objects.create(tenant=school, domain=host, is_primary=True)
        if by_hand:
            invitation, link = invitations.invite_staff_by_hand(
                operator, school, Role.ADMIN, email=admin_email, full_name=admin_name
            )
        else:
            invitation, _ = invitations.invite_staff(
                operator, school, Role.ADMIN, email=admin_email, full_name=admin_name
            )
            link = None
    return CreatedSchool(school, host, invitation, link)


__all__ = [
    "CreatedSchool",
    "OnboardingError",
    "RESERVED",
    "check_host",
    "create_school",
    "email_provider_configured",
    "setup_portal",
]
