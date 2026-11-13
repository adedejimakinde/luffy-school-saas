"""The page a card's QR code opens: valid or expired, and nothing else. `docs/id-cards.md`.

The page is public, on the school's own host, for anybody with a phone. What it
may show is a name, a class, a photo and whether the card is valid or expired.
Nothing else about the child, the family or the school is to be on it, and the
tests say so twice: structurally (the template is handed an object with exactly
those fields) and on the bytes, against a child who has every kind of record the
school can keep, so that a leak cannot pass for want of anything to leak.

An expired card names the child and says so, and shows no photo and no class.
"""

import dataclasses
import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from academics import details
from accounts.models import Role
from idcards import cards
from idcards.models import IdCard
from schools.tests.tenants import connected_to

from .base import HOST, PARENT_PHONE, SCHOOL_PHONE, IdCardSetUp


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (900, 1200), (150, 110, 80)).save(out, format="JPEG")
    return out.getvalue()


class VerifySetUp(IdCardSetUp):
    """Ada: a photo, a learner's ID, a birthday, a mother with a verified phone. Then printed."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff[Role.ADMIN])
        self.client.post(
            f"/api/enrolment/roll/{self.ada.pk}/photo/",
            {"photo": SimpleUploadedFile("p.jpg", jpeg(), content_type="image/jpeg")},
            HTTP_HOST=HOST,
        )
        with connected_to(self.stmarys):
            details.record(self.ada.pk, learner_id="OG/ABS/0042", sex="female", date_of_birth="2013-05-02")
        self.printed(self.principal)
        self.token = self.token_of(self.ada)
        self.client.logout()

    def expire(self, days_ago=1):
        with connected_to(self.stmarys):
            IdCard.objects.filter(token=self.token).update(expires_on=self.today - timedelta(days=days_ago))


class AValidCardTests(VerifySetUp):
    def test_it_says_valid_with_the_name_the_class_and_the_photo(self):
        response = self.verify(self.token)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-verdict="valid"')
        self.assertContains(response, "Valid")
        self.assertContains(response, "Ada Obi")
        self.assertContains(response, "JSS 1A")
        self.assertContains(response, '<img class="holder" src="data:image/jpeg;base64,')
        self.assertContains(response, "looks like this photo")

    def test_it_needs_no_sign_in_and_a_stranger_signed_in_elsewhere_may_open_it(self):
        self.assertEqual(self.verify(self.token, user=None).status_code, 200)
        self.assertEqual(self.verify(self.token, user=self.their_staff[Role.PRINCIPAL]).status_code, 200)
        self.assertEqual(self.verify(self.token, user=self.mama).status_code, 200)

    def test_the_last_day_is_still_valid_and_the_day_after_is_not(self):
        with connected_to(self.stmarys):
            IdCard.objects.filter(token=self.token).update(expires_on=self.today)
        self.assertContains(self.verify(self.token), 'data-verdict="valid"')
        self.expire(1)
        self.assertContains(self.verify(self.token), 'data-verdict="expired"')

    def test_a_child_with_no_photo_is_valid_with_no_picture(self):
        bola = self.token_of(self.bola)
        response = self.verify(bola)
        self.assertContains(response, 'data-verdict="valid"')
        self.assertContains(response, "Bola Eze")
        self.assertNotContains(response, 'class="holder"')
        self.assertNotContains(response, "looks like this photo")

    def test_it_is_never_cached_never_indexed_and_sends_no_referrer(self):
        response = self.verify(self.token)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("noindex", response["X-Robots-Tag"])

    def test_the_class_is_the_one_the_child_sits_in_now(self):
        from academics.models import ClassGroup, Term, TermName
        from academics.services import move_student
        from accounts.models import Membership

        with connected_to(self.stmarys):
            other = ClassGroup.objects.create(name="JSS 2A", level=2)
            move_student(other, Term.objects.get(pk=self.terms[TermName.FIRST.value]), Membership.objects.get(pk=self.ada.pk))
        self.assertContains(self.verify(self.token), "JSS 2A")


class AnExpiredCardTests(VerifySetUp):
    def test_it_says_expired_names_the_child_and_shows_no_photo_and_no_class(self):
        self.expire()
        response = self.verify(self.token)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-verdict="expired"')
        self.assertContains(response, "Expired")
        self.assertContains(response, "no longer valid")
        self.assertContains(response, "Ada Obi")
        self.assertNotContains(response, "JSS 1A")
        self.assertNotContains(response, "data:image/jpeg")
        self.assertNotContains(response, 'data-verdict="valid"')

    def test_a_withdrawn_card_reads_as_expired(self):
        from django.utils import timezone

        with connected_to(self.stmarys):
            IdCard.objects.filter(token=self.token).update(revoked_at=timezone.now())
        self.assertContains(self.verify(self.token), 'data-verdict="expired"')

    def test_a_child_who_has_left_the_school_reads_as_expired_and_the_page_does_not_say_why(self):
        self.ada.end()
        response = self.verify(self.token)
        self.assertContains(response, 'data-verdict="expired"')
        self.assertNotContains(response, "left")
        self.assertNotContains(response, "enrol")
        self.assertNotContains(response, "JSS 1A")


class NothingBeyondTheAllowedFieldsTests(VerifySetUp):
    #: Everything the school holds about Ada, and the school itself: none of it may be on the page.
    FORBIDDEN = (
        "STM/001",            # the admission number
        "OG/ABS/0042",        # the learner's ID
        "2013",               # the date of birth, however it is written
        "female",
        PARENT_PHONE,         # the parent's number
        "Mama Ada",           # the parent's name
        SCHOOL_PHONE,         # not even the school's own
        "12 Palm Road",       # nor its address
        "Bola Eze",           # another child
        "ada",                # the login name
        "Student ID card",
        "expires", "Valid until",
    )

    def test_the_valid_page_holds_none_of_it(self):
        text = self.verify(self.token).content.decode()
        for forbidden in self.FORBIDDEN:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text.replace("Ada Obi", ""))

    def test_nor_does_the_expired_page(self):
        self.expire()
        text = self.verify(self.token).content.decode()
        for forbidden in self.FORBIDDEN:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text.replace("Ada Obi", ""))

    def test_the_expiry_date_is_not_shown_either(self):
        """Valid or expired is the whole of what it says about time."""
        with connected_to(self.stmarys):
            expires = IdCard.objects.get(token=self.token).expires_on
        text = self.verify(self.token).content.decode()
        self.assertNotIn(str(expires.year * 10000 + expires.month * 100 + expires.day), text)
        self.assertNotIn(expires.isoformat(), text)
        self.assertNotIn(f"{expires:%B}", text.replace("Ada Obi", ""))

    def test_the_template_is_handed_exactly_four_fields_and_nothing_to_print_more_from(self):
        response = self.verify(self.token)
        result = response.context["result"]
        self.assertIsInstance(result, cards.Verification)
        self.assertEqual({f.name for f in dataclasses.fields(result)}, {"valid", "name", "class_name", "photo"})
        for name in ("student", "membership", "card", "child", "school_phone", "admission_number"):
            self.assertNotIn(name, response.context)

    def test_the_control_the_check_can_see_a_leak(self):
        """The forbidden strings are real: each is on the card or the roll, and the card says them."""
        from idcards import render

        with connected_to(self.stmarys):
            from academics.models import ClassGroup, Term, TermName

            group = ClassGroup.objects.get(pk=self.group_id)
            term = Term.objects.get(pk=self.terms[TermName.FIRST.value])
            kids = cards.students_of(self.stmarys, group, term)
            faces = [
                cards.face_for(k, class_name="JSS 1A", session=self.session, expires_on=self.today, by_id=None)
                for k in kids
            ]
            on_the_card = render.html_for(cards.school_face(self.stmarys), "JSS 1A", faces)
        for said in ("STM/001", SCHOOL_PHONE, "Bola Eze", "Student ID card", "Valid until"):
            self.assertIn(said, on_the_card)
        with connected_to(self.stmarys):
            self.assertEqual(details.details_for([self.ada.pk])[self.ada.pk].learner_id, "OG/ABS/0042")


class AnUnknownCardTests(VerifySetUp):
    def test_a_token_nobody_issued_is_refused_and_names_nobody(self):
        for token in ("nothingissuedthis", "x", "A" * 16, "../../etc/passwd"):
            with self.subTest(token=token):
                response = self.verify(token)
                self.assertIn(response.status_code, (404,))
                self.assertNotContains(response, "Ada Obi", status_code=404)
                self.assertNotContains(response, "Bola Eze", status_code=404)

    def test_the_page_says_it_cannot_confirm_the_card(self):
        response = self.verify("nothingissuedthis")
        self.assertContains(response, 'data-verdict="unknown"', status_code=404)
        self.assertContains(response, "Do not accept it as identification", status_code=404)

    def test_the_portal_has_no_cards(self):
        self.assertEqual(self.verify(self.token, host="testserver").status_code, 404)

    def test_it_answers_a_get_and_nothing_that_writes(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(f"/verify/{self.token}/", HTTP_HOST=HOST)
                self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.head(f"/verify/{self.token}/", HTTP_HOST=HOST).status_code, 200)
