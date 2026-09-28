"""The proprietor's daily money summary: no button, no `Notice`, one email a day.

Two schools, as every other notices test file keeps: St Mary's turns the
setting on and Grace does not, so a leak across schools or a school sent
regardless of its own switch has somewhere to show.

Entries are posted at the real wall clock and read back by
`hours.day_of(timezone.now())` — the pattern `home.tests.test_home_api`'s
`test_payments_are_counted_on_the_day_they_were_recorded` already uses, since
`recorded_at` is `auto_now_add` and the ledger refuses to backdate it.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from academics.models import Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from fees import services as ledger
from fees.models import KOBO_PER_NAIRA, PaymentMethod
from messaging.models import FakeMessage
from messaging.tests.fake import SendsThroughTheFake
from notices import hours
from notices.daily_summary import send_summaries, send_summary
from notices.models import MoneySummaryRecipient, MoneySummarySent, NoticeSettings
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"
NAIRA = KOBO_PER_NAIRA


class SummarySetUp(SendsThroughTheFake, TestCase):
    def setUp(self):
        super().setUp()
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=THEIR_HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        self.admin = self.staff("ade", "Ade Admin", Role.ADMIN, self.stmarys, email="ade@stmarys.example")
        self.bursar = self.staff("bola", "Bola Bursar", Role.BURSAR, self.stmarys, email="bola@stmarys.example")
        self.no_email_admin = self.staff("tayo", "Tayo Admin", Role.ADMIN, self.stmarys, email=None)

        self.ada = self.child("ada", "Ada Obi", self.stmarys, "SM/001")

        with connected_to(self.stmarys):
            self.term = self.a_term()

        self.today = hours.day_of(timezone.now())

    def tearDown(self):
        from django.db import connection

        connection.set_schema_to_public()
        super().tearDown()

    def staff(self, username, name, role, school, *, email):
        user = User.objects.create_user(username, PASSWORD, full_name=name, email=email)
        membership = grant_membership(user, school, role)
        # The daily summary picks recipients by membership id, not user id
        # (`MoneySummaryRecipient`) — stashed here so a test can say
        # `self.admin.membership_id` without a second lookup.
        user.membership_id = membership.pk
        return user

    def child(self, username, name, school, reference):
        membership = enroll_student(
            User.objects.create_user(username, PASSWORD, full_name=name), school
        )
        membership.reference = reference
        membership.save(update_fields=["reference"])
        return membership

    def a_term(self):
        return Term.objects.create(
            session="2025/2026", name=TermName.FIRST,
            starts_on=timezone.localdate() - timedelta(days=10),
            ends_on=timezone.localdate() + timedelta(days=70),
        )

    def offer(self, school=None, *, recipients=()):
        with connected_to(school or self.stmarys):
            NoticeSettings.objects.create(pk=1, daily_money_summary=True)
            MoneySummaryRecipient.objects.bulk_create(
                [MoneySummaryRecipient(membership_id=m.membership_id) for m in recipients]
            )

    def texts(self, address):
        return [m.text for m in FakeMessage.objects.filter(address=address).order_by("id")]


class OffByDefaultTests(SummarySetUp):
    def test_nothing_is_sent_until_the_school_turns_it_on(self):
        with connected_to(self.stmarys):
            ledger.charge(self.ada, self.term, 10_000 * NAIRA, narration="Tuition")
            ledger.record_payment(self.ada, self.term, 4_000 * NAIRA, method=PaymentMethod.CASH)
            sent = send_summary(self.stmarys, self.today)

        self.assertFalse(sent)
        self.assertEqual(self.texts("ade@stmarys.example"), [])
        with connected_to(self.stmarys):
            self.assertEqual(MoneySummarySent.objects.count(), 0)


class NobodyByDefaultTests(SummarySetUp):
    """Turning the digest on picks nobody by itself — D15, extended: the school
    chooses its recipients from its own live staff list, and the default is
    nobody until it does."""

    def setUp(self):
        super().setUp()
        self.offer()  # no recipients

    def test_nobody_chosen_means_nobody_is_emailed(self):
        with connected_to(self.stmarys):
            sent = send_summary(self.stmarys, self.today)

        self.assertTrue(sent)  # the day is still recorded processed
        self.assertEqual(self.texts("ade@stmarys.example"), [])

    def test_the_day_is_still_recorded_so_a_later_pick_does_not_resend_it(self):
        with connected_to(self.stmarys):
            send_summary(self.stmarys, self.today)
            recorded = MoneySummarySent.objects.filter(for_day=self.today).exists()

        self.assertTrue(recorded)


class WhoGetsOneTests(SummarySetUp):
    def setUp(self):
        super().setUp()
        self.offer(recipients=[self.admin])

    def test_a_chosen_staff_member_with_an_email_gets_one(self):
        with connected_to(self.stmarys):
            send_summary(self.stmarys, self.today)

        self.assertEqual(len(self.texts("ade@stmarys.example")), 1)

    def test_a_chosen_staff_member_with_no_email_is_skipped_without_failing_the_rest(self):
        with connected_to(self.stmarys):
            MoneySummaryRecipient.objects.create(membership_id=self.no_email_admin.membership_id)
            send_summary(self.stmarys, self.today)

        self.assertEqual(len(self.texts("ade@stmarys.example")), 1)

    def test_a_bursar_who_was_not_chosen_is_not_sent_one(self):
        with connected_to(self.stmarys):
            send_summary(self.stmarys, self.today)

        self.assertEqual(self.texts("bola@stmarys.example"), [])

    def test_an_administrator_who_was_not_chosen_is_not_sent_one(self):
        with connected_to(self.stmarys):
            second_admin = self.staff(
                "kemi", "Kemi Admin", Role.ADMIN, self.stmarys, email="kemi@stmarys.example"
            )
            send_summary(self.stmarys, self.today)

        self.assertEqual(self.texts("kemi@stmarys.example"), [])

    def test_each_school_is_sent_only_if_its_own_setting_is_on(self):
        with connected_to(self.grace):
            grace_admin = self.staff(
                "grace-ade", "Grace Admin", Role.ADMIN, self.grace, email="admin@grace.example"
            )
            MoneySummaryRecipient.objects.create(membership_id=grace_admin.membership_id)
        with connected_to(self.grace):
            sent = send_summary(self.grace, self.today)

        self.assertFalse(sent)
        self.assertEqual(self.texts("admin@grace.example"), [])


class TheFiguresTests(SummarySetUp):
    def setUp(self):
        super().setUp()
        self.offer(recipients=[self.admin])

    def test_collected_and_billed_and_the_payment_count(self):
        with connected_to(self.stmarys):
            ledger.charge(self.ada, self.term, 150_000 * NAIRA, narration="Tuition")
            ledger.record_payment(self.ada, self.term, 60_000 * NAIRA, method=PaymentMethod.CASH)
            ledger.record_payment(self.ada, self.term, 20_000 * NAIRA, method=PaymentMethod.BANK_TRANSFER, reference="TR-1")
            send_summary(self.stmarys, self.today)

        [text] = self.texts("ade@stmarys.example")
        self.assertIn("NGN 80,000 collected", text)
        self.assertIn("2 payments", text)
        self.assertIn("NGN 150,000 billed", text)

    def test_yesterdays_money_is_not_todays(self):
        with connected_to(self.stmarys):
            ledger.record_payment(self.ada, self.term, 60_000 * NAIRA, method=PaymentMethod.CASH)
            send_summary(self.stmarys, self.today - timedelta(days=1))

        [text] = self.texts("ade@stmarys.example")
        self.assertIn("NGN 0 collected", text)
        self.assertIn("0 payments", text)

    def test_one_payment_is_worded_in_the_singular(self):
        with connected_to(self.stmarys):
            ledger.record_payment(self.ada, self.term, 10_000 * NAIRA, method=PaymentMethod.CASH)
            send_summary(self.stmarys, self.today)

        [text] = self.texts("ade@stmarys.example")
        self.assertIn("1 payment,", text)


class SentOnceTests(SummarySetUp):
    def setUp(self):
        super().setUp()
        self.offer(recipients=[self.admin])

    def test_a_second_run_the_same_day_sends_nothing_twice(self):
        with connected_to(self.stmarys):
            ledger.record_payment(self.ada, self.term, 10_000 * NAIRA, method=PaymentMethod.CASH)
            first = send_summary(self.stmarys, self.today)
            second = send_summary(self.stmarys, self.today)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.texts("ade@stmarys.example")), 1)

    def test_send_summaries_visits_every_school_and_records_the_figures(self):
        with connected_to(self.stmarys):
            ledger.record_payment(self.ada, self.term, 10_000 * NAIRA, method=PaymentMethod.CASH)

        count = send_summaries(day=self.today)

        self.assertEqual(count, 1)  # only St Mary's has the setting on
        with connected_to(self.stmarys):
            [row] = MoneySummarySent.objects.all()
        self.assertEqual(row.for_day, self.today)
        self.assertEqual(row.collected_kobo, 10_000 * NAIRA)
        self.assertEqual(row.payments, 1)


class ProviderRefusalTests(SummarySetUp):
    def setUp(self):
        super().setUp()
        self.offer(recipients=[self.admin])

    def test_a_refused_address_does_not_stop_the_day_being_recorded(self):
        with connected_to(self.stmarys):
            User.objects.filter(pk=self.admin.pk).update(email="refused@example.com")
            ledger.record_payment(self.ada, self.term, 10_000 * NAIRA, method=PaymentMethod.CASH)
            sent = send_summary(self.stmarys, self.today)
            recorded = MoneySummarySent.objects.filter(for_day=self.today).exists()

        self.assertTrue(sent)
        self.assertTrue(recorded)
