"""What a printed card says, and how the sheet lays it out. `docs/id-cards.md`.

Read as the HTML WeasyPrint is handed (`render.html_for`), which holds every word
a card prints and every position it prints it at; and as the PDF, for its pages.
The QR code was also decoded from a printed PDF by hand for the pull request
(OpenCV is not a dependency of this project, so no test does it); what the
tests hold is that the code drawn is the code for the card's own address, and
that the address opens the card's page.
"""

import io
import re

import pikepdf
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from academics.models import ClassGroup, Term, TermName
from accounts.models import Role
from idcards import cards, render
from idcards.models import IdCard
from schools.tests.tenants import connected_to

from .base import HOST, PARENT_PHONE, SCHOOL_PHONE, IdCardSetUp


def jpeg(size=(900, 1200), colour=(180, 120, 90)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="JPEG")
    return out.getvalue()


class CardSetUp(IdCardSetUp):
    def html(self, school=None, children=None, **kwargs):
        """The HTML for the first sheet of JSS 1A, as the worker would hand it to WeasyPrint."""
        school = school or self.stmarys
        with connected_to(school):
            group = ClassGroup.objects.get(pk=self.group_of(school))
            term = Term.objects.get(pk=self.terms_of(school)[TermName.FIRST.value])
            kids = cards.students_of(school, group, term)
            if children is not None:
                kids = [k for k in kids if k["id"] in children]
            expires = cards.session_ends_on(term.session)
            faces = [
                cards.face_for(k, class_name=group.name, session=term.session, expires_on=expires, by_id=None)
                for k in kids
            ]
            return render.html_for(cards.school_face(school), group.name, faces, **kwargs), faces

    def give_photo(self, child):
        self.client.force_login(self.staff[Role.ADMIN])
        response = self.client.post(
            f"/api/enrolment/roll/{child.pk}/photo/",
            {"photo": SimpleUploadedFile("p.jpg", jpeg(), content_type="image/jpeg")},
            HTTP_HOST=HOST,
        )
        self.assertEqual(response.status_code, 200, response.content)


class WhatTheCardSaysTests(CardSetUp):
    def test_every_field_the_card_is_to_carry_is_on_it(self):
        html, faces = self.html()
        face = next(f for f in faces if f.name == "Ada Obi")
        for said in (
            "St Mary&#x27;s",          # the school's name
            "Ada Obi",                 # full name
            "STM/001",                 # admission number
            "JSS 1A",                  # class
            self.session,              # session
            "Student ID card",
        ):
            with self.subTest(said=said):
                self.assertIn(said, html)
        # The expiry date, as a person reads it, on the front and the back.
        on_card = f"{face.expires_on.day} {face.expires_on:%B %Y}"
        self.assertGreaterEqual(html.count(on_card), 2, on_card)

    def test_the_card_expires_when_the_session_does(self):
        _, faces = self.html()
        with connected_to(self.stmarys):
            last = Term.objects.get(pk=self.terms[TermName.THIRD.value]).ends_on
        self.assertEqual({f.expires_on for f in faces}, {last})

    def test_the_emergency_line_is_the_schools_phone(self):
        html, _ = self.html()
        self.assertIn("In an emergency call the school:", html)
        self.assertIn(SCHOOL_PHONE, html)

    def test_a_parents_number_is_never_on_a_card(self):
        """Ada's mother has a verified phone on record; the card must not reach for it."""
        html, _ = self.html()
        for number in (PARENT_PHONE, PARENT_PHONE[1:], "0803 000 0001", "+2348030000001", "Mama Ada"):
            with self.subTest(number=number):
                self.assertNotIn(number, html)

    def test_with_no_school_phone_it_says_so_and_invents_no_number(self):
        self.stmarys.phone = ""
        self.stmarys.save(update_fields=["phone"])
        html, _ = self.html(school=type(self.stmarys).objects.get(pk=self.stmarys.pk))
        self.assertIn("In an emergency, contact the school office.", html)
        self.assertNotIn("call the school:", html)
        self.assertNotIn(SCHOOL_PHONE, html)

    def test_the_qr_code_is_the_code_for_this_cards_own_address_and_the_address_opens_it(self):
        html, faces = self.html()
        face = next(f for f in faces if f.name == "Ada Obi")
        token = self.token_of(self.ada)
        self.assertEqual(face.verify_url, f"https://{HOST}/verify/{token}/")
        self.assertEqual(face.qr, cards.qr_data_uri(face.verify_url))
        self.assertIn(face.qr, html)
        # And the link works, for a phone with no sign-in.
        self.client.logout()
        opened = self.client.get(f"/verify/{token}/", HTTP_HOST=HOST)
        self.assertEqual(opened.status_code, 200)
        self.assertContains(opened, "Ada Obi")

    def test_each_child_has_their_own_code_and_a_reprint_keeps_it(self):
        _, first = self.html()
        _, again = self.html()
        urls = {f.name: f.verify_url for f in first}
        self.assertEqual(len(set(urls.values())), 2)
        self.assertEqual(urls, {f.name: f.verify_url for f in again})
        with connected_to(self.stmarys):
            self.assertEqual(IdCard.objects.count(), 2)


class AWithdrawnCardTests(CardSetUp):
    def test_printing_again_gives_the_child_a_new_valid_card_and_kills_the_old_code(self):
        from django.utils import timezone

        _, first = self.html()
        old = self.token_of(self.ada)
        with connected_to(self.stmarys):
            IdCard.objects.filter(token=old).update(revoked_at=timezone.now())
        self.assertContains(self.verify(old), 'data-verdict="expired"')

        _, again = self.html()
        new = self.token_of(self.ada)
        self.assertNotEqual(old, new)
        self.assertContains(self.verify(new), 'data-verdict="valid"')
        self.assertEqual(self.verify(old).status_code, 404)
        with connected_to(self.stmarys):
            self.assertEqual(IdCard.objects.filter(student_membership_id=self.ada.pk).count(), 1)
        # Everybody else's card is the one they had.
        by_name = lambda faces: {f.name: f.verify_url for f in faces}  # noqa: E731
        self.assertEqual(by_name(first)["Bola Eze"], by_name(again)["Bola Eze"])


class ThePhotoTests(CardSetUp):
    def test_a_child_with_no_photo_gets_a_clean_placeholder_with_their_initials(self):
        html, faces = self.html()
        self.assertEqual({f.photo for f in faces}, {None})
        self.assertEqual(html.count('class="abs photo none cell"'), 2)
        self.assertNotIn('<div class="abs photo"><img', html)
        self.assertIn(">AO<", html)
        self.assertIn(">BE<", html)

    def test_a_child_with_a_photo_gets_it_and_the_other_still_gets_a_placeholder(self):
        self.give_photo(self.ada)
        html, faces = self.html()
        by_name = {f.name: f for f in faces}
        self.assertTrue(by_name["Ada Obi"].photo.startswith("data:image/jpeg;base64,"))
        self.assertIsNone(by_name["Bola Eze"].photo)
        self.assertEqual(html.count('<div class="abs photo"><img'), 1)
        self.assertEqual(html.count('class="abs photo none cell"'), 1)

    def test_initials(self):
        for name, said in (
            ("Ada Obi", "AO"),
            ("Ada", "A"),
            ("", "?"),
            ("  ", "?"),
            ("Mary-Jane Okoro", "MO"),
            ("ṣọla Adéṣanya", "ṢA"),
            ("Chidi Okonkwo-Eze", "CE"),
        ):
            with self.subTest(name=name):
                self.assertEqual(cards.initials_of(name), said)


class TheSheetTests(CardSetUp):
    def test_ten_cards_to_a_sheet_a_page_of_fronts_then_a_page_of_backs(self):
        self.more_children(8)
        html, faces = self.html()
        self.assertEqual(len(faces), 10)
        sheets = re.findall(r'<div class="sheet">', html)
        self.assertEqual(len(sheets), 2)
        self.assertEqual(html.count('class="card front"'), 10)
        self.assertEqual(html.count('class="card back"'), 10)

    def test_a_sheet_holds_ten_and_no_more(self):
        self.more_children(9)
        with connected_to(self.stmarys):
            group = ClassGroup.objects.get(pk=self.group_id)
            term = Term.objects.get(pk=self.terms[TermName.FIRST.value])
            kids = cards.students_of(self.stmarys, group, term)
            faces = [
                cards.face_for(k, class_name="JSS 1A", session=self.session, expires_on=self.today, by_id=None)
                for k in kids
            ]
        self.assertEqual(len(faces), 11)
        with self.assertRaises(ValueError):
            render.sheets_for(faces, first_sheet=1, total_sheets=2)

    def test_a_card_is_credit_card_size_cr80(self):
        html, _ = self.html()
        self.assertEqual((render.CARD_W, render.CARD_H), (85.6, 54.0))
        self.assertIn("width:85.60mm;height:54.00mm", html)

    def test_the_geometry_fits_a_4_and_cut_marks_sit_clear_of_every_card(self):
        places = render.cell_positions()
        self.assertEqual(len(places), 10)
        right = max(left + render.CARD_W for _, _, left, _ in places)
        bottom = max(top + render.CARD_H for _, _, _, top in places)
        self.assertLessEqual(right, render.PAGE_W)
        self.assertLessEqual(bottom, render.PAGE_H)
        # Centred on the page.
        self.assertAlmostEqual(render.LEFT, render.PAGE_W - right, places=6)
        self.assertAlmostEqual(render.TOP, render.PAGE_H - bottom, places=6)

        grid = (render.LEFT, render.TOP, render.LEFT + render.GRID_W, render.TOP + render.GRID_H)
        marks = render.cut_marks()
        # Three vertical lines and six horizontal ones, a tick at each end of each.
        self.assertEqual(len(marks), 2 * 3 + 2 * 6)
        for left, top, width, height in marks:
            with self.subTest(mark=(left, top)):
                clear_x = left + width <= grid[0] or left >= grid[2]
                clear_y = top + height <= grid[1] or top >= grid[3]
                self.assertTrue(clear_x or clear_y, "a cut mark would print on a card")
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(left + width, render.PAGE_W)
                self.assertLessEqual(top + height, render.PAGE_H)

    def test_every_page_carries_all_the_cut_marks(self):
        html, _ = self.html()
        self.assertEqual(html.count('class="mark"'), 2 * len(render.cut_marks()))

    def test_the_backs_columns_are_mirrored_so_a_double_sided_print_lines_up(self):
        faces = self.html()[1]
        front, back = render.sheets_for(faces, first_sheet=1, total_sheets=1)
        self.assertEqual((front["side"], back["side"]), ("front", "back"))
        for f, b in zip(front["cells"], back["cells"]):
            self.assertEqual(f["face"], b["face"])
        # Row one: Ada left on the front, so her back is on the right; and Bola's the reverse.
        self.assertIn(f"left:{render.LEFT:.2f}mm", front["cells"][0]["style"])
        self.assertIn(f"left:{render.LEFT + render.CARD_W:.2f}mm", back["cells"][0]["style"])
        self.assertIn(f"left:{render.LEFT + render.CARD_W:.2f}mm", front["cells"][1]["style"])
        self.assertIn(f"left:{render.LEFT:.2f}mm", back["cells"][1]["style"])
        # Same row, whichever side.
        tops = {c["style"].split("top:")[1].split(";")[0] for c in (front["cells"][0], back["cells"][0])}
        self.assertEqual(len(tops), 1)

    def test_the_pdf_is_a4_with_a_front_and_a_back_page_per_ten_children_and_a_bookmark_per_sheet(self):
        self.more_children(12)  # 14 children: two sheets, four pages
        _, pdf = self.printed(self.principal)
        with pikepdf.open(io.BytesIO(pdf)) as doc:
            self.assertEqual(len(doc.pages), 4)
            for page in doc.pages:
                box = [float(v) for v in page.mediabox]
                self.assertAlmostEqual(box[2] - box[0], 595.28, delta=0.5)
                self.assertAlmostEqual(box[3] - box[1], 841.89, delta=0.5)
            with doc.open_outline() as outline:
                titles = [item.title for item in outline.root]
        self.assertEqual(len(titles), 2)
        self.assertTrue(titles[0].startswith("Sheet 1: "), titles)
        self.assertTrue(titles[1].startswith("Sheet 2: "), titles)
