"""The four states a card's attendance line can be, and the freeze behind them.

Two halves. `TheDecisionTests` are about `card_api.attendance_of()`, which is
the one place that decides what a reader is shown — and which both renderers
read, because `pdf.html_for()` and the parent page are the same
`card_payload()`. `TheFreezeTests` are about the numbers getting onto the card
in the first place, on the INSERT, because `ReleasedCard` refuses an UPDATE at
two layers.

The case the whole design exists for is `a_term_nobody_marked`: `0, 0, 62` is a
school that kept no register, and "Present 0 out of 62 days" would be a false
accusation against every child in the class. It is the failure A4 prevents in
the schema, arriving through the renderer instead.
"""

from django.test import SimpleTestCase

from results.card_api import AttendanceState, attendance_of
from results.models import ReleasedCard


def a_card(present=None, absent=None, open=None) -> ReleasedCard:
    """An unsaved `ReleasedCard` carrying only the three columns under test.

    Unsaved and `SimpleTestCase`: `attendance_of()` reads three attributes and
    touches no database, and a test that built a real release to assert a
    formatting rule would be measuring the release.
    """
    return ReleasedCard(days_present=present, days_absent=absent, days_open=open)


class TheDecisionTests(SimpleTestCase):
    def test_all_three_null_is_a_card_with_no_attendance_on_it(self):
        answer = attendance_of(a_card())
        self.assertEqual(answer.state, AttendanceState.ABSENT)
        self.assertIsNone(answer.marked)
        self.assertIsNone(answer.not_marked)

    def test_a_term_nobody_marked_is_not_recorded_and_carries_no_denominator(self):
        """The case that decided the design. Never "0 of 62"."""
        answer = attendance_of(a_card(present=0, absent=0, open=62))

        self.assertEqual(answer.state, AttendanceState.NOT_RECORDED)
        self.assertEqual(answer.marked, 0)
        self.assertEqual(answer.not_marked, 62)

    def test_a_partly_marked_term_is_partial_and_names_the_gap(self):
        answer = attendance_of(a_card(present=38, absent=2, open=62))

        self.assertEqual(answer.state, AttendanceState.PARTIAL)
        self.assertEqual(answer.marked, 40)
        self.assertEqual(answer.not_marked, 22)

    def test_a_fully_marked_term_is_complete(self):
        answer = attendance_of(a_card(present=58, absent=4, open=62))

        self.assertEqual(answer.state, AttendanceState.COMPLETE)
        self.assertEqual(answer.marked, 62)
        self.assertEqual(answer.not_marked, 0)

    def test_absent_every_day_of_a_fully_marked_term_is_complete_not_unrecorded(self):
        """`0` present is a real measurement, and the one case "0 of 62" is true.

        The distinction is `marked`, not `present`: nought present with sixty-two
        absences is a child who was never there, and nought present with nothing
        marked is a school that never looked.
        """
        answer = attendance_of(a_card(present=0, absent=62, open=62))

        self.assertEqual(answer.state, AttendanceState.COMPLETE)
        self.assertEqual(answer.present, 0)

    def test_marks_with_no_declared_term_length_are_partial_with_nothing_to_subtract(self):
        """A register kept by a school that never declared its term length.

        `not_marked` is null rather than nought, because it is unknowable rather
        than zero — there is no denominator to take the marked days away from.
        """
        answer = attendance_of(a_card(present=38, absent=2, open=None))

        self.assertEqual(answer.state, AttendanceState.PARTIAL)
        self.assertEqual(answer.marked, 40)
        self.assertIsNone(answer.not_marked)

    def test_more_days_marked_than_declared_is_complete_rather_than_negative(self):
        """A school whose calendar and register disagree.

        Every declared day is accounted for, so the honest reading is complete.
        Printing a negative remainder, or calling it partial, would each be
        worse than saying the term is covered.
        """
        answer = attendance_of(a_card(present=60, absent=5, open=62))

        self.assertEqual(answer.state, AttendanceState.COMPLETE)
        self.assertEqual(answer.not_marked, 0)

    def test_nothing_marked_and_no_term_length_is_still_not_recorded(self):
        answer = attendance_of(a_card(present=0, absent=0, open=None))
        self.assertEqual(answer.state, AttendanceState.NOT_RECORDED)
        self.assertIsNone(answer.not_marked)


# ---------------------------------------------------------------------------
# Getting the numbers onto the card, which can only happen on the INSERT
# ---------------------------------------------------------------------------

from datetime import date  # noqa: E402

from academics import services as academics  # noqa: E402
from attendance import services as attendance  # noqa: E402
from results import cards, revision  # noqa: E402
from results.models import CardRevision  # noqa: E402
from schools.tests.tenants import connected_to  # noqa: E402

from .test_cards import CardSetUp  # noqa: E402

TERM_DAYS = 62
FIRST_DAY = date(2025, 9, 15)
SECOND_DAY = date(2025, 9, 16)


class AttendanceFreezeSetUp(CardSetUp):
    """The first-term class, with the school's term length declared."""

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            academics.set_school_days(
                self.term(self.stmarys, "first"), TERM_DAYS, by=self.principal
            )

    def mark(self, on, absent_ids=()):
        return attendance.take_register(
            self.group(self.stmarys),
            self.term(self.stmarys, "first"),
            on=on,
            absent_ids=absent_ids,
            by=self.teacher,
        )

    def card_of(self, membership):
        return cards.card_for(membership.pk, self.term(self.stmarys, "first"))


class TheFreezeTests(AttendanceFreezeSetUp):
    def test_a_release_writes_the_three_columns_on_the_insert(self):
        with connected_to(self.stmarys):
            self.mark(FIRST_DAY)
            self.mark(SECOND_DAY, absent_ids=[self.ada.pk])
            self.release_the_term()

            card = self.card_of(self.ada)
            self.assertEqual(card.days_present, 1)
            self.assertEqual(card.days_absent, 1)
            self.assertEqual(card.days_open, TERM_DAYS)

    def test_days_open_is_the_declared_length_not_the_days_marked(self):
        """Two registers, sixty-two declared days. The gap is the school's."""
        with connected_to(self.stmarys):
            self.mark(FIRST_DAY)
            self.release_the_term()

            card = self.card_of(self.bola)
            self.assertEqual(card.days_present, 1)
            self.assertEqual(card.days_open, TERM_DAYS)
            self.assertEqual(attendance_of(card).state, AttendanceState.PARTIAL)
            self.assertEqual(attendance_of(card).not_marked, TERM_DAYS - 1)

    def test_a_term_nobody_marked_freezes_nought_and_nought_not_null(self):
        """The case the design exists for, end to end.

        Nought-and-nought with a term length is a school that kept no register,
        and the card must say so rather than print a denominator.
        """
        with connected_to(self.stmarys):
            self.release_the_term()

            card = self.card_of(self.ada)
            self.assertEqual((card.days_present, card.days_absent), (0, 0))
            self.assertEqual(card.days_open, TERM_DAYS)
            self.assertEqual(attendance_of(card).state, AttendanceState.NOT_RECORDED)

    def test_a_school_that_never_declared_its_term_length_freezes_a_null(self):
        with connected_to(self.stmarys):
            academics.set_school_days(self.term(self.stmarys, "first"), None)
            self.mark(FIRST_DAY)
            self.release_the_term()

            card = self.card_of(self.ada)
            self.assertEqual(card.days_present, 1)
            self.assertIsNone(card.days_open)

    def test_the_frozen_numbers_do_not_move_when_the_register_does(self):
        """`ReleasedCard` refuses an UPDATE at two layers; this is that, seen.

        Correctness requirement 4: amending a register after release changes
        nothing on a card already in a parent's hand.
        """
        with connected_to(self.stmarys):
            self.mark(FIRST_DAY)
            self.release_the_term()
            before = self.card_of(self.ada)

            self.mark(FIRST_DAY, absent_ids=[self.ada.pk])
            self.mark(SECOND_DAY, absent_ids=[self.ada.pk])

            after = self.card_of(self.ada)
            self.assertEqual(after.pk, before.pk)
            self.assertEqual(after.days_present, 1)
            self.assertEqual(after.days_absent, 0)


class ARevisionCarriesAttendanceForwardTests(AttendanceFreezeSetUp):
    """D7. A correction to one field must not restate another.

    A March revision fixing a comment typo must not silently change the
    attendance numbers a parent read in December — every value individually
    legal, nothing objecting. Issue #59 is the same bug about marks.
    """

    def test_a_revision_keeps_the_numbers_the_superseded_card_was_sent_with(self):
        with connected_to(self.stmarys):
            self.mark(FIRST_DAY)
            self.release_the_term()
            original = self.card_of(self.ada)

            # The register changes after release, the way a register does.
            self.mark(FIRST_DAY, absent_ids=[self.ada.pk])
            self.mark(SECOND_DAY, absent_ids=[self.ada.pk])

            revision.revise(self.ada, self.term(self.stmarys, "first"), self.principal, "typo")

            revised = self.card_of(self.ada)
            self.assertEqual(revised.version, original.version + 1)
            self.assertEqual(revised.days_present, original.days_present)
            self.assertEqual(revised.days_absent, original.days_absent)
            self.assertEqual(revised.days_open, original.days_open)

    def test_the_revision_is_recorded_as_a_revision_all_the_same(self):
        """Carrying attendance forward is not the revision doing nothing."""
        with connected_to(self.stmarys):
            self.mark(FIRST_DAY)
            self.release_the_term()
            revision.revise(self.ada, self.term(self.stmarys, "first"), self.principal, "typo")

            self.assertEqual(CardRevision.objects.count(), 1)
            self.assertTrue(self.card_of(self.ada).is_revised)

    def test_a_term_length_edited_after_release_does_not_reach_a_revised_card(self):
        """`days_open` is carried forward too, not re-read from the term.

        A school correcting its calendar in March must not restate the
        denominator on a card that went home in December.
        """
        with connected_to(self.stmarys):
            self.mark(FIRST_DAY)
            self.release_the_term()

            academics.set_school_days(self.term(self.stmarys, "first"), 40)
            revision.revise(self.ada, self.term(self.stmarys, "first"), self.principal, "typo")

            self.assertEqual(self.card_of(self.ada).days_open, TERM_DAYS)
