"""Where Classnode is based, and who it is for.

The base is `settings.SITE_LOCATION` (Lagos, Nigeria) and the market is
secondary schools across Nigeria. No public page and not `/llms.txt` may give
Abeokuta or Ogun State as either; the Ogun State report sheet stays as one
listed report card option. The registered office is `SITE_REGISTERED_ADDRESS`,
a separate setting.
"""

import re

from django.test import override_settings

from website.tests.test_homepage import SiteSetUp

PATHS = ("/", "/pricing/", "/faq/", "/about/", "/privacy/", "/terms/", "/blog/", "/llms.txt")


class TheBaseAndTheMarketTests(SiteSetUp):
    def body(self, path):
        page = self.get(path).content.decode()
        # Not the pictures' alt text or the demo sheet's own labels: those name the report template.
        return re.sub(r"<script\b.*?</script>", " ", page, flags=re.S)

    def test_no_page_makes_abeokuta_or_ogun_state_the_base_or_the_market(self):
        for path in PATHS:
            text = self.body(path)
            with self.subTest(path=path):
                self.assertNotIn("Abeokuta", text)
                # Ogun State is only ever the name of a report card or sheet.
                for found in re.finditer(r"Ogun State(?! (report|template))", text):
                    self.fail(f"{found.group(0)!r} in {text[max(0, found.start() - 60):found.end() + 40]!r}")

    def test_structured_data_serves_nigeria_from_the_location(self):
        page = self.get("/").content.decode()
        self.assertIn('"areaServed":{"@type":"Country","name":"Nigeria"}', page)
        self.assertNotIn("Abeokuta", page)
        organization = page.split('"@type":"Organization"', 1)[1].split('"@type":"SoftwareApplication"', 1)[0]
        self.assertNotIn("Ogun", organization)

    def test_the_location_is_one_setting(self):
        for path in ("/about/", "/llms.txt"):
            self.assertIn("Lagos, Nigeria", self.body(path))
        with override_settings(SITE_LOCATION="Ibadan, Nigeria"):
            for path in ("/about/", "/llms.txt"):
                with self.subTest(path=path):
                    text = self.body(path)
                    self.assertIn("Ibadan, Nigeria", text)
                    self.assertNotIn("Lagos", text)

    def test_the_positioning_is_nigeria_wide(self):
        self.assertIn("secondary schools across Nigeria", self.body("/llms.txt"))
        self.assertIn("secondary schools across Nigeria", self.body("/about/"))

    def test_the_registered_address_is_its_own_setting(self):
        with override_settings(SITE_REGISTERED_ADDRESS="1 Example Road, Lagos", SHOW_LEGAL_TODOS=True):
            for path in ("/privacy/", "/terms/"):
                with self.subTest(path=path):
                    self.assertIn("1 Example Road, Lagos", self.body(path))
        for path in ("/", "/about/", "/llms.txt", "/faq/"):
            self.assertNotIn("Example Road", self.body(path))
