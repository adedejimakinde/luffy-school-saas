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
from unittest import mock

from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test.utils import CaptureQueriesContext
from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Membership, MembershipStatus, User
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

    def test_the_charge_freezes_the_amount_too_not_only_the_wording(self):
        """`fees.md` claims the entry freezes "the amount and the narration".

        The narration half had a test and the amount half did not, which is how
        half-true claims survive: the sentence reads as covered.
        """
        with connected_to(self.stmarys):
            self.apply()
            line = FeeScheduleLine.objects.get(description="Tuition")
            line.amount_kobo = 999_000 * KOBO_PER_NAIRA
            line.save(update_fields=["amount_kobo"])

            posted = FeeLedgerEntry.objects.get(
                student_membership_id=self.ada.pk, source_line=line
            )
            self.assertEqual(posted.amount_kobo, TUITION)
            self.assertEqual(self.balance_of(self.ada), TUITION + LEVY)

    def test_a_mid_term_move_charges_twice_and_waives_once(self):
        """The interaction `fees.md` now states, asserted rather than described.

        `ClassPlacement` rewrites on a move, so the child leaves JSS 1A's roster
        — but JSS 1A's charge is a posted fact and stays. The concession is keyed
        on the term, so the second bill does not waive again. The family owes two
        bills less one waiver until a person reverses the one they are no longer
        sitting for, and that is the sentence a bursar has to be able to act on.
        """
        with connected_to(self.stmarys):
            FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )
            first = self.apply()
            self.assertEqual(first.discounts_posted, 1)

            # The child moves to another class, in the same term.
            senior = ClassGroup.objects.create(name="JSS 3A", level=3)
            academics.move_student(senior, self.term(), self.ada)
            their_bill = FeeSchedule.objects.create(
                term=self.term(), class_group=senior
            )
            FeeScheduleLine.objects.create(
                schedule=their_bill, description="Tuition", amount_kobo=TUITION
            )

            second = schedules.apply_to_class(their_bill, by=self.bursar)

            # Charged again by the new bill...
            self.assertEqual(second.charges_posted, 1)
            # ...and not waived again, because the waiver is a fact about the term.
            self.assertEqual(second.discounts_posted, 0)
            self.assertEqual(second.discounts_skipped, 1)

            # The old class's charge is still standing. Nothing recomputed it away.
            self.assertEqual(
                self.balance_of(self.ada), TUITION + LEVY + TUITION - TUITION
            )
            self.assertEqual(
                FeeLedgerEntry.objects.filter(
                    student_membership_id=self.ada.pk, kind=FeeEntryKind.CHARGE
                ).count(),
                3,
            )

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
    """Re-running is normal, and it charges nobody twice.

    Was "Test 8 of the design". The design doc's numbered list is the withholding
    half now, and it ends at 7 — the billing items moved into `docs/fees.md`, so
    the number pointed at nothing.
    """

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
        """The corner the design ruled on rather than left to be filed.

        The reversed original still exists — the ledger is append-only, so it
        always will — and the index still sees it, so a re-run posts nothing.

        **Not** "wanting it back takes an explicit `charge()`", which is what
        this docstring used to say and what the test immediately below disproves:
        the index is on the row rather than on the caller, so an explicit charge
        naming the same line is refused exactly as the re-run is. That claim was
        corrected in the model docstring and in `fees.md` and survived here, in
        the one file whose own test contradicts it.
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

    def test_what_reposting_a_reversed_charge_actually_takes(self):
        """The escape hatch, tested rather than asserted.

        The docs said a reversed charge "takes an explicit `charge()`". That
        was wrong, and only running it says so: the index is on the *row*, not
        on the code path, so an explicit charge carrying the same `source_line`
        is refused exactly as the re-run is. What actually works is a charge
        that does not name the line — which severs the new row from the line
        that billed it, and is the cost of the corner rather than a workaround
        for it.
        """
        with connected_to(self.stmarys):
            self.apply()
            line = FeeScheduleLine.objects.get(description="Tuition")
            charge = FeeLedgerEntry.objects.get(
                student_membership_id=self.ada.pk, source_line=line
            )
            services.reverse_entry(charge)

            # Naming the line: refused, whoever is asking.
            with self.assertRefusedBy(
                "a_schedule_line_charges_a_child_once"
            ), transaction.atomic():
                services.charge(
                    self.ada,
                    self.term(),
                    TUITION,
                    narration="Tuition, re-posted",
                    source_line=line,
                )

            # Not naming it: posts, and is not attributable to the line.
            reposted = services.charge(
                self.ada, self.term(), TUITION, narration="Tuition, re-posted"
            )
            self.assertIsNone(reposted.source_line_id)
            self.assertEqual(
                FeeLedgerEntry.objects.filter(
                    source_line=line, student_membership_id=self.ada.pk
                ).count(),
                2,  # this child's original charge and its reversal. Not the re-post.
            )

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


class LockScopeTests(BillingSetUp):
    """What the module docstring claims about its own lock, asserted.

    Two claims, both of the kind that reads as obviously true and is a fact about
    compiled SQL: **the roster is read once**, and **the lock joins nothing**.
    Issue #78 records what the second one costs when it stops holding — a
    `SELECT ... FOR UPDATE` takes a row lock in every table it joins, so an
    ordering or a `select_related()` that reaches through a relation quietly
    locks rows the operation never writes. Three sites in this repo have that
    bug; this test is why this one cannot join them silently.
    """

    def test_the_roster_is_read_once(self):
        """#43's discipline: 'who is being billed' is decided once."""
        with connected_to(self.stmarys):
            with CaptureQueriesContext(connection) as captured:
                self.apply()

            roster_reads = [
                q["sql"]
                for q in captured.captured_queries
                if "academics_classplacement" in q["sql"]
            ]
            self.assertEqual(
                len(roster_reads),
                1,
                "the roster was read %d times:\n%s"
                % (len(roster_reads), "\n".join(roster_reads)),
            )

    def test_the_schedule_lock_joins_nothing(self):
        """The lock must reach the schedule row and no other table.

        **This test catches the `select_related()` half only**, and the two
        halves were checked separately rather than assumed. Adding
        `select_related("term")` to the locked queryset turns it red:

            AssertionError: 'JOIN' unexpectedly found in
            '... FROM "fees_feeschedule"
             INNER JOIN "academics_term" ON (...) WHERE ... FOR UPDATE'

        Changing `Meta.ordering` to name the relation does **not** turn it red,
        because `.get()` clears ordering — which is exactly why the ordering has
        its own test below. Assuming this one covered both is the same mistake as
        crediting the lock with the index's work.
        """
        with connected_to(self.stmarys), transaction.atomic():
            locked = FeeSchedule.objects.select_for_update().filter(
                pk=self.schedule_id
            )
            sql = str(locked.order_by().query)  # what .get() compiles to
            self.assertNotIn("JOIN", sql, f"the locked query joins:\n{sql}")

    def test_meta_ordering_names_columns_and_not_relations(self):
        """The property behind the test above, stated where it can be checked.

        A relation in `Meta.ordering` is what puts the join there in two of
        issue #78's three sites, and it is added by a one-line edit that looks
        like tidying.

        **This is the half `test_the_schedule_lock_joins_nothing` cannot see.**
        Rewriting `FeeSchedule.Meta.ordering` to `["class_group", "id"]` turns
        this test red and leaves that one green, because `.get()` clears
        ordering — so the join would only appear the day somebody changed the
        terminal call to `.first()`, which is how `academics/services.py:244`
        got its bug. Pinning the ordering means the trap is never armed.
        """
        # `FeeLedgerEntry` included, and it is the one that matters most: it is
        # the model `reverse_entry()` locks with `select_for_update()`, so a
        # relation in *its* `Meta.ordering` is not two joins of waste but an
        # exclusive lock on rows the reversal never writes. The guard that
        # enumerated only the three new models could not see the one place the
        # trap actually bites.
        #
        # `ClassPlacement` is deliberately absent and is a live violation, not an
        # oversight: its ordering is `["class_group", ...]`, so the roster read
        # at the top of `apply_to_class()` joins `academics_classgroup` to sort
        # by a column it discards. Filed rather than fixed here — it is
        # `academics`' row and belongs with the audit in #78.
        for model in (FeeSchedule, FeeScheduleLine, FeeConcession, FeeLedgerEntry):
            for entry in model._meta.ordering:
                name = entry.lstrip("-")

                # `school__name` — ordering that walks a relation explicitly.
                self.assertNotIn(
                    "__",
                    name,
                    f"{model.__name__}.Meta.ordering walks a relation via {entry!r}",
                )

                # `class_group` — a bare ForeignKey name, which is the form that
                # bites: Django sorts by the *related* model's Meta.ordering and
                # joins to get it. `class_group_id` is the same intent with no
                # join, and is what this project's Meta lines must say.
                field = model._meta.get_field(name)
                if not field.is_relation:
                    continue

                # `get_field()` resolves both spellings to the same field, so the
                # field alone cannot say which was written. `attname` is the
                # column (`class_group_id`) and `name` is the relation
                # (`class_group`), and only the first orders without a join.
                self.assertEqual(
                    name,
                    field.attname,
                    f"{model.__name__}.Meta.ordering names the relation "
                    f"{entry!r}; use {field.attname!r} so the query does not "
                    f"join (see issue #78)",
                )


    def test_the_concession_read_is_ordered_so_two_bills_cannot_deadlock(self):
        """The one ordering in this module that carries a concurrency guarantee.

        Two runs of two *different* schedules in one term can reach the same
        `(child, term, concession)` rows — that overlap is what
        `ConcessionRaceTests` below is about. Reaching those rows in a total
        order every run shares makes a deadlock cycle impossible. Reaching them
        in different orders is SQLSTATE `40P01`, which Django raises as
        `OperationalError` — and `apply_to_class()` catches `IntegrityError`.
        The handler never sees it, so it cannot become a skip: the loser's whole
        transaction dies and the class goes unbilled. That is the same
        forty-five-children outcome the skip exists to prevent, reached by the
        one route the skip cannot cover.

        **Asserted against compiled SQL, because that is where the guarantee
        lives.** Postgres takes its row locks in the order the rows arrive, so
        the `ORDER BY` it receives *is* the property; no assertion about Python
        objects can stand in for it. Before the explicit `.order_by()` this
        clause was inherited from `FeeConcession.Meta.ordering`, which is the
        failure mode and not the reassurance it looks like: the guarantee held
        by accident, one `Meta` edit away from being removed with the whole
        suite still green. An explicit order that nothing pins is the same shape
        as a claim nothing tests.
        """
        with connected_to(self.stmarys):
            # Two children with concessions, because a single row cannot be
            # ordered wrongly and so cannot fail this test for the real reason.
            for child in (self.ada, self.chidi):
                FeeConcession.objects.create(
                    student_membership_id=child.pk,
                    amount_kobo=LEVY,
                    reason="Staff child",
                )

            with CaptureQueriesContext(connection) as captured:
                self.apply()

            # Matched on a real column rather than on the table name: posting
            # each discount runs `full_clean()`, whose `ForeignKey.validate()`
            # probes this same table with `SELECT 1 AS "a" ... LIMIT 1`. Those
            # probes are single-row lookups by primary key — no ordering to
            # carry and no lock ordering to get wrong — so counting them here
            # would make this assertion fail once per concession for a reason
            # that has nothing to do with what it tests.
            reads = [
                q["sql"]
                for q in captured.captured_queries
                if '"fees_feeconcession"."amount_kobo"' in q["sql"]
            ]
            self.assertEqual(
                len(reads),
                1,
                "expected one concession read, found %d:\n%s"
                % (len(reads), "\n".join(reads)),
            )

            # The whole clause and not merely "an ORDER BY is present": the
            # guarantee is a *total* order, so both columns and their sequence
            # are the property being pinned. `student_membership_id` alone
            # leaves two concessions for one child unordered between them, which
            # is enough for two runs to take the same two locks in opposite
            # orders.
            self.assertIn(
                'ORDER BY "fees_feeconcession"."student_membership_id" ASC, '
                '"fees_feeconcession"."id" ASC',
                reads[0],
                "the concession read no longer pins its order. Two bills "
                "sharing concessions can now deadlock (SQLSTATE 40P01), which "
                "arrives as OperationalError and is invisible to the "
                "IntegrityError handler in apply_to_class():\n" + reads[0],
            )

            # **And it survives `Meta`.** The assertion above passes just as
            # happily against an ordering inherited from
            # `FeeConcession.Meta.ordering`, which is precisely the state this
            # change was made to leave: a guarantee that holds by accident and
            # goes away silently the day somebody edits a `Meta` line for
            # unrelated reasons. Emptying the model's ordering here is that edit,
            # made in the one place it can be observed, and the clause has to
            # still be there afterwards. Delete the explicit `.order_by()` from
            # `apply_to_class()` and this half goes red on its own.
            with mock.patch.object(FeeConcession._meta, "ordering", []):
                with CaptureQueriesContext(connection) as without_meta:
                    self.apply()

            unordered = [
                q["sql"]
                for q in without_meta.captured_queries
                if '"fees_feeconcession"."amount_kobo"' in q["sql"]
                and "ORDER BY" not in q["sql"]
            ]
            self.assertEqual(
                unordered,
                [],
                "the concession read's order comes from FeeConcession.Meta and "
                "not from apply_to_class(), so a Meta edit removes a "
                "concurrency guarantee with nothing going red:\n"
                + "\n".join(unordered),
            )


class ConcessionRaceTests(BillingSetUp):
    """The one race the schedule lock does not cover, and what it must not cost.

    `select_for_update()` on the schedule serialises applications of *that bill*.
    `a_concession_discounts_a_child_once_per_term` spans every bill in the term,
    so two runs of two **different** schedules can both pass the discount
    skip-check for one child — reachable when a child moves class mid-term and
    sits in one bursar's roster snapshot and another's at the same moment.

    The collision is not the harm. The harm is that one transaction covers the
    whole class, so a discount that collides would take forty-five children's
    charges down with it.

    Forced deterministically rather than raced: the real threading version needs
    a third actor moving a child between two reads inside a function with no
    pause point, so this drives the branch by making the write collide.
    """

    def _racing_discount(self, note="Posted by the other bill"):
        """The real `discount()`, with another bursar's row landing first."""
        real = schedules.services.discount

        def racing(membership, term, amount_kobo, **kwargs):
            FeeLedgerEntry.objects.create(
                term=term,
                student_membership_id=membership.pk,
                student_name=membership.name,
                kind=FeeEntryKind.DISCOUNT,
                amount_kobo=-amount_kobo,
                narration=note,
                effective_on=date(2025, 9, 20),
                source_concession=kwargs["source_concession"],
            )
            return real(membership, term, amount_kobo, **kwargs)

        return racing

    def test_a_discount_another_bill_posted_is_a_skip_not_a_dead_run(self):
        with connected_to(self.stmarys):
            FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )

            with mock.patch.object(
                schedules.services, "discount", self._racing_discount()
            ):
                summary = self.apply()

            # The run finished. That is the whole point.
            self.assertEqual(summary.charges_posted, 4)
            self.assertEqual(summary.discounts_posted, 0)
            self.assertEqual(summary.discounts_skipped, 1)

            # And the child has their concession — the other bill posted it.
            self.assertEqual(
                FeeLedgerEntry.objects.filter(
                    student_membership_id=self.ada.pk, kind=FeeEntryKind.DISCOUNT
                ).count(),
                1,
            )
            self.assertEqual(self.balance_of(self.ada), LEVY)

    def test_an_unrecognised_integrity_error_is_raised_and_not_swallowed(self):
        """The narrowing is the point: only *this* constraint counts as a skip.

        A collision predicate that answered "was there an IntegrityError?" would
        turn every future constraint on this table into a silent skipped
        discount, which is the shape of bug that never gets reported.
        """
        with connected_to(self.stmarys):
            FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )

            def unrelated(*args, **kwargs):
                raise IntegrityError("something else entirely")

            with mock.patch.object(schedules.services, "discount", unrelated):
                with self.assertRaises(IntegrityError):
                    self.apply()


    def test_a_real_violation_of_another_constraint_is_raised_not_swallowed(self):
        """The predicate arm the test above cannot reach.

        `test_an_unrecognised_integrity_error_is_raised_and_not_swallowed`
        raises a bare `IntegrityError` with no `__cause__` at all, so it only
        exercises the **no diagnostics** arm of `_is_the_concession_colliding()`
        — the arm that answers "not a collision" because there is nothing to
        read. That arm is real, and it is not the one that matters for the
        future.

        The one that matters is a genuine Postgres unique violation carrying
        genuine diagnostics and naming a **different** index. That is what every
        constraint added to this table from now on looks like the day it first
        fires, and the branch that re-raises it is the only thing standing
        between a future constraint and a silently skipped discount. Untested,
        it was the guard against silent swallowing that was itself unguarded.

        **A real exception rather than a constructed one.** A hand-built stand-in
        with a fake `.diag` would assert against this test's idea of psycopg
        rather than psycopg's, and the `pgcode`/`constraint_name` pair is
        exactly what the predicate reads — so it is forced by making a real
        second `FeeSchedule` for a class that already has one, and re-raising
        what Postgres hands back.
        """
        with connected_to(self.stmarys):
            FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )

            def a_different_unique_violation(*args, **kwargs):
                """A real 23505 from a real index — just not this one.

                Inside `atomic()` so the failed statement rolls back to a
                savepoint: the exception has to travel out of here as a live
                object on a usable connection, not leave a poisoned transaction
                behind it.
                """
                try:
                    with transaction.atomic():
                        FeeSchedule.objects.create(
                            term=self.term(),
                            class_group=ClassGroup.objects.get(pk=self.group_id),
                        )
                except IntegrityError as real:
                    raise real
                raise AssertionError(
                    "a duplicate schedule was accepted, so this test no longer "
                    "produces the unique violation it exists to hand back"
                )

            with mock.patch.object(
                schedules.services, "discount", a_different_unique_violation
            ):
                with self.assertRaises(IntegrityError) as raised:
                    self.apply()

            # This test is only about the branch it names if the exception it
            # forced actually carries what the other test's does not. Without
            # these two, a future refactor could route it down the no-diagnostics
            # arm and the coverage would silently go back to one branch.
            cause = raised.exception.__cause__
            self.assertEqual(cause.pgcode, "23505", "not a unique violation")
            self.assertEqual(
                cause.diag.constraint_name,
                "one_fee_schedule_per_class_per_term",
                "the diagnostics do not name a different constraint, so the "
                "different-name branch was not the one exercised",
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

    def test_a_child_whose_membership_has_ended_is_skipped_and_counted(self):
        """The roster outlives the enrolment, so billing it blindly bills leavers.

        Nothing deletes a `ClassPlacement` when a membership ends — the
        placement is last term's record and is supposed to survive — so a child
        released in December is still on JSS 1A's roster in January. A bursar
        adding one line to that term's bill and re-running would charge them.

        Skipped rather than refused, because refusing is the forty-five-children
        outcome again: one child having left must not stop the class being
        billed. `academics` already made this call — `carry_forward_placements()`
        filters ended memberships and calls that "a correctness rule and not a
        tidiness one", while `place_student()` deliberately allows an ended child
        to be placed by hand, because entering last term's roster after the fact
        is real work.

        **Counted, and that is the half worth asserting.** A skip nobody is told
        about is the silent no-op this module refuses everywhere else, and
        `students` now means "billed" rather than "on the roster" — a change to
        an existing field's meaning that only `students_skipped` makes legible.
        """
        with connected_to(self.stmarys):
            summary = self.apply()
            self.assertEqual(summary.students, 2)
            self.assertEqual(summary.students_skipped, 0)

        self.chidi.end()

        with connected_to(self.stmarys):
            # A second line, so the re-run has something to post and the ended
            # child's skip is not confused with ordinary idempotency.
            FeeScheduleLine.objects.create(
                schedule=self.schedule(),
                description="Exam fee",
                amount_kobo=LEVY,
                position=3,
            )

            second = self.apply()

            self.assertEqual(second.students, 1, "the leaver was still billed")
            self.assertEqual(second.students_skipped, 1)
            self.assertEqual(second.charges_posted, 1, "only Ada's exam fee")

            # The leaver's books are untouched by the re-run — the charges from
            # when they *were* enrolled stand, because the ledger is append-only
            # and last term really did happen.
            self.assertEqual(self.balance_of(self.chidi), TUITION + LEVY)
            self.assertEqual(self.balance_of(self.ada), TUITION + 2 * LEVY)

    def test_the_summary_says_so_when_it_skipped_a_leaver(self):
        """`students_skipped` reaches the bursar's screen, not just the tuple.

        `__str__` is what a management command prints and what an operator
        reads. A count carried in a field nobody renders is the same silence as
        not counting it.
        """
        with connected_to(self.stmarys):
            self.assertNotIn("no longer enrolled", str(self.apply()))

        self.chidi.end()

        with connected_to(self.stmarys):
            FeeScheduleLine.objects.create(
                schedule=self.schedule(),
                description="Exam fee",
                amount_kobo=LEVY,
                position=3,
            )
            self.assertIn("1 no longer enrolled", str(self.apply()))

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

    def test_a_concession_reduces_something(self):
        """The twin of `test_a_schedule_line_charges_something`, and the gap.

        Two check constraints of identical shape guard the two amounts this
        module posts; one had a test and one did not, and the asymmetry is the
        only reason the gap was visible at all.

        It is load-bearing, not decorative. `apply_to_class()` argues that a
        concession discount's amount is **always** strictly negative — the
        amount is `-_magnitude(concession.amount_kobo)`, and this constraint is
        what forces the source above zero. That argument is the first step in
        narrowing the ten constraints on `FeeLedgerEntry` down to the one the
        collision handler treats as a skip. A zero-kobo concession would post a
        zero-amount entry, trip `a_ledger_entry_moves_money` instead, and the
        predicate would re-raise it — so the narrowing would still be honest,
        but only by accident rather than because this check holds.

        Both directions, because `gt=0` refuses both and the negative one is
        the alarming case: `_magnitude()` takes an absolute value, so a
        concession stored negative would post exactly like a positive one and
        the sign error would never surface.
        """
        for amount_kobo in (0, -TUITION):
            with self.subTest(amount_kobo=amount_kobo):
                with connected_to(self.stmarys):
                    with self.assertRefusedBy(
                        "a_concession_reduces_something"
                    ), transaction.atomic():
                        FeeConcession.objects.create(
                            student_membership_id=self.ada.pk,
                            amount_kobo=amount_kobo,
                            reason="Nothing off",
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


class DeletabilityTests(BillingSetUp):
    """What a bursar may delete, and what the ledger refuses to let go of.

    These pin claims that were made in docstrings and asserted nowhere. The
    cascade-versus-PROTECT one is the kind that reads as obviously true and is a
    statement about Django's collector, not about this schema — the same class of
    claim as the re-post corner, which was wrong.
    """

    def test_a_line_that_has_charged_nobody_is_freely_deletable(self):
        """The rule a bursar actually needs: fix next term's bill."""
        with connected_to(self.stmarys):
            line = FeeScheduleLine.objects.create(
                schedule=self.schedule(), description="Typo", amount_kobo=LEVY
            )
            line.delete()
            self.assertFalse(
                FeeScheduleLine.objects.filter(description="Typo").exists()
            )

    def test_a_line_that_has_billed_a_family_cannot_be_deleted(self):
        with connected_to(self.stmarys):
            self.apply()
            line = FeeScheduleLine.objects.get(description="Tuition")
            with self.assertRaises(ProtectedError):
                line.delete()

    def test_deleting_the_schedule_does_not_cascade_past_a_posted_charge(self):
        """The claim: PROTECT on the entry beats CASCADE on the line.

        `FeeScheduleLine.schedule` is CASCADE, so deleting a used schedule would
        take its lines with it — and each line is PROTECTed by the charges it
        posted. Which wins is a fact about Django's collector rather than about
        this schema, so it is asserted rather than reasoned about.
        """
        with connected_to(self.stmarys):
            self.apply()
            schedule = self.schedule()
            with self.assertRaises(ProtectedError):
                schedule.delete()

            # And nothing was taken down on the way to the refusal.
            self.assertEqual(FeeScheduleLine.objects.filter(schedule=schedule).count(), 2)
            self.assertEqual(FeeLedgerEntry.objects.count(), 4)

    def test_an_unused_schedule_deletes_with_its_lines(self):
        with connected_to(self.stmarys):
            spare = FeeSchedule.objects.create(
                term=self.term(),
                class_group=ClassGroup.objects.create(name="JSS 4A", level=4),
            )
            FeeScheduleLine.objects.create(
                schedule=spare, description="Tuition", amount_kobo=TUITION
            )
            spare.delete()
            self.assertFalse(FeeScheduleLine.objects.filter(schedule_id=spare.pk).exists())

    def test_a_concession_that_has_discounted_a_family_cannot_be_deleted(self):
        """Which is why it has `is_active` rather than being deleted."""
        with connected_to(self.stmarys):
            concession = FeeConcession.objects.create(
                student_membership_id=self.ada.pk,
                amount_kobo=TUITION,
                reason="Staff child",
            )
            self.apply()
            with self.assertRaises(ProtectedError):
                concession.delete()


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


class _StatusLeftUnloaded:
    """`Membership`, but the schedules read leaves `status` unfetched.

    Stands in for `fees.schedules.Membership` so the control below changes one
    thing only — whether `status` is loaded — while every other part of
    `apply_to_class()` runs as written. `defer()` rather than `only()` because
    the read chains `select_related("user", "school")` onto this queryset, and
    Django refuses a field that is both deferred and traversed.
    """

    class objects:
        @staticmethod
        def filter(*args, **kwargs):
            return Membership.objects.filter(*args, **kwargs).defer("status")


class LeaverReadTests(BillingSetUp):
    """The leaver skip is a Python property read, so the *object* is the guard.

    `apply_to_class()` decides who is billed with `memberships[sid].is_live`, in
    memory, over a dict the same commit gave `select_related("user", "school")`.
    Two things follow, and only the second is load-bearing:

    1. **`select_related` is not what makes the skip right.** `is_live` returns
       `self.status in LIVE_STATUSES` and reads nothing else, so breaking the
       join costs queries in `snapshot_student()`, not correctness here. Saying
       otherwise would be reasoning about the wrong field.
    2. **A loaded `status` is what makes it right.** Deferred, `.status` becomes
       a lazy refetch of a row the function already read, issued later and
       inside the schedule lock — the second-read-per-locked-block shape this
       project keeps hitting. The two reads can disagree, and the decision is
       taken on the later one.

    Nothing downstream would catch the disagreement. `why_not_a_student_here()`
    checks `role` and `school.schema_name` and never `status`, so this filter is
    the only thing standing between a leaver and a charge — and, the direction
    that costs money quietly, between an enrolled child and never being invoiced
    at all. A wrongly-skipped child raises no error and posts no row; the class
    bills, the summary reads plausibly, and the miss surfaces when a parent asks
    why no invoice ever came.
    """

    def _watch_is_live(self, on_first_call=None):
        """Record what each membership had loaded when `is_live` was consulted.

        Returns the record and the patch, rather than asserting inside the
        wrapper, so a test that never reaches the property fails on an empty
        record instead of passing by not looking.
        """
        seen = []
        real = Membership.is_live.fget

        def watched(membership):
            seen.append((membership.pk, frozenset(membership.get_deferred_fields())))
            if on_first_call is not None and len(seen) == 1:
                on_first_call()
            return real(membership)

        return seen, mock.patch.object(Membership, "is_live", property(watched))

    def _end_mid_flight(self, membership):
        """End a membership in the database, leaving loaded copies untouched."""

        def change():
            Membership.objects.filter(pk=membership.pk).update(
                status=MembershipStatus.ENDED
            )

        return change

    def test_the_object_is_live_reads_has_its_status_loaded(self):
        """Proven on the instance, not inferred from the absence of `only()`."""
        seen, watching = self._watch_is_live()
        with connected_to(self.stmarys), watching:
            summary = self.apply()

        self.assertEqual(summary.students, 2)
        # Non-vacuous: the property is what decided, and for both children.
        self.assertEqual(
            sorted(pk for pk, _ in seen),
            sorted([self.ada.pk, self.chidi.pk]),
        )
        for pk, deferred in seen:
            self.assertEqual(
                deferred,
                frozenset(),
                f"membership {pk} reached is_live with fields unloaded: "
                f"{sorted(deferred)} — reading one is a second query for a row "
                f"this function already read",
            )

    def test_deciding_the_skip_costs_no_second_read_of_the_membership(self):
        """One read of the row, so there is no later read to disagree with it."""
        with connected_to(self.stmarys):
            with CaptureQueriesContext(connection) as captured:
                self.apply()

        reads = [
            q["sql"]
            for q in captured.captured_queries
            if "accounts_membership" in q["sql"]
            and q["sql"].lstrip().upper().startswith("SELECT")
        ]
        self.assertEqual(
            len(reads),
            1,
            "the memberships are read once and decided from that read; "
            f"{len(reads)} reads means status can be fetched again later:\n"
            + "\n".join(reads),
        )

    def test_a_deferred_status_would_drop_an_enrolled_child_from_billing(self):
        """The control: same mutation, two fetch strategies, two different bills.

        A membership ends *while* the class is being billed. As written the
        decision is taken from the read the function already holds, so the child
        is billed and the change lands on the next application. With `status`
        deferred the decision is taken from a refetch issued after the change,
        and the child is skipped — no error, no row, nothing to notice.
        """
        # As written: status is loaded, and the mid-flight change cannot reach it.
        seen, watching = self._watch_is_live(self._end_mid_flight(self.chidi))
        with connected_to(self.stmarys), watching:
            loaded = self.apply()

            self.assertEqual(loaded.students, 2, "the enrolled child was billed")
            self.assertEqual(loaded.students_skipped, 0)
            self.assertEqual(self.balance_of(self.chidi), TUITION + LEVY)
        self.assertEqual([deferred for _, deferred in seen], [frozenset(), frozenset()])

        # Put the child back, and give the next run something new to post so a
        # skip cannot be confused with ordinary idempotency.
        Membership.objects.filter(pk=self.chidi.pk).update(
            status=MembershipStatus.ACTIVE
        )
        with connected_to(self.stmarys):
            FeeScheduleLine.objects.create(
                schedule=self.schedule(),
                description="Exam fee",
                amount_kobo=LEVY,
                position=3,
            )

        # Deferred: the same change is read back mid-flight and decides the skip.
        seen, watching = self._watch_is_live(self._end_mid_flight(self.chidi))
        with connected_to(self.stmarys), watching:
            with mock.patch.object(schedules, "Membership", _StatusLeftUnloaded):
                with CaptureQueriesContext(connection) as captured:
                    deferred_run = self.apply()

            self.assertEqual(
                deferred_run.students_skipped,
                1,
                "a deferred status re-read the row and skipped an enrolled child",
            )
            self.assertEqual(deferred_run.students, 1)
            # The silence is the point: the child is simply not invoiced.
            self.assertEqual(
                self.balance_of(self.chidi),
                TUITION + LEVY,
                "the exam fee never reached the child who was dropped",
            )
            self.assertEqual(self.balance_of(self.ada), TUITION + 2 * LEVY)

        self.assertEqual(
            [deferred for _, deferred in seen],
            [frozenset({"status"}), frozenset({"status"})],
            "the control did not actually defer status",
        )
        refetches = [
            q["sql"]
            for q in captured.captured_queries
            if "accounts_membership" in q["sql"]
            and q["sql"].lstrip().upper().startswith("SELECT")
        ]
        self.assertGreater(
            len(refetches),
            1,
            "deferring status should cost one refetch per child, inside the lock",
        )
