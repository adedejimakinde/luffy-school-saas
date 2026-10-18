"""What search engines and shared links are told, on every host.

The public site is the one thing to index: each page with its own title and
description, one canonical address on the bare domain over https, a sitemap
and a robots.txt that points to it, structured data that says only what the
page says, a card for a shared link, and the icon beside a search result. Every other host (the portal, every
school's, a demo school's) and `/healthz/` say noindex, in a header and in the
page, and their robots.txt disallows everything.
"""

import html
import io
import json
import re
from pathlib import Path
from urllib.robotparser import RobotFileParser

from django.conf import settings
from django.db import connection
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from PIL import Image

from schools.models import Domain
from schools.tests.tenants import make_school
from tests.test_budget import STATIC, served_files
from website.crawlers import CLOSED_ROBOTS, ICONS, NOINDEX
from website.tests.test_homepage import PORTAL, SITE, SiteSetUp, words
from website.views import FAQ, LOGO, PAGES

SCHOOL = "sunrise-demo.classnode.testserver"
PAGE_PATHS = {name: reverse(name, urlconf=settings.SITE_URLCONF) for name in PAGES}
ROBOTS_META = re.compile(r'<meta name="robots" content="([^"]*)">')
DASHES = re.compile("[\u2013\u2014]")


def meta(page, attribute, name):
    found = re.findall(rf'<meta {attribute}="{re.escape(name)}" content="([^"]*)">', page)
    return [html.unescape(value) for value in found]


def structured(page):
    (raw,) = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, flags=re.S)
    return json.loads(raw)


class SchoolSetUp(SiteSetUp):
    """The site's set-up, and one school on its own subdomain: a demo school."""

    def setUp(self):
        super().setUp()
        self.school = make_school("Sunrise Demo Academy", "sunrise-demo", "sunrise_demo")
        Domain.objects.create(tenant=self.school, domain=SCHOOL, is_primary=True)

    def tearDown(self):
        connection.set_schema_to_public()


class NoindexOffThePublicSiteTests(SchoolSetUp):
    def assert_noindex(self, response):
        self.assertEqual(response["X-Robots-Tag"], NOINDEX)
        if response.get("Content-Type", "").startswith("text/html") and response.status_code == 200:
            self.assertEqual(ROBOTS_META.findall(response.content.decode()), [NOINDEX])

    def test_a_school_subdomain_sends_noindex(self):
        response = self.get("/", host=SCHOOL)
        self.assertEqual(response.status_code, 200)
        self.assert_noindex(response)
        for path in ("/check/", "/sign-in/", "/staff-sign-in/", "/cards/", "/register/", "/nowhere/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, host=SCHOOL)["X-Robots-Tag"], NOINDEX)

    def test_the_portal_sends_noindex_on_both_sign_in_pages_and_platform(self):
        for path in ("/sign-in/", "/staff-sign-in/"):
            with self.subTest(path=path):
                response = self.get(path, host=PORTAL)
                self.assertEqual(response.status_code, 200)
                self.assert_noindex(response)
        for path in ("/", "/platform/", "/platform/handover/", "/admin/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, host=PORTAL)["X-Robots-Tag"], NOINDEX)

    def test_healthz_sends_noindex_on_every_host_the_sites_too(self):
        for host in (SITE, PORTAL, SCHOOL):
            with self.subTest(host=host):
                response = self.get("/healthz/", host=host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["X-Robots-Tag"], NOINDEX)

    def test_a_host_nobody_owns_sends_noindex(self):
        response = self.get("/", host="nobody.classnode.testserver")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["X-Robots-Tag"], NOINDEX)

    def test_the_public_site_does_not(self):
        for path in [*PAGE_PATHS.values(), "/?sent=1", "/sitemap.xml", "/robots.txt"]:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.has_header("X-Robots-Tag"))
                self.assertEqual(ROBOTS_META.findall(response.content.decode()), [])

    def test_robots_txt_closes_every_host_but_the_site(self):
        for host in (PORTAL, SCHOOL, "nobody.classnode.testserver"):
            with self.subTest(host=host):
                response = self.get("/robots.txt", host=host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content.decode(), CLOSED_ROBOTS)
                robots = self.robots(host)
                for path in ("/", "/sign-in/", "/staff-sign-in/", "/register/", "/favicon"):
                    self.assertFalse(robots.can_fetch("Googlebot", f"https://{host}{path}"), path)
        site = self.get("/robots.txt").content.decode()
        self.assertIn(f"Sitemap: https://{SITE}/sitemap.xml\n", site)
        self.assertNotIn("Disallow: /", site)

    def test_robots_txt_blocks_no_icon_on_any_host(self):
        for host in (SITE, PORTAL, SCHOOL):
            robots = self.robots(host)
            for path in ICONS:
                with self.subTest(host=host, path=path):
                    self.assertTrue(robots.can_fetch("Googlebot", f"https://{host}{path}"))
                    self.assertTrue(robots.can_fetch("Googlebot-Image", f"https://{host}{path}"))

    def robots(self, host):
        robots = RobotFileParser()
        robots.parse(self.get("/robots.txt", host=host).content.decode().splitlines())
        return robots


class TheSharedHeadIsNoindexByDefaultTests(SimpleTestCase):
    """The control for the meta tag: every page drawn from the design's head
    says noindex unless its view says it is the public site's."""

    def test_noindex_unless_indexable(self):
        self.assertEqual(ROBOTS_META.findall(render_to_string("design/head.html")), [NOINDEX])
        self.assertEqual(ROBOTS_META.findall(render_to_string("design/head.html", {"indexable": True})), [])


class OneAddressTests(SiteSetUp):
    def test_each_page_names_its_own_canonical_address_once(self):
        for path in PAGE_PATHS.values():
            with self.subTest(path=path):
                page = self.get(path).content.decode()
                self.assertEqual(re.findall(r'<link rel="canonical" href="([^"]*)">', page),
                                 [f"https://{SITE}{path}"])

    def test_a_query_is_not_part_of_it(self):
        page = self.get("/?sent=1").content.decode()
        self.assertIn(f'<link rel="canonical" href="https://{SITE}/">', page)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_plain_http_is_sent_to_https(self):
        response = self.get("/terms/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"https://{SITE}/terms/")

    def test_www_over_plain_http_is_one_hop(self):
        with override_settings(SECURE_SSL_REDIRECT=True):
            response = self.get("/", host=f"www.{SITE}")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"https://{SITE}/")


class TheSitemapTests(SiteSetUp):
    def test_it_lists_every_public_page_and_nothing_else(self):
        response = self.get("/sitemap.xml")
        self.assertEqual(response["Content-Type"], "application/xml; charset=utf-8")
        listed = re.findall(r"<loc>([^<]*)</loc>", response.content.decode())
        self.assertEqual(listed, [f"https://{SITE}{path}" for path in PAGE_PATHS.values()])

    def test_every_route_on_the_site_is_a_page_or_the_sitemap(self):
        from urls_site import urlpatterns

        # And the blog's: its later pages, its posts and their pictures, each
        # held by `blog/tests/test_public.py` to published posts only.
        blog = {"blog-page", "blog-post", "blog-image", "blog-image-small"}
        self.assertEqual({p.name for p in urlpatterns}, {*PAGES, "site-sitemap", *blog})

    def test_every_listed_page_answers_and_names_itself_canonical(self):
        for url in re.findall(r"<loc>([^<]*)</loc>", self.get("/sitemap.xml").content.decode()):
            path = url.removeprefix(f"https://{SITE}")
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'<link rel="canonical" href="{url}">', response.content.decode())

    def test_it_is_the_sites_alone(self):
        self.assertEqual(self.get("/sitemap.xml", host=PORTAL).status_code, 404)


class TitlesAndDescriptionsTests(SiteSetUp):
    def pages(self):
        for name, path in PAGE_PATHS.items():
            yield name, self.get(path).content.decode()

    def test_the_homepage_title_is_whole_in_a_search_result_and_starts_with_the_name(self):
        (title,) = re.findall(r"<title>([^<]*)</title>", self.get().content.decode())
        title = html.unescape(title)
        self.assertEqual(title, "Classnode: School software for Nigerian schools")
        self.assertLessEqual(len(title), 60)
        self.assertTrue(title.startswith("Classnode: "), title)

    def test_the_price_is_written_as_the_page_writes_it(self):
        """₦2,500, with its comma, in every description a search result or a
        shared link can show; never ₦2500."""
        page = self.get().content.decode()
        self.assertIn("₦2,500", html.unescape(re.sub(r"<[^>]+>", " ", page)))
        for attribute, name in (("name", "description"), ("property", "og:description"),
                                ("name", "twitter:description")):
            with self.subTest(meta=name):
                (description,) = meta(page, attribute, name)
                self.assertIn("₦2,500 per student, per term.", description)
        self.assertNotIn("₦2500", html.unescape(page))

    def test_each_page_has_its_own_title_and_description_within_their_lengths(self):
        titles, descriptions = set(), set()
        for name, page in self.pages():
            with self.subTest(page=name):
                (title,) = re.findall(r"<title>([^<]*)</title>", page)
                (description,) = meta(page, "name", "description")
                title = html.unescape(title)
                self.assertEqual((title, description), PAGES[name])
                self.assertLessEqual(len(title), 60)
                self.assertLess(len(description), 155)
                self.assertNotRegex(title + description, DASHES)
                titles.add(title)
                descriptions.add(description)
        self.assertEqual(len(titles), len(PAGES))
        self.assertEqual(len(descriptions), len(PAGES))


class TheShareCardTests(SiteSetUp):
    def test_every_page_has_open_graph_and_a_large_twitter_card(self):
        image = None
        for name, path in PAGE_PATHS.items():
            with self.subTest(page=name):
                page = self.get(path).content.decode()
                title, description = PAGES[name]
                self.assertEqual(meta(page, "property", "og:title"), [title])
                self.assertEqual(meta(page, "property", "og:description"), [description])
                self.assertEqual(meta(page, "property", "og:url"), [f"https://{SITE}{path}"])
                self.assertEqual(meta(page, "property", "og:type"), ["website"])
                self.assertEqual(meta(page, "name", "twitter:card"), ["summary_large_image"])
                self.assertEqual(meta(page, "name", "twitter:title"), [title])
                (image,) = meta(page, "property", "og:image")
                self.assertEqual(meta(page, "name", "twitter:image"), [image])
                self.assertEqual(meta(page, "property", "og:image:width"), ["1200"])
                self.assertEqual(meta(page, "property", "og:image:height"), ["630"])
                self.assertTrue(meta(page, "property", "og:image:alt")[0])
        self.assertTrue(image.startswith(f"https://{SITE}{settings.STATIC_URL}"), image)
        self.assertEqual(served_files()[image.removeprefix(f"https://{SITE}")], "website/share.png")

    def test_the_share_image_is_1200_by_630_and_small(self):
        path = STATIC / "website" / "share.png"
        with Image.open(path) as picture:
            self.assertEqual((picture.format, picture.size), ("PNG", (1200, 630)))
            self.assertEqual(picture.convert("RGB").getpixel((600, 600)), (0x14, 0x3D, 0x8C))
        self.assertLess(path.stat().st_size, 150 * 1000)


class TheStructuredDataTests(SiteSetUp):
    def setUp(self):
        self.page = self.get().content.decode()
        self.graph = {item["@type"]: item for item in structured(self.page)["@graph"]}

    def test_the_organization(self):
        org = self.graph["Organization"]
        self.assertEqual(org["name"], "Classnode Edtech Limited")
        self.assertEqual(org["email"], "hello@classnode.co")
        self.assertEqual(org["url"], f"https://{SITE}/")
        self.assertNotIn("address", org)
        self.assertEqual(org["logo"]["url"], f"https://{SITE}/icon-512.png")
        self.assertEqual((org["logo"]["width"], org["logo"]["height"]), (512, 512))
        response = self.get(LOGO)
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/png"))
        with Image.open(io.BytesIO(b"".join(response.streaming_content))) as picture:
            self.assertEqual((picture.format, picture.size), ("PNG", (512, 512)))

    def test_the_software_and_its_price(self):
        app = self.graph["SoftwareApplication"]
        self.assertEqual(app["applicationCategory"], "EducationalApplication")
        self.assertEqual(app["publisher"], {"@id": self.graph["Organization"]["@id"]})
        offer = app["offers"]
        self.assertEqual((offer["price"], offer["priceCurrency"]), ("2500", "NGN"))
        unit = offer["priceSpecification"]
        self.assertEqual((unit["price"], unit["priceCurrency"]), ("2500", "NGN"))
        self.assertEqual(unit["unitText"], "per student, per term")
        # `price` is the bare number schema.org asks for; the words carry the comma.
        self.assertEqual(offer["description"], "₦2,500 per student, per term. No setup fee.")
        self.assertIn("₦2,500 per student, per term.", app["description"])
        self.assertNotIn("₦2500", json.dumps(structured(self.page), ensure_ascii=False))

    def test_the_faq_is_the_visible_questions_and_answers_word_for_word(self):
        shown = [
            (words(q), words(a))
            for q, a in re.findall(
                r"<details>\s*<summary>(.*?)</summary>\s*<p>(.*?)</p>\s*</details>", self.page, flags=re.S
            )
        ]
        given = [
            (item["name"], item["acceptedAnswer"]["text"])
            for item in self.graph["FAQPage"]["mainEntity"]
        ]
        self.assertEqual(len(given), 6)
        self.assertEqual(given, shown)
        self.assertEqual([q for q, _ in given], [q for q, _ in FAQ])

    def test_no_ratings_reviews_or_address_anywhere(self):
        raw = json.dumps(structured(self.page))
        for word in ("aggregateRating", "review", "Review", "ratingValue", "address", "PostalAddress"):
            with self.subTest(word=word):
                self.assertNotIn(word, raw)

    def test_only_the_homepage_carries_it_and_no_dash_in_it(self):
        self.assertNotRegex(json.dumps(structured(self.page), ensure_ascii=False), DASHES)
        for path in ("/privacy/", "/terms/"):
            self.assertNotIn("application/ld+json", self.get(path).content.decode())


class ThePagesReadInOrderTests(SiteSetUp):
    """One h1, headings that never skip a level, every image described, and
    public pages reached by links."""

    def test_one_h1_and_no_skipped_level(self):
        for path in PAGE_PATHS.values():
            with self.subTest(path=path):
                page = self.get(path).content.decode()
                levels = [int(n) for n in re.findall(r"<h([1-6])\b", page)]
                self.assertEqual(levels.count(1), 1)
                self.assertEqual(levels[0], 1)
                for before, after in zip(levels, levels[1:]):
                    self.assertLessEqual(after, before + 1, levels)

    def test_every_image_has_a_description(self):
        for path in PAGE_PATHS.values():
            with self.subTest(path=path):
                for tag in re.findall(r"<img\b[^>]*>", self.get(path).content.decode()):
                    self.assertRegex(tag, r'\balt="[^"]{12,}"', tag)

    def test_every_public_page_links_to_every_other_with_a_real_link(self):
        for path in PAGE_PATHS.values():
            page = self.get(path).content.decode()
            for other in PAGE_PATHS.values():
                with self.subTest(page=path, link=other):
                    self.assertRegex(page, rf'<a\b[^>]*\bhref="{re.escape(other)}"')
            with self.subTest(page=path):
                for button in re.findall(r"<button\b[^>]*>", page):
                    self.assertNotRegex(button, r"\b(href|onclick|formaction)=", button)


ICON_LINKS = (
    '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">',
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
    '<link rel="manifest" href="/site.webmanifest">',
)

#: Each icon's type, and its size where it has one.
ICON_FILES = {
    "/favicon.ico": ("image/x-icon", None),
    "/favicon.svg": ("image/svg+xml", None),
    "/apple-touch-icon.png": ("image/png", (180, 180)),
    "/icon-192.png": ("image/png", (192, 192)),
    "/icon-512.png": ("image/png", (512, 512)),
    "/site.webmanifest": ("application/manifest+json", None),
}

ONE_BLUE = (0x14, 0x3D, 0x8C)
SHAPE = {"x", "y", "width", "height", "rx", "d", "cx", "cy", "r", "stroke-width"}


def geometry(svg):
    """Each shape's tag and the attributes that place and size it, in order."""
    return [
        (tag, sorted((k, v) for k, v in re.findall(r'([a-z-]+)="([^"]*)"', attrs) if k in SHAPE))
        for tag, attrs in re.findall(r"<(rect|path|circle)\b([^>]*)>", svg)
    ]


class TheIconsTests(SchoolSetUp):
    """The mark beside a search result and on a tab: at fixed addresses at the
    root of every host, answered there with the file and not sent anywhere."""

    def fetch(self, path, host=SITE):
        response = self.get(path, host=host)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        return response, body

    def test_the_list_is_the_files(self):
        self.assertEqual(set(ICON_FILES), set(ICONS))
        self.assertEqual({p.name for p in Path(settings.WHITENOISE_ROOT).iterdir()},
                         {path.lstrip("/") for path in ICONS})

    def test_each_answers_200_with_its_type_on_every_host(self):
        for host in (SITE, PORTAL, SCHOOL):
            for path, (kind, size) in ICON_FILES.items():
                with self.subTest(host=host, path=path):
                    response, body = self.fetch(path, host)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["Content-Type"].split(";")[0], kind)
                    self.assertGreater(len(body), 100)
                    if size:
                        with Image.open(io.BytesIO(body)) as picture:
                            self.assertEqual((picture.format, picture.size), ("PNG", size))

    def test_favicon_ico_and_the_touch_icon_are_images_on_the_site(self):
        for path in ("/favicon.ico", "/apple-touch-icon.png"):
            with self.subTest(path=path):
                response, _ = self.fetch(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Type"].startswith("image/"), response["Content-Type"])
                self.assertFalse(response.has_header("Location"))
                self.assertFalse(response.has_header("X-Robots-Tag"))

    def test_the_ico_holds_16_32_and_48_and_each_is_the_mark(self):
        _, body = self.fetch("/favicon.ico")
        with Image.open(io.BytesIO(body)) as icon:
            self.assertEqual(icon.format, "ICO")
            self.assertEqual(icon.info["sizes"], {(16, 16), (32, 32), (48, 48)})
            for size in (16, 32, 48):
                with self.subTest(size=size):
                    icon.size = (size, size)
                    frame = icon.convert("RGBA")
                    self.assertEqual(frame.getpixel((0, 0))[3], 0, "a rounded corner")
                    self.assertEqual(frame.getpixel((size // 2, size - 2))[:3], ONE_BLUE)

    def test_the_touch_icon_is_opaque_one_blue_to_the_edge(self):
        _, body = self.fetch("/apple-touch-icon.png")
        with Image.open(io.BytesIO(body)) as picture:
            self.assertEqual(picture.mode, "RGB")
            self.assertEqual(picture.getpixel((0, 0)), ONE_BLUE)

    def test_the_svg_is_the_headers_mark(self):
        """The same shapes as `i-brand-mark`, in the same order; only its
        colours are written out, since an icon file has no stylesheet."""
        _, body = self.fetch("/favicon.svg")
        svg = body.decode().split(">", 1)[1]
        icons = (Path(settings.BASE_DIR) / "templates/design/icons.html").read_text()
        (mark,) = re.findall(r'<symbol id="i-brand-mark"[^>]*>(.*?)</symbol>', icons, re.S)
        self.assertEqual(geometry(svg), geometry(mark))
        self.assertIn('<rect x="1" y="1" width="22" height="22" rx="6" fill="#143D8C"/>', svg)

    def test_the_manifest_names_both_icons_and_each_answers(self):
        _, body = self.fetch("/site.webmanifest")
        manifest = json.loads(body)
        self.assertEqual(manifest["name"], "Classnode")
        self.assertEqual(
            [(icon["src"], icon["sizes"], icon["type"]) for icon in manifest["icons"]],
            [("/icon-192.png", "192x192", "image/png"), ("/icon-512.png", "512x512", "image/png")],
        )
        for icon in manifest["icons"]:
            with self.subTest(src=icon["src"]):
                self.assertEqual(self.fetch(icon["src"])[0].status_code, 200)

    def test_every_page_names_them_on_the_site_the_portal_and_a_school(self):
        pages = [(SITE, path) for path in PAGE_PATHS.values()]
        pages += [(PORTAL, "/sign-in/"), (PORTAL, "/staff-sign-in/"), (PORTAL, "/write/sign-in/"),
                  (SCHOOL, "/")]
        for host, path in pages:
            with self.subTest(host=host, path=path):
                response = self.get(path, host=host)
                self.assertEqual(response.status_code, 200)
                page = response.content.decode()
                for link in ICON_LINKS:
                    self.assertEqual(page.count(link), 1, link)
