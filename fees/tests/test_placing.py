"""A bursar puts an unmatched payment on a child. Money: every claim has its control.

Two schools throughout, and **each school's unmatched payments have ids of their own**
(both schools' first one is `1`), so a placement that reached across schools would find
somebody else's money by number.

The claims, each with the test that fails without it:

1. **It posts once**: through `record_payment_once()` with the Paystack reference, so
   placing twice, or placing after the webhook or another person got there, is one
   ledger entry and never two.
2. **The server posts its own amount.** The person confirms the amount and reference; a
   confirmation that is not what the payment says is refused and writes nothing.
3. **It records who** placed it, on the entry and on the placement, as a name that stays.
4. **Bursar and administrator place; the principal is told they may not; everyone else
   gets the flat 404.** Nothing here reaches another school.
5. **The record is never edited or deleted**, and the database allows one placement per
   payment and per entry.
"""

from django.db import IntegrityError, connection, transaction

from academics.models import Term
from fees import services, webhook
from fees.models import (
    FeeEntryKind,
    FeeLedgerEntry,
    PlacementIsFixed,
    UnmatchedPayment,
    UnmatchedPlacement,
)
from fees.tests.test_bank import GRACE_HOST, HOST
from fees.tests.test_paystack_webhook import FIFTY_THOUSAND_NAIRA, WebhookSetUp
from schools.tests.tenants import connected_to


class PlacingSetUp(WebhookSetUp):
    def setUp(self):
        super().setUp()
        # Each school gets one unmatched payment, by the webhook: the wrong customer paid in.
        self.paid("REF-A", 5_000_000, account=self.ada_no, customer="CUS_wrong")
        self.paid("REF-Z", 2_500_000, account=self.zainab_no, customer="CUS_wrong")
        self.pid = self.unmatched(self.stmarys)[0].pk
        self.zpid = self.unmatched(self.grace)[0].pk

    def place(self, user=None, *, pid=None, child=None, amount=5_000_000, reference="REF-A", host=HOST):
        child = child or self.ada
        return self.post(
            user or self.bursar,
            f"virtual/unmatched/{pid or self.pid}/placement/",
            {"student_membership_id": child.pk, "amount_kobo": amount, "reference": reference},
            host=host,
        )

    def placements(self, school):
        with connected_to(school):
            return list(UnmatchedPlacement.objects.select_related("entry"))


class PlacingOne(PlacingSetUp):
    def test_the_bursar_puts_it_on_the_child_and_it_is_in_the_account_once(self):
        before = self.balance(self.stmarys, self.ada)

        response = self.place()

        self.assertEqual(response.status_code, 201, response.content)
        (entry,) = self.entries(self.stmarys)
        self.assertEqual((entry.student_membership_id, entry.amount_kobo), (self.ada.pk, -5_000_000))
        self.assertEqual((entry.method, entry.reference), ("bank_transfer", "REF-A"))
        self.assertEqual(entry.form_key, webhook.form_key_for("REF-A"))
        self.assertEqual(self.balance(self.stmarys, self.ada), before - 5_000_000)
        body = response.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["balance_kobo"], before - 5_000_000)

    def test_it_records_who_placed_it_on_the_entry_and_the_placement(self):
        self.place()

        (entry,) = self.entries(self.stmarys)
        (placement,) = self.placements(self.stmarys)
        self.assertEqual(entry.recorded_by_id, self.bursar.pk)
        self.assertIn("placed by Bola Bursar", entry.narration)
        self.assertEqual(
            (placement.placed_by_id, placement.placed_by_name, placement.student_name, placement.entry_id),
            (self.bursar.pk, "Bola Bursar", "Ada Obi", entry.pk),
        )
        receipt = self.get(self.bursar, f"entries/{entry.pk}/receipt/").json()
        self.assertEqual(receipt["received_by"], "Bola Bursar")

    def test_the_administrator_may_place_one_too(self):
        response = self.place(self.admin)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.placements(self.stmarys)[0].placed_by_name, "Ade Admin")

    def test_the_list_says_where_it_went_and_who_put_it_there(self):
        self.place()

        row = self.get(self.principal, "virtual/unmatched/").json()["payments"][0]

        self.assertEqual(row["placed"]["student"], "Ada Obi")
        self.assertEqual(row["placed"]["placed_by"], "Bola Bursar")
        self.assertEqual(row["placed"]["student_membership_id"], self.ada.pk)

    def test_the_list_offers_placing_only_to_those_who_may_place(self):
        self.assertTrue(self.get(self.bursar, "virtual/unmatched/").json()["may_place"])
        self.assertFalse(self.get(self.principal, "virtual/unmatched/").json()["may_place"])

    def test_an_unplaced_payment_says_so(self):
        row = self.get(self.bursar, "virtual/unmatched/").json()["payments"][0]

        self.assertIsNone(row["placed"])
        self.assertEqual(row["payment_id"], self.pid)


class OnlyOnce(PlacingSetUp):
    def test_placing_it_again_on_the_same_child_is_the_placement_that_is_there(self):
        """CONTROL: dropping the `record_payment_once` form key (or the one-to-one) makes this red."""
        first = self.place()
        before = self.balance(self.stmarys, self.ada)

        second = self.place()

        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertFalse(second.json()["created"])
        self.assertEqual(len(self.entries(self.stmarys)), 1)
        self.assertEqual(len(self.placements(self.stmarys)), 1)
        self.assertEqual(self.balance(self.stmarys, self.ada), before)

    def test_placing_it_on_another_child_says_where_it_went_and_posts_nothing(self):
        self.place()

        response = self.place(child=self.chidi)

        self.assertEqual(response.status_code, 409)
        self.assertIn("already placed on Ada Obi by Bola Bursar", response.json()["detail"])
        self.assertEqual(len(self.entries(self.stmarys)), 1)
        self.assertEqual([e.student_membership_id for e in self.entries(self.stmarys)], [self.ada.pk])

    def test_a_replayed_webhook_after_it_was_placed_is_a_duplicate_and_posts_nothing(self):
        self.place()
        self.paystack.add_transaction("REF-A", 5_000_000, account_number=self.ada_no, customer_code="CUS_wrong")

        replay = self.deliver(self.event("REF-A", 5_000_000))

        self.assertEqual(replay.json()["status"], "duplicate")
        self.assertEqual(len(self.entries(self.stmarys)), 1)

    def test_money_already_in_the_ledger_is_never_posted_a_second_time(self):
        """If the ledger already holds this reference, the money is in somebody's account: refuse."""
        with connected_to(self.stmarys):
            term = Term.objects.get(is_current=True)
            services.record_payment_once(
                self.chidi, term, 5_000_000, method="bank_transfer",
                form_key=webhook.form_key_for("REF-A"), reference="REF-A",
            )

        response = self.place()

        self.assertEqual(response.status_code, 409)
        self.assertIn("already in a child's account", response.json()["detail"])
        self.assertEqual(self.placements(self.stmarys), [])
        self.assertEqual([e.student_membership_id for e in self.entries(self.stmarys)], [self.chidi.pk])

    def test_the_database_allows_one_placement_per_payment_and_per_entry(self):
        self.place()
        with connected_to(self.stmarys):
            first = UnmatchedPlacement.objects.get()
            other = services.record_payment(self.chidi, Term.objects.get(is_current=True), 100, method="cash")
            with self.assertRaises(IntegrityError), transaction.atomic():
                UnmatchedPlacement.objects.create(
                    payment=first.payment, entry=other, student_membership_id=self.chidi.pk,
                    student_name="x", placed_by_id=1, placed_by_name="x",
                )
            with self.assertRaises(IntegrityError), transaction.atomic():
                UnmatchedPlacement.objects.create(
                    payment=UnmatchedPayment.objects.create(reference="R2", amount_kobo=1, reason="no_account"),
                    entry=first.entry, student_membership_id=1, student_name="x", placed_by_id=1, placed_by_name="x",
                )

    def test_two_people_pressing_at_once_place_it_once(self):
        """The payment row is locked: the second press finds the first's placement."""
        from fees import placing

        with connected_to(self.stmarys):
            a = placing.place(self.bursar, payment_id=self.pid, child=self.ada, amount_kobo=5_000_000, reference="REF-A")
            b = placing.place(self.admin, payment_id=self.pid, child=self.ada, amount_kobo=5_000_000, reference="REF-A")

        self.assertEqual((a[1], b[1]), (True, False))
        self.assertEqual(a[0].pk, b[0].pk)
        self.assertEqual(len(self.entries(self.stmarys)), 1)


class TheServerPostsItsOwnAmount(PlacingSetUp):
    def test_a_confirmed_amount_that_is_not_the_payments_is_refused_and_nothing_is_written(self):
        """CONTROL: trusting the confirmed amount makes this red."""
        for amount in (5_000_001, 500_000, 50_000, 0, -5_000_000):
            with self.subTest(amount=amount):
                response = self.place(amount=amount)
                self.assertEqual(response.status_code, 409, amount)
        self.assertEqual(self.entries(self.stmarys), [])
        self.assertEqual(self.placements(self.stmarys), [])

    def test_a_confirmed_reference_that_is_not_the_payments_is_refused(self):
        for reference in ("REF-B", "ref-a", "REF-A ", ""):
            with self.subTest(reference=reference):
                self.assertEqual(self.place(reference=reference).status_code, 409)
        self.assertEqual(self.entries(self.stmarys), [])

    def test_an_amount_that_is_not_a_whole_number_is_refused_by_the_shape(self):
        for amount in (5000000.5, "lots", None):
            with self.subTest(amount=amount):
                self.assertEqual(self.place(amount=amount).status_code, 422)
        self.assertEqual(self.entries(self.stmarys), [])

    def test_what_is_posted_is_the_payments_own_amount_in_whole_kobo(self):
        self.place()

        (entry,) = self.entries(self.stmarys)
        with connected_to(self.stmarys):
            self.assertEqual(entry.amount_kobo, -UnmatchedPayment.objects.get(pk=self.pid).amount_kobo)
        self.assertEqual(entry.amount_kobo, -5_000_000)


class WhenThereIsNoCurrentTerm(PlacingSetUp):
    def test_it_says_so_and_posts_nothing_and_works_once_a_term_is_open(self):
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)

        refused = self.place()
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=True)
        placed = self.place()

        self.assertEqual(refused.status_code, 422)
        self.assertIn("no current term", refused.json()["detail"])
        self.assertEqual(placed.status_code, 201)
        self.assertEqual(len(self.entries(self.stmarys)), 1)


class WhoMayPlace(PlacingSetUp):
    def test_a_principal_is_told_they_may_not_and_nothing_is_posted(self):
        self.assertEqual(self.place(self.principal).status_code, 403)
        self.assertEqual(self.entries(self.stmarys), [])

    def test_a_teacher_a_parent_and_a_student_get_the_flat_404(self):
        for user in (self.teacher, self.parent, self.student_user):
            with self.subTest(user=user.username):
                self.assertEqual(self.place(user).status_code, 404)
        self.assertEqual(self.entries(self.stmarys), [])

    def test_the_portal_has_none(self):
        self.assertEqual(self.place(host="testserver").status_code, 404)

    def test_a_payment_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.place(pid=999_999).status_code, 404)

    def test_a_child_who_is_not_a_student_here_is_a_404(self):
        self.assertEqual(self.place(child=self.zainab).status_code, 404)
        self.assertEqual(self.entries(self.stmarys), [])

    def test_another_schools_bursar_cannot_reach_this_one(self):
        self.assertEqual(self.place(self.their_bursar).status_code, 403)
        self.assertEqual(self.entries(self.stmarys), [])


class TwoSchools(PlacingSetUp):
    def test_each_schools_first_unmatched_payment_has_the_same_id_and_they_never_mix(self):
        self.assertEqual(self.pid, self.zpid)  # both are `1`: the ids overlap on purpose

        self.place()  # St Mary's, id 1 -> Ada
        theirs = self.place(
            self.their_bursar, pid=self.zpid, child=self.zainab, amount=2_500_000, reference="REF-Z", host=GRACE_HOST
        )

        self.assertEqual(theirs.status_code, 201, theirs.content)
        self.assertEqual([(e.student_membership_id, e.amount_kobo) for e in self.entries(self.stmarys)],
                         [(self.ada.pk, -5_000_000)])
        self.assertEqual([(e.student_membership_id, e.amount_kobo) for e in self.entries(self.grace)],
                         [(self.zainab.pk, -2_500_000)])
        self.assertEqual([p.student_name for p in self.placements(self.grace)], ["Zainab Musa"])

    def test_placing_one_schools_payment_leaves_the_others_unplaced(self):
        self.place()

        self.assertEqual(self.placements(self.grace), [])
        row = self.get(self.their_bursar, "virtual/unmatched/", host=GRACE_HOST).json()["payments"][0]
        self.assertIsNone(row["placed"])

    def test_a_school_cannot_place_money_with_the_other_schools_reference(self):
        """Its own payment `1` is REF-A; confirming Grace's `REF-Z` for it is refused."""
        response = self.place(reference="REF-Z", amount=2_500_000)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.entries(self.stmarys), [])


class AppendOnly(PlacingSetUp):
    def test_the_model_refuses_to_edit_or_delete_a_placement(self):
        self.place()
        with connected_to(self.stmarys):
            row = UnmatchedPlacement.objects.get()
            row.placed_by_name = "Somebody else"
            with self.assertRaises(PlacementIsFixed):
                row.save()
            with self.assertRaises(PlacementIsFixed):
                row.delete()

    def test_sql_cannot_edit_or_delete_a_placement(self):
        """CONTROL: dropping the trigger makes this red."""
        self.place()
        with connected_to(self.stmarys):
            for sql in (
                "UPDATE fees_unmatchedplacement SET placed_by_name = 'x'",
                "DELETE FROM fees_unmatchedplacement",
            ):
                with self.subTest(sql=sql):
                    with self.assertRaisesMessage(IntegrityError, "never edited or deleted"):
                        with transaction.atomic(), connection.cursor() as cursor:
                            cursor.execute(sql)
            self.assertEqual(UnmatchedPlacement.objects.count(), 1)
