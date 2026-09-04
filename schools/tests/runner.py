"""The test runner that builds the tenant template, once per test database.

`settings.TEST_RUNNER` points here. The only thing this adds to Django's
`DiscoverRunner` is *when* the template is built, and that timing is the whole
reason it is a runner rather than a fixture — see `schools/tests/tenants.py`
for what the template is and what it costs.

## The ordering, and why it needs an override at all

`django.test.utils.setup_databases()` does two things in one call:

    connection.creation.create_test_db(...)          # the test database
    if parallel > 1:
        for index in range(parallel):
            connection.creation.clone_test_db(...)   # one per worker

The template has to be built **between** them. Every worker gets its own
database, made with `CREATE DATABASE ... TEMPLATE ...` from the one above, so a
template schema that exists before that line is inherited by all N workers for
the ~0.11s the copy already costs. Built after, each worker would have to
migrate its own — N × 1.65s, and N is the core count.

Django offers no hook between those two statements, so this asks for the test
database with `parallel` temporarily set to 0, builds the template into it, and
then makes the worker clones itself. `clone_test_db(suffix=str(i + 1))` is the
same call with the same arguments Django would have made, and produces the same
`..._1 … _N` names its workers connect to.

Teardown is untouched: `DiscoverRunner.teardown_databases()` reads `self.parallel`
at the time it runs, which is back to its real value, so it destroys the worker
databases it would have destroyed anyway.

## Dropping a test database the last run has not finished letting go of

`setup_databases()` also clears stale Postgres backends first — issue #61.

A run that starts shortly after one finishes can find `test_luffy_db` still
there and still occupied: the previous process has returned, but its backend
has not gone away yet, and `DROP DATABASE` requires zero other sessions. Django
fails correctly on this — `_create_test_db` logs "Got an error recreating the
test database" and calls `sys.exit(2)` — so nothing is silently wrong. It is
the startup that is lost, twice so far, to a message four lines from the end of
a long log that reads like a configuration problem.

The window is short, which is why this is intermittent and why it looks like
something else every time. Terminating first closes it.

**What it will not touch.** The names are computed, never pattern-matched
loosely: the test database Django is about to ask for, and its `_1 … _N` worker
clones. `luffy_db` — the real one, the only database here with data anyone
wants — cannot match either, because every candidate name begins with Django's
`test_` prefix. The `_` and `%` in the name are escaped before they reach
`LIKE`, so they stay literal rather than becoming wildcards that could widen
the match.

**And it says so.** Killing connections quietly would be the same class of
fault this harness exists to refuse, so a terminated backend is reported at
verbosity 1 and above. Nothing to terminate prints nothing, which is the
ordinary case.

**`--keepdb` skips it.** That flag means the database is reused rather than
dropped, so there is no drop to lose and no reason to disconnect anybody.
"""

from django.db import connections
from django.test.runner import DiscoverRunner

from schools.tests.tenants import build_template


def terminate_backends_on(cursor, database_name):
    """Disconnect every session on `database_name` and its worker clones.

    Returns the list of database names a backend was actually killed on, so the
    caller can report it. Ours is excluded by `pg_backend_pid()`: this runs on a
    connection to the *real* database, which is not a candidate anyway.

    `_` and `%` are wildcards to `LIKE`, and `luffy_db` is full of the former,
    so the name is escaped before the clone pattern is built from it. Without
    that, `test_luffy_db\_%` would be a pattern matching far more than the
    clones it is meant to name.
    """
    escaped = (
        database_name.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")
    )
    cursor.execute(
        """
        SELECT datname, pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
          AND (datname = %s OR datname LIKE %s)
        """,
        [database_name, escaped + "\\_%"],
    )
    return [row[0] for row in cursor.fetchall()]


class TenantTemplateRunner(DiscoverRunner):
    def clear_stale_backends(self):
        """Issue #61: let go of a test database the last run is still holding.

        Runs on a connection to the real database, before Django asks for the
        test one, because the connection that does the terminating must not be
        among the connections being terminated.
        """
        for alias in connections:
            connection = connections[alias]
            test_name = connection.creation._get_test_db_name()
            with connection.cursor() as cursor:
                cleared = terminate_backends_on(cursor, test_name)
            connection.close()

            if cleared and self.verbosity >= 1:
                for name in sorted(set(cleared)):
                    print(
                        f"Terminated a leftover backend still attached to "
                        f"'{name}' (issue #61)."
                    )

    def setup_databases(self, **kwargs):
        # Before anything else: the drop that is about to happen needs to be
        # the only session on that database. `--keepdb` drops nothing, so it
        # has nothing to lose and nobody to disconnect.
        if not self.keepdb:
            self.clear_stale_backends()

        requested_parallel = self.parallel

        # Ask for the test database without the worker clones, so that the
        # template lands in what those clones are about to be copied from.
        self.parallel = 0
        try:
            old_config = super().setup_databases(**kwargs)
        finally:
            self.parallel = requested_parallel

        # `destroy` is True for exactly the first alias of each distinct test
        # database, which is the same set Django clones for.
        for connection, _old_name, destroy in old_config:
            if not destroy:
                continue
            build_template(using=connection.alias, verbosity=self.verbosity)
            if self.parallel > 1:
                for index in range(self.parallel):
                    connection.creation.clone_test_db(
                        suffix=str(index + 1),
                        verbosity=self.verbosity,
                        keepdb=self.keepdb,
                    )

        return old_config
