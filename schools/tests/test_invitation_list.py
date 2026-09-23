"""The staff screen's list of invitations: this school's, and only what it typed.

`Invitation` lives in the public schema beside `Membership`, so what keeps one
school's list out of another's is a `membership__school=` filter doing real
work. And the "who" on each row is the address the office typed
(`Invitation.sent_to`), never the account it resolved to — that account may be
another school's teacher, with a name and a second identifier this school has
no business reading (`api.InvitationOut`).
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain, Invitation, InvitationStatus, School
from schools.tests.test_invitations import RecordingChannel, make_school

PASSWORD = "correct-horse-battery"
MAY_NOT_INVITE = "invited by an administrator"


@override_settings(
    INVITATION_CHANNEL="schools.tests.test_invitations.RecordingChannel",
    INVITATION_ACCEPT_URL="https://portal.example.school/invitations/{token}/",
)
class InvitationListTests(TestCase):
    def setUp(self):
        RecordingChannel.sent = []
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.admin = self.person("admin@st-marys.school", "Ada Admin", self.stmarys, Role.ADMIN)
        self.their_admin = self.person("admin@grace.school", "Gbenga Admin", self.grace, Role.ADMIN)
        self.principal = self.person("head@st-marys.school", "Hauwa Head", self.stmarys, Role.PRINCIPAL)

    def person(self, email, name, school, role):
        user = User.objects.create_user(email, PASSWORD, full_name=name, email=email)
        grant_membership(user, school, role)
        return user

    def invite(self, admin, slug="st-marys", **payload):
        body = {"role": Role.TEACHER.value, "email": "new.teacher@example.com", "full_name": ""}
        body.update(payload)
        self.client.force_login(admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/schools/{slug}/invitations/", data=body, content_type="application/json"
            )
        self.assertEqual(response.status_code, 201, response.content)
        return Invitation.objects.get(pk=response.json()["id"])

    def listed(self, user, slug="st-marys"):
        self.client.force_login(user)
        return self.client.get(f"/api/schools/{slug}/invitations/")

    def rows(self, user, slug="st-marys"):
        response = self.listed(user, slug)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["invitations"]

    # -- the control, and it runs first ----------------------------------------

    def test_the_list_really_lists_an_invitation(self):
        """Every exclusion below would pass against a list of nobody."""
        self.invite(self.admin)

        rows = self.rows(self.admin)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sent_to"], "new.teacher@example.com")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["role"], Role.TEACHER.value)

    # -- the other school ------------------------------------------------------

    def test_each_school_lists_only_its_own(self):
        """CONTROL 3: dropping `membership__school=` from the list makes this red."""
        self.invite(self.admin, email="ours@example.com")
        self.invite(self.their_admin, slug="grace", email="theirs@example.com")

        self.assertEqual([r["sent_to"] for r in self.rows(self.admin)], ["ours@example.com"])
        self.assertEqual(
            [r["sent_to"] for r in self.rows(self.their_admin, "grace")], ["theirs@example.com"]
        )

    def test_an_administrator_at_one_school_cannot_read_the_others(self):
        self.invite(self.their_admin, slug="grace", email="theirs@example.com")

        response = self.listed(self.admin, "grace")

        self.assertEqual(response.status_code, 403)
        self.assertIn(MAY_NOT_INVITE, response.json()["detail"])
        self.assertNotIn("theirs@example.com", response.content.decode())

    # -- who, and only what was typed ------------------------------------------

    def test_the_list_never_carries_the_accounts_own_name(self):
        """The address resolves to a teacher Grace already has, under Grace's
        name for her. St Mary's typed the address and a name of its own; it is
        shown the address, and neither name.

        CONTROL 5: the row's "who" read off the account makes this red.
        """
        self.person("shared@example.com", "Their Real Name", self.grace, Role.TEACHER)

        self.invite(self.admin, email="Shared@Example.com", full_name="Typed Name")

        response = self.listed(self.admin)
        self.assertEqual(response.json()["invitations"][0]["sent_to"], "shared@example.com")
        self.assertNotIn("Their Real Name", response.content.decode())

    def test_an_invitation_from_before_the_column_says_nothing_about_who(self):
        """The screen shows "-" for this; the API says so with a null rather
        than borrowing anything from the account."""
        invitation = self.invite(self.admin, full_name="New Teacher")
        Invitation.objects.filter(pk=invitation.pk).update(sent_to="")

        row = self.rows(self.admin)[0]

        self.assertIsNone(row["sent_to"])
        self.assertNotIn("New Teacher", str(row))

    def test_a_phone_invitation_keeps_the_number_as_read(self):
        self.invite(self.admin, email=None, phone="0803 123 4567")

        self.assertEqual(self.rows(self.admin)[0]["sent_to"], "+2348031234567")

    # -- who may ---------------------------------------------------------------

    def test_a_principal_is_refused_before_the_read(self):
        self.invite(self.admin)

        response = self.listed(self.principal)

        self.assertEqual(response.status_code, 403)
        self.assertIn(MAY_NOT_INVITE, response.json()["detail"])
        self.assertNotIn("new.teacher@example.com", response.content.decode())

    # -- one row per person, the newest ----------------------------------------

    def test_a_resend_is_one_row_and_keeps_the_address(self):
        first = self.invite(self.admin)
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            resent = self.client.post(f"/api/schools/st-marys/invitations/{first.pk}/resend/")
        self.assertEqual(resent.status_code, 201, resent.content)

        rows = self.rows(self.admin)

        self.assertEqual([r["id"] for r in rows], [resent.json()["id"]])
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["sent_to"], "new.teacher@example.com")

    def test_a_revoked_invitation_stays_listed_to_send_again(self):
        invitation = self.invite(self.admin)
        invitation.revoke()

        self.assertEqual([r["status"] for r in self.rows(self.admin)], ["revoked"])

    def test_a_pending_invitation_past_its_expiry_reads_expired(self):
        invitation = self.invite(self.admin)
        Invitation.objects.filter(pk=invitation.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        self.assertEqual([r["status"] for r in self.rows(self.admin)], ["expired"])

    def test_an_accepted_invitation_drops_off(self):
        invitation = self.invite(self.admin)
        invitation.accept(password="a-long-and-unusual-passphrase")
        self.assertEqual(
            Invitation.objects.get(pk=invitation.pk).status, InvitationStatus.ACCEPTED
        )

        self.assertEqual(self.rows(self.admin), [])
