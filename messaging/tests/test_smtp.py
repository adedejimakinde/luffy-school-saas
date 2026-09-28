"""`SmtpProvider`: a real email adapter behind the same seam `FakeProvider` fills.

Never selected by the test runner's own settings (`FakeProvider` still is, in
development and in the suite) — every test here builds and calls the class by
hand, against Django's `locmem` backend, which is what proves the adapter maps
an `Outbound` to an `EmailMessage` correctly without a real mail server.
"""

import smtplib
from dataclasses import dataclass
from unittest import mock

from django.core import mail
from django.test import SimpleTestCase, override_settings

from messaging import kinds
from messaging.providers import Accepted, NotConfigured, Outbound, Refused, Unavailable
from messaging.smtp import SmtpProvider


@dataclass(frozen=True)
class OutboundWithReplyTo:
    """Stands in for `providers.Outbound` once D16's field lands on it.

    A plain `Outbound` today has no `reply_to` — this repository builds it
    that way until the Reply-To PR merges — so `SmtpProvider.send()` reads it
    with `getattr(..., "")` rather than the attribute directly, and this
    fixture is what proves that read against a value once one exists.
    """

    channel_type: str
    address: str
    kind: str
    text: str = ""
    reference: str = ""
    reply_to: str = ""


OUTBOUND = OutboundWithReplyTo(
    channel_type="email",
    address="parent@example.com",
    kind=kinds.Kind.PAYMENT_RECEIPT,
    text="NGN 50,000 received by Cash for Ada Obi.",
    reference="notice-st_marys-1",
    reply_to="office@stmarys.example",
)

SMTP_SETTINGS = dict(
    EMAIL_HOST="smtp.example.com",
    EMAIL_PORT=587,
    EMAIL_HOST_USER="",
    EMAIL_HOST_PASSWORD="",
    EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False,
    EMAIL_TIMEOUT=10,
    DEFAULT_FROM_EMAIL="no-reply@classnode.example",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)


class NotConfiguredTests(SimpleTestCase):
    @override_settings(**{**SMTP_SETTINGS, "EMAIL_HOST": ""})
    def test_no_email_host_refuses_before_anything_is_sent(self):
        with self.assertRaises(NotConfigured):
            SmtpProvider().check_configured()

    @override_settings(**SMTP_SETTINGS)
    def test_a_configured_host_passes(self):
        self.assertIsNone(SmtpProvider().check_configured())

    @override_settings(**{**SMTP_SETTINGS, "EMAIL_HOST": ""})
    def test_send_refuses_too_rather_than_trusting_the_caller(self):
        with self.assertRaises(NotConfigured):
            SmtpProvider().send(OUTBOUND)


@override_settings(**SMTP_SETTINGS)
class SendingTests(SimpleTestCase):
    def setUp(self):
        mail.outbox = []

    def test_the_message_carries_the_subject_body_recipient_and_reply_to(self):
        result = SmtpProvider().send(OUTBOUND)

        self.assertIsInstance(result, Accepted)
        [message] = mail.outbox
        self.assertEqual(message.subject, kinds.subject(kinds.Kind.PAYMENT_RECEIPT))
        self.assertEqual(message.body, OUTBOUND.text)
        self.assertEqual(message.to, ["parent@example.com"])
        self.assertEqual(message.reply_to, ["office@stmarys.example"])
        self.assertEqual(message.from_email, "no-reply@classnode.example")

    def test_no_reply_to_means_no_reply_to_header(self):
        SmtpProvider().send(
            Outbound(
                channel_type="email", address="x@example.com", kind=kinds.Kind.SIGN_IN_CODE,
                text="Your code is 123456.",
            )
        )

        [message] = mail.outbox
        self.assertEqual(message.reply_to, [])


class RefusalTests(SimpleTestCase):
    @override_settings(**SMTP_SETTINGS)
    def test_a_refused_recipient_is_refused_not_unavailable(self):
        with mock.patch(
            "django.core.mail.message.EmailMessage.send",
            side_effect=smtplib.SMTPRecipientsRefused({"x@example.com": (550, b"no such user")}),
        ):
            with self.assertRaises(Refused):
                SmtpProvider().send(OUTBOUND)

    @override_settings(**SMTP_SETTINGS)
    def test_a_refused_connection_is_unavailable_not_refused(self):
        with mock.patch(
            "django.core.mail.message.EmailMessage.send",
            side_effect=ConnectionRefusedError("[Errno 111] Connection refused"),
        ):
            with self.assertRaises(Unavailable):
                SmtpProvider().send(OUTBOUND)

    @override_settings(**SMTP_SETTINGS)
    def test_an_smtp_protocol_failure_is_unavailable(self):
        with mock.patch(
            "django.core.mail.message.EmailMessage.send",
            side_effect=smtplib.SMTPServerDisconnected("connection lost"),
        ):
            with self.assertRaises(Unavailable):
                SmtpProvider().send(OUTBOUND)
