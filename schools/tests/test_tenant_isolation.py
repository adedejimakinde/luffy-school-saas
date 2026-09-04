"""Proof that schema-per-school is real, against a real Postgres.

Nothing here is mocked and nothing skips schema creation. `RealSchemaCreationTests`
runs the production path in full — `CREATE SCHEMA` followed by the whole
`migrate_schemas` run for TENANT_APPS — because that path is its subject: it is
the test that would have to fail if saving a School stopped building a schema.
It therefore keeps calling `make_school_by_migrating()` and keeps paying the
~1.65s, and the assertions read from `pg_namespace`, `pg_tables` and
`pg_constraint` rather than taking Django's word for any of it.

The classes below it use the ordinary `make_school()`, which copies a schema
that was migrated once for the run. What they are about is isolation between
two schemas, not the manner of either one's construction, and
`schools/tests/test_tenant_template.py` is what proves a copied schema is the
same schema — including the append-only triggers this file's neighbours rely
on.

The claim being defended is the one the whole product rests on: a school's
records are not *filtered* away from other schools, they are in a different
Postgres schema which is not on the other connection's `search_path` at all.
`test_the_tenant_table_is_absent_from_public_not_merely_empty` is the load
bearing test — if it ever goes green by returning an empty list instead of
raising, isolation has silently become a query filter and the claim is false.

Note these are plain `TestCase`s, not `TenantTestCase`. See the harness notes
in docs/tenancy.md and `TenantTestCaseHarnessTests` at the bottom of this file.
"""

import contextlib
from datetime import date

from django.db import IntegrityError, ProgrammingError, connection, transaction
from django.test import TestCase
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import tenant_context

from academics.models import Term, TermName
from accounts.models import Membership, Role, User
from schools.models import Domain, School
from schools.tests.tenants import make_school, make_school_by_migrating

PASSWORD = "correct-horse-battery"


def make_term(session="2025/2026", name=TermName.FIRST, **extra):
    extra.setdefault("starts_on", date(2025, 9, 15))
    extra.setdefault("ends_on", date(2025, 12, 12))
    return Term.objects.create(session=session, name=name, **extra)


def query(sql, *params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or None)
        return cursor.fetchall()


def schema_names():
    """Straight from Postgres — the equivalent of \\dn."""
    return [
        row[0]
        for row in query(
            "select nspname from pg_namespace "
            "where nspname not like 'pg_%%' and nspname <> 'information_schema' "
            "order by 1"
        )
    ]


def tables_in(schema):
    return [
        row[0]
        for row in query(
            "select tablename from pg_tables where schemaname = %s order by 1", schema
        )
    ]


def search_path():
    return query("show search_path")[0][0]


@contextlib.contextmanager
def connected_to(school):
    """Scope the connection to `school`'s schema, as the middleware would.

    Restores whatever schema was current on the way out, so this nests. It used
    to force `public` instead, which is the same thing at the outermost level —
    the schema it found there *is* public — and a trap one level in: the inner
    block's exit dropped the outer block onto public, and the next lazy read in
    the outer block went looking for tenant tables in the shared schema. See
    `ConnectedToNestsTests` below for what that costs to diagnose (issue #58).

    Restoring keeps the guarantee the old version was written for. A test still
    cannot leave the connection inside a schema that is about to be dropped,
    because unwinding the outermost block still lands on public.

    `tenant_context` rather than `schema_context`: it hands `connection.tenant`
    the real `School`, so `schools.logging.current_school()` can print the
    school's name. `schema_context` sets a `FakeTenant`, which knows a schema
    name and no display name.
    """
    with tenant_context(school):
        yield


class RealSchemaCreationTests(TestCase):
    """Saving a School creates a genuine Postgres schema with genuine tables."""

    def test_saving_a_school_creates_a_real_postgres_schema(self):
        self.assertNotIn("st_marys", schema_names())
        make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        self.assertIn("st_marys", schema_names())

    def test_the_new_schema_holds_the_tenant_apps_tables(self):
        make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        self.assertIn("academics_term", tables_in("st_marys"))

    def test_the_tenant_table_is_never_created_in_public(self):
        """TENANT_APPS must not leak into the shared schema."""
        make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        self.assertNotIn("academics_term", tables_in("public"))

    def test_shared_tables_are_not_created_in_the_tenant_schema(self):
        """`migrate_schemas` prints "Applying accounts.0001_initial... OK" for a
        tenant schema, which reads as though the shared tables were created
        there. They are not: TenantSyncRouter skips the operations and only the
        django_migrations bookkeeping row is written. Pin the truth.
        """
        make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        tenant_tables = tables_in("st_marys")
        self.assertNotIn("accounts_user", tenant_tables)
        self.assertNotIn("accounts_membership", tenant_tables)
        self.assertNotIn("schools_school", tenant_tables)
        # ...even though the migration is recorded as applied in that schema.
        with connected_to(School.objects.get(schema_name="st_marys")):
            applied = {row[0] for row in query("select app from django_migrations")}
        self.assertIn("accounts", applied)

    def test_constraints_and_indexes_are_created_per_schema(self):
        """Not just the table — the constraints come with it, per schema.

        Note where each one lands. A plain UniqueConstraint and a
        CheckConstraint become entries in pg_constraint, but a *partial*
        UniqueConstraint (one with a condition) is implemented by Django as a
        unique index instead, so `one_current_term` is only ever in pg_indexes.
        It is enforced either way; it just is not a table constraint.
        """
        make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        constraints = {
            row[0]
            for row in query(
                "select conname from pg_constraint "
                "where connamespace = 'st_marys'::regnamespace"
            )
        }
        self.assertIn("uniq_term_session_name", constraints)
        self.assertIn("term_ends_after_it_starts", constraints)

        indexes = {
            row[0]
            for row in query(
                "select indexname from pg_indexes where schemaname = 'st_marys'"
            )
        }
        self.assertIn("one_current_term", indexes)

    def test_the_partial_unique_index_is_enforced_inside_the_schema(self):
        """Enforced per schema, so each school may have its own current term."""
        stmarys = make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        grace = make_school_by_migrating("Grace Academy", "grace", "grace")

        with connected_to(stmarys):
            make_term(is_current=True)
            with self.assertRaises(IntegrityError), transaction.atomic():
                make_term(name=TermName.SECOND, is_current=True)

        # ...and St Mary's having a current term does not stop Grace having one.
        with connected_to(grace):
            make_term(is_current=True)
            self.assertEqual(Term.objects.filter(is_current=True).count(), 1)

    def test_saving_a_school_leaves_the_connection_on_public(self):
        """A real surprise worth pinning: django_tenants' create_schema() ends
        with set_schema_to_public(), so you are NOT left inside the school you
        just created. Anything that assumes otherwise writes to public.
        """
        make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        self.assertEqual(connection.schema_name, "public")
        self.assertEqual(search_path(), "public")

    def test_a_domain_routes_to_the_school(self):
        school = make_school_by_migrating("St Mary's", "st-marys", "st_marys")
        Domain.objects.create(tenant=school, domain="stmarys.luffy.school", is_primary=True)
        self.assertEqual(
            Domain.objects.get(domain="stmarys.luffy.school").tenant, school
        )


class SchemaIsolationTests(TestCase):
    """The claim the product rests on. If any of this fails, isolation is a lie."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

    def test_a_row_in_one_school_is_not_visible_from_another(self):
        with connected_to(self.stmarys):
            make_term()
            self.assertEqual(Term.objects.count(), 1)

        with connected_to(self.grace):
            self.assertEqual(Term.objects.count(), 0)

    def test_the_tenant_table_is_absent_from_public_not_merely_empty(self):
        """The load-bearing test.

        From public, `academics_term` must not exist *at all*. An empty result
        here instead of an exception would mean the table had leaked into the
        shared schema and isolation had quietly become a query filter.

        The failed statement aborts the surrounding transaction, so the probe
        has to sit in its own savepoint or every later query in this test dies
        with "current transaction is aborted".
        """
        with connected_to(self.stmarys):
            make_term()

        self.assertEqual(search_path(), "public")
        with self.assertRaises(ProgrammingError) as caught:
            with transaction.atomic():
                query("select * from academics_term")
        self.assertIn("does not exist", str(caught.exception))

        # And the connection is still usable afterwards, thanks to the savepoint.
        self.assertEqual(School.objects.count(), 2)

    def test_the_same_natural_key_can_exist_in_both_schools(self):
        """Uniqueness is per-schema, because the index is per-schema.

        Both schools own a "2025/2026 First term" and neither collides. A single
        shared table with a school_id column could not do this without putting
        the school in every unique constraint by hand.
        """
        with connected_to(self.stmarys):
            make_term(starts_on=date(2025, 9, 15), ends_on=date(2025, 12, 12))
        with connected_to(self.grace):
            make_term(starts_on=date(2025, 9, 8), ends_on=date(2025, 12, 19))

        rows = query(
            "select starts_on from st_marys.academics_term "
            "union all select starts_on from grace.academics_term order by 1"
        )
        self.assertEqual([r[0] for r in rows], [date(2025, 9, 8), date(2025, 9, 15)])

    def test_the_two_schools_rows_live_in_physically_different_tables(self):
        """Not the same table filtered two ways — two tables."""
        with connected_to(self.stmarys):
            make_term()
        with connected_to(self.grace):
            make_term()

        oids = query(
            "select (select tableoid from st_marys.academics_term limit 1), "
            "       (select tableoid from grace.academics_term limit 1)"
        )[0]
        self.assertNotEqual(oids[0], oids[1])

    def test_search_path_is_what_does_the_isolating(self):
        """The mechanism itself, stated once so it cannot be quietly changed."""
        with connected_to(self.stmarys):
            self.assertEqual(search_path(), "st_marys, public")
        with connected_to(self.grace):
            self.assertEqual(search_path(), "grace, public")
        self.assertEqual(search_path(), "public")

    def test_dropping_a_school_takes_only_its_own_data(self):
        with connected_to(self.stmarys):
            make_term()
        with connected_to(self.grace):
            make_term()

        self.grace.delete(force_drop=True)  # auto_drop_schema is False by default

        self.assertNotIn("grace", schema_names())
        self.assertIn("st_marys", schema_names())
        with connected_to(self.stmarys):
            self.assertEqual(Term.objects.count(), 1)


class ConnectedToNestsTests(TestCase):
    """`connected_to` restores the schema it found, so it nests.

    It used to end in `set_schema_to_public()` unconditionally, and at the
    outermost level that is invisible: the schema it found *was* public, so
    forcing public and restoring public are the same thing. One level in they
    are not. The inner block's exit drops the *outer* block onto public, and
    every read after it in the outer block asks a schema where the tenant
    tables do not exist.

    What makes it expensive is that the failure never mentions a schema. It
    arrives as `relation "academics_term" does not exist` from whichever line
    touched the object next — often frames away from either `with`, inside a
    payload builder or a serialiser — and the helper that produced the object
    works perfectly when called on its own. Task 7 lost a test run to exactly
    that, and `results/tests/test_pdf.py` carried a workaround for it until
    this change. Issue #58.

    The old guarantee is kept rather than dropped: restoring what was current
    still lands the outermost block back on public, so no test can leave the
    connection inside a schema that is about to be dropped.
    """

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

    def test_leaving_an_inner_block_returns_to_the_outer_school(self):
        with connected_to(self.stmarys):
            with connected_to(self.grace):
                self.assertEqual(connection.schema_name, "grace")
            self.assertEqual(connection.schema_name, "st_marys")
            self.assertEqual(search_path(), "st_marys, public")

    def test_the_outer_block_can_still_read_its_own_rows(self):
        """The same thing said in the terms a caller would notice it in."""
        with connected_to(self.stmarys):
            make_term()

        with connected_to(self.stmarys):
            with connected_to(self.grace):
                self.assertEqual(Term.objects.count(), 0)
            self.assertEqual(Term.objects.count(), 1)

    def test_an_object_fetched_in_an_inner_block_is_read_in_the_outer_one(self):
        """The shape that actually bit: a lazy read after somebody else's block.

        `fetch()` opens a context of its own, which is the ordinary way to write
        a helper. Nothing about the call site says a `with` is closing inside
        it, and the object it returns has not read `session` yet — that query
        runs on the line below, on whatever schema the connection is left on.
        """

        with connected_to(self.stmarys):
            make_term(session="2025/2026")

        def fetch():
            with connected_to(self.stmarys):
                return Term.objects.only("id").get()

        with connected_to(self.stmarys):
            term = fetch()
            self.assertEqual(term.session, "2025/2026")

    def test_three_levels_unwind_one_at_a_time(self):
        """Restoring the previous schema, not "the outer school" — the same
        school twice over must come back to itself as well."""
        with connected_to(self.stmarys):
            with connected_to(self.grace):
                with connected_to(self.stmarys):
                    self.assertEqual(connection.schema_name, "st_marys")
                self.assertEqual(connection.schema_name, "grace")
            self.assertEqual(connection.schema_name, "st_marys")
        self.assertEqual(connection.schema_name, "public")

    def test_an_exception_inside_an_inner_block_still_restores_the_outer_one(self):
        """The restore is in a `finally`, so the unwinding path gets it too."""
        with connected_to(self.stmarys):
            with self.assertRaises(ZeroDivisionError):
                with connected_to(self.grace):
                    raise ZeroDivisionError("something in the inner block")
            self.assertEqual(connection.schema_name, "st_marys")
        self.assertEqual(connection.schema_name, "public")

    def test_the_outermost_block_still_lands_on_public(self):
        """The guarantee the old version was written for, kept.

        This is the assertion that says the change is invisible to the 800-odd
        existing call sites: not one of them nests, so for every one of them
        the schema restored is the public schema they were already given.
        """
        with connected_to(self.stmarys):
            make_term()
        self.assertEqual(connection.schema_name, "public")
        self.assertEqual(search_path(), "public")

    def test_the_connection_carries_the_school_itself_not_a_stand_in(self):
        """Why `tenant_context` and not `schema_context`.

        `schema_context(name)` sets a `FakeTenant`, which has a schema name and
        no display name. `schools.logging.current_school()` reads
        `connection.tenant.name`, so every log line that reads `[St Mary's]`
        today would read `[st_marys]` instead — `schools/tests/test_logging.py`
        asserts the display name and imports this helper. The other thirteen
        `connected_to` definitions in this repo do wrap `schema_context`, so
        that difference is real rather than stylistic; issue #67 covers it.

        The restore has to bring the `School` back too, not merely its schema
        name, or a nested block would quietly downgrade the outer one.
        """
        with connected_to(self.stmarys):
            self.assertIs(connection.tenant, self.stmarys)
            with connected_to(self.grace):
                self.assertIs(connection.tenant, self.grace)
            self.assertIs(connection.tenant, self.stmarys)


class SharedModelsResolveFromInsideATenantTests(TestCase):
    """SHARED_APPS keep working from inside a school's schema.

    They resolve because `public` is the second entry on every tenant
    connection's search_path — which is exactly why one login can span schools.
    """

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

    def test_a_membership_created_inside_a_tenant_reads_back_correctly(self):
        with connected_to(self.stmarys):
            teacher = User.objects.create_user("ada", PASSWORD, full_name="Ada Obi")
            Membership.objects.create(user=teacher, school=self.stmarys, role=Role.TEACHER)

            self.assertEqual(teacher.roles_at(self.stmarys), {"teacher"})
            self.assertTrue(teacher.has_access_to(self.stmarys))
            self.assertEqual(
                list(teacher.schools().values_list("name", flat=True)), ["St Mary's"]
            )

    def test_the_shared_row_lands_in_public_not_in_the_tenant_schema(self):
        with connected_to(self.stmarys):
            User.objects.create_user("ada", PASSWORD, full_name="Ada Obi")
            # Written from inside st_marys, but there is no accounts_user table
            # there — the search_path resolved it to public.
            self.assertNotIn("accounts_user", tables_in("st_marys"))
            self.assertEqual(query("select count(*) from public.accounts_user")[0][0], 1)

    def test_one_parent_spans_two_schools_from_inside_either_one(self):
        """The reason accounts is shared at all, proven from within a schema."""
        parent = User.objects.create_user("bisi", PASSWORD, full_name="Bisi Ade")
        Membership.objects.create(user=parent, school=self.stmarys, role=Role.PARENT)
        Membership.objects.create(user=parent, school=self.grace, role=Role.PARENT)

        for school in (self.stmarys, self.grace):
            with connected_to(school):
                found = User.objects.get(pk=parent.pk)
                self.assertEqual(
                    sorted(found.schools().values_list("name", flat=True)),
                    ["Grace Academy", "St Mary's"],
                )
                # Reachable from inside one school's schema, including the other.
                self.assertTrue(found.has_access_to(self.grace))
                self.assertTrue(found.has_access_to(self.stmarys))

    def test_tenant_data_and_shared_data_are_visible_in_the_same_breath(self):
        """One connection, both worlds: the school's own term and the shared user."""
        with connected_to(self.stmarys):
            user = User.objects.create_user("ada", PASSWORD, full_name="Ada Obi")
            Membership.objects.create(user=user, school=self.stmarys, role=Role.TEACHER)
            make_term()

            self.assertEqual(Term.objects.count(), 1)  # st_marys.academics_term
            self.assertEqual(User.objects.count(), 1)  # public.accounts_user


class TenantTestCaseHarnessTests(TenantTestCase):
    """Pins the two traps in django_tenants' own test harness.

    These assert third-party behaviour on purpose. docs/tenancy.md tells people
    to write tenant tests a particular way *because* of what is pinned here, so
    if a future django-tenants release changes it, this file should fail and
    send someone to update those docs.
    """

    setUpTestData_ran = False

    @classmethod
    def setup_tenant(cls, tenant):
        # Trap 1: without this the harness saves School(schema_name='test') with
        # name='' and slug='', because a blank CharField is not a NULL and so
        # passes the database happily.
        tenant.name = "Harness School"
        tenant.slug = "harness"

    @classmethod
    def setup_domain(cls, domain):
        domain.is_primary = True

    @classmethod
    def setUpTestData(cls):
        cls.setUpTestData_ran = True

    def test_the_harness_creates_a_real_schema_and_sets_the_connection(self):
        self.assertIn("test", schema_names())
        self.assertIn("academics_term", tables_in("test"))
        self.assertEqual(connection.schema_name, "test")
        self.assertEqual(search_path(), "test, public")

    def test_setup_tenant_is_required_for_a_sane_tenant_row(self):
        self.assertEqual(self.tenant.name, "Harness School")
        self.assertEqual(self.tenant.slug, "harness")

    def test_setUpTestData_does_not_run_under_this_harness(self):
        """Trap 2, and the nastier one.

        TenantTestCase.setUpClass never calls super().setUpClass(), so Django's
        TestCase class setup — which is what invokes setUpTestData — is skipped
        entirely. Fixtures written there are silently absent rather than
        erroring, so tests quietly assert against nothing.
        """
        self.assertFalse(
            self.setUpTestData_ran,
            "django-tenants now calls super().setUpClass(); setUpTestData works. "
            "Update the harness section of docs/tenancy.md.",
        )

    def test_tenant_rows_are_still_rolled_back_between_tests(self):
        """Per-test transactions do work, even though class-level setup does not."""
        self.assertEqual(Term.objects.count(), 0)
        make_term()
        self.assertEqual(Term.objects.count(), 1)

    def test_the_previous_test_left_nothing_behind(self):
        self.assertEqual(Term.objects.count(), 0)
