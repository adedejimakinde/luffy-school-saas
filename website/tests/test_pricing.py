"""Classnode's own price, and the pricing page that lists what it includes.

The price is the first term free, then ₦1,500 per student, per term, with no
setup fee: one setting (`settings.PRICE_PER_STUDENT_NAIRA`) read through
`website.price`, so every public page says the same and none says another. The
old ₦2,500 is on no public page. The pricing page groups every feature in the
price, from `website.features`, and lists only what is live.
"""

import html
import re

from django.test import override_settings

from website import features, price
from website.tests.test_homepage import BANNED, SiteSetUp, visible_text

PRICE = "The first term is free, then ₦1,500 per student, per term. No setup fee."

#: Every public page that carries the price or says what is in it.
PAGES = ("/", "/pricing/", "/faq/", "/terms/", "/privacy/", "/llms.txt")

#: Figures that are not the price: the showcase school's own fees and payments, drawn in the
#: homepage's screens and floating cards (`schools/showcase.py`). The only other naira amounts
#: any public page may show.
DEMO_FIGURES = {"₦48.6m", "₦71.2m", "₦120,700", "₦125,000", "₦112,000", "₦48,620,500", "₦71,206,200"}

NAIRA = re.compile(r"₦\s?[\d][\d,]*(?:\.\d+)?m?")
OLD_PRICES = ("2,500", "2500", "1,250", "₦1500")


def naira_amounts(text):
    return [re.sub(r"\s", "", amount).rstrip(",") for amount in NAIRA.findall(text)]


class ThePriceTests(SiteSetUp):
    def public(self, path):
        page = self.get(path).content.decode()
        return page if path == "/llms.txt" else visible_text(page)

    def test_the_price_is_written_one_way_on_every_public_page(self):
        for path in ("/", "/pricing/", "/terms/"):
            with self.subTest(path=path):
                page = self.get(path).content.decode()
                self.assertIn("₦1,500", visible_text(page))
                for old in OLD_PRICES:
                    self.assertNotIn(old, page)

    def test_no_public_page_shows_a_price_other_than_the_setting(self):
        """Every amount on every public page is the setting's, or a demo school's figure."""
        for path in PAGES:
            for amount in (price.figure(), "₦2,000"):
                with self.subTest(path=path, setting=amount), override_settings(
                    PRICE_PER_STUDENT_NAIRA=int(amount[1:].replace(",", ""))
                ):
                    text = self.public(path)
                    for shown in naira_amounts(text):
                        self.assertTrue(
                            shown == amount or shown in DEMO_FIGURES,
                            f"{path} shows {shown}; the price is {amount}",
                        )
                    for old in OLD_PRICES:
                        self.assertNotIn(old, text)
                    if path in ("/", "/pricing/", "/terms/", "/llms.txt"):
                        self.assertIn(amount, text)

    def test_a_changed_setting_changes_every_page_and_nothing_is_left_behind(self):
        with override_settings(PRICE_PER_STUDENT_NAIRA=1800):
            for path in PAGES:
                with self.subTest(path=path):
                    text = self.public(path)
                    self.assertNotIn("₦1,500", text)
                    if path in ("/", "/pricing/", "/faq/", "/terms/", "/llms.txt"):
                        self.assertIn("₦1,800", text)
            for path in ("/", "/pricing/", "/faq/"):
                page = self.get(path).content.decode()
                self.assertNotIn("₦1500", page)
                self.assertNotIn("₦1,500", page)

    def test_the_homepage_hero_pricing_card_and_terms_say_the_same_thing(self):
        home = visible_text(self.get().content.decode())
        self.assertIn(PRICE, home)
        self.assertIn(
            "A school's first term is free. After that, schools pay ₦1,500 per student, per term. "
            "There is no setup fee.",
            visible_text(self.get("/terms/").content.decode()),
        )

    def test_the_price_sentences_come_from_the_setting(self):
        self.assertEqual(price.sentence(), PRICE)
        with override_settings(PRICE_PER_STUDENT_NAIRA=2000):
            self.assertEqual(price.figure(), "₦2,000")

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
        for heading, group_features in features.GROUPS:
            section = self.page.split(f">{heading}</h3>", 1)
            self.assertEqual(len(section), 2, heading)
            group = section[1].split("</ul>", 1)[0]
            self.assertEqual(
                [html.unescape(b) for b in re.findall(r"<b>([^<]*)</b>", group)],
                [feature.name for feature in group_features],
                heading,
            )

    def test_every_feature_shows_its_line_and_its_detail(self):
        text = visible_text(self.page)
        for feature in features.FEATURES:
            with self.subTest(feature=feature.key):
                self.assertIn(feature.name, text)
                self.assertIn(feature.line, text)
                self.assertIn(feature.detail, text)

    def test_nothing_that_is_not_built_is_listed(self):
        text = visible_text(self.page).lower()
        for word in ("custom domain", "news post", "admissions form", "email domain", "id card",
                     "forgot password", "premium", "mailbox"):
            self.assertNotIn(word, text)

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


class NoComingSoonTests(SiteSetUp):
    def test_nothing_public_says_coming_soon_for_a_feature_that_is_live(self):
        for path in PAGES:
            with self.subTest(path=path):
                text = self.get(path).content.decode().lower()
                self.assertNotIn("coming soon", text)
