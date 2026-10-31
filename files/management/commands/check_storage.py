"""`manage.py check_storage`: the hourly look at the files and the disk.

Run from `deploy/cron/classnode` every hour. For every school (and the
platform's own blog) it tidies the uploads (`files.service.sweep`: gives up
on one stuck in the queue, forgets old failures, removes replaced crests
after their day), then looks at the disk the files are on.

- **Always** prints one line: how full the disk is and how much the schools
  keep. That line is the cron log's record that the check ran.
- **Past `FILES_DISK_WARN_PERCENT` (70%)** it sends an alert: printed and
  emailed to OPS_ALERT_EMAIL (`schools.alerts`), with the schools using the
  most, at most once a day so an hourly job does not fill an inbox. Past
  `FILES_DISK_REFUSE_PERCENT` (90%), where uploads are already refused, it
  alerts every hour.
- **A school at 90% of its quota** is named in that email too, and in the line.
- **`DISK_HEARTBEAT_URL`**, if set, gets an `ok` or `error` check-in, for a
  Sentry cron monitor later. Optional; nothing needs it.

Exits 1 when the disk is past the warning line, so the run is marked failed.
"""

import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from files import service, storage
from schools import alerts
from schools.models import School

DAY = 24 * 60 * 60


def _mb(n):
    return f"{n / 1024 ** 2:,.0f} MB"


def school_usage():
    """`[(school, usage dict, quota)]` for every customer school, and the blog's usage."""
    rows = []
    for school in School.objects.exclude(schema_name="public").order_by("name"):
        with schema_context(school.schema_name):
            rows.append((school, service.usage(), service.quota_for(school)))
    with schema_context("public"):
        blog = service.usage()
    return rows, blog


class Command(BaseCommand):
    help = "Tidy uploads, check the disk the files are on, and alert by email past 70%."

    def add_arguments(self, parser):
        parser.add_argument("--no-sweep", action="store_true", help="Only look; change nothing.")

    def _sweep(self):
        swept = {"gave_up": 0, "forgotten": 0, "removed": 0}
        for schema in ["public", *School.objects.exclude(schema_name="public").values_list("schema_name", flat=True)]:
            with schema_context(schema):
                for key, n in service.sweep().items():
                    swept[key] += n
        return swept

    def _due(self, marker, every):
        try:
            return time.time() - os.path.getmtime(marker) >= every
        except FileNotFoundError:
            return True

    def handle(self, *args, **options):
        swept = None if options["no_sweep"] else self._sweep()
        used, total = storage.disk_usage()
        percent = 100.0 * used / total if total else 0.0
        rows, blog = school_usage()
        kept = sum(u["bytes"] for _, u, _ in rows) + blog["bytes"]
        near_quota = [(s, u, q) for s, u, q in rows if q and u["bytes"] >= 0.9 * q]

        line = (
            f"check_storage: disk {percent:.1f}% used ({_mb(used)} of {_mb(total)}); "
            f"{len(rows)} schools keep {_mb(kept)} of files"
        )
        if swept:
            line += f"; swept {swept['gave_up']} stuck, {swept['forgotten']} failed, {swept['removed']} replaced"
        if near_quota:
            line += "; near their quota: " + ", ".join(s.slug for s, _, _ in near_quota)
        self.stdout.write(line)

        heartbeat_url = os.environ.get("DISK_HEARTBEAT_URL", "")
        if percent < settings.FILES_DISK_WARN_PERCENT:
            alerts.heartbeat(heartbeat_url, "ok")
            return

        marker = storage.root() / ".disk-alert-sent"
        refusing = percent >= settings.FILES_DISK_REFUSE_PERCENT
        if refusing or self._due(marker, DAY):
            top = sorted(rows, key=lambda r: r[1]["bytes"], reverse=True)[:10]
            body = "\n".join([
                f"The server's disk is {percent:.1f}% full ({_mb(used)} of {_mb(total)}).",
                (f"Uploads are REFUSED above {settings.FILES_DISK_REFUSE_PERCENT:.0f}%, and they are being refused now."
                 if refusing else
                 f"Uploads will be refused above {settings.FILES_DISK_REFUSE_PERCENT:.0f}%."),
                "",
                "docs/school-sites.md §9.1 says what to do: move the files to B2 object storage, or grow the disk.",
                "",
                "The schools keeping the most:",
                *[f"  {s.name} ({s.slug}): {_mb(u['bytes'])} in {u['files']} files, quota {_mb(q)}" for s, u, q in top],
                f"  Classnode's blog: {_mb(blog['bytes'])}",
                "",
                *([f"Near their quota: {', '.join(s.name for s, _, _ in near_quota)}"] if near_quota else []),
            ])
            emailed = alerts.send(f"Disk {percent:.0f}% full", body, heartbeat_url=heartbeat_url, out=self.stdout)
            if emailed:
                marker.touch()
        else:
            alerts.heartbeat(heartbeat_url, "error")
            self.stdout.write("Disk alert already emailed in the last day; not sent again.")
        raise CommandError(f"The disk is {percent:.1f}% full, past {settings.FILES_DISK_WARN_PERCENT:.0f}%.")
