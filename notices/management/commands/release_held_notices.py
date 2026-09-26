"""Queue every school's held notices whose time has come. Run by the server's cron.

`deploy/cron/classnode` runs this at 07:00 Lagos time and every quarter hour
through the day after, so a missed run is caught up. Safe to run as often as
anyone likes: every send is claimed before it goes (`notices.tasks`).
"""

from django.core.management.base import BaseCommand

from notices.tasks import release_held


class Command(BaseCommand):
    help = "Queue the held notices whose time has come, at every school."

    def handle(self, *args, **options):
        queued = release_held()
        self.stdout.write(f"Queued {queued} held notice{'s' if queued != 1 else ''}.")
