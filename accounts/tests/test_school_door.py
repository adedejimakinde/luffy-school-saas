"""A school's own door: sign-in on `<school>.<domain>`, for that school's members alone.

`docs/sign-in-page.md`, "A school's own door". Two schools throughout, with
real schemas (the door reads the school's crest and colour from its own), for
the reason every tenancy test here gives: a rule that only one school can see
is a rule a single-school test passes whether or not it holds.

- **Who may sign in**: on Sunrise's host only an active member of Sunrise. A
  member of Harbour, a suspended member, platform staff with no membership,
  gets the same 401 and the same sentence as a wrong password, counted by the
  same throttle.
- **Where the session is good**: in a cookie of its own with no `Domain`, so a
  browser keeps it to Sunrise's host; and bound to Sunrise, so the server
  refuses it on Harbour's host and on the portal whatever cookie carries it.
- **What it reaches**: that school alone, and the page goes to that school's
  portal for this login (`home`).
- **The portal is unchanged**: Classnode's look, every school, one session for
  every host, as `test_login.py` and `test_cross_host_session.py` already hold.

Each of the four claims the issue names was broken by hand and seen to fail
(the pull request lists the controls); the docstrings name what turns red.
"""

from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.core import mail
from django.db import connection
from django.test import Client, TestCase, override_settings

from accounts import guardian_contacts, signin
from accounts.models import GuardianContactCode, MembershipStatus, Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from schools import invitations as invitation_service
from schools.models import Domain
from schools.paths import NEVER_INDEXED, first_segment
from schools.session_store import SIGNED_IN_AT
from schools.tests.test_brand import HARBOUR_COLOUR, SUNRISE_COLOUR, give_crest, set_colour
from schools.tests.tenants import make_school as make_school_with_schema
from schools.tests.test_invitations import make_school
from tests.guardians import give_verified_channel

PORTAL = "testserver"
SUNRISE = "sunrise.testserver"
HARBOUR = "harbour.testserver"
PASSWORD = "correct-horse-battery"
HANDSET = "08031234567"

SCHOOL_COOKIE = settings.SCHOOL_SESSION_COOKIE_NAME
PORTAL_COOKIE = settings.SESSION_COOKIE_NAME


class SchoolDoorSetUp(TestCase):
    def setUp(self):
        portal = make_school("Portal", "portal", "public")
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)
        self.sunrise = make_school_with_schema("Sunrise Academy", "sunrise", "sunrise")
        Domain.objects.create(tenant=self.sunrise, domain=SUNRISE, is_primary=True)
        self.harbour = make_school_with_schema("Harbour College", "harbour", "harbour")
        Domain.objects.create(tenant=self.harbour, domain=HARBOUR, is_primary=True)

        self.ada = User.objects.create_user("ada", PASSWORD, full_name="Ada Sunrise")
        grant_membership(self.ada, self.sunrise, Role.TEACHER)
        self.tunde = User.objects.create_user("tunde", PASSWORD, full_name="Tunde Harbour")
        grant_membership(self.tunde, self.harbour, Role.TEACHER)
        # Teaches at both: the person a session good everywhere would let
        # through on the wrong host, because both hosts would admit her.
        self.folake = User.objects.create_user("folake", PASSWORD, full_name="Folake Both")
        grant_membership(self.folake, self.sunrise, Role.TEACHER)
        grant_membership(self.folake, self.harbour, Role.TEACHER)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def door(self, host, identifier, password=PASSWORD, client=None):
        """A real browser's sign-in: a token from `/api/csrf/`, then the POST, CSRF enforced."""
        client = client or Client(enforce_csrf_checks=True)
        token = client.get("/api/csrf/", HTTP_HOST=host).json()["csrf_token"]
        response = client.post(
            "/api/login/",
            data={"identifier": identifier, "password": password},
            content_type="application/json",
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=token,
        )
        connection.set_schema_to_public()
        return client, response

    def home_api(self, client, host):
        """An authenticated route every member is answered by on `host`: 200 for a
        signed-in member (her children there, none for a teacher), 401 for nobody."""
        response = client.get("/api/results/cards/", HTTP_HOST=host)
        connection.set_schema_to_public()
        return response


class OnlyItsOwnMembersSignInTests(SchoolDoorSetUp):
    def test_a_member_signs_in_at_her_own_schools_door(self):
        _, response = self.door(SUNRISE, "ada")

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual([s["slug"] for s in body["schools"]], ["sunrise"])
        self.assertTrue(body["schools"][0]["path_only"])
        self.assertEqual(body["home"], "/home/")

    def test_a_member_of_another_school_is_told_exactly_what_a_wrong_password_is(self):
        """Tunde's password is right, and he is Harbour's. On Sunrise's door the
        answer is byte for byte the wrong-password answer, and no session is made.

        CONTROL: dropping `not belongs_at(user, school)` from
        `accounts.signin.sign_in()` turns this 401 into a 200.
        """
        _, refused = self.door(SUNRISE, "tunde")
        _, wrong = self.door(SUNRISE, "ada", password="not-the-password")

        self.assertEqual(refused.status_code, 401)
        self.assertEqual(refused.json(), wrong.json())
        self.assertEqual(refused.json()["detail"], signin.REFUSED)
        self.assertNotIn(SCHOOL_COOKIE, refused.cookies)
        self.assertNotIn(PORTAL_COOKIE, refused.cookies)

    def test_the_same_login_signs_in_at_its_own_schools_door(self):
        """The control for the refusal above: it is Sunrise's door, not Tunde."""
        _, response = self.door(HARBOUR, "tunde")
        self.assertEqual(response.status_code, 200)

    def test_a_suspended_or_invited_member_is_refused_too(self):
        for status in (MembershipStatus.SUSPENDED, MembershipStatus.INVITED):
            with self.subTest(status=status):
                self.ada.memberships.filter(school=self.sunrise).update(status=status)
                _, response = self.door(SUNRISE, "ada")
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], signin.REFUSED)

    def test_platform_staff_with_no_membership_use_the_portal(self):
        ops = User.objects.create_user("ops", PASSWORD, full_name="Ops", is_platform_staff=True)

        _, at_sunrise = self.door(SUNRISE, "ops")
        _, at_portal = self.door(PORTAL, "ops")

        self.assertEqual(at_sunrise.status_code, 401)
        self.assertEqual(at_portal.status_code, 200)
        self.assertTrue(at_portal.json()["is_platform_staff"])
        self.assertTrue(ops.is_platform_staff)

    def test_a_portal_session_of_somebody_else_still_reaches_the_door(self):
        """Signed in on the portal as Tunde (Harbour's), Sunrise's door and its
        API answer: a door is for somebody not signed in here yet. Tunde's
        session itself still opens nothing at Sunrise."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.tunde)

        self.assertEqual(client.get("/staff-sign-in/", HTTP_HOST=SUNRISE).status_code, 200)
        _, response = self.door(SUNRISE, "ada", client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.home_api(client, SUNRISE).status_code, 200)

        other = Client()
        other.force_login(self.tunde)
        self.assertEqual(other.get("/home/", HTTP_HOST=SUNRISE).status_code, 403)


class TheThrottleIsThePortalsTests(SchoolDoorSetUp):
    @override_settings(SIGN_IN_MAX_FAILURES_PER_IDENTIFIER=3)
    def test_failures_at_a_schools_door_close_the_window_there_and_on_the_portal(self):
        """One bucket per identifier, whichever door the guesses arrive at:
        closed on Sunrise's door, it is closed on the portal's too."""
        for _ in range(3):
            _, response = self.door(SUNRISE, "ada", password="wrong")
            self.assertEqual(response.status_code, 401)

        _, here = self.door(SUNRISE, "ada")
        _, portal = self.door(PORTAL, "ada")

        self.assertEqual(here.status_code, 429)
        self.assertEqual(here.json()["code"], signin.TOO_MANY_ATTEMPTS)
        self.assertIn("Retry-After", here)
        self.assertEqual(portal.status_code, 429)

    @override_settings(SIGN_IN_MAX_FAILURES_PER_IDENTIFIER=3)
    def test_a_right_password_from_another_school_is_counted_as_a_failure(self):
        """Uncounted, the throttle would tell a right password from a wrong one."""
        for _ in range(3):
            self.door(SUNRISE, "tunde")

        _, response = self.door(HARBOUR, "tunde")
        self.assertEqual(response.status_code, 429)

    def test_an_unverified_post_is_refused_as_on_the_portal(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/login/",
            data={"identifier": "ada", "password": PASSWORD},
            content_type="application/json",
            HTTP_HOST=SUNRISE,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")


class ASessionIsGoodOnItsOwnHostAloneTests(SchoolDoorSetUp):
    @override_settings(SESSION_COOKIE_DOMAIN=".testserver")
    def test_the_cookie_is_the_schools_own_and_names_no_domain(self):
        """A cookie with no `Domain` attribute goes back to the host that set it
        and no other (RFC 6265 §5.3 step 6): never to Harbour's host, never to
        the portal. The portal's own cookie is not touched. Run with the
        platform's cookie domain set, as production is, so a school's cookie
        that took it would show here.

        CONTROL: giving the school's kind `SESSION_COOKIE_DOMAIN` in
        `schools.sessions.cookie_of()` turns this red.
        """
        _, response = self.door(SUNRISE, "folake")

        cookie = response.cookies[SCHOOL_COOKIE]
        self.assertEqual(cookie["domain"], "")
        self.assertEqual(cookie["path"], "/")
        self.assertTrue(cookie["httponly"])
        self.assertNotIn(PORTAL_COOKIE, response.cookies)

    @override_settings(SESSION_COOKIE_DOMAIN=".testserver")
    def test_the_portals_cookie_still_spans_every_host(self):
        """The control: the portal's door is as it was."""
        _, response = self.door(PORTAL, "folake")

        self.assertEqual(response.cookies[PORTAL_COOKIE]["domain"], ".testserver")
        self.assertNotIn(SCHOOL_COOKIE, response.cookies)

    def test_a_session_from_sunrises_host_is_refused_on_harbours(self):
        """Folake is a member of both, so Harbour's membership check would let
        her through: only the session's binding to Sunrise refuses it. The test
        client keeps one jar for every host, which is what a copied cookie is.

        CONTROL: `schools.session_store.belongs_here()` returning True turns
        Harbour's 401 into a 200.
        """
        client, _ = self.door(SUNRISE, "folake")

        self.assertEqual(self.home_api(client, SUNRISE).status_code, 200)
        refused = self.home_api(client, HARBOUR)
        self.assertEqual(refused.status_code, 401)
        self.assertEqual(refused.json()["code"], "session_expired")
        self.assertEqual(self.home_api(client, PORTAL).status_code, 401)

    def test_whatever_cookie_carries_it(self):
        """Sunrise's session key, put in the portal's cookie by hand, is still
        Sunrise's: refused on Harbour's host and on the portal."""
        client, response = self.door(SUNRISE, "folake")
        key = response.cookies[SCHOOL_COOKIE].value

        for host in (HARBOUR, PORTAL):
            with self.subTest(host=host):
                forged = Client()
                forged.cookies[PORTAL_COOKIE] = key
                self.assertEqual(self.home_api(forged, host).status_code, 401)
        # ...and the session itself is left alone for Sunrise.
        self.assertEqual(self.home_api(client, SUNRISE).status_code, 200)

    def test_a_portal_session_in_a_schools_cookie_is_refused(self):
        """The school's cookie only ever carries a session signed in there."""
        portal, _ = self.door(PORTAL, "folake")
        key = portal.cookies[PORTAL_COOKIE].value

        forged = Client()
        forged.cookies[SCHOOL_COOKIE] = key
        self.assertEqual(self.home_api(forged, SUNRISE).status_code, 401)
        # The control: in its own cookie it reaches Sunrise, as it always has.
        self.assertEqual(self.home_api(portal, SUNRISE).status_code, 200)

    def test_the_session_says_where_it_was_signed_in(self):
        _, response = self.door(SUNRISE, "folake")

        from django.contrib.sessions.backends.db import SessionStore

        data = SessionStore(response.cookies[SCHOOL_COOKIE].value).load()
        self.assertEqual(data[SIGNED_IN_AT], self.sunrise.pk)
        self.assertEqual(str(data[SESSION_KEY]), str(self.folake.pk))

    def test_a_portal_session_beside_it_is_put_aside_not_replaced(self):
        """A browser signed in on the portal as Tunde, then at Sunrise's door as
        Ada, has both: Ada at Sunrise, Tunde still on the portal."""
        client, _ = self.door(PORTAL, "tunde")
        tunde_key = client.cookies[PORTAL_COOKIE].value

        self.door(SUNRISE, "ada", client=client)

        self.assertEqual(client.cookies[PORTAL_COOKIE].value, tunde_key)
        response = client.get("/api/csrf/", HTTP_HOST=PORTAL)
        self.assertEqual(response.wsgi_request.user, self.tunde)
        response = client.get("/api/csrf/", HTTP_HOST=SUNRISE)
        self.assertEqual(response.wsgi_request.user, self.ada)
        connection.set_schema_to_public()

    def test_a_lapsed_school_session_falls_back_to_the_portals(self):
        """A school's cookie that names nothing any more does not shadow a good
        portal session, and is cleared on the way out."""
        client, _ = self.door(PORTAL, "ada")
        client.cookies[SCHOOL_COOKIE] = "lapsed-key"

        response = self.home_api(client, SUNRISE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies[SCHOOL_COOKIE].value, "")


class AMemberOfBothSchoolsTests(SchoolDoorSetUp):
    def test_she_signs_in_on_each_host_and_each_answer_is_that_school(self):
        at_sunrise, sunrise = self.door(SUNRISE, "folake")
        at_harbour, harbour = self.door(HARBOUR, "folake")

        self.assertEqual([s["slug"] for s in sunrise.json()["schools"]], ["sunrise"])
        self.assertEqual([s["slug"] for s in harbour.json()["schools"]], ["harbour"])
        self.assertEqual(self.home_api(at_sunrise, SUNRISE).status_code, 200)
        self.assertEqual(self.home_api(at_harbour, HARBOUR).status_code, 200)
        self.assertEqual(self.home_api(at_sunrise, HARBOUR).status_code, 401)
        self.assertEqual(self.home_api(at_harbour, SUNRISE).status_code, 401)

    def test_each_hosts_pages_show_that_school_alone(self):
        at_sunrise, _ = self.door(SUNRISE, "folake")

        page = at_sunrise.get("/home/", HTTP_HOST=SUNRISE).content.decode()
        connection.set_schema_to_public()
        self.assertIn("Sunrise Academy", page)
        self.assertNotIn("Harbour College", page)

    def test_the_portal_still_names_both(self):
        """The control: the portal's door is unchanged for her."""
        _, response = self.door(PORTAL, "folake")

        self.assertEqual(
            sorted(s["slug"] for s in response.json()["schools"]), ["harbour", "sunrise"]
        )
        self.assertTrue(all(not s["path_only"] for s in response.json()["schools"]))
        self.assertIsNone(response.json()["home"])


class WhereTheDoorLandsTests(SchoolDoorSetUp):
    def test_staff_land_on_the_dashboard_and_families_on_the_cards(self):
        mama = User.objects.create_user("mama", PASSWORD, full_name="Mama")
        child = enroll_student(User.objects.create_user("STU/1", PASSWORD, full_name="Kid"), self.sunrise)
        link_guardian(mama, child)
        give_verified_channel(mama, HANDSET)

        _, staff = self.door(SUNRISE, "ada")
        _, family = self.door(SUNRISE, "mama")

        self.assertEqual(staff.json()["home"], "/home/")
        self.assertEqual(family.json()["home"], "/cards/")

    def test_an_administrator_whose_school_is_not_set_up_starts_here(self):
        admin = User.objects.create_user("admin", PASSWORD, full_name="Admin")
        grant_membership(admin, self.sunrise, Role.ADMIN)

        _, response = self.door(SUNRISE, "admin")
        self.assertEqual(response.json()["home"], "/start/")


class SigningOutTests(SchoolDoorSetUp):
    def test_sign_out_at_a_school_lands_on_its_own_door_and_ends_the_portals_session_too(self):
        client, _ = self.door(PORTAL, "ada")
        portal_key = client.cookies[PORTAL_COOKIE].value
        self.door(SUNRISE, "ada", client=client)
        token = client.get("/api/csrf/", HTTP_HOST=SUNRISE).json()["csrf_token"]

        response = client.post("/sign-out/", {"csrfmiddlewaretoken": token}, HTTP_HOST=SUNRISE)
        connection.set_schema_to_public()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/staff-sign-in/")
        self.assertEqual(response.cookies[SCHOOL_COOKIE].value, "")
        self.assertEqual(response.cookies[PORTAL_COOKIE].value, "")
        from django.contrib.sessions.models import Session

        self.assertFalse(Session.objects.filter(session_key=portal_key).exists())
        self.assertEqual(self.home_api(client, SUNRISE).status_code, 401)


class TheParentDoorTests(SchoolDoorSetUp):
    def setUp(self):
        super().setUp()
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

    def test_a_parent_at_both_signs_in_at_one_and_sees_that_schools_child_alone(self):
        client = Client(enforce_csrf_checks=True)
        response = self.code_door(SUNRISE, client)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([s["slug"] for s in response.json()["schools"]], ["sunrise"])
        self.assertEqual(response.json()["home"], "/cards/")

        cards = client.get("/api/results/cards/", HTTP_HOST=SUNRISE)
        connection.set_schema_to_public()
        names = [child["student_name"] for child in cards.json()["children"]]
        self.assertEqual(names, ["Sunny Child"])
        # ...and the session opens nothing at Harbour, where her other child is.
        there = client.get("/api/results/cards/", HTTP_HOST=HARBOUR)
        connection.set_schema_to_public()
        self.assertEqual(there.status_code, 401)

    def test_a_guardian_with_no_child_at_this_school_is_sent_nothing_and_refused(self):
        """A number nobody holds, as far as Sunrise's door is concerned.

        CONTROL: `_at()` returning every contact turns the refusal into a 200.
        """
        self.mama.memberships.filter(school=self.sunrise).update(status=MembershipStatus.ENDED)
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/csrf/", HTTP_HOST=SUNRISE).json()["csrf_token"]
        codes = GuardianContactCode.objects.count()

        asked = client.post(
            "/api/guardian/code/", data={"value": HANDSET}, content_type="application/json",
            HTTP_HOST=SUNRISE, HTTP_X_CSRFTOKEN=token,
        )
        connection.set_schema_to_public()
        self.assertEqual(asked.status_code, 200)
        self.assertEqual(GuardianContactCode.objects.count(), codes)

        answered = self.code_door(SUNRISE, client)
        self.assertEqual(answered.status_code, 401)
        self.assertEqual(answered.json()["detail"], guardian_contacts_refused())
        self.assertEqual(self.code_door(HARBOUR, Client(enforce_csrf_checks=True)).status_code, 200)

    def test_a_shared_handset_offers_only_this_schools_guardian(self):
        """Mama and Papa share one phone; Papa's child is at Harbour alone. At
        Sunrise's door there is nobody to choose between: Mama is signed in
        straight away, and Papa is never named."""
        papa = User.objects.create_user("papa", PASSWORD, full_name="Papa Harbour")
        link_guardian(papa, enroll_student(
            User.objects.create_user("HAR/2", PASSWORD, full_name="Hal Child"), self.harbour
        ))
        give_verified_channel(papa, HANDSET)

        at_sunrise = self.code_door(SUNRISE, Client(enforce_csrf_checks=True))
        at_portal = self.code_door(PORTAL, Client(enforce_csrf_checks=True))

        self.assertEqual(at_sunrise.status_code, 200, at_sunrise.content)
        self.assertEqual(at_sunrise.json()["full_name"], "Mama Both")
        self.assertNotIn("Papa", at_sunrise.content.decode())
        # The control: the portal's door does have two people to choose between.
        self.assertEqual(at_portal.status_code, 202)

    def test_the_code_door_failures_count_against_the_same_channel(self):
        with override_settings(SIGN_IN_MAX_FAILURES_PER_CHANNEL=2):
            client = Client(enforce_csrf_checks=True)
            token = client.get("/api/csrf/", HTTP_HOST=SUNRISE).json()["csrf_token"]
            for _ in range(2):
                client.post(
                    "/api/guardian/session/", data={"value": HANDSET, "code": "000000"},
                    content_type="application/json", HTTP_HOST=SUNRISE, HTTP_X_CSRFTOKEN=token,
                )
            connection.set_schema_to_public()
            self.assertEqual(self.code_door(PORTAL, Client(enforce_csrf_checks=True)).status_code, 429)


def guardian_contacts_refused():
    from accounts.guardian_signin import REFUSED

    return REFUSED


@override_settings(INVITATION_ACCEPT_URL="https://{host}/invitations/{token}/")
class InvitationsGoToTheSchoolsHostTests(SchoolDoorSetUp):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user("principal", PASSWORD, full_name="P", email="p@sunrise.ng")
        grant_membership(self.admin, self.sunrise, Role.ADMIN)

    def test_the_link_is_on_the_schools_own_host(self):
        self.assertEqual(
            invitation_service.configured_accept_url("tok", self.sunrise),
            f"https://{SUNRISE}/invitations/tok/",
        )

    @override_settings(PORTAL_HOST=PORTAL)
    def test_a_school_with_no_address_yet_gets_the_portals(self):
        Domain.objects.filter(tenant=self.sunrise).update(is_primary=False)
        self.assertEqual(
            invitation_service.configured_accept_url("tok", self.sunrise),
            f"https://{PORTAL}/invitations/tok/",
        )

    def invite(self):
        """The link an operator hands over, and the token in it."""
        _, link = invitation_service.invite_staff_by_hand(
            self.admin, self.sunrise, Role.TEACHER, email="new@sunrise.ng", full_name="New"
        )
        self.assertTrue(link.startswith(f"https://{SUNRISE}/invitations/"), link)
        return link.rstrip("/").rsplit("/", 1)[1]

    def test_an_invitation_opens_on_its_own_schools_host_and_not_anothers(self):
        raw = self.invite()

        here = self.client.get(f"/api/invitations/{raw}/", HTTP_HOST=SUNRISE)
        there = self.client.get(f"/api/invitations/{raw}/", HTTP_HOST=HARBOUR)
        portal = self.client.get(f"/api/invitations/{raw}/", HTTP_HOST=PORTAL)
        connection.set_schema_to_public()

        self.assertEqual(here.status_code, 200)
        self.assertEqual(here.json()["school"], "Sunrise Academy")
        self.assertEqual(there.status_code, 404)
        self.assertEqual(portal.status_code, 200, "links already sent to the portal still open")

    def test_an_invitee_signed_in_elsewhere_still_reaches_the_page(self):
        raw = self.invite()
        self.client.force_login(self.tunde)

        page = self.client.get(f"/invitations/{raw}/", HTTP_HOST=SUNRISE)
        api = self.client.get(f"/api/invitations/{raw}/", HTTP_HOST=SUNRISE)
        connection.set_schema_to_public()

        self.assertEqual(page.status_code, 200)
        self.assertEqual(api.status_code, 200)
        self.assertFalse(mail.outbox)


class TheDoorWearsTheSchoolTests(SchoolDoorSetUp):
    def setUp(self):
        super().setUp()
        self.crest = give_crest(self.sunrise)
        set_colour(self.sunrise, SUNRISE_COLOUR)
        set_colour(self.harbour, HARBOUR_COLOUR)

    def page(self, host, path):
        response = self.client.get(path, HTTP_HOST=host)
        connection.set_schema_to_public()
        self.assertEqual(response.status_code, 200)
        return response

    def test_each_door_shows_its_own_crest_name_and_colour_and_powered_by(self):
        crest = f"/media/{self.crest}/site.png"
        for path in ("/staff-sign-in/", "/sign-in/"):
            with self.subTest(path=path):
                sunrise = self.page(SUNRISE, path).content.decode()
                harbour = self.page(HARBOUR, path).content.decode()

                self.assertRegex(sunrise, r'class="(door|logo)-name">Sunrise Academy<')
                self.assertIn(f'<img src="{crest}"', sunrise)
                self.assertIn(f"--brand:{SUNRISE_COLOUR}", sunrise)
                self.assertIn("Powered by Classnode", sunrise)
                self.assertNotIn("Harbour College", sunrise)

                # No crest: the initials. A colour under 4.5:1: the navy.
                self.assertRegex(harbour, r'class="(door|logo)-name">Harbour College<')
                self.assertIn('<span class="crest" aria-hidden="true">HC</span>', harbour)
                self.assertNotIn("--brand:", harbour)
                self.assertNotIn(HARBOUR_COLOUR, harbour)
                self.assertIn("Powered by Classnode", harbour)
                self.assertNotIn("Sunrise Academy", harbour)
                self.assertNotIn(self.crest, harbour)

    def test_the_portals_door_is_classnodes(self):
        for path in ("/staff-sign-in/", "/sign-in/"):
            with self.subTest(path=path):
                html = self.page(PORTAL, path).content.decode()
                self.assertNotIn("Powered by Classnode", html)
                self.assertNotIn("Sunrise Academy", html)
                self.assertNotIn("Harbour College", html)

    def test_the_door_is_never_indexed(self):
        """Every door's first segment is classified as the portal's, never the
        website's, and its response says so to a crawler."""
        for path in ("/staff-sign-in/", "/sign-in/", "/invitations/x/"):
            with self.subTest(path=path):
                self.assertIn(first_segment(path), NEVER_INDEXED)
        response = self.page(SUNRISE, "/staff-sign-in/")
        self.assertIn("noindex", response["X-Robots-Tag"])
        robots = self.page(SUNRISE, "/robots.txt").content.decode()
        for name in ("/staff-sign-in/", "/sign-in/", "/invitations/"):
            self.assertIn(f"Disallow: {name}", robots)


class ReadyForThePrincipalTests(SchoolDoorSetUp):
    def test_the_preview_signs_a_principal_in_at_the_schools_own_door(self):
        """The email's link is the school's preview (`schoolsite.notify`); signed
        out, it sends her to this host's door and back."""
        from schoolsite.notify import preview_url

        self.assertEqual(preview_url(self.sunrise), f"https://{SUNRISE}/website/preview/")
        response = self.client.get("/website/preview/", HTTP_HOST=SUNRISE)
        connection.set_schema_to_public()

        self.assertEqual(response.status_code, 302)
        back = quote(f"http://{SUNRISE}/website/preview/", safe="")
        self.assertEqual(response["Location"], f"/staff-sign-in/?next={back}")
