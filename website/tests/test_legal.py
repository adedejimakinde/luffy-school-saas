"""The privacy notice and the terms, on the public site host.

What these hold is the shape the brief asked for, not the law: that law is the
lawyer's, and every claim on both pages carries a visible TODO saying so. So:
the pages answer only on the site host; the contents list and the sections
match; the NDPA topics are all there; the controller and the processor are
named plainly; the writing rules hold; and the TODOs are there to be found.
"""

import re

from django.test import override_settings

from website.tests.test_homepage import BANNED, SITE, SiteSetUp, visible_text

PAGES = ("/privacy/", "/terms/")

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
                # Filled in: the name and the address to write to. Still to
                # come: the RC number and the registered address.
                self.assertIn("Classnode is run by Classnode", text)
                self.assertIn("Email: hello@classnode.co", text)
                self.assertIn("TODO: RC number.", text)
                self.assertNotIn("TODO: company name", text)

    def test_the_writing_rules_hold(self):
        for path in PAGES:
            text = visible_text(self.page(path))
            with self.subTest(path=path):
                self.assertNotRegex(text, "[–—]", "an en or em dash")
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
