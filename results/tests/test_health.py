"""A child's physical development and health. `results.health`, `health_api`.

Sensitive children's health data. **Four readers**: the child's class teacher
for the term, the principal, a school administrator, and the child's guardians
once the card has gone home. Everyone else gets a flat 404. Two schools in
every test, and a marker illness that is looked for in the raw bytes of every
other surface a family or another teacher reads.
"""

from django.db import IntegrityError, transaction

from accounts.models import Role, User
from accounts.services import grant_membership, link_guardian
from gradebook import services as gradebook
from gradebook.models import Assessment
from results import ogun, pdf
from results import services as results_services
from results.models import HealthRecord, ReleasedCard
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

MARKER = "Sickle-cell crisis QX7"

VALUES = {
    "height_start_m": "1.42",
    "height_end_m": "1.445",
    "weight_start_kg": "38.5",
    "weight_end_kg": "39",
    "days_absent_ill": "3",
    "illness": MARKER,
}


class HealthSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        self.ada = self.children["ada"]
        self.emeka = self.children["emeka"]
        self.admin = grant_membership(
            User.objects.create_user("amaka", PASSWORD, full_name="Amaka Obi"), self.stmarys, Role.ADMIN
        )
        # A teacher at the school who is not JSS 1A's class teacher.
        self.other_teacher = grant_membership(
            User.objects.create_user("tola", PASSWORD, full_name="Tola Ade"), self.stmarys, Role.TEACHER
        )
        self.mama = User.objects.create_user("mama", PASSWORD, full_name="Mama Ada")
        link_guardian(self.mama, self.ada)
        give_verified_channel(self.mama, "08030000001")
        # Another parent at the same school: Emeka's.
        self.papa = User.objects.create_user("papa", PASSWORD, full_name="Papa Emeka")
        link_guardian(self.papa, self.emeka)
        give_verified_channel(self.papa, "08030000002")
        with connected_to(self.stmarys):
            ogun.set_template_as(self.head.user, self.stmarys, "ogun")

    def url(self, child, term=None):
        tail = f"?term_id={term.pk}" if term is not None else ""
        return f"/api/results/health/{child.pk}/{tail}"

    def get(self, user, child, host=HOST, term=None):
        self.client.force_login(user)
        return self.client.get(self.url(child, term), HTTP_HOST=host)

    def put(self, user, child, host=HOST, **values):
        self.client.force_login(user)
        body = dict(VALUES)
        body.update(values)
        return self.client.put(self.url(child), data=body, content_type="application/json", HTTP_HOST=host)

    def release(self):
        with connected_to(self.stmarys):
            # The Ogun template replaced the fixture's unmarked "First CA".
            exam = Assessment.objects.get(term=self.term, subject=self.maths, name="Exam")
            gradebook.set_score(exam, self.ada, 61, by=self.teacher.user)
            sheet = results_services.open_sheet(self.jss1a, self.term, self.head.user)
            results_services.submit(sheet, self.teacher.user)
            results_services.check(sheet, self.vp.user)
            results_services.approve(sheet, self.head.user)
            results_services.release(sheet, self.head.user)


class RecordingTests(HealthSetUp):
    def test_the_control_the_class_teacher_records_and_reads_it_back(self):
        response = self.put(self.teacher.user, self.ada)

        self.assertEqual(response.status_code, 200, response.content)
        body = self.get(self.teacher.user, self.ada).json()
        self.assertEqual(
            [body[k] for k in ("height_start_m", "height_end_m", "weight_start_kg", "weight_end_kg", "days_absent_ill", "illness")],
            ["1.42", "1.45", "38.5", "39.0", 3, MARKER],
        )
        self.assertTrue(body["may_edit"] and body["printed"])

    def test_blank_clears_a_box(self):
        self.put(self.teacher.user, self.ada)
        self.put(self.teacher.user, self.ada, weight_end_kg=None, illness="")
        body = self.get(self.teacher.user, self.ada).json()
        self.assertEqual((body["weight_end_kg"], body["illness"], body["height_start_m"]), (None, "", "1.42"))

    def test_values_out_of_range_are_refused_with_a_sentence(self):
        for field, value, said in (
            ("height_start_m", "142", "metres"),
            ("weight_start_kg", "heavy", "kilograms"),
            ("days_absent_ill", "-1", "between 0"),
            ("illness", "x" * 121, "120 characters"),
        ):
            with self.subTest(field=field):
                response = self.put(self.teacher.user, self.ada, **{field: value})
                self.assertEqual(response.status_code, 422)
                self.assertIn(said, response.json()["detail"])

    def test_the_office_reads_it_and_is_told_the_class_teacher_writes_it(self):
        self.put(self.teacher.user, self.ada)
        for who in (self.head, self.admin):
            with self.subTest(who=who.user.username):
                body = self.get(who.user, self.ada).json()
                self.assertEqual((body["illness"], body["may_edit"]), (MARKER, False))
                self.assertEqual(self.put(who.user, self.ada, illness="changed").status_code, 422)
        with connected_to(self.stmarys):
            self.assertEqual(HealthRecord.objects.get().illness, MARKER)


class WhoMaySeeItTests(HealthSetUp):
    def setUp(self):
        super().setUp()
        self.put(self.teacher.user, self.ada)

    def test_another_teacher_the_vice_principal_and_the_bursar_get_a_404(self):
        for who in (self.other_teacher, self.vp, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.get(who.user, self.ada).status_code, 404)
                self.assertEqual(self.put(who.user, self.ada, illness="x").status_code, 404)
        with connected_to(self.stmarys):
            self.assertEqual(HealthRecord.objects.get().illness, MARKER)

    def test_the_class_teacher_of_another_class_sees_nothing_of_this_one(self):
        """Kemi teaches JSS 1A; Bimpe is in JSS 1B, which has no class teacher."""
        self.assertEqual(self.get(self.teacher.user, self.bimpe).status_code, 404)

    def test_the_child_herself_is_not_one_of_the_four(self):
        self.release()
        self.assertEqual(self.get(self.ada.user, self.ada, term=self.term).status_code, 404)

    def test_a_guardian_sees_it_once_the_card_has_gone_home_and_not_before(self):
        self.assertEqual(self.get(self.mama, self.ada, term=self.term).status_code, 404)
        self.release()

        response = self.get(self.mama, self.ada, term=self.term)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["illness"], MARKER)

    def test_another_parent_is_refused(self):
        self.release()
        self.assertEqual(self.get(self.papa, self.ada, term=self.term).status_code, 404)
        self.assertEqual(self.get(self.papa, self.emeka, term=self.term).status_code, 200)

    def test_the_other_schools_principal_is_refused_on_both_hosts(self):
        self.assertEqual(self.get(self.their_head.user, self.ada, host=THEIR_HOST).status_code, 404)
        self.assertEqual(self.get(self.their_head.user, self.ada).status_code, 403)

    def test_each_school_keeps_its_own(self):
        self.client.force_login(self.grace_teacher.user)
        response = self.client.put(
            self.url(self.grace_child), data=VALUES, content_type="application/json", HTTP_HOST=THEIR_HOST
        )
        self.assertEqual(response.status_code, 200, response.content)
        with connected_to(self.grace):
            self.assertEqual(HealthRecord.objects.get().student_membership_id, self.grace_child.pk)
        with connected_to(self.stmarys):
            self.assertEqual(HealthRecord.objects.get().student_membership_id, self.ada.pk)


class ItStopsWhenTheCardGoesHomeTests(HealthSetUp):
    def test_the_class_teacher_is_told_it_is_locked(self):
        self.put(self.teacher.user, self.ada)
        self.release()

        response = self.put(self.teacher.user, self.ada, illness="later")

        self.assertEqual(response.status_code, 423)
        body = self.get(self.teacher.user, self.ada).json()
        self.assertEqual((body["illness"], body["locked"], body["may_edit"]), (MARKER, True, False))

    def test_the_database_refuses_a_change_after_release(self):
        self.put(self.teacher.user, self.ada)
        self.release()
        with connected_to(self.stmarys):
            self.assertTrue(ReleasedCard.objects.filter(student_membership_id=self.ada.pk).exists())
            row = HealthRecord.objects.get()
            for act in ("update", "delete", "insert"):
                with self.subTest(act=act), self.assertRaisesMessage(IntegrityError, "its health record is part of it"):
                    with transaction.atomic():
                        if act == "update":
                            HealthRecord.objects.filter(pk=row.pk).update(illness="changed")
                        elif act == "delete":
                            HealthRecord.objects.filter(pk=row.pk).delete()
                        else:
                            HealthRecord.objects.create(term=self.term, student_membership_id=self.emeka.pk)


class NowhereElseTests(HealthSetUp):
    """The marker illness, looked for in the raw bytes of every other surface."""

    def setUp(self):
        super().setUp()
        self.put(self.teacher.user, self.ada)
        self.release()

    def test_the_control_the_marker_is_there_to_be_found(self):
        self.assertIn(MARKER, self.get(self.head.user, self.ada).content.decode())

    def test_not_in_the_card_any_reader_is_served(self):
        self.client.force_login(self.mama)
        response = self.client.get(f"/api/results/cards/{self.ada.pk}/{self.term.pk}/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn(MARKER, response.content.decode())
        self.assertNotIn("illness", response.content.decode())

    def test_not_in_the_stored_pdf(self):
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            self.assertNotIn(MARKER, pdf.html_for(card))

    def test_not_in_the_broadsheet(self):
        self.client.force_login(self.head.user)
        response = self.client.get(f"/api/results/classes/{self.jss1a.pk}/broadsheet/?term_id={self.term.pk}", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn(MARKER, response.content.decode())

    def test_not_in_the_comments_class_list_or_child_any_teacher_reads(self):
        self.client.force_login(self.other_teacher.user)
        for url in (f"/api/results/comments/?class_group_id={self.jss1a.pk}", f"/api/results/comments/{self.ada.pk}/"):
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HOST=HOST)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertNotIn(MARKER, response.content.decode())
