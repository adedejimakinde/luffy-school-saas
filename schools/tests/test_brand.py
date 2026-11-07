"""A school's crest, name and colour on its own host, and never on another's.

Two schools throughout, for the reason every tenancy test here gives: a brand
read from the wrong schema, or kept somewhere two requests share, passes any
one-school test. Sunrise has a crest and a dark colour that reads on white;
Harbour has no crest (the initials fallback) and a colour too light to read, so
it keeps the navy. Each is asserted on its own host, and each host is searched
for every trace of the other school.
"""

from django.db import connection
from django.test import TestCase, override_settings

from accounts.models import Role, User
from accounts.services import grant_membership
from files.kinds import Kind
from files.models import StoredFile
from schools import brand
from schools.models import Domain
from schools.tests.tenants import connected_to
from schools.tests.tenants import make_school as make_school_with_schema
from schools.tests.test_invitations import make_school

PORTAL = "testserver"
SUNRISE = "sunrise.testserver"
HARBOUR = "harbour.testserver"
PASSWORD = "correct-horse-battery"

SUNRISE_COLOUR = "#7A1F2B"  # 9.7:1 on white
HARBOUR_COLOUR = "#F5C518"  # 1.7:1 on white: refused, navy instead

#: Classnode's mark and wordmark, in the shell's markup or the staff door's.
CLASSNODE_MARK = r'</svg>(<span class="logo-word">)?classnode<'


def set_colour(school, colour):
    from schoolsite.models import SiteSettings

    with connected_to(school):
        row = SiteSettings.objects.get(pk=1)
        row.theme_options = {**row.theme_options, row.theme: {"colours": {"primary": colour}}}
        row.save(update_fields=["theme_options"])


def give_crest(school) -> str:
    with connected_to(school):
        stored = StoredFile.objects.create(
            schema_name=school.schema_name, kind=Kind.CREST, slot="crest", public=True,
            state="ready", sha256="a" * 64, variants={"site": {"bytes": 1}},
        )
    return stored.key


class BrandSetUp(TestCase):
    def setUp(self):
        portal = make_school("Portal", "portal", "public")
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)
        self.sunrise = make_school_with_schema("Sunrise Academy", "sunrise", "sunrise")
        Domain.objects.create(tenant=self.sunrise, domain=SUNRISE, is_primary=True)
        self.harbour = make_school_with_schema("Harbour College", "harbour", "harbour")
        Domain.objects.create(tenant=self.harbour, domain=HARBOUR, is_primary=True)

        self.ada = User.objects.create_user("sunrise.teacher", PASSWORD, full_name="Ada")
        grant_membership(self.ada, self.sunrise, Role.TEACHER)
        self.tunde = User.objects.create_user("harbour.teacher", PASSWORD, full_name="Tunde")
        grant_membership(self.tunde, self.harbour, Role.TEACHER)

        self.crest = give_crest(self.sunrise)
        set_colour(self.sunrise, SUNRISE_COLOUR)
        set_colour(self.harbour, HARBOUR_COLOUR)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def page(self, user, host, path="/timetable/"):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)
        response = self.client.get(path, HTTP_HOST=host)
        connection.set_schema_to_public()
        return response.status_code, response.content.decode()

    def assertNothingOfSunrise(self, html):
        self.assertNotIn("Sunrise Academy", html)
        self.assertNotIn(self.crest, html)
        self.assertNotIn(SUNRISE_COLOUR, html)


class EachSchoolWearsItsOwnTests(BrandSetUp):
    def test_sunrise_shows_its_crest_name_colour_and_tab_icon(self):
        status, html = self.page(self.ada, SUNRISE)

        self.assertEqual(status, 200)
        crest = f"/media/{self.crest}/site.png"
        self.assertIn(f'<link rel="icon" href="{crest}" type="image/png">', html)
        self.assertIn(f'<img src="{crest}"', html)
        self.assertIn('<span class="logo-name">Sunrise Academy</span>', html)
        self.assertIn(f"<style>:root{{--brand:{SUNRISE_COLOUR}}}</style>", html)
        self.assertIn("Powered by Classnode", html)
        # The Classnode wordmark has gone from the header and the sidebar.
        self.assertNotRegex(html, CLASSNODE_MARK)

    def test_harbour_gets_the_initials_the_navy_and_classnodes_tab_icon(self):
        status, html = self.page(self.tunde, HARBOUR)

        self.assertEqual(status, 200)
        self.assertIn('<span class="crest" aria-hidden="true">HC</span>', html)
        self.assertIn('<span class="logo-name">Harbour College</span>', html)
        self.assertIn('<link rel="icon" href="/favicon.svg"', html)
        # A colour that does not read on white is not used: no override, the navy stays.
        self.assertNotIn("--brand:", html)
        self.assertNotIn(HARBOUR_COLOUR, html)

    def test_nothing_of_sunrise_reaches_harbours_host_and_nothing_of_harbour_sunrises(self):
        _, harbour = self.page(self.tunde, HARBOUR)
        _, sunrise = self.page(self.ada, SUNRISE)

        self.assertNothingOfSunrise(harbour)
        self.assertNotIn("Harbour College", sunrise)
        self.assertNotIn(">HC<", sunrise)

    def test_one_request_after_another_never_carries_the_last_schools_brand(self):
        """No cache between requests: Sunrise, then Harbour, then Sunrise again."""
        for _ in range(2):
            _, sunrise = self.page(self.ada, SUNRISE)
            _, harbour = self.page(self.tunde, HARBOUR)
            self.assertIn(self.crest, sunrise)
            self.assertNothingOfSunrise(harbour)

    def test_the_family_pages_header_wears_it_too(self):
        _, html = self.page(self.ada, SUNRISE, "/cards/")
        self.assertIn('<div class="brand-bar"><div class="logo logo-school">', html)
        self.assertIn(self.crest, html)
        _, html = self.page(self.tunde, HARBOUR, "/cards/")
        self.assertIn(">HC</span>", html)
        self.assertNothingOfSunrise(html)

    def test_the_dashboard_wears_it_too(self):
        _, html = self.page(self.ada, SUNRISE, "/home/")
        self.assertIn('<span class="logo-name">Sunrise Academy</span>', html)
        _, html = self.page(self.tunde, HARBOUR, "/home/")
        self.assertNothingOfSunrise(html)


class NoSchoolIsNamedToAStrangerTests(BrandSetUp):
    def test_signed_out_on_a_schools_host_the_frame_is_classnodes(self):
        status, html = self.page(None, SUNRISE, "/home/")

        self.assertNothingOfSunrise(html)
        self.assertRegex(html, CLASSNODE_MARK)

    def test_a_member_of_the_other_school_is_not_shown_it(self):
        """Signed in at Harbour, asking Sunrise's host: refused, and told nothing of Sunrise's look."""
        status, html = self.page(self.tunde, SUNRISE, "/home/")

        self.assertNotIn(self.crest, html)
        self.assertNotIn(SUNRISE_COLOUR, html)

    def test_the_control_the_same_page_shows_a_member_the_brand(self):
        """The two above would pass on a page that drew no brand for anybody."""
        _, html = self.page(self.ada, SUNRISE, "/home/")
        self.assertIn(self.crest, html)


class TheDoorsTests(BrandSetUp):
    def test_the_portal_door_is_classnodes(self):
        for path in ("/staff-sign-in/", "/sign-in/"):
            with self.subTest(path=path):
                status, html = self.page(None, PORTAL, path)
                self.assertEqual(status, 200)
                self.assertRegex(html, CLASSNODE_MARK)
                self.assertNotIn("Powered by Classnode", html)
                self.assertNothingOfSunrise(html)
                self.assertNotIn("Harbour College", html)

    @override_settings(DEBUG=True, DEMO_SINGLE_HOST=True)
    def test_a_door_on_a_schools_host_wears_that_school(self):
        crest = f"/media/{self.crest}/site.png"
        for path in ("/staff-sign-in/", "/sign-in/"):
            with self.subTest(path=path):
                _, sunrise = self.page(None, SUNRISE, path)
                _, harbour = self.page(None, HARBOUR, path)

                self.assertIn("Sunrise Academy", sunrise)
                self.assertIn(f'<img src="{crest}"', sunrise)
                self.assertIn(f'<link rel="icon" href="{crest}"', sunrise)
                self.assertIn("Powered by Classnode", sunrise)

                self.assertIn("Harbour College", harbour)
                self.assertIn(">HC</span>", harbour)
                self.assertIn("Powered by Classnode", harbour)
                self.assertNothingOfSunrise(harbour)
                self.assertNotIn("Harbour College", sunrise)


class TheColourTests(TestCase):
    def test_a_colour_that_reads_on_white_is_used(self):
        self.assertEqual(brand.colour_for("#7a1f2b"), "#7A1F2B")

    def test_anything_else_is_the_navy(self):
        for chosen in (None, "", "#F5C518", "#FFFFFF", "red", "#7A1F2B;}body{display:none", "#12345", 7):
            with self.subTest(chosen=chosen):
                self.assertEqual(brand.colour_for(chosen), brand.NAVY)

    def test_the_meaning_colours_are_not_the_brand(self):
        """Only `--brand` is overridden; green, amber and red are design.css's at every school."""
        from django.template.loader import render_to_string

        html = render_to_string("design/brand_head.html", {"brand": brand.Brand("S", "S", None, "#7A1F2B")})
        self.assertIn("--brand:#7A1F2B", html)
        for token in ("--ok", "--warn", "--stop"):
            self.assertNotIn(token, html)
