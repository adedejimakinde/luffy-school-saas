"""Payment receipts: written by `record_payment()` itself, to whoever receives invoices.

Two schools in every test, as `test_fee_reminders.py` keeps: St Mary's is the one
posting a payment, and Grace has a guardian who is also Ada's mother, so a
receipt that crossed schools has somewhere to show.

**Email only** (decided for this feature, alongside the reminders and result
notices already built): a guardian reachable only by phone gets no receipt, and
is not told they are owed one — there is no button and no preview to tell them
on. **Off by default**: a school that has not turned `payment_receipts` on gets
a payment and nothing else, exactly the state it was in before this file existed.
"""

from datetime import date, timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import ContactChannel, Guardianship, Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from fees import services as ledger
from fees.authority import receipt_number
from fees.models import KOBO_PER_NAIRA, PaymentMethod
from messaging.models import FakeMessage
from messaging.tests.fake import SendsThroughTheFake
from notices import hours, tasks
from notices.models import Notice, NoticeKind, NoticeOutcome, NoticeSettings
from notices.tests.test_result_notices import lagos
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from tests.guardians import give_verified_channel

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"
NAIRA = KOBO_PER_NAIRA

MAMA_PHONE = "+2348031110011"       # Ada's mother: a live phone, no email — no receipt
PAPA_EMAIL = "papa.obi@example.com"  # Ada's father: a live email, receives no invoices
AUNTIE_EMAIL = "auntie@example.com"  # Ada's aunt: a live email, receives invoices


class ReceiptsSetUp(SendsThroughTheFake, TestCase):
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

        self.bursar = self.staff("bola", "Bola Bursar", Role.BURSAR, self.stmarys)

        self.ada = self.child("ada", "Ada Obi", self.stmarys, "SM/001")
        self.zainab = self.child("zainab", "Zainab Musa", self.grace, "GA/001")

        with connected_to(self.stmarys):
            self.term_now = self.term(TermName.FIRST, "2025/2026", date(2025, 9, 15))
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(group, self.term_now, self.ada)
            ledger.charge(self.ada, self.term_now, 150_000 * NAIRA, narration="First term tuition")
        with connected_to(self.grace):
            self.their_term = self.term(TermName.FIRST, "2025/2026", date(2025, 9, 15))
            their_group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(their_group, self.their_term, self.zainab)

        # Mama: a live phone and nothing else — not reachable by the email
        # this feature is restricted to. Papa: a live email whose link says he
        # receives no invoices. Auntie: a live email who does. Mama is also
        # Zainab's mother at Grace, for the cross-school check.
        self.mama = self.guardian("mama", "Ngozi Obi", [self.ada, self.zainab], phone=MAMA_PHONE)
        self.papa = self.guardian("papa", "Obinna Obi", [self.ada], email=PAPA_EMAIL)
        Guardianship.objects.filter(guardian=self.papa).update(receives_invoices=False)
        self.auntie = self.guardian("auntie", "Funke Obi", [self.ada], email=AUNTIE_EMAIL)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    # -- building --------------------------------------------------------

    def staff(self, username, name, role, school):
        user = User.objects.create_user(username, PASSWORD, full_name=name)
        grant_membership(user, school, role)
        return user

    def child(self, username, name, school, reference):
        membership = enroll_student(
            User.objects.create_user(username, PASSWORD, full_name=name), school
        )
        membership.reference = reference
        membership.save(update_fields=["reference"])
        return membership

    def term(self, name, session, starts_on, current=True):
        return Term.objects.create(
            session=session, name=name, starts_on=starts_on,
            ends_on=starts_on + timedelta(days=80), is_current=current,
        )

    def guardian(self, username, name, children, *, phone=None, email=None):
        user = User.objects.create_user(username, PASSWORD, full_name=name)
        for child in children:
            link_guardian(user, child)
        if phone:
            give_verified_channel(user, phone)
        if email:
            give_verified_channel(user, email, channel_type=ContactChannel.EMAIL)
        return user

    def offer(self, school=None):
        with connected_to(school or self.stmarys):
            NoticeSettings.objects.create(pk=1, payment_receipts=True)

    # -- paying and sending ------------------------------------------------

    def pay(self, child, naira, *, school=None, now=None):
        """A payment, and whatever it queued. `(entry, [queued task args])`.

        Noon Lagos time unless told otherwise — `write_receipt()` reads this
        moment to decide whether quiet hours hold it, and `record_payment()`
        itself takes no clock, so this stands in for the wall clock rather
        than for a parameter that exists.
        """
        school = school or self.stmarys
        term = self.term_now if school == self.stmarys else self.their_term
        at = lagos(0, 12) if now is None else now

        def act():
            return ledger.record_payment(
                child, term, naira * NAIRA, method=PaymentMethod.CASH, recorded_by=self.bursar,
            )

        with connected_to(school):
            with mock.patch("notices.tasks.send_notice.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    with mock.patch("notices.receipts.timezone", **{"now.return_value": at}):
                        entry = act()
        return entry, [call.kwargs["args"] for call in publish.call_args_list]

    def send_all(self, jobs, at=None):
        at = lagos(0, 12) if at is None else at
        with mock.patch("notices.tasks.timezone", **{"now.return_value": at}):
            for args in jobs:
                tasks.send_notice.apply(args=args).get()
        connection.set_schema_to_public()

    def texts(self, address):
        return [m.text for m in FakeMessage.objects.filter(address=address).order_by("id")]

    def reply_tos(self, address):
        return [m.reply_to for m in FakeMessage.objects.filter(address=address).order_by("id")]

    def receipts(self, school=None):
        with connected_to(school or self.stmarys):
            return list(Notice.objects.filter(kind=NoticeKind.PAYMENT_RECEIPT))


class OffByDefaultTests(ReceiptsSetUp):
    def test_a_payment_writes_no_receipt_until_the_school_turns_it_on(self):
        entry, jobs = self.pay(self.ada, 50_000)

        self.assertIsNotNone(entry)
        self.assertEqual(jobs, [])
        self.assertEqual(self.receipts(), [])


class WhoGetsOneTests(ReceiptsSetUp):
    def setUp(self):
        super().setUp()
        self.offer()

    def test_only_the_guardian_who_receives_invoices_on_a_live_email_gets_one(self):
        _, jobs = self.pay(self.ada, 50_000)
        self.send_all(jobs)

        self.assertEqual(self.texts(AUNTIE_EMAIL).__len__(), 1)
        self.assertEqual(self.texts(PAPA_EMAIL), [])

    def test_a_guardian_reachable_only_by_phone_gets_no_receipt(self):
        """Requirement: email only. Mama has no live email at all."""
        _, jobs = self.pay(self.ada, 50_000)
        self.send_all(jobs)

        self.assertEqual(FakeMessage.objects.filter(channel_type="phone").count(), 0)

    def test_the_text_names_the_receipt_the_amount_and_the_method(self):
        entry, jobs = self.pay(self.ada, 50_000)
        self.send_all(jobs)

        [text] = self.texts(AUNTIE_EMAIL)
        self.assertIn(receipt_number(self.stmarys, entry.pk), text)
        self.assertIn("NGN 50,000 received", text)
        self.assertIn("by Cash", text)
        self.assertIn("Ada Obi", text)

    def test_the_receipt_carries_the_schools_own_contact_email_as_reply_to(self):
        """docs/messaging.md D17."""
        self.stmarys.contact_email = "office@stmarys.example"
        self.stmarys.save(update_fields=["contact_email"])
        _, jobs = self.pay(self.ada, 50_000)
        self.send_all(jobs)

        self.assertEqual(self.reply_tos(AUNTIE_EMAIL), ["office@stmarys.example"])

    def test_no_contact_email_means_no_reply_to(self):
        _, jobs = self.pay(self.ada, 50_000)
        self.send_all(jobs)

        self.assertEqual(self.reply_tos(AUNTIE_EMAIL), [""])

    def test_each_school_receipts_its_own_payment_and_its_own_child(self):
        """Mama has a child at each school. Only St Mary's payment is receipted,
        and only to guardians reachable through St Mary's own settings."""
        _, ours = self.pay(self.ada, 50_000)
        _, theirs = self.pay(self.zainab, 30_000, school=self.grace)  # Grace: off
        self.send_all(ours)
        with connected_to(self.grace):
            self.assertEqual(theirs, [])
            self.assertEqual(Notice.objects.filter(kind=NoticeKind.PAYMENT_RECEIPT).count(), 0)


class QuietHoursTests(ReceiptsSetUp):
    def setUp(self):
        super().setUp()
        self.offer()

    def test_a_payment_recorded_at_night_is_held_for_the_morning(self):
        entry, jobs = self.pay(self.ada, 50_000, now=lagos(0, 21))

        self.assertEqual(jobs, [])
        [receipt] = self.receipts()
        self.assertGreater(receipt.send_after, lagos(0, 21))

    def test_the_07_00_sweep_queues_a_held_receipt(self):
        self.pay(self.ada, 50_000, now=lagos(0, 21))
        [receipt] = self.receipts()
        after = receipt.send_after + timedelta(minutes=5)
        with connected_to(self.stmarys):
            with mock.patch("notices.tasks.send_notice.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    from notices.tasks import release_held

                    release_held(now=after)
            jobs = [call.kwargs["args"] for call in publish.call_args_list]
        self.send_all(jobs, at=after)
        self.assertEqual(self.texts(AUNTIE_EMAIL).__len__(), 1)


class OutcomeTests(ReceiptsSetUp):
    def setUp(self):
        super().setUp()
        self.offer()

    def test_the_outcome_is_recorded_accepted(self):
        _, jobs = self.pay(self.ada, 50_000)
        self.send_all(jobs)

        with connected_to(self.stmarys):
            said = {o.said for o in NoticeOutcome.objects.all()}
        self.assertEqual(said, {NoticeOutcome.Said.ACCEPTED})

    def test_a_guardian_unlinked_before_the_send_gets_no_receipt(self):
        """D4 read again at send time, as a fee reminder's is."""
        entry, jobs = self.pay(self.ada, 50_000)
        with connected_to(self.stmarys):
            Guardianship.objects.filter(guardian=self.auntie, student=self.ada).delete()
        self.send_all(jobs)

        self.assertEqual(self.texts(AUNTIE_EMAIL), [])
        with connected_to(self.stmarys):
            said = {o.said for o in NoticeOutcome.objects.all()}
        self.assertEqual(said, {NoticeOutcome.Said.NO_LONGER_REACHABLE})
