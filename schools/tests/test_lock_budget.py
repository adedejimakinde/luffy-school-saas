"""Making a school fits in Postgres's lock table, with room to do it at once.

Postgres keeps every lock in one shared pool of `max_locks_per_transaction x
(max_connections + max_prepared_transactions)` slots, 64 x 100 = 6,400 by
default. A transaction that creates tables holds a lock on every table and
every index until it ends, and making a school is one transaction: CREATE
SCHEMA and every migration, inside the caller's `transaction.atomic()`
(`schools.onboarding.create_school`). The suite does the same for every test
that makes a school (`schools/tests/tenants.py`) and runs four workers at
once. When the pool is full the next statement to ask for a lock fails with
`out of shared memory`, in whichever test is unlucky: CI did exactly that, in
four to nine unrelated tests of one shard, never the same ones twice.

`deploy/postgres/settings.sh` holds the number every Postgres here starts with.
This file asks three things of it, and the third is the one that matters:

1. **It is applied everywhere**: production's image, the restore test's server,
   the development database and CI's all start with the file's settings, and the
   live server this suite is running on has them.
2. **It is measured, not assumed**: how many locks making a school holds is read
   from the server (`pg_locks`), by the production path (CREATE SCHEMA and
   migrate) and by the suite's path (a clone), not written down here.
3. **It leaves room**: that many locks, for as many schools as the suite makes
   at once with a quarter to spare, fits in the pool. Add tables until it does
   not and this fails, with the setting to raise, long before CI is flaky.
"""

import re
import sys
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase

from schools.tests.tenants import make_school, make_school_by_migrating

ROOT = Path(settings.BASE_DIR)
SETTINGS_FILE = ROOT / "deploy" / "postgres" / "settings.sh"

#: The suite's worst case at once. `--parallel auto` is one worker per core and a
#: GitHub runner has four; a test holds the schools it makes in `setUp` until it
#: ends, and the largest fixtures make three. A quarter more for what else shares
#: the pool (the other tests' own queries, autovacuum, a connection that is not
#: ours).
WORKERS = 4
SCHOOLS_PER_WORKER = 3
HEADROOM = 1.25

#: Postgres's default, and what neither production nor CI changes.
MAX_CONNECTIONS = 100


def configured_limit():
    """`max_locks_per_transaction` as `deploy/postgres/settings.sh` sets it."""
    found = re.search(r"^\s*max_locks_per_transaction=(\d+)\s*$", SETTINGS_FILE.read_text(), re.M)
    assert found, "deploy/postgres/settings.sh does not set max_locks_per_transaction"
    return int(found.group(1))


def read(relative):
    return (ROOT / relative).read_text()


def setting(name):
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {name}")
        return int(cursor.fetchone()[0])


def locks_held():
    """How many lock slots this connection's open transaction holds right now."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid()")
        return cursor.fetchone()[0]


def objects_in(schema):
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname = %s", [schema])
        tables = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM pg_indexes WHERE schemaname = %s", [schema])
        return tables, cursor.fetchone()[0]


class TheSettingsReachEveryPostgresTests(SimpleTestCase):
    """What is written in `settings.sh` is what each of them starts with."""

    def test_the_file_sets_a_limit_well_above_postgres_default(self):
        self.assertGreaterEqual(configured_limit(), 128)

    def test_production_starts_with_the_file(self):
        """The image carries it, and the entrypoint that starts the server passes it as arguments."""
        self.assertIn("COPY settings.sh /usr/local/lib/classnode/postgres-settings.sh", read("deploy/postgres/Dockerfile"))
        entrypoint = read("deploy/postgres/entrypoint.sh")
        self.assertIn(". /usr/local/lib/classnode/postgres-settings.sh", entrypoint)
        self.assertRegex(entrypoint, r'args=\([^)]*"\$\{CLASSNODE_PG_ARGS\[@\]\}"')

    def test_the_restore_test_starts_with_the_file_too(self):
        """Recovery refuses a server with a lower limit than the one that wrote the WAL."""
        restore = read("deploy/postgres/restore-serve.sh")
        self.assertIn(". /usr/local/lib/classnode/postgres-settings.sh", restore)
        self.assertRegex(restore, r'postgres \\\n\s+"\$\{CLASSNODE_PG_ARGS\[@\]\}"')

    def test_the_image_check_asks_the_live_server_for_each_setting(self):
        script = read("deploy/postgres/test-backup.sh")
        self.assertIn('. "$(dirname "$0")/settings.sh"', script)
        self.assertIn('SHOW ${setting%%=*}', script)

    def test_the_development_database_repeats_the_number(self):
        compose = read("docker-compose.yml")
        self.assertIn(f"max_locks_per_transaction={configured_limit()}", compose)

    def test_ci_starts_its_database_with_the_file_as_server_arguments(self):
        """Not `services:` (it cannot pass arguments to the server) and not a step that alters it after."""
        action = read(".github/actions/test-database/action.yml")
        self.assertIn(". deploy/postgres/settings.sh", action)
        self.assertRegex(action, r'postgres:15-bookworm postgres "\$\{CLASSNODE_PG_ARGS\[@\]\}"')
        self.assertIn("SHOW $name", action, "the live value is printed")
        workflow = read(".github/workflows/tests.yml")
        self.assertNotRegex(workflow, r"(?m)^\s+postgres:\n\s+(#.*\n\s+)*image: postgres", "a postgres service container is back")
        self.assertEqual(workflow.count("uses: ./.github/actions/test-database"), 2, "the suite's job and the screens job")


class CreatingASchoolFitsTheLockTableTests(TestCase):
    def report(self, how, held, tables, indexes):
        capacity = setting("max_locks_per_transaction") * (setting("max_connections") + setting("max_prepared_transactions"))
        print(
            f"\nlock budget: making a school {how} holds {held} locks ({tables} tables, {indexes} indexes); "
            f"max_locks_per_transaction = {setting('max_locks_per_transaction')}, pool of {capacity}",
            file=sys.stderr,
        )

    def test_the_database_this_suite_runs_on_has_the_limit_the_file_sets(self):
        live = setting("max_locks_per_transaction")
        self.assertGreaterEqual(
            live,
            configured_limit(),
            f"this database has max_locks_per_transaction = {live}, and deploy/postgres/settings.sh sets "
            f"{configured_limit()}: start Postgres with `-c max_locks_per_transaction={configured_limit()}` "
            "(docker-compose.yml does), or CI's tests fail with `out of shared memory` when they overlap",
        )

    def check_room(self, how, held):
        needed = int(held * WORKERS * SCHOOLS_PER_WORKER * HEADROOM)
        live_pool = setting("max_locks_per_transaction") * (setting("max_connections") + setting("max_prepared_transactions"))
        file_pool = configured_limit() * MAX_CONNECTIONS
        advice = (
            f"making a school {how} holds {held} locks; {WORKERS} workers with {SCHOOLS_PER_WORKER} schools each and a "
            f"quarter to spare need {needed}. Raise max_locks_per_transaction in deploy/postgres/settings.sh "
            f"(and docker-compose.yml), and docs/deployment.md says how it reaches production"
        )
        self.assertLessEqual(needed, file_pool, f"settings.sh gives a pool of {file_pool}: {advice}")
        self.assertLessEqual(needed, live_pool, f"this database's pool is {live_pool}: {advice}")

    def test_making_a_school_the_production_way_fits_with_room_for_the_suites_concurrency(self):
        """CREATE SCHEMA and every migration in one transaction: `School.save()`."""
        before = locks_held()
        make_school_by_migrating("Lock Budget", "lock-budget", "lock_budget")
        held = locks_held() - before
        tables, indexes = objects_in("lock_budget")
        self.report("the production way", held, tables, indexes)
        # A measurement that read nothing would pass every comparison below.
        self.assertGreaterEqual(held, tables + indexes, "a lock for every table and every index it made, at least")
        self.check_room("the production way", held)

    def test_making_a_school_the_suites_way_fits_with_the_same_room(self):
        """A clone of the template (`make_school`), which is what each test pays for."""
        before = locks_held()
        make_school("Lock Budget Clone", "lock-budget-clone", "lock_budget_clone")
        held = locks_held() - before
        tables, indexes = objects_in("lock_budget_clone")
        self.report("by clone", held, tables, indexes)
        self.assertGreaterEqual(held, tables + indexes)
        self.check_room("by clone", held)
