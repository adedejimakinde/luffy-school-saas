"""The Ogun State report card: `ReportCardOut.ogun`, its PDF, and the health copy.

`docs/ogun-template.md` part 5. Built on `ReportCardApiSetUp`: two schools, a
whole session each, St Mary's on the Ogun card and Grace on the Standard one.
"""

import io
from datetime import date

from PIL import Image

from academics import details
from academics.models import ClassGroup, ClassPlacement, StudentDetails, Term, TermName
from accounts.models import Role
from gradebook.models import Department, Subject
from results import ogun, ogun_card, pdf
from results.models import HealthRecord, ReleasedCard, ReleasedCardPdf
from results.tasks import render_card_pdf
from results.tests.test_card_api import HOST, ReportCardApiSetUp
from schools.models import School
from schools.tests.tenants import connected_to

SECOND, THIRD = TermName.SECOND.value, TermName.THIRD.value


def jpeg():
    out = io.BytesIO()
    Image.new("RGB", (300, 400), (90, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


class OgunCardSetUp(ReportCardApiSetUp):
    def setUp(self):
        super().setUp()
        School.objects.filter(pk=self.stmarys.pk).update(lga="Abeokuta South", school_code="B13003")
        self.stmarys.refresh_from_db()
        with connected_to(self.stmarys):
            ogun.set_template_as(self.principal, self.stmarys, "ogun")
            StudentDetails.objects.create(
                student_membership_id=self.ada.pk, learner_id="OG/ABS/0042", sex="female",
                date_of_birth=date(2013, 5, 2), photo=details.redraw_photo(jpeg()),
            )

    def ogun_papers(self, term, child, subject, test1, test2, assignment, exam):
        for name, value, out_of in (("1st Test", test1, 10), ("2nd Test", test2, 10), ("Assignment", assignment, 10), ("Exam", exam, 70)):
            if value is not None:
                self._mark(self.stmarys, term, child, subject, name, value, out_of=out_of)

    def payload(self, term=TermName.FIRST.value, who=None):
        response = self.fetch(who or self.mama, self.stmarys, self.ada, term)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class TheSheetTests(OgunCardSetUp):
    def test_the_control_an_ogun_card_carries_the_sheet_and_a_standard_one_does_not(self):
        self.release()
        self.release(self.grace)

        sheet = self.payload()["ogun"]
        theirs = self.fetch(self.their_principal, self.grace, self.ngozi).json()

        self.assertIsNotNone(sheet)
        self.assertIsNone(theirs["ogun"])
        self.assertEqual(sheet["school_line"], "St Mary's (Abeokuta South LGA) [B13003]")
        self.assertEqual(
            (sheet["learner_id"], sheet["sex"], sheet["date_of_birth"]), ("OG/ABS/0042", "Female", "02/05/2013")
        )
        self.assertTrue(sheet["photo"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(sheet["ministry"], list(ogun_card.MINISTRY))

    def test_a_junior_card_has_one_run_of_subjects_split_into_ca_and_exam(self):
        self.ogun_papers(SECOND, self.ada, "maths", 8, 9, 7, 61)
        self.ogun_papers(SECOND, self.ada, "english", 6, 7, 5, 40)
        # Bola sat English's exam and none of its tests: her CA is unknown, not nought.
        self._mark(self.stmarys, SECOND, self.bola, "english", "Exam", 50, out_of=70)
        self.release(term_name=SECOND)

        sheet = self.payload(SECOND)["ogun"]

        self.assertFalse(sheet["senior"])
        self.assertEqual([g["label"] for g in sheet["groups"]], [""])
        maths, english = sorted(sheet["groups"][0]["subjects"], key=lambda s: s["name"])[::-1]
        self.assertEqual((maths["ca"], maths["ca_max"], maths["exam"], maths["exam_max"], maths["weighted"]), (24, 30, 61, 70, "85"))
        self.assertEqual((english["ca"], english["exam"]), (18, 40))
        self.assertEqual((sheet["ca_out_of"], sheet["exam_out_of"]), (30, 70))
        self.client.force_login(self.principal)
        bola = self.client.get(
            f"/api/results/cards/{self.bola.pk}/{self.terms[SECOND]}/", HTTP_HOST=HOST
        ).json()["ogun"]
        bola_english = [s for s in bola["groups"][0]["subjects"] if s["name"] == "English"][0]
        self.assertEqual((bola_english["ca"], bola_english["exam"]), (None, 50))

    def test_a_senior_card_groups_subjects_by_department(self):
        with connected_to(self.stmarys):
            ClassGroup.objects.filter(pk=self.group_id).update(name="SSS 2A")
            Subject.objects.filter(pk=self.subjects["maths"]).update(department=Department.SCIENCE)
        self.release()

        sheet = self.payload()["ogun"]

        self.assertTrue(sheet["senior"])
        self.assertIn("SENIOR", sheet["title"])
        self.assertEqual(
            [(g["label"], [s["name"] for s in g["subjects"]]) for g in sheet["groups"]],
            [("Science & Mathematics", ["Mathematics"]), ("Other", ["English"])],
        )

    def test_which_class_names_are_senior(self):
        for name, senior in (("SSS 1A", True), ("SS2 Gold", True), ("S.S.S. 3", True), ("JSS 1A", False), ("Primary 4", False)):
            with self.subTest(name=name):
                self.assertEqual(ogun_card.is_senior(name), senior)


class TheThirdTermTests(OgunCardSetUp):
    def setUp(self):
        super().setUp()
        # First term: the fixture's marks (Ada: Mathematics 88, English 74).
        self.release()
        # Second term: Mathematics only.
        self.ogun_papers(SECOND, self.ada, "maths", 7, 7, 6, 50)
        self.release(term_name=SECOND)
        self.ogun_papers(THIRD, self.ada, "maths", 9, 9, 9, 63)
        self.ogun_papers(THIRD, self.ada, "english", 8, 8, 8, 56)

    def test_each_term_and_the_average_over_the_terms_taken(self):
        self.release(term_name=THIRD)
        sheet = self.payload(THIRD)["ogun"]
        by_name = {s["name"]: s for g in sheet["groups"] for s in g["subjects"]}

        self.assertTrue(sheet["third_term"])
        self.assertEqual(
            [by_name["Mathematics"][k] for k in ("first", "second", "third", "annual")], ["88", "70", "90", "82.67"]
        )
        self.assertEqual(
            [by_name["English"][k] for k in ("first", "second", "third", "annual")], ["74", None, "80", "77"]
        )

    def test_promoted_to_the_class_the_child_was_placed_in(self):
        with connected_to(self.stmarys):
            next_first = Term.objects.create(session="2026/2027", name=TermName.FIRST, starts_on=date(2026, 9, 14), ends_on=date(2026, 12, 11))
            jss2 = ClassGroup.objects.create(name="JSS 2A", level=2)
            ClassPlacement.objects.create(class_group=jss2, term=next_first, student_membership_id=self.ada.pk)
        self.release(term_name=THIRD)
        self.assertEqual(self.payload(THIRD)["ogun"]["promotion"], "Promoted to JSS 2A")

    def test_placed_in_the_same_class_is_to_repeat(self):
        with connected_to(self.stmarys):
            next_first = Term.objects.create(session="2026/2027", name=TermName.FIRST, starts_on=date(2026, 9, 14), ends_on=date(2026, 12, 11))
            ClassPlacement.objects.create(class_group_id=self.group_id, term=next_first, student_membership_id=self.ada.pk)
        self.release(term_name=THIRD)
        self.assertEqual(self.payload(THIRD)["ogun"]["promotion"], "Not promoted, to repeat JSS 1A")

    def test_no_line_before_a_decision_and_none_on_another_term(self):
        self.release(term_name=THIRD)
        self.assertIsNone(self.payload(THIRD)["ogun"]["promotion"])
        self.assertIsNone(self.payload(SECOND)["ogun"]["promotion"])


class ThePdfTests(OgunCardSetUp):
    def card(self, term=TermName.FIRST.value):
        with connected_to(self.stmarys):
            return ReleasedCard.objects.get(student_membership_id=self.ada.pk, term__name=term)

    def test_the_ogun_pdf_is_the_sheet(self):
        self.release()
        with connected_to(self.stmarys):
            html = pdf.html_for(self.card())
        for words in (
            "MINISTRY OF EDUCATION, SCIENCE AND TECHNOLOGY",
            "St Mary&#x27;s (Abeokuta South LGA) [B13003]",
            "Cont. Assess Scores",
            "Exam Scores",
            "Weighted Average (100)",
            "Times school opened",
            "Marks obtainable",
            "Class position",
            "Rating key",
            "Physical development and health",
            "Class teacher's comment",
            "Principal's remark",
            "Signature",
            "School stamp",
            "OG/ABS/0042",
            "data:image/jpeg;base64,",
        ):
            with self.subTest(words=words):
                self.assertIn(words, html)
        self.assertIn("1st of 2", html, "the Ogun card turns the position on")

    def test_a_standard_school_still_gets_the_standard_card(self):
        self.release(self.grace)
        with connected_to(self.grace):
            html = pdf.html_for(ReleasedCard.objects.get(student_membership_id=self.ngozi.pk))
        self.assertNotIn("MINISTRY OF EDUCATION", html)
        self.assertIn("Report card", html)

    def test_it_renders(self):
        self.release()
        with connected_to(self.stmarys):
            self.assertEqual(pdf.render(self.card())[:4], b"%PDF")


class TheHealthCopyTests(OgunCardSetUp):
    """The health record is only in the copy served to its four readers."""

    MARKER = "Measles QZ4"

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            HealthRecord.objects.create(
                term_id=self.terms[TermName.FIRST.value], student_membership_id=self.ada.pk,
                height_start_m="1.40", weight_start_kg="36.0", days_absent_ill=2, illness=self.MARKER,
            )
        self.release()
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            render_card_pdf.apply(args=["st_marys", card.pk]).get()
            self.stored = ReleasedCardPdf.objects.get(card=card)

    def pdf_for(self, user):
        self.client.force_login(user)
        response = self.client.get(
            f"/api/results/cards/{self.ada.pk}/{self.terms[TermName.FIRST.value]}/pdf/", HTTP_HOST=HOST
        )
        self.assertEqual(response.status_code, 200)
        return bytes(response.content)

    def test_the_control_two_copies_are_stored_and_differ(self):
        self.assertIsNotNone(self.stored.health_content)
        self.assertNotEqual(bytes(self.stored.health_content), bytes(self.stored.content))

    def test_the_guardian_and_the_office_get_the_health_copy(self):
        for user in (self.mama, self.principal, self.staff[Role.ADMIN]):
            with self.subTest(user=user.username):
                self.assertEqual(self.pdf_for(user), bytes(self.stored.health_content))

    def test_the_class_teacher_gets_it_too(self):
        self.assertEqual(self.pdf_for(self.teacher), bytes(self.stored.health_content))

    def test_the_bursar_the_vice_principal_and_the_child_get_the_ordinary_copy(self):
        for user in (self.bursar, self.vp, self.ada.user):
            with self.subTest(user=user.username):
                self.assertEqual(self.pdf_for(user), bytes(self.stored.content))

    def test_the_ordinary_copy_is_rendered_without_the_record(self):
        """What is stored as `content` was rendered with no health record at all."""
        from unittest import mock

        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            with mock.patch("results.pdf.render", wraps=pdf.render) as render:
                render_card_pdf.apply(args=["st_marys", card.pk]).get()
        healths = [call.kwargs.get("health") for call in render.call_args_list]
        self.assertEqual(len(healths), 2)
        self.assertIsNone(healths[0], "the copy everyone is served")
        self.assertEqual(healths[1].illness, self.MARKER)

    def test_the_ordinary_copy_says_nothing_of_the_illness(self):
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            plain = pdf.html_for(card)
            with_health = pdf.html_for(card, health=HealthRecord.objects.get())
        self.assertNotIn(self.MARKER, plain)
        self.assertIn(self.MARKER, with_health)


class SetUpTests(OgunCardSetUp):
    def put(self, url, body, user=None):
        self.client.force_login(user or self.principal)
        return self.client.put(url, data=body, content_type="application/json", HTTP_HOST=HOST)

    def test_the_school_code_is_set_with_the_lga(self):
        response = self.put("/api/academics/lga/", {"lga": "Ifo", "school_code": " B 13003 "})
        self.assertEqual(response.json(), {"lga": "Ifo", "school_code": "B13003"})

    def test_a_subject_gets_a_department_and_a_teacher_cannot_set_one(self):
        url = f"/api/academics/subjects/{self.subjects['maths']}/department/"
        self.assertEqual(self.put(url, {"department": "science"}).status_code, 200)
        self.assertEqual(self.put(url, {"department": "art"}).status_code, 422)
        self.assertEqual(self.put(url, {"department": "trade"}, user=self.teacher).status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(Subject.objects.get(pk=self.subjects["maths"]).department, "science")

    def test_a_standard_school_is_not_offered_departments(self):
        self.client.force_login(self.their_principal)
        response = self.client.put(
            f"/api/academics/subjects/{self.their_subjects['maths']}/department/",
            data={"department": "science"}, content_type="application/json", HTTP_HOST="grace.testserver",
        )
        self.assertEqual(response.status_code, 409)
