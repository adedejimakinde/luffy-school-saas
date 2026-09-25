"""Code delivery, end to end: a school sends, the fake delivers, the guardian answers.

`docs/messaging.md` D8 and #111. Every code in here goes through the real
routes: the guardians panel on a school's host sends it, `messaging.codes`
delivers it through the fake provider as a worker would, and the guardian types
it on the portal's sign-in door. Two schools in every test, because the thing a
code a school sends does is turn that guardian live **at that school**, and
"only there" needs a second school to be a claim.
"""

from datetime import timedelta

from django.db import connection
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import GuardianContactCode, User, VerificationCodeStatus
from accounts.tests.test_guardians_api import GuardiansSetUp
from messaging.models import FakeMessage
from messaging.tests.fake import SendsThroughTheFake
from results.tests.fixtures import HOST, PASSWORD, PORTAL, THEIR_HOST
from tests.guardians import give_verified_channel

NUMBER = "0803 123 4567"
E164 = "+2348031234567"
EMAIL = "mama.obi@example.com"


class CodeDeliverySetUp(SendsThroughTheFake, GuardiansSetUp):
    def setUp(self):
        super().setUp()
        self.handset = Client()

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    # -- the school's side ----------------------------------------------------

    def link_id(self, admin, child, contact=NUMBER, host=HOST):
        response = self.link(admin, child, contact=contact, host=host)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["guardians"][-1]["link_id"]

    def send(self, admin, child, link_id, host=HOST, channel_type=None):
        self.client.force_login(admin.user)
        return self.client.post(
            self.url(child, link_id, "send-code"),
            data={"channel_type": channel_type} if channel_type else {},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def sent(self, admin, child, link_id, host=HOST, channel_type=None):
        """Send, deliver through the fake, and return the panel the send answered with."""
        response = self.deliver(lambda: self.send(admin, child, link_id, host, channel_type))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def add(self, admin, child, link_id, contact, host=HOST):
        self.client.force_login(admin.user)
        return self.client.post(
            self.url(child, link_id, "contacts"),
            data={"contact": contact},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def guardian_here(self, admin, child, host=HOST):
        return self.read(admin, child, host).json()["guardians"][0]

    # -- the guardian's side --------------------------------------------------

    def ask(self, value):
        return self.handset.post(
            "/api/guardian/code/", data={"value": value},
            content_type="application/json", HTTP_HOST=PORTAL,
        )

    def answer(self, value, code, guardian=None):
        payload = {"value": value, "code": code}
        if guardian is not None:
            payload["guardian"] = guardian
        return self.handset.post(
            "/api/guardian/session/", data=payload,
            content_type="application/json", HTTP_HOST=PORTAL,
        )

    def answers(self, value, address):
        response = self.answer(value, self.code_sent_to(address))
        self.assertEqual(response.status_code, 200, response.content)
        self.handset = Client()
        return response

    def go_quiet(self, value=E164):
        """Age every answered code on this channel, so it reads dormant. A fold, not a column."""
        GuardianContactCode.objects.filter(
            contact__value=value, status=VerificationCodeStatus.CONFIRMED
        ).update(confirmed_at=timezone.now() - timedelta(days=400))

    def live_at_marys(self):
        """Mama linked to Ada at St Mary's, sent St Mary's code, and answered."""
        link = self.link_id(self.admin, self.ada)
        self.sent(self.admin, self.ada, link)
        self.answers(NUMBER, E164)
        return link


class TheFourDoorsTests(CodeDeliverySetUp):
    def test_a_channel_check_answered_turns_the_link_live_at_that_school_only(self):
        """Door one, over HTTP, as production will run it.

        CONTROL: `_spend()` answering with `confirm_sign_in_code()` alone, as
        it did before, refuses the channel check and this goes red at the answer.
        """
        ours = self.link_id(self.admin, self.ada)
        theirs = self.link_id(self.their_admin, self.chidi, host=THEIR_HOST)

        panel = self.sent(self.admin, self.ada, ours)
        self.assertEqual(panel["guardians"][0]["channels"][0]["last_message"], "waiting to be sent")
        [message] = self.sent_to(E164)
        self.assertIn("St Mary's", message.text)

        self.answers(NUMBER, E164)

        self.assertEqual(self.guardian_here(self.admin, self.ada)["status"], "live")
        self.assertEqual(
            self.guardian_here(self.their_admin, self.chidi, THEIR_HOST)["status"],
            "pending verification",
        )
        self.assertEqual(
            self.guardian_here(self.admin, self.ada)["channels"][0]["last_message"], "sent"
        )
        self.assertTrue(theirs)

    def test_a_school_asks_a_guardian_proved_elsewhere_with_its_own_code(self):
        """Door four (#135): Grace's own code, to a channel St Mary's proved.

        CONTROL: dropping the `activate_guardian_links()` call from
        `confirm_sign_in_code()` leaves Grace pending after the answer.
        """
        self.live_at_marys()
        theirs = self.link_id(self.their_admin, self.chidi, host=THEIR_HOST)

        waiting = self.guardian_here(self.their_admin, self.chidi, THEIR_HOST)
        self.assertEqual(waiting["status"], "pending verification")
        self.assertEqual(waiting["channels"][0]["state"], "not verified here")

        self.sent(self.their_admin, self.chidi, theirs, host=THEIR_HOST)
        message = self.sent_to(E164)[-1]
        self.assertIn("Grace Academy has added you as a parent", message.text)
        self.answers(NUMBER, E164)

        self.assertEqual(self.guardian_here(self.their_admin, self.chidi, THEIR_HOST)["status"], "live")
        self.assertEqual(self.guardian_here(self.admin, self.ada)["status"], "live")

    def test_a_dormant_phone_is_reopened_by_the_school_that_sends_the_code(self):
        """Door three: the human step D9 puts in front of a number that may have changed hands.

        CONTROL: `_spend()` skipping dormant rows, as `sign_in_with_code()`
        did when it spent only the eligible ones, refuses the reactivation code.
        """
        ours = self.live_at_marys()
        self.link_id(self.their_admin, self.chidi, host=THEIR_HOST)
        self.go_quiet()

        channel = self.guardian_here(self.admin, self.ada)["channels"][0]
        self.assertEqual((channel["state"], channel["may_send"]), ("dormant", True))
        _, asked = self.queued(lambda: self.ask(NUMBER))
        self.assertEqual(asked, [], "a dormant phone was sent a sign-in code")

        self.sent(self.admin, self.ada, ours)
        self.assertIn("open this number again", self.sent_to(E164)[-1].text)
        self.answers(NUMBER, E164)

        self.assertEqual(self.guardian_here(self.admin, self.ada)["channels"][0]["state"], "verified")
        # St Mary's code answered St Mary's; Grace has still asked nothing.
        self.assertEqual(
            self.guardian_here(self.their_admin, self.chidi, THEIR_HOST)["status"],
            "pending verification",
        )

    def test_the_request_door_queues_and_never_calls_a_provider(self):
        """Provider latency would say which numbers are guardians. D5, requirement 3.

        CONTROL: `_publish()` calling `send_code()` itself instead of queuing
        it puts a message in the fake during the request, and this goes red.
        """
        self.live_at_marys()
        FakeMessage.objects.all().delete()

        known, known_jobs = self.queued(lambda: self.ask(NUMBER))
        unknown, unknown_jobs = self.queued(lambda: self.ask("0803 999 0000"))

        self.assertEqual(FakeMessage.objects.count(), 0)
        self.assertEqual((len(known_jobs), len(unknown_jobs)), (1, 0))
        self.assertEqual(known.content, unknown.content)


class TheChannelTypedTests(CodeDeliverySetUp):
    """#111, decided 2026-09-24: its five tests, over the real doors."""

    def setUp(self):
        super().setUp()
        # The email first, so that "the oldest row" and "the row typed" differ
        # for the phone: the old rule would send a phone code to the email.
        link = self.link_id(self.admin, self.ada, contact=EMAIL)
        self.sent(self.admin, self.ada, link)
        self.answers(EMAIL, EMAIL)
        self.assertEqual(self.add(self.admin, self.ada, link, NUMBER).status_code, 201)
        self.sent(self.admin, self.ada, link, channel_type="phone")
        self.answers(NUMBER, E164)
        self.link_id(self.their_admin, self.chidi, contact=EMAIL, host=THEIR_HOST)
        FakeMessage.objects.all().delete()

    def test_one_guardian_holds_a_live_email_and_a_live_phone(self):
        channels = self.guardian_here(self.admin, self.ada)["channels"]
        self.assertEqual(
            [(c["channel_type"], c["state"]) for c in channels],
            [("phone", "verified"), ("email", "verified")],
        )

    def test_a_second_live_phone_is_refused(self):
        link = self.guardian_here(self.admin, self.ada)["link_id"]
        refused = self.add(self.admin, self.ada, link, "0805 000 1111")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("already has a live phone channel", refused.json()["detail"])

    def test_the_code_goes_to_the_channel_typed_and_no_other(self):
        """CONTROL: `_live_contacts_for()` taking every live row of the
        guardians `resolve_guardians()` finds, as before, mints the phone's code
        on the older email row, and this goes red."""
        self.deliver(lambda: self.ask(NUMBER))
        self.assertEqual((len(self.sent_to(E164)), len(self.sent_to(EMAIL))), (1, 0))

        self.deliver(lambda: self.ask(EMAIL))
        self.assertEqual((len(self.sent_to(E164)), len(self.sent_to(EMAIL))), (1, 1))

    def test_a_dormant_phone_gets_no_code_while_the_email_still_does(self):
        """CONTROL: `_eligible_for_a_code()` keeping dormant rows sends the
        phone a code, and this goes red."""
        self.go_quiet(E164)

        self.deliver(lambda: self.ask(NUMBER))
        self.deliver(lambda: self.ask(EMAIL))

        self.assertEqual(self.sent_to(E164), [])
        self.answers(EMAIL, EMAIL)

    def test_one_guardian_with_two_channels_sees_no_chooser_and_two_on_one_handset_do(self):
        """CONTROL: the same as the typed-channel test's. With every live row of
        the guardians behind the value, Mama is offered twice, once per row."""
        self.deliver(lambda: self.ask(NUMBER))
        self.answers(NUMBER, E164)

        papa = User.objects.create_user("papa", PASSWORD, full_name="Papa Obi")
        give_verified_channel(papa, NUMBER)
        self.deliver(lambda: self.ask(NUMBER))
        chooser = self.answer(NUMBER, self.code_sent_to(E164))
        self.assertEqual(chooser.status_code, 202, chooser.content)
        offered = chooser.json()["choose"]
        self.assertEqual(len({g["guardian"] for g in offered}), 2)
        self.assertIn("Papa Obi", [g["full_name"] for g in offered])


class ThePanelTests(CodeDeliverySetUp):
    def test_a_principal_may_not_send(self):
        link = self.link_id(self.admin, self.ada)
        refused = self.send(self.head, self.ada, link)
        self.assertEqual(refused.status_code, 403)
        self.assertIn("linked by an administrator", refused.json()["detail"])

    def test_another_schools_admin_cannot_reach_our_link(self):
        link = self.link_id(self.admin, self.ada)
        refused = self.send(self.their_admin, self.ada, link, host=THEIR_HOST)
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(self.sent_to(E164), [])

    @override_settings(MAX_VERIFICATION_SENDS_PER_CHANNEL=1)
    def test_too_many_codes_is_a_sentence_with_a_time_in_it(self):
        link = self.link_id(self.admin, self.ada)
        self.sent(self.admin, self.ada, link)
        refused = self.send(self.admin, self.ada, link)
        self.assertEqual(refused.status_code, 429)
        self.assertIn("Try again in", refused.json()["detail"])

    def test_a_live_current_channel_needs_nothing_from_the_school(self):
        link = self.live_at_marys()
        channel = self.guardian_here(self.admin, self.ada)["channels"][0]
        self.assertFalse(channel["may_send"])
        refused = self.send(self.admin, self.ada, link, channel_type="phone")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("live here already", refused.json()["detail"])

    def test_a_pending_guardian_cannot_be_given_another_channel(self):
        link = self.link_id(self.admin, self.ada)
        refused = self.add(self.admin, self.ada, link, EMAIL)
        self.assertEqual(refused.status_code, 422)
        self.assertIn("answer this school", refused.json()["detail"])

    def test_a_pending_link_does_not_say_which_code_it_was_sent(self):
        """#135: whether a number belongs to a parent elsewhere is not Grace's to learn.

        Mama is proved at St Mary's; a stranger's number is proved nowhere.
        Grace links both and sends to both, and its panel reads the same for
        each: a channel check went to one and Grace's own code to the other.
        """
        self.live_at_marys()
        mama = self.link_id(self.their_admin, self.chidi, host=THEIR_HOST)
        stranger = self.link_id(
            self.their_admin, self.chidi, contact="0805 111 2222", host=THEIR_HOST
        )

        self.sent(self.their_admin, self.chidi, mama, host=THEIR_HOST)
        self.sent(self.their_admin, self.chidi, stranger, host=THEIR_HOST)
        panel = self.read(self.their_admin, self.chidi, THEIR_HOST).json()
        rows = {g["link_id"]: g for g in panel["guardians"]}

        def seen(link):
            row = dict(rows[link]["channels"][0])
            row.pop("value")
            return row, rows[link]["status"], rows[link]["channel"]

        self.assertEqual(seen(mama), seen(stranger))
