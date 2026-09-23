"""The staff invitations page: a frame, and not one invitation in it.

The same claims the roll's frame makes: a shell served to whoever opens the
URL, naming nobody. The one thing it carries is the school's slug, which the
invitation routes are addressed by and which the host already says.

The flow — the list, the form, resend and cancel, the refusals — is in
`tests/js/staff.test.js` under `node --test`; the list's rules are in
`schools/tests/test_invitation_list.py`.
"""

from django.test import override_settings

from accounts.tests.test_enrolment_api import EnrolmentSetUp
from results.tests.fixtures import HOST, PORTAL

URL = "/staff/"


class TheStaffFrameHoldsNoInvitationsTests(EnrolmentSetUp):
    def test_a_schools_own_host_serves_it_with_its_slug(self):
        self.client.force_login(self.admin.user)

        response = self.client.get(URL, HTTP_HOST=HOST)

        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn('id="staff"', page)
        self.assertIn('data-school="st-marys"', page)

    @override_settings(
        INVITATION_CHANNEL="schools.tests.test_invitations.RecordingChannel",
        INVITATION_ACCEPT_URL="https://portal.example.school/invitations/{token}/",
    )
    def test_the_invitation_really_exists_while_the_frame_is_empty_of_it(self):
        """The control for the exclusion below: a frame that names nobody has
        two possible reasons, and this pins the one that is not the design."""
        self.client.force_login(self.admin.user)
        created = self.client.post(
            "/api/schools/st-marys/invitations/",
            data={"role": "teacher", "email": "new.teacher@example.com"},
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(created.status_code, 201, created.content)
        listed = self.client.get("/api/schools/st-marys/invitations/", HTTP_HOST=HOST)
        self.assertIn("new.teacher@example.com", listed.content.decode())

        page = self.client.get(URL, HTTP_HOST=HOST).content.decode()

        self.assertNotIn("new.teacher@example.com", page)

    def test_the_portal_serves_the_frame_with_no_school(self):
        self.client.force_login(self.admin.user)

        response = self.client.get(URL, HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-school=""', response.content.decode())
