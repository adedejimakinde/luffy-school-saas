"""A recorded payment is never changed quietly: not edited, not deleted, only reversed.

What the homepage tells schools ("A payment cannot be edited or deleted, only
reversed with a reason"), as tests that fail if it stops being true:

1. **Edit and delete are refused everywhere**: on the instance, in bulk through
   the ORM, through a plain `QuerySet` that goes around the manager, in raw SQL,
   through the Django admin's own code paths, through a management command, and
   through every route, for every role, the administrator included.
2. **A reversal is the only correction**: it carries a written reason, who made
   it and when, names the original, and restores the child's balance. The
   original stays, marked, in the child's account and in the school's fee log;
   the class's collections, the dashboard's figures and the outstanding figures
   all come back to where they were.
3. **Once, and final**: a payment is reversed at most once, and a reversal is
   neither reversed nor edited. Each is refused by the service, the route and
   Postgres.
4. **The reason is required**, at the route, in the service and at the database.
5. **Only the bursar and the administrator reverse**; the principal, the vice
   principal and the administrator (read as the proprietor, docs/messaging.md
   D15) see every reversal in the term.
6. **Two schools never meet**: one school cannot list, read or reverse the
   other's payments, by id, by a stale object, or by any role it holds.
7. **Every school has the guards**, including one created after this migration,
   by the real `migrate_schemas` path and not only by the test template's clone.
"""

import io
import json

from django.contrib import admin
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.db.models import QuerySet
from django.test import RequestFactory, TestCase

from academics.models import Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from fees import outstanding, services
from fees.models import (
    KOBO_PER_NAIRA,
    FeeConcession,
    FeeConcessionRevocation,
    FeeEntryKind,
    FeeLedgerEntry,
    FeeSchedule,
    FeeScheduleLine,
    LedgerIsAppendOnly,
)
from fees.tests.test_fees_api import HOST, PASSWORD, TUITION, FeesApiSetUp
from home import summary
from schools.models import Domain
from schools.tests.tenants import connected_to, make_school_by_migrating

PAID = 50_000 * KOBO_PER_NAIRA
THEIR_HOST = "grace.testserver"
APPEND_ONLY = "fees_feeledgerentry is append-only"
NOT_EXACT = "A reversal must undo its entry exactly"
NOT_TWICE = "A reversal cannot itself be reversed"


class PaidSetUp(FeesApiSetUp):
    """St Mary's from `FeesApiSetUp`, with one payment recorded through the route."""

    def setUp(self):
        super().setUp()
        answer = self.pay()
        self.assertEqual(answer.status_code, 201)
        self.paid_id = answer.json()["entry"]["entry_id"]

    def the_payment(self):
        with connected_to(self.stmarys):
            return FeeLedgerEntry.objects.get(pk=self.paid_id)

    def as_it_was(self):
        """Every column of every row, to compare before and after a refused write."""
        with connected_to(self.stmarys):
            return list(FeeLedgerEntry.objects.order_by("pk").values())

    def balance(self, child=None):
        with connected_to(self.stmarys):
            return FeeLedgerEntry.objects.for_student((child or self.ada).pk).balance()

    def reverse(self, user=None, reason="Keyed twice", entry_id=None, host=HOST):
        return self.post(
            user or self.bursar,
            f"entries/{entry_id or self.paid_id}/reversal/",
            {"reason": reason},
            host=host,
        )

    def raw_reversal(self, **overrides):
        """A reversal row written past the service, as an import or `psql` would."""
        paid = self.the_payment()
        row = {
            "term_id": paid.term_id,
            "kind": FeeEntryKind.REVERSAL,
            "amount_kobo": -paid.amount_kobo,
            "narration": "Keyed twice",
            "reference": "",
            "method": "",
            "effective_on": paid.effective_on,
            "reverses_id": paid.pk,
            "student_membership_id": paid.student_membership_id,
            "student_name": paid.student_name,
            "student_reference": paid.student_reference,
            "recorded_by_id": self.bursar.pk,
        }
        row.update(overrides)
        columns = ", ".join(row)
        marks = ", ".join(["%s"] * len(row))
        with connected_to(self.stmarys):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO fees_feeledgerentry ({columns}, recorded_at) "
                    f"VALUES ({marks}, now())",
                    list(row.values()),
                )


# -- 1. edit and delete are refused everywhere ----------------------------------


class EditAndDeleteAreRefusedEverywhereTests(PaidSetUp):
    def test_the_instance_refuses_to_save_over_itself_or_delete_itself(self):
        before = self.as_it_was()
        paid = self.the_payment()
        with connected_to(self.stmarys):
            paid.amount_kobo = -1
            with self.assertRaises(LedgerIsAppendOnly):
                paid.save()
            with self.assertRaises(LedgerIsAppendOnly):
                paid.save(update_fields=["amount_kobo"])
            with self.assertRaises(LedgerIsAppendOnly):
                paid.delete()
        self.assertEqual(self.as_it_was(), before)

    def test_the_orm_refuses_a_bulk_edit_and_a_bulk_delete(self):
        before = self.as_it_was()
        with connected_to(self.stmarys):
            rows = FeeLedgerEntry.objects.filter(pk=self.paid_id)
            with self.assertRaises(LedgerIsAppendOnly):
                rows.update(narration="rewritten")
            with self.assertRaises(LedgerIsAppendOnly):
                rows.delete()
            paid = rows.get()
            paid.narration = "rewritten"
            with self.assertRaises(LedgerIsAppendOnly):
                FeeLedgerEntry.objects.bulk_update([paid], ["narration"])
            with self.assertRaises(LedgerIsAppendOnly):
                FeeLedgerEntry.objects.update_or_create(pk=self.paid_id, defaults={"narration": "x"})
        self.assertEqual(self.as_it_was(), before)

    def test_postgres_refuses_what_goes_around_the_manager(self):
        """A plain `QuerySet` skips `FeeLedgerQuerySet`'s refusal; the trigger is what is left."""
        before = self.as_it_was()
        with connected_to(self.stmarys):
            plain = QuerySet(FeeLedgerEntry).filter(pk=self.paid_id)
            with self.assertRaisesMessage(DatabaseError, APPEND_ONLY), transaction.atomic():
                plain.update(narration="rewritten")
            with self.assertRaisesMessage(DatabaseError, APPEND_ONLY), transaction.atomic():
                plain.delete()
        self.assertEqual(self.as_it_was(), before)

    def test_raw_sql_cannot_edit_or_delete_a_payment_not_even_the_columns_a_reversal_names(self):
        """Nothing a reversal needs is carved out of the guard: a reversal is a
        new row and changes no column of the payment it undoes."""
        before = self.as_it_was()
        statements = [
            "UPDATE fees_feeledgerentry SET amount_kobo = -1 WHERE id = %s",
            "UPDATE fees_feeledgerentry SET narration = 'cash, not transfer' WHERE id = %s",
            "UPDATE fees_feeledgerentry SET reverses_id = NULL WHERE id = %s",
            "UPDATE fees_feeledgerentry SET recorded_by_id = NULL WHERE id = %s",
            "DELETE FROM fees_feeledgerentry WHERE id = %s",
        ]
        with connected_to(self.stmarys):
            for sql in statements:
                with self.subTest(sql=sql):
                    with self.assertRaisesMessage(DatabaseError, APPEND_ONLY), transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(sql, [self.paid_id])
        self.assertEqual(self.as_it_was(), before)

    def test_no_fee_record_is_in_the_django_admin(self):
        """The admin is on the portal, whose schema has no fee tables at all, and
        none of the fees models is registered there."""
        for model in (FeeLedgerEntry, FeeConcession, FeeConcessionRevocation, FeeSchedule, FeeScheduleLine):
            with self.subTest(model=model.__name__):
                self.assertFalse(admin.site.is_registered(model))
        self.assertFalse(
            [m for m in admin.site._registry if m._meta.app_label == "fees"],
            "a fees model was registered in the admin",
        )

    def test_an_admin_for_the_ledger_could_not_edit_or_delete_through_any_of_its_paths(self):
        """Should somebody register one: the admin's save, delete and "delete
        selected" each reach a refusal, because each is `save()`, `delete()` or
        `QuerySet.delete()`."""
        superuser = User.objects.create_superuser("root", PASSWORD)
        request = RequestFactory().post("/admin/fees/feeledgerentry/")
        request.user = superuser
        model_admin = admin.ModelAdmin(FeeLedgerEntry, admin.AdminSite())
        before = self.as_it_was()
        with connected_to(self.stmarys):
            paid = FeeLedgerEntry.objects.get(pk=self.paid_id)
            paid.narration = "rewritten in the admin"
            with self.assertRaises(LedgerIsAppendOnly):
                model_admin.save_model(request, paid, form=None, change=True)
            with self.assertRaises(LedgerIsAppendOnly):
                model_admin.delete_model(request, paid)
            with self.assertRaises(LedgerIsAppendOnly):
                model_admin.delete_queryset(request, FeeLedgerEntry.objects.filter(pk=self.paid_id))
        self.assertEqual(self.as_it_was(), before)

    def test_a_management_command_cannot_edit_or_delete_one_either(self):
        """`manage.py shell -c` is the management command anybody with the
        server reaches for. Through the ORM it meets the queryset's refusal;
        through a cursor, the trigger."""
        before = self.as_it_was()
        through_the_orm = (
            "from fees.models import FeeLedgerEntry\n"
            f"FeeLedgerEntry.objects.filter(pk={self.paid_id}).update(amount_kobo=-1)\n"
        )
        through_sql = (
            "from django.db import connection\n"
            "with connection.cursor() as c:\n"
            f"    c.execute('DELETE FROM fees_feeledgerentry WHERE id = {self.paid_id}')\n"
        )
        with connected_to(self.stmarys):
            with self.assertRaises(LedgerIsAppendOnly):
                call_command("shell", command=through_the_orm, stdout=io.StringIO())
            with self.assertRaisesMessage(DatabaseError, APPEND_ONLY), transaction.atomic():
                call_command("shell", command=through_sql, stdout=io.StringIO())
        self.assertEqual(self.as_it_was(), before)

    def test_no_route_edits_or_deletes_a_payment_for_any_role(self):
        """The bursar, the principal, the vice principal and the administrator
        (the proprietor, as this project reads them) each try every way a route
        could change a payment. Not one exists."""
        before = self.as_it_was()
        attempts = [
            ("put", f"entries/{self.paid_id}/"),
            ("patch", f"entries/{self.paid_id}/"),
            ("delete", f"entries/{self.paid_id}/"),
            ("put", f"entries/{self.paid_id}/reversal/"),
            ("delete", f"entries/{self.paid_id}/reversal/"),
            ("put", f"entries/{self.paid_id}/receipt/"),
            ("delete", f"entries/{self.paid_id}/receipt/"),
            ("delete", f"students/{self.ada.pk}/payments/"),
            ("put", f"students/{self.ada.pk}/payments/"),
        ]
        body = json.dumps({"amount": "1", "narration": "rewritten", "amount_kobo": -1})
        for user in (self.bursar, self.admin, self.principal, self.vp):
            self.client.force_login(user)
            for method, path in attempts:
                with self.subTest(user=user.username, method=method, path=path):
                    answer = getattr(self.client, method)(
                        f"/api/fees/{path}", data=body, content_type="application/json", HTTP_HOST=HOST
                    )
                    self.assertIn(answer.status_code, (404, 405))
        self.assertEqual(self.as_it_was(), before)


# -- 2. a reversal restores the balance, and both entries stay in both histories --


class AReversalIsTheOnlyCorrectionTests(PaidSetUp):
    def test_a_reversal_restores_the_balance_and_the_original_stays_untouched(self):
        before = self.as_it_was()
        self.assertEqual(self.balance(), TUITION - PAID)

        answer = self.reverse(reason="Cheque bounced")

        self.assertEqual(answer.status_code, 201)
        self.assertEqual(answer.json()["balance_kobo"], TUITION)
        self.assertEqual(self.balance(), TUITION)
        # The payment's row is exactly what it was; the reversal is one new row.
        after = self.as_it_was()
        self.assertEqual(after[: len(before)], before)
        [reversal] = after[len(before):]
        self.assertEqual(reversal["kind"], FeeEntryKind.REVERSAL)
        self.assertEqual(reversal["reverses_id"], self.paid_id)
        self.assertEqual(reversal["amount_kobo"], PAID)
        self.assertEqual(reversal["narration"], "Cheque bounced")
        self.assertEqual(reversal["recorded_by_id"], self.bursar.pk)
        self.assertIsNotNone(reversal["recorded_at"])

    def test_the_childs_account_shows_both_with_the_reason_who_and_when(self):
        reversal_id = self.reverse(reason="Cheque bounced").json()["entry"]["entry_id"]

        rows = {e["entry_id"]: e for e in self.get(self.principal, f"students/{self.ada.pk}/").json()["entries"]}

        original = rows[self.paid_id]
        self.assertEqual(original["kind"], "payment")
        self.assertEqual(original["amount_kobo"], -PAID)
        self.assertFalse(original["may_reverse"])
        self.assertEqual(original["reversal"]["entry_id"], reversal_id)
        self.assertEqual(original["reversal"]["reason"], "Cheque bounced")
        self.assertEqual(original["reversal"]["by"], "Bola Bursar")
        self.assertTrue(original["reversal"]["at"])
        self.assertEqual(original["recorded_by"], "Bola Bursar")

        undo = rows[reversal_id]
        self.assertEqual(undo["kind"], "reversal")
        self.assertFalse(undo["may_reverse"])
        self.assertEqual(undo["reverses"]["entry_id"], self.paid_id)
        self.assertEqual(undo["reverses"]["amount_kobo"], -PAID)
        self.assertEqual(undo["recorded_by"], "Bola Bursar")

    def test_the_schools_fee_log_shows_both_and_the_reversals_list_shows_the_reversal(self):
        reversal_id = self.reverse(reason="Cheque bounced").json()["entry"]["entry_id"]

        everything = self.get(self.principal, f"log/?term_id={self.term_id}").json()
        ids = [e["entry_id"] for e in everything["entries"]]
        self.assertIn(self.paid_id, ids)
        self.assertIn(reversal_id, ids)
        self.assertEqual(ids, sorted(ids, reverse=True), "newest typed first")
        logged = {e["entry_id"]: e for e in everything["entries"]}
        self.assertEqual(logged[self.paid_id]["reversal"]["reason"], "Cheque bounced")
        self.assertEqual(logged[self.paid_id]["student"], "Ada Obi")
        self.assertEqual(everything["reversals"], 1)

        only = self.get(self.principal, f"log/?term_id={self.term_id}&reversals_only=true").json()
        self.assertTrue(only["reversals_only"])
        self.assertEqual([e["entry_id"] for e in only["entries"]], [reversal_id])
        self.assertEqual(only["entries"][0]["reverses"]["entry_id"], self.paid_id)
        self.assertEqual(only["entries"][0]["recorded_by"], "Bola Bursar")

    def test_the_receipt_says_it_was_reversed_and_by_whom(self):
        self.reverse(reason="Cheque bounced")

        receipt = self.get(self.principal, f"entries/{self.paid_id}/receipt/").json()

        self.assertEqual(receipt["reversed"]["reason"], "Cheque bounced")
        self.assertEqual(receipt["reversed"]["by"], "Bola Bursar")

    def test_collected_outstanding_and_the_dashboard_come_back_to_where_they_were(self):
        def figures():
            with connected_to(self.stmarys):
                term = Term.objects.get(pk=self.term_id)
                money = summary.fees(term)
                owes = outstanding.total(outstanding.owing(term))
            books = self.get(self.principal, f"classes/?term_id={self.term_id}").json()
            [jss1a] = books["classes"]
            return {
                "dashboard collected": money.collected_kobo,
                "dashboard billed": money.billed_kobo,
                "outstanding": owes.kobo,
                "outstanding this term": owes.this_term_kobo,
                "books outstanding": books["outstanding_kobo"],
                "class collected": jss1a["collected_kobo"],
                "class billed": jss1a["billed_kobo"],
                "class outstanding": jss1a["outstanding_kobo"],
            }

        paid = figures()
        self.assertEqual(paid["dashboard collected"], PAID)
        self.assertEqual(paid["class collected"], PAID)
        self.assertEqual(paid["outstanding"], TUITION - PAID)

        self.reverse(reason="Cheque bounced")
        reversed_ = figures()

        self.assertEqual(
            reversed_,
            {
                "dashboard collected": 0,
                "dashboard billed": TUITION,
                "outstanding": TUITION,
                "outstanding this term": TUITION,
                "books outstanding": TUITION,
                "class collected": 0,
                "class billed": TUITION,
                "class outstanding": TUITION,
            },
        )

        # And the right payment, posted fresh, counts once.
        self.assertEqual(self.pay(amount="40,000").status_code, 201)
        corrected = figures()
        self.assertEqual(corrected["dashboard collected"], 40_000 * KOBO_PER_NAIRA)
        self.assertEqual(corrected["class collected"], 40_000 * KOBO_PER_NAIRA)
        self.assertEqual(corrected["outstanding"], TUITION - 40_000 * KOBO_PER_NAIRA)


# -- 3. once, and final ---------------------------------------------------------


class OnceAndFinalTests(PaidSetUp):
    def test_a_payment_is_reversed_once_by_the_route_the_service_and_postgres(self):
        self.assertEqual(self.reverse().status_code, 201)

        again = self.reverse(user=self.admin, reason="Again")
        self.assertEqual(again.status_code, 409)
        with connected_to(self.stmarys):
            with self.assertRaises(services.AlreadyReversed):
                services.reverse_entry(
                    FeeLedgerEntry.objects.get(pk=self.paid_id), reason="Again", recorded_by=self.admin
                )
        with self.assertRaisesMessage(DatabaseError, "an_entry_is_reversed_at_most_once"), transaction.atomic():
            self.raw_reversal()

        self.assertEqual(len(self.entries(FeeEntryKind.REVERSAL)), 1)
        self.assertEqual(self.balance(), TUITION)

    def test_a_reversal_cannot_be_reversed_by_the_route_the_service_or_postgres(self):
        reversal_id = self.reverse().json()["entry"]["entry_id"]

        self.assertEqual(self.reverse(entry_id=reversal_id).status_code, 409)
        with connected_to(self.stmarys):
            reversal = FeeLedgerEntry.objects.get(pk=reversal_id)
            with self.assertRaises(services.CannotReverse):
                services.reverse_entry(reversal, reason="Undo the undo", recorded_by=self.bursar)
        with self.assertRaisesMessage(DatabaseError, NOT_TWICE), transaction.atomic():
            self.raw_reversal(reverses_id=reversal_id, amount_kobo=-reversal.amount_kobo)

        self.assertEqual(len(self.entries(FeeEntryKind.REVERSAL)), 1)

    def test_a_reversal_cannot_be_edited_or_deleted_either(self):
        reversal_id = self.reverse().json()["entry"]["entry_id"]
        before = self.as_it_was()
        with connected_to(self.stmarys):
            reversal = FeeLedgerEntry.objects.get(pk=reversal_id)
            reversal.narration = "a better reason"
            with self.assertRaises(LedgerIsAppendOnly):
                reversal.save()
            with self.assertRaises(LedgerIsAppendOnly):
                reversal.delete()
            for sql in (
                "UPDATE fees_feeledgerentry SET narration = 'a better reason' WHERE id = %s",
                "DELETE FROM fees_feeledgerentry WHERE id = %s",
            ):
                with self.assertRaisesMessage(DatabaseError, APPEND_ONLY), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql, [reversal_id])
        self.assertEqual(self.as_it_was(), before)

    def test_postgres_refuses_a_reversal_that_does_not_undo_its_payment_exactly(self):
        """The rules `clean()` asks, held where an import or `psql` meets them."""
        with connected_to(self.stmarys):
            other_term = Term.objects.create(
                session="2025/2026", name=TermName.SECOND, starts_on="2026-01-05", ends_on="2026-04-02"
            )
        for wrong in (
            {"amount_kobo": PAID // 2},
            {"amount_kobo": PAID * 2},
            {"student_membership_id": self.chidi.pk, "student_name": "Chidi Okafor"},
            {"term_id": other_term.pk},
        ):
            with self.subTest(wrong=wrong):
                with self.assertRaisesMessage(DatabaseError, NOT_EXACT), transaction.atomic():
                    self.raw_reversal(**wrong)
        self.assertEqual(self.entries(FeeEntryKind.REVERSAL), [])
        self.assertEqual(self.balance(), TUITION - PAID)
        self.assertEqual(self.balance(self.chidi), 0)


# -- 4. the reason, and the person, are required ---------------------------------


class AReasonIsRequiredTests(PaidSetUp):
    def test_the_route_refuses_no_reason_and_writes_nothing(self):
        before = self.as_it_was()
        for reason in ("", "   ", "\n\t"):
            with self.subTest(reason=reason):
                self.assertEqual(self.reverse(reason=reason).status_code, 422)
        missing = self.post(self.bursar, f"entries/{self.paid_id}/reversal/", {})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(self.as_it_was(), before)

    def test_the_service_refuses_no_reason_or_no_person(self):
        before = self.as_it_was()
        paid = self.the_payment()
        with connected_to(self.stmarys):
            for reason in (None, "", "   "):
                with self.subTest(reason=reason):
                    with self.assertRaises(services.NoReason):
                        services.reverse_entry(paid, reason=reason, recorded_by=self.bursar)
            with self.assertRaises(services.NoReason):
                services.reverse_entry(paid, reason="x" * 256, recorded_by=self.bursar)
            with self.assertRaises(services.CannotReverse):
                services.reverse_entry(paid, reason="Keyed twice", recorded_by=None)
            with self.assertRaises(TypeError, msg="the reason is not optional"):
                services.reverse_entry(paid, recorded_by=self.bursar)
        self.assertEqual(self.as_it_was(), before)

    def test_postgres_refuses_a_reversal_with_no_reason_or_no_person(self):
        for wrong, constraint in (
            ({"narration": ""}, "a_reversal_says_why"),
            ({"narration": "   "}, "a_reversal_says_why"),
            ({"recorded_by_id": None}, "a_reversal_says_who"),
        ):
            with self.subTest(wrong=wrong):
                with self.assertRaisesMessage(DatabaseError, constraint), transaction.atomic():
                    self.raw_reversal(**wrong)
        self.assertEqual(self.entries(FeeEntryKind.REVERSAL), [])


# -- 5. who reverses, and who sees the reversals --------------------------------


class WhoReversesAndWhoSeesTests(PaidSetUp):
    def test_only_the_roles_that_record_payments_can_reverse_one(self):
        for user in (self.principal, self.vp):
            with self.subTest(user=user.username):
                self.assertEqual(self.reverse(user=user).status_code, 403)
        for user in (self.teacher, self.parent, self.student_user):
            with self.subTest(user=user.username):
                answer = self.reverse(user=user)
                self.assertEqual(answer.status_code, 404)
                self.assertEqual(answer.content, self.missing())
        self.assertEqual(self.entries(FeeEntryKind.REVERSAL), [])

        self.assertEqual(self.reverse(user=self.admin).status_code, 201)

    def test_the_principal_and_the_proprietor_see_every_reversal_this_term(self):
        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
            second = services.record_payment(self.chidi, term, 10_000 * KOBO_PER_NAIRA, method="cash")
        self.reverse(reason="Keyed twice")
        self.reverse(user=self.admin, reason="Wrong child", entry_id=second.pk)

        for user in (self.principal, self.admin, self.vp, self.bursar):
            with self.subTest(user=user.username):
                answer = self.get(user, f"log/?term_id={self.term_id}&reversals_only=true")
                self.assertEqual(answer.status_code, 200)
                listed = answer.json()["entries"]
                self.assertEqual(
                    [(e["narration"], e["recorded_by"], e["student"]) for e in listed],
                    [("Wrong child", "Ade Admin", "Chidi Okafor"), ("Keyed twice", "Bola Bursar", "Ada Obi")],
                )

    def test_nobody_else_learns_the_log_exists(self):
        for user in (self.teacher, self.parent, self.student_user):
            with self.subTest(user=user.username):
                answer = self.get(user, "log/?reversals_only=true")
                self.assertEqual(answer.status_code, 404)
                self.assertEqual(answer.content, self.missing())

    def test_the_log_costs_the_same_whatever_the_number_of_entries(self):
        def queries():
            from django.db import connection as conn
            from django.test.utils import CaptureQueriesContext

            self.client.force_login(self.principal)
            with CaptureQueriesContext(conn) as captured:
                self.assertEqual(
                    self.client.get(f"/api/fees/log/?term_id={self.term_id}", HTTP_HOST=HOST).status_code, 200
                )
            return len(captured)

        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
        self.reverse()
        few = queries()
        with connected_to(self.stmarys):
            for _ in range(6):
                entry = services.record_payment(self.chidi, term, 1_000, method="cash", recorded_by=self.admin)
                services.reverse_entry(entry, reason="Test", recorded_by=self.bursar)
        self.assertEqual(queries(), few)


# -- 6. two schools never meet --------------------------------------------------


class TwoSchoolsTests(PaidSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.grace, domain=THEIR_HOST, is_primary=True)
        self.their_bursar = User.objects.create_user("gbenga", PASSWORD, full_name="Gbenga Bursar")
        grant_membership(self.their_bursar, self.grace, Role.BURSAR)
        self.their_head = User.objects.create_user("halima", PASSWORD, full_name="Halima Head")
        grant_membership(self.their_head, self.grace, Role.PRINCIPAL)
        with connected_to(self.grace):
            term = Term.objects.get()
            # Grace's own ids run on their own sequence, so this payment's id
            # is very likely one St Mary's also uses: a lookup by id alone
            # would land on the wrong school's row.
            self.theirs = services.record_payment(
                self.zainab, term, 30_000 * KOBO_PER_NAIRA, method="cash", recorded_by=self.their_bursar
            )
        self.their_term_id = term.pk

    def grace_as_it_was(self):
        with connected_to(self.grace):
            return list(FeeLedgerEntry.objects.order_by("pk").values())

    def test_neither_school_lists_the_others_entries(self):
        ours = self.get(self.principal, "log/").json()
        self.assertNotIn("Zainab Musa", [e["student"] for e in ours["entries"]])

        theirs = self.get(self.their_head, "log/", host=THEIR_HOST).json()
        self.assertEqual([e["student"] for e in theirs["entries"]], ["Zainab Musa", "Zainab Musa"])
        self.assertNotIn("Ada Obi", json.dumps(theirs))

    def test_one_schools_staff_cannot_read_or_reverse_on_the_others_host(self):
        before = self.as_it_was(), self.grace_as_it_was()
        # Refused before the books are asked anything: a login with no place at
        # this school is turned away by the session itself (403), and the
        # books would answer their flat 404 if it were not.
        for user in (self.their_bursar, self.their_head):
            with self.subTest(user=user.username):
                for answer in (
                    self.get(user, "log/"),
                    self.get(user, "log/?reversals_only=true"),
                    self.get(user, f"students/{self.ada.pk}/"),
                    self.reverse(user=user, entry_id=self.paid_id),
                ):
                    self.assertIn(answer.status_code, (403, 404))
                    self.assertNotIn(b"Ada Obi", answer.content)
        self.assertEqual((self.as_it_was(), self.grace_as_it_was()), before)

    def test_reversing_their_entry_id_here_never_touches_their_books(self):
        """By id, on St Mary's host: the id names St Mary's own row if it has
        one, and nothing otherwise. Grace's payment is never the one reversed."""
        grace_before = self.grace_as_it_was()
        with connected_to(self.stmarys):
            ours = FeeLedgerEntry.objects.filter(pk=self.theirs.pk).first()

        answer = self.reverse(entry_id=self.theirs.pk, reason="Not ours to reverse")

        if ours is None:
            self.assertEqual(answer.status_code, 404)
        else:
            self.assertIn(answer.status_code, (201, 409))
            if answer.status_code == 201:
                self.assertEqual(answer.json()["entry"]["reverses_id"], ours.pk)
                self.assertNotEqual(answer.json()["entry"]["reverses"]["amount_kobo"], self.theirs.amount_kobo)
        self.assertEqual(self.grace_as_it_was(), grace_before)
        with connected_to(self.grace):
            self.assertFalse(FeeLedgerEntry.objects.filter(kind=FeeEntryKind.REVERSAL).exists())

    def test_their_entry_handed_to_the_service_here_is_refused(self):
        """A stale object from one school, reversed while connected to the
        other, would name some other row by the same number. Refused, and
        neither school's books change."""
        with connected_to(self.stmarys):
            same_id = FeeLedgerEntry.objects.filter(pk=self.theirs.pk).first()
        before = self.as_it_was(), self.grace_as_it_was()
        with connected_to(self.stmarys):
            with self.assertRaises(services.CannotReverse):
                services.reverse_entry(self.theirs, reason="Wrong school", recorded_by=self.bursar)
        self.assertEqual((self.as_it_was(), self.grace_as_it_was()), before)
        # The fixture is what makes this a real test: Grace's payment shares its
        # id with a row St Mary's has, or with none. Either way it is refused.
        self.assertTrue(same_id is None or same_id.student_membership_id != self.zainab.pk)

    def test_their_own_reversal_stays_theirs(self):
        answer = self.reverse(user=self.their_bursar, entry_id=self.theirs.pk, reason="Keyed twice", host=THEIR_HOST)
        self.assertEqual(answer.status_code, 201)

        ours = self.get(self.principal, "log/?reversals_only=true").json()
        self.assertEqual(ours["entries"], [])
        self.assertEqual(ours["reversals"], 0)
        theirs = self.get(self.their_head, "log/?reversals_only=true", host=THEIR_HOST).json()
        self.assertEqual([e["recorded_by"] for e in theirs["entries"]], ["Gbenga Bursar"])
        self.assertEqual(self.balance(), TUITION - PAID, "St Mary's books did not move")


# -- 7. every school has the guards, including the next one ------------------------


GUARDS = {"fees_ledger_append_only", "fees_reversal_is_exact"}
CONSTRAINTS = {"a_reversal_says_why", "a_reversal_says_who", "an_entry_is_reversed_at_most_once"}


def guards_in(schema):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE c.relnamespace = %s::regnamespace AND c.relname = 'fees_feeledgerentry' "
            "AND NOT t.tgisinternal AND t.tgenabled <> 'D'",
            [schema],
        )
        triggers = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE connamespace = %s::regnamespace "
            "UNION SELECT indexname FROM pg_indexes WHERE schemaname = %s",
            [schema, schema],
        )
        constraints = {row[0] for row in cursor.fetchall()}
    return triggers, constraints


class EverySchoolHasTheGuardsTests(TestCase):
    def test_every_school_including_one_created_later_by_migrating(self):
        """`make_school_by_migrating()` is the path a school created in
        production takes: `CREATE SCHEMA` and every migration from `0001`."""
        later = make_school_by_migrating("Later Academy", "later", "later_academy")
        triggers, constraints = guards_in(later.schema_name)
        self.assertTrue(GUARDS <= triggers, triggers)
        self.assertTrue(CONSTRAINTS <= constraints)

        with connected_to(later):
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM fees_feeledgerentry")
            # The guard fires in the new school, on a row of the new school.
            term = Term.objects.create(session="2026/2027", name=TermName.FIRST, starts_on="2026-09-14", ends_on="2026-12-11")
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO fees_feeledgerentry (term_id, student_membership_id, student_name, "
                    "student_reference, kind, amount_kobo, narration, reference, method, effective_on, "
                    "recorded_at) VALUES (%s, 1, 'A child', '', 'charge', 100, 'Tuition', '', '', "
                    "'2026-09-14', now()) RETURNING id",
                    [term.pk],
                )
                [entry_id] = cursor.fetchone()
            with self.assertRaisesMessage(DatabaseError, APPEND_ONLY), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE fees_feeledgerentry SET amount_kobo = 1 WHERE id = %s", [entry_id])
        connection.set_schema_to_public()

    def test_the_schools_the_suite_clones_have_them_too(self):
        from schools.tests.tenants import make_school

        for schema in ("clone_one", "clone_two"):
            make_school(schema, schema.replace("_", "-"), schema)
            with self.subTest(schema=schema):
                triggers, constraints = guards_in(schema)
                self.assertTrue(GUARDS <= triggers, triggers)
                self.assertTrue(CONSTRAINTS <= constraints)
