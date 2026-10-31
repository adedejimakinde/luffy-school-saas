"""`manage.py send_ops_alert "<subject>" < body.txt`

Prints the alert and emails it to OPS_ALERT_EMAIL (`schools.alerts`). Used by
scripts that run outside Django, such as the nightly media backup
(`deploy/media-backup.sh`), so every alert takes the one path. Exits 1 when
the email could not be sent, so the calling script can say so in its log.
"""

import sys

from django.core.management.base import BaseCommand, CommandError

from schools import alerts


class Command(BaseCommand):
    help = "Print an operational alert and email it to OPS_ALERT_EMAIL. The body is read from stdin."

    def add_arguments(self, parser):
        parser.add_argument("subject")
        parser.add_argument("--heartbeat-url", default="")

    def handle(self, *args, **options):
        body = sys.stdin.read() if not sys.stdin.isatty() else ""
        if not alerts.send(options["subject"], body.strip() or "(no details)",
                           heartbeat_url=options["heartbeat_url"], out=self.stdout):
            raise CommandError("The alert was printed but could not be emailed.")
