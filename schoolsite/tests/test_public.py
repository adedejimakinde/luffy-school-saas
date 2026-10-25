"""A school's public website, on its own host, at two schools. `docs/school-sites.md` PR 3.

Before a school publishes, its root is today's page and nothing else of the site
answers. After it, the pages it switched on are drawn from what it published,
never from the draft, each on its own school's host only, indexable, under a
Content-Security-Policy, cacheable, and with no cookie or session read on the
way, whoever is signed in.
"""

import base64
import hashlib
import re
from unittest import mock
from urllib.robotparser import RobotFileParser

from django.conf import settings
from django.core.cache import caches
from django.db import connection
from django.test import TestCase, override_settings

from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from website.crawlers import NOINDEX, SCHOOL_ROBOTS

from schoolsite import services
from schoolsite.demo import publish_demo_site
from schoolsite.models import Page
from schoolsite.sections import SectionRefused

SITE = "classnode.testserver"
PORTAL = "app.classnode.testserver"
ST_MARYS = "st-marys.classnode.testserver"
GRACE = "grace.classnode.testserver"
ROBOTS_META = re.compile(r'<meta name="robots" content="([^"]*)">')
STYLE = re.compile(r"<style>(.*?)</style>", re.S)


def hero(heading, link="/about/"):
    return {"heading": heading, "buttons": [{"label": "About us", "link": link}]}


@override_settings(SITE_HOST=SITE, ALLOWED_HOSTS=[".classnode.testserver", "testserver"])
class PublicSiteSetUp(TestCase):
    @classmethod
    def setUpTestData(cls):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

    def setUp(self):
        caches["sites"].clear()
        self.stmarys = make_school("St Mary's College", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.stmarys, domain=ST_MARYS, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=GRACE, is_primary=True)
        self.stmarys.address = "Off Ring Road, Ibadan"
        self.stmarys.phone = "0803 111 2222"
        self.stmarys.save()
        self.principal = User.objects.create_user("principal", "a-long-password-1", full_name="Rev. Sr. Okafor")
        self.grace_principal = User.objects.create_user("grace-principal", "a-long-password-1")
        self.grace_teacher = User.objects.create_user("grace-teacher", "a-long-password-1")
        grant_membership(self.principal, self.stmarys, Role.PRINCIPAL)
        grant_membership(self.grace_principal, self.grace, Role.PRINCIPAL)
        grant_membership(self.grace_teacher, self.grace, Role.TEACHER)

    def tearDown(self):
        connection.set_schema_to_public()

    def get(self, path, host=ST_MARYS, **extra):
        return self.client.get(path, HTTP_HOST=host, **extra)

    def build(self, who, school, heading, *, pages=("about",), publish=True):
        with connected_to(school):
            for key in pages:
                services.save_page_as(who, school, key, version=Page.objects.get(key=key).version, enabled=True)
            version = Page.objects.get(key="home").version
            services.add_section_as(who, school, "home", version=version, kind="hero", data=hero(heading))
            if "about" in pages:
                services.add_section_as(who, school, "about", version=Page.objects.get(key="about").version,
                                        kind="text", data={"body": f"About {school.name}."})
            if publish:
                return services.publish_as(who, school)

    def assertNoCookie(self, response):
        # `response.cookies`, not the headers: the test client keeps a
        # `Set-Cookie` there, and asking the headers would pass whatever happened.
        self.assertEqual(list(response.cookies), [], response.cookies.output())
        self.assertNotIn("cookie", response.get("Vary", "").lower())


class BeforeThePublishTests(PublicSiteSetUp):
    def test_the_root_is_todays_page_still_noindex_and_nothing_else_of_the_site_answers(self):
        for host, name in ((ST_MARYS, "St Mary&#x27;s College"), (GRACE, "Grace Academy")):
            with self.subTest(host=host):
                root = self.get("/", host)
                page = root.content.decode()
                self.assertEqual(root.status_code, 200)
                self.assertIn(f"<h1>{name}</h1>", page)
                self.assertIn('<a class="button primary" href="/check/">Check a result</a>', page)
                self.assertEqual(root["X-Robots-Tag"], NOINDEX)
                self.assertEqual(ROBOTS_META.findall(page), ["noindex, nofollow"])
                self.assertNotIn("Content-Security-Policy", root)
                for path in ("/about/", "/admissions/", "/news/", "/gallery/", "/contact/", "/sitemap.xml"):
                    self.assertEqual(self.get(path, host).status_code, 404, path)
                self.assertEqual(self.get("/robots.txt", host).content.decode(), SCHOOL_ROBOTS)

    def test_a_draft_is_never_served_even_with_pages_switched_on(self):
        self.build(self.principal, self.stmarys, "Draft only", publish=False)
        self.assertNotIn("Draft only", self.get("/").content.decode())
        self.assertEqual(self.get("/about/").status_code, 404)


class AfterThePublishTests(PublicSiteSetUp):
    def setUp(self):
        super().setUp()
        self.build(self.principal, self.stmarys, "Welcome to St Mary's")

    def test_each_switched_on_page_is_drawn_from_the_publish_and_indexable(self):
        for path, title in (("/", "St Mary&#x27;s College"), ("/about/", "About | St Mary&#x27;s College")):
            with self.subTest(path=path):
                response = self.get(path)
                page = response.content.decode()
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("X-Robots-Tag", response)
                self.assertEqual(ROBOTS_META.findall(page), [])
                self.assertIn(f"<title>{title}</title>", page)
                self.assertIn(f'<link rel="canonical" href="https://{ST_MARYS}{path}">', page)
        home = self.get("/").content.decode()
        self.assertIn("<h1>Welcome to St Mary&#x27;s</h1>", home)
        self.assertIn('<a class="button primary" href="/about/">About us</a>', home)
        self.assertIn('"@type":"EducationalOrganization"', home)

    def test_a_change_to_the_draft_after_the_publish_is_not_served_until_published(self):
        with connected_to(self.stmarys):
            section = services.draft_as(self.principal, self.stmarys)["pages"][0]["sections"][0]
            services.save_section_as(self.principal, self.stmarys, section["id"], version=section["version"],
                                     data={"heading": "Not yet published"})
            services.save_page_as(self.principal, self.stmarys, "contact",
                                  version=Page.objects.get(key="contact").version, enabled=True)
        caches["sites"].clear()
        home = self.get("/").content.decode()
        self.assertIn("Welcome to St Mary&#x27;s", home)
        self.assertNotIn("Not yet published", home)
        self.assertNotIn('href="/contact/"', home)
        self.assertEqual(self.get("/contact/").status_code, 404)

    def test_a_page_switched_off_is_a_404(self):
        for path in ("/admissions/", "/news/", "/gallery/", "/contact/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 404)

    def test_sign_in_is_a_menu_to_the_portals_two_doors(self):
        page = self.get("/").content.decode()
        self.assertIn('<summary>Sign in</summary>', page)
        self.assertIn(f'<a href="//{PORTAL}/sign-in/">Parent or guardian</a>', page)
        self.assertIn(f'<a href="//{PORTAL}/staff-sign-in/">Staff</a>', page)

    def test_the_menu_lists_the_pages_switched_on_and_marks_this_one(self):
        page = self.get("/about/").content.decode()
        self.assertIn('<a href="/">Home</a>', page)
        self.assertIn('<a href="/about/" aria-current="page">About</a>', page)
        self.assertNotIn('href="/admissions/"', page)

    def test_the_sitemap_lists_the_pages_switched_on_and_robots_opens_the_rest(self):
        sitemap = self.get("/sitemap.xml").content.decode()
        self.assertEqual(re.findall(r"<loc>([^<]*)</loc>", sitemap),
                         [f"https://{ST_MARYS}/", f"https://{ST_MARYS}/about/"])
        robots = RobotFileParser()
        robots.parse(self.get("/robots.txt").content.decode().splitlines())
        for path in ("/", "/about/", "/sitemap.xml"):
            self.assertTrue(robots.can_fetch("Googlebot", f"https://{ST_MARYS}{path}"), path)
        for path in ("/sit/", "/check/", "/home/", "/sign-in/", "/exam-slips/", "/api/csrf/"):
            self.assertFalse(robots.can_fetch("Googlebot", f"https://{ST_MARYS}{path}"), path)
        self.assertIn(f"Sitemap: https://{ST_MARYS}/sitemap.xml", self.get("/robots.txt").content.decode())

    def test_the_csp_refuses_every_script_and_every_inline_style_but_the_pages_own(self):
        response = self.get("/")
        csp = response["Content-Security-Policy"]
        (style,) = STYLE.findall(response.content.decode())
        digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
        self.assertIn(f"style-src 'self' 'sha256-{digest}'", csp)
        for rule in ("script-src 'none'", "object-src 'none'", "frame-src 'none'", "base-uri 'none'",
                     "frame-ancestors 'none'"):
            self.assertIn(rule, csp)
        self.assertNotIn("unsafe", csp)
        self.assertNotRegex(response.content.decode(), r"<script(?![^>]*application/ld\+json)")
        self.assertNotRegex(response.content.decode(), r'\sstyle="')

    def test_it_is_cacheable_and_answers_a_repeat_with_not_modified(self):
        first = self.get("/")
        self.assertEqual(first["Cache-Control"], "public, max-age=60, stale-while-revalidate=600")
        again = self.get("/", HTTP_IF_NONE_MATCH=first["ETag"])
        self.assertEqual(again.status_code, 304)

    def test_what_the_school_typed_is_escaped(self):
        with connected_to(self.stmarys):
            section = services.draft_as(self.principal, self.stmarys)["pages"][0]["sections"][0]
            services.save_section_as(self.principal, self.stmarys, section["id"], version=section["version"],
                                     data={"heading": '<script>alert("x")</script>'})
            services.publish_as(self.principal, self.stmarys)
        page = self.get("/").content.decode()
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", page)

    def test_a_link_field_refuses_javascript_data_and_a_protocol_relative_address(self):
        for link in ("javascript:alert(1)", "data:text/html,hi", "//evil.example/"):
            with self.subTest(link=link), connected_to(self.stmarys):
                version = Page.objects.get(key="about").version
                with self.assertRaises(SectionRefused):
                    services.add_section_as(self.principal, self.stmarys, "about", version=version, kind="hero",
                                            data=hero("About", link=link))

    def test_a_cache_that_is_down_is_a_slower_page_not_a_broken_one(self):
        broken = mock.Mock(get=mock.Mock(side_effect=ConnectionError), set=mock.Mock(side_effect=ConnectionError))
        with mock.patch("schoolsite.views.caches", {"sites": broken}):
            response = self.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Welcome to St Mary", response.content.decode())


class OneSchoolsPageIsNeverAnothersTests(PublicSiteSetUp):
    def test_same_path_same_revision_number_each_host_shows_its_own(self):
        mine = self.build(self.principal, self.stmarys, "St Mary's heading")
        theirs = self.build(self.grace_principal, self.grace, "Grace heading")
        self.assertEqual((mine.number, theirs.number), (1, 1))
        for _ in range(2):  # the second round is served from the cache
            st_marys, grace = self.get("/", ST_MARYS).content.decode(), self.get("/", GRACE).content.decode()
            self.assertIn("St Mary&#x27;s heading", st_marys)
            self.assertNotIn("Grace heading", st_marys)
            self.assertIn("Grace heading", grace)
            self.assertNotIn("St Mary", grace)

    def test_one_schools_publish_opens_nothing_at_the_other(self):
        self.build(self.principal, self.stmarys, "St Mary's heading")
        self.assertEqual(self.get("/about/", GRACE).status_code, 404)
        self.assertEqual(self.get("/sitemap.xml", GRACE).status_code, 404)
        self.assertEqual(self.get("/robots.txt", GRACE).content.decode(), SCHOOL_ROBOTS)
        self.assertEqual(self.get("/", GRACE)["X-Robots-Tag"], NOINDEX)

    def test_a_new_publish_is_drawn_at_once_and_only_on_its_own_host(self):
        self.build(self.principal, self.stmarys, "First")
        self.get("/", ST_MARYS)
        with connected_to(self.stmarys):
            section = services.draft_as(self.principal, self.stmarys)["pages"][0]["sections"][0]
            services.save_section_as(self.principal, self.stmarys, section["id"], version=section["version"],
                                     data={"heading": "Second"})
            services.publish_as(self.principal, self.stmarys)
        self.assertIn("Second", self.get("/", ST_MARYS).content.decode())
        self.assertNotIn("Second", self.get("/", GRACE).content.decode())

    def test_the_portal_serves_no_school_website(self):
        self.build(self.principal, self.stmarys, "St Mary's heading")
        for path in ("/about/", "/sitemap.xml", "/contact/"):
            self.assertEqual(self.get(path, PORTAL).status_code, 404, path)


class NoCookieAndNoSessionReadTests(PublicSiteSetUp):
    def test_signed_in_anywhere_a_public_page_sends_no_cookie_and_varies_on_none(self):
        self.build(self.principal, self.stmarys, "Welcome")
        for who in (self.principal, self.grace_teacher, None):
            if who:
                self.client.force_login(who)
            else:
                self.client.logout()
            for path in ("/", "/about/", "/sitemap.xml", "/robots.txt"):
                with self.subTest(who=str(who), path=path):
                    response = self.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertNoCookie(response)

    def test_todays_page_too_and_a_stranger_signed_in_elsewhere_sees_it_like_anyone(self):
        self.client.force_login(self.grace_teacher)
        response = self.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNoCookie(response)

    def test_the_portal_pages_on_the_same_host_still_slide_the_session_and_stay_noindex(self):
        # The control: the session middleware still does its work everywhere else.
        self.client.force_login(self.principal)
        response = self.get("/home/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertIn("Cookie", response["Vary"])
        self.assertEqual(response["X-Robots-Tag"], NOINDEX)
        stranger = self.get("/home/", GRACE)
        self.assertEqual(stranger.status_code, 403)


class TheDemoSiteTests(PublicSiteSetUp):
    def test_the_demo_schools_site_is_built_and_published_as_a_principal_would(self):
        with connected_to(self.stmarys):
            revision = publish_demo_site(self.principal, self.stmarys)
        self.assertEqual(revision.number, 1)
        for path in ("/", "/about/", "/admissions/", "/contact/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 200)
        contact = self.get("/contact/").content.decode()
        self.assertIn("Open in Maps", contact)
        self.assertIn('href="https://wa.me/2348030000000"', contact)
        self.assertIn('lang="yo"', self.get("/").content.decode())
