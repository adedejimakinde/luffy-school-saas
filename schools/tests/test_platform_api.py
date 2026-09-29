"""The platform admin screen: `GET`/`POST /api/platform/schools/` and `/platform/`.

Two schools throughout (St Mary's and Grace Academy, with different numbers of
children), because what the list must not do is add one school's children to
another's row, and what the screen must not do is open to a school's own staff:
a principal and an administrator at either school are refused, and refused
before anything is read or written.

Making a school is `create_school()` itself, run for real (a real schema, a real
migration), so those tests are few.
"""

from django.test import override_settings
from django.db import connection

from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import enroll_student, grant_membership
from results.tests.fixtures import HOST, PASSWORD, PORTAL, THEIR_HOST, ChainSetUp
from schools.models import Domain, Invitation, School
from schools.tests.test_invitations import RecordingChannel

URL = "/api/platform/schools/"

PLATFORM = dict(
    PLATFORM_DOMAIN="testserver",
    PORTAL_HOST="testserver",
    INVITATION_CHANNEL="schools.tests.test_invitations.RecordingChannel",
    INVITATION_ACCEPT_URL="https://testserver/invitations/{token}/",
)


@override_settings(**PLATFORM)
class PlatformSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        RecordingChannel.sent = []
        self.operator = User.objects.create_superuser("ops", PASSWORD, full_name="Ops")
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )
        self.their_admin = grant_membership(
            User.objects.create_user("gina", PASSWORD, full_name="Gina Admin"), self.grace, Role.ADMIN
        )
        # Grace has three (one from the fixture), St Mary's has five: the counts must not mix.
        for handle in ("gk1", "gk2"):
            enroll_student(User.objects.create_user(handle, PASSWORD, full_name=handle), self.grace)

    def get(self, user=None, host=PORTAL):
        if user is not None:
            self.client.force_login(user)
        return self.client.get(URL, HTTP_HOST=host)

    def post(self, body, user=None, host=PORTAL):
        self.client.force_login(user or self.operator)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(URL, data=body, content_type="application/json", HTTP_HOST=host)

    def new_school(self, **kw):
        body = {
            "name": "Hope Academy",
            "subdomain": "hope",
            "admin_name": "Hope Head",
            "admin_email": "head@hope.example",
        }
        body.update(kw)
        return body

    def customers(self):
        return set(School.objects.exclude(schema_name="public").values_list("slug", flat=True))


class TheListTests(PlatformSetUp):
    def test_every_school_is_listed_with_its_own_student_count(self):
        rows = {r["subdomain"]: r for r in self.get(self.operator).json()["schools"]}

        self.assertEqual(set(rows), {self.stmarys.slug, self.grace.slug})
        self.assertEqual(rows[self.stmarys.slug]["students"], 5)
        self.assertEqual(rows[self.grace.slug]["students"], 3)
        self.assertEqual(rows[self.stmarys.slug]["host"], HOST)
        self.assertEqual(rows[self.grace.slug]["host"], THEIR_HOST)
        self.assertNotIn("portal", rows)

    def test_a_child_who_has_left_is_not_counted(self):
        self.children["ada"].end()

        rows = {r["subdomain"]: r for r in self.get(self.operator).json()["schools"]}

        self.assertEqual(rows[self.stmarys.slug]["students"], 4)
        self.assertEqual(rows[self.grace.slug]["students"], 3)

    def test_a_new_child_at_one_school_moves_only_that_schools_count(self):
        enroll_student(User.objects.create_user("gk3", PASSWORD, full_name="G3"), self.grace)

        rows = {r["subdomain"]: r for r in self.get(self.operator).json()["schools"]}

        self.assertEqual((rows[self.stmarys.slug]["students"], rows[self.grace.slug]["students"]), (5, 4))

    def test_staff_and_parents_are_not_counted_as_students(self):
        rows = {r["subdomain"]: r for r in self.get(self.operator).json()["schools"]}

        self.assertEqual(rows[self.stmarys.slug]["students"], 5)  # a teacher, head, vp and admin are not children

    def test_it_is_a_constant_number_of_queries_however_many_schools(self):
        from django.db import connection as conn
        from django.test.utils import CaptureQueriesContext

        self.get(self.operator)  # warm
        with CaptureQueriesContext(conn) as queries:
            self.get(self.operator)
        counting = [q for q in queries.captured_queries if "COUNT(" in q["sql"]]
        self.assertEqual(len(counting), 1, "one grouped count for every school, not one per school")


class OnlyPlatformStaffTests(PlatformSetUp):
    def test_school_staff_cannot_reach_the_list_at_either_school(self):
        for member in (self.head, self.admin, self.teacher, self.their_head, self.their_admin):
            with self.subTest(member=member):
                self.assertEqual(self.get(member.user).status_code, 403)

    def test_school_staff_cannot_make_a_school(self):
        before = self.customers()

        for member in (self.head, self.admin, self.their_admin):
            with self.subTest(member=member):
                response = self.post(self.new_school(), user=member.user)
                self.assertEqual(response.status_code, 403)

        self.assertEqual(self.customers(), before)
        self.assertFalse(Invitation.objects.filter(sent_to="head@hope.example").exists())
        self.assertEqual(RecordingChannel.sent, [])

    def test_a_platform_account_that_is_only_a_superuser_flag_is_not_enough(self):
        someone = User.objects.create_user("su", PASSWORD, full_name="Su")
        User.objects.filter(pk=someone.pk).update(is_superuser=True)
        someone.refresh_from_db()

        self.assertEqual(self.get(someone).status_code, 403)

    def test_nobody_signed_in_is_told_to_sign_in(self):
        self.client.logout()

        self.assertEqual(self.client.get(URL, HTTP_HOST=PORTAL).status_code, 401)
        self.assertEqual(self.client.post(URL, data={}, content_type="application/json", HTTP_HOST=PORTAL).status_code, 401)

    def test_a_school_host_has_no_such_route_even_for_platform_staff(self):
        self.assertEqual(self.get(self.operator, host=HOST).status_code, 404)
        before = self.customers()
        self.assertEqual(self.post(self.new_school(), host=THEIR_HOST).status_code, 404)
        self.assertEqual(self.customers(), before)

    def test_the_page_is_on_the_portal_and_not_on_a_school(self):
        self.client.logout()

        self.assertEqual(self.client.get("/platform/", HTTP_HOST=PORTAL).status_code, 200)
        self.assertEqual(self.client.get("/platform/", HTTP_HOST=HOST).status_code, 404)
        self.assertEqual(self.client.get("/platform/", HTTP_HOST=THEIR_HOST).status_code, 404)


class MakingASchoolTests(PlatformSetUp):
    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def test_a_school_is_made_by_create_school_and_its_administrator_is_emailed(self):
        response = self.post(self.new_school())

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["school"]["subdomain"], "hope")
        self.assertEqual(body["school"]["host"], "hope.testserver")
        self.assertEqual(body["school"]["students"], 0)
        self.assertTrue(body["emailed"])
        self.assertIsNone(body["link_to_hand_over"])
        self.assertEqual(body["invited"], "head@hope.example")
        school = School.objects.get(slug="hope")
        self.assertTrue(Domain.objects.filter(tenant=school, domain="hope.testserver").exists())
        invitation = Invitation.objects.get(membership__school=school)
        self.assertEqual(invitation.membership.role, Role.ADMIN)
        self.assertEqual(invitation.membership.status, MembershipStatus.INVITED)
        self.assertEqual(len(RecordingChannel.sent), 1)
        self.assertEqual(RecordingChannel.sent[0]["invitation"].pk, invitation.pk)

    def test_the_new_school_appears_in_the_list_and_the_others_are_unchanged(self):
        self.post(self.new_school())

        rows = {r["subdomain"]: r for r in self.get(self.operator).json()["schools"]}

        self.assertEqual(set(rows), {"st-marys", "grace", "hope"})
        self.assertEqual(rows["hope"]["students"], 0)
        self.assertEqual((rows["st-marys"]["students"], rows["grace"]["students"]), (5, 3))

    def test_an_administrator_known_only_by_phone_is_handed_a_link_instead(self):
        response = self.post(self.new_school(admin_email="", admin_phone="0803 555 0100"))

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertFalse(body["emailed"])
        self.assertIn("/invitations/", body["link_to_hand_over"])
        self.assertIn("+234", body["invited"])
        self.assertEqual(RecordingChannel.sent, [])
        invitation = Invitation.objects.get(membership__school__slug="hope")
        self.assertEqual(invitation.membership.role, Role.ADMIN)

    def test_an_administrator_known_only_by_phone_is_texted_when_there_is_a_phone_provider(self):
        from messaging.models import FakeMessage

        with override_settings(MESSAGING_PROVIDERS={"phone": "messaging.fake.FakeProvider"}):
            response = self.post(self.new_school(admin_email="", admin_phone="0803 555 0100"))

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["texted"])
        self.assertFalse(body["emailed"])
        self.assertIsNone(body["link_to_hand_over"])
        self.assertIn("/invitations/", FakeMessage.objects.get().text)

    def test_a_reserved_or_taken_subdomain_is_refused_and_nothing_is_written(self):
        before = self.customers()

        for subdomain in ("app", "st-marys", "Bad Name", "a.b"):
            with self.subTest(subdomain=subdomain):
                response = self.post(self.new_school(subdomain=subdomain))
                self.assertEqual(response.status_code, 422)
                self.assertTrue(response.json()["detail"])

        self.assertEqual(self.customers(), before)
        self.assertEqual(RecordingChannel.sent, [])

    def test_an_administrator_with_no_email_or_phone_is_refused_and_nothing_is_written(self):
        before = self.customers()
        memberships = Membership.objects.count()

        response = self.post(self.new_school(admin_email="", admin_phone=""))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.customers(), before)
        self.assertEqual(Membership.objects.count(), memberships)

    def test_a_phone_number_that_is_not_one_makes_no_school(self):
        before = self.customers()

        response = self.post(self.new_school(admin_email="", admin_phone="12"))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.customers(), before)

    def test_a_school_needs_a_name(self):
        response = self.post(self.new_school(name="  "))

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("hope", self.customers())
