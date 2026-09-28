"""A real email provider, behind the same seam the fake stands in for. D2, D16.

**Plain SMTP, configured by environment variables — the same ones
`schools.delivery.EmailChannel` already reads** (`EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`,
`EMAIL_TIMEOUT`, `DEFAULT_FROM_EMAIL`), so a deploy configures its mail server
once rather than twice. `django.core.mail`'s own SMTP backend does the talking;
this class is the adapter that turns an `Outbound` into the `EmailMessage` it
sends and turns what SMTP says back into `Accepted`, `Refused` or `Unavailable`.

**Not the default anywhere.** `settings.MESSAGING_PROVIDERS["email"]` only
names this class when a deploy sets `MESSAGING_EMAIL_PROVIDER=messaging.smtp.SmtpProvider`
(`deploy/production.env`, commented, with the settings it needs beside it). In
development and in the test suite nothing points here — `FakeProvider` is
still what `DEBUG` and the test runner select — so this file is exercised by
its own unit tests, against `django.core.mail`'s `locmem` backend, and never by
the rest of the suite's fixtures.

**Two failures, D1's own distinction.** SMTP answers a bad recipient with a
`5xx` at the `RCPT TO` stage, which `smtplib` raises as
`SMTPRecipientsRefused` — permanent, the address's fault, `Refused`. A refused
connection, a timeout, an authentication failure, or any other `SMTPException`
or `OSError` is the server's problem, not the address's — `Unavailable`, the
same as an unreachable staff-invitation mailbox is in `schools.delivery`.
"""

import smtplib

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

from . import kinds
from .providers import Accepted, NotConfigured, Refused, Unavailable


class SmtpProvider:
    """The `email` half of `MESSAGING_PROVIDERS`, for a deploy with a real mail server."""

    def check_configured(self):
        """Refuse to send when this deploy has nowhere to send to.

        Read here rather than trusted from `EMAIL_BACKEND`, for the reason
        `schools.delivery.EmailChannel.check_configured()` gives: Django's own
        SMTP defaults are `localhost:25`, which answers nothing on any host
        this runs on, and a deploy that names this class but never sets
        `EMAIL_HOST` should be told so up front rather than fail mid-send.
        """
        if not getattr(settings, "EMAIL_HOST", ""):
            raise NotConfigured(
                "No EMAIL_HOST is configured for this deploy, so the SMTP "
                "message provider has nowhere to send. Set EMAIL_HOST (and "
                "its credentials), or select a different email provider."
            )

    def _connection(self):
        # A connection of its own, opened and closed with the send, rather
        # than the process-wide default `django.core.mail.send_mail()` uses:
        # this runs inside a Celery worker's task, off the request, and a
        # long-lived SMTP connection idling between jobs is one more thing
        # that can go stale and fail the *next* unrelated send.
        #
        # No explicit `backend=`: `get_connection()` without one reads
        # `settings.EMAIL_BACKEND`, which defaults to Django's own SMTP
        # backend (`settings.py`'s `DEFAULT_EMAIL_BACKEND`) — the same
        # setting `schools.delivery.EmailChannel` leaves alone for the same
        # reason. Naming the class here would be a second place that default
        # lives, and would stop a test from substituting `locmem`.
        return get_connection(
            host=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            username=settings.EMAIL_HOST_USER,
            password=settings.EMAIL_HOST_PASSWORD,
            use_tls=settings.EMAIL_USE_TLS,
            use_ssl=settings.EMAIL_USE_SSL,
            timeout=settings.EMAIL_TIMEOUT,
        )

    def send(self, outbound) -> Accepted:
        self.check_configured()
        # `getattr(..., "")`, not `outbound.reply_to`: `docs/messaging.md` D16
        # added the field, and this provider has to keep working for a deploy
        # running the version of `Outbound` from before it landed.
        reply_to = getattr(outbound, "reply_to", "")
        message = EmailMessage(
            subject=kinds.subject(outbound.kind),
            body=outbound.text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[outbound.address],
            reply_to=[reply_to] if reply_to else None,
            connection=self._connection(),
        )
        try:
            message.send(fail_silently=False)
        except smtplib.SMTPRecipientsRefused as exc:
            raise Refused(f"The mail server refuses {outbound.address}.") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise Unavailable("The SMTP server could not be reached or failed.") from exc
        return Accepted()


__all__ = ["SmtpProvider"]
