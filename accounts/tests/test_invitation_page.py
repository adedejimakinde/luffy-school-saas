"""The invitation accept page: a frame on the portal, and the API it relies on.

The flow — the offer, the password, the one state for a dead link, escaping —
is in `tests/js/invite.test.js` under `node --test`. What is here is the two
things only the server can hold: the frame names nobody and is served only on
the portal, and every refused token is answered **identically**, which is what
lets the page show one state without hiding anything.
"""

from datetime import timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User
from accounts.services import grant_membership
from schools import invitations
from schools.models import Domain, Invitation, School
from schools.tests.test_invitations import RecordingChannel, make_school

PORTAL = "testserver"
SCHOOL_HOST = "stmarys.testserver"


@override_settings(
    INVITATION_CHANNEL="schools.tests.test_invitations.RecordingChannel",
    INVITATION_ACCEPT_URL="https://portal.example.test/invitations/{token}/",
)
class InvitationPageTests(TestCase):
    def setUp(self):
        RecordingChannel.sent = []
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        Domain.objects.create(tenant=self.stmarys, domain=SCHOOL_HOST, is_primary=True)
        self.admin = User.objects.create_user("admin", "a-long-password", full_name="Ada Admin")
        grant_membership(self.admin, self.stmarys, Role.ADMIN)

    def tearDown(self):
        # `TenantMainMiddleware` (and a migrated schema) leave the connection on
        # a school's schema, and `School.save()` refuses to create a tenant
        # anywhere but public — so without this the failure lands in whichever
        # test happens to run next. `BroadsheetApiSetUp` carries the same line.
        connection.set_schema_to_public()
        super().tearDown()

    def invite(self, email="kemi@example.com", name="Kemi Bello"):
        with self.captureOnCommitCallbacks(execute=True):
            invitation, raw = invitations.invite_staff(
                self.admin, self.stmarys, Role.TEACHER, email=email, full_name=name
            )
        return invitation, raw

    def preview(self, token):
        return self.client.get(f"/api/invitations/{token}/", HTTP_HOST=PORTAL)

    # -- the frame --------------------------------------------------------------

    def test_the_frame_names_nobody_and_holds_no_token(self):
        _, raw = self.invite()
        self.assertIn("Kemi Bello", self.preview(raw).content.decode(), "the control: the API names her")

        response = self.client.get(f"/invitations/{raw}/", HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn('id="invite"', page)
        for absent in (raw, "Kemi Bello", "St Mary", "Teacher"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_the_frame_is_not_cached_and_sends_no_referrer(self):
        """The address it was served from is a live credential."""
        _, raw = self.invite()

        response = self.client.get(f"/invitations/{raw}/", HTTP_HOST=PORTAL)

        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn('name="referrer" content="no-referrer"', response.content.decode())

    def test_a_guessed_token_gets_the_same_frame(self):
        _, raw = self.invite()

        real = self.client.get(f"/invitations/{raw}/", HTTP_HOST=PORTAL).content
        guessed = self.client.get("/invitations/not-a-real-token/", HTTP_HOST=PORTAL).content

        self.assertEqual(real, guessed)

    def test_a_schools_own_host_has_no_invitation_page(self):
        _, raw = self.invite()

        response = self.client.get(f"/invitations/{raw}/", HTTP_HOST=SCHOOL_HOST)

        self.assertEqual(response.status_code, 404)

    # -- the one state the page relies on ---------------------------------------

    def test_every_refused_token_previews_identically(self):
        """Unknown, accepted, revoked and expired: the same status, the same
        bytes. The page's single "this link does not work" is honest only
        because there is nothing here for it to hide."""
        _, accepted_raw = self.invite(email="a@example.com")
        Invitation.validate_token(accepted_raw).accept(password="a-long-passphrase")
        revoked, revoked_raw = self.invite(email="r@example.com")
        revoked.revoke()
        expired, expired_raw = self.invite(email="e@example.com")
        Invitation.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(minutes=1))

        answers = {
            label: self.preview(token)
            for label, token in (
                ("unknown", "not-a-real-token"),
                ("accepted", accepted_raw),
                ("revoked", revoked_raw),
                ("expired", expired_raw),
            )
        }

        for label, response in answers.items():
            with self.subTest(token=label):
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, answers["unknown"].content)
