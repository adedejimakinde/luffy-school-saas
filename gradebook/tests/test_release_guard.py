"""Issue #27: the approval chain and the gradebook were never introduced.

`grep -rn "ResultSheet" gradebook/` returned nothing, and `set_score()` asked
two questions — is this our student, and can this assessment hold this mark —
neither of which was *has this term's results already been checked, approved or
released*. So a mark could be changed at any point after the chain left
`draft`, and the serious case is the last one: a parent holding a card the
database now disagrees with, with no revision and no audit row.

`results` spends two database guards and a long docstring making release
terminal — `nothing_moves_out_of_released` on the log, and `0003`'s trigger on
the sheet — and neither was in the way of the write that actually changes what
the card says. The chain's promise is "this is what was released"; it held for
the sheet's **state** and not for its **contents**.

**One rule covers all four states**, because "writable while the sheet is
absent or in `draft`" is the same sentence `ratings` already enforces. The
tests below walk the chain one step at a time rather than testing `released`
alone: a guard that caught release and let `submitted` through would pass a
smaller test, and the vice principal checking a sheet that moves underneath
them is the case nobody notices until a mark is wrong.

**Two layers, asserted separately.** The service refuses at every state past
`draft`; migration `0002` refuses the `released` case in the database, narrow
on purpose, and is reached here by `.update()` and `.delete()` — the callers
that skip the service, which is exactly the import and the `psql` session the
issue names.
"""

from django.db import IntegrityError, transaction

from academics.models import ClassGroup, Term
from academics.services import assign_class_teacher, move_student
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from gradebook import services
from gradebook.models import Assessment, Score
from results import services as results_services
from results.tests.test_positions import (
    PASSWORD,
    PositionSetUp,
    connected_to,
)


class TheChainReachesTheMarksTests(PositionSetUp):
    """Walk the sheet one state at a time and watch the marks shut."""

    def setUp(self):
        super().setUp()
        self.ada = self.enrol(
            self.stmarys, "ada", "Ada Obi", self.group_id, self.term_id
        )
        self.kemi = self._staff("kemi", "Kemi Bello", Role.TEACHER)
        self.vp = self._staff("ify", "Ify Nwosu", Role.VICE_PRINCIPAL_ACADEMIC)

        with connected_to(self.stmarys):
            assign_class_teacher(
                ClassGroup.objects.get(pk=self.group_id),
                Term.objects.get(pk=self.term_id),
                self.kemi.memberships.get(school=self.stmarys, role=Role.TEACHER),
            )
            self.first_ca_id = Assessment.objects.create(
                term=Term.objects.get(pk=self.term_id),
                subject_id=self.maths_id,
                name="First CA",
                max_score=20,
            ).pk

    # -- fixtures ------------------------------------------------------------

    def _staff(self, username, full_name, role):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, self.stmarys, role)
        return user

    def first_ca(self):
        return Assessment.objects.get(pk=self.first_ca_id)

    def term(self):
        return Term.objects.get(pk=self.term_id)

    def group(self):
        return ClassGroup.objects.get(pk=self.group_id)

    def mark_ada(self, value=15, expected_version=None):
        return services.set_score(
            self.first_ca(), self.ada, value, expected_version=expected_version
        )

    def ada_score(self):
        return (
            Score.objects.filter(
                assessment_id=self.first_ca_id, student_membership_id=self.ada.pk
            )
            .values_list("value", flat=True)
            .first()
        )

    def open_sheet(self):
        return results_services.open_sheet(self.group(), self.term(), self.principal)

    def walk_to(self, state):
        """Take the sheet as far as `state`, with the right person at each step."""
        sheet = self.open_sheet()
        if state == "draft":
            return sheet
        results_services.submit(sheet, self.kemi)
        if state == "submitted":
            return sheet
        results_services.check(sheet, self.vp)
        if state == "checked":
            return sheet
        results_services.approve(sheet, self.principal)
        if state == "approved":
            return sheet
        results_services.release(sheet, self.principal)
        return sheet

    # -- the service half ----------------------------------------------------

    def test_a_mark_can_be_entered_while_the_sheet_is_a_draft(self):
        """The control. The guard must not shut the ordinary case."""
        with connected_to(self.stmarys):
            self.walk_to("draft")
            self.assertEqual(self.mark_ada().value, 15)

    def test_a_mark_can_be_entered_before_anybody_opens_a_sheet(self):
        """No sheet is open, not closed — marking starts before the chain does."""
        with connected_to(self.stmarys):
            self.assertEqual(self.mark_ada().value, 15)

    def test_every_state_past_draft_shuts_the_marks(self):
        """One rule, four states, and `released` is not the only one that matters.

        A guard that caught release alone would let the vice principal check a
        sheet moving underneath them, which is the case nobody notices until a
        mark is wrong. Walked forward once rather than re-opened per state:
        `open_sheet()` refuses a class that already has one, and the states are
        a sequence rather than a set.
        """
        with connected_to(self.stmarys):
            sheet = self.open_sheet()
            steps = (
                ("submitted", lambda: results_services.submit(sheet, self.kemi)),
                ("checked", lambda: results_services.check(sheet, self.vp)),
                ("approved", lambda: results_services.approve(sheet, self.principal)),
                ("released", lambda: results_services.release(sheet, self.principal)),
            )
            for state, advance in steps:
                advance()
                with self.subTest(state=state):
                    with self.assertRaises(services.MarksLocked) as refused:
                        self.mark_ada()
                    self.assertEqual(refused.exception.state, state)

    def test_the_refusal_says_which_state_it_is(self):
        """A teacher reads this. "Being reviewed" and "went home" differ."""
        with connected_to(self.stmarys):
            self.walk_to("submitted")
            with self.assertRaises(services.MarksLocked) as refused:
                self.mark_ada()
            self.assertIn("being reviewed", str(refused.exception))

    def test_a_released_sheet_says_revision_not_review(self):
        with connected_to(self.stmarys):
            self.walk_to("released")
            with self.assertRaises(services.MarksLocked) as refused:
                self.mark_ada()
            self.assertIn("revision", str(refused.exception))

    def test_a_send_back_opens_the_marks_again(self):
        """The reason the test is `draft` and not "has never been submitted"."""
        with connected_to(self.stmarys):
            sheet = self.walk_to("submitted")
            results_services.send_back(sheet, self.vp, "A mark looks wrong.")

            self.assertEqual(self.mark_ada().value, 15)

    def test_changing_an_existing_mark_is_refused_too(self):
        """The issue's actual case: not a new mark, a corrected one."""
        with connected_to(self.stmarys):
            existing = self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(services.MarksLocked):
                services.set_score(
                    self.first_ca(), self.ada, 3, expected_version=existing.version
                )
            self.assertEqual(self.ada_score(), 15)

    def test_clearing_a_mark_is_refused_too(self):
        """`clear_score()` deletes, which is the same edit by another name."""
        with connected_to(self.stmarys):
            existing = self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(services.MarksLocked):
                services.clear_score(
                    self.first_ca(), self.ada, expected_version=existing.version
                )
            self.assertEqual(self.ada_score(), 15)

    def test_a_child_with_no_placement_is_not_refused(self):
        """Marking never required a placement, and this does not add that rule.

        No placement means no class, which means no sheet governs the mark.
        There is nothing the guard could be checking against, and refusing here
        would be inventing a requirement under cover of a bug fix.
        """
        unplaced = enroll_student(
            User.objects.create_user("bisi", PASSWORD, full_name="Bisi Lawal"),
            self.stmarys,
        )
        with connected_to(self.stmarys):
            self.walk_to("released")

            self.assertEqual(
                services.set_score(self.first_ca(), unplaced, 12).value, 12
            )

    def test_another_classs_sheet_does_not_shut_ours(self):
        """The lock is per class group, not per term.

        JSS 3B goes the whole way while JSS 1A has no sheet at all. If the guard
        keyed on the term it would shut a class nobody has finished marking.
        """
        sade = self._staff("sade", "Sade Johnson", Role.TEACHER)
        with connected_to(self.stmarys):
            other = ClassGroup.objects.create(name="JSS 3B", level=3)
            assign_class_teacher(
                other,
                self.term(),
                sade.memberships.get(school=self.stmarys, role=Role.TEACHER),
            )
            theirs = results_services.open_sheet(other, self.term(), self.principal)
            results_services.submit(theirs, sade)
            results_services.check(theirs, self.vp)
            results_services.approve(theirs, self.principal)
            results_services.release(theirs, self.principal)

            self.assertEqual(self.mark_ada().value, 15)

    # -- the database half ---------------------------------------------------

    def test_the_database_refuses_an_update_after_release(self):
        """Reached by `.update()`, which no service guard sees."""
        with connected_to(self.stmarys):
            self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Score.objects.filter(
                        assessment_id=self.first_ca_id,
                        student_membership_id=self.ada.pk,
                    ).update(value=3)
            self.assertEqual(self.ada_score(), 15)

    def test_the_database_refuses_a_delete_after_release(self):
        with connected_to(self.stmarys):
            self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Score.objects.filter(
                        assessment_id=self.first_ca_id,
                        student_membership_id=self.ada.pk,
                    ).delete()
            self.assertEqual(self.ada_score(), 15)

    def test_the_database_refuses_a_new_mark_after_release(self):
        """INSERT too: a new mark for a released term is as wrong as an edit.

        And likelier — a teacher entering marks for a term that closed while
        their screen was open.
        """
        with connected_to(self.stmarys):
            self.walk_to("released")

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Score.objects.create(
                        assessment_id=self.first_ca_id,
                        student_membership_id=self.ada.pk,
                        value=9,
                    )

    def test_the_database_still_permits_a_draft_terms_marks(self):
        """The control for the trigger: narrow means narrow."""
        with connected_to(self.stmarys):
            self.walk_to("submitted")

            Score.objects.create(
                assessment_id=self.first_ca_id,
                student_membership_id=self.ada.pk,
                value=9,
            )
            self.assertEqual(self.ada_score(), 9)

    # -- the hole that is left ------------------------------------------------

    def test_the_moved_child_is_the_case_issue_34_closes(self):
        """Written down rather than denied, the way `0010` and `0011` are.

        `Score` reaches a class only through the placement, because one
        assessment is sat by every class taught that subject. So a child moved
        after release is looked up against the new class's draft and permitted,
        while the child who stayed put is refused. Asserted so that the day
        #34's per-child release marker lands, this fails and is deleted rather
        than quietly going stale.
        """
        with connected_to(self.stmarys):
            self.mark_ada()
            self.walk_to("released")
            other = ClassGroup.objects.create(name="JSS 3B", level=3)
            move_student(other, self.term(), self.ada)

            services.set_score(self.first_ca(), self.ada, 3, expected_version=1)
            self.assertEqual(self.ada_score(), 3)
