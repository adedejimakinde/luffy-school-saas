"""Send each school's daily money summary. Run by the server's cron.

`deploy/cron/classnode` runs this once a day, shortly after Lagos midnight, to
summarise the day that just ended. Safe to run more than once: a school's
digest for a day already sent is skipped (`notices.models.MoneySummarySent`).
"""

from django.core.management.base import BaseCommand

from notices.daily_summary import send_summaries


class Command(BaseCommand):
    help = "Send each school's daily money summary for the day that just ended."

    def handle(self, *args, **options):
        sent = send_summaries()
        self.stdout.write(f"Sent {sent} daily money summar{'y' if sent == 1 else 'ies'}.")
