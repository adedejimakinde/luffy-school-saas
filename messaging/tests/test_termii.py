"""`TermiiProvider`: a real SMS adapter behind the seam `FakeProvider` fills.

Every test replaces `urllib.request.urlopen`; nothing here touches a network,
and `FakeProvider` is still what the suite's own settings select (the last
test holds that). The error replies are **assumed shapes**, not captured from
Termii — see the module's docstring — so they pin the mapping, not Termii.
"""

import io
import json
import urllib.error
from unittest import mock

from django.conf import settings
from django.utils.module_loading import import_string
from django.test import SimpleTestCase, override_settings

from messaging.fake import FakeProvider
from messaging.providers import (
    Accepted,
    NotConfigured,
    Outbound,
    Refused,
    Unavailable,
    provider_for,
)
from messaging.termii import TermiiProvider

KEY = "TL-secret-key-123"
OUTBOUND = Outbound(
    channel_type="phone",
    address="+2348031234567",
    kind="sign_in_code",
    text="Your code is 123456",
)

CONFIGURED = override_settings(
    TERMII_API_KEY=KEY,
    TERMII_SENDER_ID="StMarys",
    TERMII_BASE_URL="https://api.ng.termii.com",
    TERMII_TIMEOUT=7,
)

URLOPEN = "messaging.termii.urllib.request.urlopen"


class Reply:
    """What `urlopen` returns on a 2xx: a context manager with `status` and `read()`."""

    def __init__(self, status, body):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def http_error(status, body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return urllib.error.HTTPError("https://x/api/sms/send", status, "err", {}, io.BytesIO(raw))


def ok():
    return Reply(
        200,
        {"code": "ok", "message_id": "MSG-1", "message": "Successfully Sent", "balance": 40, "user": "u"},
    )


@CONFIGURED
class TheRequestTests(SimpleTestCase):
    def sent(self, outbound=OUTBOUND):
        with mock.patch(URLOPEN, return_value=ok()) as urlopen:
            answer = TermiiProvider().send(outbound)
        (request,), kwargs = urlopen.call_args
        return answer, request, kwargs

    def test_it_posts_to_the_sms_endpoint_on_the_dnd_route(self):
        _, request, kwargs = self.sent()

        self.assertEqual(request.full_url, "https://api.ng.termii.com/api/sms/send")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data)
        self.assertEqual(body["channel"], "dnd")
        self.assertEqual(body["type"], "plain")
        self.assertEqual(body["from"], "StMarys")
        self.assertEqual(body["api_key"], KEY)
        self.assertEqual(body["sms"], "Your code is 123456")
        self.assertEqual(kwargs["timeout"], 7)

    def test_the_number_goes_without_its_plus(self):
        _, request, _ = self.sent()
        self.assertEqual(json.loads(request.data)["to"], "2348031234567")

    def test_the_provider_reference_is_termiis_message_id(self):
        answer, _, _ = self.sent()
        self.assertEqual(answer, Accepted(provider_ref="MSG-1"))

    @override_settings(TERMII_BASE_URL="https://api.example.termii.test/")
    def test_the_base_url_is_configurable_and_a_trailing_slash_is_harmless(self):
        _, request, _ = self.sent()
        self.assertEqual(request.full_url, "https://api.example.termii.test/api/sms/send")

    def test_an_email_outbound_is_a_bug_and_says_so(self):
        email = Outbound(channel_type="email", address="a@b.example", kind="x", text="t")
        with mock.patch(URLOPEN) as urlopen, self.assertRaises(ValueError):
            TermiiProvider().send(email)
        urlopen.assert_not_called()


@CONFIGURED
class TheFailureTests(SimpleTestCase):
    def outcome(self, *, returns=None, raises=None):
        with mock.patch(URLOPEN, return_value=returns, side_effect=raises):
            try:
                TermiiProvider().send(OUTBOUND)
            except (Refused, Unavailable) as exc:
                return exc
        self.fail("the send was accepted")

    def test_a_refused_sender_id_is_the_operators_not_the_numbers(self):
        for message in ("Invalid sender ID", "ApplicationSenderId not found", "Sender ID not whitelisted for DND"):
            with self.subTest(message=message):
                exc = self.outcome(raises=http_error(400, {"code": "error", "message": message}))
                self.assertIsInstance(exc, Unavailable)
                self.assertIn("sender ID", str(exc))

    def test_a_sender_id_complaint_mentioning_a_number_is_still_a_sender_id(self):
        exc = self.outcome(raises=http_error(400, {"message": "Sender ID not allowed for this phone number"}))
        self.assertIsInstance(exc, Unavailable)

    def test_an_invalid_destination_is_refused(self):
        exc = self.outcome(raises=http_error(400, {"message": "Invalid phone number"}))
        self.assertIsInstance(exc, Refused)

    def test_a_bad_api_key_is_unavailable(self):
        for status in (401, 403):
            with self.subTest(status=status):
                exc = self.outcome(raises=http_error(status, {"message": "Invalid API key"}))
                self.assertIsInstance(exc, Unavailable)

    def test_an_empty_wallet_is_unavailable(self):
        exc = self.outcome(raises=http_error(400, {"message": "Insufficient balance"}))
        self.assertIsInstance(exc, Unavailable)

    def test_a_5xx_and_a_429_are_unavailable(self):
        for status in (429, 500, 502, 503):
            with self.subTest(status=status):
                exc = self.outcome(raises=http_error(status, b"<html>oops</html>"))
                self.assertIsInstance(exc, Unavailable)

    def test_an_unrecognised_4xx_is_unavailable_never_the_familys_fault(self):
        exc = self.outcome(raises=http_error(422, {"message": "Something new"}))
        self.assertIsInstance(exc, Unavailable)

    def test_no_route_to_termii_is_unavailable(self):
        for raises in (
            urllib.error.URLError("dns failure"),
            TimeoutError("timed out"),
            ConnectionResetError(),
        ):
            with self.subTest(raises=type(raises).__name__):
                self.assertIsInstance(self.outcome(raises=raises), Unavailable)

    def test_a_200_that_is_not_an_accepted_message_is_not_accepted(self):
        for body in (b"", b"not json", b"[]", {"code": "ok"}, {"code": "error", "message_id": "x"}, {"message": "hi"}):
            with self.subTest(body=body):
                exc = self.outcome(returns=Reply(200, body))
                self.assertIsInstance(exc, Unavailable)

    def test_the_api_key_and_the_number_are_never_in_a_failure(self):
        cases = (
            http_error(400, {"message": f"bad key {KEY}"}),
            http_error(500, KEY.encode()),
            urllib.error.URLError(f"https://x/?api_key={KEY}"),
        )
        for raises in cases:
            with self.subTest(raises=repr(raises)):
                exc = self.outcome(raises=raises)
                self.assertNotIn(KEY, str(exc))
                self.assertNotIn("2348031234567", str(exc))
                self.assertIsNone(exc.__cause__)


class TheConfigurationTests(SimpleTestCase):
    @override_settings(TERMII_API_KEY="", TERMII_SENDER_ID="StMarys")
    def test_no_api_key_is_not_configured(self):
        with self.assertRaisesMessage(NotConfigured, "TERMII_API_KEY"):
            TermiiProvider().check_configured()

    @override_settings(TERMII_API_KEY=KEY, TERMII_SENDER_ID="")
    def test_no_sender_id_is_not_configured(self):
        with self.assertRaisesMessage(NotConfigured, "TERMII_SENDER_ID"):
            TermiiProvider().check_configured()

    @override_settings(TERMII_API_KEY="", TERMII_SENDER_ID="")
    def test_send_refuses_before_any_request_when_not_configured(self):
        with mock.patch(URLOPEN) as urlopen, self.assertRaises(NotConfigured):
            TermiiProvider().send(OUTBOUND)
        urlopen.assert_not_called()

    @override_settings(TERMII_API_KEY=KEY, TERMII_SENDER_ID="S", TERMII_BASE_URL="http://insecure.example")
    def test_an_http_base_url_is_refused_so_the_key_never_travels_in_the_clear(self):
        with self.assertRaisesMessage(NotConfigured, "https"):
            TermiiProvider().check_configured()

    @override_settings(MESSAGING_PROVIDERS={"phone": "messaging.termii.TermiiProvider"})
    def test_it_is_selected_by_naming_it_in_the_phone_slot(self):
        self.assertIsInstance(provider_for("phone"), TermiiProvider)

    def test_it_is_never_a_default_and_the_fake_stays_the_development_one(self):
        """Nothing names Termii unless a deploy sets MESSAGING_PHONE_PROVIDER;
        `settings.py` still falls back to the fake only under DEBUG, and to
        nothing (a refusal, `messaging.E001`'s point) otherwise."""
        self.assertNotIn("termii", settings.MESSAGING_PROVIDERS["phone"].lower())
        self.assertIn(
            settings.MESSAGING_PROVIDERS["phone"],
            ("", "messaging.fake.FakeProvider"),
        )
        self.assertIsInstance(
            import_string("messaging.fake.FakeProvider")(), FakeProvider
        )
