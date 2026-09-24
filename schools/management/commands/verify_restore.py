"""`manage.py verify_restore` — is the database this points at a whole Classnode?

Run by `deploy/restore-check.sh` against the database it just recovered from
B2 (POSTGRES_HOST=restore-db). Exits non-zero, naming every problem, when the
answer is no. Reports to Sentry's cron monitor `restore-check` when Sentry is
configured, so a restore test that fails *or stops running* raises an alert.
"""

from django.core.management.base import BaseCommand, CommandError

from schools.restore_check import check

MONITOR = "restore-check"


def _check_in(ok):
    try:
        from sentry_sdk.crons import capture_checkin
        from sentry_sdk.crons.consts import MonitorStatus
    except ImportError:  # pragma: no cover — sentry-sdk is a requirement
        return
    capture_checkin(monitor_slug=MONITOR, status=MonitorStatus.OK if ok else MonitorStatus.ERROR)


class Command(BaseCommand):
    help = "Check that a (restored) database has every school's schema and every migration."

    def handle(self, *args, **options):
        verdict = check()
        _check_in(verdict.ok)
        if not verdict.ok:
            raise CommandError(
                "The restore is not whole:\n" + "\n".join(f"  - {p}" for p in verdict.problems)
            )
        self.stdout.write(
            f"The restore is whole: {verdict.schools} schools, every schema present, "
            f"every migration recorded."
        )
