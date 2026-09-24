"""The weekly restore test's verdict: is a restored database a whole Classnode?

Run here against the test database itself — a database this suite has just
built and migrated — and then against the same database with one thing taken
away, which is what a partial restore looks like from inside. The removals
are DDL and DML inside the test's transaction, so they roll back.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase

from schools.restore_check import check
from schools.tests.tenants import make_school as make_real_school


class RestoreCheckTests(TestCase):
    def setUp(self):
        self.stmarys = make_real_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_real_school("Grace Academy", "grace", "grace")

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def test_a_whole_database_passes(self):
        """The control: every failure below would pass against a check that
        failed everything."""
        verdict = check()

        self.assertEqual(verdict.problems, [])
        self.assertEqual(verdict.schools, 2)

    def test_a_school_whose_schema_did_not_come_back_fails_and_is_named(self):
        """The partial restore that matters most: the `School` row is back and
        its schema is not, so every page of that school is an error.

        CONTROL 8: the check skipping the schema-presence question makes this
        red.
        """
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA "grace" CASCADE')

        verdict = check()

        self.assertFalse(verdict.ok)
        self.assertIn("Grace Academy (grace) has no schema", verdict.problems)
        self.assertFalse(any("St Mary" in p for p in verdict.problems), verdict.problems)

    def test_a_school_behind_on_migrations_fails_and_names_the_migration(self):
        graph = MigrationLoader(None, ignore_no_migrations=True).graph
        app, name = next((a, n) for a, n in graph.leaf_nodes() if a == "results")
        with connection.cursor() as cursor:
            cursor.execute(
                'DELETE FROM "st_marys".django_migrations WHERE app = %s AND name = %s', [app, name]
            )

        verdict = check()

        self.assertIn(f"St Mary's (st_marys) is missing migration {app}.{name}", verdict.problems)

    def test_public_behind_on_migrations_fails(self):
        graph = MigrationLoader(None, ignore_no_migrations=True).graph
        app, name = next((a, n) for a, n in graph.leaf_nodes() if a == "accounts")
        with connection.cursor() as cursor:
            cursor.execute(
                'DELETE FROM "public".django_migrations WHERE app = %s AND name = %s', [app, name]
            )

        self.assertIn(f"public is missing migration {app}.{name}", check().problems)

    def test_the_command_says_whole_or_exits_non_zero_naming_why(self):
        out = StringIO()
        call_command("verify_restore", stdout=out)
        self.assertIn("The restore is whole: 2 schools", out.getvalue())

        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA "grace" CASCADE')
        with self.assertRaisesMessage(CommandError, "Grace Academy (grace) has no schema"):
            call_command("verify_restore", stdout=StringIO())
