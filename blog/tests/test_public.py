"""classnode.co/blog/: what is public, what never is, and what each post tells search engines."""

import json
import re
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.utils import timezone

from blog import workflow
from blog.models import Status

from .fixtures import BlogSetUp, SITE

STATIC = Path(settings.BASE_DIR) / "static"


class EmptyBlogTests(BlogSetUp):
    def test_it_says_the_first_posts_are_coming_and_nothing_else(self):
        response = self.site("/blog/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "First posts coming soon")
        self.assertNotContains(response, 'class="post-card"')
        self.assertNotContains(response, 'class="post-lead"')

    def test_drafts_and_posts_in_review_do_not_count(self):
        self.draft(slug="a-draft")
        self.in_review(slug="a-review")
        self.assertContains(self.site("/blog/"), "First posts coming soon")

    def test_nothing_is_seeded(self):
        """The blog ships empty: no migration or command makes a post or a writer."""
        from accounts.models import User
        from blog.models import Post

        self.assertEqual(
            set(User.objects.exclude(blog_role="").values_list("email", flat=True)),
            {self.writer.email, self.other_writer.email, self.editor.email},
        )
        self.assertFalse(Post.objects.exists())


class DraftsAreNeverPublicTests(BlogSetUp):
    def test_a_draft_or_a_post_in_review_is_a_404_everywhere_on_the_site(self):
        for post in (self.draft(slug="still-a-draft"), self.in_review(slug="still-in-review")):
            with self.subTest(status=post.status):
                self.assertEqual(self.site(f"/blog/{post.slug}/").status_code, 404)
                self.assertEqual(self.site(f"/blog/images/{post.cover.key}.webp").status_code, 404)
                self.assertEqual(self.site(f"/blog/images/{post.cover.key}-small.webp").status_code, 404)
                self.assertNotContains(self.site("/blog/"), post.slug)
                self.assertNotIn(post.slug, self.site("/sitemap.xml").content.decode())

    def test_only_published_posts_are_in_the_sitemap_and_each_once(self):
        live = self.published(slug="live")
        self.draft(slug="draft-two")
        self.in_review(slug="review-two")
        sitemap = self.site("/sitemap.xml").content.decode()
        listed = re.findall(r"<loc>https://classnode\.testserver/blog/([^<]+)/</loc>", sitemap)
        self.assertEqual(listed, [live.slug])
        self.assertIn(f"<lastmod>{timezone.localtime(live.updated_at):%Y-%m-%d}</lastmod>", sitemap)
        self.assertIn("<loc>https://classnode.testserver/blog/</loc>", sitemap)

    def test_the_sitemap_lastmod_is_the_site_date_late_in_the_utc_evening(self):
        """23:30 UTC is already tomorrow in Africa/Lagos, and the sitemap says so."""
        with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 23, 23, 30, tzinfo=dt_timezone.utc)):
            live = self.published(slug="late")
        sitemap = self.site("/sitemap.xml").content.decode()
        self.assertIn("<lastmod>2026-10-24</lastmod>", sitemap)
        self.assertIn(f"<lastmod>{timezone.localtime(live.updated_at):%Y-%m-%d}</lastmod>", sitemap)

    def test_unpublished_is_off_the_site_list_and_sitemap(self):
        post = self.published(slug="for-now")
        workflow.unpublish(self.editor, post)
        self.assertEqual(self.site("/blog/for-now/").status_code, 404)
        self.assertNotIn("for-now", self.site("/sitemap.xml").content.decode())
        self.assertContains(self.site("/blog/"), "First posts coming soon")

    def test_the_writing_side_is_not_on_the_site(self):
        for path in ("/write/", "/write/sign-in/", "/write/review/", "/write/posts/1/"):
            with self.subTest(path=path):
                self.assertEqual(self.site(path).status_code, 404)


class APublishedPostTests(BlogSetUp):
    def setUp(self):
        self.post_ = self.published(slug="five-checks")
        self.page = self.site("/blog/five-checks/").content.decode()

    def head(self, prop):
        found = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)">', self.page)
        return found.group(1) if found else None

    def test_its_own_title_description_and_canonical_address(self):
        self.assertIn("<title>A post for search</title>", self.page)
        self.assertEqual(self.head("description"), "What a search result says about the post.")
        self.assertIn('<link rel="canonical" href="https://classnode.testserver/blog/five-checks/">', self.page)
        self.assertNotIn('name="robots"', self.page)
        self.assertNotIn("X-Robots-Tag", self.site("/blog/five-checks/"))

    def test_its_open_graph_image_is_its_cover(self):
        cover = f"https://classnode.testserver/blog/images/{self.post_.cover.key}.webp"
        self.assertEqual(self.head("og:type"), "article")
        self.assertEqual(self.head("og:image"), cover)
        self.assertEqual(self.head("og:image:width"), "1200")
        self.assertEqual(self.head("og:image:height"), "630")
        self.assertEqual(self.head("og:image:alt"), self.post_.cover_alt)
        self.assertEqual(self.head("twitter:image"), cover)
        self.assertEqual(self.head("og:url"), "https://classnode.testserver/blog/five-checks/")
        image = self.site(f"/blog/images/{self.post_.cover.key}.webp")
        self.assertEqual((image.status_code, image["Content-Type"]), (200, "image/webp"))

    def test_its_article_structured_data(self):
        (block,) = re.findall(r'<script type="application/ld\+json">(.*?)</script>', self.page, re.S)
        data = json.loads(block)
        self.assertEqual(data["@type"], "Article")
        self.assertEqual(data["headline"], self.post_.title)
        self.assertEqual(data["description"], self.post_.seo_description)
        self.assertEqual(data["image"], [self.head("og:image")])
        self.assertEqual(data["author"], {"@type": "Person", "name": "Kemi Oladipo"})
        self.assertEqual(data["publisher"]["name"], "Classnode Edtech Limited")
        self.assertEqual(data["mainEntityOfPage"]["@id"], "https://classnode.testserver/blog/five-checks/")
        self.assertTrue(data["datePublished"].startswith(f"{self.post_.first_published_at:%Y-%m-%d}"))

    def test_one_h1_and_every_image_described(self):
        self.assertEqual(len(re.findall(r"<h1\b", self.page)), 1)
        for tag in re.findall(r"<img\b[^>]*>", self.page):
            self.assertRegex(tag, r'\balt="[^"]{12,}"', tag)

    def test_no_script_but_the_menus_and_the_structured_data(self):
        scripts = re.findall(r"<script\b([^>]*)>", self.page)
        self.assertEqual(sorted(s.strip() for s in scripts), ['type="application/ld+json"', 'type="module"'])
        for page in (self.page, self.site("/blog/").content.decode()):
            self.assertNotIn("write/app.js", page)
            self.assertNotIn("write/tools.js", page)
            self.assertNotIn("/write/", page)

    def test_the_editor_module_is_named_by_the_editor_page_only(self):
        hits = sorted(
            str(path.relative_to(settings.BASE_DIR))
            for path in Path(settings.BASE_DIR).glob("*/templates/**/*.html")
            if "{% static 'write/app.js' %}" in path.read_text()
        )
        self.assertEqual(hits, ["blog/templates/blog/write/editor.html"])


class TheListTests(BlogSetUp):
    def test_newest_first_twelve_to_a_page(self):
        posts = [self.published(slug=f"post-{n:02d}") for n in range(13)]
        first = self.site("/blog/").content.decode()
        self.assertIn("/blog/post-12/", first)
        self.assertNotIn('href="/blog/post-00/"', first)
        self.assertIn('href="/blog/page/2/"', first)
        second = self.site("/blog/page/2/")
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, 'href="/blog/post-00/"')
        self.assertContains(second, '<link rel="canonical" href="https://classnode.testserver/blog/page/2/">')
        self.assertEqual(self.site("/blog/page/1/").status_code, 404)
        self.assertEqual(self.site("/blog/page/3/").status_code, 404)
        self.assertEqual(len(posts), 13)

    def test_the_blog_is_linked_from_the_homepages_nav_and_footer(self):
        home = self.site("/").content.decode()
        nav = home.split('<nav class="site-nav"', 1)[1].split("</nav>", 1)[0]
        menu = home.split('id="site-menu"', 1)[1].split("</div>", 1)[0]
        footer = home.split('<footer class="site-foot', 1)[1]
        for part in (nav, menu, footer):
            self.assertIn('href="/blog/"', part)


class ScriptsAreStrippedTests(BlogSetUp):
    def test_a_script_tag_in_markdown_never_reaches_the_page(self):
        post = workflow.new_post(self.writer)
        from .fixtures import complete

        body = (
            "Before.\n\n<script>alert('blog-xss')</script>\n\n"
            '<iframe src="https://example.com/frame"></iframe>\n\n'
            '<img src="x" onerror="alert(\'blog-onerror\')">\n\n'
            '<a href="javascript:alert(\'blog-js\')" onclick="alert(1)">a link</a>\n\n'
            "After."
        )
        post = complete(post, self.writer, slug="with-a-script", body=body)
        workflow.publish(self.editor, workflow.submit(self.writer, post))
        page = self.site("/blog/with-a-script/").content.decode()
        article = page.split('<div class="prose">', 1)[1].split("</article>", 1)[0]
        self.assertIn("Before.", article)
        self.assertIn("After.", article)
        for gone in ("<script", "blog-xss", "<iframe", "example.com/frame", "onerror", "blog-onerror",
                     "javascript:", "onclick", 'src="x"'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, article)

    def test_the_preview_is_sanitised_the_same_way(self):
        post = self.draft(slug="preview-me")
        response = self.post(
            f"/write/posts/{post.pk}/preview/", {"body": "<script>alert(1)</script>Hi <b onclick=x>there</b>"},
            user=self.writer,
        )
        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertNotIn("<script", html)
        self.assertNotIn("onclick", html)
        self.assertIn("Hi", html)


SPOT_CHECK = (
    "## 6. Before\n\nIntro with `inline` code.\n\n"
    "## 7. Spot-check\n\nCheck that `100` is right.\n\n---\n\n"
    "> A quote with **bold** and [a link](https://example.com) →\n\n"
    "1. One\n2. Two with `code`\n\n- bullet **a**\n- bullet *b*\n\n"
    "### The end\n\nDone.\n\n<script>alert('blog-xss')</script>"
)
ELEMENTS = ("<code>100</code>", "<hr>", "<blockquote>", "<ol>", "<ul>", "<li>", "<h2>7. Spot-check</h2>",
            "<h3>The end</h3>", "<strong>bold</strong>", "<em>b</em>", 'href="https://example.com"')


class RenderedBodyIsNotEscapedTests(BlogSetUp):
    def setUp(self):
        from .fixtures import complete

        post = complete(workflow.new_post(self.writer), self.writer, slug="spot-check", body=SPOT_CHECK)
        self.post_ = workflow.publish(self.editor, workflow.submit(self.writer, post))

    def assert_drawn(self, page):
        article = page.split('<div class="prose">', 1)[1].split("</article>", 1)[0]
        self.assertNotIn("&lt;", article)
        self.assertNotIn("blog-xss", article)
        self.assertNotIn("<script", article)
        for element in ELEMENTS:
            with self.subTest(element=element):
                self.assertIn(element, article)

    def test_the_public_page_draws_every_element(self):
        self.assert_drawn(self.site("/blog/spot-check/").content.decode())

    def test_the_portal_view_page_draws_the_same_elements(self):
        response = self.get(f"/write/posts/{self.post_.pk}/view/", user=self.writer)
        self.assertEqual(response.status_code, 200)
        self.assert_drawn(response.content.decode())


class TheStylesheetTests(BlogSetUp):
    def test_tables_scroll_inside_the_article_and_long_words_wrap(self):
        css = (STATIC / "blog" / "blog.css").read_text()
        self.assertRegex(css, r"\.prose \.post-table \{[^}]*overflow-x: auto")
        self.assertRegex(css, r"\.prose \{[^}]*overflow-wrap: anywhere")
        self.assertRegex(css, r"\.prose pre \{[^}]*overflow-x: auto")

    def test_the_site_host_is_the_one_under_test(self):
        self.assertEqual(SITE, "classnode.testserver")
        self.assertEqual(Status.PUBLISHED, "published")
