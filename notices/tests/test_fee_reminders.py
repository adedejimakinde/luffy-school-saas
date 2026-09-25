"""Fee reminders: the bursar's act, to whoever receives invoices. `docs/messaging.md` D10.

Two schools in every test. St Mary's is the one reminding; Grace has a bursar,
a child who owes and a guardian with a child at each school, so a reminder that
crossed schools, or a fold that forgot which school's ledger it read, has
somewhere to show.

**The amount is the whole account** (decided 2026-09-25). Ada owes NGN 20,000
from last term and NGN 100,000 of this term's NGN 150,000, so the account shows
NGN 120,000 and this term alone would say NGN 100,000. **At send time the ledger
is read again** (decided 2026-09-25): a balance that moved sends nothing, does
not count against the interval, and is listed for the bursar to send again.
"""

import json
from datetime import date, timedelta
from unittest import mock

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts import guardian_contacts
from accounts.models import (
    ContactChannel,
    Guardianship,
    GuardianContactCode,
    Membership,
    MembershipStatus,
    Role,
    User,
    VerificationCodeStatus,
)
from accounts.services import enroll_student, grant_membership, link_guardian
from fees import services as ledger
from fees.models import KOBO_PER_NAIRA, PaymentMethod
from messaging.models import FakeMessage
from messaging.tests.fake import SendsThroughTheFake
from notices import reminders, tasks
from notices.models import Notice, NoticeKind, NoticeOutcome, NoticeSettings
from notices.tests.test_result_notices import lagos
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from tests.guardians import give_verified_channel

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"
NAIRA = KOBO_PER_NAIRA

MAMA = "+2348031110011"            # Ada's mother, and Zainab's at Grace
PAPA = "papa.obi@example.com"      # Ada's father, whose link receives no invoices
AUNTIE_PHONE = "+2348031110022"    # Bisi's aunt: a phone gone quiet ...
AUNTIE_EMAIL = "auntie@example.com"  # ... beside a live email
UNCLE = "+2348031110033"           # Bisi's uncle: a phone nobody has proved
KUNLE = "+2348031110044"           # live at Grace, still waiting for St Mary's answer
TUNDE_DAD = "+2348031110055"       # a child in JSS 1B

ADA_OWES = "NGN 120,000"


class RemindersSetUp(SendsThroughTheFake, TestCase):
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
        self.admin = self.staff("ade", "Ade Admin", Role.ADMIN, self.stmarys)
        self.principal = self.staff("ngozi", "Ngozi Head", Role.PRINCIPAL, self.stmarys)
        self.teacher = self.staff("kemi", "Kemi Teacher", Role.TEACHER, self.stmarys)
        self.their_bursar = self.staff("tayo", "Tayo Bursar", Role.BURSAR, self.grace)

        self.ada = self.child("ada", "Ada Obi", self.stmarys, "SM/001")
        self.chidi = self.child("chidi", "Chidi Okafor", self.stmarys, "SM/002")  # paid up
        self.emeka = self.child("emeka", "Emeka Eze", self.stmarys, "SM/003")  # in credit
        self.bisi = self.child("bisi", "Bisi Ade", self.stmarys, "SM/004")
        self.tunde = self.child("tunde", "Tunde Bello", self.stmarys, "SM/005")  # JSS 1B
        self.zainab = self.child("zainab", "Zainab Musa", self.grace, "GA/001")

        with connected_to(self.stmarys):
            NoticeSettings.objects.create(pk=1, fee_reminders=True)
            last = self.term(TermName.THIRD, "2024/2025", date(2025, 4, 20), current=False)
            self.term_now = self.term(TermName.FIRST, "2025/2026", date(2025, 9, 15))
            self.jss1a = ClassGroup.objects.create(name="JSS 1A", level=1)
            self.jss1b = ClassGroup.objects.create(name="JSS 1B", level=1)
            for child in (self.ada, self.chidi, self.emeka, self.bisi):
                academics.place_student(self.jss1a, self.term_now, child)
            academics.place_student(self.jss1b, self.term_now, self.tunde)
            ledger.charge(self.ada, last, 20_000 * NAIRA, narration="Third term tuition")
            ledger.charge(self.ada, self.term_now, 150_000 * NAIRA, narration="First term tuition")
            self.pay(self.ada, 50_000)
            ledger.charge(self.chidi, self.term_now, 150_000 * NAIRA, narration="Tuition")
            self.pay(self.chidi, 150_000)
            self.pay(self.emeka, 10_000)
            ledger.charge(self.bisi, self.term_now, 80_000 * NAIRA, narration="Tuition")
            ledger.charge(self.tunde, self.term_now, 60_000 * NAIRA, narration="Tuition")
        with connected_to(self.grace):
            NoticeSettings.objects.create(pk=1, fee_reminders=True)
            self.their_term = self.term(TermName.FIRST, "2025/2026", date(2025, 9, 15))
            self.their_group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(self.their_group, self.their_term, self.zainab)
            ledger.charge(self.zainab, self.their_term, 90_000 * NAIRA, narration="Tuition")

        # Ada: Mama on a live phone, who is Zainab's mother at Grace too; Papa,
        # on a live email, whose link says he receives no invoices.
        self.mama = self.guardian("mama", "Ngozi Obi", [self.ada, self.zainab], phone=MAMA)
        self.papa = self.guardian("papa", "Obinna Obi", [self.ada], email=PAPA)
        Guardianship.objects.filter(guardian=self.papa).update(receives_invoices=False)
        # Bisi (requirement 14): an aunt with a dormant phone beside a live
        # email; an uncle whose phone nobody proved; and Kunle, live at Grace
        # and still waiting for St Mary's.
        self.auntie = self.guardian(
            "auntie", "Funke Ade", [self.bisi], phone=AUNTIE_PHONE, email=AUNTIE_EMAIL
        )
        self.age(AUNTIE_PHONE)
        self.uncle = self.guardian("uncle", "Segun Ade", [self.bisi])
        guardian_contacts.record_contact(
            guardian_contacts.guardian_account_for(self.uncle), ContactChannel.PHONE, UNCLE,
            created_by=self.admin,
        )
        self.kunle = self.guardian("kunle", "Kunle Ojo", [self.zainab], phone=KUNLE)
        link_guardian(self.kunle, self.bisi)
        self.tunde_dad = self.guardian("tundedad", "Femi Bello", [self.tunde], phone=TUNDE_DAD)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    # -- building -------------------------------------------------------------

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

    def age(self, value):
        GuardianContactCode.objects.filter(
            contact__value=value, status=VerificationCodeStatus.CONFIRMED
        ).update(confirmed_at=timezone.now() - timedelta(days=400))

    def pay(self, child, naira):
        """A payment against the current term. Call inside the school."""
        term = Term.objects.filter(is_current=True).first()
        ledger.record_payment(child, term, naira * NAIRA, method=PaymentMethod.CASH)

    # -- reminding ------------------------------------------------------------

    def remind(self, *, school=None, actor=None, term=None, group=None, only=None, now=None):
        """`(what the bursar is told, [queued task args])`. Noon yesterday unless told."""
        school = school or self.stmarys
        now = lagos(1, 12) if now is None else now
        with connected_to(school):
            with mock.patch("notices.tasks.send_notice.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    told = reminders.send_reminders(
                        term or Term.objects.get(is_current=True),
                        actor=actor or (self.bursar if school == self.stmarys else self.their_bursar),
                        class_group=group, only=only, now=now,
                    )
        return told, [call.kwargs["args"] for call in publish.call_args_list]

    def send_all(self, jobs):
        for args in jobs:
            tasks.send_notice.apply(args=args).get()
        connection.set_schema_to_public()

    def released_at(self, when):
        with mock.patch("notices.tasks.send_notice.apply_async") as publish:
            tasks.release_held(now=when)
        return [call.kwargs["args"] for call in publish.call_args_list]

    def texts(self, address):
        return [m.text for m in FakeMessage.objects.filter(address=address).order_by("id")]

    def said(self, school=None):
        with connected_to(school or self.stmarys):
            return sorted(
                (o.claim.notice.student_membership_id, o.said)
                for o in NoticeOutcome.objects.select_related("claim__notice")
            )

    def get(self, user, path, host=HOST):
        self.client.force_login(user)
        return self.client.get(f"/api/fees/{path}", HTTP_HOST=host)

    def post(self, user, path, body, host=HOST):
        self.client.force_login(user)
        with mock.patch("notices.tasks.send_notice.apply_async"):
            return self.client.post(
                f"/api/fees/{path}", data=json.dumps(body),
                content_type="application/json", HTTP_HOST=host,
            )


class WhatAReminderSaysTests(RemindersSetUp):
    def test_the_amount_is_the_whole_account_worded_as_the_account(self):
        """Decided 2026-09-25. CONTROL: `balances()` folding this term's
        entries only says NGN 100,000, and this goes red."""
        _, jobs = self.remind(group=self.jss1a)
        self.send_all(jobs)

        self.assertEqual(
            self.texts(MAMA),
            [f"St Mary's: Ada Obi's fees account shows {ADA_OWES} owing. Please contact the school."],
        )

    def test_the_contact_is_the_schools_own_sentence_when_it_has_one(self):
        from results import withholding

        with connected_to(self.stmarys):
            withholding.set_policy(enabled=False, contact="the bursar's office, 0803 555 0123")
        _, jobs = self.remind(group=self.jss1a)
        self.send_all(jobs)

        [text] = self.texts(MAMA)
        self.assertTrue(text.endswith("Please contact the school: the bursar's office, 0803 555 0123"))

    def test_each_school_reminds_of_its_own_child_and_its_own_account(self):
        """Mama has a child at each school. CONTROL: every job carrying St
        Mary's schema sends Grace's ids to St Mary's, and Zainab's goes nowhere."""
        _, ours = self.remind(group=self.jss1a)
        _, theirs = self.remind(school=self.grace, group=None)
        self.send_all(ours + theirs)

        first, second = self.texts(MAMA)
        self.assertIn(f"St Mary's: Ada Obi's fees account shows {ADA_OWES}", first)
        self.assertEqual(
            second,
            "Grace Academy: Zainab Musa's fees account shows NGN 90,000 owing. Please contact the school.",
        )
        with connected_to(self.grace):
            # Mama and Kunle, who is live at Grace.
            self.assertEqual(Notice.objects.count(), 2)


class WhoIsRemindedTests(RemindersSetUp):
    def test_only_children_who_owe(self):
        """Chidi is paid up and Emeka is in credit. CONTROL: `_batch()` taking
        every child, owing or not, lists both, and this goes red."""
        with connected_to(self.stmarys):
            preview = reminders.preview_reminders(
                self.term_now, actor=self.bursar, class_group=self.jss1a, now=lagos(1, 12)
            )
        self.assertEqual(
            [(c["student"], c["amount_kobo"]) for c in preview["children"]],
            [("Ada Obi", 120_000 * NAIRA), ("Bisi Ade", 80_000 * NAIRA)],
        )

    def test_the_table_refuses_a_reminder_for_nothing_owed(self):
        """The constraint behind the fold. CONTROL: the migration without the
        check constraint writes it."""
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Notice.objects.create(
                    kind=NoticeKind.FEE_REMINDER, student_membership_id=self.chidi.pk,
                    term=self.term_now, guardian_user_id=self.mama.pk, contact_id=1,
                    channel_type="phone", address=MAMA, segments=1, amount_kobo=0,
                    send_after=timezone.now(), created_by_id=self.bursar.pk,
                )

    def test_only_guardians_whose_link_receives_invoices(self):
        """Papa's link says no. CONTROL: `for_child()` ignoring
        `invoices_only` reminds him too."""
        _, jobs = self.remind(group=self.jss1a)
        self.send_all(jobs)

        self.assertEqual(self.texts(PAPA), [])
        self.assertEqual(len(self.texts(MAMA)), 1)

    def test_the_amount_reaches_only_a_live_verified_channel(self):
        """Requirement 14. Bisi's aunt has a dormant phone beside a live email,
        her uncle a phone nobody proved, and Kunle is live at Grace and still
        waiting for St Mary's. The amount is in one text: the aunt's email.

        CONTROL: `for_child()` without its `is_live_at()` check reminds Kunle."""
        _, jobs = self.remind(group=self.jss1a)
        self.send_all(jobs)

        everything = list(FakeMessage.objects.values_list("address", "text"))
        with_amount = [address for address, text in everything if "NGN 80,000" in text]
        self.assertEqual(with_amount, [AUNTIE_EMAIL])
        for address in (AUNTIE_PHONE, UNCLE, KUNLE):
            with self.subTest(address=address):
                self.assertEqual(self.texts(address), [])

    def test_the_dormant_phone_is_passed_over_for_the_email(self):
        """Requirement 14, the dormant half. CONTROL: `channel_for()` without
        its dormancy check sends the aunt's reminder to her quiet phone."""
        _, jobs = self.remind(group=self.jss1a)
        self.send_all(jobs)
        self.assertEqual(self.texts(AUNTIE_PHONE), [])
        self.assertEqual(len(self.texts(AUNTIE_EMAIL)), 1)

    def test_a_class_is_a_class_and_the_school_is_every_class(self):
        class_only, _ = self.remind(group=self.jss1a)
        self.assertNotIn("Tunde Bello", [c["student"] for c in class_only["children"]])
        whole, _ = self.remind(group=None, now=lagos(1, 13))
        # Ada and Bisi were reminded an hour ago; the whole school adds Tunde.
        self.assertEqual([c["student"] for c in whole["children"]], ["Tunde Bello"])
        self.assertEqual(
            sorted(c["student"] for c in whole["recently_reminded"]), ["Ada Obi", "Bisi Ade"]
        )


class TheIntervalTests(RemindersSetUp):
    def test_pressing_twice_reminds_once(self):
        """D10: a bursar pressing twice in a morning sends once. CONTROL:
        `_batch()` without the interval's fold writes the second batch."""
        first, _ = self.remind(group=self.jss1a)
        again, jobs = self.remind(group=self.jss1a, now=lagos(1, 12, 5))

        self.assertEqual(first["messages"], 2)  # Mama, and the aunt's email
        self.assertEqual((again["messages"], jobs), (0, []))
        self.assertEqual(
            sorted(c["student"] for c in again["recently_reminded"]), ["Ada Obi", "Bisi Ade"]
        )

    def test_after_the_interval_a_child_can_be_reminded_again(self):
        self.remind(group=self.jss1a, now=lagos(9, 12))
        again, _ = self.remind(group=self.jss1a, now=lagos(1, 12))
        self.assertEqual(again["messages"], 2)

    def test_a_held_reminder_counts_before_it_goes(self):
        """Asked at 21:00 and held: a press next morning before 07:00's sweep
        must not queue a second one."""
        self.remind(group=self.jss1a, now=lagos(2, 21))
        again, _ = self.remind(group=self.jss1a, now=lagos(1, 9))
        self.assertEqual(again["messages"], 0)


class TheBalanceMovedTests(RemindersSetUp):
    """Decided 2026-09-25: read the ledger again at send time."""

    def test_a_payment_overnight_sends_nothing_and_says_why(self):
        """CONTROL: `send_notice` not reading the ledger again sends Mama
        yesterday's NGN 120,000 after she paid NGN 10,000 of it."""
        told, jobs = self.remind(group=self.jss1a, now=lagos(2, 21))
        self.assertEqual((told["held_until"], jobs), (lagos(1, 7), []))
        with connected_to(self.stmarys):
            self.pay(self.ada, 10_000)

        self.send_all(self.released_at(lagos(1, 7)))

        self.assertEqual(self.texts(MAMA), [])
        self.assertIn((self.ada.pk, NoticeOutcome.Said.BALANCE_CHANGED), self.said())
        self.assertEqual(len(self.texts(AUNTIE_EMAIL)), 1)  # Bisi's account did not move

    def test_an_unmoved_balance_goes_at_seven_as_it_was_shown(self):
        """CONTROL: `send_notice` treating every reminder as moved sends none."""
        self.remind(group=self.jss1a, now=lagos(2, 21))
        self.send_all(self.released_at(lagos(1, 7)))

        self.assertEqual(
            self.texts(MAMA),
            [f"St Mary's: Ada Obi's fees account shows {ADA_OWES} owing. Please contact the school."],
        )

    def test_one_that_went_nowhere_does_not_count_and_is_listed_until_resent(self):
        """CONTROL: `_counted_since()` counting a `balance_changed` reminder
        leaves Ada out of the resend, and this goes red at the second press."""
        self.remind(group=self.jss1a, now=lagos(2, 21))
        with connected_to(self.stmarys):
            self.pay(self.ada, 10_000)
        self.send_all(self.released_at(lagos(1, 7)))

        listed = self.get(self.bursar, "reminders/not-sent/").json()["children"]
        self.assertEqual(
            [(c["student"], c["stated_kobo"], c["balance_kobo"]) for c in listed],
            [("Ada Obi", 120_000 * NAIRA, 110_000 * NAIRA)],
        )

        # "Remind again" asks about Ada alone, through the route the page uses.
        asked = self.get(self.bursar, f"reminders/?term_id={self.term_now.pk}&children={self.ada.pk}")
        self.assertEqual(
            [(c["student"], c["amount_kobo"]) for c in asked.json()["children"]],
            [("Ada Obi", 110_000 * NAIRA)],
        )

        again, jobs = self.remind(only=[self.ada.pk], now=lagos(1, 9))
        self.send_all(jobs)
        self.assertEqual(again["messages"], 1)
        self.assertEqual(
            self.texts(MAMA),
            ["St Mary's: Ada Obi's fees account shows NGN 110,000 owing. Please contact the school."],
        )
        self.assertEqual(self.get(self.bursar, "reminders/not-sent/").json()["children"], [])

    def test_the_list_is_each_schools_own(self):
        self.remind(group=self.jss1a, now=lagos(2, 21))
        with connected_to(self.stmarys):
            self.pay(self.ada, 10_000)
        self.send_all(self.released_at(lagos(1, 7)))

        self.client.force_login(self.their_bursar)
        theirs = self.client.get("/api/fees/reminders/not-sent/", HTTP_HOST=THEIR_HOST)
        self.assertEqual(theirs.json()["children"], [])

    def test_a_link_that_stops_receiving_invoices_overnight_is_not_sent(self):
        """D4's re-read, for the link. CONTROL: `send_notice` not asking
        `still_receives_invoices()` sends it."""
        self.remind(group=self.jss1a, now=lagos(2, 21))
        Guardianship.objects.filter(guardian=self.mama, student=self.ada).update(
            receives_invoices=False
        )
        self.send_all(self.released_at(lagos(1, 7)))

        self.assertEqual(self.texts(MAMA), [])
        self.assertIn((self.ada.pk, NoticeOutcome.Said.NO_LONGER_REACHABLE), self.said())


class WhoMaySendTests(RemindersSetUp):
    def test_the_service_refuses_anybody_but_the_bursar_or_an_administrator(self):
        """CONTROL: `_require_reminding()` without its authority check lets the
        principal send."""
        with connected_to(self.stmarys):
            with self.assertRaises(reminders.NotAllowed):
                reminders.send_reminders(self.term_now, actor=self.principal, now=lagos(1, 12))
            answer = reminders.preview_reminders(self.term_now, actor=self.admin, now=lagos(1, 12))
        self.assertEqual(len(answer["children"]), 3)

    def test_the_routes_refuse_in_the_books_own_way(self):
        """A reader who may not write is told so; a teacher gets the books' flat
        404; Grace's bursar is stopped at St Mary's door, before the books."""
        path = f"reminders/?term_id={self.term_now.pk}"
        self.assertEqual(self.get(self.teacher, path).status_code, 404)
        outsider = self.get(self.their_bursar, path)
        self.assertEqual(outsider.status_code, 403)
        self.assertNotIn(b"Ada", outsider.content)
        refused = self.get(self.principal, path)
        self.assertEqual(refused.status_code, 403)
        self.assertIn("bursar or an administrator", refused.json()["detail"])
        self.assertEqual(self.get(self.bursar, path).status_code, 200)

    def test_a_school_that_has_not_turned_them_on_sends_none(self):
        """CONTROL: `_require_reminding()` not asking the switch sends them."""
        with connected_to(self.grace):
            NoticeSettings.objects.filter(pk=1).update(fee_reminders=False)
        self.client.force_login(self.their_bursar)
        with mock.patch("notices.tasks.send_notice.apply_async"):
            refused = self.client.post(
                "/api/fees/reminders/", data=json.dumps({"term_id": self.their_term.pk}),
                content_type="application/json", HTTP_HOST=THEIR_HOST,
            )
        self.assertEqual(refused.status_code, 422, refused.content)
        self.assertIn("does not send fee reminders", refused.json()["detail"])
        with connected_to(self.grace):
            self.assertEqual(Notice.objects.count(), 0)
        # St Mary's, which has, is offered the button.
        books = self.get(self.bursar, "classes/").json()
        self.assertTrue(books["may_remind"])


class TheQuestionTests(RemindersSetUp):
    def test_asking_writes_nothing_and_says_who_and_how_many(self):
        """D10: "see a preview: which children, which guardians, how many
        messages". CONTROL: the preview writing the batch leaves notices behind."""
        asked = self.get(
            self.bursar, f"reminders/?term_id={self.term_now.pk}&class_group_id={self.jss1a.pk}"
        )
        self.assertEqual(asked.status_code, 200, asked.content)
        body = asked.json()
        self.assertEqual(body["messages"], 2)
        self.assertIn("This will send 2 messages about 2 children", body["detail"])
        self.assertEqual(
            [(c["student"], c["guardians"]) for c in body["children"]],
            [("Ada Obi", ["Ngozi Obi"]), ("Bisi Ade", ["Funke Ade"])],
        )
        for school in (self.stmarys, self.grace):
            with connected_to(school):
                self.assertEqual(Notice.objects.count(), 0)

        sent = self.post(
            self.bursar, "reminders/", {"term_id": self.term_now.pk, "class_group_id": self.jss1a.pk}
        )
        self.assertEqual(sent.json()["messages"], 2)

    def test_asked_at_night_the_question_says_seven(self):
        night = lagos(0, 21)
        with mock.patch("notices.reminders.timezone", **{"now.return_value": night}):
            asked = self.get(self.bursar, f"reminders/?term_id={self.term_now.pk}")
        self.assertIn(f"These will be sent at {reminders.hours.said(lagos(-1, 7))}", asked.json()["detail"])

    @override_settings(NOTICE_DAILY_SEGMENTS=2)
    def test_over_the_cap_the_batch_is_refused_whole(self):
        """Requirement 11, shared with the notices' budget. CONTROL:
        `send_reminders()` without `_require_room()` writes all three."""
        with connected_to(self.stmarys):
            with self.assertRaisesMessage(reminders.OverTheCap, "Nothing has been sent"):
                reminders.send_reminders(self.term_now, actor=self.bursar, now=lagos(1, 12))
            self.assertEqual(Notice.objects.count(), 0)
