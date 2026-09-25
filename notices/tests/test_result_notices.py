"""Result notices: a step after release that tells each family, once. `docs/messaging.md` D9.

Two schools in every test. St Mary's releases JSS 1A and Grace releases its JSS 1A,
and the guardians are built to be each of the cases D4 names: live on a phone,
live on an email, waiting for this school's answer, and dormant. One guardian has
a child at each school, which is requirement 10.

The held-overnight tests use evenings and mornings in the recent past, so that
the send task's own clock agrees that a notice's hour has come.
"""

from datetime import datetime, time, timedelta
from unittest import mock

from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

from accounts import services as accounts
from accounts.models import (
    ContactChannel,
    GuardianContactCode,
    Membership,
    MembershipStatus,
    Role,
    User,
    VerificationCodeStatus,
)
from academics.models import Term
from messaging.models import FakeMessage
from messaging.tests.fake import SendsThroughTheFake
from notices import hours, services, tasks
from notices.models import (
    Notice,
    NoticeClaim,
    NoticeOutcome,
    NoticesAreAppendOnly,
    NoticeSettings,
)
from results import services as chain, withholding
from results.models import ResultSheet
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to
from tests.guardians import answer_at, give_verified_channel
from tests.refusals import RefusalAssertions

MAMA = "+2348031110011"      # Ada's mother, St Mary's, phone
PAPA = "papa.emeka@example.com"  # Emeka's father, St Mary's, email only
NNEKA = "+2348031110022"     # a child at each school, live at both
DORMANT = "+2348031110033"   # Tunde's father, St Mary's, a phone gone quiet
WAITING = "+2348031110044"   # live at Grace, linked at St Mary's, never answered it
CHIDI_MUM = "+2348031110055" # Grace


def lagos(days_ago, hour, minute=0):
    day = timezone.now().astimezone(hours.LAGOS).date() - timedelta(days=days_ago)
    return datetime.combine(day, time(hour, minute), tzinfo=hours.LAGOS)


class NoticesSetUp(SendsThroughTheFake, ChainSetUp):
    def setUp(self):
        super().setUp()
        for school in (self.stmarys, self.grace):
            with connected_to(school):
                NoticeSettings.objects.create(pk=1, result_notices=True)

        c = self.children
        self.mama = self.guardian("mama", "Ngozi Obi", [c["ada"]], phone=MAMA)
        self.papa = self.guardian("papa", "Obinna Nwosu", [c["emeka"]], email=PAPA)
        self.nneka = self.guardian("nneka", "Nneka Ade", [c["bisi"], self.grace_child], phone=NNEKA)
        self.quiet = self.guardian("quiet", "Femi Cole", [c["tunde"]], phone=DORMANT)
        self.age(DORMANT)
        self.chidi_mum = self.guardian("chidimum", "Uche Eze", [self.grace_child], phone=CHIDI_MUM)
        # Live at Grace first, then linked at St Mary's and never answered there (#135).
        self.waiting = self.guardian("waiting", "Kunle Ojo", [self.grace_child], phone=WAITING)
        accounts.link_guardian(self.waiting, c["ada"])

        self.ours = self.release(
            self.stmarys, self.jss1a, self.term_id, (self.teacher, self.vp, self.head)
        )
        self.theirs = self.release(
            self.grace, self.grace_group, self.grace_term_id,
            (self.grace_teacher, self.their_vp, self.their_head),
        )

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    # -- building -------------------------------------------------------------

    def guardian(self, username, name, children, *, phone=None, email=None):
        user = User.objects.create_user(username, PASSWORD, full_name=name)
        for child in children:
            accounts.link_guardian(user, child)
        if phone:
            give_verified_channel(user, phone)
        if email:
            give_verified_channel(user, email, channel_type=ContactChannel.EMAIL)
        return user

    def age(self, value):
        GuardianContactCode.objects.filter(
            contact__value=value, status=VerificationCodeStatus.CONFIRMED
        ).update(confirmed_at=timezone.now() - timedelta(days=400))

    def release(self, school, group, term_id, staff):
        teacher, vp, head = staff
        with connected_to(school):
            sheet = chain.open_sheet(group, Term.objects.get(pk=term_id), head.user)
            chain.submit(sheet, teacher.user)
            chain.check(sheet, vp.user)
            chain.approve(sheet, head.user)
            chain.release(ResultSheet.objects.get(pk=sheet.pk), head.user)
            return sheet.pk

    # -- telling --------------------------------------------------------------

    def tell(self, school, sheet_id, head, *, now=None):
        """`(what the principal is told, [queued task args])`."""
        with connected_to(school):
            with mock.patch("notices.tasks.send_notice.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    told = services.tell_families(
                        ResultSheet.objects.get(pk=sheet_id), actor=head.user, now=now
                    )
        return told, [call.kwargs["args"] for call in publish.call_args_list]

    def send_all(self, jobs):
        for args in jobs:
            tasks.send_notice(*args)
        connection.set_schema_to_public()

    def released_at(self, when):
        with mock.patch("notices.tasks.send_notice.apply_async") as publish:
            tasks.release_held(now=when)
        return [call.kwargs["args"] for call in publish.call_args_list]

    def texts(self, address):
        return [m.text for m in FakeMessage.objects.filter(address=address).order_by("id")]


class TellingFamiliesTests(NoticesSetUp):
    def test_each_live_guardian_is_told_once_on_one_channel(self):
        """D4: live here, verified, not dormant; one channel each.

        CONTROL: dropping the `is_live_at()` check from `recipients.for_child()`
        sends St Mary's notice to the guardian still waiting for its answer.
        """
        told, jobs = self.tell(self.stmarys, self.ours, self.head)
        self.send_all(jobs)

        self.assertEqual(told["messages"], 3)  # Mama, Papa, Nneka
        self.assertEqual(told["unreachable"], 1)  # the dormant phone
        self.assertEqual(len(self.texts(MAMA)), 1)
        self.assertEqual(len(self.texts(PAPA)), 1)
        self.assertEqual(len(self.texts(NNEKA)), 1)
        self.assertEqual(self.texts(DORMANT), [])
        self.assertEqual(self.texts(WAITING), [])
        # Grace has told nobody, so its families have heard nothing.
        self.assertEqual(self.texts(CHIDI_MUM), [])

    def test_a_notice_carries_no_results(self):
        """Requirement 7: the whole text, so nothing else can be in it."""
        _, jobs = self.tell(self.stmarys, self.ours, self.head)
        self.send_all(jobs)

        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
            words = f"{term.get_name_display()} {term.session}"
        self.assertEqual(
            self.texts(MAMA),
            [f"St Mary's: Ada Obi's {words} report card is ready. Sign in on Classnode to read it."],
        )

    def test_each_school_names_only_its_own_child(self):
        """Requirement 10: Nneka has a child at each school and hears from each about that child."""
        _, ours = self.tell(self.stmarys, self.ours, self.head)
        _, theirs = self.tell(self.grace, self.theirs, self.their_head)
        self.send_all(ours + theirs)

        first, second = self.texts(NNEKA)
        self.assertIn("St Mary's: Bisi Ade's", first)
        self.assertNotIn("Grace", first)
        self.assertIn("Grace Academy: Chidi Eze's", second)
        self.assertNotIn("Bisi", second)
        with connected_to(self.stmarys):
            self.assertEqual(Notice.objects.count(), 3)
        with connected_to(self.grace):
            self.assertEqual(Notice.objects.count(), 3)  # Chidi's mother, Nneka, Kunle

    def test_telling_twice_sends_each_notice_once(self):
        """Requirement 13. CONTROL: dropping the `told` skip meets the unique key
        and the second press raises, rather than writing nothing."""
        _, first = self.tell(self.stmarys, self.ours, self.head)
        again, second = self.tell(self.stmarys, self.ours, self.head)
        self.send_all(first + second)

        self.assertEqual((again["messages"], second), (0, []))
        self.assertEqual(len(self.texts(MAMA)), 1)

    def test_a_send_run_twice_sends_once(self):
        """D5. CONTROL: `_claim()` returning the existing claim sends twice."""
        _, jobs = self.tell(self.stmarys, self.ours, self.head)
        self.send_all(jobs)
        self.send_all(jobs)
        self.assertEqual(len(self.texts(MAMA)), 1)


class WithheldCardsTests(NoticesSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            withholding.set_policy(enabled=True, contact="the bursar's office, 0803 555 0123")

    def test_a_withheld_card_is_held_and_says_who_to_call_not_why(self):
        """Requirement 9, and read at the moment of sending, not of asking.

        Asked for at nine in the evening, the card withheld overnight, sent at
        seven: the notice says the school is holding it.

        CONTROL: rendering the text when the notice is asked for, not when it is
        sent, announces the card as ready.
        """
        evening = lagos(2, 21)
        told, jobs = self.tell(self.stmarys, self.ours, self.head, now=evening)
        self.assertEqual(jobs, [])
        with connected_to(self.stmarys):
            withholding.withhold(
                self.children["ada"].pk, Term.objects.get(pk=self.term_id),
                actor=self.head.user, reason="Second term fees unpaid.",
            )
        self.send_all(self.released_at(lagos(1, 7)))

        [text] = self.texts(MAMA)
        self.assertIn("St Mary's is holding Ada Obi's", text)
        self.assertIn("the bursar's office, 0803 555 0123", text)
        self.assertNotIn("fee", text.lower())
        self.assertNotIn("unpaid", text.lower())
        self.assertIn("report card is ready", self.texts(PAPA)[0])


class HeldOvernightTests(NoticesSetUp):
    def test_asked_at_night_sent_at_seven_and_once(self):
        """Requirement 15, at two schools: St Mary's asks at 21:00, Grace at noon.

        CONTROL: `hours.send_after()` returning `now` always queues St Mary's at
        21:00, and the first assertion goes red.
        """
        ours, ours_jobs = self.tell(self.stmarys, self.ours, self.head, now=lagos(2, 21))
        _, theirs_jobs = self.tell(self.grace, self.theirs, self.their_head, now=lagos(2, 12))

        self.assertEqual(ours_jobs, [])
        self.assertEqual(ours["held_until"], lagos(1, 7))
        self.assertEqual(len(theirs_jobs), 3)
        self.send_all(theirs_jobs)  # Grace's went at noon, so 07:00 has only St Mary's to send

        self.assertEqual(self.released_at(lagos(1, 6, 59)), [])
        at_seven = self.released_at(lagos(1, 7))
        self.assertEqual(len(at_seven), 3)
        self.send_all(at_seven)
        self.send_all(self.released_at(lagos(1, 7, 15)))  # the next sweep: nothing new

        self.assertEqual(len(self.texts(MAMA)), 1)

    def test_a_guardian_suspended_overnight_is_not_sent(self):
        """D4 is read again when a held notice goes."""
        self.tell(self.stmarys, self.ours, self.head, now=lagos(2, 21))
        Membership.objects.filter(
            user=self.mama, school=self.stmarys, role=Role.PARENT
        ).update(status=MembershipStatus.SUSPENDED)

        self.send_all(self.released_at(lagos(1, 7)))

        self.assertEqual(self.texts(MAMA), [])
        self.assertEqual(len(self.texts(PAPA)), 1)
        with connected_to(self.stmarys):
            said = NoticeOutcome.objects.get(claim__notice__address=MAMA).said
        self.assertEqual(said, NoticeOutcome.Said.NO_LONGER_REACHABLE)


class TheCapTests(NoticesSetUp):
    @override_settings(NOTICE_DAILY_SEGMENTS=2)
    def test_a_batch_over_the_cap_is_refused_whole(self):
        """Requirement 11: three segments against a cap of two, and none of the three goes.

        CONTROL: dropping `_require_room()` writes and queues all three.
        """
        with self.assertRaisesMessage(services.OverTheCap, "Nothing has been sent"):
            self.tell(self.stmarys, self.ours, self.head)
        with connected_to(self.stmarys):
            self.assertEqual(Notice.objects.count(), 0)

    @override_settings(NOTICE_DAILY_SEGMENTS=3)
    def test_each_school_has_its_own_day(self):
        """St Mary's three segments use St Mary's cap, not Grace's."""
        ours, _ = self.tell(self.stmarys, self.ours, self.head)
        theirs, _ = self.tell(self.grace, self.theirs, self.their_head)
        self.assertEqual((ours["segments"], theirs["segments"]), (3, 3))


class TheSwitchTests(NoticesSetUp):
    def test_a_school_that_has_not_turned_it_on_is_offered_nothing(self):
        with connected_to(self.grace):
            NoticeSettings.objects.filter(pk=1).update(result_notices=False)
        self.client.force_login(self.their_head.user)
        rows = self.client.get("/api/results/chain/", HTTP_HOST=THEIR_HOST).json()["rows"]
        self.assertFalse(any(r["may_tell_families"] for r in rows))
        refused = self.client.post(
            f"/api/results/chain/{self.grace_group_id}/tell-families/", HTTP_HOST=THEIR_HOST
        )
        self.assertEqual(refused.status_code, 422)
        self.assertIn("does not send result notices", refused.json()["detail"])
        # St Mary's, which has, is offered the button.
        self.client.force_login(self.head.user)
        rows = self.client.get("/api/results/chain/", HTTP_HOST=HOST).json()["rows"]
        self.assertTrue(any(r["may_tell_families"] for r in rows))

    def test_only_whoever_may_release_may_tell(self):
        self.client.force_login(self.teacher.user)
        refused = self.client.post(f"/api/results/chain/{self.jss1a_id}/tell-families/", HTTP_HOST=HOST)
        self.assertEqual(refused.status_code, 403)

    def test_the_principal_is_told_what_happened_and_the_row_counts_it(self):
        self.client.force_login(self.head.user)
        with mock.patch("notices.tasks.send_notice.apply_async"):
            answer = self.client.post(
                f"/api/results/chain/{self.jss1a_id}/tell-families/", HTTP_HOST=HOST
            )
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(answer.json()["messages"], 3)
        self.assertIn("1 guardian here has no verified phone or email", answer.json()["detail"])
        row = next(
            r for r in self.client.get("/api/results/chain/", HTTP_HOST=HOST).json()["rows"]
            if r["class_group_id"] == self.jss1a_id
        )
        self.assertEqual(row["families_told"], 3)


class TheRecordIsAppendOnlyTests(NoticesSetUp, RefusalAssertions):
    def test_the_tables_refuse_an_edit_and_a_delete(self):
        _, jobs = self.tell(self.stmarys, self.ours, self.head)
        self.send_all(jobs)
        with connected_to(self.stmarys):
            claim = NoticeClaim.objects.first()
            for table, pk in (
                ("notices_notice", claim.notice_id),
                ("notices_noticeclaim", claim.pk),
                ("notices_noticeoutcome", claim.outcome.pk),
            ):
                with self.subTest(table=table):
                    for verb, sql in (
                        ("UPDATE", f"UPDATE {table} SET id = id WHERE id = %s"),
                        ("DELETE", f"DELETE FROM {table} WHERE id = %s"),
                    ):
                        with self.assertRefusedBy(
                            f"{table} is append-only; {verb} is not allowed"
                        ), transaction.atomic(), connection.cursor() as cursor:
                            cursor.execute(sql, [pk])

    def test_the_models_refuse_before_the_tables_have_to(self):
        _, jobs = self.tell(self.stmarys, self.ours, self.head)
        self.send_all(jobs)
        with connected_to(self.stmarys):
            claim = NoticeClaim.objects.first()
            for row in (claim.notice, claim, claim.outcome):
                with self.subTest(row=type(row).__name__):
                    with self.assertRaises(NoticesAreAppendOnly):
                        row.save()
                    with self.assertRaises(NoticesAreAppendOnly):
                        row.delete()
