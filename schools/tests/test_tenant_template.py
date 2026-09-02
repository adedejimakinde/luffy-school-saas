"""What has to stay true for `make_school()` to be allowed to clone.

Every tenant `TestCase` in this repository now runs against a schema copied
from `tenant_template` rather than one built by `migrate_schemas`; the three
`TransactionTestCase` modules still migrate, and `schools/tests/tenants.py` says
why. Two properties make that substitution safe, neither of them obvious, and
nothing else in the suite would notice if either stopped holding:

**A clone is undone by the per-test rollback.** `docs/tenancy.md` depends on
tenant tests being `TestCase` and not `TransactionTestCase`. Postgres DDL is
transactional, so a `CREATE SCHEMA` inside a test is rolled back with it — but
"a clone behaves the same way" was an assumption, and if it were wrong every
test would leak a schema and the suite would fail in whichever test next reused
a name. `SchemaFromACloneIsRolledBackTests` below is four tests that each check
the *previous* test's clone is gone before making their own.

**A clone is the same schema.** This is the one that already went wrong. An
earlier version of the clone function copied tables, indexes and constraints
and checked itself by comparing index and constraint names — which is what it
copied, so it reported success. Measured against a real migrated schema it had
**0 of 13 triggers, 0 of 13 functions and none of the seeded rows**: every
`append_only` rule silently absent, and every school starting with no traits,
no rating scale and no grade bands. A suite running on those schemas would have
gone green while asserting less than it claimed, which is the failure
`scripts/run-tests.sh` exists to refuse. `AClonedSchemaIsTheSameSchemaTests`
compares against a freshly migrated schema on everything, not on the subset the
function happens to copy.

The behavioural half of that second property is not here, and does not need to
be: the results tests assert that a released card cannot be updated, and they
now run against cloned schemas. If the triggers stopped coming across, those
tests fail. What this file adds is a failure that says *why*.
"""

from django.db import connection
from django.test import TestCase

from results.models import GradeBand, RatingScalePoint, Trait, TraitGroup
from schools.models import School
from schools.tests.tenants import (
    TEMPLATE_SCHEMA,
    make_school,
    make_school_by_migrating,
    schema_exists,
)


def query(sql, *params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or None)
        return cursor.fetchall() if cursor.description else []


def structure_of(schema):
    """Everything a tenant schema is made of, by name rather than by count."""
    return {
        "tables": sorted(
            r[0] for r in query(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s", schema
            )
        ),
        "columns": sorted(
            f"{r[0]}.{r[1]}:{r[2]}" for r in query(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns WHERE table_schema = %s", schema
            )
        ),
        "indexes": sorted(
            r[0] for r in query(
                "SELECT indexname FROM pg_indexes WHERE schemaname = %s", schema
            )
        ),
        "constraints": sorted(
            r[0] for r in query(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s", schema
            )
        ),
        "sequences": sorted(
            r[0] for r in query(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind = 'S'", schema
            )
        ),
        "functions": sorted(
            r[0] for r in query(
                "SELECT p.proname FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = %s", schema
            )
        ),
        "triggers": sorted(
            r[0] for r in query(
                "SELECT t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND NOT t.tgisinternal", schema
            )
        ),
    }


def row_counts(schema, tables):
    return {
        table: query(f'SELECT count(*) FROM "{schema}".{table}')[0][0]
        for table in tables
    }


class TheTemplateItselfTests(TestCase):
    """The one migrated schema the whole suite is copied from."""

    def test_the_template_schema_exists(self):
        self.assertTrue(
            schema_exists(TEMPLATE_SCHEMA),
            "the test runner builds this once per test database before the "
            "parallel workers are cloned from it",
        )

    def test_the_template_is_not_a_school(self):
        """No row in `schools_school`, so nothing that counts schools sees it.

        Tests assert on how many schools exist and on what `School.objects`
        returns. A template that was also a School would be a permanent extra
        row in every one of those, which is why it is built by calling
        `create_schema()` on an unsaved instance rather than by saving one.
        """
        self.assertFalse(School.objects.filter(schema_name=TEMPLATE_SCHEMA).exists())


class SchemaFromACloneIsRolledBackTests(TestCase):
    """Four tests, each checking the one before it left no schema behind.

    The property is between tests, so it cannot be asserted inside one. Django
    runs a class's methods in alphabetical order and `--parallel` distributes
    whole `TestCase` classes rather than methods, so these four stay in this
    order in one worker.

    If this ever fails, `make_school()` must go back to migrating: a clone that
    survives its test leaks into the next one, and the first symptom would be
    an unrelated test failing on a schema name that was supposed to be free.
    """

    previous = None

    def _clone_and_remember(self, name):
        if type(self).previous is not None:
            self.assertFalse(
                schema_exists(type(self).previous),
                f"{type(self).previous} survived the rollback of the test that "
                f"made it — cloned schemas are leaking between tests",
            )
        make_school(name.replace("_", " ").title(), name.replace("_", "-"), name)
        self.assertTrue(schema_exists(name))
        type(self).previous = name

    def test_1_first_clone(self):
        self._clone_and_remember("rollback_one")

    def test_2_the_first_is_gone(self):
        self._clone_and_remember("rollback_two")

    def test_3_the_second_is_gone(self):
        self._clone_and_remember("rollback_three")

    def test_4_the_third_is_gone(self):
        self._clone_and_remember("rollback_four")


class AClonedSchemaIsTheSameSchemaTests(TestCase):
    """A clone, compared against a schema built the real way, on everything."""

    def test_a_clone_matches_a_freshly_migrated_schema(self):
        make_school_by_migrating("Migrated", "migrated-school", "compare_migrated")
        make_school("Cloned", "cloned-school", "compare_cloned")

        migrated = structure_of("compare_migrated")
        cloned = structure_of("compare_cloned")

        for kind in migrated:
            self.assertEqual(
                migrated[kind],
                cloned[kind],
                f"{kind} differ between a migrated schema and a cloned one",
            )

        # Named explicitly so that a clone which silently copied none of them
        # cannot pass by matching zero against zero.
        self.assertGreater(len(migrated["triggers"]), 0)
        self.assertGreater(len(migrated["functions"]), 0)

    def test_a_clone_carries_the_rows_the_migrations_seed(self):
        """`results.0006` and `results.0015` seed rows into every new schema.

        Copied structure-only, a school starts with no traits, no rating scale
        and no grade bands — and the report-card tests that read them fail a
        long way from the cause.
        """
        make_school_by_migrating("Migrated", "migrated-school", "seed_migrated")
        make_school("Cloned", "cloned-school", "seed_cloned")

        tables = structure_of("seed_migrated")["tables"]
        migrated = row_counts("seed_migrated", tables)
        cloned = row_counts("seed_cloned", tables)

        self.assertEqual(migrated, cloned)
        self.assertTrue(
            any(count for count in migrated.values()),
            "nothing was seeded at all, so this test is not comparing anything",
        )

    def test_the_seeded_rows_are_readable_through_the_orm(self):
        """Not just present in the catalogue — usable from inside the tenant."""
        school = make_school("Cloned", "cloned-school", "orm_cloned")
        connection.set_tenant(school)
        try:
            self.assertEqual(Trait.objects.count(), 11)
            self.assertEqual(RatingScalePoint.objects.count(), 5)
            self.assertEqual(GradeBand.objects.count(), 9)
        finally:
            connection.set_schema_to_public()

    def test_a_sequence_in_a_clone_does_not_collide_with_a_seeded_row(self):
        """Copying rows without their sequence positions breaks the next insert.

        The seeded traits occupy ids 1..11. A sequence left at the start of its
        range hands out 1 again, and the insert fails on the primary key.
        """
        school = make_school("Cloned", "cloned-school", "sequence_cloned")
        connection.set_tenant(school)
        try:
            highest_seeded = max(Trait.objects.values_list("pk", flat=True))
            trait = Trait.objects.create(
                group=TraitGroup.values[0], name="Punctuality in the morning"
            )
            self.assertGreater(trait.pk, highest_seeded)
        finally:
            connection.set_schema_to_public()
