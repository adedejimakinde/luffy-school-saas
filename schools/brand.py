"""Whose name, crest and colour a portal page wears: the school's, or Classnode's.

On a school's own host the staff shell and the sign-in doors wear the school's
crest and name instead of the Classnode mark, its colour for the brand accents,
and its crest as the browser tab's icon. The portal (`app.<domain>`) keeps
Classnode's own (`docs/design.md`, "School branding").

## Who is shown it

- **A member of the school, on its host**: every page drawn in the shell, and
  the family pages, which they reach only as a member.
- **Anybody, on a door served on a school's host** (`door=True`): the door is
  the school's own address, whose public website already names it and shows
  its crest (`docs/sign-in-page.md`, "A school's own door"). A door on the
  portal is Classnode's.
- **Nobody else.** A frame served on a school's host to a stranger (signed
  out, or a member of another school) names no school, the rule the shell
  already kept for the school's name (`menu.shell_open`).

## What is read

One statement, after its search path, read once per request and kept on it:
the school's crest (the upload service's ready file in the `crest` slot) and
the primary colour the website's look settings hold for its current theme
(`schoolsite.SiteSettings`). Never cached across requests: a cache keyed wrongly
is how one school's crest would reach another's host, and one indexed row costs
less than that risk.

## The colour

The school's primary is used **only** if it reads on white at WCAG AA for body
text (4.5:1, `results.look.MIN_CONTRAST`), the rule the website and the report
card already hold it to; otherwise the design's navy. It replaces `--brand` and
nothing else: green, amber and red mean the same at every school.

A crest the upload service has not yet moved off the old column
(`ReportCardSettings.crest`, before `move_files_to_disk`) is not drawn here: the
shell falls back to the initials rather than inline the image into every page.
"""

import re
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import connection

#: The design's navy, the brand colour when a school has none that reads on white.
NAVY = "#143D8C"

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

_READ = """
SELECT
    (SELECT key FROM files_storedfile
     WHERE slot = 'crest' AND state = 'ready' AND schema_name = current_schema()
     ORDER BY id DESC LIMIT 1),
    (SELECT theme_options -> theme -> 'colours' ->> 'primary'
     FROM schoolsite_sitesettings WHERE id = 1)
"""


@dataclass(frozen=True)
class Brand:
    name: str
    initials: str
    #: The crest's 128px PNG on this host, or None: the initials in a navy tile.
    crest_url: Optional[str]
    #: `#RRGGBB`, checked: the school's primary if it reads on white, else navy.
    colour: str

    @property
    def custom_colour(self) -> bool:
        return self.colour.upper() != NAVY


def colour_for(chosen) -> str:
    """The school's primary if it is a hex colour reading on white at 4.5:1, else navy."""
    from results.look import MIN_CONTRAST, contrast_with_white

    if isinstance(chosen, str) and _HEX.match(chosen.strip()):
        colour = chosen.strip().upper()
        if contrast_with_white(colour) >= MIN_CONTRAST:
            return colour
    return NAVY


def _read(school) -> Brand:
    from menu import initials

    with connection.cursor() as cursor:
        cursor.execute(_READ)
        key, primary = cursor.fetchone()
    return Brand(
        name=school.name,
        initials=initials(school.name),
        crest_url=f"/media/{key}/site.png" if key else None,
        colour=colour_for(primary),
    )


def for_request(request, *, door: bool = False) -> Optional[Brand]:
    """This request's school brand, or None for Classnode's own look (see the module)."""
    if request is None:
        return None
    school = getattr(request, "school", None)
    if school is None or getattr(connection, "schema_name", "public") != school.schema_name:
        return None
    if not (door or getattr(request, "school_roles", None)):
        return None
    cached = getattr(request, "_brand", None)
    if cached is None:
        cached = request._brand = _read(school)
    return cached


def classnode_href() -> str:
    """Where "Powered by Classnode" goes: the public site."""
    host = getattr(settings, "SITE_HOST", None)
    return f"//{host}/" if host else "https://classnode.co/"


__all__ = ["Brand", "NAVY", "classnode_href", "colour_for", "for_request"]
