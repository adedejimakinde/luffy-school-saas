"""How a school's report card looks: its crest and its one colour.

Both optional, both on `ReportCardSettings` (the row that already says how this
school handles its cards), both set from the setup page by whoever may set the
school up.

## The crest is an upload like any other

It goes through the one upload service (`files.service`, slot `"crest"`): the
file is checked by its own bytes in the request, then redrawn in the media
worker as a trimmed lossless PNG with no metadata, at the sizes the card and
the website draw it. Nothing of the uploaded file is kept. A new crest replaces
the old one only once it is ready, so a card never prints the initials for the
seconds the worker takes, and a failed upload leaves the old crest in place.

Until `manage.py move_files_to_disk` has copied it, a school's crest may still
be the bytes in `ReportCardSettings.crest`, written before the service existed;
every reader here falls back to them. Removing the crest clears both.

## The colour has to read on white

The card prints the school's name in the school's colour on white paper, and
its initials in white on a circle of the colour. Both are the same contrast: a
colour under 4.5 to 1 against white (WCAG's figure for body text) would print a
name nobody can read off a cheap printer, so it is refused with a sentence
saying why, rather than accepted and regretted.
"""

import base64
import io
import re
from typing import Optional

from django.db import transaction

from academics.services import can_set_up

from .models import ReportCardSettings

#: The design's own blue (`docs/design.md`). What a school that never chose a
#: colour prints in.
DEFAULT_COLOUR = "#143D8C"

#: The colour against white paper needs this much contrast. WCAG AA for body text.
MIN_CONTRAST = 4.5

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


class LookRefused(Exception):
    """An upload or a colour the card cannot use. The message is for the person."""


class NotAllowedToSetTheLook(Exception):
    pass


def settings() -> ReportCardSettings:
    """This school's row, or an unsaved default. Never writes on a read."""
    return ReportCardSettings.objects.filter(pk=1).first() or ReportCardSettings()


def _require_authority(actor, school):
    if not can_set_up(actor, school):
        raise NotAllowedToSetTheLook(
            "A school's crest and colour are set by its principal or an administrator."
        )


# -- the colour --------------------------------------------------------------


def _luminance(hex_colour: str) -> float:
    """WCAG relative luminance of `#RRGGBB`."""
    channels = []
    for i in (1, 3, 5):
        c = int(hex_colour[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_with_white(hex_colour: str) -> float:
    return 1.05 / (_luminance(hex_colour) + 0.05)


def clean_colour(value: Optional[str]) -> str:
    """`#RRGGBB` in upper case, or `LookRefused` saying what is wrong.

    Blank or None is the default blue: clearing the colour is choosing not to
    have one, which prints in the design's own.
    """
    if value is None or not str(value).strip():
        return DEFAULT_COLOUR
    match = _HEX.match(str(value).strip())
    if not match:
        raise LookRefused("A colour is six hex digits, like #143D8C.")
    colour = f"#{match.group(1).upper()}"
    if contrast_with_white(colour) < MIN_CONTRAST:
        raise LookRefused(
            f"{colour} is too light to read on a white page. Choose a darker shade."
        )
    return colour


def set_colour_as(actor, school, value: Optional[str]) -> ReportCardSettings:
    _require_authority(actor, school)
    colour = clean_colour(value)
    row, _ = ReportCardSettings.objects.get_or_create(pk=1)
    row.colour = colour
    row.save(update_fields=["colour", "updated_at"])
    return row


# -- the crest ---------------------------------------------------------------

CREST_SLOT = "crest"


def set_crest_as(actor, school, upload):
    """Take a new crest. It is checked now and drawn by the media worker."""
    from files import service
    from files.kinds import Kind

    _require_authority(actor, school)
    # The row the site's cache key reads the crest through (`schoolsite.views`).
    ReportCardSettings.objects.get_or_create(pk=1)
    try:
        stored = service.accept(Kind.CREST, upload, slot=CREST_SLOT, by=actor)
    except service.UploadRefused as exc:
        raise LookRefused(str(exc))
    if stored.state == "failed":
        raise LookRefused(stored.error)
    _log_crest(actor, school, "saved", "Uploaded a new crest.")
    return settings()


def clear_crest_as(actor, school) -> ReportCardSettings:
    from files import service

    _require_authority(actor, school)
    with transaction.atomic():
        row, _ = ReportCardSettings.objects.get_or_create(pk=1)
        had = row.crest is not None or service.latest(CREST_SLOT) is not None
        service.clear_slot(CREST_SLOT)
        row.crest = None
        row.save(update_fields=["crest", "updated_at"])
        if had:
            _log_crest(actor, school, "cleared", "Removed the crest. Cards print the school's initials.")
    return row


def crest_file():
    """The crest as the upload service keeps it, or None."""
    from files import service

    return service.current(CREST_SLOT)


def crest_png(row=None) -> Optional[bytes]:
    """The crest as the card prints it, a 256 px square PNG, or None."""
    from files import service

    stored = crest_file()
    if stored is not None:
        try:
            return service.read(stored, "card.png")
        except FileNotFoundError:
            return None
    row = row or settings()
    return bytes(row.crest) if row.crest else None


def crest_status() -> dict:
    """What the setup page says about the crest: ready, being drawn, or why not."""
    from files import service

    status = service.status_of(CREST_SLOT)
    if not status["ready"]:
        row = settings()
        if row.crest:
            status = {**status, "ready": True, "version": f"db{int(row.updated_at.timestamp())}"}
    return status


def _log_crest(actor, school, action, summary):
    from audit import log

    log.record(actor, school, action=action, kind="crest", item_name=school.name, summary=summary)


# -- the position in class ---------------------------------------------------


def set_show_position_as(actor, school, on: bool) -> ReportCardSettings:
    """Whether the card prints the child's position in class. Off by default.

    Read at release and frozen onto each card, so this changes cards released
    from now on and never one that has gone home.
    """
    _require_authority(actor, school)
    row, _ = ReportCardSettings.objects.get_or_create(pk=1)
    row.show_position = bool(on)
    row.save(update_fields=["show_position", "updated_at"])
    return row


# -- the ministry heading on the Ogun State card -----------------------------


def set_show_ministry_as(actor, school, on: bool) -> ReportCardSettings:
    """Whether the Ogun State card opens with the ministry's name. Off by default.

    Read when a card is drawn, as the rest of the Ogun sheet's head is
    (`results.ogun_card`): the stored PDF keeps what it was released with.
    """
    _require_authority(actor, school)
    row, _ = ReportCardSettings.objects.get_or_create(pk=1)
    row.show_ministry = bool(on)
    row.save(update_fields=["show_ministry", "updated_at"])
    return row


# -- what the card prints ----------------------------------------------------


def initials(school_name: str) -> str:
    """"SD" for Sunrise Demo Academy, "SM" for St Mary's: two letters at most."""
    words = [w for w in re.split(r"[\s\-]+", school_name or "") if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper()


def for_card(school_name: str) -> dict:
    """What the card's header needs: the colour, and a crest or the initials."""
    row = settings()
    crest = crest_png(row)
    return {
        "colour": row.colour or DEFAULT_COLOUR,
        "crest": f"data:image/png;base64,{base64.b64encode(crest).decode()}" if crest else None,
        "initials": initials(school_name),
    }


#: The side of the crest on the school's public page, in pixels. It is drawn
#: about 96 CSS pixels wide, so 128 keeps it sharp on a phone, and small
#: enough that even a crest full of noise is a fraction of the page's budget.
SITE_CREST_SIDE = 128


def for_site(school_name: str) -> dict:
    """The look for a page that has to stay small: the crest as an address.

    A crest kept by the upload service is a public file on the school's own
    host, sent by Caddy with a year's cache (§4.2), not base64 in every page.
    One still only in the database column is shrunk and inlined, as before.
    """
    from PIL import Image

    row = settings()
    look = {"colour": row.colour or DEFAULT_COLOUR, "crest": None, "initials": initials(school_name)}
    stored = crest_file()
    if stored is not None and stored.has("site.png"):
        from files.views import url_for

        look["crest"] = url_for(stored, "site.png")
        return look
    if not row.crest:
        return look
    image = Image.open(io.BytesIO(bytes(row.crest))).convert("RGBA")
    image = image.resize((SITE_CREST_SIDE, SITE_CREST_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    look["crest"] = f"data:image/png;base64,{base64.b64encode(out.getvalue()).decode()}"
    return look


__all__ = [
    "for_site",
    "CREST_SLOT",
    "DEFAULT_COLOUR",
    "LookRefused",
    "NotAllowedToSetTheLook",
    "clean_colour",
    "clear_crest_as",
    "contrast_with_white",
    "for_card",
    "initials",
    "crest_file",
    "crest_png",
    "crest_status",
    "set_colour_as",
    "set_crest_as",
    "set_show_position_as",
    "set_show_ministry_as",
    "settings",
]
