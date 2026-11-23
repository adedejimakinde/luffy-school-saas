"""The public site claims only what is live, and says it the same way everywhere.

Two guards, both reading `website.features` (the one list of what is live):

- No public page, its meta description or its structured data says a live feature is
  "coming soon" or "not yet" there. A sentence that names a live feature and also one of
  those phrases fails, so the FAQ cannot go stale when a feature ships.
- The FAQPage structured data is the visible FAQ, word for word, on `/faq/` and on the
  homepage.

And the claims the features list makes about the school website are held to the code.
"""

import html
import json
import re
from pathlib import Path

from schoolsite.models import CUSTOM_PAGE_SLOTS
from website import features
from website.landing import ADD_ONS
from website.tests.test_homepage import SiteSetUp, visible_text
from website.views import FAQ, faq_page, pages

#: Every public page, raw (so the title, meta description and structured data are read too).
PATHS = ("/", "/pricing/", "/about/", "/faq/", "/llms.txt", "/blog/", "/sitemap.xml")

#: Words that say a thing is not here yet.
NOT_LIVE = re.compile(
    r"coming soon|not yet|yet to (?:be )?(?:launch|release|ship|build|come)|available soon|"
    r"launching soon|coming later|will soon|on the way|in the works|under development",
    re.I,
)

#: What each live feature is called in running text, besides its own name.
ALSO_CALLED = {
    "results": ["results"],
    "report-cards": ["report card"],
    "cbt": ["cbt", "computer-based test", "item analysis", "calculator"],
    "fees-and-registers": ["fees", "attendance", "register"],
    "parents": ["parents"],
    "portal": ["portal"],
    "app": ["app", "install"],
    "school-website": ["website", "web site", "hero video", "custom page"],
    "fast": ["slow network", "cheap phone"],
    "backups": ["backup"],
}

TEMPLATES = [
    path
    for root in ("website/templates/website", "blog/templates/blog")
    for path in sorted((Path(__file__).resolve().parents[2] / root).rglob("*.html"))
    if "write" not in path.parts and path.name not in ("privacy.html", "terms.html")
]


def keywords(feature):
    return {feature.name.lower(), *ALSO_CALLED[feature.key]}


def stale_claims(text):
    """Sentences in `text` that say a live feature is not live: (sentence, feature name)."""
    found = []
    for sentence in re.split(r"[.!?\n]|<[^>]+>|\\n|\\u003c|\\u003e", html.unescape(text)):
        if not NOT_LIVE.search(sentence):
            continue
        lowered = sentence.lower()
        for feature in features.FEATURES:
            if any(re.search(rf"(?<![a-z]){re.escape(word)}", lowered) for word in keywords(feature)):
                found.append((sentence.strip(), feature.name))
    return found


class TheGuardCatchesStaleClaimsTests(SiteSetUp):
    """The check itself, so a pass means something."""

    def test_it_flags_a_live_feature_called_coming_soon(self):
        self.assertTrue(stale_claims("Not yet. CBT is coming soon."))
        self.assertTrue(stale_claims("<p>A school website is coming soon</p>"))
        self.assertTrue(stale_claims("Report cards: not yet available."))

    def test_it_leaves_other_sentences_alone(self):
        self.assertFalse(stale_claims("First posts coming soon"))
        self.assertFalse(stale_claims("Thank you. We will be in touch soon."))
        self.assertFalse(stale_claims("Yes. Computer-based tests are marked by the computer."))

    def test_every_feature_has_a_name_for_the_check(self):
        self.assertEqual({f.key for f in features.FEATURES}, set(ALSO_CALLED))


class NothingLiveIsCalledComingSoonTests(SiteSetUp):
    def test_no_public_page_says_a_live_feature_is_coming_soon_or_not_yet(self):
        for path in PATHS:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(stale_claims(response.content.decode()), [])

    def test_no_page_description_does(self):
        for name, (title, description) in pages().items():
            with self.subTest(page=name):
                self.assertEqual(stale_claims(f"{title}. {description}"), [])

    def test_no_template_does(self):
        self.assertTrue(TEMPLATES)
        for path in TEMPLATES:
            with self.subTest(template=path.name):
                self.assertEqual(stale_claims(path.read_text()), [])

    def test_no_feature_line_or_detail_does(self):
        for feature in features.FEATURES:
            with self.subTest(feature=feature.key):
                self.assertEqual(stale_claims(f"{feature.line} {feature.detail}"), [])

    def test_the_faq_answers_cbt_and_the_school_website_as_live(self):
        answers = dict(faq_page())
        self.assertTrue(answers["Does it have CBT?"].startswith("Yes."))
        asked = "Does Classnode include a website and app for our school?"
        self.assertTrue(answers[asked].startswith("Yes."))
        self.assertIn("No app store", answers[asked])
        for question in ("What is the best school management software for Nigerian secondary schools?",
                         "What does Classnode do?"):
            self.assertIn("CBT", answers[question])
            self.assertIn("website", answers[question])

    def test_the_school_website_is_not_sold_as_a_domain_name(self):
        """The website is the school's classnode.co address. A custom domain is
        named once, on the pricing page, as an optional paid add-on (`website.landing.ADD_ONS`)."""
        for path in ("/", "/pricing/", "/faq/", "/llms.txt"):
            with self.subTest(path=path):
                text = self.get(path).content.decode().replace(ADD_ONS, "").lower()
                self.assertNotRegex(text, r"your own domain|custom domain|own domain name|\.com\.ng|\.sch\.ng")


class TheWebsiteClaimsAreTheCodesTests(SiteSetUp):
    def test_the_page_count_is_the_models(self):
        """20 pages in all: the six fixed ones and `CUSTOM_PAGE_SLOTS` of the school's own."""
        detail = features.feature("school-website").detail
        self.assertIn(f"{CUSTOM_PAGE_SLOTS} of your own", detail)
        self.assertIn("20 pages in all", detail)
        self.assertEqual(6 + CUSTOM_PAGE_SLOTS, 20)


def faq_json_ld(page):
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, flags=re.S).group(1)
    data = json.loads(raw)
    graph = data.get("@graph", [data])
    faq = next(item for item in graph if item["@type"] == "FAQPage")
    return [(q["name"], q["acceptedAnswer"]["text"]) for q in faq["mainEntity"]]


def shown_in_sections(page):
    return [
        (html.unescape(q), visible_text(f"<body>{a}").removeprefix(">").strip())
        for q, a in re.findall(r'<section id="q\d+">\s*<h2>(.*?)</h2>\s*<p>(.*?)</p>\s*</section>', page, flags=re.S)
    ]


def shown_in_details(page):
    return [
        (html.unescape(q), visible_text(f"<body>{a}").removeprefix(">").strip())
        for q, a in re.findall(r"<details>\s*<summary>(.*?)</summary>\s*<p>(.*?)</p>\s*</details>", page, flags=re.S)
    ]


class TheFaqDataIsTheFaqShownTests(SiteSetUp):
    def test_faq_page_structured_data_is_the_visible_text(self):
        page = self.get("/faq/").content.decode()
        shown = shown_in_sections(page)
        self.assertEqual(len(shown), len(faq_page()))
        self.assertEqual(faq_json_ld(page), shown)

    def test_homepage_structured_data_is_the_visible_text(self):
        page = self.get("/").content.decode()
        shown = shown_in_details(page)
        self.assertEqual(len(shown), len(FAQ))
        self.assertEqual(faq_json_ld(page), shown)
