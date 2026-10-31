"""Telling the people who run the platform that something needs them.

Sentry is not set up yet (decided 31 October 2026), so an operational alert,
the disk filling up or a media backup that failed, is:

1. **printed**, so it is in the cron job's log under /var/log/classnode-*.log;
2. **emailed to `settings.OPS_ALERT_EMAIL`** (hello@classnode.co), through the
   same email settings every other email uses (`EMAIL_HOST`...), from
   `DEFAULT_FROM_EMAIL`;
3. and, **only if a heartbeat URL is given**, checked in there as `error`, so a
   Sentry cron monitor can be pointed at it later without changing this code.

An email that cannot be sent is printed too, and the caller is told: a failed
alert must never look like a quiet night.
"""

import logging
import sys
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def heartbeat(url: str, status: str):
    """A Sentry-style cron check-in (`?status=ok|error`). Never raises."""
    if not url:
        return
    try:
        urllib.request.urlopen(f"{url}?status={status}", timeout=10).close()
    except Exception:  # noqa: BLE001 — a heartbeat that fails is not the alert
        logger.warning("The heartbeat at %s could not be reached.", url.split("?")[0])


def send(subject: str, body: str, *, heartbeat_url: str = "", out=None) -> bool:
    """Print and email one alert. True when the email went."""
    out = out or sys.stdout
    subject = f"[Classnode] {subject}"
    out.write(f"ALERT: {subject}\n{body}\n")
    out.flush()
    heartbeat(heartbeat_url, "error")
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [settings.OPS_ALERT_EMAIL], fail_silently=False)
    except Exception as exc:  # noqa: BLE001 — said out loud below, never swallowed
        out.write(f"ALERT NOT EMAILED to {settings.OPS_ALERT_EMAIL}: {exc}\n")
        logger.exception("An operational alert could not be emailed.")
        return False
    out.write(f"Emailed to {settings.OPS_ALERT_EMAIL}.\n")
    return True


__all__ = ["heartbeat", "send"]
