"""Two bursars clicking "Charge JSS 1A" at the same instant.

`apply_to_class()` is read-modify-write across a whole class: read who is on the
roster, read who has already been charged, decide what is missing, write it.
Both runs read the same "already charged" set, both find the same children
missing, and both post.

**Two defences, doing two different jobs**, and the distinction is measured
rather than asserted. Removing `select_for_update()` from `apply_to_class()` and
re-running `test_two_simultaneous_applications_charge_each_child_once` gives:

    IntegrityError: duplicate key value violates unique constraint
    "a_schedule_line_charges_a_child_once"
    DETAIL: Key (student_membership_id, source_line_id)=(1, 1) already exists.

So the *index* is what stops the double charge — even unlocked, no family is
billed twice. The *lock* is what turns the loser's outcome from an unhandled
`IntegrityError` on a bursar's screen into an ordinary "4 skipped" summary. A
docstring claiming the lock prevents double-billing would have been easy to
write and wrong, which is why this module asserts both halves: **four entries,
and both threads returning a summary.**

`TransactionTestCase` and real threads, for the reason
`results/tests/test_approval_concurrency.py` sets out: two connections whose
commits are visible to each other, released together by a barrier rather than
interleaved with sleeps, so both applications are provably in flight.

**Two schools, both real schemas.** The race needs only one, and one is not
enough to catch the other bug in reach here: each thread resolves its school
from the connection it is on, so a thread whose `search_path` is wrong would
bill one school's children into another school's books, and no single-tenant
test can tell that from working correctly.
"""

import threading
from datetime import date

from django.db import connection, connections
from django.test import TransactionTestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import User
from accounts.services import enroll_student
from fees import schedules
from fees.models import FeeLedgerEntry, FeeSchedule, FeeScheduleLine, KOBO_PER_NAIRA
from schools.models import School
from schools.tests.tenants import connected_to

PASSWORD = "correct-horse-battery"

TUITION = 120_000 * KOBO_PER_NAIRA
LEVY = 15_000 * KOBO_PER_NAIRA


class TwoSchoolsBillingSetUp(TransactionTestCase):
    """St Mary's and Grace Academy, each with a two-line bill for a JSS 1A."""

    def setUp(self):
        self.stmarys = self._school("St Mary's", "st-marys", "st_marys")
        self.grace = self._school("Grace Academy", "grace", "grace")

        self.bursar = User.objects.create_user(
            "bursar", PASSWORD, full_name="Bola Bursar"
        )
        # Two, because the interesting race is two *different* people running
        # the same bill; the entries name whichever of them got there first.
        self.other_bursar = User.objects.create_user(
            "bursar2", PASSWORD, full_name="Femi Bursar"
        )

        self.ada = self._student("ada", "Ada Obi", self.stmarys)
        self.chidi = self._student("chidi", "Chidi Okafor", self.stmarys)
        self.ngozi = self._student("ngozi", "Ngozi Eze", self.grace)

        self.schedule_id = self._bill(self.stmarys, [self.ada, self.chidi])
        self.their_schedule_id = self._bill(self.grace, [self.ngozi])

    def _school(self, name, slug, schema_name):
        school = School(name=name, slug=slug, schema_name=schema_name)
        school.save()
        return school

    def _student(self, username, full_name, school):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        return enroll_student(user, school)

    def _bill(self, school, memberships):
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
                schedule=schedule, description="Tuition", amount_kobo=TUITION, position=1
            )
            FeeScheduleLine.objects.create(
                schedule=schedule, description="PTA levy", amount_kobo=LEVY, position=2
            )
            return schedule.pk

    def tearDown(self):
        connection.set_schema_to_public()
        # Drop the schemas, not just the rows: `TransactionTestCase` flushes the
        # public tables between tests, so the `School` rows go — but a schema is
        # not a table and would survive to be inherited by the next test, which
        # surfaces as a duplicate Term in `setUp`. The note in
        # `results/tests/test_approval_concurrency.py` records this in full.
        with connection.cursor() as cursor:
            for school in (self.stmarys, self.grace):
                cursor.execute(f'DROP SCHEMA IF EXISTS "{school.schema_name}" CASCADE')
        super().tearDown()

    def _apply_together(self, runs):
        """Run each (school, schedule_id, actor) at once, released by a barrier."""
        ready = threading.Barrier(len(runs), timeout=15)
        summaries = []
        unexpected = []

        def run(school, schedule_id, actor):
            try:
                with connected_to(school):
                    schedule = FeeSchedule.objects.get(pk=schedule_id)
                    ready.wait()
                    summaries.append(
                        schedules.apply_to_class(schedule, by=actor)
                    )
            except Exception as exc:  # noqa: BLE001 — reported, not swallowed
                unexpected.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=args) for args in runs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        return summaries, unexpected


class ConcurrentApplicationTests(TwoSchoolsBillingSetUp):
    def test_two_simultaneous_applications_charge_each_child_once(self):
        """Test 10 of the design, and the reason the lock is on the schedule row."""
        summaries, unexpected = self._apply_together(
            [
                (self.stmarys, self.schedule_id, self.bursar),
                (self.stmarys, self.schedule_id, self.other_bursar),
            ]
        )

        self.assertEqual(unexpected, [], f"a thread failed: {unexpected}")

        with connected_to(self.stmarys):
            entries = FeeLedgerEntry.objects.all()
            # Two children, two lines. Not four *and a bit*, and not eight.
            self.assertEqual(entries.count(), 4)
            self.assertEqual(
                FeeLedgerEntry.objects.for_student(self.ada.pk).balance(),
                TUITION + LEVY,
            )
            self.assertEqual(
                FeeLedgerEntry.objects.for_student(self.chidi.pk).balance(),
                TUITION + LEVY,
            )

        # Both threads returned a summary rather than one dying: that is the
        # lock's job, and it is a different claim from the count above.
        self.assertEqual(len(summaries), 2)
        self.assertEqual(sorted(s.charges_posted for s in summaries), [0, 4])
        self.assertEqual(sorted(s.charges_skipped for s in summaries), [0, 4])

    def test_four_at_once_still_charges_each_child_once(self):
        """Two threads can pass by luck. Four is harder to be lucky with."""
        extra = [
            User.objects.create_user(f"bursar-{n}", PASSWORD, full_name=f"Bursar {n}")
            for n in range(2)
        ]
        summaries, unexpected = self._apply_together(
            [
                (self.stmarys, self.schedule_id, actor)
                for actor in [self.bursar, self.other_bursar, *extra]
            ]
        )

        self.assertEqual(unexpected, [], f"a thread failed: {unexpected}")
        with connected_to(self.stmarys):
            self.assertEqual(FeeLedgerEntry.objects.count(), 4)
        self.assertEqual(sorted(s.charges_posted for s in summaries), [0, 0, 0, 4])

    def test_each_thread_bills_the_school_its_connection_is_on(self):
        """Two schools billed at once; neither one's entries land in the other.

        A thread whose `search_path` were wrong would post St Mary's charges
        into Grace Academy's tables and every assertion about counts within one
        school would still pass. This is the one that would not.
        """
        summaries, unexpected = self._apply_together(
            [
                (self.stmarys, self.schedule_id, self.bursar),
                (self.grace, self.their_schedule_id, self.other_bursar),
            ]
        )

        self.assertEqual(unexpected, [], f"a thread failed: {unexpected}")
        self.assertEqual(sorted(s.charges_posted for s in summaries), [2, 4])

        with connected_to(self.stmarys):
            ours = set(
                FeeLedgerEntry.objects.values_list("student_membership_id", flat=True)
            )
            self.assertEqual(ours, {self.ada.pk, self.chidi.pk})

        with connected_to(self.grace):
            theirs = set(
                FeeLedgerEntry.objects.values_list("student_membership_id", flat=True)
            )
            self.assertEqual(theirs, {self.ngozi.pk})
