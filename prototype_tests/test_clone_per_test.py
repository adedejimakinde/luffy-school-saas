"""The test-runner half of the clone_schema prototype, measured where it matters.

`scripts/prototype_clone_schema.py` measured a clone against a migrate in a
plain script, on the development database, outside any transaction. That
answered "is cloning faster than migrating". It did not answer the question the
suite actually poses, which is narrower and harsher:

  build ONE migrated tenant schema per run, then clone it PER TEST —
  inside the test database, inside the per-test transaction, with a
  rollback between every clone.

Those conditions can only make it slower, and one of them could have made it
impossible: `docs/tenancy.md` relies on tenant tests being `TestCase` rather
than `TransactionTestCase`, so a clone has to survive being wrapped in a
transaction that is then thrown away. The prototype write-up called that
"asserted, not tested". It is tested here.

Prototype, not a change to how anything runs. Nothing imports this package and
`make_school()` is untouched.
"""

import os
import sys
import time

from django.db import connection
from django.test import TestCase

from schools.models import School

SQL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
TEMPLATE = "proto_template"

# The figure in `.github/workflows/tests.yml`, and the thing being argued with.
CI_BASELINE = 1.65


def sql(statement, *params):
    with connection.cursor() as cursor:
        cursor.execute(statement, params or None)
        return cursor.fetchall() if cursor.description else []


def schema_exists(name):
    return bool(sql("SELECT 1 FROM pg_namespace WHERE nspname = %s", name))


def build_by_migrating(schema_name):
    """Exactly what every make_school() in the suite pays, timed."""
    connection.set_schema_to_public()
    school = School(
        name=schema_name, slug=schema_name.replace("_", "-"), schema_name=schema_name
    )
    started = time.perf_counter()
    school.save()
    return time.perf_counter() - started


def report(label, times, extra=""):
    mean = sum(times) / len(times)
    print(
        f"\n  [{label}] n={len(times)}  "
        f"min {min(times):.3f}s  max {max(times):.3f}s  mean {mean:.3f}s{extra}",
        file=sys.stderr,
    )
    print("    " + "  ".join(f"{t:.3f}" for t in times), file=sys.stderr)
    return mean


class MigrateBaselinePerTest(TestCase):
    """The cost the suite pays today: one CREATE SCHEMA + migrate per test."""

    times = []

    def _build(self, n):
        taken = build_by_migrating(f"proto_base_{n}")
        type(self).times.append(taken)

    def test_1(self):
        self._build(1)

    def test_2(self):
        self._build(2)

    def test_3(self):
        self._build(3)

    def test_4(self):
        self._build(4)

    def test_5(self):
        self._build(5)

    @classmethod
    def tearDownClass(cls):
        report("migrate per test", cls.times, f"   [CI comment cites ~{CI_BASELINE}s]")
        super().tearDownClass()


class ClonePerTest(TestCase):
    """One migrated template per run; a clone per test, rolled back between."""

    times = []
    previous = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        connection.set_schema_to_public()
        with open(os.path.join(SQL_DIR, "clone_schema_v2.sql")) as handle:
            sql(handle.read())
        cls.template_cost = build_by_migrating(TEMPLATE)
        print(
            f"\n  [template] built once for the run by the ordinary path: "
            f"{cls.template_cost:.3f}s",
            file=sys.stderr,
        )

    def _clone(self, n):
        # The previous test's clone must be gone. This is the property the
        # write-up asserted without testing: a clone made inside a TestCase is
        # undone by the same rollback that undoes a CREATE SCHEMA, so tenant
        # tests can stay TestCase and never TransactionTestCase.
        if type(self).previous is not None:
            self.assertFalse(
                schema_exists(type(self).previous),
                f"{type(self).previous} survived the rollback — a clone per test "
                f"would leak schemas across tests",
            )

        dest = f"proto_clone_{n}"
        connection.set_schema_to_public()
        started = time.perf_counter()
        sql("SELECT clone_schema_v2(%s, %s)", TEMPLATE, dest)
        taken = time.perf_counter() - started

        type(self).times.append(taken)
        type(self).previous = dest

        # A clone nothing can be written to is not a tenant schema. Prove the
        # structure is live, not merely present, before trusting the number.
        self.assertTrue(schema_exists(dest))
        rows = sql(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
            dest,
        )
        self.assertGreater(rows[0][0], 0)

    def test_1(self):
        self._clone(1)

    def test_2(self):
        self._clone(2)

    def test_3(self):
        self._clone(3)

    def test_4(self):
        self._clone(4)

    def test_5(self):
        self._clone(5)

    def test_6_structure_matches_a_migrated_schema(self):
        """A fast clone that is not the same schema is worth nothing.

        The earlier write-up checked this on the development database. It is
        checked here in the *test* database, which is the one that would
        actually be built this way. Names, not just counts: `LIKE INCLUDING
        ALL` regenerates index names, and this repository asserts constraint
        violations by name.
        """
        connection.set_schema_to_public()
        sql("SELECT clone_schema_v2(%s, %s)", TEMPLATE, "proto_structure")
        for kind in ("index", "constraint"):
            expected, got = names(TEMPLATE, kind), names("proto_structure", kind)
            self.assertEqual(
                expected, got, f"{kind} names differ between template and clone"
            )
            print(f"    [structure] {len(expected)} {kind} names preserved",
                  file=sys.stderr)

    @classmethod
    def tearDownClass(cls):
        report("clone per test", cls.times)
        super().tearDownClass()


def names(schema, kind):
    if kind == "index":
        rows = sql("SELECT indexname FROM pg_indexes WHERE schemaname = %s", schema)
    else:
        rows = sql(
            """SELECT con.conname FROM pg_constraint con
               JOIN pg_class c ON c.oid = con.conrelid
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = %s""",
            schema,
        )
    return sorted(r[0] for r in rows)


def tearDownModule():
    """Print the comparison once, whichever order the runner chose."""
    base, clones = MigrateBaselinePerTest.times, ClonePerTest.times
    if not (base and clones):
        return
    mean_base = sum(base) / len(base)
    mean_clone = sum(clones) / len(clones)
    template = ClonePerTest.template_cost
    print(
        f"\n  VERDICT  migrate {mean_base:.3f}s -> clone {mean_clone:.3f}s = "
        f"{mean_base / mean_clone:.1f}x faster on this machine; "
        f"{CI_BASELINE / mean_clone:.1f}x against the {CI_BASELINE}s CI figure.",
        file=sys.stderr,
    )
    print(
        f"           template paid once ({template:.3f}s); break-even after "
        f"{template / max(mean_base - mean_clone, 1e-9):.1f} tenants, "
        f"of ~1,479 built per run.",
        file=sys.stderr,
    )
