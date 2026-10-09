"""The weekly restore test's verdict: is a restored database a whole Classnode?

Run here against the test database itself — a database this suite has just
built and migrated — and then against the same database with one thing taken
away, which is what a partial restore looks like from inside. The removals
are DDL and DML inside the test's transaction, so they roll back.
"""

import json
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase
from django_tenants.utils import tenant_context

from academics.models import ClassGroup
from schools.restore_check import check, pick_school, school_counts, tolerance
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


class RowCountsTests(TestCase):
    """The weekly restore also counts one school's rows and compares them with
    what the live database held. Two schools, so a count can be the wrong
    school's, and rows in only one of them."""

    def setUp(self):
        self.stmarys = make_real_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_real_school("Grace Academy", "grace", "grace")
        with tenant_context(self.stmarys):
            for number in range(1, 4):
                ClassGroup.objects.create(name=f"JSS {number}", level=number)
        with tenant_context(self.grace):
            ClassGroup.objects.create(name="Primary 1", level=1)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def live_counts(self, slug):
        return {"school": slug, "counts": school_counts(pick_school(slug).schema_name)}

    def test_it_counts_the_school_it_was_asked_for_and_no_other(self):
        verdict = check(slug="st-marys")

        self.assertEqual(verdict.counted, "st-marys")
        self.assertEqual(verdict.counts["academics_classgroup"], 3)
        self.assertEqual(check(slug="grace").counts["academics_classgroup"], 1)

    def test_with_no_school_named_it_counts_the_first_by_slug(self):
        self.assertEqual(check().counted, "grace")

    def test_a_school_that_is_not_there_is_a_problem_not_a_pass(self):
        verdict = check(slug="nowhere")

        self.assertIn("there is no school 'nowhere' to count", verdict.problems)

    def test_the_rows_that_were_live_are_there_after_the_restore(self):
        """The control: every failure below would pass against a check that
        failed everything."""
        verdict = check(slug="st-marys", expected=self.live_counts("st-marys")["counts"])

        self.assertEqual(verdict.problems, [])

    def test_a_table_that_came_back_short_is_named_with_both_numbers(self):
        """The restore that started Postgres and lost the data.

        CONTROL 15: `_compare` not comparing makes this red.
        """
        expected = {"academics_classgroup": 3 + tolerance(3) + 1}

        verdict = check(slug="st-marys", expected=expected)

        self.assertEqual(
            verdict.problems,
            ["St Mary's (st_marys) academics_classgroup has 3 rows after the restore; the live database had 14"],
        )

    def test_a_table_short_by_no_more_than_the_tolerance_passes(self):
        """The last minute's writes were not archived when the restore began;
        failing on them would fail the drill every week a school was busy."""
        verdict = check(slug="st-marys", expected={"academics_classgroup": 3 + tolerance(3)})

        self.assertEqual(verdict.problems, [])

    def test_a_busy_table_is_allowed_a_percent(self):
        self.assertEqual(tolerance(5), 10)
        self.assertEqual(tolerance(10_000), 100)

    def test_a_table_that_did_not_come_back_at_all_is_named(self):
        verdict = check(slug="st-marys", expected={"academics_a_table_that_was_lost": 1})

        self.assertIn("St Mary's (st_marys) has no table academics_a_table_that_was_lost", verdict.problems)

    def test_the_other_schools_rows_do_not_satisfy_this_ones(self):
        """Counts are per schema: Grace has one class group, so St Mary's
        expecting three cannot be met by the platform's total."""
        with tenant_context(self.stmarys):
            ClassGroup.objects.all().delete()

        verdict = check(slug="st-marys", expected={"academics_classgroup": 3 + tolerance(3) + 1})

        self.assertEqual(len(verdict.problems), 1, verdict.problems)
        self.assertIn("has 0 rows", verdict.problems[0])

    def test_print_counts_then_expect_counts_is_the_drill_end_to_end(self):
        printed = StringIO()
        call_command("verify_restore", "--school", "st-marys", "--print-counts", stdout=printed)
        line = printed.getvalue().strip()
        self.assertEqual(json.loads(line)["counts"]["academics_classgroup"], 3)

        out = StringIO()
        call_command("verify_restore", "--expect-counts", line, stdout=out)

        self.assertIn("st-marys:", out.getvalue())
        self.assertIn("matching the live database", out.getvalue())
        self.assertIn("academics_classgroup=3", out.getvalue())

    def test_the_command_fails_naming_the_table_when_the_rows_are_gone(self):
        printed = StringIO()
        call_command("verify_restore", "--school", "st-marys", "--print-counts", stdout=printed)
        line = printed.getvalue().strip()
        wanted = json.loads(line)
        wanted["counts"]["academics_classgroup"] = 500

        with self.assertRaisesMessage(CommandError, "academics_classgroup has 3 rows after the restore"):
            call_command("verify_restore", "--expect-counts", json.dumps(wanted), stdout=StringIO())

    def test_expect_counts_that_is_not_what_print_counts_prints_is_refused(self):
        for bad in ("not json", "[]", '{"school": "grace"}'):
            with self.subTest(bad=bad):
                with self.assertRaisesMessage(CommandError, "--expect-counts is not what"):
                    call_command("verify_restore", "--expect-counts", bad, stdout=StringIO())

    def test_print_counts_checks_nothing_and_reports_nothing(self):
        """Run against the live database: a missing migration there is not a
        restore failure, and it must not check in to the restore monitor."""
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM "st_marys".django_migrations')

        out = StringIO()
        call_command("verify_restore", "--print-counts", stdout=out)

        self.assertEqual(json.loads(out.getvalue())["school"], "grace")


class NoSchoolToCountTests(TestCase):
    def test_a_platform_with_no_school_has_no_rows_to_compare_and_still_passes(self):
        verdict = check()
        self.assertEqual((verdict.counted, verdict.counts, verdict.problems), ("", None, []))

        out = StringIO()
        call_command("verify_restore", "--print-counts", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), {"school": "", "counts": {}})

        call_command("verify_restore", "--expect-counts", out.getvalue(), stdout=out)
        self.assertIn("No school to count rows for.", out.getvalue())
