"""The installable app: a host's manifest, and the page it shows with no connection.

`docs/pwa.md`. Three hosts answer `/site.webmanifest`, each its own way, and none
can answer another's:

- **A school's host** (`manifest()`): the school's name and short name, its crest as
  the icons (the upload service's `icon-192.png` and `icon-512.png`, cut inside the
  maskable safe zone), its brand colour as the theme colour (navy when it has none
  that reads on white), and the portal home as the start. Read for *this request's*
  school from its own schema, so a school's name or crest cannot come out of any other
  host: there is no list of schools in this module and nothing is kept between requests
  (`schools.brand` says why).
- **The portal** (`app.<domain>`): Classnode's, with the staff door as the start.
- **The public site** (`site_manifest()`): Classnode's, as it was, which is not
  installable (`display: browser`).

The manifest is fetched by the browser with no cookie, so it names only what the
school's public website already names, as a door does (`brand.of_school()`).

A school with no crest keeps Classnode's two icons: its name and colour are still its
own, and nothing of another school's can be there.
"""

import re

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django_tenants.utils import get_public_schema_name

from files import service
from files.kinds import APP_ICON_SIDES
from schools import brand

MANIFEST_TYPE = "application/manifest+json"

#: Where an installed school app opens: the portal home, `api._landing()`'s.
SCHOOL_START = "/home/"
#: Where the installed portal opens: the staff door (`/` redirects there).
PORTAL_START = "/staff-sign-in/"

#: What Android shows under the icon fits about this many letters.
SHORT_NAME_LENGTH = 12
#: Words a school's name can lose when it is too long for a home screen.
GENERIC_WORDS = frozenset(
    {
        "academy", "college", "group", "high", "international", "ltd", "limited",
        "nursery", "primary", "school", "schools", "secondary", "the", "and", "&",
    }
)

CLASSNODE_ICONS = [
    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
]

#: Classnode's public site: not installable, as it has always been.
SITE_MANIFEST = {
    "name": "Classnode",
    "short_name": "Classnode",
    "icons": CLASSNODE_ICONS,
    "start_url": "/",
    "display": "browser",
    "theme_color": brand.NAVY,
    "background_color": "#FFFFFF",
}


def short_name(name: str) -> str:
    """A name that fits under an icon: the whole name if it does, else its distinctive words.

    "Grace Academy" is "Grace Academy" (it fits); "Saint Mary's International School"
    is "Saint Mary's"; a single long word is cut at the limit.
    """
    name = " ".join((name or "").split())
    if len(name) <= SHORT_NAME_LENGTH:
        return name
    words = name.split(" ")
    kept = [w for w in words if re.sub(r"[^\w&]", "", w).lower() not in GENERIC_WORDS] or words
    short = ""
    for word in kept:
        trial = f"{short} {word}".strip()
        if len(trial) > SHORT_NAME_LENGTH:
            break
        short = trial
    return short or kept[0][:SHORT_NAME_LENGTH]


def _on_a_school() -> bool:
    tenant = getattr(connection, "tenant", None)
    return tenant is not None and tenant.schema_name != get_public_schema_name()


def _manifest_response(body: dict) -> JsonResponse:
    response = JsonResponse(body, content_type=MANIFEST_TYPE, json_dumps_params={"indent": 2})
    # A school changes its crest or colour now and then; a few minutes' staleness is
    # the whole cost of not asking the database on every page's manifest fetch.
    response["Cache-Control"] = "public, max-age=300"
    return response


def _icons_of(look: brand.Brand) -> list:
    """The crest's app icons for `look`, as the manifest lists them; Classnode's with no crest."""
    stored = service.find(look.crest_key) if look.crest_key else None
    if stored is None or not service.ensure_icons(stored):
        return CLASSNODE_ICONS
    icons = []
    for side in APP_ICON_SIDES:
        entry = {"src": f"/media/{stored.key}/icon-{side}.png", "sizes": f"{side}x{side}", "type": "image/png"}
        # The same file serves both: it is opaque and drawn inside the safe zone.
        icons.extend([{**entry, "purpose": "any"}, {**entry, "purpose": "maskable"}])
    return icons


@require_GET
def manifest(request):
    """`/site.webmanifest` on a school's host or the portal."""
    school = getattr(request, "school", None)
    if _on_a_school() and school is not None:
        look = brand.of_school(school)
        return _manifest_response(
            {
                "id": SCHOOL_START,
                "name": look.name,
                "short_name": short_name(look.name),
                "start_url": SCHOOL_START,
                "scope": "/",
                "display": "standalone",
                "lang": "en-NG",
                "theme_color": look.colour,
                "background_color": "#FFFFFF",
                "icons": _icons_of(look),
            }
        )
    return _manifest_response(
        {
            "id": PORTAL_START,
            "name": "Classnode",
            "short_name": "Classnode",
            "start_url": PORTAL_START,
            "scope": "/",
            "display": "standalone",
            "lang": "en-NG",
            "theme_color": brand.NAVY,
            "background_color": "#FFFFFF",
            "icons": CLASSNODE_ICONS,
        }
    )


@require_GET
def site_manifest(request):
    """`/site.webmanifest` on Classnode's public site."""
    return _manifest_response(SITE_MANIFEST)


@require_GET
def offline(request):
    """`/offline/`: what the worker shows when a page cannot be reached.

    The same for everybody on a host, signed in or not: the school's crest and name
    (as its public website and doors show them) or Classnode's, one sentence, and a way
    to try again. The worker keeps this one copy (`sync/worker.js`), which is why it names
    no person and no page.
    """
    school = getattr(request, "school", None)
    on_a_school = _on_a_school() and school is not None
    response = render(
        request,
        "schools/offline.html",
        {"door": True, "retry": SCHOOL_START if on_a_school else PORTAL_START, "indexable": False},
    )
    response["Cache-Control"] = "no-cache"
    return response


__all__ = ["manifest", "offline", "short_name", "site_manifest"]
