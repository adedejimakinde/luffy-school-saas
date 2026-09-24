"""The bursar's routes: balances, one child's account, a payment, an undo and
a receipt. Fees B1, decided 2026-09-24.

Two schools throughout. St Mary's is under test; Grace Academy has its own
child, so a lookup that forgot `school=` would find her.

Six claims, each with the test that fails without it:

1. The bursar and the administrator write; the principal and the vice
   principal (academic) read and are told they may not write; everybody else
   gets the books' own flat 404.
2. Another school's child is not found — not "found and refused".
3. Money that moved says how, at the database, and nothing else claims to.
4. `12.345` naira is refused, not rounded.
5. The same form twice is one payment.
6. A credit is not a debt (the renderer; `tests/js/fees.test.js`).
"""

import json
import uuid
from datetime import date, timedelta

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from fees import services
from fees.models import KOBO_PER_NAIRA, FeeEntryKind, FeeLedgerEntry
from fees.money import NotAnAmount, kobo_from_naira
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from tests.refusals import RefusalAssertions

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"
TUITION = 150_000 * KOBO_PER_NAIRA
NOBODY = 10**9


class FeesApiSetUp(RefusalAssertions, TestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        def staff(username, name, role, school=None):
            user = User.objects.create_user(username, PASSWORD, full_name=name)
            grant_membership(user, school or self.stmarys, role)
            return user

        self.bursar = staff("bola", "Bola Bursar", Role.BURSAR)
        self.admin = staff("ade", "Ade Admin", Role.ADMIN)
        self.principal = staff("ngozi", "Ngozi Head", Role.PRINCIPAL)
        self.vp = staff("vera", "Vera Vp", Role.VICE_PRINCIPAL_ACADEMIC)
        self.teacher = staff("kemi", "Kemi Teacher", Role.TEACHER)
        self.parent = staff("uche", "Uche Parent", Role.PARENT)

        self.ada = self.child("ada", "Ada Obi", self.stmarys, reference="SM/001")
        self.chidi = self.child("chidi", "Chidi Okafor", self.stmarys)
        self.zainab = self.child("zainab", "Zainab Musa", self.grace)

        with connected_to(self.stmarys):
            term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
                is_current=True,
            )
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            for child in (self.ada, self.chidi):
                academics.place_student(group, term, child)
            services.charge(self.ada, term, TUITION, narration="First term tuition")
        with connected_to(self.grace):
            their_term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
                is_current=True,
            )
            services.charge(self.zainab, their_term, TUITION, narration="Tuition")
        self.term_id, self.group_id = term.pk, group.pk
        self.student_user = self.ada.user

    def tearDown(self):
        connection.set_schema_to_public()

    def child(self, username, name, school, reference=""):
        membership = enroll_student(
            User.objects.create_user(username, PASSWORD, full_name=name), school
        )
        if reference:
            membership.reference = reference
            membership.save(update_fields=["reference"])
        return membership

    # -- requests -------------------------------------------------------------

    def get(self, user, path, host=HOST):
        self.client.force_login(user)
        return self.client.get(f"/api/fees/{path}", HTTP_HOST=host)

    def post(self, user, path, body, host=HOST):
        self.client.force_login(user)
        return self.client.post(
            f"/api/fees/{path}",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=host,
        )

    def payment(self, **overrides):
        body = {
            "term_id": self.term_id,
            "amount": "50,000.00",
            "method": "cash",
            "reference": "",
            "effective_on": str(date(2025, 10, 1)),
            "form_key": str(uuid.uuid4()),
        }
        body.update(overrides)
        return body

    def pay(self, user=None, child=None, **overrides):
        child = child or self.ada
        return self.post(user or self.bursar, f"students/{child.pk}/payments/", self.payment(**overrides))

    def entries(self, kind=None, school=None):
        with connected_to(school or self.stmarys):
            rows = FeeLedgerEntry.objects.all()
            if kind:
                rows = rows.filter(kind=kind)
            return list(rows)

    def missing(self):
        """The body a principal gets for an account that does not exist: the
        books' flat 404, and every refusal below must be exactly this."""
        answer = self.get(self.principal, f"students/{NOBODY}/")
        self.assertEqual(answer.status_code, 404, "the fixture's refusal moved")
        return answer.content


class WhoMayReadTests(FeesApiSetUp):
    def test_the_bursar_the_admin_the_principal_and_the_vp_read_an_account(self):
        """The control, and it runs first."""
        for user in (self.bursar, self.admin, self.principal, self.vp):
            with self.subTest(user=user.username):
                answer = self.get(user, f"students/{self.ada.pk}/")

                self.assertEqual(answer.status_code, 200)
                body = answer.json()
                self.assertEqual((body["student"], body["reference"]), ("Ada Obi", "SM/001"))
                self.assertEqual(body["balance_kobo"], TUITION)

    def test_a_teacher_a_parent_and_a_student_get_the_books_own_flat_404(self):
        """**The refusal's identity**: exactly the body a principal gets for a
        child who does not exist, on every read."""
        missing = self.missing()
        for user in (self.teacher, self.parent, self.student_user):
            for path in (
                "classes/",
                f"classes/{self.group_id}/?term_id={self.term_id}",
                f"students/{self.ada.pk}/",
            ):
                with self.subTest(user=user.username, path=path):
                    answer = self.get(user, path)

                    self.assertEqual(answer.status_code, 404)
                    self.assertEqual(answer.content, missing)
                    self.assertNotIn(b"Ada", answer.content)

    def test_there_are_no_books_on_the_portal(self):
        self.assertEqual(self.get(self.bursar, "classes/", host="testserver").status_code, 404)


class WhoMayWriteTests(FeesApiSetUp):
    def test_the_bursar_and_the_admin_record_a_payment(self):
        for user, amount in ((self.bursar, "10,000"), (self.admin, "20,000")):
            with self.subTest(user=user.username):
                answer = self.pay(user, amount=amount)

                self.assertEqual(answer.status_code, 201, answer.content)
        self.assertEqual(len(self.entries(FeeEntryKind.PAYMENT)), 2)

    def test_the_principal_and_the_vp_are_told_they_may_not_write(self):
        """They read the books, so the account's existence is not news: a 403
        with its own sentence — not the flat 404, and not a payment.

        CONTROL 1: the write routes skipping the authority check make this red.
        """
        for user in (self.principal, self.vp):
            with self.subTest(user=user.username):
                answer = self.pay(user)

                self.assertEqual(answer.status_code, 403)
                self.assertEqual(
                    answer.json(),
                    {"detail": "Payments and reversals are recorded by the bursar or an administrator."},
                )
        self.assertEqual(self.entries(FeeEntryKind.PAYMENT), [])

    def test_a_teacher_writing_gets_the_flat_404(self):
        """CONTROL 1 also: a teacher's payment is refused as though there were
        no such child."""
        missing = self.missing()
        [charge] = self.entries(FeeEntryKind.CHARGE)

        paid = self.pay(self.teacher)
        undone = self.post(self.teacher, f"entries/{charge.pk}/reversal/", {"reason": "Wrong"})

        for answer in (paid, undone):
            self.assertEqual(answer.status_code, 404)
            self.assertEqual(answer.content, missing)
        self.assertEqual(len(self.entries()), 1, "the teacher's write reached the books")

    def test_the_principal_may_not_undo_either(self):
        [charge] = self.entries(FeeEntryKind.CHARGE)

        answer = self.post(self.principal, f"entries/{charge.pk}/reversal/", {"reason": "Wrong"})

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(self.entries(FeeEntryKind.REVERSAL), [])


class AnotherSchoolsChildTests(FeesApiSetUp):
    def test_their_child_is_not_found_here(self):
        """Zainab is Grace's. On St Mary's host her account is exactly as
        missing as an id nobody holds — no name, no balance.

        CONTROL 2: the child lookup losing `school=` makes this red.
        """
        missing = self.missing()

        answer = self.get(self.bursar, f"students/{self.zainab.pk}/")

        self.assertEqual(answer.status_code, 404)
        self.assertEqual(answer.content, missing)
        self.assertNotIn(b"Zainab", answer.content)

    def test_a_payment_against_their_child_is_refused_and_writes_nothing(self):
        answer = self.pay(child=self.zainab)

        self.assertEqual(answer.status_code, 404)
        self.assertEqual(self.entries(FeeEntryKind.PAYMENT), [])
        self.assertEqual(self.entries(FeeEntryKind.PAYMENT, school=self.grace), [])


class HowMoneyMovedTests(FeesApiSetUp):
    def entry(self, **fields):
        with connected_to(self.stmarys):
            values = {
                "term_id": self.term_id,
                "student_membership_id": self.ada.pk,
                "student_name": "Ada Obi",
                "narration": "Test",
                "effective_on": date(2025, 10, 1),
            }
            values.update(fields)
            return FeeLedgerEntry.objects.create(**values)

    def test_a_payment_without_a_method_is_refused_by_the_database(self):
        """Not only by the service: an import or a shell meets it too.

        CONTROL 3: dropping the method constraint makes this red.
        """
        with self.assertRefusedBy("a_method_on_money_that_moved_and_nowhere_else"), transaction.atomic():
            self.entry(kind=FeeEntryKind.PAYMENT, amount_kobo=-TUITION, method="")

    def test_a_charge_with_a_method_is_refused_by_the_database(self):
        """A charge that says "cash" reads, to anyone totalling the till, as
        money received. CONTROL 3 also."""
        with self.assertRefusedBy("a_method_on_money_that_moved_and_nowhere_else"), transaction.atomic():
            self.entry(kind=FeeEntryKind.CHARGE, amount_kobo=TUITION, method="cash")

    def test_a_method_off_the_list_is_refused_by_the_database(self):
        with self.assertRefusedBy("a_method_on_money_that_moved_and_nowhere_else"), transaction.atomic():
            self.entry(kind=FeeEntryKind.PAYMENT, amount_kobo=-TUITION, method="barter")

    def test_a_bank_transfer_without_a_reference_is_refused_by_the_database(self):
        with self.assertRefusedBy("a_bank_transfer_names_its_reference"), transaction.atomic():
            self.entry(kind=FeeEntryKind.PAYMENT, amount_kobo=-TUITION, method="bank_transfer", reference="  ")

    def test_the_route_says_so_in_a_sentence(self):
        cases = (
            ({"method": ""}, "Say how the money moved"),
            ({"method": "bank_transfer", "reference": " "}, "teller or transfer reference"),
        )
        for overrides, words in cases:
            with self.subTest(**overrides):
                answer = self.pay(**overrides)

                self.assertEqual(answer.status_code, 422)
                self.assertIn(words, answer.json()["detail"])
        self.assertEqual(self.entries(FeeEntryKind.PAYMENT), [])

    def test_a_transfer_with_its_reference_is_recorded_with_both(self):
        answer = self.pay(method="bank_transfer", reference="GTB/2025/0099817")

        self.assertEqual(answer.status_code, 201)
        [paid] = self.entries(FeeEntryKind.PAYMENT)
        self.assertEqual((paid.method, paid.reference), ("bank_transfer", "GTB/2025/0099817"))
        self.assertEqual(answer.json()["entry"]["method_label"], "Bank transfer")

    def test_a_payment_cannot_be_dated_after_today(self):
        answer = self.pay(effective_on=str(timezone.localdate() + timedelta(days=1)))

        self.assertEqual(answer.status_code, 422)
        self.assertEqual(self.entries(FeeEntryKind.PAYMENT), [])


class NairaTests(FeesApiSetUp):
    def test_what_a_bursar_types_becomes_kobo(self):
        for typed, kobo in (
            ("15,000.50", 1_500_050),
            ("15000.5", 1_500_050),
            ("₦2,500", 250_000),
            ("1,234,567.89", 123_456_789),
            (" 700 ", 70_000),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(kobo_from_naira(typed), kobo)

    def test_a_third_decimal_place_is_refused_not_rounded(self):
        """`12.345` is a typo — of `12,345`, most likely — and rounding it to
        ₦12.35 would put a number nobody meant on a receipt a parent keeps.

        CONTROL 4: rounding instead of refusing makes this red.
        """
        with self.assertRaisesRegex(NotAnAmount, "two decimal places"):
            kobo_from_naira("12.345")

        answer = self.pay(amount="12.345")

        self.assertEqual(answer.status_code, 422)
        self.assertIn("two decimal places", answer.json()["detail"])
        self.assertEqual(self.entries(FeeEntryKind.PAYMENT), [])

    def test_nothing_else_that_is_not_an_amount_gets_through(self):
        for typed in ("-500", "0", "0.00", "", "abc", "1,50", "12,34.5", "1e5", "15 000,50"):
            with self.subTest(typed=typed):
                with self.assertRaises(NotAnAmount):
                    kobo_from_naira(typed)

    def test_the_amount_reaches_the_books_to_the_kobo(self):
        self.pay(amount="15,000.50")

        [paid] = self.entries(FeeEntryKind.PAYMENT)
        self.assertEqual(paid.amount_kobo, -1_500_050)


class OneFormOnePaymentTests(FeesApiSetUp):
    def test_the_same_form_twice_is_one_payment(self):
        """A double click, or a phone retrying a request whose answer it never
        got. The second answer is the first payment, and says so.

        CONTROL 5: dropping the form key's uniqueness makes this red.
        """
        key = str(uuid.uuid4())

        first = self.pay(form_key=key)
        second = self.pay(form_key=key)

        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(len(self.entries(FeeEntryKind.PAYMENT)), 1)
        self.assertTrue(first.json()["posted"])
        self.assertFalse(second.json()["posted"])
        self.assertEqual(second.json()["entry"]["entry_id"], first.json()["entry"]["entry_id"])

    def test_one_key_with_a_different_payment_is_refused(self):
        """Answering with the first entry would tell the bursar a payment was
        recorded that was not."""
        key = str(uuid.uuid4())
        self.pay(form_key=key, amount="10,000")

        answer = self.pay(form_key=key, amount="20,000")

        self.assertEqual(answer.status_code, 409)
        self.assertIn("different payment", answer.json()["detail"])
        self.assertEqual(len(self.entries(FeeEntryKind.PAYMENT)), 1)

    def test_two_forms_are_two_payments(self):
        self.pay()
        self.pay()

        self.assertEqual(len(self.entries(FeeEntryKind.PAYMENT)), 2)


class UndoingTests(FeesApiSetUp):
    def test_an_undo_posts_a_new_entry_and_never_edits_the_old_one(self):
        paid = self.pay().json()["entry"]

        answer = self.post(self.bursar, f"entries/{paid['entry_id']}/reversal/", {"reason": "Keyed twice"})

        self.assertEqual(answer.status_code, 201)
        body = answer.json()
        self.assertEqual(body["entry"]["kind"], "reversal")
        self.assertEqual(body["entry"]["narration"], "Keyed twice")
        self.assertEqual(body["entry"]["reverses_id"], paid["entry_id"])
        self.assertEqual(body["balance_kobo"], TUITION)
        with connected_to(self.stmarys):
            original = FeeLedgerEntry.objects.get(pk=paid["entry_id"])
        self.assertEqual((original.amount_kobo, original.narration), (-50_000 * KOBO_PER_NAIRA, "Payment received"))

    def test_an_undo_says_why(self):
        [charge] = self.entries(FeeEntryKind.CHARGE)

        for reason in ("", "   "):
            with self.subTest(reason=reason):
                answer = self.post(self.bursar, f"entries/{charge.pk}/reversal/", {"reason": reason})

                self.assertEqual(answer.status_code, 422)
        self.assertEqual(self.entries(FeeEntryKind.REVERSAL), [])

    def test_an_entry_is_undone_once(self):
        [charge] = self.entries(FeeEntryKind.CHARGE)
        self.post(self.bursar, f"entries/{charge.pk}/reversal/", {"reason": "Wrong class"})

        again = self.post(self.bursar, f"entries/{charge.pk}/reversal/", {"reason": "Wrong class"})

        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(self.entries(FeeEntryKind.REVERSAL)), 1)

    def test_the_account_marks_what_was_undone(self):
        [charge] = self.entries(FeeEntryKind.CHARGE)
        self.post(self.bursar, f"entries/{charge.pk}/reversal/", {"reason": "Wrong class"})

        rows = {e["entry_id"]: e for e in self.get(self.bursar, f"students/{self.ada.pk}/").json()["entries"]}

        self.assertIsNotNone(rows[charge.pk]["reversed_by_id"])
        self.assertFalse(rows[charge.pk]["may_reverse"])


class ReceiptTests(FeesApiSetUp):
    def test_the_receipt_is_what_the_entry_recorded(self):
        paid = self.pay(
            amount="15,000.50", method="bank_transfer", reference="GTB/7781", effective_on="2025-10-03"
        ).json()["entry"]

        receipt = self.get(self.principal, f"entries/{paid['entry_id']}/receipt/").json()

        self.assertEqual(receipt["receipt_number"], f"ST-MARYS-{paid['entry_id']:06d}")
        self.assertEqual(paid["receipt_number"], receipt["receipt_number"])
        self.assertEqual(
            {k: receipt[k] for k in ("school", "student", "student_reference", "amount_kobo",
                                     "method_label", "payment_reference", "effective_on",
                                     "received_by")},
            {
                "school": "St Mary's",
                "student": "Ada Obi",
                "student_reference": "SM/001",
                "amount_kobo": 1_500_050,
                "method_label": "Bank transfer",
                "payment_reference": "GTB/7781",
                "effective_on": "2025-10-03",
                "received_by": "Bola Bursar",
            },
        )
        self.assertIsNone(receipt["reversed"])

    def test_a_receipt_keeps_the_name_it_was_issued_with(self):
        paid = self.pay().json()["entry"]
        self.ada.display_name = "Adaeze Obi"
        self.ada.save(update_fields=["display_name"])

        receipt = self.get(self.bursar, f"entries/{paid['entry_id']}/receipt/").json()

        self.assertEqual(receipt["student"], "Ada Obi")

    def test_an_undone_payments_receipt_says_so(self):
        paid = self.pay().json()["entry"]
        self.post(self.bursar, f"entries/{paid['entry_id']}/reversal/", {"reason": "Cheque bounced"})

        receipt = self.get(self.bursar, f"entries/{paid['entry_id']}/receipt/").json()

        self.assertEqual(receipt["reversed"]["reason"], "Cheque bounced")

    def test_a_charge_has_no_receipt(self):
        missing = self.missing()
        [charge] = self.entries(FeeEntryKind.CHARGE)

        answer = self.get(self.bursar, f"entries/{charge.pk}/receipt/")

        self.assertEqual(answer.status_code, 404)
        self.assertEqual(answer.content, missing)


class ClassBalancesTests(FeesApiSetUp):
    def test_each_child_with_their_whole_account(self):
        """Ada owes the tuition; Chidi paid ahead and is in credit — a real
        state, and the number the page must not read as owing."""
        self.pay(child=self.chidi, amount="5,000")

        body = self.get(self.bursar, f"classes/{self.group_id}/?term_id={self.term_id}").json()

        self.assertEqual(
            [(c["student"], c["balance_kobo"]) for c in body["children"]],
            [("Ada Obi", TUITION), ("Chidi Okafor", -5_000 * KOBO_PER_NAIRA)],
        )

    def test_the_classes_for_the_current_term(self):
        body = self.get(self.vp, "classes/").json()

        self.assertEqual(body["term_id"], self.term_id)
        self.assertFalse(body["may_write"])
        self.assertEqual(
            [(c["class_group"], c["children"]) for c in body["classes"]], [("JSS 1A", 2)]
        )

    def test_the_list_does_not_cost_more_as_the_class_grows(self):
        """A fixed number of queries per class, none per child. Every query is
        counted, and the login is outside the measured block."""

        def queries():
            self.client.force_login(self.bursar)
            with CaptureQueriesContext(connection) as captured:
                answer = self.client.get(
                    f"/api/fees/classes/{self.group_id}/?term_id={self.term_id}", HTTP_HOST=HOST
                )
            return answer, len(captured.captured_queries)

        _, small = queries()
        with connected_to(self.stmarys):
            group, term = ClassGroup.objects.get(pk=self.group_id), Term.objects.get(pk=self.term_id)
        for n in range(3):
            extra = self.child(f"extra{n}", f"Extra {n}", self.stmarys)
            with connected_to(self.stmarys):
                academics.place_student(group, term, extra)
                services.charge(extra, term, TUITION, narration="Tuition")
        answer, larger = queries()

        self.assertEqual(len(answer.json()["children"]), 5)
        self.assertEqual(larger, small, "the class list costs more per child")


class TheFrameTests(FeesApiSetUp):
    def test_the_frame_names_no_child_and_no_money(self):
        self.client.force_login(self.bursar)

        page = self.client.get("/fees/", HTTP_HOST=HOST).content.decode()

        self.assertIn('id="fees"', page)
        self.assertIn('data-on-school="yes"', page)
        for absent in ("Ada", "JSS 1A", "150", "St Mary"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_the_portal_frame_says_it_is_not_a_school(self):
        page = self.client.get("/fees/", HTTP_HOST="testserver").content.decode()

        self.assertIn('data-on-school=""', page)
