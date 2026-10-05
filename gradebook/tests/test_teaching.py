"""The office's teaching setup over HTTP: `/api/teaching/`.

Subjects, this term's papers and class teachers were models with no writer, so a real school
could not start a term. These tests hold the routes' three promises:

- **Only the office opens them.** A principal and an administrator may; a vice principal, a
  teacher, a bursar, a parent and a child may not, on the page's read and on every write, and a
  refused write changes nothing.
- **The school's own rules hold.** A paper's total cannot move under marks; a subject that has
  been taught is retired, not removed; a duplicate is a sentence, not a 500.
- **One school's setup is never another's.** Ids repeat across schools (both start at 1), so
  every lookup is by the school the request arrived at.
"""

from datetime import date

from django.test import TestCase

from academics.models import ClassGroup, ClassTeacher, Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from gradebook import services
from gradebook.models import Assessment, Score, Subject
from gradebook.tests.test_api import HOST, GradebookApiSetUp
from gradebook.tests.test_scores import PASSWORD
from schools.models import Domain
from schools.tests.tenants import connected_to, make_school

THEIR_HOST = "grace.testserver"
BASE = "/api/teaching/"


class TeachingSetUp(GradebookApiSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=True)
        self.head = self.staff("head", Role.PRINCIPAL)
        self.admin = self.staff("ade", Role.ADMIN)
        self.vp = self.staff("ify", Role.VICE_PRINCIPAL_ACADEMIC)
        self.bursar = self.staff("bola", Role.BURSAR)

    def staff(self, username, role, school=None):
        return grant_membership(
            User.objects.create_user(username, PASSWORD, full_name=username.title()),
            school or self.stmarys,
            role,
        )

    def call(self, method, path, who, host=HOST, **body):
        self.client.force_login(who.user)
        kwargs = {"HTTP_HOST": host}
        if body:
            kwargs.update(data=body, content_type="application/json")
        return getattr(self.client, method)(f"{BASE}{path}", **kwargs)

    def overview(self, who=None, host=HOST):
        return self.call("get", "", who or self.head, host=host)

    def subject_named(self, name):
        with connected_to(self.stmarys):
            return Subject.objects.get(name=name)


class WhoMayOpenIt(TeachingSetUp):
    def test_the_principal_and_the_administrator_open_it(self):
        for who in (self.head, self.admin):
            with self.subTest(who=who.user.username):
                response = self.overview(who)
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual([s["name"] for s in body["subjects"]], ["Mathematics"])
                self.assertEqual([c["name"] for c in body["classes"]], ["JSS 1A"])
                self.assertEqual([t["name"] for t in body["teachers"]], ["Kemi Bello", "Tunde Ade"])

    def test_nobody_else_at_the_school_does(self):
        for who in (self.vp, self.teacher, self.other_teacher, self.bursar, self.parent, self.ada):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.overview(who).status_code, 403)

    def test_every_write_is_refused_the_same_way_and_changes_nothing(self):
        routes = [
            ("post", "subjects/", {"name": "Civic", "code": "CVC"}),
            ("put", f"subjects/{self.maths_id}/", {"name": "Maths", "code": "MTH", "is_active": True}),
            ("delete", f"subjects/{self.maths_id}/", {}),
            ("post", f"subjects/{self.maths_id}/papers/", {"name": "Exam", "max_score": 60}),
            ("put", f"papers/{self.first_ca_id}/", {"name": "Test", "max_score": 20}),
            ("delete", f"papers/{self.first_ca_id}/", {}),
            ("put", f"classes/{self.jss1a_id}/teacher/", {"membership_id": self.teacher.pk}),
            ("delete", f"classes/{self.jss1a_id}/teacher/", {}),
        ]
        for who in (self.vp, self.teacher, self.bursar, self.parent, self.ada):
            for method, path, body in routes:
                with self.subTest(who=who.user.username, route=f"{method} {path}"):
                    self.assertEqual(self.call(method, path, who, **body).status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(list(Subject.objects.values_list("name", flat=True)), ["Mathematics"])
            self.assertEqual(list(Assessment.objects.values_list("name", flat=True)), ["First CA"])
            self.assertFalse(ClassTeacher.objects.exists())

    def test_a_refusal_does_not_say_whether_the_subject_exists(self):
        real = self.call("delete", f"subjects/{self.maths_id}/", self.teacher)
        invented = self.call("delete", "subjects/999999/", self.teacher)
        self.assertEqual((real.status_code, invented.status_code), (403, 403))
        self.assertEqual(real.json(), invented.json())

    def test_signed_out_is_not_a_page_and_the_portal_has_no_school(self):
        self.client.logout()
        self.assertEqual(self.client.get(BASE, HTTP_HOST=HOST).status_code, 401)
        self.assertEqual(self.overview(self.head, host="testserver").status_code, 404)


class Subjects(TeachingSetUp):
    def test_adding_a_subject_answers_with_the_new_overview(self):
        response = self.call("post", "subjects/", self.head, name="  Civic   Education ", code=" cvc ")
        self.assertEqual(response.status_code, 200)
        added = next(s for s in response.json()["subjects"] if s["code"] == "CVC")
        self.assertEqual((added["name"], added["is_active"], added["papers"]), ("Civic Education", True, []))

    def test_a_name_or_code_already_used_is_a_sentence(self):
        for body, needle in (
            ({"name": "mathematics", "code": "MX"}, "already a subject"),
            ({"name": "Maths", "code": "mth"}, "code MTH is already used"),
            ({"name": "", "code": "X"}, "needs a name"),
            ({"name": "Art", "code": ""}, "short code"),
            ({"name": "A" * 101, "code": "A"}, "at most 100"),
        ):
            with self.subTest(body=body):
                response = self.call("post", "subjects/", self.head, **body)
                self.assertEqual(response.status_code, 422)
                self.assertIn(needle, response.json()["detail"])

    def test_renaming_and_retiring_keep_the_subject(self):
        response = self.call("put", f"subjects/{self.maths_id}/", self.admin, name="Maths", code="MTH", is_active=False)
        self.assertEqual(response.status_code, 200)
        row = response.json()["subjects"][0]
        self.assertEqual((row["name"], row["is_active"]), ("Maths", False))
        self.assertEqual(len(row["papers"]), 1, "its papers are still its own")

    def test_a_subject_that_has_papers_is_retired_not_removed(self):
        response = self.call("delete", f"subjects/{self.maths_id}/", self.head)
        self.assertEqual(response.status_code, 422)
        self.assertIn("Mark it as no longer taught", response.json()["detail"])
        with connected_to(self.stmarys):
            self.assertTrue(Subject.objects.filter(pk=self.maths_id).exists())

    def test_a_subject_with_no_papers_can_go(self):
        self.call("post", "subjects/", self.head, name="Civic", code="CVC")
        civic = self.subject_named("Civic")
        response = self.call("delete", f"subjects/{civic.pk}/", self.head)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["name"] for s in response.json()["subjects"]], ["Mathematics"])

    def test_a_subject_that_only_an_earlier_term_used_still_cannot_go(self):
        with connected_to(self.stmarys):
            old = Term.objects.create(
                session="2024/2025", name=TermName.THIRD, starts_on=date(2025, 5, 1), ends_on=date(2025, 7, 25)
            )
            civic = Subject.objects.create(name="Civic", code="CVC")
            Assessment.objects.create(term=old, subject=civic, name="Exam", max_score=60)
        self.assertEqual(self.call("delete", f"subjects/{civic.pk}/", self.head).status_code, 422)


class Papers(TeachingSetUp):
    def papers(self, response):
        return {p["name"]: p for p in response.json()["subjects"][0]["papers"]}

    def test_a_paper_is_added_to_the_current_term_after_the_others(self):
        response = self.call("post", f"subjects/{self.maths_id}/papers/", self.head, name="Exam", max_score=60)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.papers(response)), ["First CA", "Exam"])
        with connected_to(self.stmarys):
            exam = Assessment.objects.get(name="Exam")
            self.assertEqual((exam.term_id, exam.max_score), (self.term_id, 60))
            self.assertGreater(exam.position, Assessment.objects.get(name="First CA").position)

    def test_no_current_term_is_a_sentence_not_a_paper(self):
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)
        response = self.call("post", f"subjects/{self.maths_id}/papers/", self.head, name="Exam", max_score=60)
        self.assertEqual(response.status_code, 422)
        self.assertIn("No term is open", response.json()["detail"])

    def test_a_bad_total_or_a_repeated_name_is_a_sentence(self):
        for body, needle in (
            ({"name": "first ca", "max_score": 20}, "already has a paper"),
            ({"name": "Exam", "max_score": 0}, "at least 1"),
            ({"name": "Exam", "max_score": 5000}, "at most 1000"),
            ({"name": " ", "max_score": 20}, "needs a name"),
        ):
            with self.subTest(body=body):
                response = self.call("post", f"subjects/{self.maths_id}/papers/", self.head, **body)
                self.assertEqual(response.status_code, 422)
                self.assertIn(needle, response.json()["detail"])

    def test_before_any_mark_a_paper_can_be_changed_and_removed(self):
        response = self.call("put", f"papers/{self.first_ca_id}/", self.head, name="Test 1", max_score=30)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.papers(response)["Test 1"]["max_score"], 30)
        self.assertFalse(self.papers(response)["Test 1"]["has_marks"])
        gone = self.call("delete", f"papers/{self.first_ca_id}/", self.head)
        self.assertEqual((gone.status_code, gone.json()["subjects"][0]["papers"]), (200, []))

    def test_with_marks_it_can_be_renamed_but_not_re_totalled_or_removed(self):
        with connected_to(self.stmarys):
            services.set_score(Assessment.objects.get(pk=self.first_ca_id), self.ada, 15)

        renamed = self.call("put", f"papers/{self.first_ca_id}/", self.head, name="Test 1", max_score=20)
        self.assertEqual(renamed.status_code, 200)
        self.assertTrue(self.papers(renamed)["Test 1"]["has_marks"])
        retotalled = self.call("put", f"papers/{self.first_ca_id}/", self.head, name="Test 1", max_score=10)
        self.assertEqual(retotalled.status_code, 422)
        self.assertIn("already has marks", retotalled.json()["detail"])
        removed = self.call("delete", f"papers/{self.first_ca_id}/", self.head)
        self.assertEqual(removed.status_code, 422)
        with connected_to(self.stmarys):
            paper = Assessment.objects.get(pk=self.first_ca_id)
            self.assertEqual((paper.name, paper.max_score, Score.objects.count()), ("Test 1", 20, 1))

    def test_a_paper_that_is_not_there_is_a_404_for_the_office(self):
        self.assertEqual(self.call("put", "papers/999999/", self.head, name="x", max_score=1).status_code, 404)
        self.assertEqual(self.call("delete", "subjects/999999/", self.head).status_code, 404)


class ClassTeachers(TeachingSetUp):
    def teacher_of(self, response):
        return response.json()["classes"][0]["class_teacher_id"]

    def test_a_class_teacher_is_set_changed_and_cleared(self):
        path = f"classes/{self.jss1a_id}/teacher/"
        self.assertIsNone(self.teacher_of(self.overview()))
        self.assertEqual(self.teacher_of(self.call("put", path, self.head, membership_id=self.teacher.pk)), self.teacher.pk)
        self.assertEqual(
            self.teacher_of(self.call("put", path, self.admin, membership_id=self.other_teacher.pk)),
            self.other_teacher.pk,
        )
        with connected_to(self.stmarys):
            self.assertEqual(ClassTeacher.objects.count(), 1, "changing is an update, not a second row")
        self.assertIsNone(self.teacher_of(self.call("delete", path, self.head)))
        self.assertEqual(self.call("delete", path, self.head).status_code, 200, "clearing none is fine")

    def test_only_a_teacher_of_this_school_can_be_chosen(self):
        path = f"classes/{self.jss1a_id}/teacher/"
        for who in (self.bursar, self.parent, self.ada, self.head):
            with self.subTest(chosen=who.user.username):
                response = self.call("put", path, self.head, membership_id=who.pk)
                self.assertEqual(response.status_code, 422)
                self.assertIn("one of this school's teachers", response.json()["detail"])
        self.assertEqual(self.call("put", path, self.head, membership_id=999999).status_code, 422)
        with connected_to(self.stmarys):
            self.assertFalse(ClassTeacher.objects.exists())

    def test_no_current_term_is_a_sentence(self):
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)
        response = self.call("put", f"classes/{self.jss1a_id}/teacher/", self.head, membership_id=self.teacher.pk)
        self.assertEqual(response.status_code, 422)
        self.assertIn("No term is open", response.json()["detail"])

    def test_the_assigned_teacher_can_then_submit_the_class(self):
        """The point of the screen: `results` asks `is_class_teacher()`, and this is what answers it."""
        from academics import services as academics

        self.call("put", f"classes/{self.jss1a_id}/teacher/", self.head, membership_id=self.teacher.pk)
        with connected_to(self.stmarys):
            group = ClassGroup.objects.get(pk=self.jss1a_id)
            term = Term.objects.get(pk=self.term_id)
            self.assertTrue(academics.is_class_teacher(self.teacher.pk, group, term))
            self.assertFalse(academics.is_class_teacher(self.other_teacher.pk, group, term))


class OneSchoolIsNotAnother(TeachingSetUp):
    """Both schools' first subject, paper and class have the same id. Nothing may cross."""

    def setUp(self):
        super().setUp()
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.grace, domain=THEIR_HOST, is_primary=True)
        self.their_head = self.staff("gloria", Role.PRINCIPAL, self.grace)
        self.their_teacher = self.staff("chidi", Role.TEACHER, self.grace)
        with connected_to(self.grace):
            term = Term.objects.create(
                session="2025/2026", name=TermName.FIRST, starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12), is_current=True,
            )
            self.their_subject = Subject.objects.create(name="Biology", code="BIO")
            self.their_paper = Assessment.objects.create(term=term, subject=self.their_subject, name="Exam", max_score=70)
            self.their_group = ClassGroup.objects.create(name="SS 1", level=4)

    def test_each_school_sees_only_its_own_setup(self):
        ours = self.overview(self.head).json()
        theirs = self.overview(self.their_head, host=THEIR_HOST).json()
        self.assertEqual([s["name"] for s in ours["subjects"]], ["Mathematics"])
        self.assertEqual([s["name"] for s in theirs["subjects"]], ["Biology"])
        self.assertEqual([c["name"] for c in theirs["classes"]], ["SS 1"])
        self.assertEqual([t["name"] for t in theirs["teachers"]], ["Chidi"])
        self.assertNotIn("Kemi", str(theirs))

    def test_the_other_schools_principal_is_refused_here(self):
        self.assertEqual(self.overview(self.their_head, host=HOST).status_code, 403)
        refused = self.call("put", f"subjects/{self.maths_id}/", self.their_head, name="Hacked", code="HAK", is_active=True)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.subject_named("Mathematics").code, "MTH")

    def test_a_write_by_id_lands_in_the_school_the_request_came_to(self):
        self.assertEqual(self.their_subject.pk, self.maths_id, "the ids repeat across the two schools")
        self.call("put", f"subjects/{self.their_subject.pk}/", self.their_head, host=THEIR_HOST,
                  name="Life Science", code="LSC", is_active=True)
        self.call("delete", f"papers/{self.their_paper.pk}/", self.their_head, host=THEIR_HOST)
        self.assertEqual(self.subject_named("Mathematics").code, "MTH")
        with connected_to(self.stmarys):
            self.assertTrue(Assessment.objects.filter(pk=self.first_ca_id).exists(), "St Mary's paper stands")
        with connected_to(self.grace):
            self.assertEqual(Subject.objects.get().name, "Life Science")
            self.assertFalse(Assessment.objects.exists())

    def test_another_schools_teacher_cannot_be_made_class_teacher_here(self):
        response = self.call(
            "put", f"classes/{self.jss1a_id}/teacher/", self.head, membership_id=self.their_teacher.pk
        )
        self.assertEqual(response.status_code, 422)
        with connected_to(self.stmarys):
            self.assertFalse(ClassTeacher.objects.exists())
        response = self.call(
            "put", f"classes/{self.their_group.pk}/teacher/", self.their_head, host=THEIR_HOST,
            membership_id=self.teacher.pk,
        )
        self.assertEqual(response.status_code, 422, "and ours cannot be made theirs")
        with connected_to(self.grace):
            self.assertFalse(ClassTeacher.objects.exists())
