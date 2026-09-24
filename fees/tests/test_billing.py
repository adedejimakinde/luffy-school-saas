"""Bills and concessions below the routes: `fees.billing` and the tables. B2.

Two schools throughout, as everywhere in `fees`. St Mary's is under test.

Claims, each with the test that fails without it:

1. Issue #75. Revoking a concession writes a row saying who, when and why, and
   leaves the concession exactly as it was granted.
2. A revocation without a reason is refused — by the service in a sentence,
   and by the table from anywhere.
3. A revocation without a person is refused.
4. A concession is revoked once.
5. A concession and its revocation are never edited or deleted: `save()` and
   `delete()` refuse, and a trigger refuses below them.
6. The same grant form twice is one concession.
7. A bill line is added once per name; a line that has charged somebody is
   not removed.
"""

import uuid
from datetime import date

from django.db import connection, transaction
from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import User
from accounts.services import enroll_student
from fees import billing, schedules, services
from fees.models import (
    KOBO_PER_NAIRA,
    ConcessionIsFixed,
    FeeConcession,
    FeeConcessionRevocation,
    FeeSchedule,
)
from schools.tests.tenants import connected_to, make_school
from tests.refusals import RefusalAssertions

PASSWORD = "correct-horse-battery"
TUITION = 120_000 * KOBO_PER_NAIRA
LEVY = 15_000 * KOBO_PER_NAIRA

#: What `fees_concession_is_fixed` says, table first and operation second —
#: both, for the reason `test_ledger.APPEND_ONLY_UPDATE` gives.
FIXED = "{table} is never edited or deleted; {op} is not allowed"


class BillingServiceSetUp(RefusalAssertions, TestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.bursar = User.objects.create_user("bola", PASSWORD, full_name="Bola Bursar")
        self.ada = enroll_student(User.objects.create_user("ada", PASSWORD, full_name="Ada Obi"), self.stmarys)
        self.zainab = enroll_student(
            User.objects.create_user("zainab", PASSWORD, full_name="Zainab Musa"), self.grace
        )
        with connected_to(self.stmarys):
            self.term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )
            self.group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(self.group, self.term, self.ada)
        with connected_to(self.grace):
            # Grace has a concession of its own, which nothing here may touch.
            self.theirs = FeeConcession.objects.create(
                student_membership_id=self.zainab.pk, amount_kobo=LEVY, reason="Bursary"
            )

    def tearDown(self):
        connection.set_schema_to_public()

    def grant(self, **overrides):
        kwargs = {"reason": "Staff child", "form_key": uuid.uuid4(), "by": self.bursar}
        kwargs.update(overrides)
        amount = kwargs.pop("amount_kobo", TUITION)
        return billing.grant_concession(self.ada, amount, **kwargs)


class RevokingTests(BillingServiceSetUp):
    """Claims 1 to 4."""

    def test_a_revocation_says_who_when_and_why_and_the_grant_stands(self):
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            granted = FeeConcession.objects.filter(pk=concession.pk).values().get()

            revocation = billing.revoke_concession(
                concession, reason="  Parent left the staff ", by=self.bursar
            )

            revocation.refresh_from_db()
            self.assertEqual(
                (revocation.reason, revocation.revoked_by_id, revocation.revoked_by_name),
                ("Parent left the staff", self.bursar.pk, "Bola Bursar"),
            )
            self.assertIsNotNone(revocation.revoked_at)
            self.assertEqual(FeeConcession.objects.filter(pk=concession.pk).values().get(), granted)
            self.assertFalse(FeeConcession.objects.standing().filter(pk=concession.pk).exists())
        with connected_to(self.grace):
            self.assertFalse(FeeConcessionRevocation.objects.exists())

    def test_the_revokers_name_is_frozen_on_the_row(self):
        """Rule 2: the record of who stopped a discount does not change when
        that person's login does — which is issue #143's receipt, not
        repeated."""
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            revocation = billing.revoke_concession(concession, reason="Left", by=self.bursar)
        User.objects.filter(pk=self.bursar.pk).update(full_name="Bola Adeyemi")

        with connected_to(self.stmarys):
            revocation.refresh_from_db()
            self.assertEqual(revocation.revoked_by_name, "Bola Bursar")

    def test_a_revocation_without_a_reason_is_refused_and_writes_nothing(self):
        """CONTROL B2-7: `revoke_concession()` without `_require_reason()`
        makes this red — the table still refuses, but as an `IntegrityError`
        nobody can show a bursar."""
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            for blank in ("", "   ", None):
                with self.subTest(reason=blank):
                    with self.assertRaises(services.NoReason):
                        billing.revoke_concession(concession, reason=blank, by=self.bursar)
            self.assertFalse(FeeConcessionRevocation.objects.exists())
            self.assertTrue(FeeConcession.objects.standing().filter(pk=concession.pk).exists())

    def test_the_table_refuses_a_revocation_without_a_reason(self):
        """From anywhere — a shell, an import — not only through the service.

        CONTROL B2-8: migration 0005 without `a_revocation_says_why` makes
        this red."""
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            for blank in ("", " \t "):
                with self.subTest(reason=blank):
                    with self.assertRefusedBy("a_revocation_says_why"), transaction.atomic():
                        FeeConcessionRevocation.objects.create(
                            concession=concession, reason=blank, revoked_by_id=self.bursar.pk
                        )

    def test_a_revocation_without_a_person_is_refused(self):
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            with self.assertRaises(billing.RevocationNeedsAPerson):
                billing.revoke_concession(concession, reason="Left", by=None)
            self.assertFalse(FeeConcessionRevocation.objects.exists())

    def test_a_concession_is_revoked_once(self):
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            billing.revoke_concession(concession, reason="Left", by=self.bursar)

            with self.assertRaises(billing.AlreadyRevoked) as refused:
                billing.revoke_concession(concession, reason="Again", by=self.bursar)

            self.assertIn('"Left"', str(refused.exception))
            self.assertEqual(FeeConcessionRevocation.objects.count(), 1)

    def test_the_table_holds_one_revocation_per_concession(self):
        """The one-to-one is what holds when two bursars revoke at once."""
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            billing.revoke_concession(concession, reason="Left", by=self.bursar)
            with self.assertRefusedBy("fees_feeconcessionrevocation_concession_id_key"), transaction.atomic():
                FeeConcessionRevocation.objects.create(
                    concession=concession, reason="Again", revoked_by_id=self.bursar.pk
                )

    def test_revoking_leaves_the_discounts_already_given(self):
        """The ledger is append-only: this term's discount stands, and the next
        application gives no more."""
        with connected_to(self.stmarys):
            bill = FeeSchedule.objects.create(term=self.term, class_group=self.group)
            billing.add_line(bill, "Tuition", TUITION)
            concession, _ = self.grant()
            schedules.apply_to_class(bill, by=self.bursar)

            billing.revoke_concession(concession, reason="Left", by=self.bursar)
            again = schedules.apply_to_class(bill, by=self.bursar)

            self.assertEqual((again.discounts_posted, again.discounts_skipped), (0, 0))
            self.assertEqual(concession.entries.count(), 1)


class NeverEditedTests(BillingServiceSetUp):
    """Claim 5. The model's refusal is what a developer sees; the trigger is
    what holds for everything that never calls it.

    CONTROL B2-9: migration 0006 without its triggers makes the four database
    tests red and leaves the two model tests green — which is the split."""

    def test_the_model_refuses_to_rewrite_or_delete_a_concession(self):
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            concession.amount_kobo = LEVY
            with self.assertRaises(ConcessionIsFixed):
                concession.save()
            with self.assertRaises(ConcessionIsFixed):
                concession.delete()

    def test_the_model_refuses_to_rewrite_or_delete_a_revocation(self):
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            revocation = billing.revoke_concession(concession, reason="Left", by=self.bursar)
            revocation.reason = "Something kinder"
            with self.assertRaises(ConcessionIsFixed):
                revocation.save()
            with self.assertRaises(ConcessionIsFixed):
                revocation.delete()

    def test_the_database_refuses_an_update_to_a_concession(self):
        with connected_to(self.stmarys):
            self.grant()
            table = "fees_feeconcession"
            with self.assertRefusedBy(FIXED.format(table=table, op="UPDATE")), transaction.atomic():
                FeeConcession.objects.update(amount_kobo=1)

    def test_the_database_refuses_deleting_a_concession_nothing_protects(self):
        """Never used, so no entry `PROTECT`s it and Django's collector lets
        the DELETE through — to the trigger."""
        with connected_to(self.stmarys):
            self.grant()
            table = "fees_feeconcession"
            with self.assertRefusedBy(FIXED.format(table=table, op="DELETE")), transaction.atomic():
                FeeConcession.objects.all().delete()

    def test_the_database_refuses_an_update_to_a_revocation(self):
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            billing.revoke_concession(concession, reason="Left", by=self.bursar)
            table = "fees_feeconcessionrevocation"
            with self.assertRefusedBy(FIXED.format(table=table, op="UPDATE")), transaction.atomic():
                FeeConcessionRevocation.objects.update(reason="Something kinder")

    def test_the_database_refuses_deleting_a_revocation(self):
        """Deleting it would un-revoke the concession with no trace — the
        exact absence #75 is about."""
        with connected_to(self.stmarys):
            concession, _ = self.grant()
            billing.revoke_concession(concession, reason="Left", by=self.bursar)
            table = "fees_feeconcessionrevocation"
            with self.assertRefusedBy(FIXED.format(table=table, op="DELETE")), transaction.atomic():
                FeeConcessionRevocation.objects.all().delete()

    def test_the_triggers_exist_in_every_school_schema(self):
        for school in (self.stmarys, self.grace):
            with self.subTest(school=school.slug), connection.cursor() as cursor:
                cursor.execute(
                    "select tgname from pg_trigger t join pg_class c on c.oid = t.tgrelid "
                    "where c.relnamespace = %s::regnamespace and not t.tgisinternal",
                    [school.schema_name],
                )
                triggers = {row[0] for row in cursor.fetchall()}
                self.assertLessEqual(
                    {"fees_concession_fixed", "fees_concession_revocation_fixed"}, triggers
                )


class GrantingTests(BillingServiceSetUp):
    """Claim 6."""

    def test_the_same_form_twice_is_one_concession(self):
        with connected_to(self.stmarys):
            key = uuid.uuid4()
            first, granted = self.grant(form_key=key)
            again, granted_again = self.grant(form_key=key)

            self.assertEqual((granted, granted_again, again.pk), (True, False, first.pk))
            self.assertEqual(FeeConcession.objects.count(), 1)

    def test_one_key_with_a_different_grant_is_refused(self):
        with connected_to(self.stmarys):
            key = uuid.uuid4()
            self.grant(form_key=key)
            with self.assertRaises(services.FormAlreadyUsed):
                self.grant(form_key=key, amount_kobo=LEVY)
            self.assertEqual(FeeConcession.objects.count(), 1)

    def test_a_grant_says_why(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.NoReason):
                self.grant(reason="  ")
            self.assertFalse(FeeConcession.objects.exists())

    def test_another_schools_child_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.NotThisSchoolsStudent):
                billing.grant_concession(
                    self.zainab, LEVY, reason="Bursary", form_key=uuid.uuid4(), by=self.bursar
                )
            self.assertFalse(FeeConcession.objects.exists())


class EditingABillTests(BillingServiceSetUp):
    """Claim 7."""

    def test_a_double_click_adds_one_line(self):
        with connected_to(self.stmarys):
            bill = billing.open_bill(self.group, self.term)
            first, added = billing.add_line(bill, "Tuition", TUITION)
            again, added_again = billing.add_line(bill, " Tuition ", TUITION)

            self.assertEqual((added, added_again, again.pk), (True, False, first.pk))
            self.assertEqual(bill.lines.count(), 1)
            self.assertEqual(billing.open_bill(self.group, self.term).pk, bill.pk)

    def test_the_same_name_at_another_amount_is_refused(self):
        with connected_to(self.stmarys):
            bill = billing.open_bill(self.group, self.term)
            billing.add_line(bill, "Tuition", TUITION)
            with self.assertRaises(billing.LineAlreadyOnBill):
                billing.add_line(bill, "Tuition", LEVY)
            self.assertEqual(list(bill.lines.values_list("amount_kobo", flat=True)), [TUITION])

    def test_lines_go_on_the_end(self):
        with connected_to(self.stmarys):
            bill = billing.open_bill(self.group, self.term)
            for description in ("Tuition", "PTA levy", "Uniform"):
                billing.add_line(bill, description, LEVY)
            self.assertEqual(
                list(bill.lines.values_list("description", flat=True)),
                ["Tuition", "PTA levy", "Uniform"],
            )

    def test_a_line_that_has_charged_somebody_is_not_removed(self):
        with connected_to(self.stmarys):
            bill = billing.open_bill(self.group, self.term)
            used, _ = billing.add_line(bill, "Tuition", TUITION)
            schedules.apply_to_class(bill, by=self.bursar)
            spare, _ = billing.add_line(bill, "Uniform", LEVY)

            with self.assertRaises(billing.LineHasCharged):
                billing.remove_line(used)
            billing.remove_line(spare)

            self.assertEqual(list(bill.lines.all()), [used])

    def test_changing_a_line_leaves_what_it_already_charged(self):
        with connected_to(self.stmarys):
            bill = billing.open_bill(self.group, self.term)
            line, _ = billing.add_line(bill, "Tuition", TUITION)
            schedules.apply_to_class(bill, by=self.bursar)

            billing.change_line(line, description="Tuition (revised)", amount_kobo=LEVY)

            [charge] = line.entries.all()
            self.assertEqual((charge.narration, charge.amount_kobo), ("Tuition", TUITION))
            line.refresh_from_db()
            self.assertEqual((line.description, line.amount_kobo), ("Tuition (revised)", LEVY))
