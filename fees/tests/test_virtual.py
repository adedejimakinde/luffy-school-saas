"""A dedicated virtual account for each child, and where families see it.

Two schools throughout (St Mary's under test, Grace Academy beside it), because
what must never happen is one school's child being given an account that settles
through another school's split, or one school seeing another's account.

Claims, each with the test that fails without it:

1. An account is made against **the school's own split**, and only once a bank is
   connected; asking again returns the same account and calls Paystack no more.
2. It is routed by a public row to the right school.
3. Bursar and administrator make; the principal is told they may not; everybody
   else gets the flat 404. A child at another school is not found.
4. A parent sees where to pay for **their own** children and nobody else's.
5. A fee reminder and a receipt say "Pay into: Bank Number, Name" when the child
   has an account, and nothing extra when they do not.
6. A row is never edited or deleted.
"""

from datetime import date

from django.db import IntegrityError, connection, transaction

from accounts.models import Role, User
from accounts.services import link_guardian, grant_membership
from fees import virtual
from fees.models import UnmatchedPayment, UnmatchedPaymentIsFixed, VirtualAccount, VirtualAccountIsFixed
from fees.tests.test_bank import ADA_ACCOUNT, GRACE_HOST, HOST, BankSetUp
from notices import receipts, reminders
from schools.models import PaystackRoute
from schools.tests.tenants import connected_to


class VirtualSetUp(BankSetUp):
    def connect_bank(self, who="stmarys"):
        if who == "stmarys":
            assert self.connect().status_code == 201
        else:
            assert self.connect(
                self.their_bursar, host=GRACE_HOST, bank_code="044",
                account_number="1234567890", account_name="GRACE ACADEMY LTD",
            ).status_code == 201

    def make(self, child=None, user=None, host=HOST):
        child = child or self.ada
        return self.post(user or self.bursar, f"virtual/students/{child.pk}/", {}, host=host)

    def accounts(self, school):
        with connected_to(school):
            return list(VirtualAccount.objects.all())


class MakingOne(VirtualSetUp):
    def test_it_is_made_against_the_schools_own_split_and_routed_to_the_school(self):
        self.connect_bank()
        split = self.rows(self.stmarys)[0].split_code

        response = self.make()

        self.assertEqual(response.status_code, 201, response.content)
        (row,) = self.accounts(self.stmarys)
        self.assertEqual(row.student_membership_id, self.ada.pk)
        self.assertEqual((row.bank_name, row.account_number), ("Wema Bank", "9000000001"))
        self.assertEqual(row.split_code, split)
        self.assertEqual((row.created_by_id, row.created_by_name), (self.bursar.pk, "Bola Bursar"))
        self.assertEqual(response.json()["pay_into"]["account_number"], "9000000001")
        (customer,) = self.paystack.sent("POST", "/customer")
        self.assertEqual(customer["body"]["email"], f"st-marys-{self.ada.pk}@classnode.example")
        self.assertEqual((customer["body"]["first_name"], customer["body"]["last_name"]), ("Ada", "Obi"))
        (dedicated,) = self.paystack.sent("POST", "/dedicated_account")
        self.assertEqual(dedicated["body"]["split_code"], split)
        self.assertEqual(dedicated["body"]["customer"], row.customer_code)
        self.assertEqual(PaystackRoute.objects.get(account_number="9000000001").school_id, self.stmarys.pk)

    def test_asking_again_returns_the_same_account_and_calls_paystack_no_more(self):
        self.connect_bank()
        self.make()
        calls = len(self.paystack.requests)

        again = self.make()

        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["created"])
        self.assertEqual(len(self.paystack.requests), calls)
        self.assertEqual(len(self.accounts(self.stmarys)), 1)

    def test_it_needs_the_schools_bank_first(self):
        response = self.make()

        self.assertEqual(response.status_code, 409)
        self.assertIn("Connect the school's bank", response.json()["detail"])
        self.assertEqual(self.paystack.sent("POST", "/customer"), [])
        self.assertEqual(self.accounts(self.stmarys), [])

    def test_paystack_down_is_a_503_and_nothing_is_kept(self):
        self.connect_bank()
        self.paystack.down()

        response = self.make()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.accounts(self.stmarys), [])
        self.assertFalse(PaystackRoute.objects.exists())

    def test_paystack_refusing_the_account_is_a_sentence_and_nothing_is_kept(self):
        from fees.tests.paystack_fake import _Response

        self.connect_bank()
        original = self.paystack._route

        def refuse(record):
            if record["path"] == "/dedicated_account":
                return _Response(400, {"status": False, "message": "Customer is not eligible"})
            return original(record)

        self.paystack._route = refuse

        response = self.make()

        self.assertEqual(response.status_code, 422)
        self.assertIn("Customer is not eligible", response.json()["detail"])
        self.assertEqual(self.accounts(self.stmarys), [])
        self.assertFalse(PaystackRoute.objects.exists())

    def test_the_account_page_says_where_to_pay_and_whether_a_bank_is_connected(self):
        before = self.get(self.bursar, f"students/{self.ada.pk}/").json()
        self.connect_bank()
        self.make()
        after = self.get(self.principal, f"students/{self.ada.pk}/").json()

        self.assertEqual((before["pay_into"], before["bank_connected"]), (None, False))
        self.assertEqual(after["pay_into"]["bank_name"], "Wema Bank")
        self.assertEqual(after["pay_into"]["account_number"], "9000000001")
        self.assertTrue(after["bank_connected"])


class WhoMay(VirtualSetUp):
    def setUp(self):
        super().setUp()
        self.connect_bank()

    def test_the_administrator_may_make_one_too(self):
        self.assertEqual(self.make(user=self.admin).status_code, 201)

    def test_a_principal_is_told_they_may_not_and_nothing_is_made(self):
        self.assertEqual(self.make(user=self.principal).status_code, 403)
        self.assertEqual(self.accounts(self.stmarys), [])

    def test_a_teacher_a_parent_and_a_student_get_the_flat_404(self):
        for user in (self.teacher, self.parent, self.student_user):
            with self.subTest(user=user.username):
                self.assertEqual(self.make(user=user).status_code, 404)
        self.assertEqual(self.accounts(self.stmarys), [])

    def test_a_child_at_another_school_is_not_found(self):
        self.assertEqual(self.make(child=self.zainab).status_code, 404)
        self.assertEqual(self.paystack.sent("POST", "/customer"), [])

    def test_the_portal_has_none(self):
        self.assertEqual(self.make(host="testserver").status_code, 404)


class TwoSchools(VirtualSetUp):
    def test_each_school_settles_through_its_own_split_and_is_routed_to_itself(self):
        self.connect_bank("stmarys")
        self.connect_bank("grace")

        self.assertEqual(self.make().status_code, 201)
        self.assertEqual(self.make(child=self.zainab, user=self.their_bursar, host=GRACE_HOST).status_code, 201)

        ours, theirs = self.accounts(self.stmarys)[0], self.accounts(self.grace)[0]
        self.assertNotEqual(ours.split_code, theirs.split_code)
        self.assertEqual(ours.split_code, self.rows(self.stmarys)[0].split_code)
        self.assertEqual(theirs.split_code, self.rows(self.grace)[0].split_code)
        routes = {r.account_number: r.school_id for r in PaystackRoute.objects.all()}
        self.assertEqual(routes, {ours.account_number: self.stmarys.pk, theirs.account_number: self.grace.pk})
        splits = [d["body"]["split_code"] for d in self.paystack.sent("POST", "/dedicated_account")]
        self.assertEqual(splits, [ours.split_code, theirs.split_code])

    def test_a_school_never_sees_the_others_accounts(self):
        self.connect_bank("stmarys")
        self.connect_bank("grace")
        self.make()
        self.make(child=self.zainab, user=self.their_bursar, host=GRACE_HOST)

        self.assertEqual([a.student_membership_id for a in self.accounts(self.stmarys)], [self.ada.pk])
        self.assertEqual([a.student_membership_id for a in self.accounts(self.grace)], [self.zainab.pk])


class AParentSees(VirtualSetUp):
    def test_where_to_pay_for_their_own_children_and_nobody_elses(self):
        self.connect_bank()
        self.make()
        self.make(child=self.chidi)
        link_guardian(self.parent, self.ada)

        mine = self.get(self.parent, "virtual/mine/").json()["children"]

        self.assertEqual([c["student_membership_id"] for c in mine], [self.ada.pk])
        self.assertEqual(mine[0]["pay_into"]["account_number"], "9000000001")
        self.assertNotIn("9000000002", str(mine))

    def test_a_child_with_no_account_is_listed_with_none(self):
        link_guardian(self.parent, self.ada)

        mine = self.get(self.parent, "virtual/mine/").json()["children"]

        self.assertEqual(mine[0]["pay_into"], None)

    def test_someone_with_no_children_gets_an_empty_list_and_the_portal_a_404(self):
        self.assertEqual(self.get(self.teacher, "virtual/mine/").json(), {"children": []})
        self.assertEqual(self.get(self.parent, "virtual/mine/", host="testserver").status_code, 404)


class WhatMessagesSay(VirtualSetUp):
    def text(self, child):
        with connected_to(self.stmarys):
            reminder = reminders.reminder_text(
                school_name="St Mary's", child_name=child.name, amount_kobo=150_000_00,
                channel_type="email", student_membership_id=child.pk,
            )
        return reminder

    def test_a_fee_reminder_says_where_to_pay_when_the_child_has_an_account(self):
        self.connect_bank()
        self.make()

        text = self.text(self.ada)

        self.assertIn("Pay into: Wema Bank 9000000001, CLASSNODE/CUS_test0001.", text)
        self.assertIn("owing.", text)

    def test_a_child_with_no_account_gets_the_old_reminder_word_for_word(self):
        text = self.text(self.ada)

        self.assertNotIn("Pay into", text)
        self.assertEqual(text, "St Mary's: Ada Obi's fees account shows NGN 150,000 owing. Please contact the school.")

    def test_a_reminder_for_one_child_never_names_anothers_account(self):
        self.connect_bank()
        self.make()

        self.assertNotIn("9000000001", self.text(self.chidi))

    def test_a_receipt_says_where_to_pay_too(self):
        from fees import services
        from academics.models import Term

        self.connect_bank()
        self.make()
        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
            entry = services.record_payment(self.ada, term, 50_000_00, method="cash")
            text = receipts.receipt_text_for(entry, school=self.stmarys, channel_type="email")
            other = services.record_payment(self.chidi, term, 10_000_00, method="cash")
            other_text = receipts.receipt_text_for(other, school=self.stmarys, channel_type="email")

        self.assertIn("Pay into: Wema Bank 9000000001,", text)
        self.assertNotIn("Pay into", other_text)


class AppendOnly(VirtualSetUp):
    def test_the_models_refuse_to_edit_or_delete(self):
        self.connect_bank()
        self.make()
        with connected_to(self.stmarys):
            row = VirtualAccount.objects.get()
            row.account_number = "1111111111"
            with self.assertRaises(VirtualAccountIsFixed):
                row.save()
            with self.assertRaises(VirtualAccountIsFixed):
                row.delete()
            note = UnmatchedPayment.objects.create(reference="R1", amount_kobo=100, reason="no_account")
            with self.assertRaises(UnmatchedPaymentIsFixed):
                note.save()
            with self.assertRaises(UnmatchedPaymentIsFixed):
                note.delete()

    def test_sql_cannot_edit_or_delete_either(self):
        """CONTROL: dropping the trigger makes this red."""
        self.connect_bank()
        self.make()
        with connected_to(self.stmarys):
            UnmatchedPayment.objects.create(reference="R1", amount_kobo=100, reason="no_account")
            for sql in (
                "UPDATE fees_virtualaccount SET account_number = '1111111111'",
                "DELETE FROM fees_virtualaccount",
                "UPDATE fees_unmatchedpayment SET amount_kobo = 1",
                "DELETE FROM fees_unmatchedpayment",
            ):
                with self.subTest(sql=sql):
                    with self.assertRaisesMessage(IntegrityError, "never edited or deleted"):
                        with transaction.atomic(), connection.cursor() as cursor:
                            cursor.execute(sql)

    def test_one_account_per_child_and_per_number_at_the_database(self):
        self.connect_bank()
        self.make()
        with connected_to(self.stmarys):
            base = dict(customer_code="C", account_name="N", bank_name="B", split_code="S",
                        created_by_id=1, created_by_name="x")
            with self.assertRaises(IntegrityError), transaction.atomic():
                VirtualAccount.objects.create(student_membership_id=self.ada.pk, account_number="1234509876", **base)
            with self.assertRaises(IntegrityError), transaction.atomic():
                VirtualAccount.objects.create(student_membership_id=self.chidi.pk, account_number="9000000001", **base)
            with self.assertRaises(IntegrityError), transaction.atomic():
                VirtualAccount.objects.create(student_membership_id=self.chidi.pk, account_number="123", **base)
