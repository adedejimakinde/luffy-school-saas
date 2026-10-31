"""Who may see a child's photo: the same people as before the upload service.

Before the files moved to disk (PR #313), a child's passport photo reached
people two ways, and only two:

1. **The roll's photo route**, `GET /api/enrolment/roll/<child>/photo/`, behind
   `accounts.enrolment_api._refuse_outsiders`: a principal, an administrator,
   and platform staff (`can_grant_memberships` admits them), at the child's own
   school. Not a teacher, a vice principal, a bursar, a parent or the child.
2. **The Ogun State card**, which prints it: the card's payload (`ogun.photo`)
   and its PDF, to whoever `results.card_api._may_read` admits: the child,
   the child's own guardians, and the school's teachers, vice principals,
   principals, administrators and bursars. Not another child's parent, and not
   another school's staff.

This file pins that table. It uses the HTTP routes only, and the photo is
uploaded through the roll's own route (the fixture's photo in the old column is
emptied first, and each answer is checked to be the uploaded picture), so the
same file was run against the commit before the service, where all of it
passed too, and runs here: the two answers are the same table, and here they
are answered from the file kept on disk.
"""

import base64
import io

from PIL import Image

from accounts.models import Role, User
from academics.models import StudentDetails, TermName
from results import cards, pdf
from results.tests.test_card_api import HOST, THEIR_HOST
from results.tests.test_ogun_card import OgunCardSetUp
from schools.tests.tenants import connected_to

FIRST = TermName.FIRST.value


def body(response) -> bytes:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


def is_the_red_upload(data: bytes) -> bool:
    r, g, b = Image.open(io.BytesIO(data)).convert("RGB").getpixel((140, 180))
    return r > 150 and g < 100 and b < 100


def photo(colour=(200, 40, 40)):
    out = io.BytesIO()
    Image.new("RGB", (900, 1200), colour).save(out, format="JPEG")
    return out.getvalue()


class PhotoAccessSetUp(OgunCardSetUp):
    def setUp(self):
        super().setUp()
        self.admin = self.staff[Role.ADMIN]
        self.ops = User.objects.create_user("ops-photos", "a-long-password-1", is_platform_staff=True)
        # The fixture writes a blue photo straight into the column; this table
        # is about the one the office uploads (red), so the column is emptied.
        with connected_to(self.stmarys):
            StudentDetails.objects.filter(student_membership_id=self.ada.pk).update(photo=None)
        # Uploaded the way the office does it, through the roll.
        self.client.force_login(self.admin)
        sent = self.client.post(
            f"/api/enrolment/roll/{self.ada.pk}/photo/",
            {"photo": io.BytesIO(photo())},
            HTTP_HOST=HOST,
        )
        self.assertEqual(sent.status_code, 200, sent.content)
        self.assertTrue(sent.json()["has_photo"])
        self.release()
        self.release(self.grace)

    def roll_photo(self, user, host=HOST, child=None):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)
        return self.client.get(f"/api/enrolment/roll/{(child or self.ada).pk}/photo/", HTTP_HOST=host)

    def card_photo(self, user, host=None):
        """The card's `ogun.photo`, or the status code when the card was refused."""
        response = self.fetch(user, self.stmarys, self.ada, FIRST, host=host)
        if response.status_code != 200:
            return response.status_code
        return response.json()["ogun"]["photo"]


class TheRollsPhotoRouteTests(PhotoAccessSetUp):
    def test_the_principal_the_administrator_and_platform_staff_are_sent_it(self):
        for user in (self.principal, self.admin, self.ops):
            with self.subTest(user=user.username):
                response = self.roll_photo(user)
                self.assertEqual(response.status_code, 200)
                sent = body(response)  # a streamed file is read once
                self.assertEqual(Image.open(io.BytesIO(sent)).size, (280, 360))
                self.assertTrue(is_the_red_upload(sent))

    def test_nobody_else_at_the_school_is(self):
        for who, user in (
            ("teacher", self.teacher),
            ("vice principal", self.vp),
            ("bursar", self.bursar),
            ("the child's guardian", self.mama),
            ("the child", self.ada.user),
        ):
            with self.subTest(who=who):
                response = self.roll_photo(user)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(b"JFIF", body(response))

    def test_signed_out_or_from_another_school_it_is_not_sent(self):
        self.assertIn(self.roll_photo(None).status_code, (401, 403))
        self.assertEqual(self.roll_photo(self.their_principal).status_code, 403)
        self.assertEqual(self.roll_photo(self.their_principal, host=THEIR_HOST).status_code, 404)


class TheOgunCardTests(PhotoAccessSetUp):
    def test_the_child_their_guardian_and_every_card_reading_role_see_the_photo(self):
        for who, user in (
            ("the child", self.ada.user),
            ("the child's guardian", self.mama),
            ("teacher", self.teacher),
            ("vice principal", self.vp),
            ("principal", self.principal),
            ("administrator", self.admin),
            ("bursar", self.bursar),
        ):
            with self.subTest(who=who):
                shown = self.card_photo(user)
                self.assertIsInstance(shown, str, f"refused with {shown}")
                self.assertTrue(shown.startswith("data:image/jpeg;base64,"))
                self.assertTrue(is_the_red_upload(base64.b64decode(shown.split(",", 1)[1])))

    def test_another_childs_parent_another_school_and_platform_staff_do_not(self):
        self.assertEqual(self.card_photo(self.bolas_father), 404)
        self.assertEqual(self.card_photo(self.ops), 404)
        self.assertNotEqual(self.card_photo(self.their_principal), 200)
        self.assertEqual(self.card_photo(self.their_principal, host=THEIR_HOST), 404)

    def test_the_card_as_printed_carries_it(self):
        with connected_to(self.stmarys):
            html = pdf.html_for(cards.card_for(self.ada, self.term_of(self.stmarys, FIRST)))
        self.assertIn('<div class="photo"><img src="data:image/jpeg;base64,', html)
        printed = html.split('<div class="photo"><img src="data:image/jpeg;base64,', 1)[1].split('"', 1)[0]
        self.assertTrue(is_the_red_upload(base64.b64decode(printed)))
