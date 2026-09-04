"""Consecutive runs must not race on dropping the leftover test database.

Issue #61. The previous run's process has returned, but its Postgres backend
has not gone away yet; `DROP DATABASE` requires zero other sessions, so the next
run's teardown loses a race and Django exits 2 four lines from the end of a long
log. `schools/tests/runner.py` now terminates those backends first.

**The control is the first test.** It holds a connection open and asserts the
drop genuinely fails — if that ever stops failing, the race has gone away by
some other route and the fix below is guarding nothing. A test for a fix whose
bug cannot be reproduced on demand is decoration, and this file exists because
the bug *can* be, against a scratch database rather than by waiting for the
timing to go wrong on its own.

**The second control is the decoy.** `_` is a single-character wildcard to
`LIKE`, and every database name here is full of them, so an unescaped clone
pattern would reach far past the clones it names. Two decoys carry that: one for
the pattern's trailing separator, one for the underscores inside the name
itself. The second was added after a control showed the first could not tell
the difference on its own.

Nothing here touches the suite's own database: three scratch databases are
created and dropped, and the helper is called with their names.
"""

import unittest

from django.conf import settings
from django.test import SimpleTestCase

from schools.tests.runner import terminate_backends_on

try:
    import psycopg2
    from psycopg2 import errors as pg_errors
except ImportError:  # pragma: no cover - psycopg2 is a hard dependency here
    psycopg2 = None

PROBE = "luffy_probe_61"
CLONE = f"{PROBE}_1"
# Two decoys, because there are two places an underscore can stop being literal.
# SUFFIX_DECOY is matched by `..._%` and not by `...\_%`: it guards the separator
# the clone pattern ends with. NAME_DECOY has letters exactly where PROBE has
# underscores, so it is matched only if the *name's* own underscores were left
# unescaped and became single-character wildcards. The first version of this
# file had only the former, and a control with the name escaping removed still
# passed — the suffix was carrying the test on its own.
SUFFIX_DECOY = f"{PROBE}x"
NAME_DECOY = "luffyXprobeX61_1"
DECOYS = (SUFFIX_DECOY, NAME_DECOY)


def admin_connection():
    """An autocommit connection, because CREATE/DROP DATABASE cannot be in one."""
    config = settings.DATABASES["default"]
    connection = psycopg2.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"],
    )
    connection.autocommit = True
    return connection


def connection_to(name):
    config = settings.DATABASES["default"]
    return psycopg2.connect(
        dbname=name,
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"],
    )


@unittest.skipIf(psycopg2 is None, "psycopg2 is not importable")
class TerminatingBeforeTheDropTests(SimpleTestCase):
    """The race, and the helper that ends it."""

    def setUp(self):
        self.admin = admin_connection()
        self.addCleanup(self.admin.close)
        self.holders = []
        self.addCleanup(self.release_holders)
        self.addCleanup(self.drop_scratch_databases)

        self.drop_scratch_databases()
        with self.admin.cursor() as cursor:
            for name in (PROBE, CLONE, *DECOYS):
                cursor.execute(f'CREATE DATABASE "{name}"')

    def release_holders(self):
        for holder in self.holders:
            try:
                holder.close()
            except Exception:
                pass
        self.holders = []

    def drop_scratch_databases(self):
        """Terminate then drop, which is the very thing under test — but here it
        is only cleanup, and a leaked scratch database would break the next run
        of this file."""
        with self.admin.cursor() as cursor:
            for name in (PROBE, CLONE, *DECOYS):
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    [name],
                )
                cursor.execute(f'DROP DATABASE IF EXISTS "{name}"')

    def hold(self, name):
        """Open and keep a connection, standing in for the last run's backend."""
        holder = connection_to(name)
        self.holders.append(holder)
        return holder

    def drop(self, name):
        with self.admin.cursor() as cursor:
            cursor.execute(f'DROP DATABASE "{name}"')

    def test_a_held_database_really_cannot_be_dropped(self):
        """The control. Without this the rest proves nothing about a real race."""
        self.hold(PROBE)

        with self.assertRaises(pg_errors.ObjectInUse) as raised:
            self.drop(PROBE)

        self.assertIn("is being accessed by other users", str(raised.exception))

    def test_terminating_first_lets_the_drop_through(self):
        self.hold(PROBE)

        with self.admin.cursor() as cursor:
            cleared = terminate_backends_on(cursor, PROBE)

        self.assertIn(PROBE, cleared)
        self.drop(PROBE)  # would raise ObjectInUse without the line above

    def test_a_worker_clone_is_terminated_too(self):
        """`--parallel` leaves `test_luffy_db_1 … _N` behind as well as the original."""
        self.hold(CLONE)

        with self.admin.cursor() as cursor:
            cleared = terminate_backends_on(cursor, PROBE)

        self.assertIn(CLONE, cleared)
        self.drop(CLONE)

    def test_names_only_an_unescaped_underscore_would_match_are_left_alone(self):
        """The escaping control, in both places an underscore can leak.

        `luffy_probe_61x` is matched by `luffy_probe_61_%` and not by
        `luffy_probe_61\\_%` — it guards the separator the pattern ends with.
        `luffyXprobeX61_1` has letters where PROBE has underscores, so it is
        matched only if the name's own underscores became wildcards.

        Both are needed. With only the first, removing the escaping from the
        name still left every test passing, because the escaped suffix was
        enough to keep `...x` out on its own.
        """
        holders = {name: self.hold(name) for name in DECOYS}

        with self.admin.cursor() as cursor:
            cleared = terminate_backends_on(cursor, PROBE)

        for name, holder in holders.items():
            with self.subTest(decoy=name):
                self.assertNotIn(name, cleared)
                with holder.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    self.assertEqual(cursor.fetchone()[0], 1)

    def test_nothing_to_terminate_is_not_an_error(self):
        """The ordinary case: no previous run, nothing held, no complaint."""
        with self.admin.cursor() as cursor:
            self.assertEqual(terminate_backends_on(cursor, PROBE), [])
