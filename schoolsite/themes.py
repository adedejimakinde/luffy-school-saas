"""Which themes exist, and the only options a school may set on each.

A theme's look is a directory of templates and one stylesheet, and none exists
yet: the starter theme arrives in PR 3 and the three designed ones after the
design round (`docs/school-sites.md` §3). What a school *chooses* is stored now,
so it has to be held to a list now: a theme key from `THEMES`, and per theme,
option names and values from that theme's own allow-list. A colour is six hex
digits. Nothing a school sends is ever kept as markup, CSS or a free string a
template would print.

Adding a theme is adding an entry here, with no migration: the theme key is
checked here rather than by a database constraint for that reason.
"""

import re
from dataclasses import dataclass

from .errors import SiteRefused

#: Every colour role a theme may draw with (§3.1). A theme need not use all.
COLOUR_ROLES = ("primary", "secondary", "accent", "surface", "text")

#: WCAG AA for body text: text on its surface must read.
MIN_TEXT_CONTRAST = 4.5

_HEX = re.compile(r"^#[0-9A-F]{6}$")


class ThemeRefused(SiteRefused):
    """A theme or a theme option this platform does not offer. The message is for the person."""


@dataclass(frozen=True)
class Theme:
    name: str
    header_styles: tuple
    font_pairings: tuple
    #: Its stylesheet and its font files, under `static/`: what the theme
    #: contract weighs and checks the Nigerian alphabets against (§3.3, §11.2).
    stylesheet: str
    fonts: tuple


#: The starter theme is the plain design system (PR 3). The design round adds
#: the others here, each with its own header styles and font pairings.
THEMES = {
    "starter": Theme(
        name="Starter",
        header_styles=("solid",),
        font_pairings=("default",),
        stylesheet="schoolsite/starter.css",
        fonts=("web/fonts/hanken-grotesk-400.woff2", "web/fonts/hanken-grotesk-700.woff2"),
    ),
}

DEFAULT_THEME = "starter"


def theme(key):
    """The theme named `key`, or `ThemeRefused`."""
    if not isinstance(key, str) or key not in THEMES:
        raise ThemeRefused("That is not one of the themes on offer.")
    return THEMES[key]


def _luminance(hex_colour: str) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def clean_colour(value) -> str:
    """`#RRGGBB` in capitals, or `ThemeRefused`. Nothing else is a colour here."""
    if not isinstance(value, str):
        raise ThemeRefused("A colour is six hex digits, like #143D8C.")
    colour = value.strip().upper()
    if not colour.startswith("#"):
        colour = f"#{colour}"
    if not _HEX.match(colour):
        raise ThemeRefused("A colour is six hex digits, like #143D8C.")
    return colour


def clean_options(key, options) -> dict:
    """A theme's options as they may be stored: allow-listed names and values only.

    `options` may name `header_style`, `font_pairing` and `colours` (a mapping of
    `COLOUR_ROLES` to hex colours). Anything else is refused, not dropped: a
    school is told its choice was not kept rather than finding it missing.
    """
    chosen = theme(key)
    if not isinstance(options, dict):
        raise ThemeRefused("Theme options are a set of named choices.")
    unknown = set(options) - {"header_style", "font_pairing", "colours"}
    if unknown:
        raise ThemeRefused(f"{_one(unknown)} is not an option of the {chosen.name} theme.")
    cleaned = {}
    if "header_style" in options:
        if options["header_style"] not in chosen.header_styles:
            raise ThemeRefused(f"The {chosen.name} theme has no such header style.")
        cleaned["header_style"] = options["header_style"]
    if "font_pairing" in options:
        if options["font_pairing"] not in chosen.font_pairings:
            raise ThemeRefused(f"The {chosen.name} theme has no such font pairing.")
        cleaned["font_pairing"] = options["font_pairing"]
    if "colours" in options:
        colours = options["colours"]
        if not isinstance(colours, dict):
            raise ThemeRefused("Colours are named by their role: primary, secondary, accent, surface, text.")
        unknown = set(colours) - set(COLOUR_ROLES)
        if unknown:
            raise ThemeRefused(f"{_one(unknown)} is not a colour role.")
        cleaned_colours = {role: clean_colour(colours[role]) for role in COLOUR_ROLES if role in colours}
        text, surface = cleaned_colours.get("text"), cleaned_colours.get("surface")
        if text and surface and contrast(text, surface) < MIN_TEXT_CONTRAST:
            raise ThemeRefused(
                f"Text in {text} on {surface} is too hard to read. Choose a darker text colour "
                f"or a lighter background."
            )
        cleaned["colours"] = cleaned_colours
    return cleaned


def _one(names) -> str:
    """One name from a set of unknown ones, for a sentence, shortened so it cannot be a page."""
    name = sorted(str(n) for n in names)[0]
    return repr(name[:40])


__all__ = [
    "COLOUR_ROLES",
    "DEFAULT_THEME",
    "THEMES",
    "Theme",
    "ThemeRefused",
    "clean_colour",
    "clean_options",
    "contrast",
    "theme",
]
