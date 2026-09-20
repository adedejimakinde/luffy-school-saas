"""A term's registers counted per child, and the three ways a count can lie.

The summary is what `results.services.release()` reads once inside its locked
block and hands to the card freeze. What it must never do is guess: a child with
no mark on a day is not absent, and the gap belongs to the school.
"""

from datetime import date

from attendance import services, summary
from attendance.models import AttendanceMark, AttendanceStatus
from academics import services as academics
from schools.tests.tenants import connected_to

from .fixtures import A_SCHOOL_DAY, RegisterSetUp

SECOND_DAY = date(2025, 9, 18)
THIRD_DAY = date(2025, 9, 19)


class CountingATermTests(RegisterSetUp):
    def test_present_and_absent_are_counted_across_every_day_of_the_term(self):
        with connected_to(self.stmarys):
            ada = self.children["ada"].pk
            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            services.take_register(
                self.jss1a, self.term, on=SECOND_DAY, absent_ids=[ada], by=self.teacher
            )
            services.take_register(
                self.jss1a, self.term, on=THIRD_DAY, by=self.teacher
            )

            counted = summary.for_term(self.term, self.everyone())

            self.assertEqual(counted[ada].present, 2)
            self.assertEqual(counted[ada].absent, 1)
            self.assertEqual(counted[ada].marked, 3)
            other = counted[self.children["emeka"].pk]
            self.assertEqual((other.present, other.absent), (3, 0))

    def test_every_child_asked_about_gets_an_entry_even_with_no_marks(self):
        """A missing key would be a `KeyError` in the middle of a release.

        `freeze_for_release()` writes a row for every child on the roster
        unconditionally, so "not marked" has to arrive as a value rather than as
        an absence from the dict.
        """
        with connected_to(self.stmarys):
            counted = summary.for_term(self.term, self.everyone())

            self.assertEqual(sorted(counted), self.everyone())
            for entry in counted.values():
                self.assertEqual((entry.present, entry.absent), (0, 0))

    def test_a_child_marked_in_two_groups_has_both_halves_counted(self):
        """She moved in October; both classes marked her and both are her term.

        `Register.class_group` records who did the marking, which is D2's
        question and a different one from how many days she attended.
        """
        with connected_to(self.stmarys):
            tunde = self.children["tunde"]
            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            academics.move_student(self.jss1b, self.term, tunde)
            services.take_register(
                self.jss1b,
                self.term,
                on=SECOND_DAY,
                absent_ids=[tunde.pk],
                by=self.teacher,
            )

            counted = summary.for_term(self.term, [tunde.pk])
            self.assertEqual((counted[tunde.pk].present, counted[tunde.pk].absent), (1, 1))

    def test_another_terms_registers_are_not_counted(self):
        with connected_to(self.stmarys):
            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            counted = summary.for_term(self.second_term, self.everyone())
            for entry in counted.values():
                self.assertEqual(entry.marked, 0)

    def test_asking_about_nobody_reads_nothing(self):
        with connected_to(self.stmarys):
            self.assertEqual(summary.for_term(self.term, []), {})


class TheSummaryDoesNotGuessTests(RegisterSetUp):
    def test_an_unmarked_child_in_a_taken_register_is_not_absent(self):
        """She was skipped, which is the school's gap and not her absence.

        This is A4 at the point where it would be easiest to lose: the register
        exists, so a count that filled in the blanks would look defensible.
        """
        with connected_to(self.stmarys):
            tunde = self.children["tunde"].pk
            services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                shown_ids=self.ids("ada", "emeka", "bisi"),
                by=self.teacher,
            )

            counted = summary.for_term(self.term, [tunde])
            self.assertEqual((counted[tunde].present, counted[tunde].absent), (0, 0))
            self.assertEqual(counted[tunde].marked, 0)

    def test_a_day_with_no_register_adds_to_nobodys_absence(self):
        with connected_to(self.stmarys):
            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            counted = summary.for_term(self.term, self.everyone())
            for entry in counted.values():
                self.assertEqual(entry.absent, 0)
                self.assertEqual(entry.present, 1)
