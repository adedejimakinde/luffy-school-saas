"""Position in class and in subject, and the three ways ranking goes wrong.

Two schools throughout, as everywhere in this project: a position is *out of a
class*, and the class roster comes from `academics.ClassPlacement`, so "did this
ranking reach into the other school's children" is a question only a second
tenant can ask.

The properties, one section each:

- dense ranking, where a tie does not consume the position below it;
- ties decided on the number as printed, not on an unrounded one;
- an unmarked child has no position rather than the last one;
- the overall average is the child's own across their subjects, not a weighted
  total and not the class's;
- half-way values round the same way whatever the ambient decimal context says,
  and whichever function a caller happens to reach for;
- a whole page comes from **one** read of the marks, so no two numbers on it
  are separated by an incoming mark.
"""

import contextlib
import decimal
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django_tenants.utils import schema_context

from academics.models import ClassGroup, Term, TermName
from academics.services import place_student
from accounts.models import Membership, Role, User
from accounts.services import enroll_student, grant_membership
from gradebook.models import Assessment, Score, Subject
from results import positions
from schools.models import School

PASSWORD = "correct-horse-battery"


def make_school(name, slug, schema_name):
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.save()
    return school


@contextlib.contextmanager
def connected_to(school):
    with schema_context(school.schema_name):
        yield


class PositionSetUp(TestCase):
    """St Mary's and Grace Academy, each with a JSS 1A and a term."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.principal = User.objects.create_user(
            "tunde", PASSWORD, full_name="Tunde Alabi"
        )
        grant_membership(self.principal, self.stmarys, Role.PRINCIPAL)
        self.their_principal = User.objects.create_user(
            "chidi", PASSWORD, full_name="Chidi Okafor"
        )
        grant_membership(self.their_principal, self.grace, Role.PRINCIPAL)

        self.term_id, self.group_id, self.maths_id, self.english_id = self._academics(
            self.stmarys
        )
        (
            self.their_term_id,
            self.their_group_id,
            self.their_maths_id,
            self.their_english_id,
        ) = self._academics(self.grace)

    def _academics(self, school):
        with connected_to(school):
            term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            maths = Subject.objects.create(name="Mathematics", code="MTH")
            english = Subject.objects.create(name="English", code="ENG")
            return term.pk, group.pk, maths.pk, english.pk

    def enrol(self, school, username, full_name, group_id, term_id):
        """A child of this school, placed in this class for this term."""
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        membership = enroll_student(user, school)
        with connected_to(school):
            place_student(
                ClassGroup.objects.get(pk=group_id),
                Term.objects.get(pk=term_id),
                membership,
            )
        return membership

    def mark(self, school, term_id, subject_id, membership, value, out_of=100):
        """One mark, in its own assessment so `out_of` is per call."""
        with connected_to(school):
            term = Term.objects.get(pk=term_id)
            assessment, _ = Assessment.objects.get_or_create(
                term=term,
                subject_id=subject_id,
                name=f"Exam out of {out_of}",
                defaults={"max_score": out_of},
            )
            Score.objects.create(
                assessment=assessment,
                student_membership_id=membership.pk,
                value=value,
            )

    def group_and_term(self, group_id, term_id):
        return ClassGroup.objects.get(pk=group_id), Term.objects.get(pk=term_id)


class DenseRankingTests(PositionSetUp):
    def test_a_tie_does_not_consume_the_position_below_it(self):
        """88, 74, 74, 61 places 1, 2, 2, 3 — not 1, 2, 2, 4."""
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        bola = self.enrol(self.stmarys, "bola", "Bola B", self.group_id, self.term_id)
        chika = self.enrol(self.stmarys, "chika", "Chika C", self.group_id, self.term_id)
        dele = self.enrol(self.stmarys, "dele", "Dele D", self.group_id, self.term_id)

        for student, value in ((ada, 88), (bola, 74), (chika, 74), (dele, 61)):
            self.mark(self.stmarys, self.term_id, self.maths_id, student, value)

        with connected_to(self.stmarys):
            placed = positions.subject_positions(
                *self.group_and_term(self.group_id, self.term_id), self.maths_id
            )

        self.assertEqual(
            {placed[ada.pk], placed[bola.pk], placed[chika.pk], placed[dele.pk]},
            {1, 2, 3},
        )
        self.assertEqual(placed[ada.pk], 1)
        self.assertEqual(placed[bola.pk], 2)
        self.assertEqual(placed[chika.pk], 2)
        self.assertEqual(
            placed[dele.pk], 3, "a tie consumed the position below it"
        )

    def test_everyone_tied_is_all_first(self):
        """The degenerate case, which standard ranking also gets right and which
        is worth pinning because an off-by-one in the tie branch shows up here."""
        students = [
            self.enrol(self.stmarys, f"s{n}", f"S {n}", self.group_id, self.term_id)
            for n in range(4)
        ]
        for student in students:
            self.mark(self.stmarys, self.term_id, self.maths_id, student, 70)

        with connected_to(self.stmarys):
            placed = positions.subject_positions(
                *self.group_and_term(self.group_id, self.term_id), self.maths_id
            )

        self.assertEqual(set(placed.values()), {1})

    def test_the_rule_lives_in_one_function(self):
        """`dense_positions` is where a school switching to standard ranking
        would change one thing, so it is asserted directly as well as through
        the query path."""
        self.assertEqual(
            positions.dense_positions(
                {1: Decimal("88"), 2: Decimal("74"), 3: Decimal("74"), 4: Decimal("61")}
            ),
            {1: 1, 2: 2, 3: 2, 4: 3},
        )


class TiesAreDecidedOnThePrintedNumberTests(PositionSetUp):
    def test_two_children_printing_the_same_percentage_share_a_position(self):
        """45/60 and 15/20 are both 75.00, by different arithmetic.

        The failure this guards is specific: rank on an unrounded value, print a
        rounded one, and two children show identical percentages with different
        positions — which no teacher can explain to a parent.
        """
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        bola = self.enrol(self.stmarys, "bola", "Bola B", self.group_id, self.term_id)

        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 45, out_of=60)
        self.mark(self.stmarys, self.term_id, self.maths_id, bola, 15, out_of=20)

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            percentages = positions.subject_percentages(group, term, self.maths_id)
            placed = positions.subject_positions(group, term, self.maths_id)

        self.assertEqual(percentages[ada.pk], percentages[bola.pk])
        self.assertEqual(placed[ada.pk], placed[bola.pk])

    def test_percentages_are_decimals_not_floats(self):
        """Ties are an equality test, so the type is part of the rule.

        A float percentage makes equality a coin toss on the last bit, and the
        symptom is a tie that is a tie on one school's data and not on another's.
        """
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 1, out_of=3)

        with connected_to(self.stmarys):
            percentages = positions.subject_percentages(
                *self.group_and_term(self.group_id, self.term_id), self.maths_id
            )

        self.assertIsInstance(percentages[ada.pk], Decimal)
        self.assertEqual(percentages[ada.pk], Decimal("33.33"))


class NotMarkedIsNotZeroTests(PositionSetUp):
    def test_a_child_with_no_marks_has_no_position_rather_than_the_last_one(self):
        """Ranking them last says the school assessed them and they scored
        nothing. A child off sick for the term would be printed bottom of a card
        that goes home."""
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        absent = self.enrol(
            self.stmarys, "ngozi", "Ngozi N", self.group_id, self.term_id
        )
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 80)

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            placed = positions.class_positions(group, term)
            averages = positions.overall_percentages(group, term)

        self.assertEqual(placed[ada.pk], 1)
        self.assertNotIn(absent.pk, placed)
        self.assertNotIn(absent.pk, averages)

    def test_an_unmarked_child_does_not_drag_the_class_average_down(self):
        """The same rule, seen from the number staff read off the broadsheet."""
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        self.enrol(self.stmarys, "ngozi", "Ngozi N", self.group_id, self.term_id)
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 80)

        with connected_to(self.stmarys):
            average = positions.class_average(
                *self.group_and_term(self.group_id, self.term_id)
            )

        self.assertEqual(average, Decimal("80.00"))

    def test_a_class_where_nobody_is_marked_has_no_average_at_all(self):
        self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            self.assertIsNone(positions.class_average(group, term))
            self.assertEqual(positions.class_positions(group, term), {})

    def test_a_child_marked_in_one_subject_is_ranked_in_that_one_only(self):
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 80)

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            self.assertIn(ada.pk, positions.subject_positions(group, term, self.maths_id))
            self.assertNotIn(
                ada.pk, positions.subject_positions(group, term, self.english_id)
            )


class TheAverageIsTheChildsOwnTests(PositionSetUp):
    def test_it_is_the_mean_of_subject_percentages_not_a_weighted_total(self):
        """Maths 10/10 and English 40/80 is **75%**, not 55.56%.

        The two readings of "average across their subjects" disagree whenever
        subjects have different `max_score`, and the weighted one lets a long
        paper quietly outweigh the rest of the term.
        """
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 10, out_of=10)
        self.mark(self.stmarys, self.term_id, self.english_id, ada, 40, out_of=80)

        with connected_to(self.stmarys):
            averages = positions.overall_percentages(
                *self.group_and_term(self.group_id, self.term_id)
            )

        self.assertEqual(averages[ada.pk], Decimal("75.00"))
        self.assertNotEqual(averages[ada.pk], Decimal("55.56"))

    def test_the_class_average_is_not_the_childs_average(self):
        """Both numbers exist and they are different questions. A card shows the
        first; only staff see the second."""
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        bola = self.enrol(self.stmarys, "bola", "Bola B", self.group_id, self.term_id)
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 90)
        self.mark(self.stmarys, self.term_id, self.maths_id, bola, 50)

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            averages = positions.overall_percentages(group, term)
            self.assertEqual(averages[ada.pk], Decimal("90.00"))
            self.assertEqual(positions.class_average(group, term), Decimal("70.00"))


class PositionIsOutOfThisClassOnlyTests(PositionSetUp):
    def test_a_child_in_another_class_does_not_affect_the_ranking(self):
        """The roster is the denominator, which is what `ClassPlacement` is for."""
        with connected_to(self.stmarys):
            jss1b = ClassGroup.objects.create(name="JSS 1B", level=1)

        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        top_of_1b = self.enrol(
            self.stmarys, "emeka", "Emeka E", jss1b.pk, self.term_id
        )
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 70)
        self.mark(self.stmarys, self.term_id, self.maths_id, top_of_1b, 99)

        with connected_to(self.stmarys):
            placed = positions.subject_positions(
                *self.group_and_term(self.group_id, self.term_id), self.maths_id
            )

        self.assertEqual(placed, {ada.pk: 1})

    def test_the_other_schools_children_are_not_in_this_ranking(self):
        """Two schemas, two rosters. The check a single-tenant test cannot make."""
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 55)

        theirs = self.enrol(
            self.grace, "uche", "Uche U", self.their_group_id, self.their_term_id
        )
        self.mark(self.grace, self.their_term_id, self.their_maths_id, theirs, 95)

        with connected_to(self.stmarys):
            ours = positions.subject_positions(
                *self.group_and_term(self.group_id, self.term_id), self.maths_id
            )
        with connected_to(self.grace):
            theirs_placed = positions.subject_positions(
                *self.group_and_term(self.their_group_id, self.their_term_id),
                self.their_maths_id,
            )

        self.assertEqual(ours, {ada.pk: 1})
        self.assertEqual(theirs_placed, {theirs.pk: 1})
        self.assertNotIn(theirs.pk, ours)
        self.assertNotIn(ada.pk, theirs_placed)

    def test_both_schools_first_placements_can_share_a_primary_key(self):
        """Per-schema sequences: each school's first row is `pk=1`.

        Recorded as a deliberate assertion because it is the trap — a test that
        asserted these were *different* would fail for a reason that has nothing
        to do with what it is testing.
        """
        with connected_to(self.stmarys):
            ours = ClassGroup.objects.get(pk=self.group_id).pk
        with connected_to(self.grace):
            theirs = ClassGroup.objects.get(pk=self.their_group_id).pk
        self.assertEqual(ours, theirs)


class RankingIsScopedToTheTermTests(PositionSetUp):
    def test_last_terms_marks_do_not_enter_this_terms_position(self):
        with connected_to(self.stmarys):
            second = Term.objects.create(
                session="2025/2026",
                name=TermName.SECOND,
                starts_on=date(2026, 1, 8),
                ends_on=date(2026, 4, 3),
            )
            second_id = second.pk

        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        with connected_to(self.stmarys):
            place_student(
                ClassGroup.objects.get(pk=self.group_id),
                Term.objects.get(pk=second_id),
                Membership.objects.get(pk=ada.pk),
            )

        self.mark(self.stmarys, self.term_id, self.maths_id, ada, 40)
        self.mark(self.stmarys, second_id, self.maths_id, ada, 90)

        with connected_to(self.stmarys):
            first_term = positions.subject_percentages(
                *self.group_and_term(self.group_id, self.term_id), self.maths_id
            )
            second_term = positions.subject_percentages(
                *self.group_and_term(self.group_id, second_id), self.maths_id
            )

        self.assertEqual(first_term[ada.pk], Decimal("40.00"))
        self.assertEqual(second_term[ada.pk], Decimal("90.00"))


class RoundingIsStatedNotInheritedTests(PositionSetUp):
    """Half-way values, and the two ways this module used to lose them.

    `Decimal.quantize()` with no `rounding=` reads
    `decimal.getcontext().rounding`, which is `ROUND_HALF_EVEN` — banker's
    rounding, where 74.505 goes *down* to 74.50. That is not what a Nigerian
    report card does, and because `dense_positions()` ties on the quantised
    value it decides positions as well as printed numbers.

    Two properties, and the second is the one that was actually broken:

    - the rounding does not follow the ambient decimal context, which is
      thread-local and mutable by any library in the process;
    - every function that produces a given number rounds it the same way.
    """

    def _child_averaging_74_505(self, username="ada", full_name="Ada A"):
        """A child whose own average is exactly 74.505.

        88.00 in Maths and 61.01 in English: (88.00 + 61.01) / 2 = 74.505,
        which is a true half and so is decided entirely by the rounding mode.
        61.01 needs a denominator finer than 100, hence 6101 out of 10000.
        """
        child = self.enrol(
            self.stmarys, username, full_name, self.group_id, self.term_id
        )
        self.mark(self.stmarys, self.term_id, self.maths_id, child, 88)
        self.mark(
            self.stmarys,
            self.term_id,
            self.english_id,
            child,
            6101,
            out_of=10000,
        )
        return child

    def test_a_half_is_rounded_up_not_to_even(self):
        child = self._child_averaging_74_505()

        with connected_to(self.stmarys):
            averages = positions.overall_percentages(
                *self.group_and_term(self.group_id, self.term_id)
            )

        self.assertEqual(
            averages[child.pk],
            Decimal("74.51"),
            "74.505 came back as banker's rounding would leave it",
        )

    def test_the_ambient_decimal_context_cannot_change_a_printed_number(self):
        """The control: force the context to a mode that would change it.

        `ROUND_DOWN` would make 74.505 print as 74.50. If this module inherited
        the context — as it did before `ROUNDING` was stated — this assertion
        would fail, which is exactly what makes it a test rather than a comment.
        """
        child = self._child_averaging_74_505()

        with decimal.localcontext() as context:
            context.rounding = decimal.ROUND_DOWN
            with connected_to(self.stmarys):
                averages = positions.overall_percentages(
                    *self.group_and_term(self.group_id, self.term_id)
                )

        self.assertEqual(averages[child.pk], Decimal("74.51"))

    def _child_averaging_74_50(self, username="tayo", full_name="Tayo T"):
        """A child whose own average is exactly 74.50, with nothing to round.

        88.00 and 61.00, both out of 100. On its own this child is not
        interesting; paired with the 74.505 one it puts the half **in the class
        mean**, which is the level `class_average()` rounds at.
        """
        child = self.enrol(
            self.stmarys, username, full_name, self.group_id, self.term_id
        )
        self.mark(self.stmarys, self.term_id, self.maths_id, child, 88)
        self.mark(self.stmarys, self.term_id, self.english_id, child, 61)
        return child

    def test_a_small_ambient_precision_cannot_break_the_page(self):
        """The other half of the context, and it fails louder than a wrong number.

        `prec` is thread-local and mutable exactly like `rounding`, and pinning
        only the rounding mode left this open. At `prec=3` two separate things go
        wrong: the division `6101 * 100 / 10000` comes back 61.0 rather than
        61.01, so the percentage is wrong before any rounding happens; and
        `quantize()` raises `InvalidOperation`, because 74.51 needs four digits
        and only three are allowed. The second is the worse one — a library
        calling `decimal.setcontext()` anywhere in the process turns every
        broadsheet on the platform into a 500.
        """
        child = self._child_averaging_74_505()

        with decimal.localcontext() as context:
            context.prec = 3
            with connected_to(self.stmarys):
                averages = positions.overall_percentages(
                    *self.group_and_term(self.group_id, self.term_id)
                )

        self.assertEqual(averages[child.pk], Decimal("74.51"))

    def test_the_class_average_agrees_with_the_broadsheets_copy_of_it(self):
        """One number, and it used to be computed two ways.

        `class_average()` derived the mean itself and quantised it with a bare
        `.quantize(PLACES)`, inheriting `ROUND_HALF_EVEN`, while
        `class_results().class_average` rounded the same mean with `ROUNDING`.
        At a class mean of 74.505 they disagreed — 74.50 from one, 74.51 from
        the other — so which number a parent's teacher quoted depended on which
        function their screen happened to call.

        **The half has to be in the class mean, not in a child's own average**,
        and the first version of this test got that wrong. One child averaging
        74.505 proves nothing here: their average is quantised to 74.51 *before*
        the class mean is taken, so the mean is 74.51 exactly and the two code
        paths agree however either of them rounds. Restoring the bug left the
        test passing, which is how the mistake was found — see the control table
        in docs/positions.md.

        So: two children, 74.50 and 74.51, whose mean is (74.50 + 74.51) / 2 =
        74.505. `ROUND_HALF_UP` makes that 74.51; the inherited
        `ROUND_HALF_EVEN` makes it 74.50, because 0 is the even digit.
        """
        self._child_averaging_74_505()
        self._child_averaging_74_50()

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            standalone = positions.class_average(group, term)
            from_results = positions.class_results(group, term).class_average

        self.assertEqual(standalone, Decimal("74.51"))
        self.assertEqual(standalone, from_results)

    def test_the_other_school_rounds_the_same_way(self):
        """The rule is the module's, not one schema's."""
        theirs = self.enrol(
            self.grace, "chika", "Chika C", self.their_group_id, self.their_term_id
        )
        self.mark(self.grace, self.their_term_id, self.their_maths_id, theirs, 88)
        self.mark(
            self.grace,
            self.their_term_id,
            self.their_english_id,
            theirs,
            6101,
            out_of=10000,
        )

        with connected_to(self.grace):
            averages = positions.overall_percentages(
                *self.group_and_term(self.their_group_id, self.their_term_id)
            )

        self.assertEqual(averages[theirs.pk], Decimal("74.51"))


class OneReadForTheWholePageTests(PositionSetUp):
    """Every number on a broadsheet comes from the same instant.

    The failure this guards is not slowness. The gradebook saves one mark per
    cell-blur, so a teacher marking while a HOD reads the broadsheet is the
    ordinary case; under READ COMMITTED a page that asks the database once per
    subject sees a different moment in each answer. A mark landing between the
    percentage read and the position read prints 88.00 in 1st place above a row
    showing 91.00 — the same "identical percentages, different positions"
    failure the module exists to prevent, reached by a different route.

    Query *counts* are the observable proxy: a page whose cost does not grow
    with the number of subjects is a page that is not re-reading per subject.
    """

    def _class_of_two(self, subject_ids):
        ada = self.enrol(self.stmarys, "ada", "Ada A", self.group_id, self.term_id)
        bola = self.enrol(self.stmarys, "bola", "Bola B", self.group_id, self.term_id)
        for subject_id in subject_ids:
            self.mark(self.stmarys, self.term_id, subject_id, ada, 88)
            self.mark(self.stmarys, self.term_id, subject_id, bola, 61)
        return ada, bola

    def _more_subjects(self, how_many):
        with connected_to(self.stmarys):
            return [
                Subject.objects.create(name=f"Subject {n}", code=f"S{n}").pk
                for n in range(how_many)
            ]

    @staticmethod
    def _reads(captured):
        """The captured SQL, minus `schema_context`'s own bookkeeping.

        `django_tenants` issues a `SET search_path` on entering and leaving a
        schema. Those are real round trips but they are the harness, not the
        page, and counting them would make this assertion about how the test is
        written rather than about how many times the marks are read.
        """
        return [
            query["sql"]
            for query in captured.captured_queries
            if not query["sql"].startswith("SET search_path")
        ]

    def test_class_results_reads_the_marks_once_however_many_subjects(self):
        """The roster, then the marks. Not once per subject."""
        extra = self._more_subjects(6)
        self._class_of_two([self.maths_id, self.english_id, *extra])

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            with CaptureQueriesContext(connection) as captured:
                results = positions.class_results(group, term)

        reads = self._reads(captured)
        self.assertEqual(len(results.subject_ids), 8)
        self.assertEqual(
            len(reads),
            2,
            "one query per subject is the stale-read bug, not a slow page:\n"
            + "\n".join(sql[:120] for sql in reads),
        )
        self.assertEqual(
            len([sql for sql in reads if "gradebook_score" in sql]),
            1,
            "the marks were read more than once",
        )

    def test_the_cost_does_not_grow_with_the_subject_count(self):
        """Two subjects and eight subjects cost the same.

        Stated as a comparison rather than a fixed number so the test survives
        an unrelated extra query elsewhere, and still fails the moment the
        per-subject loop comes back.
        """
        ada, bola = self._class_of_two([self.maths_id, self.english_id])

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            with CaptureQueriesContext(connection) as two_subjects:
                positions.class_results(group, term)

        for subject_id in self._more_subjects(6):
            for student in (ada, bola):
                self.mark(self.stmarys, self.term_id, subject_id, student, 70)

        with connected_to(self.stmarys):
            group, term = self.group_and_term(self.group_id, self.term_id)
            with CaptureQueriesContext(connection) as eight_subjects:
                results = positions.class_results(group, term)

        self.assertEqual(len(results.subject_ids), 8)
        self.assertEqual(
            len(self._reads(eight_subjects)),
            len(self._reads(two_subjects)),
        )

    def test_a_subject_nobody_was_marked_in_is_not_a_column(self):
        """`subject_ids` comes from the marks, not from `Subject.objects`.

        The subject table keeps retired subjects on purpose — `is_active` says
        "no longer taught, kept because old scores name it" — so ranging over
        all of them puts an all-blank column on the sheet for every subject the
        school teaches to anybody.
        """
        self._class_of_two([self.maths_id])
        with connected_to(self.stmarys):
            retired = Subject.objects.create(
                name="Technical Drawing", code="TD", is_active=False
            )

        with connected_to(self.stmarys):
            results = positions.class_results(
                *self.group_and_term(self.group_id, self.term_id)
            )

        self.assertEqual(results.subject_ids, [self.maths_id])
        self.assertNotIn(retired.pk, results.subject_ids)
        self.assertNotIn(self.english_id, results.subject_ids)

    def test_the_other_school_is_read_in_its_own_schema(self):
        """Two tenants, because a roster query missing its filter reads fine on
        one school and wrongly on two."""
        self._class_of_two([self.maths_id])
        theirs = self.enrol(
            self.grace, "chika", "Chika C", self.their_group_id, self.their_term_id
        )
        self.mark(self.grace, self.their_term_id, self.their_maths_id, theirs, 95)

        with connected_to(self.stmarys):
            ours = positions.class_results(
                *self.group_and_term(self.group_id, self.term_id)
            )
        with connected_to(self.grace):
            others = positions.class_results(
                *self.group_and_term(self.their_group_id, self.their_term_id)
            )

        self.assertNotIn(theirs.pk, ours.student_ids)
        self.assertEqual(others.student_ids, [theirs.pk])
        self.assertEqual(others.averages[theirs.pk], Decimal("95.00"))
