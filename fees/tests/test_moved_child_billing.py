"""A child moved to another class mid-term: billed for what the new class adds. G-13.

Ada is charged by JSS 1A's bill, then moved to JSS 3A. Under B2 she stays JSS
1A's for the term, and before G-13 a line either bill added later reached
neither of them: she was silently under-billed. Now JSS 3A's bill charges her
each line added after she joined it, and only those, and never an item another
bill already charged her.

Two schools: Grace has a child in a JSS 3A of its own, moved the same way, whose
account must not move when St Mary's bills.
"""

from academics import services as academics
from academics.models import ClassGroup, ClassPlacement, Term
from fees import schedules
from fees.models import FeeEntryKind, FeeLedgerEntry, FeeSchedule, FeeScheduleLine, KOBO_PER_NAIRA
from fees.tests.test_schedules import LEVY, TUITION, BillingSetUp
from schools.tests.tenants import connected_to

EXAM = 8_000 * KOBO_PER_NAIRA
LAB = 5_000 * KOBO_PER_NAIRA


class AMovedChildIsBilledForLaterLinesTests(BillingSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            self.apply()  # Ada and Chidi charged Tuition and PTA levy by JSS 1A's bill.
            self.senior = ClassGroup.objects.create(name="JSS 3A", level=3)
            # JSS 3A's bill, as it stood before Ada arrived: its own tuition and a lab levy.
            self.senior_bill = FeeSchedule.objects.create(term=self.term(), class_group=self.senior)
            FeeScheduleLine.objects.create(
                schedule=self.senior_bill, description="Tuition", amount_kobo=TUITION, position=1
            )
            FeeScheduleLine.objects.create(
                schedule=self.senior_bill, description="Laboratory levy", amount_kobo=LAB, position=2
            )
            academics.move_student(self.senior, self.term(), self.ada)

    def ada_charges(self):
        return sorted(
            FeeLedgerEntry.objects.filter(
                student_membership_id=self.ada.pk, kind=FeeEntryKind.CHARGE
            ).values_list("narration", "amount_kobo")
        )

    def add_line(self, bill, description, amount=EXAM):
        return FeeScheduleLine.objects.create(
            schedule=bill, description=description, amount_kobo=amount, position=9
        )

    def test_a_line_the_new_class_adds_later_is_charged_to_the_child_who_moved_in(self):
        """The finding's test idea, the half that was broken.

        CONTROL G13-1: `apply_to_class()` with the later-lines block removed
        (`later_lines` left empty) makes this red: no exam fee for Ada."""
        with connected_to(self.stmarys):
            self.add_line(self.senior_bill, "Exam fee")

            summary = schedules.apply_to_class(self.senior_bill, by=self.bursar)

            self.assertIn(("Exam fee", EXAM), self.ada_charges())
            self.assertEqual(summary.billed_elsewhere, (self.ada.pk,))
            self.assertEqual(self.balance_of(self.ada), TUITION + LEVY + EXAM)

    def test_the_lines_the_new_class_had_before_they_arrived_are_not_charged(self):
        """B2 unchanged: what JSS 3A already billed when Ada joined is taken to be
        what JSS 1A already charged her. Its tuition and its lab levy stay off her.

        CONTROL G13-2: the later-lines test without `line.created_at <= since`
        makes this red: Ada is charged the laboratory levy."""
        with connected_to(self.stmarys):
            self.add_line(self.senior_bill, "Exam fee")

            schedules.apply_to_class(self.senior_bill, by=self.bursar)

            self.assertEqual(
                self.ada_charges(),
                sorted([("Tuition", TUITION), ("PTA levy", LEVY), ("Exam fee", EXAM)]),
            )

    def test_an_item_the_old_class_already_charged_is_not_charged_again(self):
        """No line billed twice: JSS 1A's bill added a second instalment and
        charged Ada it before she moved; JSS 3A adds its own "Second instalment"
        later. One fee, one charge, and the summary says why.

        CONTROL G13-3: the later-lines test without the same-description skip
        makes this red: Ada is charged two second instalments."""
        with connected_to(self.stmarys):
            # Back in JSS 1A for a moment, so its new line reaches her...
            academics.move_student(ClassGroup.objects.get(pk=self.group_id), self.term(), self.ada)
            self.add_line(self.schedule(), "Second instalment")
            self.apply()
            academics.move_student(self.senior, self.term(), self.ada)
            # ...then JSS 3A adds the same item after she has rejoined it.
            self.add_line(self.senior_bill, " second  INSTALMENT ")

            summary = schedules.apply_to_class(self.senior_bill, by=self.bursar)

            self.assertEqual(
                [n for n, _ in self.ada_charges()].count("Second instalment"), 1
            )
            self.assertEqual(
                [n.strip().lower() for n, _ in self.ada_charges()].count("second  instalment"), 0
            )
            self.assertEqual(len(summary.same_item_elsewhere), 1)
            self.assertIn("not charged again", str(summary))

    def test_applying_the_new_bill_twice_charges_the_later_line_once(self):
        """The ordinary re-run: the per-line skip and the index hold it."""
        with connected_to(self.stmarys):
            self.add_line(self.senior_bill, "Exam fee")
            schedules.apply_to_class(self.senior_bill, by=self.bursar)

            again = schedules.apply_to_class(self.senior_bill, by=self.bursar)

            self.assertEqual(again.charges_posted, 0)
            self.assertEqual([n for n, _ in self.ada_charges()].count("Exam fee"), 1)

    def test_the_old_classs_later_line_does_not_reach_the_child_who_left_it(self):
        """JSS 1A adds an exam fee after Ada moved: it is JSS 3A's to charge her
        hers, so JSS 1A's does not, and with JSS 3A's she pays one."""
        with connected_to(self.stmarys):
            self.add_line(self.schedule(), "Exam fee")
            self.add_line(self.senior_bill, "Exam fee")

            self.apply()
            schedules.apply_to_class(self.senior_bill, by=self.bursar)

            self.assertEqual([n for n, _ in self.ada_charges()].count("Exam fee"), 1)
            chidi = FeeLedgerEntry.objects.filter(
                student_membership_id=self.chidi.pk, narration="Exam fee"
            ).count()
            self.assertEqual(chidi, 1, "the child still in JSS 1A is charged its exam fee")

    def test_the_move_stamps_when_they_joined_and_a_resave_does_not(self):
        """`class_since` is the move, not the last save: `updated_at` would move
        on any save and turn every old line into a later one."""
        with connected_to(self.stmarys):
            placement = ClassPlacement.objects.get(term=self.term(), student_membership_id=self.ada.pk)
            since = placement.class_since
            placement.save()
            placement.refresh_from_db()
            self.assertEqual(placement.class_since, since)
            self.assertGreater(placement.updated_at, since)

    def test_the_other_school_is_untouched(self):
        with connected_to(self.grace):
            grace_term = Term.objects.get(pk=self.their_term_id)
            schedules.apply_to_class(
                FeeSchedule.objects.get(pk=self.their_schedule_id), by=self.bursar
            )
            senior = ClassGroup.objects.create(name="JSS 3A", level=3)
            academics.move_student(senior, grace_term, self.ngozi)
            before = self.balance_of(self.ngozi)

        with connected_to(self.stmarys):
            self.add_line(self.senior_bill, "Exam fee")
            schedules.apply_to_class(self.senior_bill, by=self.bursar)

        with connected_to(self.grace):
            self.assertEqual(self.balance_of(self.ngozi), before)
            self.assertFalse(FeeLedgerEntry.objects.filter(narration="Exam fee").exists())
