"""The solution pages (`website.landing`): eight pages for what schools search for.

Each answers on the public site and nowhere else, with one h1 holding its main
search phrase, its own title (the phrase first, 60 characters or fewer) and
description (under 155), a canonical address, a share card, a place in the
sitemap, 700 to 1,200 words, four to six questions that are its FAQPage
structured data word for word, lazy WebP screens of a demo school, the two
calls to action, the contact email, and links to related pages and the
homepage. The homepage and every page's footer link to all eight.
"""

import html
import json
import re

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from website import landing
from website.landing import LANDINGS, SHOTS, SOLUTIONS
from website.tests.test_homepage import BANNED, PORTAL, SITE, visible_text, words
from website.tests.test_seo import SCHOOL, SchoolSetUp, meta, structured
from tests.test_budget import STATIC

PATHS = {page.name: page.path for page in LANDINGS}
DASHES = re.compile("[\u2013\u2014]")


def main(page):
    return page.split('<main id="main">', 1)[1].split("</main>", 1)[0]


def shown_questions(page):
    return [
        (html.unescape(q), words(a))
        for q, a in re.findall(r"<details>\s*<summary>(.*?)</summary>\s*<p>(.*?)</p>\s*</details>", page, flags=re.S)
    ]


class TheEightPagesTests(SchoolSetUp):
    def page(self, path):
        response = self.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.content.decode()

    def test_there_are_eight_at_the_addresses_asked_for(self):
        self.assertEqual(sorted(PATHS.values()), sorted([
            "/result-computation-software/", "/cbt-software-for-schools/", "/school-result-checker/",
            "/pricing/", "/school-fees-management-software/", "/school-website-design/",
            "/school-management-software-lagos/", "/excel-vs-school-software/",
        ]))
        for name, path in PATHS.items():
            self.assertEqual(reverse(name, urlconf=settings.SITE_URLCONF), path)

    def test_each_answers_200_on_the_site_with_one_h1_holding_its_phrase(self):
        for page in LANDINGS:
            with self.subTest(path=page.path):
                found = re.findall(r"<h1\b[^>]*>(.*?)</h1>", self.page(page.path), flags=re.S)
                self.assertEqual(len(found), 1)
                self.assertIn(page.keyword.lower(), words(found[0]).lower())

    def test_each_names_its_canonical_address_once(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                self.assertEqual(re.findall(r'<link rel="canonical" href="([^"]*)">', self.page(path)),
                                 [f"https://{SITE}{path}"])

    def test_each_is_in_the_sitemap(self):
        sitemap = self.get("/sitemap.xml").content.decode()
        for path in PATHS.values():
            with self.subTest(path=path):
                self.assertEqual(sitemap.count(f"<loc>https://{SITE}{path}</loc>"), 1)

    def test_none_is_served_on_a_school_subdomain_or_the_portal(self):
        for path in PATHS.values():
            for host in (SCHOOL, PORTAL):
                with self.subTest(path=path, host=host):
                    response = self.get(path, host=host)
                    self.assertNotEqual(response.status_code, 200)
                    self.assertNotIn(b"Start your free first term", response.content)

    def test_title_puts_the_phrase_first_and_fits_and_so_does_the_description(self):
        titles, descriptions = set(), set()
        for page in LANDINGS:
            with self.subTest(path=page.path):
                text = self.page(page.path)
                (title,) = [html.unescape(t) for t in re.findall(r"<title>([^<]*)</title>", text)]
                (description,) = meta(text, "name", "description")
                self.assertTrue(title.lower().startswith(page.keyword.lower()), title)
                self.assertLessEqual(len(title), 60)
                self.assertLess(len(description), 155)
                self.assertIn("Classnode", title + description)
                self.assertNotRegex(title + description, DASHES)
                titles.add(title)
                descriptions.add(description)
        self.assertEqual((len(titles), len(descriptions)), (8, 8))

    def test_each_has_a_share_card_with_an_image(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                text = self.page(path)
                (image,) = meta(text, "property", "og:image")
                self.assertTrue(image.startswith(f"https://{SITE}/"), image)
                self.assertEqual(meta(text, "property", "og:url"), [f"https://{SITE}{path}"])
                self.assertEqual(meta(text, "name", "twitter:card"), ["summary_large_image"])

    def test_headings_never_skip_a_level(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                levels = [int(n) for n in re.findall(r"<h([1-6])\b", self.page(path))]
                self.assertEqual(levels[0], 1)
                self.assertGreaterEqual(levels.count(2), 4)
                for before, after in zip(levels, levels[1:]):
                    self.assertLessEqual(after, before + 1, levels)


class TheWordsTests(SchoolSetUp):
    def text(self, path, **kwargs):
        return visible_text("<body>" + main(self.get(path).content.decode()), **kwargs)

    def test_each_has_700_to_1200_words(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                count = len(self.text(path).split())
                self.assertGreaterEqual(count, 700)
                self.assertLessEqual(count, 1200)

    def test_the_writing_rules_hold(self):
        for path in PATHS.values():
            page = self.get(path).content.decode()
            text = visible_text(page)
            with self.subTest(path=path):
                self.assertNotRegex(page, DASHES, "an en or em dash anywhere in the page")
                self.assertNotIn("!", text)
                self.assertNotIn("?", visible_text(page, questions=False), "a question outside the questions")
                self.assertNotRegex(text, r"(^|[.:] )Imagine\b")
                for word in BANNED:
                    self.assertNotRegex(text.lower(), rf"(?<![a-z]){re.escape(word)}(?![a-z])", word)

    def test_no_coming_soon_and_nothing_that_is_not_built(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                text = self.text(path).replace(landing.ADD_ONS, "").lower()
                for phrase in ("coming soon", "not yet", "custom domain", "own domain", "school email", "news post",
                               "admissions form", "id card", "forgot password", "premium", "testimonial"):
                    self.assertNotIn(phrase, text)

    def test_the_nigerian_school_words_are_there(self):
        """Written for a Nigerian secondary school: its offices, its classes and its year."""
        everything = " ".join(self.text(path) for path in PATHS.values())
        for word in ("JSS", "SS 3", "CA", "exam", "term", "session", "broadsheet", "proprietor",
                     "principal", "bursar"):
            with self.subTest(word=word):
                self.assertRegex(everything, rf"(?<![A-Za-z]){re.escape(word)}(?![a-z])")

    def test_no_two_pages_share_a_paragraph(self):
        """Each page is its own, the Lagos page included: none is a renamed copy of another."""
        seen = {}
        for page in LANDINGS:
            for section in page.sections:
                for paragraph in (*section.body, *section.after):
                    with self.subTest(path=page.path, paragraph=paragraph[:40]):
                        self.assertNotIn(paragraph, seen, f"also on {seen.get(paragraph)}")
                    seen[paragraph] = page.path

    def test_the_lagos_page_is_about_lagos(self):
        text = self.text("/school-management-software-lagos/")
        for phrase in ("Lagos, Nigeria", "set up within 48 hours of receiving your student list",
                       "Staff trained in person at your school", "WhatsApp and email, Monday to Friday",
                       "+234 903 026 9294", "hello@classnode.co"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertGreaterEqual(text.count("Lagos"), 12)

    def test_the_lagos_page_promises_no_visit_and_no_local_support(self):
        text = self.text("/school-management-software-lagos/").lower()
        for phrase in ("visit", "local support", "face to face", "call us"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)

    def test_the_add_ons_line_is_on_the_pricing_page_alone(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                self.assertEqual(self.text(path).count(landing.ADD_ONS), 1 if path == "/pricing/" else 0)
        pricing = self.text("/pricing/")
        self.assertIn("Staff and parent logins are not charged.", pricing)
        self.assertIn("CBT, the result checker and your school website, on your school's classnode.co "
                      "address, are included at no extra cost.", pricing)

    def test_the_excel_page_says_what_excel_does_well_and_where_it_breaks(self):
        page = self.get("/excel-vs-school-software/").content.decode()
        headings = [words(h) for h in re.findall(r"<h2\b[^>]*>(.*?)</h2>", page, flags=re.S)]
        self.assertIn("What an Excel result template does well", headings)
        self.assertIn("Where the spreadsheet starts to break", headings)
        self.assertIn("<table>", page)

    def test_the_price_is_the_settings(self):
        with override_settings(PRICE_PER_STUDENT_NAIRA=1800):
            for path in PATHS.values():
                with self.subTest(path=path):
                    text = visible_text(self.get(path).content.decode())
                    self.assertIn("₦1,800", text)
                    self.assertNotIn("₦1,500", text)
        pricing = self.get("/pricing/").content.decode()
        self.assertIn("The first term is free, then ₦1,500 per student, per term. No setup fee.",
                      meta(pricing, "name", "description")[0])

    def test_location_is_lagos_nigeria(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                text = self.text(path)
                self.assertIn("We are in Lagos, Nigeria.", text)
                self.assertNotIn("Abeokuta", self.get(path).content.decode())


class TheQuestionsTests(SchoolSetUp):
    def test_four_to_six_questions_and_the_structured_data_is_them_word_for_word(self):
        for page in LANDINGS:
            with self.subTest(path=page.path):
                text = self.get(page.path).content.decode()
                shown = shown_questions(text)
                self.assertGreaterEqual(len(shown), 4)
                self.assertLessEqual(len(shown), 6)
                for question, _ in shown:
                    self.assertTrue(question.endswith("?"), question)
                self.assertEqual(text.count("application/ld+json"), 1)
                data = structured(text)
                self.assertEqual(data["@context"], "https://schema.org")
                self.assertEqual(data["@type"], "FAQPage")
                given = [(q["name"], q["acceptedAnswer"]["text"]) for q in data["mainEntity"]]
                self.assertEqual(given, shown)

    def test_no_ratings_or_reviews_in_any_markup(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                raw = json.dumps(structured(self.get(path).content.decode()))
                for word in ("aggregateRating", '"Review"', '"Rating"', "reviewRating", "ratingValue"):
                    self.assertNotIn(word, raw)

    def test_the_homepage_software_price_is_1500_naira_per_student_per_term(self):
        graph = {item["@type"]: item for item in structured(self.get().content.decode())["@graph"]}
        _, then = graph["SoftwareApplication"]["offers"]
        self.assertEqual((then["price"], then["priceCurrency"]), ("1500", "NGN"))
        self.assertEqual(then["priceSpecification"]["unitText"], "per student, per term")


class TheActionsAndLinksTests(SchoolSetUp):
    def test_each_offers_the_free_first_term_whatsapp_and_the_email(self):
        for path in PATHS.values():
            with self.subTest(path=path):
                page = main(self.get(path).content.decode())
                self.assertGreaterEqual(
                    len(re.findall(r'<a class="btn[^"]*" href="/#demo">Start your free first term</a>', page)), 2)
                self.assertGreaterEqual(page.count('href="https://wa.me/2349030269294" rel="noopener"'), 2)
                self.assertIn('href="mailto:hello@classnode.co"', page)

    def test_whatsapp_is_the_support_phone_setting(self):
        with override_settings(SITE_PHONE="+2348000000000"):
            self.assertIn('href="https://wa.me/2348000000000"', self.get("/pricing/").content.decode())
        with override_settings(SITE_PHONE=""):
            self.assertNotIn("wa.me", self.get("/pricing/").content.decode())

    def test_each_links_two_or_three_related_pages_and_the_homepage(self):
        for page in LANDINGS:
            with self.subTest(path=page.path):
                self.assertIn(len(page.related), (2, 3))
                self.assertNotIn(page.name, page.related)
                related = self.get(page.path).content.decode().split('class="land-related"', 1)[1].split("</nav>", 1)[0]
                links = re.findall(r'<a href="([^"]+)">', related)
                self.assertEqual(links, [PATHS[name] for name in page.related] + ["/"])

    def test_the_homepage_and_every_footer_link_to_all_eight(self):
        home = main(self.get().content.decode())
        for path in PATHS.values():
            with self.subTest(path=path):
                self.assertIn(f'href="{path}"', home)
        self.assertEqual(len(SOLUTIONS), 8)
        for path in [*PATHS.values(), "/", "/faq/", "/about/", "/blog/"]:
            footer = self.get(path).content.decode().split('<footer class="site-foot', 1)[1]
            solutions = footer.split('class="foot-col foot-solutions"', 1)[1].split("</div>", 1)[0]
            with self.subTest(path=path):
                self.assertEqual(re.findall(r'<a href="([^"]+)"', solutions), [PATHS[n] for n, _, _ in SOLUTIONS])


class TheScreensTests(SchoolSetUp):
    def test_screens_are_lazy_webp_sized_described_and_small(self):
        used = set()
        for page in LANDINGS:
            text = main(self.get(page.path).content.decode())
            images = re.findall(r"<img\b[^>]*>", text)
            with self.subTest(path=page.path):
                self.assertGreaterEqual(len(images), 1)
                # The first screen is words and buttons only: nothing above the first section's heading.
                self.assertLess(text.index('<h1'), text.index("<img"))
                self.assertLess(text.index('class="hero-actions"'), text.index("<img"))
            for tag in images:
                with self.subTest(path=page.path, image=tag[:60]):
                    self.assertIn('loading="lazy"', tag)
                    self.assertRegex(tag, r'srcset="[^"]+\.webp \d+w, [^"]+\.webp \d+w"')
                    self.assertRegex(tag, r'width="\d+" height="\d+"')
                    alt = re.search(r'alt="([^"]+)"', tag).group(1)
                    self.assertGreaterEqual(len(alt), 40)
                    self.assertIn("demo", html.unescape(alt).lower())
        for shot in SHOTS.values():
            for file, _ in shot.files:
                used.add(file)
                with self.subTest(file=file):
                    self.assertTrue((STATIC / file).exists(), file)
                    self.assertLess((STATIC / file).stat().st_size, 60 * 1000)

    def test_every_shot_is_used_and_every_section_shot_exists(self):
        named = {section.shot for page in LANDINGS for section in page.sections if section.shot}
        self.assertEqual(named, set(SHOTS))

    def test_whatsapp_address_comes_from_the_setting(self):
        self.assertEqual(landing.whatsapp(), "https://wa.me/2349030269294")
