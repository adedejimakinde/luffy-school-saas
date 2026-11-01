"""The design's rules, as far as a file can be checked for them.

`static/web/design.css` holds the palette, the font and the shared parts; each
page's stylesheet holds its layout and nothing else. These tests are what keep
that true after the first restyle, when "just this once" a page wants its own
shade of grey:

- **One palette, in one file.** Every colour literal in `design.css` is one of
  the palette's sixteen, and no stylesheet, module or page template anywhere
  else writes a colour of its own — they say `var(--muted)`, not `#5B6475`.
- **No gradients but the ones named below, no emoji, no icon pack.**
- **One font, two weights, served from here.** Hanken Grotesk at 400 and 700,
  `font-display: swap`, from files beside the stylesheet; and no stylesheet
  asks for a weight in between, which the browser would have to fake. Behind it,
  Noto Sans at the same two weights, cut to the few Hausa letters Hanken has no
  drawing of and fetched only by a page that has one; and every Nigerian letter,
  tone mark and the naira sign is drawn by one of the two, never by whatever
  font the phone happens to have (`tests/glyphs.py`).
- **Every page draws from it.** Each page template includes
  `templates/design/head.html`.

What a browser has to be asked — sideways scrolling, target sizes, text sizes
on a phone — is `tests/ui/screens.test.js`'s.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from tests import glyphs

ROOT = Path(settings.BASE_DIR)
STATIC = ROOT / "static"
DESIGN = STATIC / "web" / "design.css"

#: The whole palette: seven for the page, six for the three status labels.
PALETTE = {
    "#143D8C",  # brand: buttons, links, active nav, logo
    "#0E1726",  # text
    "#5B6475",  # secondary text
    "#F5F6F8",  # background
    "#FFFFFF",  # cards
    "#E3E6EB",  # borders
    "#EEF0F3",  # row dividers
    "#16693F", "#E7F4EC",  # green label
    "#8A5A00", "#FDF1DC",  # amber label
    "#B42318", "#FDECEA",  # red label
    # The public site's three accents, for its icon tiles and nothing else.
    "#0F766E",  # teal
    "#B45309",  # amber
    "#C2452D",  # coral
}

#: The only gradients, each of One Blue: the public site's final band, One Blue
#: deepening; the faintest blue on the hero photo's top edge and a faint glow
#: behind its screens, on the light top band; the staff sign-in's
#: background, One Blue fading into the grey; and the blog's tab row on a
#: phone, whose last 32px fade out so a tab past the edge reads as more to
#: scroll to. That last one is a mask, not a colour: only its opacity is drawn.
#: (file, selector)
GRADIENTS = {
    ("static/website/website.css", ".cta"),
    ("static/website/website.css", ".photo-hero::after"),
    ("static/website/website.css", ".hero-visual::before"),
    ("static/staff-signin/staff-signin.css", "body.door"),
    ("static/write/write.css", ".tabs"),
}

#: Page templates that are not drawn from `design.css`, and why.
NOT_ON_THE_DESIGN = {
    # Inline and asset-free on purpose (the file says why). Its colours are
    # still held to the palette below.
    "accounts/templates/403.html",
    # The rest of the error pages, which are the same: one frame, inline, so a
    # 500 does not depend on an asset (`errors/base.html` says why).
    "accounts/templates/errors/base.html",
    "accounts/templates/404.html",
    "accounts/templates/500.html",
    "accounts/templates/csrf_failure.html",
    # The report card PDF and the result-checker slips are WeasyPrint documents,
    # not pages. They are restyled last, in their own change, around the
    # school's own crest and colour.
    "results/templates/results/report_card.html",
    "results/templates/results/report_card_ogun.html",
    "results/templates/results/checker_slips.html",
    # The exam slips are the checker slips' twin (`cbt/pdf.py`), printed the same way.
    "cbt/templates/cbt/exam_slips.html",
}

#: Documents WeasyPrint draws, which are not pages a browser opens: they have no
#: head to put a doctype in front of, and no quirks mode to leave.
WEASYPRINT_DOCUMENTS = {
    "results/templates/results/report_card.html",
    "results/templates/results/report_card_ogun.html",
    "results/templates/results/checker_slips.html",
    "cbt/templates/cbt/exam_slips.html",
}

HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
FUNCTIONAL = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(", re.I)
NAMED = re.compile(
    r":\s*[^;{}]*\b(black|white|red|green|blue|gr[ae]y|orange|yellow|purple|pink|navy|silver|maroon)\b",
    re.I,
)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def page_templates():
    for path in sorted(ROOT.glob("*/templates/**/*.html")):
        yield str(path.relative_to(ROOT)), path.read_text()


def stylesheets():
    for path in sorted(STATIC.rglob("*.css")):
        yield str(path.relative_to(ROOT)), COMMENT.sub("", path.read_text())


def modules():
    for path in sorted(STATIC.rglob("*.js")):
        yield str(path.relative_to(ROOT)), path.read_text()


def style_blocks(html):
    return "".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))


def colours_in(css):
    """Hex literals, upper-cased; a module's `#127` issue number is not one."""
    return {h.upper() for h in HEX.findall(css) if len(h) in (4, 7, 9)}


class OnePaletteInOneFileTests(SimpleTestCase):
    def test_the_design_uses_the_palette_and_only_the_palette(self):
        css = COMMENT.sub("", DESIGN.read_text())

        self.assertEqual(colours_in(css), PALETTE)
        self.assertIsNone(FUNCTIONAL.search(css), "a colour written as a function")
        self.assertIsNone(NAMED.search(css), "a colour written as a name")

    def test_no_other_stylesheet_declares_a_colour(self):
        for name, css in stylesheets():
            if name == str(DESIGN.relative_to(ROOT)):
                continue
            with self.subTest(stylesheet=name):
                self.assertEqual(colours_in(css), set(), "use a design.css token")
                self.assertIsNone(FUNCTIONAL.search(css))
                self.assertIsNone(NAMED.search(css))

    def test_no_module_writes_a_colour_into_its_markup(self):
        for name, source in modules():
            with self.subTest(module=name):
                self.assertNotRegex(source, r"style=[\"'][^\"']*(#[0-9A-Fa-f]{3,6}|rgb|hsl)")

    def test_no_page_template_carries_colours_of_its_own(self):
        for name, html in page_templates():
            if name in NOT_ON_THE_DESIGN:
                continue
            with self.subTest(template=name):
                self.assertEqual(colours_in(style_blocks(html)), set())

    def test_the_error_pages_inline_colours_are_the_palettes(self):
        """The one frame with a copy, because it may not load an asset."""
        html = (ROOT / "accounts/templates/errors/base.html").read_text()
        used = colours_in(style_blocks(html))

        self.assertTrue(used, "the error pages are styled at all")
        self.assertLessEqual(used, PALETTE)

    def test_every_error_page_wears_that_frame(self):
        for name in ("403", "404", "500", "csrf_failure"):
            with self.subTest(page=name):
                html = (ROOT / f"accounts/templates/{name}.html").read_text()
                self.assertIn('{% extends "errors/base.html" %}', html)
                self.assertEqual(colours_in(style_blocks(html)), set())

    def test_no_gradients_but_the_named_ones(self):
        found = set()
        for name, css in [*stylesheets(), *((n, style_blocks(h)) for n, h in page_templates())]:
            for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if "gradient(" in body:
                    found.add((name, selector.strip()))
                    self.assertRegex(body, r"(linear-gradient\(\d+deg|radial-gradient\(closest-side), (var\(--brand\)|color-mix\(in srgb, var\(--brand\))", f"{name} {selector}")
        self.assertEqual(found, GRADIENTS)


class NoEmojiAndNoIconPackTests(SimpleTestCase):
    def test_no_emoji_in_any_page_module_stylesheet_or_template(self):
        files = [*modules(), *stylesheets(), *page_templates(), ("templates/design/head.html",
                 (ROOT / "templates/design/head.html").read_text())]
        for name, text in files:
            with self.subTest(file=name):
                self.assertIsNone(EMOJI.search(text))

    def test_no_icon_font_or_pack(self):
        """Icons are inline `<svg class="icon">` with strokes, drawn here."""
        for name, text in [*modules(), *page_templates()]:
            with self.subTest(file=name):
                self.assertNotRegex(text, r"material-icons|\bfa-|lucide|feather|bootstrap-icons")


class OneFontTwoWeightsTests(SimpleTestCase):
    def faces(self):
        return re.findall(r"@font-face\s*{(.*?)}", DESIGN.read_text(), re.S)

    def test_hanken_grotesk_and_the_noto_sans_behind_it_at_400_and_700_and_nothing_else(self):
        faces = self.faces()
        self.assertEqual(len(faces), 4)
        for face in faces:
            self.assertRegex(face, r'font-family: "(Hanken Grotesk|Noto Sans)"')
            self.assertIn("font-display: swap", face)
        for family in ("Hanken Grotesk", "Noto Sans"):
            with self.subTest(family=family):
                self.assertEqual(
                    sorted(
                        re.search(r"font-weight:\s*(\d+)", f).group(1)
                        for f in faces
                        if f'font-family: "{family}"' in f
                    ),
                    ["400", "700"],
                )

    def test_each_face_is_a_file_beside_the_stylesheet(self):
        """Self-hosted: a school's host serves the font, and nobody else is asked."""
        for face in self.faces():
            with self.subTest(face=face[:80]):
                (source,) = re.findall(r'url\("([^"]+)"\)', face)
                self.assertNotRegex(source, r"^(https?:)?//")
                self.assertTrue((DESIGN.parent / source).is_file(), source)

        on_disk = sorted(p.name for p in (STATIC / "web" / "fonts").glob("*.woff2"))
        self.assertEqual(
            on_disk,
            [
                "hanken-grotesk-400.woff2",
                "hanken-grotesk-700.woff2",
                # The school websites' headings (`docs/school-sites-theme-modern.md`),
                # declared by the theme's own stylesheet, not here (below).
                "hanken-grotesk-800.woff2",
                "noto-sans-hausa-400.woff2",
                "noto-sans-hausa-700.woff2",
            ],
        )

    def test_the_websites_heading_weight_is_hankens_own_cut_over_the_same_letters(self):
        """Modern Campus sets its headings at 800 (`static/schoolsite/modern.css`): the same cut
        (`scripts/fonts.py`), the same letters as the 400 face here, and the same `prep`."""
        from fontTools.ttLib import TTFont

        theme_css = (STATIC / "schoolsite" / "modern.css").read_text()
        (face,) = re.findall(r"@font-face\s*{(.*?)}", theme_css, re.S)
        self.assertIn('font-family: "Hanken Grotesk"', face)
        self.assertIn("font-weight: 800", face)
        self.assertIn("font-display: swap", face)
        self.assertIn('url("../web/fonts/hanken-grotesk-800.woff2")', face)
        regular = next(f for f in self.faces() if "font-weight: 400" in f and "Hanken" in f)
        ranges = [re.sub(r"\s+", " ", re.search(r"unicode-range:\s*([^;]+);", f).group(1)) for f in (face, regular)]
        self.assertEqual(ranges[0], ranges[1])
        heavy, light = (TTFont(STATIC / "web" / "fonts" / f"hanken-grotesk-{w}.woff2") for w in (800, 400))
        self.assertEqual(set(heavy.getBestCmap()), set(light.getBestCmap()))
        self.assertEqual(heavy["OS/2"].usWeightClass, 800)
        self.assertIn("prep", heavy)

    def test_the_font_falls_back_to_noto_and_then_the_systems_own(self):
        self.assertRegex(DESIGN.read_text(), r'--font:\s*"Hanken Grotesk",\s*"Noto Sans",\s*system-ui')

    def test_no_stylesheet_asks_for_a_weight_that_is_not_there(self):
        """400 and 700 everywhere; 800 only in the school websites' theme, which ships its face."""
        for name, css in stylesheets():
            with self.subTest(stylesheet=name):
                there = {"400", "700", "normal", "bold", "inherit"}
                if name == "static/schoolsite/modern.css":
                    there |= {"800", "var(--heavy)"}
                for weight in re.findall(r"font-weight:\s*([^;}\s]+)", css):
                    self.assertIn(weight, there)

    def test_the_licences_ship_with_the_fonts(self):
        """SIL Open Font License 1.1: the files may be redistributed with it."""
        for licence, family in (("OFL.txt", "Hanken Grotesk"), ("OFL-noto-sans.txt", "Noto Project")):
            with self.subTest(licence=licence):
                text = (STATIC / "web" / "fonts" / licence).read_text()
                self.assertIn("SIL Open Font License, Version 1.1", text)
                self.assertIn(family, text)


class EveryNigerianLetterHasADrawingTests(SimpleTestCase):
    """A letter no face draws is drawn in the phone's own font, and nothing says so."""

    def test_every_letter_mark_name_and_amount_is_drawn_by_a_face_of_ours_at_both_weights(self):
        for weight in (400, 700):
            for character in glyphs.CHARACTERS:
                with self.subTest(weight=weight, character=f"U+{ord(character):04X} {character}"):
                    self.assertTrue(
                        glyphs.covering(character, weight),
                        "in no face's range and file: the browser would draw it in a system font",
                    )

    def test_every_letter_a_file_holds_can_be_asked_of_it(self):
        """A glyph outside its face's `unicode-range` is never used: dead bytes, and a letter that looks covered."""
        for face in glyphs.faces():
            with self.subTest(file=face["file"]):
                unreachable = sorted(
                    c for c in glyphs.cmap_of(face["file"])
                    if c > 0x20 and not glyphs.in_range(face, chr(c))
                )
                self.assertEqual([f"U+{c:04X}" for c in unreachable], [])

    def test_noto_is_fetched_only_for_what_hanken_cannot_draw(self):
        """Disjoint ranges: a page with no Hausa hook never asks for the second face."""
        hanken = [f for f in glyphs.faces() if f["family"] == "Hanken Grotesk"]
        noto = [f for f in glyphs.faces() if f["family"] == "Noto Sans"]
        for face in noto:
            for other in hanken:
                for low, high in face["ranges"]:
                    for point in range(low, high + 1):
                        self.assertFalse(glyphs.in_range(other, chr(point)), f"U+{point:04X} is in both")

    def test_the_noto_faces_are_sized_and_spaced_to_hanken(self):
        """A Hausa hook in a line of Hanken is the line's height and the letters' size.

        `size-adjust` scales Noto to Hanken's x-height, and its ascent and descent are
        Hanken's, divided by that scale because the browser multiplies them by it (the
        formula Next.js writes its fallback fonts with). Noto's own line gap is nil, so
        none is overridden. Each number is read from the files, so a recut font that
        moves them fails here rather than showing as a line that grows.
        """
        from fontTools.ttLib import TTFont

        for face in glyphs.faces():
            if face["family"] != "Noto Sans":
                continue
            hanken = TTFont(glyphs.FONTS / f"hanken-grotesk-{face['weight']}.woff2")
            noto = TTFont(glyphs.FONTS / face["file"])
            with self.subTest(file=face["file"]):
                size = float(re.search(r"size-adjust:\s*([\d.]+)%", face["body"]).group(1)) / 100
                ascent = float(re.search(r"ascent-override:\s*([\d.]+)%", face["body"]).group(1)) / 100
                descent = float(re.search(r"descent-override:\s*([\d.]+)%", face["body"]).group(1)) / 100
                x = hanken["glyf"][hanken.getBestCmap()[ord("x")]]
                x.recalcBounds(hanken["glyf"])
                self.assertAlmostEqual(size, x.yMax / noto["OS/2"].sxHeight, delta=0.005)
                self.assertAlmostEqual(ascent * size, hanken["hhea"].ascent / hanken["head"].unitsPerEm, delta=0.005)
                self.assertAlmostEqual(descent * size, -hanken["hhea"].descent / hanken["head"].unitsPerEm, delta=0.005)
                self.assertEqual((noto["hhea"].lineGap, noto["OS/2"].sTypoLineGap), (0, 0))
                self.assertNotIn("line-gap-override", face["body"])

    def test_the_letters_hanken_draws_itself_are_not_left_to_noto(self):
        """Where Yoruba and Igbo's marked letters and the naira sign come from: Hanken's own drawing."""
        for character in "ẹọṣẸỌṢịụṅỊỤṄ₦ʼ" + glyphs.MARKS:
            with self.subTest(character=f"U+{ord(character):04X}"):
                self.assertEqual(glyphs.covering(character), ["Hanken Grotesk"])
        for character in "ɓɗƙƴƁƊƘƳǹǸ":
            with self.subTest(character=f"U+{ord(character):04X}"):
                self.assertEqual(glyphs.covering(character), ["Noto Sans"])

    def test_every_font_file_keeps_its_prep_so_the_platform_does_not_hint_it_itself(self):
        """What a cut must not drop: the one-line `prep` of an unhinted font.

        A TrueType font with no instructions at all is one FreeType hints with its
        auto-hinter, and on a machine with medium or full hinting and no subpixel
        positioning that rounds every glyph's advance. The first cut of these files
        had no `prep`: bold came out 1.6% wider on CI, and the Ogun card's 294px
        health table at 360px, which has no width to spare, overflowed by 4px
        (`tests/ui/screens.test.js`, "cards"). `scripts/fonts.py` keeps it.
        """
        from fontTools.ttLib import TTFont

        for face in glyphs.faces():
            with self.subTest(file=face["file"]):
                font = TTFont(glyphs.FONTS / face["file"])
                self.assertIn("prep", font)
                self.assertEqual(font["maxp"].maxSizeOfInstructions, 0, "glyph programs are not worth their bytes here")


#: `{% extends "app/layout.html" %}`: a page drawn inside a layout, which is
#: where its head is.
EXTENDS = re.compile(r'^\s*{%\s*extends\s+"([^"]+)"\s*%}')


def is_a_part(name):
    """A piece included into pages (a drawing, a fragment): not a page itself.

    Kept in a `parts/` folder so that this is a fact about where the file is,
    not a list here to keep up to date.
    """
    return "/parts/" in name


def own_head(name, html):
    """The template that carries this page's head: itself, or its layout's."""
    match = EXTENDS.match(html)
    if not match:
        return html
    (layout,) = [path for path in ROOT.glob(f"*/templates/{match.group(1)}")]
    return own_head(match.group(1), layout.read_text())


class EveryPageDrawsFromTheDesignTests(SimpleTestCase):
    def test_every_page_template_includes_the_design_head(self):
        for name, html in page_templates():
            if name in NOT_ON_THE_DESIGN or is_a_part(name):
                continue
            with self.subTest(template=name):
                self.assertIn('{% include "design/head.html" %}', own_head(name, html))

    def test_every_page_opens_with_a_doctype_and_a_language(self):
        """`design/doc_open.html`, or the same two lines written out in a layout.

        A page that starts at `<meta charset>` is laid out in quirks mode and has
        no language for a screen reader (WCAG 3.1.1).
        """
        for name, html in page_templates():
            if name in WEASYPRINT_DOCUMENTS or is_a_part(name):
                continue
            with self.subTest(template=name):
                head = own_head(name, html)
                shared = '{% include "design/doc_open.html" %}' in head
                written = re.search(r"<!doctype html>\s*<html lang=\"en\">", head, re.I)
                self.assertTrue(shared or written, "no doctype and lang")

    def test_a_part_draws_no_head_and_a_layout_is_followed(self):
        """The control for the two allowances above: each is used, and narrowly."""
        names = dict(page_templates())
        parts = [name for name in names if is_a_part(name)]
        self.assertTrue(parts, "no part to allow")
        for name in parts:
            with self.subTest(part=name):
                self.assertNotIn("<html", names[name])
                self.assertNotIn("<link", names[name])
        extending = [name for name, html in names.items() if EXTENDS.match(html)]
        self.assertTrue(extending, "no page extends a layout")

    def test_the_design_comes_before_the_pages_own_stylesheet(self):
        """So the page's rules narrow the design's, and not the other way round."""
        for name, html in page_templates():
            if name in NOT_ON_THE_DESIGN or 'rel="stylesheet"' not in html:
                continue
            with self.subTest(template=name):
                self.assertLess(
                    html.index('{% include "design/head.html" %}'),
                    html.index('rel="stylesheet"'),
                )
