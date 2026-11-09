"""Every sign-in link on a school's host stays on that host (the C2 follow-up).

`docs/sign-in-page.md`, "Links stay on the host". Two schools with real schemas, as
`test_school_door.py` has, because a link built from one setting is right at one school and
wrong at the other:

- the sign-in links on a school's pages and frames (`data-portal`, the website's header and
  footer, the signed-out pages, the 403) are that school's own host, never another school's
  and never the portal's;
- signing out on a school's host lands on that school's own door, whichever session it ends;
- a code or a notice a school sends names that school's host;
- the portal and Classnode's public site still link to the portal;
- every signed-out page wears the school's crest and name, never the Classnode wordmark;
- the parent door is the school's, and a guardian with children at both schools sees only the
  one school's children on each host.

CONTROL for each: building the link from `settings.PORTAL_HOST` / `portal_host()` again turns
the first group, the sign-out and the messages red.
"""

import re

from django.db import connection
from django.test import Client, override_settings

from accounts import guardian_contacts
from accounts.models import User
from accounts.services import enroll_student, link_guardian
from accounts.tests.test_school_door import (
    HANDSET,
    HARBOUR,
    PASSWORD,
    PORTAL,
    SUNRISE,
    SchoolDoorSetUp,
)
from messaging import kinds
from messaging.kinds import Kind
from schools.hosts import sign_in_host
from schools.tests.test_brand import give_crest, set_colour
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

#: Pages a school's host serves as frames with a "sign in" way back (they hold no data, so a
#: stranger gets them): each carries `data-portal`, which every module builds its link from.
FRAMES = ("/home/", "/marking/", "/fees/", "/timetable/", "/results/", "/check/", "/cards/")

HREF_HOST = re.compile(r'(?:href|action)="//([^/"]+)')
DATA_PORTAL = re.compile(r'data-portal="([^"]*)"')
WORDMARK = 'class="logo-word"'


class LinksStayOnTheHostTests(SchoolDoorSetUp):
    def get(self, host, path):
        response = self.client.get(path, HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def test_every_frame_builds_its_sign_in_link_from_the_schools_own_host(self):
        """What `static/*/states.js` read: `data-portal` is this school's host, never the other's."""
        seen = 0
        for host, other in ((SUNRISE, HARBOUR), (HARBOUR, SUNRISE)):
            for path in FRAMES:
                with self.subTest(host=host, path=path):
                    response = self.get(host, path)
                    if response.status_code != 200:
                        continue
                    html = response.content.decode()
                    for value in DATA_PORTAL.findall(html):
                        seen += 1
                        self.assertEqual(value, host)
                    self.assertNotIn(other, html)
                    self.assertNotIn(f"//{PORTAL}/", html)
        self.assertGreater(seen, 0, "no frame carried data-portal: the test saw nothing")

    def test_the_signed_out_home_page_links_to_this_schools_staff_door(self):
        for host, other in ((SUNRISE, HARBOUR), (HARBOUR, SUNRISE)):
            with self.subTest(host=host):
                html = self.get(host, "/home/").content.decode()
                self.assertIn("Please sign in", html)
                self.assertIn(f'<a href="//{host}/staff-sign-in/">Sign in</a>', html)
                self.assertNotIn(other, html)
                self.assertNotIn(f"//{PORTAL}/", html)

    def test_a_refusal_offers_this_schools_door_to_a_member_it_signed_out(self):
        """The 403's "Sign in with your password": this host, from the host the request is on."""
        from accounts.refusals import CodeSessionCannotEscalate
        from django.test import RequestFactory

        from accounts.views import refused

        for host in (SUNRISE, HARBOUR):
            with self.subTest(host=host):
                request = RequestFactory().get("/marking/", HTTP_HOST=host)
                with connected_to(self.sunrise if host == SUNRISE else self.harbour):
                    html = refused(request, CodeSessionCannotEscalate("x")).content.decode()
                self.assertIn(f'href="//{host}/staff-sign-in/"', html)

    def test_the_portal_still_links_to_the_portal(self):
        self.assertEqual(sign_in_host(), PORTAL)
        html = self.get(PORTAL, "/staff-sign-in/").content.decode()
        self.assertNotIn("Sunrise", html)
        self.assertNotIn("Harbour", html)
        self.assertNotIn(SUNRISE, html)
        self.assertNotIn(HARBOUR, html)
        self.assertIn('class="door-logo"', html)


class SigningOutStaysOnTheSchoolTests(SchoolDoorSetUp):
    def sign_out(self, host, client):
        token = client.get("/api/csrf/", HTTP_HOST=host).json()["csrf_token"]
        response = client.post("/sign-out/", {"csrfmiddlewaretoken": token}, HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def test_signing_out_of_either_school_returns_to_that_schools_own_door(self):
        for host in (SUNRISE, HARBOUR):
            with self.subTest(host=host):
                client, _ = self.door(host, "folake")
                response = self.sign_out(host, client)
                self.assertEqual(response["Location"], "/staff-sign-in/")
                self.assertNotIn("//", response["Location"])

    def test_a_portal_session_signing_out_on_a_schools_host_still_returns_there(self):
        """Signed in at the portal only, then "Sign out" on Sunrise's page: Sunrise's door, not
        `app.`: the browser stays where the installed app lives."""
        client, _ = self.door(PORTAL, "ada")
        response = self.sign_out(SUNRISE, client)
        self.assertEqual(response["Location"], "/staff-sign-in/")

    def test_signing_out_on_the_portal_returns_to_the_portals_door(self):
        client, _ = self.door(PORTAL, "ada")
        response = self.sign_out(PORTAL, client)
        self.assertIn(response["Location"], ("/staff-sign-in/", f"//{PORTAL}/staff-sign-in/"))
        self.assertNotIn("sunrise", response["Location"])


class MessagesNameTheSchoolsHostTests(SchoolDoorSetUp):
    def test_a_notice_built_inside_a_school_names_that_schools_host(self):
        for school, host, other in (
            (self.sunrise, SUNRISE, HARBOUR),
            (self.harbour, HARBOUR, SUNRISE),
        ):
            with self.subTest(host=host), connected_to(school):
                text = kinds.render(
                    Kind.RESULT_NOTICE, channel_type="email", school=school.name, child="Ada", term="First term"
                )
                self.assertIn(f"at {host}", text)
                self.assertNotIn(other, text)
                self.assertNotIn(PORTAL, text.replace(host, ""))

    @override_settings(PORTAL_HOST=PORTAL)
    def test_a_code_a_school_sent_names_that_schools_host_and_a_platform_one_the_portal(self):
        text = kinds.render(
            Kind.CHANNEL_CHECK, channel_type="phone", school="Sunrise Academy", code="123456",
            minutes=15, school_host=SUNRISE,
        )
        self.assertIn(f"Enter it at {SUNRISE}.", text)
        self.assertNotIn(HARBOUR, text)
        plain = kinds.render(
            Kind.CHANNEL_CHECK, channel_type="phone", school="", code="123456", minutes=15
        )
        self.assertIn(f"Enter it at {PORTAL}.", plain)

    def test_the_code_task_passes_the_requesting_schools_host(self):
        from schools.hosts import school_host

        self.assertEqual(school_host(self.sunrise), SUNRISE)
        self.assertEqual(school_host(self.harbour), HARBOUR)
        self.assertEqual(school_host(None), "")


class SignedOutPagesWearTheSchoolTests(SchoolDoorSetUp):
    """The installed app opens signed out first: no page may flash Classnode's wordmark."""

    def setUp(self):
        super().setUp()
        self.crest = give_crest(self.sunrise)
        set_colour(self.sunrise, "#1B5E20")

    def get(self, host, path):
        response = self.client.get(path, HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def test_the_please_sign_in_home_shows_the_schools_crest_and_name(self):
        sunrise = self.get(SUNRISE, "/home/").content.decode()
        harbour = self.get(HARBOUR, "/home/").content.decode()

        self.assertIn("Please sign in", sunrise)
        self.assertRegex(sunrise, r'class="logo-name">Sunrise Academy<')
        self.assertIn(f'<img src="/media/{self.crest}/site.png"', sunrise)
        self.assertNotIn(WORDMARK, sunrise)
        self.assertRegex(harbour, r'class="logo-name">Harbour College<')
        self.assertIn('<span class="crest" aria-hidden="true">HC</span>', harbour)
        self.assertNotIn(WORDMARK, harbour)
        self.assertNotIn("Sunrise Academy", harbour)

    def test_every_signed_out_page_has_the_crest_and_never_the_wordmark(self):
        for path in ("/home/", "/staff-sign-in/", "/sign-in/", "/check/", "/cards/", "/no-such-page/"):
            with self.subTest(path=path):
                response = self.get(SUNRISE, path)
                html = response.content.decode()
                self.assertIn("Sunrise Academy", html)
                self.assertNotIn(WORDMARK, html)
                self.assertNotIn("Harbour College", html)
                self.assertNotIn(">classnode<", html.replace("Powered by Classnode", ""))

    def test_the_error_page_wears_the_school_and_the_portals_does_not(self):
        sunrise = self.get(SUNRISE, "/no-such-page/")
        self.assertEqual(sunrise.status_code, 404)
        self.assertRegex(sunrise.content.decode(), r'class="brand">\s*<span class="crest"')
        self.assertIn("Sunrise Academy", sunrise.content.decode())
        portal = self.get(PORTAL, "/no-such-page/").content.decode()
        self.assertNotIn("Sunrise Academy", portal)
        self.assertIn("classnode", portal)

    def test_the_manifest_and_every_sign_in_link_stay_inside_the_installed_apps_scope(self):
        manifest = self.get(SUNRISE, "/site.webmanifest").json()
        self.assertEqual((manifest["start_url"], manifest["scope"]), ("/home/", "/"))
        # Every link a signed-out page offers is a path on this host (or `//` this host), so
        # it is inside the scope: following it never opens a browser tab on another origin.
        for path in ("/home/", "/staff-sign-in/", "/sign-in/", "/check/"):
            html = self.get(SUNRISE, path).content.decode()
            for host in HREF_HOST.findall(html):
                self.assertIn(host, {SUNRISE, "classnode.co"}, f"{path} links to {host}")


class ParentEntryPointsStayOnTheHostTests(SchoolDoorSetUp):
    """The parent door is the school's, every way into it stays there, and a guardian with
    children at two schools sees one school's on each host.

    Its own setup rather than a subclass of `test_school_door.TheParentDoorTests`: importing a
    test class into this module makes discovery load its tests a second time here, and the CI
    shard check (`scripts/shard_tests.py`) refuses a suite whose shards load more than it does.
    """

    def setUp(self):
        super().setUp()
        self.crest = give_crest(self.sunrise)
        self.mama = User.objects.create_user("mama", PASSWORD, full_name="Mama Both")
        self.kid_here = enroll_student(
            User.objects.create_user("SUN/1", PASSWORD, full_name="Sunny Child"), self.sunrise
        )
        self.kid_there = enroll_student(
            User.objects.create_user("HAR/1", PASSWORD, full_name="Harry Child"), self.harbour
        )
        link_guardian(self.mama, self.kid_here)
        link_guardian(self.mama, self.kid_there)
        self.contact = give_verified_channel(self.mama, HANDSET)

    def code_door(self, host, client):
        token = client.get("/api/csrf/", HTTP_HOST=host).json()["csrf_token"]
        _, raw = guardian_contacts.request_sign_in_code(self.contact)
        response = client.post(
            "/api/guardian/session/",
            data={"value": HANDSET, "code": raw},
            content_type="application/json",
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=token,
        )
        connection.set_schema_to_public()
        return response

    def page(self, host, path):
        response = self.client.get(path, HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def test_the_parent_door_wears_the_school_and_says_powered_by_classnode(self):
        html = self.page(SUNRISE, "/sign-in/").content.decode()
        self.assertRegex(html, r'class="logo-name">Sunrise Academy<')
        self.assertIn(f'<img src="/media/{self.crest}/site.png"', html)
        self.assertIn("Powered by Classnode", html)
        other = self.page(HARBOUR, "/sign-in/").content.decode()
        self.assertRegex(other, r'class="logo-name">Harbour College<')
        self.assertNotIn("Sunrise", other)

    def test_the_staff_door_offers_a_parent_link_on_the_same_host(self):
        """"I'm a parent" is a path (`/sign-in/`), so it cannot leave the host: checked in the
        module that draws it, which builds it with no host in it."""
        import pathlib

        source = pathlib.Path("static/staff-signin/states.js").read_text()
        self.assertIn("<a href=\"/sign-in/\">I\\'m a parent</a>", source)

    def test_the_result_checker_and_card_frames_sign_in_on_this_host(self):
        for host in (SUNRISE, HARBOUR):
            for path in ("/check/", "/cards/"):
                with self.subTest(host=host, path=path):
                    html = self.page(host, path).content.decode()
                    self.assertEqual(set(DATA_PORTAL.findall(html)), {host})

    def test_a_guardian_of_children_at_two_schools_sees_only_each_hosts_child(self):
        for host, name in ((SUNRISE, "Sunny Child"), (HARBOUR, "Harry Child")):
            with self.subTest(host=host):
                client = Client(enforce_csrf_checks=True)
                response = self.code_door(host, client)
                self.assertEqual(response.status_code, 200, response.content)
                cards = client.get("/api/results/cards/", HTTP_HOST=host)
                connection.set_schema_to_public()
                self.assertEqual([c["student_name"] for c in cards.json()["children"]], [name])
