"""What a post's Markdown may turn into (`blog.markdown`)."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from blog import markdown

KEY = "a" * 32
OTHER = "b" * 32
IMAGES = {KEY: SimpleNamespace(key=KEY, width=1600, height=900)}


def render(text):
    return markdown.render(text, images=IMAGES)


class TheSanitiserTests(SimpleTestCase):
    def test_a_script_tag_is_stripped_with_what_is_inside_it(self):
        html = render("Hello <script>alert('x')</script> world\n\n<script src=\"//evil/x.js\"></script>")
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("alert", html)
        self.assertNotIn("evil", html)
        self.assertIn("Hello", html)
        self.assertIn("world", html)

    def test_frames_objects_forms_and_svg_go(self):
        html = render(
            '<iframe src="https://evil"></iframe><object data="x"></object><embed src="x">'
            '<form action="/x"><input name="a"></form><svg onload="alert(1)"><circle/></svg>'
            "<style>body{display:none}</style>"
        )
        for gone in ("<iframe", "<object", "<embed", "<form", "<input", "<svg", "onload", "<style", "display:none"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, html)

    def test_every_inline_event_handler_and_style_is_dropped(self):
        html = render('<p onclick="x" onmouseover="y" style="color:red" class="z">Words</p><a href="https://example.com" onfocus="x">a</a>')
        for gone in ("onclick", "onmouseover", "onfocus", "style=", "class="):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, html)
        self.assertIn('href="https://example.com"', html)

    def test_only_web_and_mail_links(self):
        html = render("[a](javascript:alert(1)) [b](data:text/html,x) [c](mailto:hello@classnode.co) [d](https://classnode.co)")
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:", html)
        self.assertIn('href="mailto:hello@classnode.co"', html)
        self.assertIn('href="https://classnode.co"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_a_code_block_shows_markup_as_text(self):
        html = render("```\n<script>x</script>\n```")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)


class PicturesTests(SimpleTestCase):
    def test_this_posts_picture_is_drawn_sized_described_and_lazy(self):
        html = render(f"![A chart of fees](image:{KEY})")
        self.assertIn(
            f'<img src="/blog/images/{KEY}.webp" alt="A chart of fees" width="1600" height="900" '
            'loading="lazy" decoding="async">',
            html,
        )

    def test_any_other_picture_is_dropped(self):
        html = render(
            f"![x](image:{OTHER}) ![y](https://example.com/a.png) <img src=\"https://example.com/b.png\">"
            "<IMG SRC='https://example.com/c.png'>"
        )
        self.assertNotIn("<img", html.lower())
        self.assertNotIn("example.com", html)

    def test_the_portal_draws_the_same_picture_from_its_own_address(self):
        html = markdown.render(f"![A chart](image:{KEY})", images=IMAGES, base="/write/images/")
        self.assertIn(f'src="/write/images/{KEY}.webp"', html)

    def test_pictures_with_no_description_are_found(self):
        self.assertEqual(markdown.images_without_alt(f"![](image:{KEY}) ![ok](image:{OTHER})"), [KEY])
        self.assertEqual(markdown.image_keys(f"![a](image:{KEY}) ![b](image:{KEY})"), [KEY])


class ShapeTests(SimpleTestCase):
    def test_headings_start_at_h2(self):
        html = render("# One\n\n## Two\n\n### Three")
        self.assertNotIn("<h1", html)
        self.assertIn("<h2>One</h2>", html)
        self.assertIn("<h2>Two</h2>", html)
        self.assertIn("<h3>Three</h3>", html)

    def test_a_table_sits_in_its_own_scroller(self):
        html = render("| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertIn('<div class="post-table"><table>', html)
        self.assertIn("</table></div>", html)

    def test_words_are_the_readers_not_the_markups(self):
        self.assertEqual(markdown.words("## Two words\n\n**three more words** <script>not these</script>"), 5)
