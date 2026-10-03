"""The design's rules, as far as a file can be checked for them.

`static/web/design.css` holds the palette, the font and the shared parts; each
page's stylesheet holds its layout and nothing else. These tests are what keep
that true after the first restyle, when "just this once" a page wants its own
shade of grey:

- **One palette, in one file.** Every colour literal in `design.css` is one of
  the palette's thirteen, and no stylesheet, module or page template anywhere
  else writes a colour of its own — they say `var(--muted)`, not `#5B6475`.
- **No gradients, no emoji, no icon pack.**
- **One font, two weights, served from here.** Hanken Grotesk at 400 and 700,
  `font-display: swap`, from files beside the stylesheet; and no stylesheet
  asks for a weight in between, which the browser would have to fake.
- **Every page draws from it.** Each page template includes
  `templates/design/head.html`.

What a browser has to be asked — sideways scrolling, target sizes, text sizes
on a phone — is `tests/ui/screens.test.js`'s.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

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
}

#: Page templates that are not drawn from `design.css`, and why.
NOT_ON_THE_DESIGN = {
    # Inline and asset-free on purpose (the file says why). Its colours are
    # still held to the palette below.
    "accounts/templates/403.html",
    # The report card PDF and the result-checker slips are WeasyPrint documents,
    # not pages. They are restyled last, in their own change, around the
    # school's own crest and colour.
    "results/templates/results/report_card.html",
    "results/templates/results/checker_slips.html",
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

    def test_the_403_pages_inline_colours_are_the_palettes(self):
        """The one page with a copy, because it may not load an asset."""
        html = (ROOT / "accounts/templates/403.html").read_text()
        used = colours_in(style_blocks(html))

        self.assertTrue(used, "the 403 page is styled at all")
        self.assertLessEqual(used, PALETTE)

    def test_no_gradients_anywhere(self):
        for name, css in [*stylesheets(), *((n, style_blocks(h)) for n, h in page_templates())]:
            with self.subTest(file=name):
                self.assertNotIn("gradient(", css)


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

    def test_hanken_grotesk_at_400_and_700_and_nothing_else(self):
        faces = self.faces()
        self.assertEqual(len(faces), 2)
        for face in faces:
            self.assertIn('font-family: "Hanken Grotesk"', face)
            self.assertIn("font-display: swap", face)
        self.assertEqual(
            sorted(re.search(r"font-weight:\s*(\d+)", f).group(1) for f in faces), ["400", "700"]
        )

    def test_each_face_is_a_file_beside_the_stylesheet(self):
        """Self-hosted: a school's host serves the font, and nobody else is asked."""
        for face in self.faces():
            with self.subTest(face=face[:80]):
                (source,) = re.findall(r'url\("([^"]+)"\)', face)
                self.assertNotRegex(source, r"^(https?:)?//")
                self.assertTrue((DESIGN.parent / source).is_file(), source)

        on_disk = sorted(p.name for p in (STATIC / "web" / "fonts").glob("*.woff2"))
        self.assertEqual(on_disk, ["hanken-grotesk-400.woff2", "hanken-grotesk-700.woff2"])

    def test_the_font_falls_back_to_the_systems_own(self):
        self.assertRegex(DESIGN.read_text(), r'--font:\s*"Hanken Grotesk",\s*system-ui')

    def test_no_stylesheet_asks_for_a_weight_that_is_not_there(self):
        for name, css in stylesheets():
            with self.subTest(stylesheet=name):
                for weight in re.findall(r"font-weight:\s*([^;}\s]+)", css):
                    self.assertIn(weight, {"400", "700", "normal", "bold", "inherit"})

    def test_the_licence_ships_with_the_font(self):
        """SIL Open Font License 1.1: the files may be redistributed with it."""
        licence = (STATIC / "web" / "fonts" / "OFL.txt").read_text()
        self.assertIn("SIL Open Font License, Version 1.1", licence)
        self.assertIn("Hanken Grotesk", licence)


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
