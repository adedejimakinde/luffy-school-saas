"""The grading scale: what letter a mark earns, and who may change it.

Three things are proved here, and they fail in different ways.

**The boundaries**, where the failure is a letter a parent disputes. A scale is
read by comparison, so every band's edge is an off-by-one waiting to happen:
75.00 must be A1 and 74.99 must be B2, and the test that only checks 80 and 60
would pass against `>` where `>=` was meant.

**The shape**, where the failure is a mark with no grade. Bands store where they
start, so overlaps and gaps are unrepresentable — but coverage is not, and a
scale that starts above nought prints a blank where a letter belongs, which on a
card is indistinguishable from a subject nobody marked.

**The tenancy**, where the failure is one school's scale grading another
school's children. Two schools throughout, and the second is used rather than
built and ignored.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Role, User
from accounts.services import grant_membership
from results import grades
from results.models import GradeBand
from results.tests.test_positions import PASSWORD, make_school
from schools.tests.tenants import connected_to


class GradeSetUp(TestCase):
    """One school, seeded with the default scale by migration `0015`.

    **One school, deliberately.** Per-test tenant schema creation is most of this
    suite's runtime, and a fixture that builds a second school every test so that
    four of them can use it is the exact pattern
    [#38](https://github.com/adedejimakinde/luffy-school-saas/issues/38) has
    filed against `test_release_guard.py`. The project rule is to prove
    behaviour against 2+ tenants, and the way to honour it is a second school
    that is *used* — `TwoSchoolSetUp` below builds one, and every class that
    inherits it asserts something across the pair.
    """

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")

        self.principal = self._staff(self.stmarys, "sm-principal", Role.PRINCIPAL)
        self.admin = self._staff(self.stmarys, "sm-admin", Role.ADMIN)
        self.teacher = self._staff(self.stmarys, "sm-teacher", Role.TEACHER)

    def _staff(self, school, username, role):
        user = User.objects.create_user(
            username, PASSWORD, full_name=f"{role.label} of {school.name}"
        )
        grant_membership(user, school, role)
        return user


class TwoSchoolSetUp(GradeSetUp):
    """A second school, for the tests whose whole subject is the pair."""

    def setUp(self):
        super().setUp()
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.their_principal = self._staff(self.grace, "ga-principal", Role.PRINCIPAL)


class TheSeededScaleTests(GradeSetUp):
    """Every schema starts with a scale, because a card with no letters is broken."""

    def test_a_new_school_has_the_documented_default(self):
        with connected_to(self.stmarys):
            scale = grades.scale()

        self.assertEqual(len(scale), 9)
        self.assertEqual([band.letter for band in scale][:3], ["A1", "B2", "B3"])
        self.assertEqual(scale[0].minimum, Decimal("75.00"))
        self.assertEqual(scale[-1].letter, "F9")
        self.assertEqual(scale[-1].minimum, Decimal("0.00"))

    def test_the_scale_reads_highest_first(self):
        """The order it is printed in, and the order `grade_for()` walks."""
        with connected_to(self.stmarys):
            minima = [band.minimum for band in grades.scale()]

        self.assertEqual(minima, sorted(minima, reverse=True))

    def test_the_seeded_scale_starts_at_nought(self):
        """The one invariant no constraint can hold. Every mark earns a letter."""
        with connected_to(self.stmarys):
            self.assertEqual(min(band.minimum for band in grades.scale()), Decimal(0))


class TheBoundariesTests(GradeSetUp):
    """A band's edge is where an off-by-one costs a parent an argument."""

    def test_the_bottom_of_a_band_is_in_it(self):
        """75.00 is A1. `>=`, not `>` — and a test at 80 would not notice."""
        with connected_to(self.stmarys):
            self.assertEqual(grades.grade_for(Decimal("75.00")).letter, "A1")

    def test_a_hundredth_below_is_the_band_beneath(self):
        with connected_to(self.stmarys):
            self.assertEqual(grades.grade_for(Decimal("74.99")).letter, "B2")

    def test_every_band_edge_lands_on_its_own_band(self):
        """All nine at once, so a scale edited later cannot half-break."""
        with connected_to(self.stmarys):
            scale = grades.scale()
            for band in scale:
                with self.subTest(letter=band.letter):
                    self.assertEqual(
                        grades.grade_for(band.minimum, bands=scale).letter, band.letter
                    )
                    below = band.minimum - Decimal("0.01")
                    if below >= 0:
                        self.assertNotEqual(
                            grades.grade_for(below, bands=scale).letter, band.letter
                        )

    def test_full_marks_and_nought_both_grade(self):
        with connected_to(self.stmarys):
            self.assertEqual(grades.grade_for(Decimal("100.00")).letter, "A1")
            self.assertEqual(grades.grade_for(Decimal("0.00")).letter, "F9")

    def test_an_unmarked_subject_has_no_grade_rather_than_an_F(self):
        """Not marked is not zero, and it is not a fail either.

        The same rule `positions._percentage()` keeps. An F here would be the
        card asserting the school assessed this child and they scored nothing.
        """
        with connected_to(self.stmarys):
            self.assertIsNone(grades.grade_for(None))

    def test_a_caller_supplied_band_list_may_be_in_any_order(self):
        """`bands=` is public, and the wrong order must not silently grade everyone F.

        Walking the list and taking the first band at or below the mark is
        correct only for a highest-first list. A caller passing
        `order_by("minimum")` would get the lowest qualifying band every time —
        every child on the page an F, no exception, nothing to notice.
        """
        with connected_to(self.stmarys):
            lowest_first = list(GradeBand.objects.order_by("minimum"))
            self.assertEqual(lowest_first[0].letter, "F9")

            self.assertEqual(
                grades.grade_for(Decimal("95.00"), bands=lowest_first).letter, "A1"
            )
            self.assertEqual(
                grades.grade_for(Decimal("62.00"), bands=lowest_first).letter, "C4"
            )

    def test_a_mark_below_every_band_grades_blank_rather_than_raising(self):
        """A hole a `psql` session can still make, answered without an exception.

        `set_scale()` refuses a scale that does not start at nought, so this is
        unreachable through the service. It is reachable by hand, and a card
        printing a blank grade beats one that raises while a parent waits.
        """
        with connected_to(self.stmarys):
            GradeBand.objects.filter(letter="F9").delete()
            self.assertIsNone(grades.grade_for(Decimal("10.00")))
            self.assertEqual(grades.grade_for(Decimal("95.00")).letter, "A1")


class SettingTheScaleTests(GradeSetUp):
    """A scale is replaced whole, because a band only means anything in a set."""

    FIVE_LETTER = [
        (70, "A", "Excellent"),
        (60, "B", "Very Good"),
        (50, "C", "Credit"),
        (40, "D", "Pass"),
        (0, "F", "Fail"),
    ]

    def test_a_school_can_replace_the_whole_scale(self):
        with connected_to(self.stmarys):
            grades.set_scale(self.FIVE_LETTER)
            scale = grades.scale()
            # Inside the schema, deliberately: `GradeBand` is a tenant table and
            # a count on the public schema is a different question entirely.
            self.assertEqual(GradeBand.objects.count(), 5)

        self.assertEqual([band.letter for band in scale], list("ABCDF"))

    def test_replacing_leaves_none_of_the_old_scale_behind(self):
        """The failure this guards is a scale that is both scales at once."""
        with connected_to(self.stmarys):
            grades.set_scale(self.FIVE_LETTER)
            self.assertFalse(GradeBand.objects.filter(letter="A1").exists())

    def test_the_new_scale_grades_immediately(self):
        with connected_to(self.stmarys):
            self.assertEqual(grades.grade_for(Decimal("72.00")).letter, "B2")
            grades.set_scale(self.FIVE_LETTER)
            self.assertEqual(grades.grade_for(Decimal("72.00")).letter, "A")

    def test_a_scale_that_does_not_start_at_nought_is_refused(self):
        """The invariant with nowhere else to live: coverage is a table fact."""
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale) as refused:
                grades.set_scale([(50, "P", "Pass"), (40, "F", "Fail")])
            self.assertIn("start at 0", str(refused.exception))
            # And the old scale is untouched — a refused write writes nothing.
            self.assertEqual(grades.grade_for(Decimal("72.00")).letter, "B2")

    def test_an_empty_scale_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale):
                grades.set_scale([])

    def test_two_bands_starting_at_the_same_mark_are_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale) as refused:
                grades.set_scale([(0, "F", ""), (50, "C", ""), (50, "B", "")])
            self.assertIn("only earn one grade", str(refused.exception))

    def test_one_letter_used_twice_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale):
                grades.set_scale([(0, "F", ""), (50, "C", ""), (60, "C", "")])

    def test_a_band_outside_the_percentage_range_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale):
                grades.set_scale([(0, "F", ""), (140, "A", "")])

    def test_a_band_with_no_letter_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale):
                grades.set_scale([(0, "  ", "Fail")])

    def test_a_letter_too_long_for_the_column_is_refused_as_a_sentence(self):
        """`DataError` is not a refusal — it is a 500 with a poisoned transaction.

        `letter` is `varchar(4)`, and "Fail" fits while "Merit" does not, which
        is exactly the kind of scale a school types. The service has to refuse
        what the table would refuse, or the caller gets a raw `DataError` from
        inside `set_scale()`'s own `atomic()` — outside `ResultsError`, so every
        `except ResultsError` misses it. `ratings._require_a_trait_name()` states
        the rule.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale) as refused:
                grades.set_scale([(0, "Fail", ""), (50, "Merit", "")])
            self.assertIn("fits 4 characters", str(refused.exception))
            # And the scale it refused is still the one in force.
            self.assertEqual(grades.grade_for(Decimal("72.00")).letter, "B2")

    def test_a_remark_too_long_for_the_column_is_refused_as_a_sentence(self):
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale) as refused:
                grades.set_scale([(0, "F", "x" * 33)])
            self.assertIn("fits 32 characters", str(refused.exception))

    def test_two_bands_that_collide_only_after_rounding_are_refused(self):
        """The column stores two places, so 49.996 and 50.001 are one band.

        Checking the typed value rather than the stored one lets the pair
        through the service and collides on the unique constraint instead —
        an `IntegrityError` outside `ResultsError`, for a scale the school
        could reasonably have typed.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(grades.InvalidGradeScale) as refused:
                grades.set_scale(
                    [(0, "F", ""), ("49.996", "C", ""), ("50.001", "B", "")]
                )
            self.assertIn("only earn one grade", str(refused.exception))

    def test_a_minimum_is_stored_at_the_precision_it_is_compared_at(self):
        """A boundary that moves on save is one no test at the edge would catch."""
        with connected_to(self.stmarys):
            grades.set_scale([(0, "F", ""), ("74.996", "A", "")])
            self.assertEqual(grades.scale()[0].minimum, Decimal("75.00"))
            self.assertEqual(grades.grade_for(Decimal("75.00")).letter, "A")
            self.assertEqual(grades.grade_for(Decimal("74.99")).letter, "F")

    def test_bands_may_be_offered_in_any_order(self):
        """A school types its scale bottom-up as readily as top-down."""
        with connected_to(self.stmarys):
            grades.set_scale(list(reversed(self.FIVE_LETTER)))
            self.assertEqual([band.letter for band in grades.scale()], list("ABCDF"))

    def test_a_remark_is_optional(self):
        with connected_to(self.stmarys):
            grades.set_scale([(0, "F", ""), (50, "P", "")])
            self.assertEqual(grades.grade_for(Decimal("60.00")).remark, "")


class TheDatabaseRefusesItTooTests(GradeSetUp):
    """Every service check but coverage is also a constraint. The import path."""

    def test_two_bands_cannot_start_at_the_same_mark(self):
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    GradeBand.objects.create(minimum=Decimal("75.00"), letter="AA")

    def test_a_letter_cannot_be_used_twice(self):
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    GradeBand.objects.create(minimum=Decimal("77.00"), letter="A1")

    def test_a_band_cannot_start_outside_the_percentage_range(self):
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    GradeBand.objects.create(minimum=Decimal("140.00"), letter="XX")

    def test_a_band_cannot_have_a_blank_letter(self):
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    GradeBand.objects.create(minimum=Decimal("99.00"), letter="   ")


class WhoMaySetTheScaleTests(TwoSchoolSetUp):
    """The pair who already decide what the card prints, and nobody else."""

    def test_the_principal_may(self):
        with connected_to(self.stmarys):
            grades.set_scale_as(self.principal, [(0, "F", "Fail"), (50, "P", "Pass")])
            self.assertEqual(len(grades.scale()), 2)

    def test_the_administrator_may(self):
        """Unlike a promotion decision — this is an office act, not a judgement."""
        with connected_to(self.stmarys):
            grades.set_scale_as(self.admin, [(0, "F", "Fail"), (50, "P", "Pass")])
            self.assertEqual(len(grades.scale()), 2)

    def test_a_teacher_may_not(self):
        with connected_to(self.stmarys):
            with self.assertRaises(grades.NotAllowedToConfigureGrades) as refused:
                grades.set_scale_as(self.teacher, [(0, "F", "Fail")])
            self.assertIn("principal or an administrator", str(refused.exception))
            # And nothing was written.
            self.assertEqual(len(grades.scale()), 9)

    def test_a_principal_of_another_school_may_not(self):
        """Holding the role somewhere else is not holding it here."""
        with connected_to(self.stmarys):
            with self.assertRaises(grades.NotAllowedToConfigureGrades):
                grades.set_scale_as(self.their_principal, [(0, "F", "Fail")])


class TwoSchoolsTests(TwoSchoolSetUp):
    """A scale is a tenant table, and one school's grading is not the other's."""

    def test_a_scale_is_one_schools_and_not_the_others(self):
        with connected_to(self.stmarys):
            grades.set_scale([(0, "F", "Fail"), (50, "P", "Pass")])

        with connected_to(self.grace):
            self.assertEqual(len(grades.scale()), 9)
            self.assertEqual(grades.grade_for(Decimal("72.00")).letter, "B2")

    def test_the_same_mark_earns_two_letters_at_two_schools(self):
        """The point of it being per-school, shown as two answers to one mark."""
        with connected_to(self.stmarys):
            grades.set_scale([(0, "F", "Fail"), (70, "A", "Excellent")])
            ours = grades.grade_for(Decimal("72.00")).letter
        with connected_to(self.grace):
            theirs = grades.grade_for(Decimal("72.00")).letter

        self.assertEqual(ours, "A")
        self.assertEqual(theirs, "B2")

    def test_replacing_one_schools_scale_leaves_the_others_row_count_alone(self):
        """`set_scale()` deletes before it inserts. It must delete in one schema."""
        with connected_to(self.grace):
            before = GradeBand.objects.count()
        with connected_to(self.stmarys):
            grades.set_scale([(0, "F", "Fail")])
        with connected_to(self.grace):
            self.assertEqual(GradeBand.objects.count(), before)
