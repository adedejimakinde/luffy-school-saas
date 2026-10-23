"""Who teaches what, and what it does to marking: `docs/subject-teachers.md`.

Two schools in every class, on their own hosts (`results.tests.fixtures.ChainSetUp`).
The claims, each with a control in the doc:

- **Until the term has an assignment, nothing changes.** Any teacher sees and marks
  every paper and class, as before.
- **From the first one, a teacher marks only their own pairs**, and the server refuses
  the rest: the sheet, a save and a clear, not only the list on the page.
- **The principal, the vice principal and the administrator are never narrowed.**
- **Only the principal changes assignments**; the vice principal and the administrator
  read them; nobody else opens them. A refused write changes nothing.
- **Every change is written down, who and when**, in a table that cannot be edited.
- **One school's assignments and teachers are never another's.** Ids repeat across the
  two schools, so every lookup is by the school the request arrived at.
- **Released results are never affected.**
"""

from django.db import connection, transaction

from academics.models import Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from gradebook import assignments
from gradebook.models import Assessment, Score, Subject, SubjectTeacher, SubjectTeacherChange
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

    def test_taking_the_last_one_away_opens_marking_again(self):
        body = self.give_kemi_maths_in_jss1a()
        self.assertEqual(self.save(self.teacher, self.english_ca_id, self.children["ada"]).status_code, 403)

        self.unassign(self.head, body["assignments"][0]["id"])

        self.assertFalse(self.where(self.teacher).json()["narrowed"])
        self.assertEqual(self.save(self.teacher, self.english_ca_id, self.children["ada"]).status_code, 200)


class ATeacherMarksOnlyTheirOwnPairsTests(SubjectTeachersSetUp):
    def setUp(self):
        super().setUp()
        self.give_kemi_maths_in_jss1a()

    def test_their_page_is_sent_only_their_paper_and_class(self):
        body = self.where(self.teacher).json()

        self.assertTrue(body["narrowed"])
        self.assertEqual(body["pairs"], [{"subject_id": self.maths_id, "class_group_id": self.jss1a_id}])
        self.assertEqual([a["id"] for a in body["assessments"]], [self.first_ca_id])
        self.assertEqual([g["id"] for g in body["classes"]], [self.jss1a_id])

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

        pairs = self.where(self.teacher).json()["pairs"]

        self.assertEqual(
            sorted((p["subject_id"], p["class_group_id"]) for p in pairs),
            sorted([(self.maths_id, self.jss1a_id), (self.english_id, self.jss1b_id)]),
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
