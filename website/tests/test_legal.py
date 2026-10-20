"""The privacy notice and the terms, on the public site host.

What these hold is the shape the brief asked for, not the law: that law is the
lawyer's, and every claim on both pages carries a visible TODO saying so. So:
the pages answer only on the site host; the contents list and the sections
match; the NDPA topics are all there; the controller and the processor are
named plainly; the writing rules hold; and the TODOs are there to be found.
"""

import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import override_settings

from blog.tests.fixtures import BlogSetUp
from website.crawlers import NOINDEX
from website.tests.test_homepage import BANNED, SITE, SiteSetUp, visible_text

PAGES = ("/privacy/", "/terms/")
TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "website"
DRAFT_LINE = "This notice is being finalised with our lawyer. Questions: hello@classnode.co."

#: The privacy notice's sections, by the NDPA topic each one answers.
PRIVACY_SECTIONS = [
    "who", "roles", "collect", "why", "basis", "stored", "shared", "kept", "children",
    "rights", "complain", "contact", "changes",
]


@override_settings(SHOW_LEGAL_TODOS=True)
class TheLegalPagesTests(SiteSetUp):
    def page(self, path):
        response = self.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.content.decode()

    def test_they_answer_on_the_site_host_only(self):
        for path in PAGES:
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 200)
                self.assertEqual(self.get(path, host="app.classnode.testserver").status_code, 404)

    def test_the_homepages_footer_links_now_land(self):
        home = self.page("/")
        for path in PAGES:
            self.assertIn(f'href="{path}"', home)

    def test_every_public_page_names_the_company_in_its_footer(self):
        """The legal name and RC number on the copyright line, every page, named once; no address."""
        for path in ("/", *PAGES):
            footer = self.page(path).split('<footer class="site-foot', 1)[1].split("</footer>", 1)[0]
            with self.subTest(path=path):
                text = visible_text("<body>" + footer)
                self.assertIn("© 2026 Classnode Edtech Limited · RC 9926572", text)
                self.assertEqual(text.count("Classnode Edtech Limited"), 1)
                self.assertNotIn("TODO", footer)

    def test_the_contents_list_matches_the_sections_in_order(self):
        for path in PAGES:
            page = self.page(path)
            listed = re.findall(r'<li><a href="#([a-z-]+)">', page.split('class="legal-contents"')[1].split("</nav>")[0])
            sections = re.findall(r'<section id="([a-z-]+)">', page)
            with self.subTest(path=path):
                self.assertGreaterEqual(len(sections), 10)
                self.assertEqual(listed, sections)

    def test_the_privacy_notice_covers_the_ndpa_basics(self):
        page = self.page("/privacy/")
        self.assertEqual(re.findall(r'<section id="([a-z-]+)">', page), PRIVACY_SECTIONS)
        text = visible_text(page)
        for needed in (
            "Your child's school is the controller.",
            "Classnode is the processor.",
            "Paystack", "Termii", "Our email provider", "Our SMS provider",
            "Nigeria Data Protection Commission",
            "We do not collect data from children directly.",
        ):
            with self.subTest(needed=needed):
                self.assertIn(needed, text)

    def test_every_page_marks_its_claims_and_gaps_for_the_lawyer(self):
        for path, at_least in (("/privacy/", 20), ("/terms/", 20)):
            text = visible_text(self.page(path))
            with self.subTest(path=path):
                self.assertGreaterEqual(text.count("TODO"), at_least)
                self.assertIn("TODO: lawyer", text)
                self.assertIn("TODO: date.", text)
                # Filled in: the company, its RC number and the address to
                # write to. Still to come: the registered address.
                self.assertIn("Classnode is run by Classnode Edtech Limited, RC 9926572.", text)
                self.assertIn("Email: hello@classnode.co", text)
                self.assertNotIn("TODO: RC number", text)
                self.assertNotIn("TODO: company name", text)

    def test_the_writing_rules_hold(self):
        for path in PAGES:
            text = visible_text(self.page(path))
            with self.subTest(path=path):
                self.assertNotRegex(text, "[\u2013\u2014]", "an en or em dash")
                self.assertNotIn("!", text)
                self.assertNotIn("?", text)
                self.assertNotRegex(text, r"(^|[.:] )Imagine\b")
                for word in BANNED:
                    self.assertNotRegex(text.lower(), rf"(?<![a-z]){re.escape(word)}(?![a-z])", word)

    def test_sentences_are_short(self):
        """Plain sentences a parent can follow: none past 30 words."""
        for path in PAGES:
            body = self.page(path).split('class="legal-body"')[1]
            # A heading, a list item and a paragraph each end a sentence.
            body = re.sub(r"</(h2|h3|li|p)>", " . ", body)
            text = re.sub(r"TODO:[^.]*\.", "", visible_text("<body>" + body))
            for sentence in re.split(r"(?<=[.;:])\s+", text):
                if sentence.strip(" .") == "":
                    continue
                with self.subTest(path=path, sentence=sentence[:50]):
                    self.assertLessEqual(len(sentence.split()), 30)

    @override_settings(SITE_HOST=None)
    def test_with_no_site_host_they_are_nobodys(self):
        for path in PAGES:
            self.assertEqual(self.client.get(path, HTTP_HOST=SITE).status_code, 404)


class TheLegalTodosSwitchTests(SiteSetUp):
    """`SHOW_LEGAL_TODOS`: off, a public reader sees no TODO box and no TODO word."""

    def test_off_there_is_no_todo_on_either_page(self):
        for path in PAGES:
            with self.subTest(path=path), override_settings(SHOW_LEGAL_TODOS=False):
                page = self.get(path).content.decode()
                self.assertNotIn('class="todo"', page)
                self.assertNotIn("TODO", page)
                # Still the whole page: its contents list and its sections.
                self.assertGreaterEqual(len(re.findall(r'<section id="', page)), 10)

    def test_on_the_notes_are_there(self):
        for path in PAGES:
            with self.subTest(path=path), override_settings(SHOW_LEGAL_TODOS=True):
                self.assertIn('class="todo"', self.get(path).content.decode())


class TheKnownFactsTests(SiteSetUp):
    @override_settings(SHOW_LEGAL_TODOS=False)
    def test_the_company_and_where_backups_are_kept_are_stated(self):
        privacy = visible_text(self.get("/privacy/").content.decode())
        terms = visible_text(self.get("/terms/").content.decode())
        for text in (privacy, terms):
            self.assertIn("Classnode is run by Classnode Edtech Limited, RC 9926572.", text)
        self.assertIn("Encrypted backups are kept with Backblaze B2, in its EU Central region.", privacy)

    @override_settings(SHOW_LEGAL_TODOS=True)
    def test_the_registered_address_is_still_open_and_still_in_the_source(self):
        for path in PAGES:
            self.assertIn("TODO: registered address", self.get(path).content.decode())


class TheDraftMarksTests(SiteSetUp):
    """While `LEGAL_IN_DRAFT`: one plain line, noindex, and no place in the sitemap."""

    def test_each_page_says_it_is_being_finalised_in_one_line_at_the_top(self):
        for path in PAGES:
            for show in (False, True):
                with self.subTest(path=path, show=show), override_settings(SHOW_LEGAL_TODOS=show):
                    page = self.get(path).content.decode()
                    text = visible_text(page)
                    self.assertEqual(text.count("This notice is being finalised"), 1)
                    self.assertIn(DRAFT_LINE, text)
                    # Above the contents list, which is above every section.
                    self.assertLess(page.index("being finalised"), page.index('class="legal-contents"'))

    def test_each_page_is_noindex_in_the_page_and_in_the_header(self):
        for path in PAGES:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["X-Robots-Tag"], NOINDEX)
                self.assertIn('<meta name="robots" content="noindex, nofollow">', response.content.decode())

    def test_robots_txt_lets_a_crawler_read_the_noindex(self):
        """A page a crawler may not fetch is a page whose noindex it never sees."""
        robots = self.get("/robots.txt").content.decode()
        for path in PAGES:
            self.assertNotIn(f"Disallow: {path}", robots)

    def test_neither_is_in_the_sitemap_and_the_rest_still_are(self):
        listed = re.findall(r"<loc>([^<]*)</loc>", self.get("/sitemap.xml").content.decode())
        for path in PAGES:
            self.assertNotIn(f"https://{SITE}{path}", listed)
        self.assertIn(f"https://{SITE}/", listed)
        self.assertIn(f"https://{SITE}/blog/", listed)

    def test_when_the_lawyers_version_is_in_all_of_it_reverses(self):
        with mock.patch("website.views.LEGAL_IN_DRAFT", False):
            listed = re.findall(r"<loc>([^<]*)</loc>", self.get("/sitemap.xml").content.decode())
            for path in PAGES:
                with self.subTest(path=path):
                    response = self.get(path)
                    self.assertFalse(response.has_header("X-Robots-Tag"))
                    self.assertNotIn("noindex", response.content.decode())
                    self.assertNotIn("being finalised", response.content.decode())
                    self.assertIn(f"https://{SITE}{path}", listed)

    def test_the_homepage_and_the_blog_are_still_indexable(self):
        for path in ("/", "/blog/"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertFalse(response.has_header("X-Robots-Tag"))
                self.assertNotIn("noindex", response.content.decode())


class ThePublicOutputHasNoTodoTests(SiteSetUp):
    """Public output: no note, no empty paragraph, no heading with nothing under it."""

    @override_settings(SHOW_LEGAL_TODOS=False)
    def test_what_is_left_is_whole(self):
        for path in PAGES:
            page = self.get(path).content.decode()
            with self.subTest(path=path):
                self.assertNotRegex(page, r"<p>\s*</p>")
                listed = re.findall(r'<li><a href="#([a-z-]+)">', page.split('class="legal-contents"')[1].split("</nav>")[0])
                sections = re.findall(r'<section id="([a-z-]+)">', page)
                self.assertEqual(listed, sections)
                for section in re.split(r'<section id="', page.split('class="legal-body"')[-1])[1:]:
                    self.assertRegex(re.sub(r"<h2>.*?</h2>", "", section.split("</section>")[0], flags=re.S), r"<(p|ul)[ >]")

    @override_settings(SHOW_LEGAL_TODOS=False)
    def test_a_section_that_was_only_a_note_goes_with_its_contents_line(self):
        terms = self.get("/terms/").content.decode()
        self.assertNotIn('id="liability"', terms)
        self.assertNotIn('href="#liability"', terms)

    @override_settings(SHOW_LEGAL_TODOS=True)
    def test_the_templates_keep_every_note_and_nothing_is_lost(self):
        for name, path in (("privacy", "/privacy/"), ("terms", "/terms/")):
            source = (TEMPLATES / f"{name}.html").read_text()
            with self.subTest(name=name):
                self.assertGreaterEqual(source.count('class="todo"'), 20)
                self.assertEqual(self.get(path).content.decode().count('class="todo"'), source.count('class="todo"'))
                # Every TODO in the source is inside a note, so stripping the notes takes them all.
                self.assertEqual(source.count("TODO"), len(re.findall(r'<span class="todo">[^<]*TODO', source)))

    def test_production_does_not_switch_the_notes_on(self):
        production = (Path(settings.BASE_DIR) / "deploy" / "production.env").read_text()
        lines = [line.strip() for line in production.splitlines() if not line.strip().startswith("#")]
        self.assertFalse([line for line in lines if line.startswith(("SHOW_LEGAL_TODOS", "DJANGO_DEBUG"))])


class NoPublicPageOnTheSiteHasTodoTests(BlogSetUp):
    """The site host, every page it serves and the files crawlers read, with the notes off."""

    @override_settings(SHOW_LEGAL_TODOS=False)
    def test_no_rendered_page_contains_todo(self):
        post = self.published(slug="a-post")
        paths = ["/", "/?sent=1", "/privacy/", "/terms/", "/blog/", f"/blog/{post.slug}/", "/sitemap.xml", "/robots.txt"]
        for path in paths:
            with self.subTest(path=path):
                response = self.site(path)
                self.assertEqual(response.status_code, 200, path)
                body = response.content.decode()
                self.assertNotIn("TODO", body)
                self.assertNotIn('class="todo"', body)
