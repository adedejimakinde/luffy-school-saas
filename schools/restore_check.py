"""Could Classnode run on this database? The question the weekly restore asks.

`deploy/restore-check.sh` recovers the latest backup from B2 into a throwaway
Postgres and points `manage.py verify_restore` at it. A backup nobody has
restored is a hope, and "the restore succeeded" only means Postgres started:
it says nothing about whether every school came back. So this asks, of the
restored database, the things the application itself depends on:

1. **Every school has its schema.** `School` rows live in `public` and their
   schemas beside it; a restore that brought back the row and not the schema is
   a school whose every page is a `ProgrammingError`.
2. **`public` has every shared app's latest migration** — the tables every
   request reads before it knows which school it is for.
3. **Every school's schema has every tenant app's latest migration.** A schema
   that stopped part-way through `migrate_schemas` is a school the code no
   longer matches.

4. **One school's rows came back.** Every table in that school's schema is
   counted. Given the counts the live database had just before the restore began
   (`expected`), a table that came back short is named; the drill does not trust
   "Postgres started" to mean "the data is there". Which school: the one asked
   for, else the first by slug. A table may be short by `tolerance()` rows —
   writes in the last minute before the restore had not been archived yet — and
   by nothing more.

Leaf migrations only: a leaf that is recorded implies its ancestors were.
"""

from typing import Dict, List, NamedTuple, Optional

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from schools.models import School


class Verdict(NamedTuple):
    schools: int
    problems: List[str]
    #: The school whose rows were counted, and how many each table held. Empty
    #: when there is no school to count.
    counted: str = ""
    counts: Optional[Dict[str, int]] = None

    @property
    def ok(self) -> bool:
        return not self.problems


def _labels(app_names):
    """App labels for the dotted names in `SHARED_APPS` / `TENANT_APPS`."""
    by_name = {config.name: config.label for config in apps.get_app_configs()}
    return {by_name[name] for name in app_names if name in by_name}


def _leaves(labels):
    graph = MigrationLoader(None, ignore_no_migrations=True).graph
    return {(app, name) for app, name in graph.leaf_nodes() if app in labels}


def _schemas():
    with connection.cursor() as cursor:
        cursor.execute("SELECT nspname FROM pg_namespace")
        return {row[0] for row in cursor.fetchall()}


def _recorded(schema):
    # The schema name comes from `pg_namespace` membership checked by the
    # caller, and is quoted as an identifier: never a value typed by anybody.
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT app, name FROM "{schema}".django_migrations')
        return set(cursor.fetchall())


def tolerance(expected: int) -> int:
    """How many rows a restored table may be short of the live one: the last
    minute's writes (`archive_timeout`) were not yet in the archive, and a busy
    table's share of that is a percent, an idle one's a handful."""
    return max(10, expected // 100)


def school_counts(schema: str) -> Dict[str, int]:
    """Rows in every table of one school's schema, by table name."""
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY 1", [schema])
        tables = [row[0] for row in cursor.fetchall()]
        counts = {}
        for table in tables:
            cursor.execute(f"SELECT count(*) FROM {quote(schema)}.{quote(table)}")
            counts[table] = cursor.fetchone()[0]
    return counts


def pick_school(slug: str = "") -> Optional[School]:
    """The school to count: the one named, else the first by slug."""
    schools = School.objects.exclude(schema_name="public").order_by("slug")
    if slug:
        return schools.filter(slug=slug).first()
    return schools.first()


def _compare(school, counts, expected):
    problems = []
    for table, was in sorted(expected.items()):
        if table not in counts:
            problems.append(f"{school.name} ({school.schema_name}) has no table {table}")
        elif counts[table] < was - tolerance(was):
            problems.append(
                f"{school.name} ({school.schema_name}) {table} has {counts[table]} rows "
                f"after the restore; the live database had {was}"
            )
    return problems


def check(slug: str = "", expected: Optional[Dict[str, int]] = None) -> Verdict:
    connection.set_schema_to_public()
    problems = []
    present = _schemas()

    for app, name in sorted(_leaves(_labels(settings.SHARED_APPS)) - _recorded("public")):
        problems.append(f"public is missing migration {app}.{name}")

    tenant_leaves = _leaves(_labels(settings.TENANT_APPS))
    schools = list(School.objects.exclude(schema_name="public").order_by("schema_name"))
    for school in schools:
        if school.schema_name not in present:
            problems.append(f"{school.name} ({school.schema_name}) has no schema")
            continue
        for app, name in sorted(tenant_leaves - _recorded(school.schema_name)):
            problems.append(f"{school.name} ({school.schema_name}) is missing migration {app}.{name}")

    counted, counts = "", None
    chosen = pick_school(slug)
    if slug and chosen is None:
        problems.append(f"there is no school {slug!r} to count")
    elif chosen is not None and chosen.schema_name in present:
        counted, counts = chosen.slug, school_counts(chosen.schema_name)
        problems.extend(_compare(chosen, counts, expected or {}))

    return Verdict(schools=len(schools), problems=problems, counted=counted, counts=counts)


__all__ = ["Verdict", "check", "pick_school", "school_counts", "tolerance"]
