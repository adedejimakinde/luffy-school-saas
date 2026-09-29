"""Paystack's webhook, against a pretend Paystack. Money: every claim has its control.

Two schools throughout. What must never happen: a payment landing on the wrong
child or the wrong school, the same money recorded twice, money recorded that
Paystack does not confirm, or a payment guessed onto the nearest child.

The claims, each with the test that fails without it:

1. **A forged or unsigned webhook does nothing**, and costs no call to Paystack.
2. **A transaction Paystack does not confirm is not recorded**: failed, unknown,
   or for a different amount than the webhook claimed. Paystack being down is a
   503 so it is sent again, and the retry then records it once.
3. **Once per reference**: a replay, or two racing, is one ledger entry.
4. **Never guessed**: an account nobody owns, a customer that is not the one the
   account was made for, a child who is not a student here, and a school with no
   current term are listed as unmatched and touch no child's books.
5. **The right child at the right school**, in whole kobo.
"""

import hashlib
import hmac
import json
from datetime import date

from django.db import connection

from academics.models import Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from fees import services, webhook
from fees.models import FeeEntryKind, FeeLedgerEntry, UnmatchedPayment, UnmatchedReason
from fees.tests.paystack_fake import TEST_KEY
from fees.tests.test_bank import GRACE_HOST, HOST, BankSetUp
from fees.tests.test_virtual import VirtualSetUp
from schools.models import UnroutedPayment
from schools.tests.tenants import connected_to

URL = "/api/paystack/webhook/"
PORTAL = "testserver"
FIFTY_THOUSAND_NAIRA = 5_000_000  # kobo


def signed(raw, secret=TEST_KEY):
    return hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()


class WebhookSetUp(VirtualSetUp):
    def setUp(self):
        super().setUp()
        self.connect_bank("stmarys")
        self.connect_bank("grace")
        self.make()  # Ada at St Mary's: 9000000001
        self.make(child=self.zainab, user=self.their_bursar, host=GRACE_HOST)  # Zainab at Grace: 9000000002
        self.ada_no, self.zainab_no = "9000000001", "9000000002"
        self.ada_customer = self.accounts(self.stmarys)[0].customer_code
        self.zainab_customer = self.accounts(self.grace)[0].customer_code

    # -- a delivery ------------------------------------------------------------
    def event(self, reference="REF-1", amount=FIFTY_THOUSAND_NAIRA, kind="charge.success", **data):
        return {"event": kind, "data": {"reference": reference, "amount": amount, "status": "success", **data}}

    def deliver(self, body, *, secret=TEST_KEY, signature=None, host=PORTAL, method="post"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        header = signed(raw, secret) if signature is None else signature
        headers = {"HTTP_HOST": host}
        if header is not None:
            headers["HTTP_X_PAYSTACK_SIGNATURE"] = header
        self.client.logout()
        if method == "get":  # a GET has no body: `data` would be read as a query string
            return self.client.get(URL, **headers)
        return getattr(self.client, method)(URL, data=raw, content_type="application/json", **headers)

    def paid(self, reference="REF-1", amount=FIFTY_THOUSAND_NAIRA, account=None, customer=None, **more):
        """Paystack knows this transaction, and the webhook announces it."""
        self.paystack.add_transaction(
            reference, amount, account_number=account or self.ada_no,
            customer_code=customer or self.ada_customer, **more,
        )
        return self.deliver(self.event(reference, amount))

    # -- what happened ---------------------------------------------------------
    def entries(self, school):
        with connected_to(school):
            return list(FeeLedgerEntry.objects.filter(kind=FeeEntryKind.PAYMENT).order_by("id"))

    def balance(self, school, child):
        with connected_to(school):
            return FeeLedgerEntry.objects.for_student(child.pk).balance()

    def unmatched(self, school):
        with connected_to(school):
            return list(UnmatchedPayment.objects.all())

    def verifies(self):
        return self.paystack.sent("GET", path=None) and [
            r for r in self.paystack.requests if r["path"].startswith("/transaction/verify/")
        ]


class ARealPayment(WebhookSetUp):
    def test_a_confirmed_payment_is_recorded_once_on_the_right_child_in_whole_kobo(self):
        before = self.balance(self.stmarys, self.ada)

        response = self.paid()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "recorded")
        (entry,) = self.entries(self.stmarys)
        self.assertEqual(entry.student_membership_id, self.ada.pk)
        self.assertEqual(entry.amount_kobo, -FIFTY_THOUSAND_NAIRA)
        self.assertEqual((entry.method, entry.reference), ("bank_transfer", "REF-1"))
        self.assertEqual(entry.narration, "Paid online through Paystack")
        self.assertIsNone(entry.recorded_by_id)
        self.assertEqual(entry.form_key, webhook.form_key_for("REF-1"))
        self.assertEqual(self.balance(self.stmarys, self.ada), before - FIFTY_THOUSAND_NAIRA)
        self.assertIsInstance(entry.amount_kobo, int)

    def test_it_verifies_with_paystack_by_the_reference_before_recording(self):
        self.paid("REF/with slash")

        (call,) = [r for r in self.paystack.requests if r["path"].startswith("/transaction/verify/")]
        self.assertEqual(call["path"], "/transaction/verify/REF%2Fwith%20slash")
        self.assertEqual(call["headers"]["authorization"], f"Bearer {TEST_KEY}")

    def test_the_payment_is_taken_from_paystacks_record_not_the_webhooks_words(self):
        """The webhook's `account`-ish fields are never read: Paystack's verify says which account."""
        self.paystack.add_transaction("REF-1", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no,
                                      customer_code=self.ada_customer)
        body = self.event("REF-1", FIFTY_THOUSAND_NAIRA,
                          authorization={"receiver_bank_account_number": self.zainab_no},
                          customer={"customer_code": self.zainab_customer})

        response = self.deliver(body)

        self.assertEqual(response.json()["status"], "recorded")
        self.assertEqual(len(self.entries(self.stmarys)), 1)
        self.assertEqual(self.entries(self.grace), [])

    def test_only_a_charge_success_is_acted_on(self):
        response = self.deliver(self.event(kind="transfer.success"))

        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(self.verifies(), [])
        self.assertEqual(self.entries(self.stmarys), [])

    def test_an_amount_that_is_not_a_positive_whole_number_of_kobo_is_ignored(self):
        for amount in (0, -5, 5000.5, "5000", True, None):
            with self.subTest(amount=amount):
                response = self.deliver({"event": "charge.success", "data": {"reference": "R", "amount": amount}})
                self.assertEqual((response.status_code, response.json()["status"]), (200, "ignored"))
        self.assertEqual(self.verifies(), [])
        self.assertEqual(self.entries(self.stmarys), [])

    def test_a_missing_or_overlong_reference_is_ignored(self):
        for reference in (None, "", "  ", "x" * 65, 12):
            with self.subTest(reference=reference):
                response = self.deliver({"event": "charge.success", "data": {"reference": reference, "amount": 100}})
                self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(self.verifies(), [])

    def test_bad_json_that_is_signed_is_a_400(self):
        self.assertEqual(self.deliver(b"{not json").status_code, 400)

    def test_it_answers_only_a_post_and_only_on_the_portal(self):
        self.assertEqual(self.deliver(self.event(), method="get").status_code, 405)
        self.assertEqual(self.deliver(self.event(), host=HOST).status_code, 404)


class AForgedWebhook(WebhookSetUp):
    def test_a_wrong_signature_does_nothing_and_asks_paystack_nothing(self):
        """CONTROL: skipping the signature check makes this red."""
        self.paystack.add_transaction("REF-1", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no,
                                      customer_code=self.ada_customer)

        response = self.deliver(self.event(), secret="sk_test_somebody_elses_key")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.verifies(), [])
        self.assertEqual(self.entries(self.stmarys), [])
        self.assertEqual(self.unmatched(self.stmarys), [])

    def test_no_signature_at_all_is_refused(self):
        self.paystack.add_transaction("REF-1", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no,
                                      customer_code=self.ada_customer)
        raw = json.dumps(self.event()).encode()
        self.client.logout()

        response = self.client.post(URL, data=raw, content_type="application/json", HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.entries(self.stmarys), [])

    def test_a_signature_for_a_different_body_is_refused(self):
        raw = json.dumps(self.event(amount=100)).encode()
        tampered = json.dumps(self.event(amount=FIFTY_THOUSAND_NAIRA)).encode()

        response = self.deliver(tampered, signature=signed(raw))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.verifies(), [])

    def test_no_secret_configured_refuses_everything(self):
        with self.settings(PAYSTACK_WEBHOOK_SECRET=""):
            response = self.deliver(self.event(), signature=signed(json.dumps(self.event()).encode(), ""))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.verifies(), [])

    def test_the_signature_is_an_hmac_sha512_hex_digest_compared_as_such(self):
        raw = b'{"a": 1}'

        self.assertTrue(webhook.signature_ok(raw, signed(raw)))
        self.assertTrue(webhook.signature_ok(raw, signed(raw).upper()))
        self.assertFalse(webhook.signature_ok(raw, hashlib.sha256(raw).hexdigest()))
        self.assertFalse(webhook.signature_ok(raw, ""))


class AReplayedWebhook(WebhookSetUp):
    def test_the_same_webhook_twice_is_one_payment(self):
        """CONTROL: dropping the form key makes this red."""
        first = self.paid()
        before = self.balance(self.stmarys, self.ada)

        second = self.deliver(self.event())

        self.assertEqual((first.json()["status"], second.json()["status"]), ("recorded", "duplicate"))
        self.assertEqual(len(self.entries(self.stmarys)), 1)
        self.assertEqual(self.balance(self.stmarys, self.ada), before)

    def test_a_replay_arriving_many_times_is_still_one_payment(self):
        self.paid()
        for _ in range(3):
            self.deliver(self.event())

        self.assertEqual(len(self.entries(self.stmarys)), 1)

    def test_two_different_references_are_two_payments(self):
        self.paid("REF-1", 1_000_000)
        self.paid("REF-2", 2_000_000)

        self.assertEqual([e.amount_kobo for e in self.entries(self.stmarys)], [-1_000_000, -2_000_000])

    def test_the_form_key_guards_the_ledger_itself(self):
        """A second entry with one reference's key is refused by the database, not just by a read."""
        from django.db import IntegrityError, transaction

        self.paid()
        with connected_to(self.stmarys):
            term = Term.objects.get(is_current=True)
            with self.assertRaises(IntegrityError), transaction.atomic():
                services.record_payment(self.ada, term, 100, method="bank_transfer", reference="REF-1",
                                        form_key=webhook.form_key_for("REF-1"))

    def test_an_already_recorded_reference_with_a_different_amount_is_not_recorded_again(self):
        self.paid("REF-1", 1_000_000)
        self.paystack.add_transaction("REF-1", 9_000_000, account_number=self.ada_no,
                                      customer_code=self.ada_customer)

        response = self.deliver(self.event("REF-1", 9_000_000))

        self.assertEqual(response.json()["status"], "conflict")
        self.assertEqual([e.amount_kobo for e in self.entries(self.stmarys)], [-1_000_000])


class APaymentPaystackDoesNotConfirm(WebhookSetUp):
    def test_a_transaction_paystack_says_failed_is_not_recorded(self):
        """CONTROL: trusting the webhook without verifying makes this red."""
        self.paystack.add_transaction("REF-1", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no,
                                      customer_code=self.ada_customer, status="failed")

        response = self.deliver(self.event())

        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(self.entries(self.stmarys), [])
        self.assertEqual(self.unmatched(self.stmarys), [])

    def test_a_transaction_paystack_has_never_heard_of_is_not_recorded(self):
        response = self.deliver(self.event("REF-FAKE"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(self.entries(self.stmarys), [])

    def test_an_amount_paystack_disagrees_with_is_not_recorded(self):
        """CONTROL: dropping the amount comparison makes this red."""
        self.paystack.add_transaction("REF-1", 100, account_number=self.ada_no, customer_code=self.ada_customer)

        response = self.deliver(self.event("REF-1", FIFTY_THOUSAND_NAIRA))

        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(self.entries(self.stmarys), [])

    def test_a_different_currency_or_reference_is_not_recorded(self):
        self.paystack.add_transaction("REF-1", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no,
                                      customer_code=self.ada_customer, currency="USD")
        self.paystack.add_transaction("REF-2", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no,
                                      customer_code=self.ada_customer)
        self.paystack.transactions["REF-2"]["reference"] = "REF-OTHER"

        self.assertEqual(self.deliver(self.event("REF-1")).json()["status"], "ignored")
        self.assertEqual(self.deliver(self.event("REF-2")).json()["status"], "ignored")
        self.assertEqual(self.entries(self.stmarys), [])

    def test_paystack_down_is_a_503_so_it_is_sent_again_and_the_retry_records_once(self):
        self.paystack.add_transaction("REF-1", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no,
                                      customer_code=self.ada_customer)
        self.paystack.down()

        down = self.deliver(self.event())
        self.paystack.down(False)
        retry = self.deliver(self.event())
        again = self.deliver(self.event())

        self.assertEqual(down.status_code, 503)
        self.assertEqual(self.entries(self.stmarys)[0].reference, "REF-1")
        self.assertEqual([retry.json()["status"], again.json()["status"]], ["recorded", "duplicate"])
        self.assertEqual(len(self.entries(self.stmarys)), 1)

    def test_paystack_rejecting_our_key_is_a_503_and_leaks_nothing(self):
        self.paystack.fail_next(401, b'{"status": false, "message": "Invalid key"}')

        response = self.deliver(self.event())

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Invalid key", response.content.decode())
        self.assertEqual(self.entries(self.stmarys), [])


class NeverGuessed(WebhookSetUp):
    def test_an_account_nobody_owns_is_listed_for_the_platform_and_touches_no_books(self):
        response = self.paid(account="0000000000")

        self.assertEqual(response.json()["status"], "unrouted")
        (row,) = UnroutedPayment.objects.all()
        self.assertEqual((row.reference, row.amount_kobo, row.account_number), ("REF-1", FIFTY_THOUSAND_NAIRA, "0000000000"))
        self.assertEqual(self.entries(self.stmarys) + self.entries(self.grace), [])
        self.assertEqual(self.unmatched(self.stmarys) + self.unmatched(self.grace), [])
        self.deliver(self.event())
        self.assertEqual(UnroutedPayment.objects.count(), 1)

    def test_a_different_customer_than_the_account_was_made_for_is_listed_not_recorded(self):
        """CONTROL: dropping the customer check makes this red."""
        response = self.paid(customer="CUS_somebody_else")

        self.assertEqual(response.json()["status"], "unmatched")
        (row,) = self.unmatched(self.stmarys)
        self.assertEqual((row.reference, row.reason, row.amount_kobo), ("REF-1", UnmatchedReason.WRONG_CUSTOMER, FIFTY_THOUSAND_NAIRA))
        self.assertEqual(row.customer_code, "CUS_somebody_else")
        self.assertEqual(self.entries(self.stmarys), [])

    def test_no_customer_in_paystacks_record_is_a_mismatch_too(self):
        self.paystack.add_transaction("REF-1", FIFTY_THOUSAND_NAIRA, account_number=self.ada_no, customer_code="")

        self.deliver(self.event())

        self.assertEqual([u.reason for u in self.unmatched(self.stmarys)], [UnmatchedReason.WRONG_CUSTOMER])
        self.assertEqual(self.entries(self.stmarys), [])

    def test_an_account_whose_child_is_not_a_student_here_is_listed(self):
        with connected_to(self.stmarys):
            from fees.models import VirtualAccount

            teacher = grant_membership(User.objects.create_user("tt", "correct-horse-battery", full_name="T T"),
                                       self.stmarys, Role.TEACHER)
            VirtualAccount.objects.create(
                student_membership_id=teacher.pk, customer_code="CUS_t", account_number="9000000099",
                account_name="N", bank_name="Wema Bank", split_code="S", created_by_id=1, created_by_name="x",
            )
        from schools.models import PaystackRoute

        PaystackRoute.objects.create(account_number="9000000099", school=self.stmarys)

        response = self.paid(account="9000000099", customer="CUS_t")

        self.assertEqual(response.json()["status"], "unmatched")
        self.assertEqual([u.reason for u in self.unmatched(self.stmarys)], [UnmatchedReason.NOT_A_STUDENT])

    def test_a_route_with_no_account_behind_it_is_listed(self):
        from schools.models import PaystackRoute

        PaystackRoute.objects.create(account_number="9000000088", school=self.stmarys)

        self.paid(account="9000000088", customer="CUS_x")

        self.assertEqual([u.reason for u in self.unmatched(self.stmarys)], [UnmatchedReason.NO_ACCOUNT])
        self.assertEqual(self.entries(self.stmarys), [])

    def test_a_school_with_no_current_term_lists_it_and_a_replay_stays_listed(self):
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)

        self.paid()
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=True)
        replay = self.deliver(self.event())

        self.assertEqual([u.reason for u in self.unmatched(self.stmarys)], [UnmatchedReason.NO_CURRENT_TERM])
        self.assertEqual(replay.json()["status"], "unmatched")
        self.assertEqual(self.entries(self.stmarys), [], "a replay recorded money a person has yet to place")

    def test_unmatched_money_is_listed_once_however_often_it_arrives(self):
        for _ in range(3):
            self.paid(customer="CUS_somebody_else")

        self.assertEqual(len(self.unmatched(self.stmarys)), 1)

    def test_no_child_is_the_nearest_guess(self):
        """A payment that cannot be placed leaves every child's account exactly where it was."""
        balances = {c.pk: self.balance(self.stmarys, c) for c in (self.ada, self.chidi)}

        self.paid(customer="CUS_somebody_else")
        self.paid("REF-2", account="0000000000")

        self.assertEqual({c.pk: self.balance(self.stmarys, c) for c in (self.ada, self.chidi)}, balances)


class TwoSchoolsAtOnce(WebhookSetUp):
    def test_each_payment_lands_only_at_the_school_whose_account_it_was_paid_into(self):
        self.paid("REF-A", 1_000_000, account=self.ada_no, customer=self.ada_customer)
        self.paid("REF-Z", 2_500_000, account=self.zainab_no, customer=self.zainab_customer)

        self.assertEqual([(e.student_membership_id, e.amount_kobo) for e in self.entries(self.stmarys)],
                         [(self.ada.pk, -1_000_000)])
        self.assertEqual([(e.student_membership_id, e.amount_kobo) for e in self.entries(self.grace)],
                         [(self.zainab.pk, -2_500_000)])

    def test_one_schools_unmatched_list_never_shows_the_others_money(self):
        self.paid("REF-A", 1_000_000, account=self.ada_no, customer="CUS_wrong")
        self.paid("REF-Z", 2_500_000, account=self.zainab_no, customer="CUS_wrong")

        self.assertEqual([u.reference for u in self.unmatched(self.stmarys)], ["REF-A"])
        self.assertEqual([u.reference for u in self.unmatched(self.grace)], ["REF-Z"])
        ours = self.get(self.bursar, "virtual/unmatched/").json()["payments"]
        theirs = self.get(self.their_bursar, "virtual/unmatched/", host=GRACE_HOST).json()["payments"]
        self.assertEqual([p["reference"] for p in ours], ["REF-A"])
        self.assertEqual([p["reference"] for p in theirs], ["REF-Z"])

    def test_the_same_reference_at_two_schools_cannot_double_record(self):
        """References are Paystack's and unique; a second school's account must not reuse one."""
        self.paid("REF-1", 1_000_000, account=self.ada_no, customer=self.ada_customer)
        self.paystack.add_transaction("REF-1", 1_000_000, account_number=self.zainab_no,
                                      customer_code=self.zainab_customer)

        self.deliver(self.event("REF-1", 1_000_000))

        self.assertEqual(len(self.entries(self.stmarys)), 1)
        self.assertEqual(len(self.entries(self.grace)), 1)  # a different school's own ledger


class TheUnmatchedList(WebhookSetUp):
    def test_the_bursar_and_the_principal_read_it_a_teacher_gets_the_flat_404(self):
        self.paid(customer="CUS_wrong")

        for user, status in ((self.bursar, 200), (self.admin, 200), (self.principal, 200), (self.teacher, 404), (self.parent, 404)):
            with self.subTest(user=user.username):
                self.assertEqual(self.get(user, "virtual/unmatched/").status_code, status)
        row = self.get(self.bursar, "virtual/unmatched/").json()["payments"][0]
        self.assertEqual((row["reference"], row["amount_kobo"], row["reason"]), ("REF-1", FIFTY_THOUSAND_NAIRA, "wrong_customer"))
        self.assertEqual(row["reason_label"], "Paystack says a different customer paid into it")

    def test_the_portal_has_none(self):
        self.assertEqual(self.get(self.bursar, "virtual/unmatched/", host=PORTAL).status_code, 404)
