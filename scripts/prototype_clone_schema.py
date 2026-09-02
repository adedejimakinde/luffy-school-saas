"""Measure cloning a migrated tenant schema against building one from migrations.

Prototype, not a change to how anything runs. The number it is arguing with is
the one in `.github/workflows/tests.yml`: ~1.65s of CREATE SCHEMA plus
`migrate_schemas` per tenant, about 1,479 times per suite run.

Five consecutive of each, reported individually rather than averaged — a mean
would hide a first-run cost, and a first-run cost is the whole question when the
thing being proposed is "pay it once, then copy".

Structure is compared afterwards, because a fast clone that is not the same
schema is worth nothing. The comparison is deliberately picky: column defaults
and **index names** are both included, the latter because this project has a
test that reads index names out of `information_schema` and `LIKE INCLUDING
INDEXES` regenerates names rather than copying them.
"""

import os
import sys
import time

import django

# The repository root, so `settings` and the apps import the same way they do
# for `manage.py` — this file lives one directory down.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from django.db import connection  # noqa: E402
from schools.models import School  # noqa: E402

TEMPLATE = "proto_template"
BASELINE = [f"proto_baseline_{i}" for i in range(1, 6)]
CLONES_V1 = [f"proto_v1_{i}" for i in range(1, 6)]
CLONES_V2 = [f"proto_v2_{i}" for i in range(1, 6)]
HERE = os.path.dirname(os.path.abspath(__file__))


def sql(statement, *params):
    with connection.cursor() as cursor:
        cursor.execute(statement, params or None)
        if cursor.description:
            return cursor.fetchall()
        return []


def drop_everything():
    connection.set_schema_to_public()
    for name in BASELINE + CLONES_V1 + CLONES_V2 + [TEMPLATE]:
        sql(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    School.objects.filter(schema_name__startswith="proto_").delete()


def build_by_migrating(schema_name):
    """The real path: what every make_school() in the suite pays."""
    connection.set_schema_to_public()
    school = School(
        name=schema_name, slug=schema_name.replace("_", "-"), schema_name=schema_name
    )
    started = time.perf_counter()
    school.save()
    return time.perf_counter() - started


def clone(fn, source, dest):
    connection.set_schema_to_public()
    started = time.perf_counter()
    sql(f"SELECT {fn}(%s, %s)", source, dest)
    return time.perf_counter() - started


# --- the structural comparison -------------------------------------------


def normalise(rows, schema):
    return sorted(r.replace(f"{schema}.", "").replace(f'"{schema}".', "") for r in rows)


def tables(schema):
    return normalise(
        [r[0] for r in sql(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s", schema)],
        schema,
    )


def columns(schema):
    return normalise(
        [
            f"{t}.{c}:{d}:{n}:{dflt}"
            for t, c, d, n, dflt in sql(
                """SELECT table_name, column_name, data_type, is_nullable,
                          COALESCE(column_default, '-')
                   FROM information_schema.columns WHERE table_schema = %s""",
                schema,
            )
        ],
        schema,
    )


def indexes(schema):
    return normalise(
        [f"{name}::{d}" for name, d in sql(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s", schema)],
        schema,
    )


def constraints(schema):
    return normalise(
        [
            f"{name}::{d}"
            for name, d in sql(
                """SELECT con.conname, pg_get_constraintdef(con.oid)
                   FROM pg_constraint con
                   JOIN pg_class c ON c.oid = con.conrelid
                   JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = %s""",
                schema,
            )
        ],
        schema,
    )


def compare(a, b):
    verdict = []
    for label, fn in (
        ("tables", tables),
        ("columns", columns),
        ("indexes", indexes),
        ("constraints", constraints),
    ):
        left, right = fn(a), fn(b)
        if left == right:
            verdict.append((label, len(left), "same", []))
        else:
            only_a = [x for x in left if x not in right]
            only_b = [x for x in right if x not in left]
            verdict.append((label, len(left), "DIFFERENT", (only_a, only_b)))
    return verdict


def main():
    print("Cleaning up any previous run...")
    drop_everything()

    for name in ("clone_schema.sql", "clone_schema_v2.sql"):
        with open(os.path.join(HERE, name)) as handle:
            sql(handle.read())
    print("clone_schema() and clone_schema_v2() installed.\n")

    print("=" * 72)
    print("BASELINE — CREATE SCHEMA + migrate_schemas, the path make_school() uses")
    print("=" * 72)
    baseline = []
    for name in BASELINE:
        taken = build_by_migrating(name)
        baseline.append(taken)
        print(f"  {name}: {taken:6.3f}s")
    print(f"  -> min {min(baseline):.3f}s  max {max(baseline):.3f}s  "
          f"mean {sum(baseline)/len(baseline):.3f}s")

    print("\nBuilding the template schema (paid once, by the same path)...")
    template_cost = build_by_migrating(TEMPLATE)
    print(f"  {TEMPLATE}: {template_cost:6.3f}s")

    results = {}
    for label, fn, names in (
        ("v1  LIKE INCLUDING ALL", "clone_schema", CLONES_V1),
        ("v2  names preserved", "clone_schema_v2", CLONES_V2),
    ):
        print("\n" + "=" * 72)
        print(f"CLONE {label} — five consecutive, from that template")
        print("=" * 72)
        taken = []
        for name in names:
            t = clone(fn, TEMPLATE, name)
            taken.append(t)
            print(f"  {name}: {t:6.3f}s")
        print(f"  -> min {min(taken):.3f}s  max {max(taken):.3f}s  "
              f"mean {sum(taken)/len(taken):.3f}s")
        results[label] = (taken, names[0])

    mean_base = sum(baseline) / len(baseline)

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    print(f"  baseline (migrate):        {mean_base:6.3f}s   "
          f"[the ~1.65s the CI comment cites]")

    overall_ok = True
    for label, (taken, first) in results.items():
        mean_clone = sum(taken) / len(taken)
        verdict = compare(TEMPLATE, first)
        same = all(state == "same" for _, _, state, _ in verdict)
        overall_ok = overall_ok and same
        print(f"\n  {label}")
        print(f"    time:      {mean_clone:6.3f}s   "
              f"({mean_base / mean_clone:.1f}x faster)")
        print(f"    break-even after "
              f"{template_cost / max(mean_base - mean_clone, 1e-9):.1f} tenants "
              f"(the suite builds ~1,479)")
        for name, count, state, diff in verdict:
            if state == "same":
                print(f"    {name:12} {count:5}  same")
            else:
                only_a, only_b = diff
                print(f"    {name:12} {count:5}  DIFFERENT "
                      f"({len(only_a)} missing, {len(only_b)} unexpected)")
                for item in only_a[:3]:
                    print(f"        migrated only: {item[:110]}")
                for item in only_b[:3]:
                    print(f"        cloned only:   {item[:110]}")
        print(f"    STRUCTURE: {'identical to a migrated schema' if same else 'DIFFERS — not a drop-in'}")

    print("\nCleaning up...")
    drop_everything()
    print("Done.")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
