"""Who teaches what, and what it does to marking: `docs/subject-teachers.md`.

Two schools in every class, on their own hosts (`results.tests.fixtures.ChainSetUp`).
The claims, each with a control in the doc:

- **Until the term has an assignment, nothing changes.** Any teacher sees and marks
  every paper and class, as before.
- **From the first one, a teacher marks only their own pairs**, and the server refuses
  the rest: the sheet, a save and a clear, not only the list on the page.
- **And it stays that way.** Taking the last one away opens nothing; only the
  principal's switch opens the term to every teacher, and the switch is the principal's
  alone, written down with who and when.
- **A new term starts with the last one's assignments**, copied by the system from this
  school's own rows only, leaving out a teacher who has gone. With none to copy, nothing
  changes.
- **The principal, the vice principal and the administrator are never narrowed.**
- **Only the principal changes assignments**; the vice principal and the administrator
  read them; nobody else opens them. A refused write changes nothing.
- **Every change is written down, who and when**, in a table that cannot be edited.
- **One school's assignments and teachers are never another's.** Ids repeat across the
  two schools, so every lookup is by the school the request arrived at.
- **Released results are never affected.**
"""

from django.db import connection, transaction

from academics import services as academics
from academics.models import Term, TermName
from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import grant_membership
from attendance.tests.fixtures import a_term
from gradebook import assignments
from gradebook.models import (
    Assessment,
    Score,
    Subject,
    SubjectTeacher,
    SubjectTeacherCarry,
    SubjectTeacherChange,
)
from gradebook.services import set_score
from results import services as chain
from results.models import ReleasedAssessmentScore, ReleasedCard
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to
from tests.refusals import RefusalAssertions

BASE = "/api/subject-teachers/"


class SubjectTeachersSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )
        self.tayo = grant_membership(
            User.objects.create_user("tayo", PASSWORD, full_name="Tayo Ojo"), self.stmarys, Role.TEACHER
        )
        with connected_to(self.stmarys):
            self.english = Subject.objects.create(name="English", code="ENG")
            self.english_ca = Assessment.objects.create(
                term=self.term, subject=self.english, name="First CA", max_score=20
            )
            self.english_id = self.english.pk
            self.english_ca_id = self.english_ca.pk
        with connected_to(self.grace):
            self.grace_maths_id = Assessment.objects.get(pk=self.grace_ca_id).subject_id

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    # -- HTTP -----------------------------------------------------------------

    def as_(self, who):
        self.client.force_login(who.user)
        return self.client

    def overview(self, who, host=HOST):
        return self.as_(who).get(BASE, HTTP_HOST=host)

    def assign(self, who, group_id, subject_id, membership, host=HOST):
        return self.as_(who).post(
            BASE,
            data={"class_group_id": group_id, "subject_id": subject_id, "membership_id": membership.pk},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def unassign(self, who, row_id, host=HOST):
        return self.as_(who).delete(f"{BASE}{row_id}/", HTTP_HOST=host)

    def switch(self, who, open_to_all, host=HOST):
        return self.as_(who).put(
            f"{BASE}marking/", data={"open": open_to_all}, content_type="application/json", HTTP_HOST=host
        )

    def make_current(self, who, term_id, host=HOST):
        response = self.as_(who).put(f"/api/academics/terms/{term_id}/current/", HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def where(self, who, host=HOST):
        return self.as_(who).get("/api/gradebook/where/", HTTP_HOST=host)

    def sheet(self, who, assessment_id, group_id, host=HOST):
        return self.as_(who).get(
            f"/api/gradebook/assessments/{assessment_id}/sheet/?class_group_id={group_id}", HTTP_HOST=host
        )

    def save(self, who, assessment_id, student, value=15, host=HOST, expected_version=None):
        return self.as_(who).put(
            f"/api/gradebook/assessments/{assessment_id}/scores/{student.pk}/",
            data={"value": value, "expected_version": expected_version},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def clear(self, who, assessment_id, student, expected_version, host=HOST):
        return self.as_(who).delete(
            f"/api/gradebook/assessments/{assessment_id}/scores/{student.pk}/?expected_version={expected_version}",
            HTTP_HOST=host,
        )

    # -- reading the tables ------------------------------------------------------

    def score(self, assessment_id, student, school=None):
        with connected_to(school or self.stmarys):
            return Score.objects.filter(assessment_id=assessment_id, student_membership_id=student.pk).first()

    def rows(self, school=None):
        with connected_to(school or self.stmarys):
            return list(
                SubjectTeacher.objects.values_list("class_group_id", "subject_id", "teacher_membership_id")
            )

    def changes(self, school=None):
        with connected_to(school or self.stmarys):
            return list(SubjectTeacherChange.objects.order_by("id"))

    def give_kemi_maths_in_jss1a(self):
        response = self.assign(self.head, self.jss1a_id, self.maths_id, self.teacher)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class UntilTheTermHasAnAssignmentNothingChangesTests(SubjectTeachersSetUp):
    def test_a_teacher_is_sent_every_paper_and_every_class(self):
        body = self.where(self.teacher).json()

        self.assertFalse(body["narrowed"])
        self.assertEqual(body["pairs"], [])
        self.assertEqual(sorted(a["id"] for a in body["assessments"]), sorted([self.first_ca_id, self.english_ca_id]))
        self.assertTrue(all(a["class_group_id"] is None for a in body["assessments"]))
        self.assertEqual(sorted(g["id"] for g in body["classes"]), sorted([self.jss1a_id, self.jss1b_id]))

    def test_a_teacher_opens_and_marks_any_subject_in_any_class(self):
        ada, bimpe = self.children["ada"], self.bimpe

        self.assertEqual(self.sheet(self.teacher, self.english_ca_id, self.jss1b_id).status_code, 200)
        self.assertEqual(self.save(self.teacher, self.english_ca_id, ada).status_code, 200)
        self.assertEqual(self.save(self.tayo, self.first_ca_id, bimpe).status_code, 200)
        self.assertEqual(self.score(self.english_ca_id, ada).value, 15)
        self.assertEqual(self.score(self.first_ca_id, bimpe).value, 15)

    def test_and_clears_any(self):
        saved = self.save(self.teacher, self.english_ca_id, self.bimpe).json()

        response = self.clear(self.tayo, self.english_ca_id, self.bimpe, saved["version"])

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.score(self.english_ca_id, self.bimpe))



class ATeacherMarksOnlyTheirOwnPairsTests(SubjectTeachersSetUp):
    def setUp(self):
        super().setUp()
        self.give_kemi_maths_in_jss1a()

    def test_their_page_is_sent_only_their_paper_and_class(self):
        body = self.where(self.teacher).json()

        self.assertTrue(body["narrowed"])
        self.assertEqual(body["pairs"], [{"subject_id": self.maths_id, "class_group_id": self.jss1a_id}])
        # One entry per paper and class, naming the class, and no class list to mix it with.
        self.assertEqual(
            [(a["id"], a["class_group_id"], a["class_group"]) for a in body["assessments"]],
            [(self.first_ca_id, self.jss1a_id, "JSS 1A")],
        )
        self.assertEqual(body["classes"], [])

    def test_their_own_sheet_opens(self):
        self.assertEqual(self.sheet(self.teacher, self.first_ca_id, self.jss1a_id).status_code, 200)

    def test_another_subject_or_another_class_is_refused_on_the_server(self):
        for assessment_id, group_id in ((self.english_ca_id, self.jss1a_id), (self.first_ca_id, self.jss1b_id)):
            with self.subTest(assessment=assessment_id, group=group_id):
                response = self.sheet(self.teacher, assessment_id, group_id)
                self.assertEqual(response.status_code, 403)
                self.assertIn("not down to teach", response.json()["detail"])

    def test_a_mark_in_their_own_pair_is_saved(self):
        self.assertEqual(self.save(self.teacher, self.first_ca_id, self.children["ada"]).status_code, 200)
        self.assertEqual(self.score(self.first_ca_id, self.children["ada"]).value, 15)

    def test_a_mark_in_another_subject_is_refused_and_nothing_is_written(self):
        response = self.save(self.teacher, self.english_ca_id, self.children["ada"])

        self.assertEqual(response.status_code, 403)
        self.assertIn("not down to teach English", response.json()["detail"])
        self.assertIsNone(self.score(self.english_ca_id, self.children["ada"]))

    def test_a_mark_for_a_child_in_another_class_is_refused_and_nothing_is_written(self):
        response = self.save(self.teacher, self.first_ca_id, self.bimpe)

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.score(self.first_ca_id, self.bimpe))

    def test_clearing_a_mark_outside_their_pairs_is_refused_and_the_mark_stays(self):
        saved = self.save(self.head, self.english_ca_id, self.children["ada"]).json()

        response = self.clear(self.teacher, self.english_ca_id, self.children["ada"], saved["version"])

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.score(self.english_ca_id, self.children["ada"]).value, 15)

    def test_a_teacher_given_nothing_marks_nothing(self):
        body = self.where(self.tayo).json()

        self.assertTrue(body["narrowed"])
        self.assertEqual((body["assessments"], body["classes"], body["pairs"]), ([], [], []))
        self.assertEqual(self.sheet(self.tayo, self.first_ca_id, self.jss1a_id).status_code, 403)
        self.assertEqual(self.save(self.tayo, self.first_ca_id, self.children["ada"]).status_code, 403)
        self.assertIsNone(self.score(self.first_ca_id, self.children["ada"]))

    def test_a_pair_can_have_two_teachers(self):
        self.assertEqual(self.assign(self.head, self.jss1a_id, self.maths_id, self.tayo).status_code, 200)

        self.assertEqual(self.save(self.tayo, self.first_ca_id, self.children["ada"]).status_code, 200)
        self.assertEqual(self.save(self.teacher, self.first_ca_id, self.children["emeka"]).status_code, 200)

    def test_a_teacher_can_have_many_pairs(self):
        self.assign(self.head, self.jss1b_id, self.english_id, self.teacher)

        body = self.where(self.teacher).json()

        self.assertEqual(
            sorted((p["subject_id"], p["class_group_id"]) for p in body["pairs"]),
            sorted([(self.maths_id, self.jss1a_id), (self.english_id, self.jss1b_id)]),
        )
        # Maths in JSS 1A and English in JSS 1B, never Maths in JSS 1B.
        self.assertEqual(
            sorted((a["id"], a["class_group_id"]) for a in body["assessments"]),
            sorted([(self.first_ca_id, self.jss1a_id), (self.english_ca_id, self.jss1b_id)]),
        )
        self.assertEqual(self.save(self.teacher, self.english_ca_id, self.bimpe).status_code, 200)

    def test_a_paper_is_judged_by_its_own_terms_assignments(self):
        """Kemi holds only Maths in JSS 1A in the first term. The second term has no
        assignment, so its English paper is open to her, as before."""
        with connected_to(self.stmarys):
            second = Term.objects.get(name=TermName.SECOND)
            later = Assessment.objects.create(term=second, subject=self.english, name="Second CA", max_score=20)
            from academics import services as academics

            academics.place_student(self.jss1a, second, self.children["ada"])

        self.assertEqual(self.save(self.teacher, later.pk, self.children["ada"]).status_code, 200)


class ThePrincipalTheViceAndTheAdministratorAreNeverNarrowedTests(SubjectTeachersSetUp):
    def setUp(self):
        super().setUp()
        self.give_kemi_maths_in_jss1a()

    def test_the_principal_and_the_administrator_see_and_mark_everything(self):
        for who in (self.head, self.admin):
            with self.subTest(who=who.user.username):
                body = self.where(who).json()
                self.assertFalse(body["narrowed"])
                self.assertEqual(len(body["assessments"]), 2)
                self.assertEqual(len(body["classes"]), 2)
                self.assertEqual(self.sheet(who, self.english_ca_id, self.jss1b_id).status_code, 200)
                self.assertEqual(self.save(who, self.english_ca_id, self.bimpe).status_code, 200)
                with connected_to(self.stmarys):
                    Score.objects.all().delete()

    def test_a_vice_principal_who_teaches_marks_everything(self):
        both = grant_membership(self.vp.user, self.stmarys, Role.TEACHER)

        self.assertFalse(self.where(both).json()["narrowed"])
        self.assertEqual(self.save(both, self.english_ca_id, self.bimpe).status_code, 200)

    def test_a_vice_principal_alone_still_does_not_mark(self):
        """No new access: the vice principal has no marking role of their own."""
        self.assertEqual(self.where(self.vp).status_code, 403)
        self.assertEqual(self.save(self.vp, self.first_ca_id, self.children["ada"]).status_code, 403)


class WhoMayOpenAndChangeThemTests(SubjectTeachersSetUp):
    def test_the_principal_the_vice_and_the_administrator_read_them(self):
        for who in (self.head, self.vp, self.admin):
            with self.subTest(who=who.user.username):
                response = self.overview(who)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["may_change"], who is self.head)

    def test_nobody_else_reads_them(self):
        for who in (self.teacher, self.bursar, self.children["ada"]):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.overview(who).status_code, 403)

    def test_only_the_principal_changes_them(self):
        body = self.give_kemi_maths_in_jss1a()
        row_id = body["assignments"][0]["id"]
        before = (self.rows(), len(self.changes()))

        for who in (self.vp, self.admin, self.teacher, self.bursar, self.children["ada"]):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.assign(who, self.jss1b_id, self.english_id, self.tayo).status_code, 403)
                self.assertEqual(self.unassign(who, row_id).status_code, 403)
                self.assertEqual((self.rows(), len(self.changes())), before)

    def test_the_refusal_is_the_same_whether_or_not_the_row_exists(self):
        """The oracle rule: authority is asked before anything is looked up."""
        for row_id in (1, 999):
            with self.subTest(row=row_id):
                self.assertEqual(self.unassign(self.admin, row_id).json(), {"detail": "Who teaches what is set by the principal."})


class EveryChangeIsWrittenDownTests(RefusalAssertions, SubjectTeachersSetUp):
    def test_adding_and_removing_each_write_who_and_when(self):
        body = self.give_kemi_maths_in_jss1a()
        self.unassign(self.head, body["assignments"][0]["id"])

        added, removed = self.changes()
        for change, kind in ((added, "added"), (removed, "removed")):
            with self.subTest(kind=kind):
                self.assertEqual(change.kind, kind)
                self.assertEqual(change.by_id, self.head.user.pk)
                self.assertEqual(change.by_name, "Ngozi Eze")
                self.assertIsNotNone(change.at)
                self.assertEqual(
                    (change.teacher_name, change.subject_name, change.class_group_name),
                    ("Kemi Bello", "Mathematics", "JSS 1A"),
                )
        self.assertLessEqual(added.at, removed.at)

    def test_the_page_lists_them_newest_first(self):
        body = self.give_kemi_maths_in_jss1a()
        body = self.unassign(self.head, body["assignments"][0]["id"]).json()

        self.assertEqual([c["kind"] for c in body["changes"]], ["removed", "added"])
        self.assertEqual(body["changes"][0]["by"], "Ngozi Eze")

    def test_the_record_cannot_be_edited_or_deleted(self):
        self.give_kemi_maths_in_jss1a()
        with connected_to(self.stmarys):
            with self.assertRefusedBy("gradebook_subjectteacherchange is append-only; UPDATE"):
                with transaction.atomic():
                    SubjectTeacherChange.objects.update(by_name="Somebody else")
            with self.assertRefusedBy("gradebook_subjectteacherchange is append-only; DELETE"):
                with transaction.atomic():
                    SubjectTeacherChange.objects.all().delete()

    def test_a_refused_assignment_writes_nothing(self):
        self.give_kemi_maths_in_jss1a()

        response = self.assign(self.head, self.jss1a_id, self.maths_id, self.teacher)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Kemi Bello already teaches Mathematics to JSS 1A.")
        self.assertEqual(len(self.changes()), 1)


class TheSchoolsOwnRulesTests(SubjectTeachersSetUp):
    def test_a_subject_no_longer_taught_cannot_be_given(self):
        with connected_to(self.stmarys):
            Subject.objects.filter(pk=self.english_id).update(is_active=False)

        response = self.assign(self.head, self.jss1a_id, self.english_id, self.teacher)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.rows(), [])

    def test_with_no_current_term_nothing_can_be_given(self):
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)

        response = self.assign(self.head, self.jss1a_id, self.maths_id, self.teacher)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.rows(), [])

    def test_only_a_teacher_can_be_given_a_subject(self):
        response = self.assign(self.head, self.jss1a_id, self.maths_id, self.bursar)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.rows(), [])


class OneSchoolIsNeverAnothersTests(SubjectTeachersSetUp):
    def test_the_premise_both_schools_number_their_rows_alike(self):
        self.assertEqual(
            (self.first_ca_id, self.maths_id, self.jss1a_id),
            (self.grace_ca_id, self.grace_maths_id, self.grace_group_id),
        )

    def test_a_teacher_at_one_school_cannot_see_or_mark_the_other(self):
        self.give_kemi_maths_in_jss1a()

        self.assertEqual(self.where(self.teacher, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.sheet(self.teacher, self.grace_ca_id, self.grace_group_id, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.save(self.teacher, self.grace_ca_id, self.grace_child, host=THEIR_HOST).status_code, 403)
        self.assertIsNone(self.score(self.grace_ca_id, self.grace_child, school=self.grace))

    def test_the_other_schools_assignments_do_not_narrow_this_one(self):
        response = self.assign(self.their_head, self.grace_group_id, self.grace_maths_id, self.grace_teacher, host=THEIR_HOST)
        self.assertEqual(response.status_code, 200, response.content)

        self.assertFalse(self.where(self.teacher).json()["narrowed"])
        self.assertTrue(self.where(self.grace_teacher, host=THEIR_HOST).json()["narrowed"])
        self.assertEqual(self.save(self.teacher, self.english_ca_id, self.children["ada"]).status_code, 200)

    def test_an_assignment_here_gives_nothing_there(self):
        """Kemi's St Mary's Maths pair shares its ids with Grace's, and Grace has
        assignments of its own: a teacher there holding nothing still marks nothing."""
        self.give_kemi_maths_in_jss1a()
        self.assign(self.their_head, self.grace_group_id, self.grace_maths_id, self.grace_teacher, host=THEIR_HOST)
        newcomer = grant_membership(
            User.objects.create_user("obi", PASSWORD, full_name="Obi Grace"), self.grace, Role.TEACHER
        )

        self.assertEqual(self.save(newcomer, self.grace_ca_id, self.grace_child, host=THEIR_HOST).status_code, 403)

    def test_the_principal_cannot_give_a_subject_to_the_other_schools_teacher(self):
        response = self.assign(self.head, self.jss1a_id, self.maths_id, self.grace_teacher)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "That is not one of this school's teachers.")
        self.assertEqual(self.rows(), [])

    def test_the_principal_of_one_school_is_nobody_at_the_other(self):
        self.assertEqual(self.overview(self.head, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.assign(self.head, self.grace_group_id, self.grace_maths_id, self.grace_teacher, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.rows(school=self.grace), [])

    def test_each_page_lists_its_own_schools_assignments(self):
        self.give_kemi_maths_in_jss1a()

        theirs = self.overview(self.their_head, host=THEIR_HOST).json()

        self.assertEqual(theirs["assignments"], [])
        self.assertEqual(theirs["changes"], [])
        self.assertFalse(theirs["in_force"])


class ReleasedResultsAreNeverAffectedTests(SubjectTeachersSetUp):
    def test_assignments_change_nothing_on_a_released_card_and_open_nothing(self):
        ada = self.children["ada"]
        with connected_to(self.stmarys):
            set_score(self.first_ca, ada, 17, by=self.teacher.user)
            term = Term.objects.get(pk=self.term_id)
            sheet = chain.open_sheet(self.jss1a, term, self.head.user)
            chain.submit(sheet, self.teacher.user)
            chain.check(sheet, self.vp.user)
            chain.approve(sheet, self.head.user)
            chain.release(sheet, self.head.user)
            frozen = sorted(ReleasedAssessmentScore.objects.values_list("id", "score"))
            cards = sorted(ReleasedCard.objects.values_list("id", flat=True))
        self.assertTrue(frozen)

        response = self.assign(self.head, self.jss1a_id, self.maths_id, self.tayo)
        self.assertEqual(response.status_code, 200, response.content)
        body = self.assign(self.head, self.jss1a_id, self.english_id, self.teacher).json()
        english = next(a for a in body["assignments"] if a["subject"] == "English")
        self.unassign(self.head, english["id"])
        mark = self.score(self.first_ca_id, ada)

        # Tayo now holds Maths in JSS 1A, and the released card still refuses him.
        refused = self.save(self.tayo, self.first_ca_id, ada, 3, expected_version=mark.version)
        self.assertEqual(refused.status_code, 423, refused.content)
        # Kemi holds nothing now, and is refused for that before anything else.
        self.assertEqual(self.save(self.teacher, self.first_ca_id, ada, 3, expected_version=mark.version).status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(sorted(ReleasedAssessmentScore.objects.values_list("id", "score")), frozen)
            self.assertEqual(sorted(ReleasedCard.objects.values_list("id", flat=True)), cards)
        self.assertEqual(self.score(self.first_ca_id, ada).value, 17)


class ThePrincipalIsPromptedOnHomeTests(SubjectTeachersSetUp):
    def home(self, who):
        return self.as_(who).get("/home/", HTTP_HOST=HOST).content.decode()

    def test_the_principal_sees_the_prompt_until_the_first_assignment(self):
        self.assertIn('data-prompt="subject-teachers"', self.home(self.head))

        self.give_kemi_maths_in_jss1a()

        self.assertNotIn('data-prompt="subject-teachers"', self.home(self.head))

    def test_nobody_else_is_prompted(self):
        for who in (self.vp, self.admin, self.teacher, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertNotIn('data-prompt="subject-teachers"', self.home(who))

    def test_the_prompt_is_this_schools_question(self):
        """Grace has an assignment; St Mary's has none, so St Mary's is still asked."""
        self.assign(self.their_head, self.grace_group_id, self.grace_maths_id, self.grace_teacher, host=THEIR_HOST)

        self.assertIn('data-prompt="subject-teachers"', self.home(self.head))


class TheRulesInPythonTests(SubjectTeachersSetUp):
    """The service, with no HTTP in front of it."""

    def test_may_mark_answers_true_for_everyone_until_the_term_has_one(self):
        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
            self.assertFalse(assignments.in_force(term))
            self.assertTrue(assignments.may_mark(self.tayo.user, self.stmarys, term, self.english_id, self.jss1b_id))

    def test_a_child_with_no_class_cannot_be_marked_by_a_narrowed_teacher(self):
        self.give_kemi_maths_in_jss1a()
        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
            self.assertFalse(assignments.may_mark(self.teacher.user, self.stmarys, term, self.maths_id, None))
            self.assertTrue(assignments.may_mark(self.head.user, self.stmarys, term, self.maths_id, None))


class ATermThatHasHadOneStaysRestrictedTests(SubjectTeachersSetUp):
    """Taking the last assignment away does not open marking to every teacher."""

    def setUp(self):
        super().setUp()
        body = self.give_kemi_maths_in_jss1a()
        # A mark Kemi made while she held the pair, for the clear below.
        self.mark = self.save(self.teacher, self.first_ca_id, self.children["ada"]).json()
        self.unassign(self.head, body["assignments"][0]["id"])

    def test_the_term_says_restricted_with_nobody_left_in_it(self):
        body = self.overview(self.head).json()

        self.assertEqual((body["marking"], body["in_force"], body["assignments"]), ("restricted", True, []))

    def test_a_teacher_with_nothing_is_sent_nothing_to_mark(self):
        for who in (self.teacher, self.tayo):
            with self.subTest(who=who.user.username):
                body = self.where(who).json()
                self.assertTrue(body["narrowed"])
                self.assertEqual((body["assessments"], body["classes"], body["pairs"]), ([], [], []))

    def test_and_is_refused_on_the_server_open_save_and_clear(self):
        ada = self.children["ada"]
        for who in (self.teacher, self.tayo):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.sheet(who, self.first_ca_id, self.jss1a_id).status_code, 403)
                self.assertEqual(self.sheet(who, self.english_ca_id, self.jss1b_id).status_code, 403)
                self.assertEqual(self.save(who, self.english_ca_id, ada).status_code, 403)
                self.assertEqual(self.save(who, self.first_ca_id, ada, 3, expected_version=self.mark["version"]).status_code, 403)
                self.assertEqual(self.clear(who, self.first_ca_id, ada, self.mark["version"]).status_code, 403)
        self.assertIsNone(self.score(self.english_ca_id, ada))
        self.assertEqual(self.score(self.first_ca_id, ada).value, 15)

    def test_the_principal_and_the_administrator_still_mark(self):
        for who in (self.head, self.admin):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.sheet(who, self.english_ca_id, self.jss1b_id).status_code, 200)

    def test_home_does_not_ask_again_as_though_nothing_had_been_given(self):
        html = self.as_(self.head).get("/home/", HTTP_HOST=HOST).content.decode()

        self.assertNotIn('data-prompt="subject-teachers"', html)

    def test_the_paper_is_judged_by_its_own_term_still(self):
        """The second term has never had one, so its paper is open to anybody."""
        with connected_to(self.stmarys):
            second = Term.objects.get(name=TermName.SECOND)
            later = Assessment.objects.create(term=second, subject=self.english, name="Second CA", max_score=20)
            academics.place_student(self.jss1a, second, self.children["ada"])

        self.assertEqual(self.save(self.tayo, later.pk, self.children["ada"]).status_code, 200)


class ThePrincipalsSwitchTests(RefusalAssertions, SubjectTeachersSetUp):
    """The one way a restricted term opens to every teacher, and back."""

    def setUp(self):
        super().setUp()
        self.give_kemi_maths_in_jss1a()

    def switches(self, school=None):
        return [c for c in self.changes(school) if c.kind in SubjectTeacherChange.SWITCH]

    def test_opening_lets_every_teacher_mark_everything(self):
        response = self.switch(self.head, True)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["marking"], response.json()["in_force"]), ("open", False))
        self.assertFalse(self.where(self.tayo).json()["narrowed"])
        self.assertEqual(self.sheet(self.tayo, self.english_ca_id, self.jss1b_id).status_code, 200)
        self.assertEqual(self.save(self.tayo, self.english_ca_id, self.bimpe).status_code, 200)

    def test_restricting_again_narrows_it_again(self):
        self.switch(self.head, True)

        response = self.switch(self.head, False)

        self.assertEqual(response.json()["marking"], "restricted")
        self.assertEqual(self.save(self.tayo, self.english_ca_id, self.bimpe).status_code, 403)
        self.assertIsNone(self.score(self.english_ca_id, self.bimpe))

    def test_each_turn_is_written_down_with_who_and_when(self):
        self.switch(self.head, True)
        self.switch(self.head, False)

        opened, restricted = self.switches()
        self.assertEqual([opened.kind, restricted.kind], ["opened", "restricted"])
        for change in (opened, restricted):
            with self.subTest(kind=change.kind):
                self.assertEqual((change.by_id, change.by_name), (self.head.user.pk, "Ngozi Eze"))
                self.assertIsNotNone(change.at)
        body = self.overview(self.head).json()
        self.assertEqual([c["kind"] for c in body["changes"][:2]], ["restricted", "opened"])

    def test_saying_what_it_already_is_writes_nothing(self):
        self.switch(self.head, False)
        self.switch(self.head, True)
        self.switch(self.head, True)

        self.assertEqual([c.kind for c in self.switches()], ["opened"])

    def test_adding_one_while_open_keeps_it_open(self):
        """The mirror of the rule: nothing narrows a term the principal opened, either."""
        self.switch(self.head, True)

        self.assign(self.head, self.jss1b_id, self.english_id, self.teacher)

        self.assertEqual(self.overview(self.head).json()["marking"], "open")
        self.assertEqual(self.save(self.tayo, self.first_ca_id, self.bimpe).status_code, 200)

    def test_before_the_first_assignment_there_is_nothing_to_switch(self):
        self.assertEqual(self.switch(self.their_head, False, host=THEIR_HOST).status_code, 422)
        self.assertEqual(self.switch(self.their_head, True, host=THEIR_HOST).status_code, 422)
        self.assertEqual(self.changes(self.grace), [])

    def test_only_the_principal_turns_it(self):
        for who in (self.vp, self.admin, self.teacher, self.tayo, self.bursar, self.children["ada"]):
            with self.subTest(who=who.user.username):
                response = self.switch(who, True)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": "Who teaches what is set by the principal."})
                self.assertEqual(self.switches(), [])
                self.assertEqual(self.save(self.tayo, self.english_ca_id, self.bimpe).status_code, 403)

    def test_the_vice_principal_and_the_administrator_see_where_it_stands(self):
        self.switch(self.head, True)

        for who in (self.vp, self.admin):
            with self.subTest(who=who.user.username):
                body = self.overview(who).json()
                self.assertEqual((body["marking"], body["may_change"]), ("open", False))

    def test_one_schools_switch_is_not_the_others(self):
        self.assign(self.their_head, self.grace_group_id, self.grace_maths_id, self.grace_teacher, host=THEIR_HOST)
        newcomer = grant_membership(User.objects.create_user("obi", PASSWORD, full_name="Obi Grace"), self.grace, Role.TEACHER)

        self.assertEqual(self.switch(self.head, True).status_code, 200)
        # St Mary's principal is nobody at Grace, so cannot turn Grace's.
        self.assertEqual(self.switch(self.head, True, host=THEIR_HOST).status_code, 403)

        self.assertEqual(self.overview(self.their_head, host=THEIR_HOST).json()["marking"], "restricted")
        self.assertEqual(self.save(newcomer, self.grace_ca_id, self.grace_child, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.switches(self.grace), [])

    def test_opening_marking_never_opens_a_released_card(self):
        ada = self.children["ada"]
        with connected_to(self.stmarys):
            set_score(self.first_ca, ada, 17, by=self.teacher.user)
            term = Term.objects.get(pk=self.term_id)
            sheet = chain.open_sheet(self.jss1a, term, self.head.user)
            chain.submit(sheet, self.teacher.user)
            chain.check(sheet, self.vp.user)
            chain.approve(sheet, self.head.user)
            chain.release(sheet, self.head.user)
            frozen = sorted(ReleasedAssessmentScore.objects.values_list("id", "score"))
        mark = self.score(self.first_ca_id, ada)

        self.switch(self.head, True)

        refused = self.save(self.tayo, self.first_ca_id, ada, 3, expected_version=mark.version)
        self.assertEqual(refused.status_code, 423, refused.content)
        with connected_to(self.stmarys):
            self.assertEqual(sorted(ReleasedAssessmentScore.objects.values_list("id", "score")), frozen)
        self.assertEqual(self.score(self.first_ca_id, ada).value, 17)


class ANewTermCarriesTheLastOnesTeachersTests(SubjectTeachersSetUp):
    """Moving on to the next term copies this school's assignments into it."""

    def setUp(self):
        super().setUp()
        self.second_id = self.second_term.pk

    def held_in(self, term_id, school=None):
        with connected_to(school or self.stmarys):
            return sorted(
                SubjectTeacher.objects.filter(term_id=term_id).values_list(
                    "class_group_id", "subject_id", "teacher_membership_id"
                )
            )

    def changes_in(self, term_id, school=None):
        with connected_to(school or self.stmarys):
            return list(SubjectTeacherChange.objects.filter(term_id=term_id).order_by("id"))

    def carry(self, term_id, school=None):
        with connected_to(school or self.stmarys):
            return SubjectTeacherCarry.objects.filter(term_id=term_id).first()

    def home(self, who, host=HOST):
        return self.as_(who).get("/home/", HTTP_HOST=host).content.decode()

    def give_both(self):
        self.give_kemi_maths_in_jss1a()
        self.assertEqual(self.assign(self.head, self.jss1b_id, self.english_id, self.tayo).status_code, 200)

    def test_the_new_term_starts_with_the_last_ones_assignments(self):
        self.give_both()

        self.assertEqual(self.make_current(self.head, self.second_id).status_code, 200)

        self.assertEqual(self.held_in(self.second_id), self.held_in(self.term_id))
        self.assertEqual(len(self.held_in(self.second_id)), 2)
        body = self.overview(self.head).json()
        self.assertEqual((body["marking"], body["carried"]["copied"], body["carried"]["skipped"]), ("restricted", 2, 0))

    def test_and_is_restricted_from_its_first_day(self):
        self.give_both()
        with connected_to(self.stmarys):
            later = Assessment.objects.create(term=self.second_term, subject=self.english, name="Second CA", max_score=20)
            academics.place_student(self.jss1a, self.second_term, self.children["ada"])

        self.make_current(self.head, self.second_id)

        self.assertEqual(self.where(self.teacher).json()["pairs"], [{"subject_id": self.maths_id, "class_group_id": self.jss1a_id}])
        self.assertEqual(self.save(self.teacher, later.pk, self.children["ada"]).status_code, 403)
        self.assertIsNone(self.score(later.pk, self.children["ada"]))

    def test_each_copy_is_written_down_as_the_systems_naming_where_it_came_from(self):
        self.give_both()

        self.make_current(self.head, self.second_id)

        copies = self.changes_in(self.second_id)
        self.assertEqual(len(copies), 2)
        with connected_to(self.stmarys):
            from_name = str(Term.objects.get(pk=self.term_id))
        for change in copies:
            with self.subTest(teacher=change.teacher_name):
                self.assertEqual(change.kind, "added")
                self.assertEqual((change.by_id, change.by_name), (None, ""))
                self.assertEqual((change.from_term_id, change.from_term_name), (self.term_id, from_name))
                self.assertIsNotNone(change.at)
        self.assertEqual(sorted(c.teacher_name for c in copies), ["Kemi Bello", "Tayo Ojo"])

    def test_a_teacher_who_has_left_or_lost_teacher_access_is_not_copied(self):
        self.give_both()
        sade = grant_membership(User.objects.create_user("sade", PASSWORD, full_name="Sade Ola"), self.stmarys, Role.TEACHER)
        self.assertEqual(self.assign(self.head, self.jss1a_id, self.english_id, sade).status_code, 200)
        Membership.objects.filter(pk=self.tayo.pk).update(status=MembershipStatus.ENDED)
        Membership.objects.filter(pk=sade.pk).update(status=MembershipStatus.SUSPENDED)

        self.make_current(self.head, self.second_id)

        self.assertEqual(self.held_in(self.second_id), [(self.jss1a_id, self.maths_id, self.teacher.pk)])
        skipped = [c for c in self.changes_in(self.second_id) if c.kind == "skipped"]
        self.assertEqual(sorted(c.teacher_name for c in skipped), ["Sade Ola", "Tayo Ojo"])
        self.assertEqual({c.reason for c in skipped}, {"no longer a teacher here"})
        self.assertEqual((self.carry(self.second_id).copied, self.carry(self.second_id).skipped), (1, 2))
        self.assertEqual(self.save(self.tayo, self.first_ca_id, self.bimpe).status_code, 403)

    def test_a_subject_no_longer_taught_is_not_copied(self):
        self.give_both()
        with connected_to(self.stmarys):
            Subject.objects.filter(pk=self.english_id).update(is_active=False)

        self.make_current(self.head, self.second_id)

        self.assertEqual(self.held_in(self.second_id), [(self.jss1a_id, self.maths_id, self.teacher.pk)])
        self.assertEqual([c.reason for c in self.changes_in(self.second_id) if c.kind == "skipped"], ["the subject is no longer taught"])

    def test_with_none_last_term_nothing_at_all_changes(self):
        self.make_current(self.head, self.second_id)

        self.assertEqual((self.held_in(self.second_id), self.changes_in(self.second_id)), ([], []))
        self.assertIsNone(self.carry(self.second_id))
        self.assertFalse(self.where(self.tayo).json()["narrowed"])
        self.assertEqual(self.overview(self.head).json()["marking"], "not-yet")
        html = self.home(self.head)
        self.assertIn('data-prompt="subject-teachers"', html)
        self.assertNotIn('data-prompt="subject-teachers-carried"', html)

    def test_going_back_and_forward_again_copies_nothing_twice(self):
        self.give_both()
        self.make_current(self.head, self.second_id)
        self.make_current(self.head, self.term_id)
        self.make_current(self.head, self.second_id)

        self.assertEqual(len(self.held_in(self.second_id)), 2)
        self.assertEqual(len(self.changes_in(self.second_id)), 2)
        # And going back put nothing into the first term.
        self.assertEqual(len(self.changes_in(self.term_id)), 2)

    def test_going_back_to_an_earlier_term_copies_nothing_into_it(self):
        self.make_current(self.head, self.second_id)
        self.give_both()

        self.make_current(self.head, self.term_id)

        self.assertEqual((self.held_in(self.term_id), self.changes_in(self.term_id)), ([], []))
        self.assertEqual(self.overview(self.head).json()["marking"], "not-yet")

    def test_a_term_the_principal_had_opened_starts_open(self):
        self.give_both()
        self.switch(self.head, True)

        self.make_current(self.head, self.second_id)

        self.assertEqual(self.overview(self.head).json()["marking"], "open")
        self.assertFalse(self.where(self.tayo).json()["narrowed"])
        opened = [c for c in self.changes_in(self.second_id) if c.kind == "opened"]
        self.assertEqual([(c.by_id, c.from_term_id) for c in opened], [(None, self.term_id)])

    def test_only_who_may_set_the_term_starts_one(self):
        self.give_both()
        for who in (self.teacher, self.vp):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.make_current(who, self.second_id).status_code, 403)
                self.assertEqual(self.held_in(self.second_id), [])
        # The administrator may set the term, and the copy is still the system's.
        self.assertEqual(self.make_current(self.admin, self.second_id).status_code, 200)
        self.assertEqual({c.by_id for c in self.changes_in(self.second_id)}, {None})


class TheCarryForwardNeverCrossesSchoolsTests(SubjectTeachersSetUp):
    """Two schools whose rows share their ids, each moving on to its next term."""

    def setUp(self):
        super().setUp()
        with connected_to(self.grace):
            self.grace_second_id = a_term(
                name=TermName.SECOND, starts=self.second_term.starts_on, ends=self.second_term.ends_on
            ).pk
        self.give_kemi_maths_in_jss1a()
        response = self.assign(self.their_head, self.grace_group_id, self.grace_maths_id, self.grace_teacher, host=THEIR_HOST)
        self.assertEqual(response.status_code, 200, response.content)

    def held_in(self, term_id, school):
        with connected_to(school):
            return sorted(SubjectTeacher.objects.filter(term_id=term_id).values_list("teacher_membership_id", flat=True))

    def test_each_school_copies_only_its_own(self):
        self.make_current(self.head, self.second_term.pk)

        self.assertEqual(self.held_in(self.second_term.pk, self.stmarys), [self.teacher.pk])
        self.assertEqual(self.held_in(self.grace_second_id, self.grace), [])
        with connected_to(self.grace):
            self.assertFalse(SubjectTeacherCarry.objects.exists())

        self.make_current(self.their_head, self.grace_second_id, host=THEIR_HOST)

        self.assertEqual(self.held_in(self.grace_second_id, self.grace), [self.grace_teacher.pk])
        self.assertEqual(self.held_in(self.second_term.pk, self.stmarys), [self.teacher.pk])

    def test_a_row_naming_another_schools_teacher_is_never_copied(self):
        """Written past every guard, as a bad import might: the copy looks the teacher
        up among this school's own memberships, so it is left out and said so."""
        with connected_to(self.stmarys):
            SubjectTeacher.objects.create(
                term_id=self.term_id, class_group_id=self.jss1b_id, subject_id=self.maths_id,
                teacher_membership_id=self.grace_teacher.pk,
            )

        self.make_current(self.head, self.second_term.pk)

        self.assertEqual(self.held_in(self.second_term.pk, self.stmarys), [self.teacher.pk])
        with connected_to(self.stmarys):
            skipped = SubjectTeacherChange.objects.get(term_id=self.second_term.pk, kind="skipped")
        # Not even the other school's teacher's name is copied into this school's log.
        self.assertEqual((skipped.teacher_membership_id, skipped.teacher_name), (self.grace_teacher.pk, ""))
        self.assertEqual(self.save(self.grace_teacher, self.first_ca_id, self.bimpe).status_code, 403)

    def test_the_other_schools_principal_never_sees_this_schools_card(self):
        self.make_current(self.head, self.second_term.pk)

        theirs = self.as_(self.their_head).get("/home/", HTTP_HOST=THEIR_HOST).content.decode()

        self.assertNotIn('data-prompt="subject-teachers-carried"', theirs)


class ThePrincipalIsAskedToReviewTheCopyTests(SubjectTeachersSetUp):
    CARD = 'data-prompt="subject-teachers-carried"'

    def setUp(self):
        super().setUp()
        self.give_kemi_maths_in_jss1a()
        self.make_current(self.head, self.second_term.pk)

    def home(self, who, host=HOST):
        return self.as_(who).get("/home/", HTTP_HOST=host).content.decode()

    def dismiss(self, who, host=HOST):
        return self.as_(who).post("/subject-teachers/seen/", HTTP_HOST=host)

    def test_the_principal_sees_the_card(self):
        html = self.home(self.head)

        self.assertIn(self.CARD, html)
        self.assertIn("Assignments copied from last term, review them", html)
        self.assertIn("1 copied from", html)

    def test_nobody_else_does(self):
        for who in (self.vp, self.admin, self.teacher, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertNotIn(self.CARD, self.home(who))

    def test_it_goes_when_the_principal_opens_the_page(self):
        self.overview(self.head)

        self.assertNotIn(self.CARD, self.home(self.head))

    def test_the_vice_principal_or_the_administrator_opening_it_does_not_count(self):
        self.overview(self.vp)
        self.overview(self.admin)

        self.assertIn(self.CARD, self.home(self.head))

    def test_it_goes_when_the_principal_dismisses_it(self):
        response = self.dismiss(self.head)

        self.assertEqual((response.status_code, response["Location"]), (302, "/home/"))
        self.assertNotIn(self.CARD, self.home(self.head))

    def test_only_the_principal_dismisses_it(self):
        for who in (self.vp, self.admin, self.teacher):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.dismiss(who).status_code, 403)
        self.assertEqual(self.dismiss(self.their_head, host=HOST).status_code, 403)
        self.assertIn(self.CARD, self.home(self.head))
