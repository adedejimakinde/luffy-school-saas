"""One migrated tenant schema per test database, and a clone of it per test.

## What this replaces

`make_school()` used to be copied into fourteen test modules, and ten of those
copies did the same expensive thing: `School.save()` with `auto_create_schema`
left on, which issues `CREATE SCHEMA` and then runs `migrate_schemas` into it.
That costs about **1.65s**, and because thirty-three test modules build their
schools in `setUp` rather than `setUpTestData`, the suite paid it roughly
**1,479 times a run** — around 90% of its wall clock, none of it assertion work.

Here the migration is paid **once per test database** and every school after
that is a copy of the result. `schools/tests/clone_tenant_schema.sql` explains
what a faithful copy has to include and why an unfaithful one is worse than no
change at all.

## Where the template comes from, and what happens under `--parallel`

`schools.tests.runner.TenantTemplateRunner` builds it in `setup_databases()`,
between Django creating the test database and Django cloning that database for
each parallel worker. That ordering is the whole trick: the template is inside
the database being copied, so every worker inherits it through
`CREATE DATABASE ... TEMPLATE ...` at about 0.11s, and **no worker migrates
anything**. Build it after the workers had been cloned and each of the N workers
would have to migrate its own.

There is deliberately **no lazy fallback**. A missing template would otherwise be
rebuilt inside the per-test transaction and rolled back with it — once per test,
which is slower than the migration this replaces and completely silent. That is
the failure mode `scripts/run-tests.sh` exists to refuse, so a missing template
raises and says what to fix.

## Two things that are deliberately not cloned

`accounts.tests.test_membership`, `accounts.tests.test_transfers`,
`accounts.tests.test_transfer_concurrency` and `schools.tests.test_invitations`
set `auto_create_schema = False` because every model they touch is in the public
schema. They never paid the cost and they keep their own `make_school()`;
cloning would hand them a schema they deliberately do without.

`make_school_by_migrating()` below is the real path, kept for the tests whose
subject *is* the real path — `RealSchemaCreationTests` asserts that saving a
School creates a genuine Postgres schema, and it has to keep asserting that
against the code that really does it.
"""

import os

from django.db import connections
from django.db.utils import DEFAULT_DB_ALIAS

from schools.models import School

#: The migrated schema every test's school is copied from. Not a School — there
#: is no row for it in `schools_school`, so nothing that counts or lists schools
#: can see it, and a test that asserts "no schools yet" still holds.
TEMPLATE_SCHEMA = "tenant_template"

CLONE_FUNCTION_SQL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "clone_tenant_schema.sql"
)


class TemplateMissing(RuntimeError):
    """The template schema is not in this database, so nothing can be cloned."""


def _connection(using=None):
    return connections[using or DEFAULT_DB_ALIAS]


def schema_exists(name, using=None):
    connection = _connection(using)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", [name])
        return cursor.fetchone() is not None


def build_template(using=None, verbosity=0):
    """Install the clone function and migrate the template. Idempotent.

    Called once per test database by the test runner, before Django clones that
    database for the parallel workers. Safe to call again: the function is
    `CREATE OR REPLACE` and the schema is only built if it is absent.
    """
    connection = _connection(using)
    connection.set_schema_to_public()

    with open(CLONE_FUNCTION_SQL) as handle:
        definition = handle.read()
    with connection.cursor() as cursor:
        cursor.execute(definition)

    if not schema_exists(TEMPLATE_SCHEMA, using):
        # `create_schema()` on an unsaved instance: it issues CREATE SCHEMA and
        # then `migrate_schemas --schema`, which takes the schema name and does
        # not read `schools_school`. Nothing is written to the public schema, so
        # the template leaves no row behind for a test to trip over.
        School(
            name="Tenant template",
            slug="tenant-template",
            schema_name=TEMPLATE_SCHEMA,
        ).create_schema(check_if_exists=True, verbosity=verbosity)
        connection.set_schema_to_public()

    return TEMPLATE_SCHEMA


def clone_template(schema_name, using=None):
    """Copy the template into `schema_name`. About 0.27s against 1.65s."""
    connection = _connection(using)
    connection.set_schema_to_public()
    if not schema_exists(TEMPLATE_SCHEMA, using):
        raise TemplateMissing(
            f"{TEMPLATE_SCHEMA!r} is not in this test database, so there is "
            f"nothing to clone. It is built once per database by "
            f"schools.tests.runner.TenantTemplateRunner, which settings.py sets "
            f"as TEST_RUNNER — check that it is still set, and that anything "
            f"overriding it calls build_template(). Building it here instead "
            f"would happen inside this test's transaction and be rolled back "
            f"with it, once per test, which is slower than the migration this "
            f"replaces and would say nothing about why."
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT clone_tenant_schema(%s, %s)", [TEMPLATE_SCHEMA, schema_name]
        )


def make_school(name, slug, schema_name, using=None):
    """A real tenant, its schema copied from the template instead of migrated.

    The schema this produces is the same one `make_school_by_migrating()` makes
    — same tables, columns, indexes, constraints, sequences, functions,
    triggers and seeded rows. `schools/tests/test_tenant_template.py` is what
    holds that claim up, and it compares a clone against a freshly migrated
    schema on every one of those.
    """
    school = School(name=name, slug=slug, schema_name=schema_name)
    # The template supplies the schema, so `save()` must not also build one.
    school.auto_create_schema = False
    school.save()
    clone_template(schema_name, using)
    return school


def make_school_by_migrating(name, slug, schema_name):
    """A real tenant, the slow way: CREATE SCHEMA plus a full migrate_schemas.

    For the tests whose subject is that path itself. Everything else should use
    `make_school()` — this one costs about 1.65s every time it is called.
    """
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.save()
    return school
