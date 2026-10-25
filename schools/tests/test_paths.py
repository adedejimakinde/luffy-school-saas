"""A school host's paths: each one the website's or the portal's, and the held ones.

`schools.paths` sorts every first path segment `urls.py` routes into the
website's (`PUBLIC_SITE`), the portal's (`PORTAL`) and the held ones
(`RESERVED`), and `website.crawlers` keeps every path but the website's out of
search engines whatever a view says. These tests hold the sorting to the
routes, the held names to a 404 at two schools, and the indexing to what it
was: no school host is indexable until its website exists.
"""

import re
from urllib.robotparser import RobotFileParser

from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import path, resolve

import urls
from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain
from schools.paths import NEVER_INDEXED, PORTAL, PUBLIC_SITE, RESERVED, first_segment
from schools.tests.tenants import connected_to, make_school
from schools.views import reserved
from website.crawlers import CLOSED_ROBOTS, ICONS, NOINDEX, SCHOOL_ROBOTS, CrawlerMiddleware
from website.tests.test_homepage import PORTAL as PORTAL_HOST
from website.tests.test_homepage import SITE, SiteSetUp

ST_MARYS = "st-marys.classnode.testserver"
GRACE = "grace.classnode.testserver"
SCHOOLS = (ST_MARYS, GRACE)
ROBOTS_META = re.compile(r'<meta name="robots" content="([^"]*)">')

#: Paths that must never be indexed, built or not, signed in or not.
NEVER = (
    "/sit/", "/sit/abc123/", "/sit/a/b/c", "/website/", "/website/preview/home",
    "/applicants/", "/applicants/42/", "/exam-slips/", "/check/", "/home/",
    "/register/", "/sign-in/", "/staff-sign-in/", "/api/csrf/",
)


def segments(patterns):
    return {first_segment(str(pattern.pattern)) for pattern in patterns}


def unclassified(patterns):
    """The first segments of `patterns` that are neither the website's nor the portal's."""
    return segments(patterns) - PUBLIC_SITE - NEVER_INDEXED


class EveryRouteIsSortedTests(SiteSetUp):
    def test_every_route_on_a_school_host_is_the_websites_or_never_indexed(self):
        self.assertEqual(unclassified(urls.urlpatterns), set())

    def test_a_route_added_without_being_sorted_is_caught(self):
        added = [*urls.urlpatterns, path("prospectus/", reserved)]
        self.assertEqual(unclassified(added), {"prospectus"})

    def test_no_name_is_both_and_no_name_is_stale(self):
        self.assertEqual(PUBLIC_SITE & NEVER_INDEXED, set())
        self.assertEqual(PORTAL & set(RESERVED), set())
        self.assertEqual(NEVER_INDEXED - segments(urls.urlpatterns), set())

    def test_the_website_paths_routed_are_the_fixed_pages_and_not_media_yet(self):
        self.assertEqual(
            segments(urls.urlpatterns) & PUBLIC_SITE,
            {"", "about", "admissions", "news", "gallery", "contact", "sitemap.xml", "robots.txt"},
        )

    def test_sit_and_the_other_held_names_are_held_everywhere_under_them(self):
        self.assertEqual(set(RESERVED), {"sit", "website", "applicants"})
        for name in RESERVED:
            for tail in ("", "x", "x/", "a/b/c", "preview/home"):
                with self.subTest(path=f"/{name}/{tail}"):
                    self.assertIs(resolve(f"/{name}/{tail}", urlconf="urls").func, reserved)

    def test_first_segment(self):
        for given, expected in (("/", ""), ("/sit/", "sit"), ("/sit/a/b", "sit"),
                                ("/sw.js", "sw.js"), ("/sitemap.xml", "sitemap.xml"),
                                ("sit/<path:rest>", "sit"), ("", "")):
            with self.subTest(given=given):
                self.assertEqual(first_segment(given), expected)


class TwoSchoolsSetUp(SiteSetUp):
    def setUp(self):
        super().setUp()
        self.st_marys = make_school("St Mary's College", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.st_marys, domain=ST_MARYS, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=GRACE, is_primary=True)

    def tearDown(self):
        connection.set_schema_to_public()

    def assertNoindex(self, response):
        self.assertEqual(response.get("X-Robots-Tag"), NOINDEX)


class HeldNamesAreA404Tests(TwoSchoolsSetUp):
    def test_signed_out_every_method_gets_a_noindex_404_at_both_schools(self):
        for host in SCHOOLS:
            for name in RESERVED:
                for where in (f"/{name}/", f"/{name}/anything/at/all"):
                    with self.subTest(host=host, path=where):
                        response = self.get(where, host=host)
                        self.assertEqual(response.status_code, 404)
                        self.assertNoindex(response)
                        posted = self.client.post(where, HTTP_HOST=host)
                        self.assertIn(posted.status_code, (403, 404))
                        self.assertNoindex(posted)

    def test_signed_in_at_one_school_it_is_a_404_there_and_never_a_page_at_the_other(self):
        user = User.objects.create_user("principal", "a-long-password-1")
        grant_membership(user, self.st_marys, Role.PRINCIPAL)
        self.client.force_login(user)
        for name in RESERVED:
            with self.subTest(name=name):
                own = self.get(f"/{name}/", host=ST_MARYS)
                self.assertEqual(own.status_code, 404)
                self.assertNoindex(own)
                other = self.get(f"/{name}/", host=GRACE)
                self.assertIn(other.status_code, (403, 404))
                self.assertNoindex(other)

    def test_the_portal_holds_them_too(self):
        # `urls_public.py` serves every school-host route as well.
        for name in RESERVED:
            with self.subTest(name=name):
                response = self.get(f"/{name}/", host=PORTAL_HOST)
                self.assertEqual(response.status_code, 404)
                self.assertNoindex(response)


class NothingIsIndexedYetTests(TwoSchoolsSetUp):
    def test_the_school_root_is_still_todays_page_and_still_noindex(self):
        for host, name in ((ST_MARYS, "St Mary&#x27;s College"), (GRACE, "Grace Academy")):
            with self.subTest(host=host):
                response = self.get("/", host=host)
                self.assertEqual(response.status_code, 200)
                page = response.content.decode()
                self.assertIn(f"<h1>{name}</h1>", page)
                self.assertIn('<a class="button primary" href="/check/">Check a result</a>', page)
                self.assertNoindex(response)
                self.assertEqual(ROBOTS_META.findall(page), ["noindex, nofollow"])

    def test_portal_pages_sit_exam_slips_and_sign_in_stay_noindex_at_both_schools(self):
        for host in SCHOOLS:
            for where in NEVER:
                with self.subTest(host=host, path=where):
                    self.assertNoindex(self.get(where, host=host))

    def test_the_portals_sign_in_pages_stay_noindex(self):
        for where in ("/sign-in/", "/staff-sign-in/", "/"):
            with self.subTest(path=where):
                response = self.get(where, host=PORTAL_HOST)
                self.assertNoindex(response)
                if response.status_code == 200:
                    self.assertEqual(
                        ROBOTS_META.findall(response.content.decode()), ["noindex, nofollow"]
                    )

    def test_the_public_site_is_unchanged(self):
        response = self.get("/", host=SITE)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.has_header("X-Robots-Tag"))


class RobotsTxtTests(TwoSchoolsSetUp):
    def robots(self, host):
        parser = RobotFileParser()
        parser.parse(self.get("/robots.txt", host=host).content.decode().splitlines())
        return parser

    def test_each_school_names_sit_and_the_other_never_indexed_paths(self):
        for host in SCHOOLS:
            with self.subTest(host=host):
                body = self.get("/robots.txt", host=host).content.decode()
                self.assertEqual(body, SCHOOL_ROBOTS)
                for line in ("Disallow: /sit/\n", "Disallow: /exam-slips/\n",
                             "Disallow: /website/\n", "Disallow: /applicants/\n",
                             "Disallow: /check/\n", "Disallow: /sign-in/\n",
                             "Disallow: /sw.js\n"):
                    self.assertIn(line, body)
                self.assertTrue(body.endswith("Disallow: /\n"))

    def test_each_school_is_closed_to_crawlers_as_before_but_for_the_icons(self):
        for host in SCHOOLS:
            robots = self.robots(host)
            for where in (*NEVER, "/", "/about/", "/news/"):
                with self.subTest(host=host, path=where):
                    self.assertFalse(robots.can_fetch("Googlebot", f"https://{host}{where}"))
            for where in ICONS:
                with self.subTest(host=host, path=where):
                    self.assertTrue(robots.can_fetch("Googlebot", f"https://{host}{where}"))

    def test_the_named_paths_stay_closed_once_the_last_line_goes(self):
        # What opening a school's website will do to this file: drop the
        # closing `Disallow: /`. The held and portal paths must not open with it.
        opened = RobotFileParser()
        opened.parse(SCHOOL_ROBOTS.removesuffix("Disallow: /\n").splitlines())
        for where in NEVER:
            with self.subTest(path=where):
                self.assertFalse(opened.can_fetch("Googlebot", f"https://{ST_MARYS}{where}"))
        for where in ("/", "/about/", "/news/a-post/", "/gallery/", "/sitemap.xml"):
            with self.subTest(path=where):
                self.assertTrue(opened.can_fetch("Googlebot", f"https://{ST_MARYS}{where}"))

    def test_the_portals_is_unchanged(self):
        self.assertEqual(self.get("/robots.txt", host=PORTAL_HOST).content.decode(), CLOSED_ROBOTS)


class AMarkedResponseTests(TwoSchoolsSetUp):
    """What a future website view's mark (`response.indexable = True`) can and cannot do."""

    def answer(self, host, where, *, indexable):
        """The middleware's answer, with the connection where serving `host` leaves it."""
        response = HttpResponse("a page")
        if indexable is not None:
            response.indexable = indexable
        request = RequestFactory().get(where, HTTP_HOST=host)
        school = {ST_MARYS: self.st_marys, GRACE: self.grace}.get(host)
        if school is None:
            connection.set_schema_to_public()
            return CrawlerMiddleware(lambda request: response)(request)
        with connected_to(school):
            return CrawlerMiddleware(lambda request: response)(request)

    def test_a_marked_website_page_on_a_school_host_is_the_one_thing_let_in(self):
        for host in SCHOOLS:
            for where in ("/", "/about/", "/news/a-post/", "/gallery/sports-day/", "/sitemap.xml"):
                with self.subTest(host=host, path=where):
                    response = self.answer(host, where, indexable=True)
                    self.assertFalse(response.has_header("X-Robots-Tag"))

    def test_the_mark_never_opens_sit_exam_slips_a_sign_in_page_or_the_portal(self):
        for host in SCHOOLS:
            for where in NEVER:
                with self.subTest(host=host, path=where):
                    self.assertNoindex(self.answer(host, where, indexable=True))
        for where in ("/", "/about/", "/sign-in/"):
            with self.subTest(host=PORTAL_HOST, path=where):
                self.assertNoindex(self.answer(PORTAL_HOST, where, indexable=True))

    def test_an_unmarked_page_or_a_mark_that_is_not_true_is_noindex(self):
        for host in SCHOOLS:
            for mark in (None, False, "yes", 1):
                with self.subTest(host=host, mark=mark):
                    self.assertNoindex(self.answer(host, "/", indexable=mark))
