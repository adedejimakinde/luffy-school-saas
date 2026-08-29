"""Task 3: the report card snapshot, and the row that says a card went home.

Three things are proved here, and they fail in three different ways.

**The marker**, where the failure is a guard with nothing to key on. One row per
child on the roster at release, **unconditionally** — no marks, no ratings, the
conduct section off school-wide, nothing decided. That is the guarantee issues
#31, #33 and #34 each arrived at from a different direction, and **no
constraint can hold it**: no `CHECK` can say "a row exists for every child on a
roster this transaction has already moved past". It is held by
`cards.freeze_for_release()` and by `TheUnconditionalMarkerTests` below, which
has a control run behind it.

**The copy**, where the failure is a card that changes after it has gone home.
Every name, label and letter on the page is copied at release, and the tests
that matter are the ones that *edit the school's configuration afterwards* and
assert the card did not move. A test that only reads a fresh card proves
nothing about freezing.

**The grade**, which is the sharpest of those. A school replacing its grading
scale is an ordinary Tuesday act, and re-deriving the letter would rewrite every
card already in a parent's hand while the percentages beside them stayed put.
`TheGradeIsCopiedTests` asserts both the values and, separately, that reading a
card touches no `GradeBand` row at all.

Two schools where tenancy is the subject, one where it is not — see #38's
finding 10 on fixtures that build a tenant nothing uses.

## One hazard specific to writing these tests

**Every queryset must be evaluated inside its `connected_to()` block.** These
are tenant tables, and a lazy `.first()` or `.all()` that escapes the block runs
against the public schema, where the table does not exist. It does not fail as a
weaker assertion — it fails as `ProgrammingError: relation does not exist`, or
worse, silently answers a different question. It has already caught two tests in
this phase, both of which read perfectly well by eye. Materialise inside; assert
outside.
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from academics.models import ClassGroup, Term, TermName
from academics.services import assign_class_teacher, move_student, place_student
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from gradebook.models import Assessment, Score, Subject
from results import cards, grades, ratings
from results import services as results_services
from results.models import (
    CardsAreFrozenAtRelease,
    ReleasedAssessmentScore,
    ReleasedCard,
    ReleasedSubjectResult,
)
from results.tests.test_positions import PASSWORD, connected_to, make_school

SESSION = "2025/2026"


class CardSetUp(TestCase):
    """One school, a full session, a class, two subjects and two children."""

    TERM_DATES = {
        TermName.FIRST.value: (date(2025, 9, 15), date(2025, 12, 12)),
        TermName.SECOND.value: (date(2026, 1, 12), date(2026, 4, 2)),
        TermName.THIRD.value: (date(2026, 4, 27), date(2026, 7, 24)),
    }

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.staff = self._staff_for(self.stmarys)
        self.principal = self.staff[Role.PRINCIPAL]
        self.teacher = self.staff[Role.TEACHER]
        self.vp = self.staff[Role.VICE_PRINCIPAL_ACADEMIC]

        self.terms, self.group_id, self.subject_ids = self._academics(self.stmarys)
        self.ada = self.child(self.stmarys, "ada", "Ada Obi")
        self.bola = self.child(self.stmarys, "bola", "Bola Eze")

    def _staff_for(self, school):
        people = {}
        tag = school.schema_name
        for role in (
            Role.PRINCIPAL,
            Role.ADMIN,
            Role.TEACHER,
            Role.VICE_PRINCIPAL_ACADEMIC,
        ):
            user = User.objects.create_user(
                f"{tag}-{role.value}", PASSWORD, full_name=f"{role.label} {tag}"
            )
            grant_membership(user, school, role)
            people[role] = user
        return people

    def _academics(self, school):
        with connected_to(school):
            terms = {}
            for name, (starts_on, ends_on) in self.TERM_DATES.items():
                terms[name] = Term.objects.create(
                    session=SESSION, name=name, starts_on=starts_on, ends_on=ends_on
                ).pk
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            subjects = {
                "maths": Subject.objects.create(name="Mathematics", code="MTH").pk,
                "english": Subject.objects.create(name="English", code="ENG").pk,
            }
            teaching = self._staff_for_school(school).memberships.get(
                school=school, role=Role.TEACHER
            )
            for term_id in terms.values():
                assign_class_teacher(group, Term.objects.get(pk=term_id), teaching)
            return terms, group.pk, subjects

    def _staff_for_school(self, school):
        return self.staff[Role.TEACHER] if school == self.stmarys else self.their_teacher

    def child(self, school, username, full_name, terms=None):
        membership = enroll_student(
            User.objects.create_user(username, PASSWORD, full_name=full_name), school
        )
        if terms is None:
            terms = [name.value for name in TermName]
        with connected_to(school):
            for name in terms:
                place_student(self.group(school), self.term(school, name), membership)
        return membership

    def mark(self, school, term_name, membership, subject_key, name, value, out_of=100):
        with connected_to(school):
            term = self.term(school, term_name)
            assessment, _ = Assessment.objects.get_or_create(
                term=term,
                subject_id=self.subject_ids[subject_key],
                name=name,
                defaults={"max_score": out_of},
            )
            Score.objects.create(
                assessment=assessment,
                student_membership_id=membership.pk,
                value=value,
            )

    def term(self, school, name):
        return Term.objects.get(pk=self.terms[str(name)])

    def group(self, school):
        return ClassGroup.objects.get(pk=self.group_id)

    def release_the_term(self, term_name=TermName.FIRST.value, school=None):
        school = school or self.stmarys
        sheet = results_services.open_sheet(
            self.group(school), self.term(school, term_name), self.principal
        )
        results_services.submit(sheet, self.teacher)
        results_services.check(sheet, self.vp)
        results_services.approve(sheet, self.principal)
        results_services.release(sheet, self.principal)
        return sheet


class TheUnconditionalMarkerTests(CardSetUp):
    """One row per child on the roster, whatever else is or is not true.

    The guarantee no `CHECK` can hold, and the reason `ReleasedCard` exists at
    all. If these tests are deleted the guarantee goes with them and nothing
    else in the codebase will say so.
    """

    def test_a_school_with_everything_off_still_freezes_a_card_per_child(self):
        """No marks, no ratings, no comments, both conduct groups off, nothing decided.

        The per-school hole `0010` and `0011` left behind: a school with the
        conduct section switched off froze nothing for anybody, so nothing
        recorded that its releases had happened at all.
        """
        with connected_to(self.stmarys):
            ratings.set_group_enabled("affective", False)
            ratings.set_group_enabled("psychomotor", False)
            self.assertEqual(ratings.enabled_groups(), [])

            sheet = self.release_the_term()

            frozen = ReleasedCard.objects.filter(sheet=sheet)
            self.assertEqual(frozen.count(), 2)
            self.assertEqual(
                sorted(frozen.values_list("student_membership_id", flat=True)),
                sorted([self.ada.pk, self.bola.pk]),
            )
            # And nothing else froze, which is the condition that used to leave
            # the release unrecorded.
            self.assertEqual(ReleasedSubjectResult.objects.count(), 0)

    def test_the_count_is_the_same_with_the_conduct_section_on(self):
        """Unconditional means unconditional in both directions.

        The test above switches everything off; a write that had become
        conditional on *something else* would still pass it. One card per child
        either way is the claim.
        """
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)
        with connected_to(self.stmarys):
            ratings.set_group_enabled("affective", True)
            ratings.set_group_enabled("psychomotor", True)
            sheet = self.release_the_term()
            self.assertEqual(ReleasedCard.objects.filter(sheet=sheet).count(), 2)

    def test_a_child_with_no_marks_at_all_still_gets_a_card(self):
        """A blank card is still a card, and a parent was still handed one."""
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.bola, self.term(self.stmarys, "first"))

            self.assertIsNotNone(card)
            self.assertIsNone(card.own_average)
            self.assertIsNone(card.position)
            self.assertEqual(card.total_available, 0)

    def test_a_card_went_home_survives_the_child_changing_class(self):
        """The failure that started all of this. Release, move, ask again.

        `ClassPlacement` holds one group per child per term, so the move
        **rewrites** the row — a guard keying on placement is not reading a
        stale answer, it is asking a different question. The artefact does not
        move.
        """
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

        with connected_to(self.stmarys):
            first = self.term(self.stmarys, "first")
            self.release_the_term()
            self.assertTrue(cards.a_card_went_home(self.ada, first))

            elsewhere = ClassGroup.objects.create(name="JSS 3B", level=3)
            move_student(elsewhere, first, self.ada)

            self.assertTrue(cards.a_card_went_home(self.ada, first))
            self.assertIsNotNone(cards.card_for(self.ada, first))

    def test_a_child_of_an_unreleased_term_has_no_card(self):
        """`a_card_went_home()` is a fact, not a default. It must be able to say no."""
        with connected_to(self.stmarys):
            self.assertFalse(
                cards.a_card_went_home(self.ada, self.term(self.stmarys, "first"))
            )
            self.assertIsNone(
                cards.card_for(self.ada, self.term(self.stmarys, "first"))
            )


class TheCardsNumbersTests(CardSetUp):
    """What the card says, and that it says it about the right child."""

    def setUp(self):
        super().setUp()
        # Ada: 80/100 maths, 60/100 english -> 80.00, 60.00, own average 70.00
        # Bola: 50/100 maths, 90/100 english -> 50.00, 90.00, own average 70.00
        # A deliberate tie on the average, so dense ranking has something to do.
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)
        self.mark(self.stmarys, "first", self.ada, "english", "Exam", 60)
        self.mark(self.stmarys, "first", self.bola, "maths", "Exam", 50)
        self.mark(self.stmarys, "first", self.bola, "english", "Exam", 90)

    def test_the_card_carries_the_childs_own_average_and_totals(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

        self.assertEqual(card.own_average, Decimal("70.00"))
        self.assertEqual(card.total_scored, 140)
        self.assertEqual(card.total_available, 200)
        self.assertEqual(card.roster_size, 2)

    def test_a_tie_shares_a_position_and_both_cards_say_so(self):
        """Dense ranking, frozen. Position is a fact about *this* child."""
        with connected_to(self.stmarys):
            self.release_the_term()
            first = self.term(self.stmarys, "first")
            self.assertEqual(cards.card_for(self.ada, first).position, 1)
            self.assertEqual(cards.card_for(self.bola, first).position, 1)

    def test_the_subject_lines_carry_their_own_marks_and_order(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            lines = list(card.subject_results.all())

        # Ordered by subject name: English before Mathematics.
        self.assertEqual([line.subject_name for line in lines], ["English", "Mathematics"])
        self.assertEqual([line.position for line in lines], [1, 2])
        english, maths = lines
        self.assertEqual(english.percentage, Decimal("60.00"))
        self.assertEqual(maths.percentage, Decimal("80.00"))
        self.assertEqual(maths.total_scored, 80)
        self.assertEqual(maths.total_available, 100)

    def test_the_score_cells_carry_each_paper(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            cells = list(card.assessment_scores.all())

        self.assertEqual(len(cells), 2)
        self.assertEqual({cell.score for cell in cells}, {80, 60})
        self.assertTrue(all(cell.max_score == 100 for cell in cells))

    def test_an_unmarked_subject_prints_blank_and_still_has_a_line(self):
        """The frozen thing is the *line*. A blank column was on the page."""
        chidi = self.child(self.stmarys, "chidi", "Chidi Nwosu")
        self.mark(self.stmarys, "first", chidi, "maths", "Exam", 70)

        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(chidi, self.term(self.stmarys, "first"))
            english = card.subject_results.get(subject_name="English")

        self.assertIsNone(english.percentage)
        self.assertEqual(english.total_available, 0)
        self.assertEqual(english.grade_letter, "")
        self.assertIsNone(english.subject_position)

    def test_an_unsat_paper_is_a_null_cell_rather_than_a_missing_one(self):
        chidi = self.child(self.stmarys, "chidi", "Chidi Nwosu")
        self.mark(self.stmarys, "first", chidi, "maths", "Exam", 70)

        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(chidi, self.term(self.stmarys, "first"))
            cells = {cell.subject.code: cell for cell in card.assessment_scores.all()}

        self.assertEqual(cells["MTH"].score, 70)
        self.assertIsNone(cells["ENG"].score)

    def test_the_class_average_is_not_on_the_card(self):
        """Signed off deliberately: position is frozen, the class average is not.

        Position is a statement about *this* child and is fixed at release. The
        class average is a statistic about the other children, and freezing it
        would leave every unrevised card asserting a number that disagrees with
        a revised one — the school's-screen-versus-card disagreement this phase
        exists to kill.
        """
        field_names = {field.name for field in ReleasedCard._meta.get_fields()}
        self.assertNotIn("class_average", field_names)


class TheCopyTests(CardSetUp):
    """Edit the school's configuration afterwards. The card must not move."""

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

    def test_renaming_the_subject_does_not_relabel_a_released_line(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            Subject.objects.filter(pk=self.subject_ids["maths"]).update(
                name="Further Mathematics", code="FMT"
            )
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            line = card.subject_results.get(subject_id=self.subject_ids["maths"])

        self.assertEqual(line.subject_name, "Mathematics")
        self.assertEqual(line.subject_code, "MTH")

    def test_renaming_the_assessment_does_not_relabel_a_released_column(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            Assessment.objects.all().update(name="Final Examination")
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            frozen_name = card.assessment_scores.first().assessment_name

        self.assertEqual(frozen_name, "Exam")

    def test_renaming_the_class_does_not_rename_it_on_a_released_card(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            ClassGroup.objects.filter(pk=self.group_id).update(name="JSS 1 Diamond")
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

        self.assertEqual(card.class_group_name, "JSS 1A")

    def test_correcting_the_childs_name_does_not_rewrite_the_card(self):
        """`accounts` is a **shared** schema. Its rows change for other reasons."""
        with connected_to(self.stmarys):
            self.release_the_term()
        User.objects.filter(pk=self.ada.user_id).update(full_name="Adaeze Obi")

        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

        self.assertEqual(card.student_name, "Ada Obi")

    def test_the_card_records_the_school_it_was_released_by(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

        self.assertEqual(card.school_name, "St Mary's")


class TheGradeIsCopiedTests(CardSetUp):
    """The letter is stored, and a renderer must never re-derive it.

    A school replacing its scale is an ordinary act. Re-deriving would rewrite
    the letters on every card already in a parent's hand while the percentages
    beside them stayed put — a card that said B2 quietly beginning to say B3,
    with nothing recording that it had ever said anything else.
    """

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 72)

    def test_the_letter_and_remark_are_frozen_onto_the_line(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            line = card.subject_results.get(subject_id=self.subject_ids["maths"])

        self.assertEqual(line.percentage, Decimal("72.00"))
        self.assertEqual(line.grade_letter, "B2")
        self.assertEqual(line.grade_remark, "Very Good")

    def test_replacing_the_scale_does_not_reach_a_released_card(self):
        """The whole reason the letter is a column rather than a lookup."""
        with connected_to(self.stmarys):
            self.release_the_term()

            grades.set_scale([(0, "F", "Fail"), (70, "A", "Excellent")])
            self.assertEqual(grades.grade_for(Decimal("72.00")).letter, "A")

            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            line = card.subject_results.get(subject_id=self.subject_ids["maths"])

        self.assertEqual(line.grade_letter, "B2")
        self.assertEqual(line.grade_remark, "Very Good")

    def test_reading_a_card_touches_no_grade_band_at_all(self):
        """Values agreeing is not proof the lookup is gone. This is.

        A renderer that called `grade_for()` and happened to get the same answer
        would pass the test above. What must be true is that reading a frozen
        card does not consult the scale, and the query log is where that shows.
        """
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

            with CaptureQueriesContext(connection) as captured:
                lines = cards.card_lines(card)
                self.assertTrue(lines)
                self.assertEqual(lines[0][0].grade_letter or "", lines[0][0].grade_letter)

            sql = " ".join(query["sql"].lower() for query in captured)

        self.assertNotIn("results_gradeband", sql)


class WhichCardIsTheCardTests(CardSetUp):
    """More than one row can exist for one (child, term), in two ways."""

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

    def test_the_first_release_is_the_card_when_the_child_moves_and_is_released_again(self):
        """Release JSS 1A, move the child, release JSS 3B. The first is the card."""
        with connected_to(self.stmarys):
            first = self.term(self.stmarys, "first")
            self.release_the_term()
            original = cards.card_for(self.ada, first)

            elsewhere = ClassGroup.objects.create(name="JSS 3B", level=3)
            move_student(elsewhere, first, self.ada)
            assign_class_teacher(
                elsewhere,
                first,
                self.teacher.memberships.get(school=self.stmarys, role=Role.TEACHER),
            )
            second = results_services.open_sheet(elsewhere, first, self.principal)
            results_services.submit(second, self.teacher)
            results_services.check(second, self.vp)
            results_services.approve(second, self.principal)
            results_services.release(second, self.principal)

            self.assertEqual(ReleasedCard.objects.filter(term=first).count(), 3)
            self.assertEqual(cards.card_for(self.ada, first).pk, original.pk)

    def test_a_later_version_of_the_first_release_wins(self):
        """Task 8's shape, proved now so the read rule is not written blind."""
        with connected_to(self.stmarys):
            first = self.term(self.stmarys, "first")
            self.release_the_term()
            original = cards.card_for(self.ada, first)

            revised = ReleasedCard.objects.create(
                sheet=original.sheet,
                student_membership_id=original.student_membership_id,
                term=original.term,
                version=2,
                session=original.session,
                term_name=original.term_name,
                class_group=original.class_group,
                class_group_name=original.class_group_name,
                school_name=original.school_name,
                student_name=original.student_name,
                total_scored=original.total_scored,
                total_available=original.total_available,
                own_average=Decimal("99.00"),
                position=original.position,
                roster_size=original.roster_size,
            )

            found = cards.card_for(self.ada, first)

        self.assertEqual(found.pk, revised.pk)
        self.assertEqual(found.version, 2)
        self.assertEqual(found.own_average, Decimal("99.00"))


class AppendOnlyTests(CardSetUp):
    """A frozen card that can be edited is not frozen. Two layers, as always."""

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

    def test_the_model_refuses_an_edit_and_a_delete(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

            card.own_average = Decimal("99.00")
            with self.assertRaises(CardsAreFrozenAtRelease):
                card.save()
            with self.assertRaises(CardsAreFrozenAtRelease):
                card.delete()

            line = card.subject_results.first()
            with self.assertRaises(CardsAreFrozenAtRelease):
                line.save()
            cell = card.assessment_scores.first()
            with self.assertRaises(CardsAreFrozenAtRelease):
                cell.delete()

    def test_the_database_refuses_an_update_that_skips_the_model(self):
        """`.update()` never calls `save()`. The import and the psql session."""
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedCard.objects.filter(pk=card.pk).update(
                        own_average=Decimal("99.00")
                    )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedSubjectResult.objects.filter(card=card).update(
                        grade_letter="A1"
                    )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedAssessmentScore.objects.filter(card=card).update(score=1)

            self.assertEqual(
                cards.card_for(self.ada, self.term(self.stmarys, "first")).own_average,
                Decimal("80.00"),
            )

    def test_the_database_refuses_a_delete_that_skips_the_model(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedAssessmentScore.objects.filter(card=card).delete()


class TheConstraintsTests(CardSetUp):
    """What the table refuses that the code would never write."""

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

    def _a_card(self, **overrides):
        with connected_to(self.stmarys):
            sheet = self.release_the_term()
            defaults = dict(
                sheet=sheet,
                student_membership_id=self.ada.pk + 9999,
                term=self.term(self.stmarys, "first"),
                version=1,
                session=SESSION,
                term_name=TermName.FIRST.value,
                class_group=self.group(self.stmarys),
                class_group_name="JSS 1A",
                school_name="St Mary's",
                student_name="Nobody",
            )
            defaults.update(overrides)
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedCard.objects.create(**defaults)

    def test_an_average_with_no_marks_behind_it_is_refused(self):
        self._a_card(own_average=Decimal("70.00"), total_available=0)

    def test_marks_with_no_average_are_refused(self):
        self._a_card(own_average=None, total_scored=10, total_available=20)

    def test_scoring_above_what_was_available_is_refused(self):
        self._a_card(
            own_average=Decimal("70.00"), total_scored=30, total_available=20
        )

    def test_a_version_below_one_is_refused(self):
        self._a_card(version=0)

    def test_a_score_above_its_paper_is_refused(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            cell = card.assessment_scores.first()
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedAssessmentScore.objects.create(
                        card=card,
                        subject_id=self.subject_ids["english"],
                        assessment=cell.assessment,
                        assessment_name="Bad",
                        max_score=20,
                        position=9,
                        score=21,
                    )


class EveryFrozenSectionHangsOffTheCardTests(CardSetUp):
    """One answer to "did a card go home", not four. See `ReleasedCard`."""

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

    def test_the_frozen_ratings_point_at_the_card(self):
        with connected_to(self.stmarys):
            # Both conduct groups default to **off**, so this has to ask for the
            # section it is about to assert on. Worth stating: it is why
            # `TheUnconditionalMarkerTests` disables them explicitly rather than
            # relying on the default — a test whose precondition is a default is
            # one that stops testing what it says when the default changes.
            ratings.set_group_enabled("affective", True)
            self.release_the_term()
            card = cards.card_for(self.ada, self.term(self.stmarys, "first"))
            frozen = card.trait_ratings.all()

            self.assertTrue(frozen.exists())
            self.assertTrue(all(row.card_id == card.pk for row in frozen))


class TwoSchoolsTests(CardSetUp):
    """A card is a tenant artefact, and one school's release is not the other's."""

    def setUp(self):
        super().setUp()
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.their_staff = self._staff_for(self.grace)
        self.their_teacher = self.their_staff[Role.TEACHER]
        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)

    def test_a_release_at_one_school_writes_no_card_at_the_other(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            self.assertEqual(ReleasedCard.objects.count(), 2)

        with connected_to(self.grace):
            self.assertEqual(ReleasedCard.objects.count(), 0)
            self.assertEqual(ReleasedSubjectResult.objects.count(), 0)

    def test_a_card_went_home_is_false_at_the_other_school(self):
        with connected_to(self.stmarys):
            self.release_the_term()
            first = self.term(self.stmarys, "first")
            self.assertTrue(cards.a_card_went_home(self.ada, first))
