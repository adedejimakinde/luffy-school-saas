"""Absence alerts: written by `take_register()` itself, to every live guardian.

Same shape as `test_payment_receipts.py`: two schools, one that turns the
setting on, and a guardian who is also linked at the other school so a cross-
school leak has somewhere to show.

**Every live guardian, not only those who receive invoices** — the one place
this differs from a fee reminder or a receipt. **At most one alert per
register per child**: re-submitting an unchanged register, or a correction
round trip back to absent, must not repeat an alert already sent for the
same register and the same child.
"""

from datetime import date, timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import ContactChannel, Guardianship, Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from attendance import services as attendance
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

MAMA_PHONE = "+2348031110011"       # Ada's mother: a live phone, no email — no alert
AUNTIE_EMAIL = "auntie@example.com"  # Ada's aunt: a live email


class AlertsSetUp(SendsThroughTheFake, TestCase):
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

        self.teacher = self.staff("kemi", "Kemi Teacher", Role.TEACHER, self.stmarys)

        self.ada = self.child("ada", "Ada Obi", self.stmarys, "SM/001")
        self.emeka = self.child("emeka", "Emeka Nwosu", self.stmarys, "SM/002")
        self.zainab = self.child("zainab", "Zainab Musa", self.grace, "GA/001")

        with connected_to(self.stmarys):
            self.term_now = self.term(TermName.FIRST, "2025/2026", date(2025, 9, 15))
            self.jss1a = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(self.jss1a, self.term_now, self.ada)
            academics.place_student(self.jss1a, self.term_now, self.emeka)
        with connected_to(self.grace):
            self.their_term = self.term(TermName.FIRST, "2025/2026", date(2025, 9, 15))
            self.their_group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(self.their_group, self.their_term, self.zainab)

        # Mama: a live phone and nothing else — not reachable by the email
        # this feature is restricted to. Auntie: a live email. Mama is also
        # Zainab's mother at Grace, for the cross-school check.
        self.mama = self.guardian("mama", "Ngozi Obi", [self.ada, self.zainab], phone=MAMA_PHONE)
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
            NoticeSettings.objects.create(pk=1, absence_alerts=True)

    # -- marking and sending -----------------------------------------------

    def mark_absent(self, group, term, absent_ids, *, on=None, school=None, now=None):
        """Take a register with `absent_ids` absent. `(RegisterTaken, [queued task args])`.

        Noon Lagos time unless told otherwise, standing in for the wall clock
        `write_alerts()` reads to decide whether quiet hours hold it —
        `take_register()` itself takes no clock, same as `record_payment()`.
        """
        school = school or self.stmarys
        on = on or date(2025, 9, 17)
        at = lagos(0, 12) if now is None else now

        with connected_to(school):
            with mock.patch("notices.tasks.send_notice.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    with mock.patch("notices.absence_alerts.timezone", **{"now.return_value": at}):
                        taken = attendance.take_register(
                            group, term, on=on, absent_ids=absent_ids, by=self.teacher,
                        )
        return taken, [call.kwargs["args"] for call in publish.call_args_list]

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

    def alerts(self, school=None):
        with connected_to(school or self.stmarys):
            return list(Notice.objects.filter(kind=NoticeKind.ABSENCE_ALERT))


class OffByDefaultTests(AlertsSetUp):
    def test_marking_a_child_absent_writes_no_alert_until_the_school_turns_it_on(self):
        taken, jobs = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])

        self.assertIn(self.ada.pk, taken.absent)
        self.assertEqual(jobs, [])
        self.assertEqual(self.alerts(), [])


class WhoGetsOneTests(AlertsSetUp):
    def setUp(self):
        super().setUp()
        self.offer()

    def test_every_live_guardian_gets_one_not_only_those_who_receive_invoices(self):
        with connected_to(self.stmarys):
            Guardianship.objects.filter(guardian=self.auntie, student=self.ada).update(
                receives_invoices=False
            )
        _, jobs = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        self.send_all(jobs)

        self.assertEqual(len(self.texts(AUNTIE_EMAIL)), 1)

    def test_a_guardian_reachable_only_by_phone_gets_no_alert(self):
        _, jobs = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        self.send_all(jobs)

        self.assertEqual(FakeMessage.objects.filter(channel_type="phone").count(), 0)

    def test_a_present_child_gets_no_alert(self):
        _, jobs = self.mark_absent(self.jss1a, self.term_now, [self.emeka.pk])
        self.send_all(jobs)

        self.assertEqual(self.texts(AUNTIE_EMAIL), [])

    def test_the_text_names_the_child_the_class_and_the_day(self):
        _, jobs = self.mark_absent(
            self.jss1a, self.term_now, [self.ada.pk], on=date(2025, 9, 17),
        )
        self.send_all(jobs)

        [text] = self.texts(AUNTIE_EMAIL)
        self.assertIn("Ada Obi", text)
        self.assertIn("JSS 1A", text)
        self.assertIn("Wednesday 17 September 2025", text)

    def test_the_alert_carries_the_schools_own_contact_email_as_reply_to(self):
        """docs/messaging.md D17."""
        self.stmarys.contact_email = "office@stmarys.example"
        self.stmarys.save(update_fields=["contact_email"])
        _, jobs = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        self.send_all(jobs)

        self.assertEqual(self.reply_tos(AUNTIE_EMAIL), ["office@stmarys.example"])

    def test_each_school_alerts_its_own_register_and_its_own_child(self):
        """Mama has a child at each school. Only St Mary's register is
        alerted, and Grace's own settings (off) leave Zainab untouched."""
        _, ours = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        _, theirs = self.mark_absent(
            self.their_group, self.their_term, [self.zainab.pk], school=self.grace,
        )
        self.send_all(ours)
        with connected_to(self.grace):
            self.assertEqual(theirs, [])
            self.assertEqual(Notice.objects.filter(kind=NoticeKind.ABSENCE_ALERT).count(), 0)


class ResubmittingTests(AlertsSetUp):
    def setUp(self):
        super().setUp()
        self.offer()

    def test_resubmitting_the_same_register_sends_no_second_alert(self):
        _, first = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        _, second = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])  # same day, same mark

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(self.alerts()), 1)

    def test_a_correction_round_trip_on_the_same_register_sends_no_second_alert(self):
        """Absent, corrected to present, corrected back to absent — one
        register, one calendar fact, and D14 dedupes on exactly those two."""
        self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        self.mark_absent(self.jss1a, self.term_now, [])  # corrected to present
        _, third = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])  # absent again

        self.assertEqual(third, [])
        self.assertEqual(len(self.alerts()), 1)


class QuietHoursTests(AlertsSetUp):
    def setUp(self):
        super().setUp()
        self.offer()

    def test_a_register_taken_at_night_is_held_for_the_morning(self):
        _, jobs = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk], now=lagos(0, 21))

        self.assertEqual(jobs, [])
        [alert] = self.alerts()
        self.assertGreater(alert.send_after, lagos(0, 21))

    def test_the_07_00_sweep_queues_a_held_alert(self):
        self.mark_absent(self.jss1a, self.term_now, [self.ada.pk], now=lagos(0, 21))
        [alert] = self.alerts()
        after = alert.send_after + timedelta(minutes=5)
        with connected_to(self.stmarys):
            with mock.patch("notices.tasks.send_notice.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    from notices.tasks import release_held

                    release_held(now=after)
            jobs = [call.kwargs["args"] for call in publish.call_args_list]
        self.send_all(jobs, at=after)
        self.assertEqual(len(self.texts(AUNTIE_EMAIL)), 1)


class OutcomeTests(AlertsSetUp):
    def setUp(self):
        super().setUp()
        self.offer()

    def test_the_outcome_is_recorded_accepted(self):
        _, jobs = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        self.send_all(jobs)

        with connected_to(self.stmarys):
            said = {o.said for o in NoticeOutcome.objects.all()}
        self.assertEqual(said, {NoticeOutcome.Said.ACCEPTED})

    def test_a_guardian_unlinked_before_the_send_gets_no_alert(self):
        _, jobs = self.mark_absent(self.jss1a, self.term_now, [self.ada.pk])
        with connected_to(self.stmarys):
            Guardianship.objects.filter(guardian=self.auntie, student=self.ada).delete()
        self.send_all(jobs)

        self.assertEqual(self.texts(AUNTIE_EMAIL), [])
        with connected_to(self.stmarys):
            said = {o.said for o in NoticeOutcome.objects.all()}
        self.assertEqual(said, {NoticeOutcome.Said.NO_LONGER_REACHABLE})
