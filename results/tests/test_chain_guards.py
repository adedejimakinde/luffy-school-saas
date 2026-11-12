"""What a class in the chain refuses, and what it says before a signature.

Audit findings F-01, F-02 and F-05 (`docs/audit/2026-11-security-and-correctness.md`).

- **F-01.** While a class's results are submitted, checked or approved, no
  child is placed into it, moved into or out of it, admitted into it or taken
  off it. A release reads the roster afresh, so a change in between would send
  home positions and an "of N" nobody signed.
- **F-02.** While such a class has marks in a subject, that subject takes no
  new paper and loses none: the class could not mark the paper, and would
  release with the subject incomplete and nobody ranked.
- **F-05.** Submitting, checking and approving a class with papers unmarked
  says how many, per subject, and goes on only when the number is sent back.
  The number is written on the step's row in the log.

Each refusal is asserted at the service, which is the gate, and through the
route a page uses. Two schools throughout: the two schools' first class, term
and sheet share ids, so a guard that read the wrong schema would refuse (or
allow) on the other school's sheet.
"""

from academics import services as academics
from academics.models import ClassGroup, ClassPlacement, Term
from accounts.models import Membership, Role, User
from accounts.services import enroll_student, grant_membership
from gradebook import curriculum
from gradebook.models import Assessment, Score, Subject
from results import services, unmarked
from results.models import ResultSheetTransition, SheetState
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

WAITING = "JSS 1A's results are waiting for approval. Send them back first to change the class."
APPROVED = "JSS 1A's results have been approved. Send them back first to change the class."
IN_THE_CHAIN = ("submitted", "checked", "approved")


class GuardSetUp(ChainSetUp):
    """The chain's cast, an administrator at each school, and a child to place."""

    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ola", PASSWORD, full_name="Ola Office"),
            self.stmarys,
            Role.ADMIN,
        )
        self.their_admin = grant_membership(
            User.objects.create_user("gbenga", PASSWORD, full_name="Gbenga Office"),
            self.grace,
            Role.ADMIN,
        )
        self.newcomer = enroll_student(
            User.objects.create_user("zainab", PASSWORD, full_name="Zainab Bello"),
            self.stmarys,
        )
        self.their_newcomer = enroll_student(
            User.objects.create_user("uche", PASSWORD, full_name="Uche Grace"),
            self.grace,
        )

    # -- the chain -----------------------------------------------------------

    def term_now(self):
        return Term.objects.get(pk=self.term_id)

    def group(self, pk=None):
        return ClassGroup.objects.get(pk=pk or self.jss1a_id)

    def walk(self, state, *, group_id=None, seen=None):
        """Take St Mary's class as far as `state`. Call inside `connected_to`.

        The administrator submits, so a class with no class teacher can be
        walked too. `seen` is the unmarked count, where a test has one.
        """
        sheet = services.open_sheet(self.group(group_id), self.term_now(), self.head.user)
        if state == "draft":
            return sheet
        services.submit(sheet, self.admin.user, unmarked=seen)
        if state == "submitted":
            return sheet
        services.check(sheet, self.vp.user, unmarked=seen)
        if state == "checked":
            return sheet
        services.approve(sheet, self.head.user, unmarked=seen)
        if state == "approved":
            return sheet
        services.release(sheet, self.head.user)
        return sheet

    def walk_grace(self, state):
        """The same at Grace, whose class, term and sheet share St Mary's ids."""
        term = Term.objects.get(pk=self.grace_term_id)
        group = ClassGroup.objects.get(pk=self.grace_group_id)
        sheet = services.open_sheet(group, term, self.their_head.user)
        services.submit(sheet, self.their_admin.user)
        if state == "submitted":
            return sheet
        services.check(sheet, self.their_vp.user)
        if state == "checked":
            return sheet
        services.approve(sheet, self.their_head.user)
        return sheet

    def send_back(self, sheet):
        services.send_back(sheet, self.head.user, "One child is in the wrong class.")

    def roster(self, group_id=None):
        return sorted(
            ClassPlacement.objects.student_ids(self.group(group_id), self.term_now())
        )

    def mark(self, assessment, child, value=10):
        Score.objects.create(
            assessment=assessment, student_membership_id=child.pk, value=value
        )

    def as_(self, member):
        self.client.force_login(member.user)
        return self.client


# -- F-01 -------------------------------------------------------------------------


class ARosterInTheChainStaysPutTests(GuardSetUp):
    def test_the_control_a_draft_class_takes_and_gives_children(self):
        """Every refusal below would pass if placing were simply broken."""
        with connected_to(self.stmarys):
            self.walk("draft")
            academics.place_student(self.jss1a, self.term_now(), self.newcomer)
            academics.move_student(self.jss1b, self.term_now(), self.children["ada"])
            academics.move_student(self.jss1a, self.term_now(), self.bimpe)
            self.assertTrue(academics.remove_placement(self.term_now(), self.children["bisi"]))
            self.assertEqual(
                self.roster(),
                sorted([self.newcomer.pk, self.bimpe.pk, *self.ids("emeka", "tunde")]),
            )

    def test_placing_a_child_into_the_class_is_refused_in_every_state(self):
        for state in IN_THE_CHAIN:
            with self.subTest(state=state), connected_to(self.stmarys):
                sheet = self.walk(state)
                with self.assertRaises(academics.ResultsInTheChain) as refused:
                    academics.place_student(self.jss1a, self.term_now(), self.newcomer)
                self.assertEqual(
                    str(refused.exception), APPROVED if state == "approved" else WAITING
                )
                self.assertEqual(self.roster(), self.everyone())
                self.send_back(sheet)

    def test_moving_a_child_out_of_the_class_is_refused_in_every_state(self):
        for state in IN_THE_CHAIN:
            with self.subTest(state=state), connected_to(self.stmarys):
                sheet = self.walk(state)
                with self.assertRaises(academics.ResultsInTheChain) as refused:
                    academics.move_student(self.jss1b, self.term_now(), self.children["ada"])
                self.assertEqual(
                    str(refused.exception), APPROVED if state == "approved" else WAITING
                )
                self.assertEqual(self.roster(), self.everyone())
                self.assertEqual(self.roster(self.jss1b_id), [self.bimpe.pk])
                self.send_back(sheet)

    def test_moving_a_child_into_the_class_is_refused_in_every_state(self):
        """The class being joined, where the mover's own class is open."""
        for state in IN_THE_CHAIN:
            with self.subTest(state=state), connected_to(self.stmarys):
                sheet = self.walk(state)
                with self.assertRaises(academics.ResultsInTheChain) as refused:
                    academics.move_student(self.jss1a, self.term_now(), self.bimpe)
                self.assertIn("JSS 1A's results", str(refused.exception))
                self.assertEqual(self.roster(), self.everyone())
                self.assertEqual(self.roster(self.jss1b_id), [self.bimpe.pk])
                self.send_back(sheet)

    def test_taking_a_child_off_the_class_is_refused_in_every_state(self):
        for state in IN_THE_CHAIN:
            with self.subTest(state=state), connected_to(self.stmarys):
                sheet = self.walk(state)
                with self.assertRaises(academics.ResultsInTheChain):
                    academics.remove_placement(self.term_now(), self.children["ada"])
                self.assertEqual(self.roster(), self.everyone())
                self.send_back(sheet)

    def test_a_send_back_lets_the_class_change_again(self):
        for state in IN_THE_CHAIN:
            with self.subTest(state=state), connected_to(self.stmarys):
                sheet = self.walk(state)
                with self.assertRaises(academics.ResultsInTheChain):
                    academics.move_student(self.jss1b, self.term_now(), self.children["ada"])

                self.send_back(sheet)

                academics.move_student(self.jss1b, self.term_now(), self.children["ada"])
                self.assertEqual(self.roster(), self.ids("emeka", "bisi", "tunde"))
                academics.move_student(self.jss1a, self.term_now(), self.children["ada"])
                self.assertEqual(self.roster(), self.everyone())

    def test_a_released_class_is_as_it_was_before(self):
        """Released results are frozen cards, and placement did not refuse them.

        Stated so that widening the guard to `released` is a decision somebody
        makes, not a side effect: the child placed afterwards has no card, which
        is issue #165's, and the cards that went home do not change.
        """
        with connected_to(self.stmarys):
            self.walk("released")
            academics.place_student(self.jss1a, self.term_now(), self.newcomer)
            academics.move_student(self.jss1b, self.term_now(), self.children["ada"])
            self.assertIn(self.newcomer.pk, self.roster())
            self.assertNotIn(self.children["ada"].pk, self.roster())

    def test_another_classs_sheet_does_not_shut_this_one(self):
        """Per class: JSS 1A waiting must not stop the office filling JSS 1B."""
        with connected_to(self.stmarys):
            self.walk("approved")
            academics.place_student(self.jss1b, self.term_now(), self.newcomer)
            self.assertEqual(
                self.roster(self.jss1b_id), sorted([self.bimpe.pk, self.newcomer.pk])
            )

    def test_another_terms_sheet_does_not_shut_this_term(self):
        with connected_to(self.stmarys):
            self.walk("approved")
            second = Term.objects.get(pk=self.second_term.pk)
            academics.place_student(self.jss1a, second, self.newcomer)
            self.assertTrue(
                ClassPlacement.objects.filter(
                    term=second, student_membership_id=self.newcomer.pk
                ).exists()
            )

    def test_the_other_schools_chain_shuts_nothing_here(self):
        """Grace's JSS 1A is approved. St Mary's JSS 1A, same ids, is open."""
        with connected_to(self.grace):
            self.walk_grace("approved")
            with self.assertRaises(academics.ResultsInTheChain):
                academics.place_student(
                    ClassGroup.objects.get(pk=self.grace_group_id),
                    Term.objects.get(pk=self.grace_term_id),
                    self.their_newcomer,
                )
        with connected_to(self.stmarys):
            academics.place_student(self.jss1a, self.term_now(), self.newcomer)
            self.assertIn(self.newcomer.pk, self.roster())

    def test_carrying_a_roster_forward_into_a_class_in_the_chain_is_refused(self):
        with connected_to(self.stmarys):
            second = Term.objects.get(pk=self.second_term.pk)
            sheet = services.open_sheet(self.jss1a, second, self.head.user)
            services.submit(sheet, self.admin.user)

            with self.assertRaises(academics.ResultsInTheChain):
                academics.carry_forward_placements(self.term_now(), second)
            self.assertFalse(ClassPlacement.objects.filter(term=second).exists())

            self.send_back(sheet)
            self.assertEqual(
                academics.carry_forward_placements(self.term_now(), second), 5
            )


class TheRollRoutesRefuseTooTests(GuardSetUp):
    """The routes the roll page uses. A hidden button is not the gate."""

    def place(self, member, child, group_id, host=HOST):
        return self.as_(member).put(
            f"/api/enrolment/roll/{child.pk}/class/",
            data={"class_group_id": group_id},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def admit(self, member, username, group_id, host=HOST):
        return self.as_(member).post(
            "/api/enrolment/roll/",
            data={"full_name": "New Child", "username": username, "class_group_id": group_id},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def test_the_control_the_routes_work_on_an_open_class(self):
        self.assertEqual(self.place(self.admin, self.newcomer, self.jss1a_id).status_code, 200)
        self.assertEqual(self.place(self.admin, self.newcomer, self.jss1b_id).status_code, 200)
        self.assertEqual(self.admit(self.admin, "STM/NEW/1", self.jss1a_id).status_code, 201)

    def test_placing_is_refused_with_the_sentence(self):
        with connected_to(self.stmarys):
            self.walk("submitted")

        response = self.place(self.admin, self.newcomer, self.jss1a_id)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], WAITING)
        with connected_to(self.stmarys):
            self.assertEqual(self.roster(), self.everyone())

    def test_moving_out_and_moving_in_are_refused(self):
        with connected_to(self.stmarys):
            self.walk("approved")

        out = self.place(self.admin, self.children["ada"], self.jss1b_id)
        into = self.place(self.head, self.bimpe, self.jss1a_id)

        self.assertEqual((out.status_code, into.status_code), (422, 422))
        self.assertEqual(out.json()["detail"], APPROVED)
        self.assertEqual(into.json()["detail"], APPROVED)
        with connected_to(self.stmarys):
            self.assertEqual(self.roster(), self.everyone())
            self.assertEqual(self.roster(self.jss1b_id), [self.bimpe.pk])

    def test_admitting_into_the_class_is_refused_and_admits_nobody(self):
        """One transaction: the refusal takes the new account back out with it."""
        with connected_to(self.stmarys):
            self.walk("checked")
        before = User.objects.count()

        response = self.admit(self.admin, "STM/NEW/2", self.jss1a_id)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], WAITING)
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(Membership.objects.filter(user__username="STM/NEW/2").exists())

    def test_a_roll_import_naming_the_class_is_refused_whole(self):
        with connected_to(self.stmarys):
            self.walk("submitted")
        before = User.objects.count()

        response = self.as_(self.admin).post(
            "/api/enrolment/roll/import/",
            data={
                "csv": "full_name,class_group,username,reference,guardian_name,guardian_contact\n"
                "Chike Obi,JSS 1B,STM/2026/0100,0100,,\n"
                "Ngozi Abah,JSS 1A,STM/2026/0101,0101,,\n"
            },
            content_type="application/json",
            HTTP_HOST=HOST,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], WAITING)
        self.assertEqual(User.objects.count(), before)

    def test_a_send_back_opens_the_route_again(self):
        with connected_to(self.stmarys):
            sheet = self.walk("approved")
        self.assertEqual(self.place(self.admin, self.newcomer, self.jss1a_id).status_code, 422)

        with connected_to(self.stmarys):
            self.send_back(sheet)

        self.assertEqual(self.place(self.admin, self.newcomer, self.jss1a_id).status_code, 200)

    def test_grace_in_the_chain_does_not_shut_st_marys_route(self):
        with connected_to(self.grace):
            self.walk_grace("approved")

        ours = self.place(self.admin, self.newcomer, self.jss1a_id)
        theirs = self.place(
            self.their_admin, self.their_newcomer, self.grace_group_id, host=THEIR_HOST
        )

        self.assertEqual(ours.status_code, 200)
        self.assertEqual(theirs.status_code, 422)
        self.assertEqual(theirs.json()["detail"], APPROVED)


# -- F-02 -------------------------------------------------------------------------

ADD_WAITING = "JSS 1A's results are waiting for approval. Send them back first to add a paper to Mathematics."
ADD_APPROVED = "JSS 1A's results have been approved. Send them back first to add a paper to Mathematics."


class ASubjectInTheChainKeepsItsPapersTests(GuardSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            # JSS 1A is marked in Mathematics, whole: one paper, four marks.
            for child in self.children.values():
                self.mark(self.first_ca, child)
            self.english = Subject.objects.create(name="English", code="ENG")

    def add(self, name="Project", subject=None):
        return curriculum.create_paper_as(
            self.head.user, self.stmarys, subject or self.maths, name, 10
        )

    def papers(self, subject=None):
        return sorted(
            Assessment.objects.filter(
                term_id=self.term_id, subject=subject or self.maths
            ).values_list("name", flat=True)
        )

    def test_the_control_a_draft_class_takes_a_paper(self):
        with connected_to(self.stmarys):
            self.walk("draft")
            self.add()
            self.assertEqual(self.papers(), ["First CA", "Project"])

    def test_adding_a_paper_is_refused_in_every_state(self):
        for state in IN_THE_CHAIN:
            with self.subTest(state=state), connected_to(self.stmarys):
                sheet = self.walk(state)
                with self.assertRaises(curriculum.CurriculumRefused) as refused:
                    self.add()
                self.assertEqual(
                    str(refused.exception),
                    ADD_APPROVED if state == "approved" else ADD_WAITING,
                )
                self.assertEqual(self.papers(), ["First CA"])
                self.send_back(sheet)

    def test_what_the_refusal_prevents(self):
        """The finding itself: with the paper added, nobody in the class is whole.

        Staged past the service, as an import or a shell would, to show what
        the guard stands in front of.
        """
        from results import positions

        with connected_to(self.stmarys):
            self.walk("approved")
            self.assertEqual(
                sorted(positions.class_results(self.jss1a, self.term_now()).whole_students),
                self.everyone(),
            )
            Assessment.objects.create(
                term=self.term_now(), subject=self.maths, name="Project", max_score=10
            )
            self.assertEqual(
                positions.class_results(self.jss1a, self.term_now()).whole_students,
                frozenset(),
            )

    def test_a_send_back_lets_the_paper_in(self):
        with connected_to(self.stmarys):
            sheet = self.walk("approved")
            with self.assertRaises(curriculum.CurriculumRefused):
                self.add()
            self.send_back(sheet)
            self.add()
            self.assertEqual(self.papers(), ["First CA", "Project"])

    def test_a_subject_the_class_has_no_mark_in_is_not_shut(self):
        """English has no mark in JSS 1A, so its papers change nothing there."""
        with connected_to(self.stmarys):
            self.walk("approved")
            self.add("Essay", self.english)
            self.assertEqual(self.papers(self.english), ["Essay"])

    def test_a_class_in_the_chain_with_no_mark_in_the_subject_is_not_the_reason(self):
        """JSS 1B is approved and has no Mathematics mark; JSS 1A is a draft."""
        with connected_to(self.stmarys):
            self.walk("approved", group_id=self.jss1b_id)
            self.add()
            self.assertEqual(self.papers(), ["First CA", "Project"])

    def test_a_released_class_does_not_refuse(self):
        with connected_to(self.stmarys):
            self.walk("released")
            self.add()
            self.assertEqual(self.papers(), ["First CA", "Project"])

    def test_removing_an_unmarked_paper_is_refused_too(self):
        """It would make the subject whole for a class signed as incomplete."""
        with connected_to(self.stmarys):
            project = self.add()
            sheet = self.walk("submitted", seen=4)
            with self.assertRaises(curriculum.CurriculumRefused) as refused:
                curriculum.delete_paper_as(self.head.user, self.stmarys, project)
            self.assertEqual(
                str(refused.exception),
                "JSS 1A's results are waiting for approval. Send them back first "
                "to remove a paper from Mathematics.",
            )
            self.assertEqual(self.papers(), ["First CA", "Project"])
            self.send_back(sheet)
            curriculum.delete_paper_as(self.head.user, self.stmarys, project)
            self.assertEqual(self.papers(), ["First CA"])

    def test_the_teaching_route_refuses_with_the_sentence(self):
        with connected_to(self.stmarys):
            self.walk("checked")

        response = self.as_(self.head).post(
            f"/api/teaching/subjects/{self.maths_id}/papers/",
            data={"name": "Project", "max_score": 10},
            content_type="application/json",
            HTTP_HOST=HOST,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], ADD_WAITING)
        with connected_to(self.stmarys):
            self.assertEqual(self.papers(), ["First CA"])

    def test_the_teaching_route_takes_the_paper_after_a_send_back(self):
        with connected_to(self.stmarys):
            self.send_back(self.walk("checked"))

        response = self.as_(self.head).post(
            f"/api/teaching/subjects/{self.maths_id}/papers/",
            data={"name": "Project", "max_score": 10},
            content_type="application/json",
            HTTP_HOST=HOST,
        )

        self.assertEqual(response.status_code, 200)
        with connected_to(self.stmarys):
            self.assertEqual(self.papers(), ["First CA", "Project"])

    def test_the_other_schools_chain_shuts_no_subject_here(self):
        """Grace's JSS 1A is approved with a Mathematics mark, under the same ids."""
        with connected_to(self.grace):
            self.mark(self.grace_ca, self.grace_child)
            self.walk_grace("approved")
            with self.assertRaises(curriculum.CurriculumRefused):
                curriculum.create_paper_as(
                    self.their_head.user,
                    self.grace,
                    Subject.objects.get(name="Mathematics"),
                    "Project",
                    10,
                )
        with connected_to(self.stmarys):
            self.add()
            self.assertEqual(self.papers(), ["First CA", "Project"])


# -- F-05 -------------------------------------------------------------------------


class UnmarkedSetUp(GuardSetUp):
    """JSS 1A, four children. Mathematics: First CA marked for Ada only, and an
    Exam nobody is marked in. So three and four: seven papers unmarked."""

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            self.exam = Assessment.objects.create(
                term=self.term, subject=self.maths, name="Exam", max_score=60
            )
            self.mark(self.first_ca, self.children["ada"])

    def mark_everything(self):
        for paper in (self.first_ca, self.exam):
            for child in self.children.values():
                Score.objects.get_or_create(
                    assessment=paper,
                    student_membership_id=child.pk,
                    defaults={"value": 5},
                )

    def sheet(self):
        return services.open_sheet(self.jss1a, self.term_now(), self.head.user)

    def log(self):
        return list(
            ResultSheetTransition.objects.filter(sheet__class_group_id=self.jss1a_id)
            .order_by("pk")
            .values_list("to_state", "unmarked_papers")
        )


class TheCountTests(UnmarkedSetUp):
    def test_it_counts_a_child_and_a_paper_with_no_mark(self):
        with connected_to(self.stmarys):
            found = unmarked.for_class(self.jss1a, self.term_now())
            self.assertEqual([(s.subject, s.unmarked) for s in found], [("Mathematics", 7)])
            self.assertEqual(unmarked.total(found), 7)

    def test_it_is_per_subject_and_by_name(self):
        with connected_to(self.stmarys):
            english = Subject.objects.create(name="English", code="ENG")
            essay = Assessment.objects.create(
                term=self.term, subject=english, name="Essay", max_score=20
            )
            self.mark(essay, self.children["ada"])
            self.mark(essay, self.children["bisi"])
            self.assertEqual(
                [(s.subject, s.unmarked) for s in unmarked.for_class(self.jss1a, self.term_now())],
                [("English", 2), ("Mathematics", 7)],
            )

    def test_a_subject_nobody_in_the_class_has_a_mark_in_is_not_counted(self):
        """The class's subjects are read off its marks, as the broadsheet's are."""
        with connected_to(self.stmarys):
            english = Subject.objects.create(name="English", code="ENG")
            Assessment.objects.create(term=self.term, subject=english, name="Essay", max_score=20)
            self.assertEqual(
                [s.subject for s in unmarked.for_class(self.jss1a, self.term_now())],
                ["Mathematics"],
            )

    def test_a_whole_class_counts_nothing(self):
        with connected_to(self.stmarys):
            self.mark_everything()
            self.assertEqual(unmarked.for_class(self.jss1a, self.term_now()), [])

    def test_another_classs_marks_and_another_terms_papers_are_not_counted(self):
        with connected_to(self.stmarys):
            self.mark_everything()
            self.mark(self.first_ca, self.bimpe)
            Assessment.objects.create(
                term=self.second_term, subject=self.maths, name="First CA", max_score=20
            )
            self.assertEqual(unmarked.for_class(self.jss1a, self.term_now()), [])
            self.assertEqual(
                [(s.subject, s.unmarked) for s in unmarked.for_class(self.jss1b, self.term_now())],
                [("Mathematics", 1)],
            )

    def test_each_school_counts_its_own(self):
        """Grace: one child, one paper, marked. St Mary's: seven unmarked."""
        with connected_to(self.grace):
            self.mark(self.grace_ca, self.grace_child)
            self.assertEqual(
                unmarked.for_class(
                    ClassGroup.objects.get(pk=self.grace_group_id),
                    Term.objects.get(pk=self.grace_term_id),
                ),
                [],
            )
        with connected_to(self.stmarys):
            self.assertEqual(unmarked.total(unmarked.for_class(self.jss1a, self.term_now())), 7)


class AStepSaysWhatIsUnmarkedTests(UnmarkedSetUp):
    def test_a_whole_class_goes_through_with_nothing_said_and_logs_nought(self):
        """The control: the warning is about unmarked papers, not about steps."""
        with connected_to(self.stmarys):
            self.mark_everything()
            self.walk("approved")
            self.assertEqual(
                self.log(), [("submitted", 0), ("checked", 0), ("approved", 0)]
            )

    def test_submitting_is_refused_with_the_count_per_subject(self):
        with connected_to(self.stmarys):
            sheet = self.sheet()
            with self.assertRaises(services.UnmarkedPapers) as refused:
                services.submit(sheet, self.teacher.user)

            self.assertEqual(refused.exception.total, 7)
            self.assertEqual(
                [(s.subject, s.unmarked) for s in refused.exception.subjects],
                [("Mathematics", 7)],
            )
            self.assertIn("JSS 1A has 7 papers still unmarked: Mathematics 7.", str(refused.exception))
            self.assertIn("submit anyway", str(refused.exception))
            self.assertEqual(services.sheet_for(self.jss1a, self.term_now()).state, SheetState.DRAFT)
            self.assertEqual(self.log(), [])

    def test_anyway_with_the_count_goes_through_and_is_logged(self):
        with connected_to(self.stmarys):
            sheet = self.sheet()
            row = services.submit(sheet, self.teacher.user, unmarked=7)

            self.assertEqual(row.unmarked_papers, 7)
            self.assertEqual(self.log(), [("submitted", 7)])

    def test_checking_and_approving_ask_again_each_time(self):
        """Three signatures, three people shown the number, three rows."""
        with connected_to(self.stmarys):
            sheet = self.sheet()
            services.submit(sheet, self.teacher.user, unmarked=7)

            with self.assertRaises(services.UnmarkedPapers):
                services.check(sheet, self.vp.user)
            services.check(sheet, self.vp.user, unmarked=7)

            with self.assertRaises(services.UnmarkedPapers) as refused:
                services.approve(sheet, self.head.user)
            self.assertIn("approve anyway", str(refused.exception))
            services.approve(sheet, self.head.user, unmarked=7)

            self.assertEqual(
                self.log(), [("submitted", 7), ("checked", 7), ("approved", 7)]
            )

    def test_a_count_that_is_not_the_count_is_refused_with_the_right_one(self):
        """A stale number, a guess, nought, and `True` standing for one."""
        with connected_to(self.stmarys):
            sheet = self.sheet()
            for wrong in (6, 8, 0, True, "7"):
                with self.subTest(wrong=wrong):
                    with self.assertRaises(services.UnmarkedPapers) as refused:
                        services.submit(sheet, self.teacher.user, unmarked=wrong)
                    self.assertEqual(refused.exception.total, 7)
            self.assertEqual(self.log(), [])

    def test_true_does_not_stand_for_one(self):
        with connected_to(self.stmarys):
            self.mark_everything()
            Score.objects.filter(
                assessment=self.exam, student_membership_id=self.children["ada"].pk
            ).delete()
            with self.assertRaises(services.UnmarkedPapers) as refused:
                services.submit(self.sheet(), self.teacher.user, unmarked=True)
            self.assertEqual(refused.exception.total, 1)
            self.assertIn("1 paper still unmarked", str(refused.exception))

    def test_a_mark_entered_after_the_warning_changes_the_number_needed(self):
        with connected_to(self.stmarys):
            sheet = self.sheet()
            with self.assertRaises(services.UnmarkedPapers):
                services.submit(sheet, self.teacher.user)
            self.mark(self.first_ca, self.children["bisi"])

            with self.assertRaises(services.UnmarkedPapers) as refused:
                services.submit(sheet, self.teacher.user, unmarked=7)
            self.assertEqual(refused.exception.total, 6)
            self.assertEqual(services.submit(sheet, self.teacher.user, unmarked=6).unmarked_papers, 6)

    def test_somebody_who_may_not_take_the_step_is_not_shown_the_count(self):
        """Authority and state are asked first. The bursar learns nothing."""
        with connected_to(self.stmarys):
            sheet = self.sheet()
            with self.assertRaises(services.NotAllowedToActOnResults):
                services.submit(sheet, self.bursar.user)
            with self.assertRaises(services.WrongState):
                services.approve(sheet, self.head.user)

    def test_a_send_back_and_a_release_count_nothing(self):
        with connected_to(self.stmarys):
            sheet = self.sheet()
            services.submit(sheet, self.admin.user, unmarked=7)
            self.send_back(sheet)
            services.submit(sheet, self.admin.user, unmarked=7)
            services.check(sheet, self.vp.user, unmarked=7)
            services.approve(sheet, self.head.user, unmarked=7)
            services.release(sheet, self.head.user)

            self.assertEqual(
                self.log(),
                [
                    ("submitted", 7),
                    ("draft", None),
                    ("submitted", 7),
                    ("checked", 7),
                    ("approved", 7),
                    ("released", None),
                ],
            )

    def test_the_other_schools_unmarked_papers_are_not_ours(self):
        """St Mary's is whole. Grace, under the same ids, has one unmarked."""
        with connected_to(self.grace):
            group = ClassGroup.objects.get(pk=self.grace_group_id)
            term = Term.objects.get(pk=self.grace_term_id)
            academics.place_student(group, term, self.their_newcomer)
            self.mark(self.grace_ca, self.grace_child)
        with connected_to(self.stmarys):
            self.mark_everything()
            self.assertEqual(
                services.submit(self.sheet(), self.teacher.user).unmarked_papers, 0
            )
        with connected_to(self.grace):
            sheet = services.open_sheet(group, term, self.their_head.user)
            with self.assertRaises(services.UnmarkedPapers) as refused:
                services.submit(sheet, self.grace_teacher.user)
            self.assertEqual(refused.exception.total, 1)


class TheChainRoutesSayItTooTests(UnmarkedSetUp):
    def step(self, member, step, host=HOST, group_id=None, **payload):
        return self.as_(member).post(
            f"/api/results/chain/{group_id or self.jss1a_id}/{step}/",
            data=payload,
            content_type="application/json",
            HTTP_HOST=host,
        )

    def test_a_step_without_the_count_answers_428_and_moves_nothing(self):
        response = self.step(self.teacher, "submit")

        self.assertEqual(response.status_code, 428)
        body = response.json()
        self.assertEqual(body["code"], "unmarked_papers")
        self.assertEqual(body["unmarked"], 7)
        self.assertEqual(body["subjects"], [{"subject": "Mathematics", "unmarked": 7}])
        self.assertIn("7 papers still unmarked", body["detail"])
        with connected_to(self.stmarys):
            self.assertEqual(services.sheet_for(self.jss1a, self.term_now()).state, SheetState.DRAFT)
            self.assertEqual(self.log(), [])

    def test_a_request_with_no_body_at_all_is_the_same_428(self):
        self.client.force_login(self.teacher.user)
        response = self.client.post(
            f"/api/results/chain/{self.jss1a_id}/submit/", HTTP_HOST=HOST
        )
        self.assertEqual(response.status_code, 428)

    def test_the_count_sent_back_walks_the_chain_and_is_logged(self):
        self.assertEqual(self.step(self.teacher, "submit", unmarked=7).status_code, 200)
        self.assertEqual(self.step(self.vp, "check").status_code, 428)
        self.assertEqual(self.step(self.vp, "check", unmarked=7).status_code, 200)
        self.assertEqual(self.step(self.head, "approve").status_code, 428)
        approved = self.step(self.head, "approve", unmarked=7)

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["state"], SheetState.APPROVED)
        with connected_to(self.stmarys):
            self.assertEqual(
                self.log(), [("submitted", 7), ("checked", 7), ("approved", 7)]
            )

    def test_the_wrong_count_is_a_428_with_the_right_one(self):
        response = self.step(self.teacher, "submit", unmarked=3)

        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.json()["unmarked"], 7)

    def test_a_count_that_is_not_a_whole_number_is_nothing_seen(self):
        for junk in ("7", True, 7.0, None, [7]):
            with self.subTest(junk=junk):
                self.assertEqual(self.step(self.teacher, "submit", unmarked=junk).status_code, 428)
        with connected_to(self.stmarys):
            self.assertEqual(self.log(), [])

    def test_a_whole_class_is_a_plain_200(self):
        with connected_to(self.stmarys):
            self.mark_everything()
        self.assertEqual(self.step(self.teacher, "submit").status_code, 200)

    def test_a_login_with_no_part_in_the_chain_is_a_403_not_a_count(self):
        response = self.step(self.bursar, "submit")

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("unmarked", response.json())

    def test_grace_is_told_grace_s_count_and_never_ours(self):
        with connected_to(self.grace):
            academics.place_student(
                ClassGroup.objects.get(pk=self.grace_group_id),
                Term.objects.get(pk=self.grace_term_id),
                self.their_newcomer,
            )
            self.mark(self.grace_ca, self.grace_child)

        response = self.step(
            self.grace_teacher, "submit", host=THEIR_HOST, group_id=self.grace_group_id
        )

        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.json()["unmarked"], 1)
