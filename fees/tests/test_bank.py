"""A school connects its bank: `/api/fees/bank/`, against a pretend Paystack.

Paystack's HTTP is mocked (`paystack_fake`); nothing reaches a network. Two
schools throughout, St Mary's under test and Grace Academy beside it, because
what must never happen is one school's fees being pointed at another's account,
or one school seeing the other's.

The claims, each with the test that fails without it:

1. The name saved is Paystack's, and only after a person confirmed it: a
   confirmation that is not what a fresh resolve says is a 409 that writes and
   creates nothing.
2. **The platform takes no share and the school bears the fees**: the
   subaccount is made with `percentage_charge` 0 and the split gives it 100%
   with the subaccount as bearer.
3. Bursar and administrator write; the principal reads (number masked) and is
   told they may not write; a teacher gets the flat 404.
4. Two schools never share a connection.
5. A live key is refused before any call is made; a key never appears in a reply.
6. A row is never edited or deleted, and changing bank re-points the same
   subaccount and adds a row.
"""

import logging

from django.db import IntegrityError, connection, transaction

from fees import bank
from fees.models import BankRecordIsFixed, SchoolBank
from fees.tests.paystack_fake import TEST_KEY, PaystackMixin, _Response
from fees.tests.test_fees_api import HOST, FeesApiSetUp
from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain
from schools.tests.tenants import connected_to

GRACE_HOST = "grace.testserver"
ADA_ACCOUNT = {"bank_code": "035", "account_number": "0123456789"}


class BankSetUp(PaystackMixin, FeesApiSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.grace, domain=GRACE_HOST, is_primary=True)
        self.their_bursar = grant_membership(
            User.objects.create_user("gbola", "correct-horse-battery", full_name="Gina Bursar"),
            self.grace,
            Role.BURSAR,
        ).user

    def connect(self, user=None, host=HOST, **overrides):
        body = {**ADA_ACCOUNT, "account_name": "ST MARYS COLLEGE", **overrides}
        return self.post(user or self.bursar, "bank/", body, host=host)

    def rows(self, school):
        with connected_to(school):
            return list(SchoolBank.objects.all())


class ResolveTests(BankSetUp):
    def test_it_returns_the_name_the_bank_holds_and_writes_nothing(self):
        response = self.post(self.bursar, "bank/resolve/", ADA_ACCOUNT)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"account_name": "ST MARYS COLLEGE"})
        self.assertEqual(self.paystack.sent("GET", "/bank/resolve")[0]["query"],
                         {"account_number": "0123456789", "bank_code": "035"})
        self.assertEqual(self.paystack.sent("POST"), [])
        self.assertEqual(self.rows(self.stmarys), [])

    def test_an_account_the_bank_does_not_have_is_a_sentence(self):
        response = self.post(self.bursar, "bank/resolve/", {**ADA_ACCOUNT, "account_number": "9999999999"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("no account with that number", response.json()["detail"])

    def test_a_number_that_is_not_ten_digits_never_reaches_paystack(self):
        response = self.post(self.bursar, "bank/resolve/", {**ADA_ACCOUNT, "account_number": "12345"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.paystack.sent("GET", "/bank/resolve"), [])

    def test_a_bank_paystack_does_not_list_is_refused(self):
        response = self.post(self.bursar, "bank/resolve/", {**ADA_ACCOUNT, "bank_code": "999"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.paystack.sent("GET", "/bank/resolve"), [])

    def test_the_bank_list_is_paystacks_by_name(self):
        response = self.get(self.admin, "bank/banks/")

        self.assertEqual([b["name"] for b in response.json()["banks"]],
                         ["Access Bank", "Wema Bank", "Zenith Bank"])


class ConnectTests(BankSetUp):
    def test_a_confirmed_name_connects_the_school_and_saves_paystacks_name(self):
        response = self.connect()

        self.assertEqual(response.status_code, 201, response.content)
        (row,) = self.rows(self.stmarys)
        self.assertEqual((row.bank_name, row.account_number), ("Wema Bank", "0123456789"))
        self.assertEqual(row.account_name, "ST MARYS COLLEGE")
        self.assertEqual(row.subaccount_code, "ACCT_test0001")
        self.assertEqual(row.split_code, "SPL_test0001")
        self.assertEqual((row.connected_by_id, row.connected_by_name), (self.bursar.pk, "Bola Bursar"))
        body = response.json()
        self.assertEqual(body["connected"]["account_number"], "0123456789")

    def test_a_confirmation_that_differs_only_in_case_and_spacing_is_accepted_but_paystacks_name_is_kept(self):
        response = self.connect(account_name="  st   marys college ")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.rows(self.stmarys)[0].account_name, "ST MARYS COLLEGE")

    def test_a_name_that_is_not_what_the_bank_says_is_refused_and_nothing_is_made(self):
        """CONTROL: taking the confirmed name on trust makes this red."""
        response = self.connect(account_name="SOMEBODY ELSE ENTIRELY")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.rows(self.stmarys), [])
        self.assertEqual(self.paystack.sent("POST"), [], "a subaccount was made for an unconfirmed name")

    def test_the_bank_changing_the_name_after_it_was_shown_is_refused(self):
        self.paystack.accounts["0123456789"] = "A DIFFERENT HOLDER"

        response = self.connect()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.rows(self.stmarys), [])

    def test_the_platform_takes_no_share_and_the_school_bears_paystacks_fees(self):
        """CONTROL: a non-zero share, or the account as bearer, makes this red."""
        self.connect()

        (sub,) = self.paystack.sent("POST", "/subaccount")
        self.assertEqual(sub["body"]["percentage_charge"], 0)
        self.assertEqual(sub["body"]["bank_code"], "035")
        self.assertEqual(sub["body"]["account_number"], "0123456789")
        self.assertEqual(sub["body"]["business_name"], "St Mary's")
        (split,) = self.paystack.sent("POST", "/split")
        self.assertEqual(split["body"]["subaccounts"], [{"subaccount": "ACCT_test0001", "share": 100}])
        self.assertEqual(split["body"]["bearer_type"], "subaccount")
        self.assertEqual(split["body"]["bearer_subaccount"], "ACCT_test0001")

    def test_the_subaccount_calls_name_the_bank_field_bank_code(self):
        """Paystack's Subaccount API says `bank_code`, on create and on update.

        CONTROL: naming it `settlement_bank` again makes this red, and the fake
        Paystack refuses it too, so the connection itself fails.
        """
        self.connect()
        self.connect(account_number="2222222222", account_name="ST MARYS COLLEGE SAVINGS")

        (create,) = self.paystack.sent("POST", "/subaccount")
        (update,) = self.paystack.sent("PUT")
        self.assertEqual(set(create["body"]),
                         {"business_name", "bank_code", "account_number", "percentage_charge"})
        self.assertEqual(set(update["body"]), {"bank_code", "account_number"})
        self.assertEqual((create["body"]["bank_code"], update["body"]["bank_code"]), ("035", "035"))

    def test_every_call_is_sent_with_the_test_key_as_a_bearer_token(self):
        self.connect()

        self.assertTrue(self.paystack.requests)
        for request in self.paystack.requests:
            self.assertEqual(request["headers"]["authorization"], f"Bearer {TEST_KEY}")

    def test_connecting_the_same_account_again_is_a_409_and_makes_nothing_more(self):
        self.connect()
        before = len(self.paystack.sent("POST"))

        response = self.connect()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.paystack.sent("POST")), before)
        self.assertEqual(len(self.rows(self.stmarys)), 1)

    def test_changing_bank_repoints_the_same_subaccount_and_adds_a_row(self):
        self.connect()

        response = self.connect(account_number="2222222222", account_name="ST MARYS COLLEGE SAVINGS")

        self.assertEqual(response.status_code, 201, response.content)
        (put,) = self.paystack.sent("PUT")
        self.assertEqual(put["path"], "/subaccount/ACCT_test0001")
        self.assertEqual(put["body"]["account_number"], "2222222222")
        self.assertEqual(len(self.paystack.sent("POST", "/subaccount")), 1)
        rows = self.rows(self.stmarys)  # newest first
        self.assertEqual([r.account_number for r in rows], ["2222222222", "0123456789"])
        self.assertEqual({r.subaccount_code for r in rows}, {"ACCT_test0001"})
        self.assertEqual(self.get(self.bursar, "bank/").json()["connected"]["account_number"], "2222222222")

    def test_paystack_refusing_the_subaccount_writes_nothing(self):
        # The bank list and the resolve succeed; the subaccount call is refused.
        original = self.paystack._route

        def refuse(record):
            if (record["method"], record["path"]) == ("POST", "/subaccount"):
                return _Response(400, {"status": False, "message": "Settlement bank is not supported"})
            return original(record)

        self.paystack._route = refuse

        response = self.connect()

        self.assertEqual(response.status_code, 422)
        self.assertIn("Settlement bank is not supported", response.json()["detail"])
        self.assertEqual(self.rows(self.stmarys), [])


class WhenPaystackIsNotThere(BankSetUp):
    def test_a_live_key_is_refused_before_any_call_is_made(self):
        """CONTROL: dropping the `sk_test_` check makes this red."""
        with self.settings(PAYSTACK_SECRET_KEY="sk_live_0123456789abcdef"):
            response = self.connect()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.paystack.requests, [])
        self.assertNotIn("sk_live", response.content.decode())
        self.assertEqual(self.rows(self.stmarys), [])

    def test_no_key_is_a_503_and_no_call(self):
        with self.settings(PAYSTACK_SECRET_KEY=""):
            response = self.post(self.bursar, "bank/resolve/", ADA_ACCOUNT)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.paystack.requests, [])

    def test_paystack_unreachable_is_a_503_that_says_nothing_of_why(self):
        self.paystack.down()

        with self.assertLogs("fees.bank_api", level=logging.WARNING):
            response = self.connect()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.rows(self.stmarys), [])
        self.assertNotIn(TEST_KEY, response.content.decode())
        self.assertNotIn("no route", response.content.decode())

    def test_paystack_rejecting_our_key_is_a_503_not_a_leak(self):
        self.paystack.fail_next(401, b'{"status": false, "message": "Invalid key"}')

        response = self.post(self.bursar, "bank/resolve/", ADA_ACCOUNT)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Invalid key", response.content.decode())

    def test_a_paystack_500_is_a_503_and_writes_nothing(self):
        self.paystack.fail_next(500)  # the bank list

        response = self.connect()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.rows(self.stmarys), [])

    def test_an_unreadable_reply_is_a_503(self):
        self.paystack.fail_next(200, b"<html>gateway</html>")

        response = self.connect()

        self.assertEqual(response.status_code, 503)


class WhoMay(BankSetUp):
    def test_the_administrator_may_write_too(self):
        self.assertEqual(self.connect(self.admin).status_code, 201)

    def test_a_principal_reads_with_the_number_masked_and_may_not_write(self):
        self.connect()

        seen = self.get(self.principal, "bank/").json()
        refused = self.post(self.principal, "bank/resolve/", ADA_ACCOUNT)
        refused_connect = self.connect(self.principal)

        self.assertFalse(seen["may_write"])
        self.assertEqual(seen["connected"]["account_number"], "******6789")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused_connect.status_code, 403)
        self.assertEqual(self.get(self.principal, "bank/banks/").status_code, 403)
        self.assertEqual(len(self.rows(self.stmarys)), 1)

    def test_a_teacher_a_parent_and_a_student_get_the_flat_404(self):
        for user in (self.teacher, self.parent, self.student_user):
            with self.subTest(user=user.username):
                self.assertEqual(self.get(user, "bank/").status_code, 404)
                self.assertEqual(self.connect(user).status_code, 404)

    def test_the_portal_has_no_bank(self):
        self.assertEqual(self.get(self.bursar, "bank/", host="testserver").status_code, 404)

    def test_a_signed_out_caller_is_refused(self):
        self.client.logout()
        response = self.client.get("/api/fees/bank/", HTTP_HOST=HOST)

        self.assertIn(response.status_code, (401, 403))

    def test_another_schools_bursar_cannot_reach_this_one(self):
        # The school-access middleware refuses a stranger before the route is reached.
        self.assertEqual(self.connect(self.their_bursar, host=HOST).status_code, 403)
        self.assertEqual(self.rows(self.stmarys), [])


class TwoSchools(BankSetUp):
    def test_each_school_has_its_own_connection_and_never_sees_the_others(self):
        self.assertEqual(self.connect().status_code, 201)
        grace = self.connect(
            self.their_bursar,
            host=GRACE_HOST,
            bank_code="044",
            account_number="1234567890",
            account_name="GRACE ACADEMY LTD",
        )

        self.assertEqual(grace.status_code, 201, grace.content)
        ours, theirs = self.rows(self.stmarys), self.rows(self.grace)
        self.assertEqual([(r.bank_name, r.account_number) for r in ours], [("Wema Bank", "0123456789")])
        self.assertEqual([(r.bank_name, r.account_number) for r in theirs], [("Access Bank", "1234567890")])
        self.assertNotEqual(ours[0].subaccount_code, theirs[0].subaccount_code)
        self.assertNotEqual(ours[0].split_code, theirs[0].split_code)
        # ...and each school's own payload named its own school and account.
        subs = self.paystack.sent("POST", "/subaccount")
        self.assertEqual([s["body"]["business_name"] for s in subs], ["St Mary's", "Grace Academy"])
        self.assertEqual([s["body"]["account_number"] for s in subs], ["0123456789", "1234567890"])

    def test_a_school_with_no_connection_does_not_see_the_others(self):
        self.connect()

        seen = self.get(self.their_bursar, "bank/", host=GRACE_HOST).json()

        self.assertIsNone(seen["connected"])
        self.assertTrue(seen["may_write"])

    def test_changing_one_schools_bank_leaves_the_other_alone(self):
        self.connect()
        self.connect(self.their_bursar, host=GRACE_HOST, bank_code="044",
                     account_number="1234567890", account_name="GRACE ACADEMY LTD")

        self.connect(account_number="2222222222", account_name="ST MARYS COLLEGE SAVINGS")

        self.assertEqual([r.account_number for r in self.rows(self.grace)], ["1234567890"])
        (put,) = self.paystack.sent("PUT")
        self.assertEqual(put["path"], "/subaccount/ACCT_test0001")  # St Mary's, not Grace's 0002


class AppendOnly(BankSetUp):
    def test_a_row_cannot_be_edited_or_deleted_by_the_model(self):
        self.connect()
        with connected_to(self.stmarys):
            row = SchoolBank.objects.get()
            row.account_number = "1111111111"
            with self.assertRaises(BankRecordIsFixed):
                row.save()
            with self.assertRaises(BankRecordIsFixed):
                row.delete()

    def test_a_row_cannot_be_edited_or_deleted_by_sql(self):
        """CONTROL: dropping the trigger makes this red."""
        self.connect()
        with connected_to(self.stmarys):
            with self.assertRaisesMessage(IntegrityError, "never edited or deleted"):
                with transaction.atomic():
                    SchoolBank.objects.update(account_number="1111111111")
            with self.assertRaisesMessage(IntegrityError, "never edited or deleted"):
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("DELETE FROM fees_schoolbank")
            self.assertEqual(SchoolBank.objects.get().account_number, "0123456789")

    def test_an_account_number_must_be_ten_digits_at_the_database(self):
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    SchoolBank.objects.create(
                        bank_code="035", bank_name="Wema", account_number="123", account_name="X",
                        subaccount_code="A", split_code="S", connected_by_id=1, connected_by_name="x",
                    )
