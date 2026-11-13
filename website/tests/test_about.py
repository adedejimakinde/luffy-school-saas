"""`/about/`: who runs Classnode, how a school's data is kept, and the contacts.

What a browser has to be asked (how it lands at 320, 390 and 1280) is
`tests/ui/screens.test.js`'s.
"""

import re

from django.test import override_settings

from website.tests.test_homepage import PORTAL, SITE, SiteSetUp, visible_text


class TheAboutPageTests(SiteSetUp):
    def page(self):
        response = self.get("/about/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_it_is_on_the_site_host_only(self):
        self.assertEqual(self.client.get("/about/", HTTP_HOST=PORTAL).status_code, 404)

    def test_it_says_who_runs_classnode(self):
        text = visible_text(self.page())
        for fact in ("Classnode Edtech Limited, RC 9926572", "Abeokuta, Ogun State",
                     "founded by Adedeji Makinde"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_the_founder_has_no_photo(self):
        page = self.page()
        self.assertNotIn("<img", page.split("<main", 1)[1].split("</main>", 1)[0])

    def test_it_states_the_security_facts(self):
        text = visible_text(self.page())
        for fact in ("Nightly off-site backups", "backed up every night",
                     "kept apart from every other school's",
                     "Staff see only their part, by role", "Parents see only their own children"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_the_contacts_come_from_the_settings(self):
        page = self.page()
        for href in ("mailto:hello@classnode.co", "tel:+2349030269294",
                     "https://www.linkedin.com/company/classnode/",
                     "https://share.google/1MOPiuTETX2wehGWA"):
            with self.subTest(href=href):
                self.assertIn(f'href="{href}"', page.split("<main", 1)[1].split("</main>", 1)[0])
        with override_settings(SITE_PHONE="+2348000000000", SITE_LINKEDIN_URL="", SITE_GOOGLE_BUSINESS_URL=""):
            main = self.page().split("<main", 1)[1].split("</main>", 1)[0]
        self.assertIn("tel:+2348000000000", main)
        self.assertNotIn("LinkedIn", main)
        self.assertNotIn("Google", main)

    def test_the_faq_reads_the_same_contacts(self):
        faq = self.get("/faq/").content.decode().split('<section id="more">', 1)[1]
        for href in ("tel:+2349030269294", "https://www.linkedin.com/company/classnode/",
                     "https://share.google/1MOPiuTETX2wehGWA"):
            self.assertIn(f'href="{href}"', faq)
        with override_settings(SITE_PHONE="+2348000000000"):
            self.assertIn("tel:+2348000000000", self.get("/faq/").content.decode())

    def test_it_is_linked_from_the_nav_and_the_footer(self):
        page = self.get("/").content.decode()
        self.assertGreaterEqual(len(re.findall(r'<a href="/about/"', page)), 3)

    def test_it_is_in_the_sitemap(self):
        self.assertIn(f"https://{SITE}/about/", self.get("/sitemap.xml").content.decode())
