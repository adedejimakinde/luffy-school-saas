"""Close every school's attempts whose time is over, stamped when each was due.

`cbt.jobs.close_overdue()`. Safe to run as often as anyone likes: an attempt is closed
once. Meant for the server's cron every few minutes (`docs/cbt.md`, step 5 "Built").
"""

from django.core.management.base import BaseCommand

from cbt.jobs import close_overdue


class Command(BaseCommand):
    help = "Close the CBT attempts whose time and late window are over, at every school."

    def handle(self, *args, **options):
        closed = close_overdue()
        self.stdout.write(f"Closed {closed} attempt{'s' if closed != 1 else ''}.")
