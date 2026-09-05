"""Billing a class from a schedule: what it posts, what it skips, what it refuses.

The subject is `fees.schedules.apply_to_class()`, and the property worth more
than any other is that **running it twice does not charge anybody twice**. Two
mechanisms hold that, and they are not the same mechanism:

- the service *skips* a child who already has a line's charge, which is what
  gives a bursar "42 skipped, 3 charged" instead of a stack trace;
- the partial unique index `a_schedule_line_charges_a_child_once` refuses the
  write outright, which is what holds when two applications race.

`SkipIsNotTheIndexTests` at the foot proves they are two, by removing the skip
and showing the index still refusing. A test that only ever exercises the skip
would pass identically against a schema with no index at all, which is exactly
the shape of green test `docs/operating-rules.md` rule 5 is about.

**Two schools throughout.** A fee schedule is per schema, and every "this
school's bill" claim below is asserted against a second school that must be
untouched — a single-tenant test cannot tell a correctly scoped query from one
that quietly bills the wrong children.
"""

from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import User
from accounts.services import enroll_student
from fees import schedules, services
from fees.models import (
    FeeConcession,
    FeeEntryKind,
    FeeLedgerEntry,
    FeeSchedule,
    FeeScheduleLine,
    KOBO_PER_NAIRA,
)
from schools.tests.tenants import connected_to, make_school

PASSWORD = "correct-horse-battery"

TUITION = 120_000 * KOBO_PER_NAIRA
LEVY = 15_000 * KOBO_PER_NAIRA


class BillingSetUp(TestCase):
    """Two schools, each with a JSS 1A, a first term, and children in it.

    St Mary's is the school under test. Grace Academy exists to be untouched:
    it has its own bill for its own class, with the same amounts, so that a
    query missing a schema filter would visibly change its balances.
    """

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.bursar = User.objects.create_user(
            "bursar", PASSWORD, full_name="Bola Bursar"
        )

        self.ada = self._student("ada", "Ada Obi", self.stmarys)
        self.chidi = self._student("chidi", "Chidi Okafor", self.stmarys)
        self.kemi = self._student("kemi", "Kemi Bello", self.stmarys)
        # Grace Academy's child, whose books must not move.
        self.ngozi = self._student("ngozi", "Ngozi Eze", self.grace)

        self.term_id, self.group_id, self.schedule_id = self._bill(
            self.stmarys, [self.ada, self.chidi]
        )
        self.their_term_id, self.their_group_id, self.their_schedule_id = self._bill(
            self.grace, [self.ngozi]
        )

    def _student(self, username, full_name, school):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        return enroll_student(user, school)

    def _bill(self, school, memberships):
        """A term, a JSS 1A with these children in it, and a two-line bill."""
        with connected_to(school):
            term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            for membership in memberships:
                academics.place_student(group, term, membership)

            schedule = FeeSchedule.objects.create(term=term, class_group=group)
            FeeScheduleLine.objects.create(
                schedule=schedule,
                description="Tuition",
                amount_kobo=TUITION,
                position=1,
            )
            FeeScheduleLine.objects.create(
                schedule=schedule,
                description="PTA levy",
                amount_kobo=LEVY,
                position=2,
            )
            return term.pk, group.pk, schedule.pk

    # -- fixtures reloaded inside a schema ----------------------------------

    def term(self):
        return Term.objects.get(pk=self.term_id)

    def schedule(self):
        return FeeSchedule.objects.get(pk=self.schedule_id)

    def apply(self, **kwargs):
        return schedules.apply_to_class(
            self.schedule(), by=self.bursar, **kwargs
        )

    def balance_of(self, membership):
        return FeeLedgerEntry.objects.for_student(membership.pk).balance()

    def assertRefusedBy(self, name):
        """A context manager asserting *which* constraint refused the write.

        `assertRaises(IntegrityError)` alone is the green test rule 5 warns
        about: any constraint firing for any reason passes it, including one
        that has nothing to do with what the test claims to be about. Naming it
        means the test goes red if the refusal starts coming from somewhere
        else — which is what happens when a constraint is renamed, dropped, or
        quietly replaced by a different one.
        """
        return self.assertRaisesRegex(IntegrityError, name)


class ApplyTests(BillingSetUp):
    """The ordinary run: everyone on the roster, every line of the bill."""

    def test_every_child_on_the_roster_is_charged_every_line(self):
        with connected_to(self.stmarys):
            summary = self.apply()

            self.assertEqual(summary.students, 2)
            self.assertEqual(summary.lines, 2)
            self.assertEqual(summary.charges_posted, 4)
            self.assertEqual(summary.charges_skipped, 0)
            self.assertEqual(summary.charged_kobo, 2 * (TUITION + LEVY))

            self.assertEqual(self.balance_of(self.ada), TUITION + LEVY)
            self.assertEqual(self.balance_of(self.chidi), TUITION + LEVY)

    def test_the_charge_freezes_the_line_description_rather_than_joining_to_it(self):
        """Rule 2: content is copied at write time, never joined to.

        Renaming a line next year must not relabel a charge already posted.
        """
        with connected_to(self.stmarys):
            self.apply()
            line = FeeScheduleLine.objects.get(description="PTA levy")
            line.description = "PTA levy (2027)"
            line.save(update_fields=["description"])

            posted = FeeLedgerEntry.objects.get(
                student_membership_id=self.ada.pk, source_line=line
            )
            self.assertEqual(posted.narration, "PTA levy")

    def test_the_other_school_is_untouched(self):
        with connected_to(self.stmarys):
            self.apply()

        with connected_to(self.grace):
            self.assertEqual(self.balance_of(self.ngozi), 0)
            self.assertEqual(FeeLedgerEntry.objects.count(), 0)

    def test_each_school_bills_its_own_class_from_its_own_schedule(self):
        """Both schools run their bill; neither one's entries land in the other."""
        with connected_to(self.stmarys):
            self.apply()
        with connected_to(self.grace):
            schedules.apply_to_class(
                FeeSchedule.objects.get(pk=self.their_schedule_id), by=self.bursar
            )
            self.assertEqual(self.balance_of(self.ngozi), TUITION + LEVY)
            self.assertEqual(FeeLedgerEntry.objects.count(), 2)

        with connected_to(self.stmarys):
            self.assertEqual(FeeLedgerEntry.objects.count(), 4)

    def test_every_entry_names_who_applied_the_bill_and_when_it_counts_for(self):
        """Rule 8's argument for having no run table: the entries carry it."""
        with connected_to(self.stmarys):
            self.apply(effective_on=date(2025, 9, 15))
            for entry in FeeLedgerEntry.objects.all():
                self.assertEqual(entry.recorded_by_id, self.bursar.pk)
                self.assertEqual(entry.effective_on, date(2025, 9, 15))
                self.assertIsNotNone(entry.source_line_id)


class IdempotencyTests(BillingSetUp):
    """Test 8 of the design: re-running is normal, and it charges nobody twice."""

    def test_applying_twice_charges_nobody_twice(self):
        with connected_to(self.stmarys):
            first = self.apply()
            second = self.apply()

            self.assertEqual(first.charges_posted, 4)
            self.assertEqual(second.charges_posted, 0)
            self.assertEqual(second.charges_skipped, 4)

            self.assertEqual(self.balance_of(self.ada), TUITION + LEVY)
            self.assertEqual(FeeLedgerEntry.objects.count(), 4)

    def test_a_child_admitted_after_the_first_run_is_the_only_one_charged(self):
        """The reason it skips rather than refuses: this is the ordinary case."""
        with connected_to(self.stmarys):
            self.apply()
            academics.place_student(
                ClassGroup.objects.get(pk=self.group_id), self.term(), self.kemi
            )

            second = self.apply()

            self.assertEqual(second.charges_posted, 2)
            self.assertEqual(second.charges_skipped, 4)
            self.assertEqual(self.balance_of(self.kemi), TUITION + LEVY)
            self.assertEqual(self.balance_of(self.ada), TUITION + LEVY)

    def test_a_line_added_later_charges_everybody_only_that_line(self):
        with connected_to(self.stmarys):
            self.apply()
            FeeScheduleLine.objects.create(
                schedule=self.schedule(),
                description="Excursion",
                amount_kobo=5_000 * KOBO_PER_NAIRA,
                position=3,
            )

            second = self.apply()

            self.assertEqual(second.charges_posted, 2)
            self.assertEqual(second.charges_skipped, 4)
            self.assertEqual(
                self.balance_of(self.ada), TUITION + LEVY + 5_000 * KOBO_PER_NAIRA
            )

    def test_a_reversed_charge_is_not_reposted_by_rerunning(self):
        """Test 9, and the corner the design ruled on rather than left to be filed.

        The reversed original still exists — the ledger is append-only, so it
        always will — and the index still sees it. Deliberately undoing a charge
        and then wanting it back takes an explicit `charge()`, not a second
        click on the same button.
        """
        with connected_to(self.stmarys):
            self.apply()
            tuition = FeeLedgerEntry.objects.get(
                student_membership_id=self.ada.pk,
                kind=FeeEntryKind.CHARGE,
                narration="Tuition",
            )
            services.reverse_entry(tuition)
            self.assertEqual(self.balance_of(self.ada), LEVY)

            second = self.apply()

            self.assertEqual(second.charges_posted, 0)
            self.assertEqual(self.balance_of(self.ada), LEVY)

    def test_a_reversal_inherits_the_source_line_it_undoes(self):
        """So that "everything this line did" returns the mistake and the fix."""
        with connected_to(self.stmarys):
            self.apply()
            line = FeeScheduleLine.objects.get(description="Tuition")
            charge = FeeLedgerEntry.objects.get(
                student_membership_id=self.ada.pk, source_line=line
            )
            reversal = services.reverse_entry(charge)

            self.assertEqual(reversal.source_line_id, line.pk)
            self.assertEqual(
                set(
                    FeeLedgerEntry.objects.filter(source_line=line).values_list(
                        "kind", flat=True
                    )
                ),
                {FeeEntryKind.CHARGE, FeeEntryKind.REVERSAL},
            )


class ConcessionTests(BillingSetUp):
    """A standing discount: applied per term, once per term, per concession."""

    def _grant(self, membership, amount_kobo, reason):
        return FeeConcession.objects.create(
            student_membership_id=membership.pk,
            amount_kobo=amount_kobo,
            reason=reason,
            granted_by_id=self.bursar.pk,
        )

    def test_a_concession_posts_a_discount_alongside_the_full_charge(self):
        """The child is charged in full and discounted, not billed less."""
        with connected_to(self.stmarys):
            self._grant(self.ada, TUITION, "Staff child")
            summary = self.apply()

            self.assertEqual(summary.discounts_posted, 1)
            self.assertEqual(self.balance_of(self.ada), LEVY)

            charged = FeeLedgerEntry.objects.filter(
                student_membership_id=self.ada.pk, kind=FeeEntryKind.CHARGE
            ).balance()
            self.assertEqual(charged, TUITION + LEVY)

    def test_two_concessions_for_one_child_are_two_discounts(self):
        with connected_to(self.stmarys):
            self._grant(self.ada, 20_000 * KOBO_PER_NAIRA, "Bursary 2026")
            self._grant(self.ada, 10_000 * KOBO_PER_NAIRA, "Sibling discount")

            summary = self.apply()

            self.assertEqual(summary.discounts_posted, 2)
            self.assertEqual(
                self.balance_of(self.ada),
                TUITION + LEVY - 30_000 * KOBO_PER_NAIRA,
            )

    def test_rerunning_does_not_discount_twice(self):
        with connected_to(self.stmarys):
            self._grant(self.ada, TUITION, "Staff child")
            self.apply()
            second = self.apply()

            self.assertEqual(second.discounts_posted, 0)
            self.assertEqual(second.discounts_skipped, 1)
            self.assertEqual(self.balance_of(self.ada), LEVY)

    def test_an_inactive_concession_posts_nothing(self):
        with connected_to(self.stmarys):
            concession = self._grant(self.ada, TUITION, "Staff child")
            concession.is_active = False
            concession.save(update_fields=["is_active"])

            summary = self.apply()

            self.assertEqual(summary.discounts_posted, 0)
            self.assertEqual(self.balance_of(self.ada), TUITION + LEVY)

    def test_the_same_concession_applies_again_next_term(self):
        """The key names the term, or a scholarship is granted once and never again."""
        with connected_to(self.stmarys):
            self._grant(self.ada, TUITION, "Staff child")
            self.apply()

            second_term = Term.objects.create(
                session="2025/2026",
                name=TermName.SECOND,
                starts_on=date(2026, 1, 12),
                ends_on=date(2026, 4, 3),
            )
            group = ClassGroup.objects.get(pk=self.group_id)
            academics.place_student(group, second_term, self.ada)
            next_bill = FeeSchedule.objects.create(
                term=second_term, class_group=group
            )
            FeeScheduleLine.objects.create(
                schedule=next_bill, description="Tuition", amount_kobo=TUITION
            )

            summary = schedules.apply_to_class(next_bill, by=self.bursar)

            self.assertEqual(summary.discounts_posted, 1)
            self.assertEqual(
                FeeLedgerEntry.objects.filter(
                    student_membership_id=self.ada.pk, kind=FeeEntryKind.DISCOUNT
                ).count(),
                2,
            )

    def test_a_reversed_discount_keeps_its_concession_and_is_not_reposted(self):
        """The mirror image of the schedule-line case, on the other index.

        `a_concession_discounts_a_child_once_per_term` is conditioned on
        `kind=DISCOUNT`, so a REVERSAL may carry the same concession without
        colliding with the discount it undoes — and the original discount row
        still exists, so re-running does not grant the concession again.
        """
        with connected_to(self.stmarys):
            concession = self._grant(self.ada, TUITION, "Staff child")
            self.apply()
            posted = FeeLedgerEntry.objects.get(
                student_membership_id=self.ada.pk, kind=FeeEntryKind.DISCOUNT
            )

            reversal = services.reverse_entry(posted)
            self.assertEqual(reversal.source_concession_id, concession.pk)

            second = self.apply()

            self.assertEqual(second.discounts_posted, 0)
            self.assertEqual(second.discounts_skipped, 1)
            self.assertEqual(self.balance_of(self.ada), TUITION + LEVY)

    def test_a_concession_for_another_schools_child_is_not_applied(self):
        """The roster is the filter, and the roster is this school's."""
        with connected_to(self.stmarys):
            # A concession row in St Mary's schema naming Grace Academy's child:
            # nothing in the database refuses it, which is the point.
            FeeConcession.objects.create(
                student_membership_id=self.ngozi.pk,
                amount_kobo=TUITION,
                reason="Not ours",
            )
            summary = self.apply()

            self.assertEqual(summary.discounts_posted, 0)
            self.assertFalse(
                FeeLedgerEntry.objects.filter(
                    student_membership_id=self.ngozi.pk
                ).exists()
            )


class RefusalTests(BillingSetUp):
    """What the service will not do, and says so rather than doing nothing."""

    def test_an_unitemised_bill_is_refused_rather_than_reported_as_nothing(self):
        with connected_to(self.stmarys):
            empty = FeeSchedule.objects.create(
                term=self.term(),
                class_group=ClassGroup.objects.create(name="JSS 2A", level=2),
            )
            with self.assertRaises(schedules.EmptySchedule):
                schedules.apply_to_class(empty, by=self.bursar)

    def test_an_empty_roster_posts_nothing_and_is_not_an_error(self):
        """A class nobody is placed in yet is a state, not a mistake."""
        with connected_to(self.stmarys):
            group = ClassGroup.objects.create(name="JSS 3A", level=3)
            bill = FeeSchedule.objects.create(term=self.term(), class_group=group)
            FeeScheduleLine.objects.create(
                schedule=bill, description="Tuition", amount_kobo=TUITION
            )

            summary = schedules.apply_to_class(bill, by=self.bursar)

            self.assertEqual(summary.students, 0)
            self.assertEqual(summary.charges_posted, 0)

    def test_every_refusal_is_a_fee_ledger_error(self):
        """`except FeeLedgerError` has to keep meaning "nothing was posted"."""
        self.assertTrue(issubclass(schedules.EmptySchedule, services.FeeLedgerError))
        self.assertTrue(issubclass(schedules.UnknownStudent, services.FeeLedgerError))


class ConstraintTests(BillingSetUp):
    """The database's half, asked directly rather than through the service."""

    def test_one_bill_per_class_per_term(self):
        with connected_to(self.stmarys):
            with self.assertRefusedBy(
                "one_fee_schedule_per_class_per_term"
            ), transaction.atomic():
                FeeSchedule.objects.create(
                    term=self.term(),
                    class_group=ClassGroup.objects.get(pk=self.group_id),
                )

    def test_a_bill_names_each_line_once(self):
        with connected_to(self.stmarys):
            with self.assertRefusedBy(
                "a_bill_names_each_line_once"
            ), transaction.atomic():
                FeeScheduleLine.objects.create(
                    schedule=self.schedule(), description="Tuition", amount_kobo=LEVY
                )

    def test_a_schedule_line_charges_something(self):
        with connected_to(self.stmarys):
            with self.assertRefusedBy(
                "a_schedule_line_charges_something"
            ), transaction.atomic():
                FeeScheduleLine.objects.create(
                    schedule=self.schedule(), description="Free", amount_kobo=0
                )

    def test_a_concession_says_why_and_whitespace_is_not_a_reason(self):
        with connected_to(self.stmarys):
            with self.assertRefusedBy(
                "a_concession_says_why"
            ), transaction.atomic():
                FeeConcession.objects.create(
                    student_membership_id=self.ada.pk,
                    amount_kobo=TUITION,
                    reason="   ",
                )

    def test_a_payment_may_not_name_a_schedule_line(self):
        """A source column has to agree with what the entry is."""
        with connected_to(self.stmarys):
            line = FeeScheduleLine.objects.get(description="Tuition")
            with self.assertRefusedBy(
                "a_schedule_line_only_produces_charges"
            ), transaction.atomic():
                FeeLedgerEntry.objects.create(
                    term=self.term(),
                    student_membership_id=self.ada.pk,
                    student_name="Ada Obi",
                    kind=FeeEntryKind.PAYMENT,
                    amount_kobo=-TUITION,
                    narration="Payment",
                    effective_on=date(2025, 9, 20),
                    source_line=line,
                )

    def test_an_entry_has_one_source(self):
        """And the only kind that can even reach this constraint is a REVERSAL.

        Worth stating, because the first version of this test asserted the
        wrong thing and passed: it posted a CHARGE naming both a line and a
        concession, which is refused by `a_concession_only_produces_discounts`
        — a charge may not name a concession at all — so
        `an_entry_has_one_source` was never reached. The test was green, and
        green for a reason that had nothing to do with its name.

        For every kind except REVERSAL one of the two kind-agreement
        constraints refuses one of the two columns first. A reversal is in both
        `SCHEDULE_SOURCED_KINDS` and `CONCESSION_SOURCED_KINDS`, because it
        inherits whichever source its target had — so it is the one row shape
        where "both at once" is the *only* thing wrong with it.
        """
        with connected_to(self.stmarys):
            self.apply()
            line = FeeScheduleLine.objects.get(description="Tuition")
            concession = FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )
            charge = FeeLedgerEntry.objects.get(
                student_membership_id=self.ada.pk, source_line=line
            )

            with self.assertRefusedBy(
                "an_entry_has_one_source"
            ), transaction.atomic():
                FeeLedgerEntry.objects.create(
                    term=self.term(),
                    student_membership_id=self.ada.pk,
                    student_name="Ada Obi",
                    kind=FeeEntryKind.REVERSAL,
                    amount_kobo=-charge.amount_kobo,
                    narration="Both at once",
                    effective_on=date(2025, 9, 20),
                    reverses=charge,
                    source_line=line,
                    source_concession=concession,
                )

    def test_a_charge_may_not_name_a_concession(self):
        """The constraint that fired instead, now asserted in its own right."""
        with connected_to(self.stmarys):
            concession = FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )
            with self.assertRefusedBy(
                "a_concession_only_produces_discounts"
            ), transaction.atomic():
                FeeLedgerEntry.objects.create(
                    term=self.term(),
                    student_membership_id=self.ada.pk,
                    student_name="Ada Obi",
                    kind=FeeEntryKind.CHARGE,
                    amount_kobo=TUITION,
                    narration="Charge naming a concession",
                    effective_on=date(2025, 9, 20),
                    source_concession=concession,
                )


class RefundTests(BillingSetUp):
    """The new kind, and the sign that surprises people."""

    def test_a_refund_moves_a_credit_balance_back_towards_zero(self):
        with connected_to(self.stmarys):
            term = self.term()
            services.record_payment(self.ada, term, 50_000 * KOBO_PER_NAIRA)
            self.assertEqual(self.balance_of(self.ada), -50_000 * KOBO_PER_NAIRA)

            services.refund(
                self.ada, term, 50_000 * KOBO_PER_NAIRA, narration="Cash returned"
            )

            self.assertEqual(self.balance_of(self.ada), 0)

    def test_a_refund_is_told_apart_from_a_reversal_in_the_books(self):
        """Money handed back and a mistake undone are different facts."""
        with connected_to(self.stmarys):
            term = self.term()
            services.refund(self.ada, term, 10_000 * KOBO_PER_NAIRA)
            entry = FeeLedgerEntry.objects.get(kind=FeeEntryKind.REFUND)

            self.assertGreater(entry.amount_kobo, 0)
            self.assertIsNone(entry.reverses_id)

    def test_a_negative_refund_is_refused_by_the_service(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.NotPositive):
                services.refund(self.ada, self.term(), -1)


class SkipIsNotTheIndexTests(BillingSetUp):
    """Two mechanisms, proved separately — rule 5's "a control, or it proves nothing".

    `IdempotencyTests` above passes if the service skips correctly. It would
    pass just as well against a schema with no unique index at all, because the
    skip means the index is never reached. So this asks the index directly, by
    posting the second charge the way a racing application would: past the skip.
    """

    def test_the_index_refuses_a_second_charge_for_one_line_and_child(self):
        with connected_to(self.stmarys):
            self.apply()
            line = FeeScheduleLine.objects.get(description="Tuition")

            with self.assertRefusedBy(
                "a_schedule_line_charges_a_child_once"
            ), transaction.atomic():
                services.charge(
                    self.ada,
                    self.term(),
                    TUITION,
                    narration="Tuition again",
                    source_line=line,
                )

    def test_the_index_refuses_a_second_discount_for_one_concession_and_term(self):
        with connected_to(self.stmarys):
            concession = FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )
            self.apply()

            with self.assertRefusedBy(
                "a_concession_discounts_a_child_once_per_term"
            ), transaction.atomic():
                services.discount(
                    self.ada,
                    self.term(),
                    TUITION,
                    narration="Staff child again",
                    source_concession=concession,
                )

    def test_a_hand_posted_charge_without_a_source_is_not_blocked_by_the_index(self):
        """The index is keyed on the line, so it must not fence ordinary charges."""
        with connected_to(self.stmarys):
            self.apply()
            services.charge(
                self.ada, self.term(), 2_000 * KOBO_PER_NAIRA, narration="Late fee"
            )
            services.charge(
                self.ada, self.term(), 2_000 * KOBO_PER_NAIRA, narration="Late fee"
            )
            self.assertEqual(
                FeeLedgerEntry.objects.filter(
                    student_membership_id=self.ada.pk, narration="Late fee"
                ).count(),
                2,
            )
