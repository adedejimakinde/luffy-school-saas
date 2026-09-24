"""Two first grants of one membership at the same moment, at two schools.

`grant_membership()` locks the `(user, school, role)` row before deciding
anything, and that is enough whenever the row exists. On a first grant it does
not: `SELECT ... FOR UPDATE` finds nothing to lock, both callers insert, and the
second insert waits on the first's transaction and is refused by
`uniq_membership_user_school_role` once that commits. Issue #94 measured it
through `link_guardian()`: one caller got its link, the other a raw
`IntegrityError`, on the first link at a school — the ordinary case for a new
parent.

**The interleaving is arranged, not hoped for.** #94 recorded why a barrier is
not enough here: it makes both callers *start* together, and if one happens to
commit before the other's `SELECT`, they serialise and the test passes while
proving nothing. So the first caller inserts inside a transaction and holds it
open, and the second is not released into the assertion until
`pg_stat_activity` shows its backend waiting on a lock *in its INSERT into
`accounts_membership`*. Only then does the first commit. Every run takes the
collision path, and a run that never reaches it fails as "not arranged" rather
than passing.

**Two schools, raced at once.** The table is shared, so both races stand in one
`public` index, and each loser has to come back with its own school's row and
not merely *a* row for that user and role. Both are held open together, which
also shows that a first grant at one school does not wait on an uncommitted one
at the other.

`TransactionTestCase` and real threads, because this needs two connections whose
commits are visible to each other — the idiom `test_transfer_concurrency.py`
established.
"""

import threading
import time

from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from accounts import services
from accounts.models import Guardianship, Membership, MembershipStatus, Role, User
from schools.models import School
from tests.refusals import RefusalAssertions

PASSWORD = "correct-horse-battery"


def make_school(name, slug, schema_name):
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.auto_create_schema = False
    school.save()
    return school


def make_user(username, full_name, **extra):
    return User.objects.create_user(username, PASSWORD, full_name=full_name, **extra)


def backend_pid():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


def is_waiting_in_the_membership_insert(pid):
    """Is backend `pid` blocked on a lock, in an INSERT into `accounts_membership`?

    The query text is part of the test, not decoration: a caller blocked on a
    row lock in its `SELECT ... FOR UPDATE` is also "waiting on a lock", and
    that is the serialised path, not the collision.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_stat_activity"
            " WHERE pid = %s AND wait_event_type = 'Lock'"
            " AND query LIKE 'INSERT INTO \"accounts_membership\"%%'",
            [pid],
        )
        return cursor.fetchone() is not None


class Race:
    """A first call that inserts and holds, and a second that must collide with it.

    `first` runs inside a transaction that stays open until `release` is set.
    `second` runs once `first` has returned, and so once its row is written and
    not yet visible to anybody else.
    """

    def __init__(self, first, second):
        self.first = first
        self.second = second
        self.inserted = threading.Event()
        self.second_started = threading.Event()
        self.release = threading.Event()
        self.second_pid = None
        self.outcome = {}

    def run_first(self):
        try:
            with transaction.atomic():
                self.outcome["first"] = ("ok", self.first())
                self.inserted.set()
                if not self.release.wait(15):
                    raise TimeoutError("the first call was never released")
        except Exception as exc:  # noqa: BLE001 — the outcome is the assertion
            self.outcome["first"] = (type(exc).__name__, str(exc)[:160])
        finally:
            self.inserted.set()
            connections.close_all()

    def run_second(self):
        try:
            self.inserted.wait(15)
            self.second_pid = backend_pid()
            self.second_started.set()
            self.outcome["second"] = ("ok", self.second())
        except Exception as exc:  # noqa: BLE001 — the outcome is the assertion
            self.outcome["second"] = (type(exc).__name__, str(exc)[:160])
        finally:
            self.second_started.set()
            connections.close_all()


class RaceHarness:
    def run_races(self, *races):
        threads = []
        for race in races:
            threads.append(threading.Thread(target=race.run_first))
            threads.append(threading.Thread(target=race.run_second))
        for thread in threads:
            thread.start()
        try:
            for race in races:
                self.assertTrue(race.second_started.wait(15), race.outcome)
                self.assertIsNotNone(race.second_pid, race.outcome)
                self.wait_until_blocked_in_the_insert(race)
        finally:
            for race in races:
                race.release.set()
            for thread in threads:
                thread.join(20)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "a racing thread never finished")

    def wait_until_blocked_in_the_insert(self, race):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if is_waiting_in_the_membership_insert(race.second_pid):
                return
            if "second" in race.outcome:
                break
            time.sleep(0.01)
        self.fail(
            "the race was not arranged: the second grant never waited in its "
            f"INSERT on the first's uncommitted row. Outcome so far: {race.outcome}"
        )


class TwoFirstGrantsAtOnceTests(RaceHarness, TransactionTestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.parent = make_user("08031234567", "Bisi Ade", phone="08031234567")

    def a_race_at(self, school):
        """The winner grants ACTIVE; the loser asks for INVITED, inside a
        transaction that goes on to read afterwards.

        Two different statuses so the row says whose it is: a sequential second
        call returns a live row untouched, and the loser of a race must do the
        same rather than overwrite the winner's grant with its own. And the
        loser runs inside an enclosing transaction, as it does under
        `link_guardian()` and `bulk.admit()`, so that a refusal which poisoned
        that transaction would show up as the read after it failing.
        """

        def first():
            return services.grant_membership(self.parent, school, Role.PARENT).pk

        def second():
            with transaction.atomic():
                row = services.grant_membership(
                    self.parent, school, Role.PARENT, status=MembershipStatus.INVITED
                )
                still_usable = Membership.objects.filter(user=self.parent).count()
            return row.pk, still_usable

        return Race(first, second)

    def test_each_loser_takes_its_own_schools_row_instead_of_raising(self):
        at_stmarys = self.a_race_at(self.stmarys)
        at_grace = self.a_race_at(self.grace)

        self.run_races(at_stmarys, at_grace)

        for race in (at_stmarys, at_grace):
            self.assertEqual(race.outcome["first"][0], "ok", race.outcome)
            self.assertEqual(race.outcome["second"][0], "ok", race.outcome)

        for race, school in ((at_stmarys, self.stmarys), (at_grace, self.grace)):
            winner_pk = race.outcome["first"][1]
            loser_pk, _ = race.outcome["second"][1]
            self.assertEqual(loser_pk, winner_pk)

            row = Membership.objects.get(pk=winner_pk)
            self.assertEqual(row.school_id, school.pk)
            self.assertEqual(row.role, Role.PARENT)
            # The winner's grant, untouched by the loser's request for INVITED.
            self.assertEqual(row.status, MembershipStatus.ACTIVE)

        self.assertEqual(
            sorted(
                Membership.objects.filter(
                    user=self.parent, role=Role.PARENT
                ).values_list("school_id", flat=True)
            ),
            sorted([self.stmarys.pk, self.grace.pk]),
        )


class TheFirstLinkAtASchoolTests(RaceHarness, TransactionTestCase):
    """#94's own reproduction, through the service a school actually calls."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.parent = make_user("08031234567", "Bisi Ade", phone="08031234567")
        self.child = services.enroll_student(make_user("STM/1", "Ada Ade"), self.stmarys)

        # The parent already holds PARENT at Grace through a sibling, so St
        # Mary's is a first link at a school and not a first link anywhere —
        # the ordinary shape of a parent whose second child starts somewhere new.
        self.sibling = services.enroll_student(make_user("GA/1", "Tunde Ade"), self.grace)
        self.grace_link = services.link_guardian(self.parent, self.sibling)
        self.grace_membership = Membership.objects.get(
            user=self.parent, school=self.grace, role=Role.PARENT
        )

    def test_two_first_links_at_a_school_both_succeed_with_one_link(self):
        race = Race(
            lambda: services.link_guardian(self.parent, self.child).pk,
            lambda: services.link_guardian(self.parent, self.child).pk,
        )

        self.run_races(race)

        self.assertEqual(race.outcome["first"][0], "ok", race.outcome)
        self.assertEqual(race.outcome["second"][0], "ok", race.outcome)
        self.assertEqual(race.outcome["first"][1], race.outcome["second"][1])

        self.assertEqual(
            Guardianship.objects.filter(guardian=self.parent, student=self.child).count(),
            1,
        )
        self.assertEqual(
            Membership.objects.filter(
                user=self.parent, school=self.stmarys, role=Role.PARENT
            ).count(),
            1,
        )
        # The other school's membership and link are the same rows as before.
        self.assertEqual(
            list(
                Membership.objects.filter(
                    user=self.parent, school=self.grace, role=Role.PARENT
                ).values_list("pk", flat=True)
            ),
            [self.grace_membership.pk],
        )
        self.assertTrue(Guardianship.objects.filter(pk=self.grace_link.pk).exists())


class OnlyTheCollisionIsRetriedTests(RefusalAssertions, TransactionTestCase):
    """The retry is for one constraint, and every other refusal is raised as it was."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.child = make_user("STM/1", "Ada Ade")
        services.enroll_student(self.child, self.stmarys)

    def test_a_second_live_school_is_refused_once_and_not_retried(self):
        """`one_live_student_membership_per_user` is a refusal, not a race.

        Called directly rather than through `enroll_student()`, whose own check
        would refuse first with `AlreadyEnrolled` and never reach the insert.
        Counted as well as named: a retry of this refusal fails the same way a
        second time, so the name alone would pass against a catch that retried
        every `IntegrityError`.
        """
        with CaptureQueriesContext(connection) as queries:
            with self.assertRefusedBy("one_live_student_membership_per_user"):
                services.grant_membership(self.child, self.grace, Role.STUDENT)

        inserts = [
            q["sql"]
            for q in queries.captured_queries
            if q["sql"].startswith('INSERT INTO "accounts_membership"')
        ]
        self.assertEqual(len(inserts), 1, inserts)
        self.assertFalse(
            Membership.objects.filter(user=self.child, school=self.grace).exists()
        )

    def test_the_collision_is_recognised_by_its_constraint(self):
        """The retry's premise: the loser's refusal names this constraint.

        Arranged without threads — a plain duplicate insert is refused by the
        same index the concurrent loser meets, which is what lets the retry key
        off the constraint's name rather than off whether a row is there now.
        """
        existing = Membership.objects.get(user=self.child, school=self.stmarys)
        with self.assertRefusedBy("uniq_membership_user_school_role") as caught:
            with transaction.atomic():
                Membership.objects.create(
                    user=self.child,
                    school=self.stmarys,
                    role=Role.STUDENT,
                    status=MembershipStatus.ENDED,
                )
        self.assertTrue(services._is_the_membership_colliding(caught.exception))
        self.assertTrue(Membership.objects.filter(pk=existing.pk).exists())
