"""Two copies of one queued write in flight at the same instant.

A phone that retries while its first attempt is still on the wire sends the
same key twice, and both copies can be inside the server at once. Neither can
see the other's receipt by reading: the first has not committed. **The unique
index is what makes the second one wait**, and then find the first's receipt
when it commits. That is the claim D3 rests on, and only real concurrency tests
it; `test_replay` sends its copies one after the other.

`TransactionTestCase` and real threads, for the reason
`fees/tests/test_schedule_concurrency.py` gives. The winner does not guess at
timing: it holds its transaction open until Postgres reports the loser blocked
by it, so both copies are provably in flight together.

Two schools, one key, all four copies at once. Each thread sets its own
`search_path`; a thread on the wrong one would find the other school's receipt,
and a single school cannot tell that from working.
"""

import threading
import time
import uuid

from django.db import connection, connections
from django.test import TransactionTestCase
from ninja import Schema

from accounts.models import User
from schools.models import School
from schools.tests.tenants import connected_to
from sync import receipts
from sync.models import SyncReceipt

PASSWORD = "correct-horse-battery"


class _Answer(Schema):
    school: str


def _somebody_is_waiting_on_me(timeout=5.0):
    """Poll until another backend is blocked by this one. True if it happened.

    Asked of this backend and not of the database: once one school's winner
    commits, its loser stops waiting, so a count of every waiter would drop
    before the other school's winner had looked.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
            if cursor.fetchone()[0]:
                return True
        time.sleep(0.05)
    return False


class TwoCopiesAtOnceTests(TransactionTestCase):
    def setUp(self):
        self.stmarys = School(name="St Mary's", slug="st-marys", schema_name="st_marys")
        self.stmarys.save()
        self.grace = School(name="Grace Academy", slug="grace", schema_name="grace")
        self.grace.save()
        self.teacher = User.objects.create_user("kemi", PASSWORD, full_name="Kemi Bello")

    def tearDown(self):
        connection.set_schema_to_public()
        # The note in `fees/tests/test_schedule_concurrency.py`: a flush clears
        # the `School` rows and leaves the schemas.
        with connection.cursor() as cursor:
            for school in (self.stmarys, self.grace):
                cursor.execute(f'DROP SCHEMA IF EXISTS "{school.schema_name}" CASCADE')
        super().tearDown()

    def test_each_school_acts_once_and_every_copy_gets_its_answer(self):
        key = uuid.uuid4()
        copies = [self.stmarys, self.stmarys, self.grace, self.grace]
        ready = threading.Barrier(len(copies), timeout=15)
        acted = []
        overlapped = []
        answers = []
        unexpected = []
        lock = threading.Lock()

        def run(school):
            def act():
                with lock:
                    acted.append(school.schema_name)
                # Hold this transaction open until this school's loser is
                # queued behind the index.
                overlapped.append(_somebody_is_waiting_on_me())
                return 200, _Answer(school=school.schema_name)

            try:
                with connected_to(school):
                    # Connected, and on this school's schema, before the start.
                    # Opening a connection is the slow part of a first query,
                    # and a copy still connecting when its rival commits never
                    # races at all.
                    SyncReceipt.objects.exists()
                    ready.wait()
                    status, answer = receipts.once(
                        key=key,
                        actor=self.teacher,
                        write="PUT /api/gradebook/assessments/1/scores/1/",
                        request={"value": 17, "expected_version": None},
                        act=act,
                    )
                    if not isinstance(answer, dict):
                        answer = answer.model_dump(mode="json")
                    with lock:
                        answers.append((school.schema_name, status, answer))
            except Exception as exc:  # noqa: BLE001 — reported, not swallowed
                unexpected.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=(school,)) for school in copies]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(unexpected, [])
        # The copies really were in flight together: each winner saw its
        # loser queued behind the index before it committed.
        self.assertEqual(overlapped, [True, True])
        self.assertEqual(sorted(acted), ["grace", "st_marys"])
        # Each school's winner has its own answer; each loser is told it is
        # already saved, and nothing about what the winner wrote (#161).
        self.assertEqual(
            sorted((s, st, a.get("school", a.get("detail"))) for s, st, a in answers),
            [
                ("grace", 200, "Already saved."),
                ("grace", 200, "grace"),
                ("st_marys", 200, "Already saved."),
                ("st_marys", 200, "st_marys"),
            ],
        )
        for school in (self.stmarys, self.grace):
            with connected_to(school):
                self.assertEqual(SyncReceipt.objects.count(), 1)
