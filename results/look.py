"""How a school's report card looks: its crest and its one colour.

Both optional, both on `ReportCardSettings` (the row that already says how this
school handles its cards), both set from the setup page by whoever may set the
school up.

## The crest is re-drawn, never kept as sent

An upload is a file somebody chose, and it is opened here with Pillow only to be
drawn again: fitted inside a square, on transparency, and written out as a
fresh PNG. What is stored is that PNG and nothing of the original, so a
metadata block, a second image hidden after the first, or a file that only
claims to be a PNG never reaches a card. A file over 1 MB is refused before it
is opened, and one that decodes to more pixels than a crest could need is
refused before it is decoded.

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

from academics.services import can_set_up

from .models import ReportCardSettings

#: The design's own blue (`docs/design.md`). What a school that never chose a
#: colour prints in.
DEFAULT_COLOUR = "#143D8C"

#: The largest upload looked at, in bytes.
MAX_UPLOAD_BYTES = 1024 * 1024

#: The side of the square the crest is drawn into, in pixels. About 22mm at
#: 300dpi, which is larger than the card prints it.
CREST_SIDE = 256

#: More pixels than any crest needs, and fewer than a decompression bomb
#: expands to. Checked from the header, before a pixel is decoded.
MAX_SOURCE_PIXELS = 4096 * 4096

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


def redraw_crest(raw: bytes) -> bytes:
    """The upload, fitted into a transparent square and written as a new PNG."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if len(raw) > MAX_UPLOAD_BYTES:
        raise LookRefused("A crest can be at most 1 MB. Save it smaller and try again.")
    try:
        source = Image.open(io.BytesIO(raw))
        if source.format not in ("PNG", "JPEG"):
            raise LookRefused("A crest is a PNG or a JPG file.")
        width, height = source.size
        if width * height > MAX_SOURCE_PIXELS:
            raise LookRefused("That image is far larger than a crest needs. Save it smaller and try again.")
        source = ImageOps.exif_transpose(source)
        source = source.convert("RGBA")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise LookRefused("That file is not an image this can read. A crest is a PNG or a JPG file.")

    source.thumbnail((CREST_SIDE, CREST_SIDE), Image.LANCZOS)
    square = Image.new("RGBA", (CREST_SIDE, CREST_SIDE), (0, 0, 0, 0))
    square.paste(source, ((CREST_SIDE - source.width) // 2, (CREST_SIDE - source.height) // 2), source)
    out = io.BytesIO()
    square.save(out, format="PNG", optimize=True)
    return out.getvalue()


def set_crest_as(actor, school, raw: bytes) -> ReportCardSettings:
    _require_authority(actor, school)
    crest = redraw_crest(raw)
    row, _ = ReportCardSettings.objects.get_or_create(pk=1)
    row.crest = crest
    row.save(update_fields=["crest", "updated_at"])
    return row


def clear_crest_as(actor, school) -> ReportCardSettings:
    _require_authority(actor, school)
    row, _ = ReportCardSettings.objects.get_or_create(pk=1)
    row.crest = None
    row.save(update_fields=["crest", "updated_at"])
    return row


# -- what the card prints ----------------------------------------------------


def initials(school_name: str) -> str:
    """"SD" for Sunrise Demo Academy, "SM" for St Mary's: two letters at most."""
    words = [w for w in re.split(r"[\s\-]+", school_name or "") if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper()


def for_card(school_name: str) -> dict:
    """What the card's header needs: the colour, and a crest or the initials."""
    row = settings()
    crest = bytes(row.crest) if row.crest else None
    return {
        "colour": row.colour or DEFAULT_COLOUR,
        "crest": f"data:image/png;base64,{base64.b64encode(crest).decode()}" if crest else None,
        "initials": initials(school_name),
    }


__all__ = [
    "DEFAULT_COLOUR",
    "LookRefused",
    "MAX_UPLOAD_BYTES",
    "NotAllowedToSetTheLook",
    "clean_colour",
    "clear_crest_as",
    "contrast_with_white",
    "for_card",
    "initials",
    "redraw_crest",
    "set_colour_as",
    "set_crest_as",
    "settings",
]
