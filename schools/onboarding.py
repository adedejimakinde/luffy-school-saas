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
are one transaction. `invite_staff()` refuses before commit when invitations
cannot be delivered (`DeliveryNotConfigured`), so a deployment with no email
provider yet refuses to create a school rather than creating one nobody can
get into.
"""

import re

from django.conf import settings
from django.db import transaction

from accounts.models import Role
from schools import invitations
from schools.models import Domain, School

#: A DNS label: lowercase letters, digits and inner hyphens, at most 63.
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

#: Subdomains a school may not take: the portal's, and the ones a platform
#: needs for itself sooner or later.
RESERVED = frozenset({"app", "www", "api", "admin", "mail", "static", "portal", "public"})


class OnboardingError(Exception):
    """The portal or a school cannot be set up as asked. Nothing was written."""


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

    Returns `(school, host, invitation)`. Everything is checked before anything
    is written, and everything is written in one transaction.
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

    with transaction.atomic():
        school = School(name=name, slug=label, schema_name=schema_name)
        school.save()  # creates and migrates the schema
        Domain.objects.create(tenant=school, domain=host, is_primary=True)
        invitation, _ = invitations.invite_staff(
            operator, school, Role.ADMIN, email=admin_email, full_name=admin_name
        )
    return school, host, invitation


__all__ = ["OnboardingError", "RESERVED", "check_host", "create_school", "setup_portal"]
