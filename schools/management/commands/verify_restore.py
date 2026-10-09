"""`manage.py verify_restore` — is the database this points at a whole Classnode?

Run by `deploy/restore-check.sh` against the database it just recovered from
B2 (POSTGRES_HOST=restore-db). Exits non-zero, naming every problem, when the
answer is no. Reports to Sentry's cron monitor `restore-check` when Sentry is
configured, so a restore test that fails *or stops running* raises an alert.

Two uses, both by that script:

* `--print-counts`, against the **live** database before the restore starts:
  prints one line of JSON, the school and every table's row count. It checks
  nothing and reports nothing.
* `--expect-counts '<that line>'`, against the **restored** database: the usual
  checks, and that school's tables hold what the live database held, within
  `schools.restore_check.tolerance`.

Without `--expect-counts` the row counts are printed and not compared.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from schools.restore_check import check, pick_school, school_counts

MONITOR = "restore-check"


def _check_in(ok):
    try:
        from sentry_sdk.crons import capture_checkin
        from sentry_sdk.crons.consts import MonitorStatus
    except ImportError:  # pragma: no cover — sentry-sdk is a requirement
        return
    capture_checkin(monitor_slug=MONITOR, status=MonitorStatus.OK if ok else MonitorStatus.ERROR)


class Command(BaseCommand):
    help = (
        "Check that a (restored) database has every school's schema, every migration, "
        "and one school's rows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--school", default="", help="Slug of the school to count (default: the first).")
        parser.add_argument(
            "--print-counts",
            action="store_true",
            help="Print the school's row counts as one line of JSON and stop (run on the live database).",
        )
        parser.add_argument(
            "--expect-counts",
            default="",
            help="The line --print-counts printed; the restored school must hold those rows.",
        )

    def handle(self, *args, school, print_counts, expect_counts, **options):
        if print_counts:
            return self.print_counts(school)

        expected = {}
        if expect_counts:
            try:
                wanted = json.loads(expect_counts)
                school = wanted["school"] or school
                expected = wanted["counts"] or {}
            except (ValueError, KeyError, TypeError) as error:
                raise CommandError(f"--expect-counts is not what --print-counts prints: {error!r}")

        verdict = check(slug=school, expected=expected)
        _check_in(verdict.ok)
        if not verdict.ok:
            raise CommandError(
                "The restore is not whole:\n" + "\n".join(f"  - {p}" for p in verdict.problems)
            )
        self.stdout.write(
            f"The restore is whole: {verdict.schools} schools, every schema present, "
            f"every migration recorded."
        )
        if verdict.counts is None:
            self.stdout.write("No school to count rows for.")
        else:
            held = sum(verdict.counts.values())
            compared = "matching the live database" if expected else "not compared"
            self.stdout.write(
                f"{verdict.counted}: {held} rows in {len(verdict.counts)} tables, {compared}. "
                + ", ".join(f"{t}={n}" for t, n in verdict.counts.items() if n)
            )

    def print_counts(self, slug):
        chosen = pick_school(slug)
        if chosen is None:
            if slug:
                raise CommandError(f"there is no school {slug!r} to count")
            self.stdout.write(json.dumps({"school": "", "counts": {}}))
            return
        self.stdout.write(json.dumps({"school": chosen.slug, "counts": school_counts(chosen.schema_name)}))
