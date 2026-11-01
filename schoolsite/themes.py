"""Which themes exist, and the only options a school may set on each.

A theme's look is a directory of templates and one stylesheet. There is one,
Modern Campus (`docs/school-sites-theme-modern.md`), which replaced the starter
theme's look in its place: a school that chose "starter" now has "modern"
(`migrations/0005`), and an older revision naming "starter" is drawn in it
(`render.theme_of`). What a school *chooses* is held to a list: a theme key
from `THEMES`, and per theme, option names and values from that theme's own
allow-list. A colour is six hex digits; an animated background is on or off.
Nothing a school sends is ever kept as markup, CSS or a free string a template
would print.

**Colours.** A school sets four, each checked here before anything is kept,
against the palette the theme will actually draw (what the school chose, the
theme's own colours for the rest):

- primary, from the crest: white writing on it reads (4.5:1);
- accent, the main call to action: the dark band's colour, which is its
  button's writing, reads on it (4.5:1);
- dark, the one dark band: white writing on it reads (4.5:1);
- detail, the gold of the line art: decoration only, never writing, and it must
  show on the dark band (3:1).

The tinted panels are not chosen: `palette()` works them out from the primary
and the accent (a mint panel is fixed), and the body text must read on every
one of them (4.5:1), as on the page's surface.

**Animated backgrounds**, five, each switched on or off per school
(`ANIMATIONS`); a school that has not chosen has them on.

Adding a theme is adding an entry here, with no migration: the theme key is
checked here rather than by a database constraint for that reason.
"""

import colorsys
import re
from dataclasses import dataclass, field

from .errors import SiteRefused

#: Every colour role a theme may draw with (§3.1). A theme need not use all.
COLOUR_ROLES = ("primary", "secondary", "accent", "surface", "text", "detail", "dark")

#: WCAG AA for body text: text on its surface must read.
MIN_TEXT_CONTRAST = 4.5
#: WCAG AA for what is not writing: the line art's gold on the dark band.
MIN_DETAIL_CONTRAST = 3.0

WHITE = "#FFFFFF"

#: The five animated backgrounds (`docs/school-sites-theme-modern.md`), each a
#: school's to switch off, in the order the editor lists them.
ANIMATIONS = {
    "hero": "Hero: orbits and the node triangle",
    "academics": "Academics: rings and a dashed gold ring",
    "student_life": "Student life: a constellation on the dark band",
    "admissions": "Admissions band: orbits and a pulsing centre",
    "contact": "Visit us: a route to the school's pin",
}

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
    #: The `sizes` attribute of each place a picture is drawn (§4.2): how wide
    #: the theme draws it, so a phone fetches the size it needs and no larger.
    sizes: dict = None
    #: Whether a phone may be sent the hero's video (§9.2). Off: phones get the poster.
    video_on_phones: bool = False
    #: The colours it draws with where a school has chosen none.
    colours: dict = field(default_factory=dict)
    #: The font file preloaded with the page: the face its headings are set in.
    heading_font: str = ""


#: Modern Campus, the one designed theme (decided 25 October 2026: one theme,
#: with strong options).
THEMES = {
    "modern": Theme(
        name="Modern Campus",
        header_styles=("sticky",),
        font_pairings=("hanken",),
        stylesheet="schoolsite/modern.css",
        fonts=(
            "web/fonts/hanken-grotesk-400.woff2",
            "web/fonts/hanken-grotesk-800.woff2",
            "web/fonts/noto-sans-hausa-400.woff2",
            "web/fonts/noto-sans-hausa-700.woff2",
        ),
        heading_font="web/fonts/hanken-grotesk-800.woff2",
        # The page is at most 72rem (1152px) wide, 16px a side on a phone. The
        # hero's slideshow is the right half beside its words from 860px, the
        # whole width under them on a phone.
        sizes={
            "hero": "(min-width: 72rem) 34rem, (min-width: 54rem) 46vw, calc(100vw - 32px)",
            "portrait": "(min-width: 54rem) 20rem, calc(100vw - 32px)",
            "grid": "(min-width: 72rem) 17rem, (min-width: 54rem) 23vw, calc(50vw - 22px)",
            "tall": "(min-width: 72rem) 35rem, (min-width: 54rem) 48vw, calc(100vw - 32px)",
            "strip": "(min-width: 54rem) 16rem, 60vw",
            "cover": "(min-width: 54rem) 22rem, calc(100vw - 32px)",
        },
        colours={
            "primary": "#143D8C",
            "accent": "#FFD66B",
            "detail": "#C9A24A",
            "dark": "#0F1B33",
            "surface": "#FFFFFF",
            "text": "#0F1B33",
        },
    ),
}

DEFAULT_THEME = "modern"

#: The theme key a school had before Modern Campus, drawn as Modern Campus.
FORMER_THEMES = {"starter": "modern"}

#: The demo's colours, which every school that was on the starter theme was
#: given (`migrations/0005`), keeping its own primary.
DEMO_COLOURS = {"accent": "#FFD66B", "detail": "#C9A24A", "dark": "#0F1B33"}

#: The mint panel, the one tint not worked out from the school's colours.
MINT = "#E8F6EF"


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


def _tint(colour, lightness, saturation_cap):
    """A pale panel of `colour`'s hue: the given lightness, its saturation held under the cap."""
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, _, saturation = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(hue, lightness, min(saturation, saturation_cap))
    return "#" + "".join(f"{round(c * 255):02X}" for c in (r, g, b))


def palette(key, options=None) -> dict:
    """Every colour the theme draws with, for these options: chosen, the theme's own, and the tints.

    The tints: a pale panel of the primary's hue (`tint`, #EEF3FC for the demo's
    navy), one of the accent's (`warm`, #FFF6DC for its yellow), a near-grey of
    the primary's (`mist`, #F1F4F9), and the fixed mint.
    """
    chosen = theme(key)
    colours = {**chosen.colours, **((options or {}).get("colours") or {})}
    colours.setdefault("surface", WHITE)
    colours.setdefault("text", colours.get("dark", "#0F1B33"))
    colours["tint"] = _tint(colours["primary"], 0.96, 0.71)
    colours["warm"] = _tint(colours["accent"], 0.931, 1.0)
    colours["mist"] = _tint(colours["primary"], 0.96, 0.33)
    colours["mint"] = MINT
    return colours


def animations(options=None) -> dict:
    """Each animated background on or off, for these options: on unless the school switched it off."""
    chosen = (options or {}).get("animations") or {}
    return {name: chosen.get(name, True) is not False for name in ANIMATIONS}


def full_options(key, options=None) -> dict:
    """`options` with every colour role a school sets and every switch filled in, as a school
    moved from the starter theme was given them: how two snapshots are compared (`services`)."""
    options = dict(options or {})
    colours = {**DEMO_COLOURS, **(options.get("colours") or {})}
    options["colours"] = colours
    options["animations"] = animations(options)
    return options


def check_palette(colours):
    """Refuse a palette whose writing would not read: the checks the module's docstring lists."""
    checks = (
        (WHITE, colours["primary"], MIN_TEXT_CONTRAST,
         f"{colours['primary']} is too light for white writing on it to read. Choose a darker main colour."),
        (WHITE, colours["dark"], MIN_TEXT_CONTRAST,
         f"{colours['dark']} is too light for white writing on the dark band. Choose a darker colour."),
        (colours["dark"], colours["accent"], MIN_TEXT_CONTRAST,
         f"The writing on {colours['accent']} buttons would be too hard to read. Choose a lighter or "
         "stronger accent colour, or a darker band colour."),
        (colours["detail"], colours["dark"], MIN_DETAIL_CONTRAST,
         f"The detail colour {colours['detail']} would not show on the dark band. Choose a brighter detail colour."),
    )
    for ink, ground, least, sentence in checks:
        if contrast(ink, ground) < least:
            raise ThemeRefused(sentence)
    for panel in ("surface", "tint", "warm", "mist", "mint"):
        if contrast(colours["text"], colours[panel]) < MIN_TEXT_CONTRAST:
            if panel == "surface":
                raise ThemeRefused(
                    f"Text in {colours['text']} on {colours['surface']} is too hard to read. Choose a darker "
                    "text colour or a lighter background."
                )
            raise ThemeRefused(
                f"Text in {colours['text']} would be too hard to read on the pale panels made from your "
                "colours. Choose a darker text colour."
            )


def clean_options(key, options) -> dict:
    """A theme's options as they may be stored: allow-listed names and values only.

    `options` may name `header_style`, `font_pairing`, `colours` (a mapping of
    `COLOUR_ROLES` to hex colours) and `animations` (a mapping of `ANIMATIONS`
    to on or off). Anything else is refused, not dropped: a school is told its
    choice was not kept rather than finding it missing. The colours are checked
    together with the theme's own for the roles not chosen (`check_palette`).
    """
    chosen = theme(key)
    if not isinstance(options, dict):
        raise ThemeRefused("Theme options are a set of named choices.")
    unknown = set(options) - {"header_style", "font_pairing", "colours", "animations"}
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
            raise ThemeRefused("Colours are named by their role: primary, accent, detail and dark.")
        unknown = set(colours) - set(COLOUR_ROLES)
        if unknown:
            raise ThemeRefused(f"{_one(unknown)} is not a colour role.")
        cleaned["colours"] = {role: clean_colour(colours[role]) for role in COLOUR_ROLES if role in colours}
    if "animations" in options:
        switches = options["animations"]
        if not isinstance(switches, dict):
            raise ThemeRefused("The animated backgrounds are each switched on or off.")
        unknown = set(switches) - set(ANIMATIONS)
        if unknown:
            raise ThemeRefused(f"{_one(unknown)} is not one of the animated backgrounds.")
        if any(not isinstance(v, bool) for v in switches.values()):
            raise ThemeRefused("Each animated background is on or off.")
        cleaned["animations"] = {name: switches[name] for name in ANIMATIONS if name in switches}
    check_palette(palette(key, cleaned))
    return cleaned


def _one(names) -> str:
    """One name from a set of unknown ones, for a sentence, shortened so it cannot be a page."""
    name = sorted(str(n) for n in names)[0]
    return repr(name[:40])


__all__ = [
    "ANIMATIONS",
    "COLOUR_ROLES",
    "DEMO_COLOURS",
    "FORMER_THEMES",
    "DEFAULT_THEME",
    "THEMES",
    "Theme",
    "ThemeRefused",
    "animations",
    "check_palette",
    "clean_colour",
    "clean_options",
    "contrast",
    "full_options",
    "palette",
    "theme",
]
