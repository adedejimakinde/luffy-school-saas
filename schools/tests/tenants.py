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

## Three things that are deliberately not cloned

`accounts.tests.test_membership`, `accounts.tests.test_transfers`,
`accounts.tests.test_transfer_concurrency` and `schools.tests.test_invitations`
set `auto_create_schema = False` because every model they touch is in the public
schema. They never paid the cost and they keep their own `make_school()`;
cloning would hand them a schema they deliberately do without.

`results.tests.test_approval_concurrency`,
`results.tests.test_ratings_concurrency` and
`results.tests.test_release_roster_race` are `TransactionTestCase`, so nothing
they do is rolled back: they build schemas that really commit and drop them in
teardown, and their flush between tests would empty a cloned schema's seeded
rows anyway. Twenty-one tests still migrate for that reason. Converting them is
a separate question about their teardown, not about this function.

`make_school_by_migrating()` below is the real path, kept for the tests whose
subject *is* the real path — `RealSchemaCreationTests` asserts that saving a
School creates a genuine Postgres schema, and it has to keep asserting that
against the code that really does it.
"""

import contextlib
import os

from django.db import connections
from django.db.utils import DEFAULT_DB_ALIAS
from django_tenants.utils import tenant_context

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


@contextlib.contextmanager
def connected_to(school):
    """Scope the connection to `school`'s schema, as the middleware would.

    The one definition. There were fourteen (issue #67): thirteen wrapping
    `schema_context(school.schema_name)` and this one wrapping
    `tenant_context(school)`, with nothing in the name to say which a module had
    imported.

    **`tenant_context`, not `schema_context`**, and the choice is not cosmetic:

    - `tenant_context(school)` puts the real `School` on `connection.tenant`, so
      `schools.logging.current_school()` prints `[St Mary's]`. `schema_context`
      sets a `FakeTenant`, which knows a schema name and no display name, and
      the same log line reads `[st_marys]`. Only `schools/tests/test_logging.py`
      asserts on this, which is why the divergence survived unnoticed — and why
      standardising the *other* way would have been the quiet choice rather than
      the safe one.
    - Both restore the schema they found rather than forcing `public`, so this
      nests. The hand-rolled version this replaced did not, which is issue #58,
      and it cost a lost run and a diagnosis three frames from its cause. Twice.

    Restoring keeps the guarantee the old version was written for: a test still
    cannot leave the connection inside a schema about to be dropped, because
    unwinding the outermost block lands on public — that being the schema the
    outermost block found.
    """
    with tenant_context(school):
        yield


@contextlib.contextmanager
def _on_public(connection):
    """Run schema DDL on `public`, then put the connection back where it was.

    `build_template()` and `clone_template()` need `public`: they install a
    function and issue `CREATE SCHEMA`, and both belong to the shared schema
    rather than to any tenant. That reason is real and unchanged.

    What changed is the exit. They used to *end* on public, so `make_school()` —
    which calls `clone_template()` — silently dropped its caller onto public.
    Inside a `connected_to` block that is issue #58's shape all over again, three
    lines from the helper that fixes it: the block appears to continue, and the
    next lazy read goes looking for tenant tables in the shared schema. Issue
    #67. `MakeSchoolInsideABlockTests` is what holds this up.
    """
    previous = getattr(connection, "tenant", None)
    connection.set_schema_to_public()
    try:
        yield
    finally:
        if previous is None:
            connection.set_schema_to_public()
        else:
            connection.set_tenant(previous)


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
    with _on_public(connection):
        with open(CLONE_FUNCTION_SQL) as handle:
            definition = handle.read()
        with connection.cursor() as cursor:
            cursor.execute(definition)

        if not schema_exists(TEMPLATE_SCHEMA, using):
            # `create_schema()` on an unsaved instance: it issues CREATE SCHEMA
            # and then `migrate_schemas --schema`, which takes the schema name
            # and does not read `schools_school`. Nothing is written to the
            # public schema, so the template leaves no row behind for a test to
            # trip over.
            School(
                name="Tenant template",
                slug="tenant-template",
                schema_name=TEMPLATE_SCHEMA,
            ).create_schema(check_if_exists=True, verbosity=verbosity)
            # `create_schema()` leaves the connection on the schema it built, so
            # this comes back to public for the rest of the block. `_on_public`
            # restores the caller's schema on the way out either way.
            connection.set_schema_to_public()

    return TEMPLATE_SCHEMA


def clone_template(schema_name, using=None):
    """Copy the template into `schema_name`. About 0.27s against 1.65s."""
    connection = _connection(using)
    with _on_public(connection):
        _clone_template_on_public(connection, schema_name, using)


def _clone_template_on_public(connection, schema_name, using):
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

    **Schema-neutral.** The row and the DDL both belong on `public`, and this
    ends where it started rather than on public — so calling it from inside a
    `connected_to` block leaves that block where it was. It used to drop the
    caller onto public, which is issue #58's shape and was issue #67's other
    half. `MakeSchoolInsideABlockTests` pins it.
    """
    connection = _connection(using)
    with _on_public(connection):
        school = School(name=name, slug=slug, schema_name=schema_name)
        # The template supplies the schema, so `save()` must not also build one.
        school.auto_create_schema = False
        school.save()
        _clone_template_on_public(connection, schema_name, using)
    return school


def make_school_by_migrating(name, slug, schema_name):
    """A real tenant, the slow way: CREATE SCHEMA plus a full migrate_schemas.

    For the tests whose subject is that path itself. Everything else should use
    `make_school()` — this one costs about 1.65s every time it is called.
    """
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.save()
    return school
