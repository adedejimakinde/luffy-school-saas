"""Classnode's own price, and the pricing page that lists what it includes.

The price is the first term free, then ₦1,500 per student, per term, with no
setup fee, written the same way everywhere (`website.views.PRICE`). The old
₦2,500 is on no public page. The pricing page groups every feature in the
price; a feature not yet on `main` wears "Coming soon", decided by one setting
per feature (`website.features`), so the label goes with a setting and no code.
"""

import html
import re

from django.conf import settings
from django.test import override_settings

from website import features
from website.tests.test_homepage import BANNED, SiteSetUp, visible_text

PRICE = "The first term is free, then ₦1,500 per student, per term. No setup fee."

#: Every feature the pricing page lists in the price, by heading.
LISTED = {
    "Results and report cards": [
        "Report cards, including the Ogun State sheet", "CA and exam scores",
        "Affective and psychomotor traits", "Parent result checks",
    ],
    "Registers, fees and notices": ["Attendance registers", "Fees and payments tracking", "Notices"],
    "Staff and exams": [
        "Staff roles and subject-teacher assignment", "Exam PIN slips", "CBT: school tests",
        "CBT: UTME-style practice", "CBT: WASSCE-style practice",
    ],
    "Your school online": ["A school website on its Classnode address"],
    "Safe and separate": ["Backups", "Each school's data kept apart"],
}
PREMIUM = [
    "A custom domain for the school website",
    "Results and notices from the school's own email domain",
]

#: What `main` does not have yet: the school's website has no editor (so a school
#: cannot publish one), CBT stops at exam PINs (no question bank, no tests, no
#: modes), and no domain or sender domain can be connected. `docs/website.md`.
NOT_LIVE = {
    "A school website on its Classnode address": "COMING_SOON_SCHOOL_WEBSITE",
    "CBT: school tests": "COMING_SOON_CBT_SCHOOL_TESTS",
    "CBT: UTME-style practice": "COMING_SOON_CBT_UTME_PRACTICE",
    "CBT: WASSCE-style practice": "COMING_SOON_CBT_WASSCE_PRACTICE",
    "A custom domain for the school website": "COMING_SOON_CUSTOM_DOMAIN",
    "Results and notices from the school's own email domain": "COMING_SOON_SENDER_DOMAIN",
}


def soon(page):
    """The labelled features on a rendered pricing page, in order."""
    return [html.unescape(label) for label in re.findall(r"<b>([^<]*)</b> <span class=\"chip\">Coming soon</span>", page)]


class ThePriceTests(SiteSetUp):
    def test_the_price_is_written_one_way_on_every_public_page(self):
        for path in ("/", "/pricing/", "/terms/"):
            with self.subTest(path=path):
                page = self.get(path).content.decode()
                text = visible_text(page)
                self.assertIn("₦1,500", text)
                self.assertNotIn("2,500", page)
                self.assertNotIn("1,250", page)
                self.assertNotIn("₦1500", text)

    def test_the_homepage_hero_pricing_card_and_terms_say_the_same_thing(self):
        home = visible_text(self.get().content.decode())
        self.assertIn(PRICE, home)
        self.assertIn("The first term is free, then ₦1,500 per student, per term. No setup fee.", home)
        self.assertIn(
            "The first term is free. After that, schools pay ₦1,500 per student, per term. "
            "There is no setup fee.",
            visible_text(self.get("/terms/").content.decode()),
        )

    def test_the_pricing_page_has_the_price_and_its_meta(self):
        page = self.get("/pricing/").content.decode()
        text = visible_text(page)
        self.assertIn("The first term is free, then", text)
        self.assertIn("₦1,500", text)
        self.assertIn("per student, per term. No setup fee.", text)
        self.assertIn(PRICE, re.search(r'<meta name="description" content="([^"]*)">', page).group(1))

    def test_every_page_links_to_the_pricing_page(self):
        for path in ("/", "/pricing/", "/privacy/"):
            with self.subTest(path=path):
                self.assertIn('href="/pricing/"', self.get(path).content.decode())


class ThePricingPageTests(SiteSetUp):
    def setUp(self):
        self.page = self.get("/pricing/").content.decode()

    def test_every_feature_is_listed_under_its_group(self):
        for heading, labels in LISTED.items():
            section = self.page.split(f">{heading}</h3>", 1)
            self.assertEqual(len(section), 2, heading)
            group = section[1].split("</ul>", 1)[0]
            self.assertEqual([html.unescape(b) for b in re.findall(r"<b>([^<]*)</b>", group)], labels, heading)

    def test_the_premium_add_on_is_its_own_group_priced_by_asking(self):
        premium = self.page.split('id="premium-title">Premium add-on</h2>', 1)[1]
        self.assertIn("<b>Contact us</b>", premium)
        found = re.findall(r"<li>.*?<b>([^<]*)</b>", premium.split("</ul>", 1)[0], flags=re.S)
        self.assertEqual([html.unescape(label) for label in found], PREMIUM)
        everything = visible_text(self.page).lower()
        self.assertNotIn("mailbox", everything)
        self.assertNotIn("inbox", everything)
        # None of the premium items is among the features the price includes.
        included = self.page.split('id="premium-title"', 1)[0]
        for label in PREMIUM:
            self.assertNotIn(label, included)

    def test_the_writing_rules_hold(self):
        text = visible_text(self.page)
        self.assertNotRegex(text, "[–—]", "an en or em dash")
        self.assertNotIn("!", text)
        self.assertNotIn("?", text)
        for word in BANNED:
            self.assertNotRegex(text.lower(), rf"(?<![a-z]){re.escape(word)}(?![a-z])", word)

    def test_the_page_is_in_the_sitemap(self):
        sitemap = self.get("/sitemap.xml").content.decode()
        self.assertIn("https://classnode.testserver/pricing/", sitemap)


class ComingSoonTests(SiteSetUp):
    def test_what_is_not_on_main_wears_the_label_and_nothing_else_does(self):
        self.assertEqual(sorted(soon(self.get("/pricing/").content.decode())), sorted(NOT_LIVE))

    def test_each_label_has_its_own_setting_and_switching_it_off_removes_only_that_label(self):
        for label, setting in NOT_LIVE.items():
            with self.subTest(feature=label), override_settings(**{setting: False}):
                shown = soon(self.get("/pricing/").content.decode())
                self.assertEqual(sorted(shown), sorted(set(NOT_LIVE) - {label}))

    def test_with_every_setting_off_no_label_is_left_and_every_feature_still_is(self):
        with override_settings(**{setting: False for setting in NOT_LIVE.values()}):
            page = self.get("/pricing/").content.decode()
        self.assertNotIn("Coming soon", page)
        for label in [label for labels in LISTED.values() for label in labels] + PREMIUM:
            self.assertIn(f"<b>{html.escape(label)}</b>", page)

    def test_the_settings_are_the_ones_the_features_name_and_each_is_on_until_it_is_switched_off(self):
        self.assertEqual(features.SETTINGS, sorted(NOT_LIVE.values()))
        for setting in NOT_LIVE.values():
            with self.subTest(setting=setting):
                self.assertIs(getattr(settings, setting), True)

    def test_a_feature_with_no_setting_is_live(self):
        self.assertFalse(features.coming_soon(None))

    def test_the_labels_are_not_on_the_homepage(self):
        self.assertNotIn("Coming soon", self.get().content.decode())
