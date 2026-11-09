"""Where the portal answers, read from the one row that knows.

This was `results.views._portal_host()`, private to the pages a family sees,
and it is here because a second caller arrived that cannot reach it there. The
403 page `accounts` renders has the same problem the card page had: it must
send a reader to a door on **another host**, so the link cannot be relative,
and `accounts` importing from `results` would point the dependency backwards —
`results` is a leaf that already imports `accounts`, not the other way round.

`Domain` is a `schools` model, so this is the app the fact belongs to.
"""

from django.db import connection
from django_tenants.utils import get_public_schema_name

from schools.models import Domain


def portal_host() -> str:
    """The hostname the portal answers on, or `""` if none is configured.

    Both callers need it for a single sentence: a page on a school's host has
    to offer a way back to a door that is on the portal, and the link therefore
    cannot be relative.

    **The card page did not always have this, and that was a dead link rather
    than a missing nicety.** Its signed-out and expired states emitted
    `<a href="/">`, and `urls.py` routes no root — `api/`, `cards/` and
    `cards/<child>/<term>/` and nothing else — so a parent whose session lapsed
    on a card was handed a 404 by the one screen whose job is telling her how to
    get back in.

    One indexed row per page load, on pages that are already doing a fetch.
    Caching it would be a second place for a redeployed domain to go stale.

    **The API deliberately will not answer this** — `api._portal_only()` says a
    client knows its own portal and that having the server name it would put the
    same fact in two places. This does not reopen that. It reads the fact from
    the single authority there is, the `Domain` row for the public schema, and
    renders it into a page this same deployment serves; it does not add an API
    that tells arbitrary callers where the front door is.

    Empty where no such row exists, and **every caller must have a branch for
    that**. The page then renders its sentence without a link, because a dead
    link is worse than being told to go back the way you came. `static/card/
    states.js` `wayBack()` and `accounts/templates/403.html` are both on that
    rule.
    """
    return (
        Domain.objects.filter(tenant__schema_name="public", is_primary=True)
        .values_list("domain", flat=True)
        .first()
        or ""
    )


def school_host(school) -> str:
    """`school`'s own primary host, or `""` (no school, or none made yet)."""
    if school is None:
        return ""
    return (
        Domain.objects.filter(tenant_id=school.pk, is_primary=True)
        .values_list("domain", flat=True)
        .first()
        or ""
    )


def _on_a_school() -> bool:
    tenant = getattr(connection, "tenant", None)
    return tenant is not None and tenant.schema_name != get_public_schema_name()


def sign_in_host(request=None) -> str:
    """The host a person signs in on, from where they are now (host-aware, not a setting).

    **On a school's host, that host**: its own `/staff-sign-in/` and `/sign-in/`
    (C2), so a link never takes anybody to `app.<domain>` and out of the school
    they are using or the installed app. Wherever no school is current (the
    portal, an old link, a deployment with no school hosts) it is the portal's,
    `portal_host()`, which is where those pages are.

    The request's own host is used when there is one: it is a host the tenant
    middleware has already matched to a `Domain` row (an unknown host is a 404
    before any view runs), so it is never a value the client chose. With no
    request (a message being built in a task) the school's primary `Domain`.
    """
    if _on_a_school():
        if request is not None:
            return request.get_host()
        return (
            Domain.objects.filter(tenant__schema_name=connection.tenant.schema_name, is_primary=True)
            .values_list("domain", flat=True)
            .first()
            or ""
        )
    return portal_host()


__all__ = ["portal_host", "school_host", "sign_in_host"]
