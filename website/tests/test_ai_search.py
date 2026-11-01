"""classnode.co for AI search tools and search engines.

`/robots.txt` welcomes the AI crawlers by name on the public site and on no
other host, `/llms.txt` summarises the site in Markdown from the same settings
the pricing page reads, the homepage and `/faq/` carry valid structured data,
`/faq/` answers the ten questions a school asks first, and every public page
has its own title and description.
"""

import html
import json
import re
from unittest import mock
from urllib.robotparser import RobotFileParser

from django.test import override_settings
from django.urls import reverse

from blog.tests.fixtures import BlogSetUp
from tests.test_budget import BUDGET, STATIC, _ASSET, served_files, urls_in_css
from website import features
from website.crawlers import AI_CRAWLERS, CLOSED_ROBOTS, SCHOOL_ROBOTS
from website.tests.test_homepage import BANNED, PORTAL, SITE, SiteSetUp, visible_text
from website.tests.test_seo import SCHOOL, DASHES, SchoolSetUp, meta, structured
from website.views import FAQ, LEGAL_PAGES, PAGES, PRICE

#: The crawlers the brief names, spelled as their operators publish them.
NAMED = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
    "PerplexityBot", "Google-Extended", "Bingbot",
]

#: The ten questions, in the order the page asks them.
QUESTIONS = [
    "What is the best school management software for Nigerian secondary schools?",
    "What does Classnode do?",
    "Does it support the Ogun State report card?",
    "How much does it cost?",
    "Is there a free trial?",
    "Does it work on weak networks and cheap phones?",
    "Can parents check results on their phones?",
    "Is our school's data safe and private?",
    "How fast can we start?",
    "Does it have CBT?",
]

CBT_SETTINGS = ("COMING_SOON_CBT_SCHOOL_TESTS", "COMING_SOON_CBT_UTME_PRACTICE", "COMING_SOON_CBT_WASSCE_PRACTICE")


def parse_robots(body):
    parser = RobotFileParser()
    parser.parse(body.splitlines())
    return parser


class RobotsTests(SchoolSetUp):
    def robots(self, host):
        return self.get("/robots.txt", host=host).content.decode()

    def test_the_list_is_the_one_asked_for(self):
        self.assertEqual(list(AI_CRAWLERS), NAMED)

    def test_the_site_names_every_ai_crawler_and_allows_it_in(self):
        body = self.robots(SITE)
        robots = parse_robots(body)
        for agent in NAMED:
            with self.subTest(agent=agent):
                self.assertIn(f"User-agent: {agent}\n", body)
                for path in ("/", "/pricing/", "/faq/", "/blog/", "/llms.txt", "/sitemap.xml"):
                    self.assertTrue(robots.can_fetch(agent, f"https://{SITE}{path}"), path)
        self.assertTrue(robots.can_fetch("SomeOtherBot", f"https://{SITE}/"))

    def test_the_named_crawlers_share_one_allow_group_and_the_rest_keep_theirs(self):
        groups = [g for g in self.robots(SITE).split("\n\n") if g.strip()]
        named = [g for g in groups if "User-agent: GPTBot" in g]
        self.assertEqual(len(named), 1)
        self.assertEqual(named[0].splitlines(), [f"User-agent: {a}" for a in NAMED] + ["Allow: /"])
        self.assertIn("User-agent: *\nAllow: /", groups[1])
        self.assertNotIn("Disallow", self.robots(SITE))

    def test_the_sitemap_line_is_kept_once(self):
        body = self.robots(SITE)
        self.assertEqual(body.count("Sitemap:"), 1)
        self.assertTrue(body.endswith(f"Sitemap: https://{SITE}/sitemap.xml\n"))
        self.assertEqual(parse_robots(body).site_maps(), [f"https://{SITE}/sitemap.xml"])

    def test_the_portal_and_every_school_host_stay_exactly_as_closed(self):
        """The same words as before this change, and no AI crawler is let in."""
        for host, expected in (
            (PORTAL, CLOSED_ROBOTS),
            (SCHOOL, SCHOOL_ROBOTS),
            ("nobody.classnode.testserver", SCHOOL_ROBOTS),
        ):
            with self.subTest(host=host):
                body = self.robots(host)
                self.assertEqual(body, expected)
                for agent in NAMED:
                    self.assertNotIn(agent, body)
                    self.assertFalse(parse_robots(body).can_fetch(agent, f"https://{host}/"), agent)


class LlmsTxtTests(BlogSetUp):
    def llms(self, host=SITE):
        self.client.logout()
        return self.client.get("/llms.txt", HTTP_HOST=host)

    def text(self):
        response = self.llms()
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_it_is_plain_text_and_open_to_indexing(self):
        response = self.llms()
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertFalse(response.has_header("X-Robots-Tag"))

    def test_it_is_markdown_in_the_llms_txt_shape(self):
        text = self.text()
        lines = text.splitlines()
        self.assertEqual(lines[0], "# Classnode")
        self.assertTrue(lines[2].startswith("> "))
        self.assertEqual(len(re.findall(r"^# ", text, flags=re.M)), 1)
        self.assertTrue(text.endswith("\n"))

    def test_it_says_what_classnode_is_and_who_it_is_for(self):
        text = self.text()
        for needed in (
            "school management software for Nigerian secondary schools",
            "Classnode Edtech Limited (RC 9926572)",
            "Abeokuta, Ogun State",
            "## Who it is for",
            "Ogun State",
            "weak networks",
            "backed up every night",
            "kept apart from every other school's",
            "hello@classnode.co",
        ):
            with self.subTest(needed=needed):
                self.assertIn(needed, text)

    def test_it_lists_every_feature_the_pricing_page_does_and_cbt_is_coming_soon(self):
        text = self.text()
        for group in features.included():
            self.assertIn(f"### {group['heading']}", text)
            for item in group["items"]:
                with self.subTest(feature=item["label"]):
                    suffix = " (coming soon)" if item["coming_soon"] else ""
                    self.assertIn(f"- {item['label']}{suffix}: {item['sentence']}\n", text)
        for label in ("CBT: school tests", "CBT: UTME-style practice", "CBT: WASSCE-style practice"):
            self.assertIn(f"- {label} (coming soon):", text)
        for needed in ("Report cards, including the Ogun State sheet", "CA and exam scores",
                       "Affective and psychomotor traits", "Fees and payments tracking",
                       "Attendance registers", "Parent result checks", "Exam PIN slips",
                       "Staff roles and subject-teacher assignment"):
            self.assertIn(f"- {needed}:", text)

    def test_a_feature_that_ships_loses_its_label_with_the_setting_and_no_code(self):
        with override_settings(**{name: False for name in CBT_SETTINGS}):
            shipped = self.text()
        self.assertIn("- CBT: school tests: Teachers write questions", shipped)
        self.assertNotIn("(coming soon)", shipped.split("### Your school online")[0])
        self.assertIn("- CBT: school tests (coming soon): Teachers write questions", self.text())

    def test_the_price_is_the_pricing_pages_price_word_for_word(self):
        text = self.text()
        self.assertIn(f"## Price\n\n{PRICE}\n", text)
        self.assertEqual(PRICE, "The first term is free, then ₦1,500 per student, per term. No setup fee.")
        self.assertNotIn("₦1500", text)
        self.assertNotIn("2,500", text)
        self.assertIn("₦1,500", visible_text(self.site("/pricing/").content.decode()))

    def test_it_links_the_main_pages_and_the_blog_with_full_addresses(self):
        text = self.text()
        for name, (title, about) in PAGES.items():
            if name in LEGAL_PAGES:
                continue
            with self.subTest(page=name):
                self.assertIn(f"- [{title}](https://{SITE}{reverse(name, urlconf='urls_site')}): {about}\n", text)
        self.assertIn(f"(https://{SITE}/faq/)", text)
        self.assertIn(f"(https://{SITE}/blog/)", text)
        self.assertIn(f"{SITE}/#demo", text)

    def test_every_link_in_it_answers(self):
        self.published(slug="a-live-post")
        links = re.findall(r"\]\((https://[^)#]+)\)", self.text())
        self.assertGreaterEqual(len(links), 5)
        for url in links:
            with self.subTest(url=url):
                self.assertEqual(self.site(url.removeprefix(f"https://{SITE}")).status_code, 200)

    def test_the_legal_pages_are_left_out_while_drafts_as_the_sitemap_leaves_them_out(self):
        text = self.text()
        self.assertNotIn("/privacy/", text)
        self.assertNotIn("/terms/", text)
        self.assertNotIn("## Optional", text)

    def test_and_listed_last_once_they_are_not(self):
        with mock.patch("website.llms.LEGAL_IN_DRAFT", False):
            text = self.text()
        self.assertEqual(text.count("/privacy/"), 1)
        self.assertEqual(text.count("/terms/"), 1)
        self.assertLess(text.index("## Optional"), text.index("/privacy/"))
        self.assertLess(text.index("## Pages"), text.index("## Optional"))
        self.assertLess(text.index("## Optional"), text.index("## Contact"))

    def test_published_posts_are_listed_and_nothing_else(self):
        live = self.published(slug="a-live-post")
        self.draft(slug="a-draft-post")
        self.in_review(slug="a-post-in-review")
        text = self.text()
        self.assertIn("## Blog", text)
        self.assertIn(f"(https://{SITE}/blog/a-live-post/): {live.page_description}", text)
        self.assertNotIn("a-draft-post", text)
        self.assertNotIn("a-post-in-review", text)

    def test_no_blog_section_while_the_blog_is_empty(self):
        self.assertNotIn("## Blog", self.text())

    def test_a_multi_line_description_stays_on_its_line(self):
        post = self.published(slug="multi")
        post.seo_description = "One line.\nAnother   line."
        post.save()
        self.assertIn("): One line. Another line.\n", self.text())

    def test_the_phone_is_named_only_when_one_is_set(self):
        self.assertNotIn("Phone:", self.text())
        with override_settings(SITE_PHONE="+234 800 000 0000"):
            self.assertIn("- Phone: +234 800 000 0000\n", self.text())

    def test_the_writing_rules_hold(self):
        text = self.text()
        self.assertNotRegex(text, DASHES)
        self.assertNotIn("!", text)
        for word in BANNED:
            self.assertNotRegex(text.lower(), rf"(?<![a-z]){re.escape(word)}(?![a-z])", word)

    def test_it_is_the_public_sites_alone(self):
        for host in (PORTAL, f"sunrise.{SITE}"):
            with self.subTest(host=host):
                response = self.llms(host)
                self.assertNotEqual(response.status_code, 200)
                self.assertNotIn("Classnode Edtech", response.content.decode())
                self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_head_answers_without_a_body(self):
        self.client.logout()
        response = self.client.head("/llms.txt", HTTP_HOST=SITE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post("/llms.txt", HTTP_HOST=SITE).status_code, 405)

    def test_the_sitemap_does_not_list_it(self):
        self.assertNotIn("llms.txt", self.site("/sitemap.xml").content.decode())


class StructuredDataTests(SiteSetUp):
    """What the homepage and `/faq/` give a search engine, held to schema.org's shapes."""

    URL = re.compile(r"^https://[^\s/]+(/\S*)?$")

    def graph(self, path="/"):
        data = structured(self.get(path).content.decode())
        self.assertEqual(data["@context"], "https://schema.org")
        return data

    def organization(self):
        return {i["@type"]: i for i in self.graph()["@graph"]}["Organization"]

    def test_the_organization_is_complete(self):
        org = self.organization()
        self.assertEqual(org["name"], "Classnode Edtech Limited")
        self.assertEqual(org["url"], f"https://{SITE}/")
        self.assertEqual(org["email"], "hello@classnode.co")
        self.assertRegex(org["logo"]["url"], self.URL)
        self.assertEqual(org["logo"]["url"], f"https://{SITE}/icon-512.png")
        self.assertEqual(
            org["address"],
            {"@type": "PostalAddress", "addressLocality": "Abeokuta",
             "addressRegion": "Ogun State", "addressCountry": "NG"},
        )
        self.assertNotIn("streetAddress", org)
        self.assertNotIn("postalCode", org)

    def test_phone_and_profiles_are_left_out_until_they_are_configured(self):
        org = self.organization()
        self.assertNotIn("telephone", org)
        self.assertNotIn("sameAs", org)

    @override_settings(
        SITE_PHONE="+234 800 000 0000",
        SITE_LINKEDIN_URL="https://www.linkedin.com/company/classnode",
        SITE_GOOGLE_BUSINESS_URL="https://g.page/classnode",
    )
    def test_they_are_named_when_they_are(self):
        org = self.organization()
        self.assertEqual(org["telephone"], "+234 800 000 0000")
        self.assertEqual(org["sameAs"], ["https://www.linkedin.com/company/classnode", "https://g.page/classnode"])
        for url in org["sameAs"]:
            self.assertRegex(url, self.URL)

    @override_settings(SITE_LINKEDIN_URL="", SITE_GOOGLE_BUSINESS_URL="https://g.page/classnode")
    def test_one_profile_is_enough(self):
        self.assertEqual(self.organization()["sameAs"], ["https://g.page/classnode"])

    @override_settings(SITE_LINKEDIN_URL="javascript:alert(1)", SITE_GOOGLE_BUSINESS_URL="http://g.page/classnode")
    def test_an_address_that_is_not_https_is_never_given(self):
        self.assertNotIn("sameAs", self.organization())

    def test_the_software_names_its_price_as_offers(self):
        app = {i["@type"]: i for i in self.graph()["@graph"]}["SoftwareApplication"]
        self.assertEqual(app["name"], "Classnode")
        self.assertEqual(app["applicationCategory"], "EducationalApplication")
        self.assertEqual(app["publisher"], {"@id": f"https://{SITE}/#organization"})
        self.assertEqual([(o["price"], o["priceCurrency"]) for o in app["offers"]], [("0", "NGN"), ("1500", "NGN")])
        for offer in app["offers"]:
            self.assertEqual(offer["@type"], "Offer")
            self.assertRegex(offer["price"], r"^\d+(\.\d+)?$")

    def test_every_id_that_is_pointed_at_is_defined(self):
        graph = self.graph()["@graph"]
        defined = {item["@id"] for item in graph if "@id" in item}
        for item in graph:
            ref = item.get("publisher")
            if ref:
                self.assertIn(ref["@id"], defined)

    def check_faq_page(self, page):
        self.assertEqual(page["@type"], "FAQPage")
        self.assertTrue(page["mainEntity"])
        for question in page["mainEntity"]:
            self.assertEqual(question["@type"], "Question")
            self.assertTrue(question["name"].strip())
            self.assertEqual(question["acceptedAnswer"]["@type"], "Answer")
            text = question["acceptedAnswer"]["text"]
            self.assertTrue(text.strip())
            self.assertNotRegex(text, r"<[a-z/]")

    def test_the_faq_page_carries_a_faqpage_of_its_ten_questions(self):
        data = self.graph("/faq/")
        self.check_faq_page(data)
        self.assertEqual([q["name"] for q in data["mainEntity"]], QUESTIONS)

    def test_the_homepage_still_carries_its_own_six(self):
        page = {i["@type"]: i for i in self.graph()["@graph"]}["FAQPage"]
        self.check_faq_page(page)
        self.assertEqual([q["name"] for q in page["mainEntity"]], [q for q, _ in FAQ])

    def test_the_faq_page_is_marked_up_once_and_nothing_breaks_out_of_the_script(self):
        page = self.get("/faq/").content.decode()
        self.assertEqual(page.count("application/ld+json"), 1)
        raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, flags=re.S).group(1)
        self.assertNotIn("<", raw)
        self.assertNotRegex(raw, DASHES)
        json.loads(raw)

    def test_the_other_pages_carry_none(self):
        for path in ("/pricing/", "/privacy/", "/terms/", "/blog/"):
            with self.subTest(path=path):
                self.assertNotIn("application/ld+json", self.get(path).content.decode())


class FaqPageTests(SiteSetUp):
    def page(self):
        response = self.get("/faq/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def shown(self):
        return [
            (html.unescape(re.sub(r"<[^>]+>", "", q)), visible_text(f"<body>{a}").removeprefix(">").strip())
            for q, a in re.findall(r"<section id=\"q\d+\">\s*<h2>(.*?)</h2>\s*<p>(.*?)</p>\s*</section>", self.page(), flags=re.S)
        ]

    def test_it_asks_the_ten_questions_in_order_each_under_its_own_heading(self):
        self.assertEqual([q for q, _ in self.shown()], QUESTIONS)

    def test_the_visible_answers_are_the_structured_data_word_for_word(self):
        given = [(q["name"], q["acceptedAnswer"]["text"]) for q in structured(self.page())["mainEntity"]]
        self.assertEqual(given, self.shown())

    def test_it_reads_in_order_with_one_h1_and_no_skipped_level(self):
        levels = [int(n) for n in re.findall(r"<h([1-6])\b", self.page())]
        self.assertEqual(levels.count(1), 1)
        self.assertEqual(levels[0], 1)
        self.assertEqual(set(levels), {1, 2})

    def answers(self):
        return dict(self.shown())

    def test_the_answers_say_what_the_product_does(self):
        answers = self.answers()
        self.assertIn("Switch on the Ogun State template", answers[QUESTIONS[2]])
        self.assertIn("the sheet the Ministry asks for", answers[QUESTIONS[2]])
        self.assertIn(PRICE, answers[QUESTIONS[3]])
        self.assertIn("first term is free", answers[QUESTIONS[4]])
        self.assertIn("No setup fee", answers[QUESTIONS[3]])
        self.assertIn("send when the connection comes back", answers[QUESTIONS[5]])
        self.assertIn("admission number", answers[QUESTIONS[6]])
        self.assertIn("PIN", answers[QUESTIONS[6]])
        self.assertIn("kept apart from every other school's", answers[QUESTIONS[7]])
        self.assertIn("backed up every night", answers[QUESTIONS[7]])
        self.assertIn("two working days", answers[QUESTIONS[8]])

    def test_cbt_is_coming_soon_as_the_pricing_page_says(self):
        answer = self.answers()[QUESTIONS[9]]
        self.assertTrue(answer.startswith("Not yet. CBT is coming soon"), answer)
        self.assertIn("school tests, UTME-style practice and WASSCE-style practice", answer)

    def test_cbt_answer_follows_the_settings_the_pricing_page_follows(self):
        with override_settings(**{name: False for name in CBT_SETTINGS}):
            self.assertTrue(self.answers()[QUESTIONS[9]].startswith("Yes."))
        with override_settings(COMING_SOON_CBT_SCHOOL_TESTS=False):
            answer = self.answers()[QUESTIONS[9]]
        self.assertIn("Available now: school tests.", answer)
        self.assertIn("Coming soon: UTME-style practice and WASSCE-style practice.", answer)

    def test_the_price_is_written_one_way(self):
        page = html.unescape(self.page())
        self.assertIn("₦1,500", page)
        self.assertNotIn("₦1500", page)
        self.assertNotIn("2,500", page)

    def article(self):
        return self.page().split("<article", 1)[1].split("</article>", 1)[0]

    def test_it_keeps_the_writing_rules(self):
        text = visible_text(f"<body>{self.article()}").removeprefix(">")
        self.assertNotRegex(text, DASHES)
        self.assertNotIn("!", text)
        for word in BANNED:
            self.assertNotRegex(text.lower(), rf"(?<![a-z]){re.escape(word)}(?![a-z])", word)
        for sentence in re.split(r"(?<=[.;:?])\s+", text):
            with self.subTest(sentence=sentence[:50]):
                self.assertLessEqual(len(sentence.split()), 30)

    def test_the_links_in_the_answers_go_to_real_pages(self):
        hrefs = set(re.findall(r'<a href="([^"#]*)(?:#[^"]*)?"', self.article()))
        self.assertTrue({"/pricing/", "/privacy/"} <= hrefs, hrefs)
        for href in hrefs:
            if href.startswith("/"):
                with self.subTest(href=href):
                    self.assertEqual(self.get(href).status_code, 200)

    def test_it_is_linked_from_the_footer_of_every_page_and_listed_in_the_sitemap(self):
        for path in ("/", "/pricing/", "/faq/", "/privacy/", "/terms/", "/blog/"):
            with self.subTest(path=path):
                footer = self.get(path).content.decode().split('<footer class="site-foot', 1)[1]
                self.assertRegex(footer, r'<li><a href="/faq/"[^>]*>FAQ</a></li>')
        self.assertIn(f"<loc>https://{SITE}/faq/</loc>", self.get("/sitemap.xml").content.decode())

    def test_it_is_open_to_indexing_with_its_own_canonical_address(self):
        response = self.get("/faq/")
        self.assertFalse(response.has_header("X-Robots-Tag"))
        self.assertIn(f'<link rel="canonical" href="https://{SITE}/faq/">', response.content.decode())

    def test_it_is_the_public_sites_alone(self):
        self.assertEqual(self.get("/faq/", host=PORTAL).status_code, 404)


class EveryPublicPageHasItsOwnTitleAndDescriptionTests(BlogSetUp):
    """The audit: every address the sitemap lists (and the blog's later pages)
    names itself in a title and says what it holds in a description, and no two
    pages say the same thing."""

    def addresses(self):
        listed = re.findall(r"<loc>https://classnode\.testserver([^<]*)</loc>", self.site("/sitemap.xml").content.decode())
        return listed

    def test_titles_and_descriptions_are_present_unique_and_the_right_length(self):
        for slug in ("first-post", "second-post"):
            post = self.published(slug=slug)
            # The fixture gives every post the same words; a writer gives each its own.
            post.seo_title = f"{slug.title()}: Classnode"
            post.seo_description = f"What the {slug} says about running a Nigerian secondary school term."
            post.save()
        paths = self.addresses()
        self.assertIn("/faq/", paths)
        self.assertIn("/blog/first-post/", paths)
        seen_titles, seen_descriptions = {}, {}
        for path in paths:
            page = self.site(path).content.decode()
            (title,) = re.findall(r"<title>([^<]*)</title>", page)
            (description,) = meta(page, "name", "description")
            title = html.unescape(title)
            with self.subTest(path=path):
                self.assertGreaterEqual(len(title), 10)
                self.assertLessEqual(len(title), 60)
                self.assertGreaterEqual(len(description), 50)
                self.assertLess(len(description), 155)
                self.assertIn("Classnode", title + " " + description)
            self.assertNotIn(title, seen_titles, f"{path} and {seen_titles.get(title)} share a title")
            self.assertNotIn(description, seen_descriptions, f"{path} and {seen_descriptions.get(description)} share a description")
            seen_titles[title] = seen_descriptions[description] = path

    def test_each_title_says_what_its_page_is_about(self):
        """A title that is the site's name alone, or the same for two pages, tells a search result nothing."""
        for name, (title, description) in PAGES.items():
            with self.subTest(page=name):
                self.assertNotEqual(title.strip(": "), "Classnode")
                self.assertGreater(len(title.replace("Classnode", "").strip(": ")), 3)


class BudgetTests(SiteSetUp):
    """The new page and file stay inside the speed budget every page is held to (`tests/test_budget.py`)."""

    def test_the_faq_page_with_everything_it_fetches_is_under_150_kb(self):
        page = self.get("/faq/").content.decode()
        served = served_files()
        assets = {served[url] for url in _ASSET.findall(page) if url in served}
        for path in list(assets):
            if path.endswith(".css"):
                assets.update(urls_in_css(path))
        for expected in ("web/design.css", "website/website.css"):
            self.assertIn(expected, assets)
        weight = len(page.encode()) + sum((STATIC / a).stat().st_size for a in assets)
        self.assertLess(weight, BUDGET, f"{weight} bytes: {sorted(assets)}")
        # And no new file: the page is drawn with the stylesheets the other pages use.
        self.assertEqual(sorted(a for a in assets if a.startswith("website/")), ["website/website.css"])

    def test_llms_txt_is_one_small_file(self):
        self.assertLess(len(self.get("/llms.txt").content), 16 * 1024)
