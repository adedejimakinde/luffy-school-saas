"""Code delivery's machinery: queued after the commit, sealed, sent once. `docs/messaging.md`.

Two schools in every test that touches a school: a code a school asks for is
counted against it, names it, and is shown only to it.
"""

import json
import logging
from datetime import timedelta
from unittest import mock

from django.core.checks import Error, Warning
from django.db import connection, transaction
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts import guardian_contacts
from accounts.models import ContactChannel, GuardianContactCode
from accounts.tests.test_guardian_contacts import TwoSchools
from messaging import checks, codes, kinds
from messaging.models import (
    CodeDelivery,
    CodeDeliveryOutcome,
    DeliveriesAreAppendOnly,
    FakeMessage,
    Outcome,
)
from messaging.seal import open_sealed, seal
from messaging.tests.fake import BOTH_FAKE, FAKE, SendsThroughTheFake
from messaging.views import outbox
from tests.refusals import RefusalAssertions

MARYS_PHONE = "+2348031234567"
GRACE_PHONE = "+2348051234567"


class CodeSetUp(SendsThroughTheFake, TwoSchools):
    """A St Mary's parent and a Grace parent, each with a phone their school typed."""

    def setUp(self):
        super().setUp()
        self.ours = self.record(self.marys_admin, self.parent, ContactChannel.PHONE, MARYS_PHONE)
        self.theirs = self.record(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, GRACE_PHONE
        )

    def check_ours(self):
        return guardian_contacts.request_verification_as(
            self.marys_admin, self.ours, school=self.st_marys
        )

    def check_theirs(self):
        return guardian_contacts.request_verification_as(
            self.grace_admin, self.theirs, school=self.grace
        )

    def outcome_of(self, code):
        return CodeDeliveryOutcome.objects.get(delivery__code=code).outcome


class AfterTheCommitAndSealedTests(CodeSetUp):
    def test_nothing_is_queued_before_the_door_commits(self):
        """A worker is another connection: a message published inside the
        transaction can be picked up before the code row exists.

        CONTROL: calling `_publish()` directly in `deliver_code()` instead of
        registering it on commit turns the first assertion red.
        """
        with mock.patch("messaging.codes.send_code.apply_async") as publish:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.check_ours()
                self.check_theirs()
            self.assertFalse(publish.called, "a send was queued before the commit")
            for callback in callbacks:
                callback()
        self.assertEqual(publish.call_count, 2)

    def test_the_code_crosses_the_queue_sealed(self):
        """The broker message never carries the code in the clear. D6.

        CONTROL: passing `raw_code` instead of `seal(raw_code)` to the queue in
        `deliver_code()` turns this red on the first assertion.
        """
        (code, raw), jobs = self.queued(self.check_ours)

        self.assertEqual(len(jobs), 1)
        self.assertNotIn(raw, json.dumps(jobs[0]))
        self.assertEqual(jobs[0][:2], [code.pk, kinds.Kind.CHANNEL_CHECK])
        lifetime = int((code.expires_at - code.created_at).total_seconds())
        self.assertEqual(open_sealed(jobs[0][2], ttl_seconds=lifetime), raw)

    def test_each_school_is_named_in_its_own_code(self):
        (ours, raw_ours) = self.deliver(self.check_ours)
        (theirs, raw_theirs) = self.deliver(self.check_theirs)

        [to_ours] = self.sent_to(MARYS_PHONE)
        [to_theirs] = self.sent_to(GRACE_PHONE)
        self.assertIn(raw_ours, to_ours.text)
        self.assertIn("St Mary's", to_ours.text)
        self.assertNotIn("Grace", to_ours.text)
        self.assertIn(raw_theirs, to_theirs.text)
        self.assertIn("Grace Academy", to_theirs.text)
        self.assertNotIn("St Mary", to_theirs.text)
        self.assertEqual(self.outcome_of(ours), Outcome.ACCEPTED)
        self.assertEqual(self.outcome_of(theirs), Outcome.ACCEPTED)

    def test_no_code_is_named_after_a_child(self):
        """A school can type a number wrong. The stranger holding it learns no name."""
        self.deliver(self.check_ours)
        [message] = self.sent_to(MARYS_PHONE)
        self.assertNotIn(self.child_at_marys.user.full_name, message.text)


class AtMostOnceTests(CodeSetUp):
    def test_a_send_run_twice_sends_once(self):
        """`acks_late` can run a task twice; a second SMS would reach a parent twice. D5.

        CONTROL: making `_claim()` return the existing claim instead of None on
        the IntegrityError lets the second run send, and this goes red.
        """
        _, jobs = self.queued(self.check_ours)
        codes.send_code(*jobs[0])
        codes.send_code(*jobs[0])

        self.assertEqual(len(self.sent_to(MARYS_PHONE)), 1)
        self.assertEqual(CodeDelivery.objects.count(), 1)

    def test_a_claim_with_no_outcome_is_never_resent_and_reads_not_known(self):
        """A worker that died between the claim and the provider's answer. D5."""
        (code, _), jobs = self.queued(self.check_ours)
        CodeDelivery.objects.create(code=code, kind=jobs[0][1], channel_type="phone")

        codes.send_code(*jobs[0])

        self.assertEqual(self.sent_to(MARYS_PHONE), [])
        self.assertEqual(codes.last_message(self.ours, self.st_marys.pk), codes.NOT_KNOWN)


class WhatTheProviderSaidTests(CodeSetUp, RefusalAssertions):
    def test_an_expired_code_is_not_sent(self):
        (code, _), jobs = self.queued(self.check_ours)
        GuardianContactCode.objects.filter(pk=code.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        codes.send_code(*jobs[0])

        self.assertEqual(self.sent_to(MARYS_PHONE), [])
        self.assertEqual(self.outcome_of(code), Outcome.EXPIRED)

    def test_a_refused_address_is_said_to_the_school_that_sent_it(self):
        """D12's first half: the office learns the number is not reachable."""
        dead = self.record(
            self.grace_admin, self.other_parent, ContactChannel.EMAIL, "refused@grace.ng"
        )
        code, _ = self.deliver(
            lambda: guardian_contacts.request_verification_as(
                self.grace_admin, dead, school=self.grace
            )
        )

        self.assertEqual(self.outcome_of(code), Outcome.REFUSED)
        self.assertEqual(
            codes.last_message(dead, self.grace.pk), "could not be delivered to this contact"
        )
        # St Mary's sent it nothing, so St Mary's is told nothing.
        self.assertEqual(codes.last_message(dead, self.st_marys.pk), "")

    def test_no_provider_is_a_refusal_not_a_silence(self):
        """With nothing configured, nothing is sent and the outcome says why. D2.

        CONTROL: catching `NotConfigured` as ACCEPTED turns this red.
        """
        with override_settings(MESSAGING_PROVIDERS={"email": "", "phone": ""}):
            with self.assertLogs("messaging.codes", "ERROR"):
                code, _ = self.deliver(self.check_ours)

        self.assertEqual(FakeMessage.objects.count(), 0)
        self.assertEqual(self.outcome_of(code), Outcome.NOT_CONFIGURED)

    def test_no_log_line_carries_the_code(self):
        """A code is never at rest, and a log file is rest. D6."""
        lines = []

        class Keep(logging.Handler):
            def emit(self, record):
                lines.append(self.format(record))

        handler = Keep(level=logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s %(exc_text)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)
        unavailable = self.record(
            self.grace_admin, self.other_parent, ContactChannel.EMAIL, "unavailable@grace.ng"
        )

        _, raw_one = self.deliver(self.check_ours)
        _, raw_two = self.deliver(
            lambda: guardian_contacts.request_verification_as(
                self.grace_admin, unavailable, school=self.grace
            )
        )

        self.assertTrue(lines, "nothing was logged, so this proves nothing")
        for line in lines:
            self.assertNotIn(raw_one, line)
            self.assertNotIn(raw_two, line)

    def test_the_panel_hears_only_its_own_schools_codes(self):
        """A guardian's own sign-in codes and another school's sends are not this school's to read."""
        self.deliver(self.check_ours)
        self.assertEqual(codes.last_message(self.ours, self.st_marys.pk), "sent")
        self.assertEqual(codes.last_message(self.ours, self.grace.pk), "")


class TheSuiteTests(SimpleTestCase):
    def test_the_suite_starts_with_no_provider(self):
        """A local run has DEBUG on and CI does not; the runner makes them start alike.

        Without it, a test that sent without asking for the fake would pass on
        a developer's machine and fail in CI. CONTROL (run locally, where DEBUG
        is on): removing the line in `schools.tests.runner` stops the run at
        `messaging.E001` before any test starts, because the line also keeps the
        fake out of the checks. Removing it with E001 silenced turns this red.
        """
        from django.conf import settings

        self.assertEqual(settings.MESSAGING_PROVIDERS, {"email": "", "phone": ""})


class TheSealTests(SimpleTestCase):
    def test_a_sealed_code_opens_once_and_not_after_its_life(self):
        token = seal("123456")
        self.assertEqual(open_sealed(token, ttl_seconds=900), "123456")
        self.assertIsNone(open_sealed(token, ttl_seconds=0))
        self.assertIsNone(open_sealed(token[:-2] + "AA", ttl_seconds=900))
        with override_settings(SECRET_KEY="another key entirely, of a decent length"):
            self.assertIsNone(open_sealed(token, ttl_seconds=900))


class TheChecksTests(SimpleTestCase):
    def test_the_fake_with_debug_off_is_refused(self):
        """CONTROL: `return []` at the top of the check turns this red."""
        with override_settings(DEBUG=False, MESSAGING_PROVIDERS={"email": "", "phone": FAKE}):
            found = checks.the_fake_is_for_development_only(None)
        self.assertEqual([(type(e), e.id) for e in found], [(Error, "messaging.E001")])

        with override_settings(DEBUG=True, MESSAGING_PROVIDERS=BOTH_FAKE):
            self.assertEqual(checks.the_fake_is_for_development_only(None), [])
        with override_settings(
            DEBUG=False, MESSAGING_PROVIDERS={"email": "", "phone": "somewhere.RealSms"}
        ):
            self.assertEqual(checks.the_fake_is_for_development_only(None), [])

    def test_no_phone_provider_is_warned_about(self):
        with override_settings(MESSAGING_PROVIDERS={"email": "x.Mail", "phone": ""}):
            found = checks.guardians_need_a_phone_provider(None)
        self.assertEqual([(type(e), e.id) for e in found], [(Warning, "messaging.W001")])
        with override_settings(MESSAGING_PROVIDERS={"email": "", "phone": "x.Sms"}):
            self.assertEqual(checks.guardians_need_a_phone_provider(None), [])


class TheOutboxPageTests(TestCase):
    def test_it_is_not_there_without_debug(self):
        """It shows codes in the clear. CONTROL: dropping the view's own DEBUG check turns this red."""
        from django.http import Http404

        request = RequestFactory().get("/dev/outbox/")
        with override_settings(DEBUG=False):
            with self.assertRaises(Http404):
                outbox(request)
        with override_settings(DEBUG=True):
            FakeMessage.objects.create(
                channel_type="phone", address=MARYS_PHONE, kind="sign_in_code",
                text="Your Classnode sign-in code is 123456.", outcome=Outcome.ACCEPTED,
            )
            self.assertContains(outbox(request), "123456")


class TheRecordIsAppendOnlyTests(CodeSetUp, RefusalAssertions):
    def a_delivery(self):
        code, _ = self.deliver(self.check_ours)
        return CodeDelivery.objects.get(code=code)

    def test_the_tables_refuse_an_edit_and_a_delete(self):
        delivery = self.a_delivery()
        for model, table, pk, change in (
            (CodeDelivery, "messaging_codedelivery", delivery.pk, {"channel_type": "email"}),
            (
                CodeDeliveryOutcome,
                "messaging_codedeliveryoutcome",
                delivery.outcome.pk,
                {"outcome": Outcome.REFUSED},
            ),
        ):
            with self.subTest(table=table):
                with self.assertRefusedBy(
                    f"{table} is append-only; UPDATE is not allowed"
                ), transaction.atomic():
                    model.objects.filter(pk=pk).update(**change)
                # Raw, because the ORM's delete of a claim with an outcome is
                # refused by `PROTECT` in Python before any SQL is sent, and
                # this is about the trigger, which is what stands behind a path
                # that skips the ORM.
                with self.assertRefusedBy(
                    f"{table} is append-only; DELETE is not allowed"
                ), transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(f"DELETE FROM {table} WHERE id = %s", [pk])

    def test_the_models_refuse_before_the_tables_have_to(self):
        delivery = self.a_delivery()
        for row in (delivery, delivery.outcome):
            with self.subTest(row=type(row).__name__):
                with self.assertRaises(DeliveriesAreAppendOnly):
                    row.save()
                with self.assertRaises(DeliveriesAreAppendOnly):
                    row.delete()


class WhatAMessageCostsTests(SimpleTestCase):
    def test_one_naira_sign_makes_a_message_ucs2(self):
        self.assertEqual(kinds.segments("x" * 160), ("gsm7", 1))
        self.assertEqual(kinds.segments("x" * 161), ("gsm7", 2))
        self.assertEqual(kinds.segments("x" * 159 + "€"), ("gsm7", 2))
        self.assertEqual(kinds.segments("NGN 45,000"), ("gsm7", 1))
        self.assertEqual(kinds.segments("₦45,000"), ("ucs2", 1))
        self.assertEqual(kinds.segments("₦" + "x" * 70), ("ucs2", 2))

    def test_a_sign_in_code_is_one_segment(self):
        text = kinds.render(kinds.Kind.SIGN_IN_CODE, channel_type="phone", code="123456", minutes=15)
        self.assertEqual(kinds.segments(text), ("gsm7", 1))
