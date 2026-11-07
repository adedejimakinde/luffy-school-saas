"""Sitting a test: `docs/cbt.md`, Phase 2 step 4.

Two schools on their own hosts (`results.tests.fixtures.ChainSetUp`), whose first class,
term, subject, test and student share ids, and whose first students share an admission
number. The claims, each with a control in `docs/cbt.md` ("Built", step 4):

- **The door**: a wrong code, a wrong number, a wrong PIN, somebody else's PIN, a
  cancelled PIN and another school's code get one refusal, counted per admission number
  and per address; while a wait lasts the right answer is refused too. Only a proved
  door says the sitting is not open, or that they have sat it.
- **No key reaches a student's device**: no response under `/sit/` carries a correct
  index or an explanation.
- **Answers**: saved once whatever the resends, the later sequence or the later choice
  counts, both kept; an answer after `deadline + late_window`, or chosen after the
  deadline, is refused and logged; the server closes the attempt at that time.
- **One computer holds an attempt**; a second ends the first, which is told so.
- **Extra time, retakes, the code and opening or closing a sitting**, each only by whom
  `docs/cbt.md` names, with a reason where one is owed, and logged.
- **The sitting log** has no answer in it, and the administrator reads it.
- **The `/sit/` cookie opens one attempt and no other route**, at one school.
"""

import json
import re
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

from django.db import connection, transaction
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, User
from accounts.services import grant_membership, link_guardian
from cbt import officers, pins, sittings
from cbt.models import (
    AnswerEvent,
    Attempt,
    AttemptEvent,
    AttemptSession,
    RetakeGrant,
    SittingControl,
    Test,
    TestCodeChange,
    TestItem,
    TimeExtension,
)
from cbt.sitting import ALREADY_SAT, NOT_OPEN_NOW, NOT_OPENED, WAIT
# The module, not the class: a class in this module's namespace is collected here too,
# and `BanksSetUp` carries a helper whose name starts with `test`.
from cbt.tests import test_banks_and_tests
from results.tests.fixtures import HOST, THEIR_HOST
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

SIT = "/sit/api/"
STAFF = "/api/cbt/"
#: Anything that would give an answer away, as a JSON key.
KEYS = re.compile(r'"(correct_index|explanation|topic)"')
CODE = "KMTRWX"
GRACE_CODE = "PQZHNB"


class SittingSetUp(test_banks_and_tests.BanksSetUp):
    def setUp(self):
        super().setUp()
        for handle, number in (("ada", "SM/001"), ("emeka", "SM/002"), ("bisi", "SM/003"), ("tunde", "SM/004")):
            Membership.objects.filter(pk=self.children[handle].pk).update(reference=number)
        Membership.objects.filter(pk=self.bimpe.pk).update(reference="SM/005")
        Membership.objects.filter(pk=self.grace_child.pk).update(reference="SM/001")
        for m in (*self.children.values(), self.bimpe, self.grace_child):
            m.refresh_from_db()
        self.test_id = self.published()
        with connected_to(self.stmarys):
            slips = pins.print_class_as(self.head.user, self.stmarys, self.jss1a_id)
            self.pins = {s.admission_number: s.pin for s in slips.slips}
            pins.print_class_as(self.head.user, self.stmarys, self.jss1b_id)
            sittings.set_code_as(self.head.user, self.stmarys, self.test_id, code=CODE)
            test = Test.objects.get(pk=self.test_id)
            self.opens, self.closes, self.duration = test.opens_at, test.closes_at, test.duration
            self.item_ids = list(TestItem.objects.filter(test=test).order_by("position").values_list("pk", flat=True))
        self.device = Client()
        self.responses = []

    # -- time ---------------------------------------------------------------------

    @contextmanager
    def at(self, when):
        with mock.patch("django.utils.timezone.now", return_value=when):
            yield

    def in_window(self, minutes=5):
        return self.opens + timedelta(minutes=minutes)

    # -- the student's device ------------------------------------------------------

    def sit(self, path, data=None, device=None, host=HOST, method="post"):
        device = device or self.device
        if method == "get":
            response = device.get(f"{SIT}{path}", HTTP_HOST=host)
        else:
            response = device.post(
                f"{SIT}{path}", data=json.dumps(data or {}), content_type="application/json", HTTP_HOST=host
            )
        connection.set_schema_to_public()
        self.responses.append(response)
        return response

    def door(self, number="SM/001", pin=None, code=CODE, **kw):
        pin = self.pins.get(number, "00000000") if pin is None else pin
        return self.sit("door/", {"code": code, "admission_number": number, "pin": pin}, **kw)

    def started(self, number="SM/001", device=None, when=None, seat="Seat 1"):
        with self.at(when or self.in_window()):
            door = self.door(number, device=device)
            self.assertEqual(door.status_code, 200, door.content)
            response = self.sit("start/", {"ticket": door.json()["ticket"], "seat": seat}, device=device)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def answer(self, seq, item, chosen, chosen_at=None, device=None, when=None):
        when = when or self.in_window(6)
        body = {"answers": [{"seq": seq, "item": item, "chosen": chosen, "chosen_at": (chosen_at or when).isoformat()}]}
        with self.at(when):
            return self.sit("sync/", body, device=device)

    # -- staff ---------------------------------------------------------------------

    def staff(self, who, path, data=None, host=HOST):
        return self.post(who, path, data, host=host)

    def open_by_hand(self, who=None, reason="Moved to period 2"):
        return self.staff(who or self.head, f"tests/{self.test_id}/classes/{self.jss1a_id}/open/", {"reason": reason})

    def counted(self):
        from cbt import sitting

        with connected_to(self.stmarys):
            attempt = Attempt.objects.get(test_id=self.test_id, student_membership_id=self.children["ada"].pk)
            return sitting.counted_answers(attempt)

    def events(self, **filters):
        with connected_to(self.stmarys):
            return list(AttemptEvent.objects.filter(test_id=self.test_id, **filters).order_by("id").values_list("kind", flat=True))


class TheDoorTests(SittingSetUp):
    def test_the_right_three_say_who_and_start_nothing(self):
        with self.at(self.in_window()):
            response = self.door()
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["student"], {"name": "Ada Obi", "admission_number": "SM/001", "class_name": "JSS 1A"})
        self.assertEqual((body["test"]["title"], body["test"]["questions"], body["resuming"]), ("First CA test", 4, False))
        with connected_to(self.stmarys):
            self.assertFalse(Attempt.objects.exists())
        self.assertNotIn("sit", response.cookies)

    def test_every_wrong_answer_is_one_refusal(self):
        with connected_to(self.stmarys):
            # A cancelled PIN: Emeka's slip is printed again, so his first PIN stops.
            old = self.pins["SM/002"]
            pins.print_student_as(self.head.user, self.stmarys, self.jss1a_id, self.children["emeka"].pk)
        cases = {
            "a wrong PIN": dict(number="SM/001", pin="12345678"),
            "somebody else's PIN": dict(number="SM/001", pin=self.pins["SM/003"]),
            "a cancelled PIN": dict(number="SM/002", pin=old),
            "an unknown number": dict(number="SM/999", pin=self.pins["SM/001"]),
            "a wrong code": dict(number="SM/001", code="ZZZZZZ"),
            "a code too short": dict(number="SM/001", code="KMT"),
            "no PIN at all": dict(number="SM/001", pin=""),
            # Bimpe is in JSS 1B, which does not sit this test; her PIN is real.
            "a student not in its classes": dict(number="SM/005", pin=None),
        }
        with connected_to(self.stmarys):
            bimpe_pin = pins.print_student_as(self.head.user, self.stmarys, self.jss1b_id, self.bimpe.pk).slips[0].pin
        cases["a student not in its classes"]["pin"] = bimpe_pin
        bodies = set()
        with self.at(self.in_window()):
            for why, case in cases.items():
                with self.subTest(why):
                    response = self.door(**case)
                    self.assertEqual(response.status_code, 404, response.content)
                    self.assertEqual(response.json()["detail"], NOT_OPENED)
                    bodies.add(response.content)
        self.assertEqual(len(bodies), 1)

    def test_another_schools_code_opens_nothing_here(self):
        """Grace's test has the same id as St Mary's and a code of its own; Grace's code,
        and Grace's student's number and PIN, open nothing at St Mary's, and the other way."""
        grace_test = self.grace_published()
        self.assertEqual(grace_test, self.test_id)
        with self.at(self.in_window()):
            here = self.door("SM/001", pin=self.grace_pins["SM/001"], code=GRACE_CODE)
            there = self.door("SM/001", pin=self.pins["SM/001"], code=CODE, host=THEIR_HOST)
            theirs = self.door("SM/001", pin=self.grace_pins["SM/001"], code=GRACE_CODE, host=THEIR_HOST)
        self.assertEqual((here.status_code, there.status_code), (404, 404))
        self.assertEqual(here.json()["detail"], NOT_OPENED)
        self.assertEqual(theirs.status_code, 200, theirs.content)
        self.assertEqual(theirs.json()["student"]["name"], "Chidi Eze")

    def grace_published(self):
        self.fill(self.grace_teacher, 4, host=THEIR_HOST, subject_id=self.grace_maths_id)
        body = self.test_body(classes=[self.grace_group_id], subject_id=self.grace_maths_id)
        response = self.post(self.grace_teacher, "tests/", body, host=THEIR_HOST)
        self.assertEqual(response.status_code, 200, response.content)
        test_id = response.json()["id"]
        self.assertEqual(self.post(self.grace_teacher, f"tests/{test_id}/submit/", host=THEIR_HOST).status_code, 200)
        self.assertEqual(self.post(self.their_head, f"tests/{test_id}/approve/", host=THEIR_HOST).status_code, 200)
        with connected_to(self.grace):
            slips = pins.print_class_as(self.their_head.user, self.grace, self.grace_group_id)
            self.grace_pins = {s.admission_number: s.pin for s in slips.slips}
            sittings.set_code_as(self.their_head.user, self.grace, test_id, code=GRACE_CODE)
        return test_id

    @override_settings(SIT_MAX_FAILURES_PER_ADMISSION_NUMBER=3)
    def test_wrong_tries_are_counted_per_number_and_then_even_the_right_one_waits(self):
        with self.at(self.in_window()):
            for _ in range(3):
                self.assertEqual(self.door(pin="11111111").status_code, 404)
            waiting = self.door()
            other = self.door("SM/002")
        self.assertEqual(waiting.status_code, 429)
        self.assertEqual(waiting.json()["detail"], WAIT)
        self.assertGreater(waiting.json()["retry_after"], 0)
        self.assertEqual(other.status_code, 200, "another number is not made to wait")

    @override_settings(SIT_MAX_FAILURES_PER_ADDRESS=3)
    def test_wrong_tries_are_counted_per_address(self):
        with self.at(self.in_window()):
            for number in ("SM/101", "SM/102", "SM/103"):
                self.assertEqual(self.door(number, pin="11111111").status_code, 404)
            self.assertEqual(self.door().status_code, 429)

    def test_a_proved_door_says_the_sitting_is_not_open_and_a_wrong_one_does_not(self):
        early = self.opens - timedelta(hours=1)
        with self.at(early):
            proved = self.door()
            wrong = self.door(pin="11111111")
        self.assertEqual((proved.status_code, proved.json()["detail"]), (409, NOT_OPEN_NOW))
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (404, NOT_OPENED))
        with self.at(self.closes + timedelta(minutes=1)):
            self.assertEqual(self.door().json()["detail"], NOT_OPEN_NOW)

    def test_opening_and_closing_by_hand_decide_and_are_logged(self):
        early = self.opens - timedelta(hours=1)
        with self.at(early):
            self.assertEqual(self.open_by_hand().status_code, 200)
            self.assertEqual(self.door().status_code, 200)
        closed = self.staff(self.admin, f"tests/{self.test_id}/classes/{self.jss1a_id}/close/", {"reason": "Fire drill"})
        self.assertEqual(closed.status_code, 200, closed.content)
        with self.at(self.in_window()):
            self.assertEqual(self.door().json()["detail"], NOT_OPEN_NOW, "the latest control decides, not the window")
        with connected_to(self.stmarys):
            rows = list(SittingControl.objects.order_by("id").values_list("kind", "reason", "role"))
        self.assertEqual(rows, [("opened", "Moved to period 2", "principal"), ("closed", "Fire drill", "administrator")])
        self.assertEqual(self.open_by_hand(reason="").status_code, 422)

    def test_not_me_is_logged_and_starts_nothing(self):
        with self.at(self.in_window()):
            ticket = self.door().json()["ticket"]
            response = self.sit("not-me/", {"ticket": ticket})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.events(), ["not_me"])
        with connected_to(self.stmarys):
            self.assertFalse(Attempt.objects.exists())

    def test_a_guardian_session_never_reaches_the_door(self):
        parent = User.objects.create_user("papa", "a-long-password-1", full_name="Papa Obi")
        link_guardian(parent, self.children["emeka"])
        give_verified_channel(parent, "08030000072")
        with self.at(self.in_window()):
            # Signed in at the moment the clock is moved to, or the session has expired.
            self.device.force_login(parent)
            response = self.door()
        self.assertEqual(response.status_code, 403)
        page = self.device.get("/sit/", HTTP_HOST=HOST)
        connection.set_schema_to_public()
        self.assertContains(page, 'data-guardian="1"')

    def test_the_door_is_only_on_a_schools_host(self):
        from results.tests.fixtures import PORTAL

        self.assertEqual(self.client.get("/sit/", HTTP_HOST=PORTAL).status_code, 404)
        connection.set_schema_to_public()
        self.assertEqual(self.door(host=PORTAL).status_code, 404)

    def test_a_write_must_be_json(self):
        response = self.device.post(f"{SIT}door/", {"code": CODE}, HTTP_HOST=HOST)
        connection.set_schema_to_public()
        self.assertEqual(response.status_code, 415)


class StartingAndTheKeyTests(SittingSetUp):
    def test_start_writes_the_attempt_with_the_servers_times_and_a_cookie_for_sit_only(self):
        when = self.in_window()
        with self.at(when):
            ticket = self.door().json()["ticket"]
            response = self.sit("start/", {"ticket": ticket, "seat": "Lab seat 4", "sync_offset_ms": 1500})
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        cookie = response.cookies["sit"]
        self.assertEqual(cookie["path"], "/sit/")
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(body["now"], when.isoformat())
        self.assertEqual(body["deadline"], (when + timedelta(minutes=self.duration)).isoformat())
        self.assertEqual(body["late_window"], 120)
        self.assertEqual(len(body["paper"]["items"]), 4)
        with connected_to(self.stmarys):
            attempt = Attempt.objects.get()
            session = AttemptSession.objects.get()
        self.assertEqual((attempt.started_at, attempt.number, session.seat, session.sync_offset_ms), (when, 1, "Lab seat 4", 1500))
        self.assertEqual(self.events(), ["start"])

    def test_a_late_starter_gets_until_the_test_closes(self):
        late = self.closes - timedelta(minutes=10)
        body = self.started(when=late)
        self.assertEqual(body["deadline"], self.closes.isoformat())

    def test_no_response_a_students_device_receives_carries_a_key(self):
        body = self.started()
        first = body["paper"]["items"][0]
        self.answer(1, first["id"], first["options"][0]["index"])
        with self.at(self.in_window(7)):
            self.sit("attempt/", method="get")
            self.sit("submit/", {})
        with connected_to(self.stmarys):
            explanations = [e for e in TestItem.objects.values_list("explanation", flat=True) if e]
        self.assertGreaterEqual(len(self.responses), 5)
        for response in self.responses:
            with self.subTest(path=response.request["PATH_INFO"]):
                text = response.content.decode()
                self.assertIsNone(KEYS.search(text), text[:200])
                for explanation in explanations:
                    self.assertNotIn(explanation, text)

    def test_an_option_is_sent_with_its_original_index_in_the_students_order(self):
        body = self.started()
        with connected_to(self.stmarys):
            items = {i.pk: i.options for i in TestItem.objects.all()}
        for item in body["paper"]["items"]:
            self.assertEqual(sorted(o["index"] for o in item["options"]), list(range(len(items[item["id"]]))))
            for o in item["options"]:
                self.assertEqual(o["text"], items[item["id"]][o["index"]])

    def test_after_submit_signing_in_again_opens_nothing(self):
        self.started()
        with self.at(self.in_window(8)):
            self.assertEqual(self.sit("submit/", {}).status_code, 200)
            again = self.door()
        self.assertEqual((again.status_code, again.json()["detail"]), (409, ALREADY_SAT))


class AnswersTests(SittingSetUp):
    def test_an_answer_is_saved_once_however_often_it_is_sent(self):
        item = self.started()["paper"]["items"][0]["id"]
        for _ in range(3):
            response = self.answer(1, item, 2)
            self.assertEqual(response.json()["acks"], [1])
        with connected_to(self.stmarys):
            self.assertEqual(AnswerEvent.objects.count(), 1)
        self.assertEqual(self.counted(), {item: 2})

    def test_one_computer_the_later_sequence_counts_whatever_order_they_arrive_in(self):
        item = self.started()["paper"]["items"][0]["id"]
        when = self.in_window(6)
        body = {"answers": [
            {"seq": 2, "item": item, "chosen": 3, "chosen_at": when.isoformat()},
            {"seq": 1, "item": item, "chosen": 1, "chosen_at": when.isoformat()},
        ]}
        with self.at(when):
            self.assertEqual(sorted(self.sit("sync/", body).json()["acks"]), [1, 2])
        self.assertEqual(self.counted(), {item: 3})
        # And a later batch with the earlier number does not undo it.
        self.answer(3, item, 0, when=self.in_window(7))
        self.answer(1, item, 1, when=self.in_window(8))
        self.assertEqual(self.counted(), {item: 0})
        with connected_to(self.stmarys):
            self.assertEqual(AnswerEvent.objects.count(), 3, "every answer is kept")

    def test_a_cleared_answer_counts_as_none(self):
        item = self.started()["paper"]["items"][0]["id"]
        self.answer(1, item, 2)
        self.answer(2, item, None, when=self.in_window(7))
        self.assertEqual(self.counted(), {item: None})

    def test_an_answer_for_another_tests_item_or_an_option_it_has_not_is_ignored(self):
        item = self.started()["paper"]["items"][0]["id"]
        self.assertEqual(self.answer(1, item + 999, 1).json()["acks"], [])
        self.assertEqual(self.answer(2, item, 7).json()["acks"], [])
        with connected_to(self.stmarys):
            self.assertEqual(AnswerEvent.objects.count(), 0)

    def test_reloading_restores_the_answers_and_the_same_deadline(self):
        body = self.started()
        item = body["paper"]["items"][1]["id"]
        self.answer(1, item, 1)
        with self.at(self.in_window(12)):
            again = self.sit("attempt/", method="get").json()
        self.assertEqual(again["answers"], {str(item): 1})
        self.assertEqual(again["deadline"], body["deadline"])
        self.assertEqual(again["now"], self.in_window(12).isoformat())
        self.assertEqual([i["id"] for i in again["paper"]["items"]], [i["id"] for i in body["paper"]["items"]])

    def test_device_events_are_logged_once_each_and_a_heartbeat_gap_is_noted(self):
        self.started()
        events = {"events": [
            {"seq": 1, "kind": "left_page", "at": self.in_window(6).isoformat(), "seconds": 14},
            {"seq": 2, "kind": "disconnect", "at": self.in_window(6).isoformat()},
            {"seq": 3, "kind": "reconnect", "at": self.in_window(7).isoformat()},
            {"seq": 4, "kind": "not_a_kind"},
        ]}
        with self.at(self.in_window(8)):
            self.assertEqual(self.sit("sync/", events).json()["event_acks"], [1, 2, 3])
            self.sit("sync/", events)
        self.assertEqual(self.events(said_by="device"), ["left_page", "disconnect", "reconnect"])
        # The server saw three minutes without a heartbeat before that sync.
        self.assertEqual(self.events(said_by="server"), ["start", "disconnect"])


class TheServersDeadlineTests(SittingSetUp):
    def test_an_answer_chosen_in_time_is_accepted_inside_the_late_window_and_refused_after(self):
        body = self.started()
        deadline = timezone.datetime.fromisoformat(body["deadline"])
        first, second, third = [i["id"] for i in body["paper"]["items"][:3]]
        chosen = deadline - timedelta(seconds=30)
        inside = self.answer(1, first, 1, chosen_at=chosen, when=deadline + timedelta(seconds=90))
        self.assertEqual(inside.json()["refused"], [])
        after_time = self.answer(2, second, 1, chosen_at=deadline + timedelta(seconds=5), when=deadline + timedelta(seconds=95))
        self.assertEqual(after_time.json()["refused"], [{"seq": 2, "why": "after_time"}])
        late = self.answer(3, third, 1, chosen_at=chosen, when=deadline + timedelta(minutes=2, seconds=1))
        self.assertEqual(late.json()["refused"], [{"seq": 3, "why": "after_submit"}])
        self.assertTrue(late.json()["closed"])
        self.assertEqual(self.counted(), {first: 1})
        with connected_to(self.stmarys):
            attempt = Attempt.objects.get()
            refused = list(AnswerEvent.objects.filter(accepted=False).values_list("refusal", flat=True))
        self.assertEqual(attempt.ended_by, "clock")
        self.assertEqual(attempt.submitted_at, deadline + timedelta(minutes=2))
        self.assertEqual(sorted(refused), ["after_submit", "after_time"])
        # The server also saw the heartbeat stop while the device was away.
        self.assertEqual(self.events(), ["start", "disconnect", "late_refused", "clock_submit", "late_refused"])

    def test_a_device_cannot_claim_a_choice_from_the_future(self):
        body = self.started()
        item = body["paper"]["items"][0]["id"]
        when = self.in_window(6)
        self.answer(1, item, 1, chosen_at=when + timedelta(hours=5), when=when)
        with connected_to(self.stmarys):
            self.assertEqual(AnswerEvent.objects.get().chosen_at, when)

    def test_the_server_closes_the_attempt_on_any_read_once_time_and_window_are_over(self):
        body = self.started()
        deadline = timezone.datetime.fromisoformat(body["deadline"])
        with self.at(deadline + timedelta(minutes=3)):
            state = self.sit("attempt/", method="get").json()
            log = self.get(self.head, f"tests/{self.test_id}/sitting/")
        self.assertTrue(state["closed"])
        self.assertEqual(state["ended_by"], "clock")
        self.assertEqual(log.json()["rows"][0]["state"], "Time ran out")


class OneComputerAtATimeTests(SittingSetUp):
    def test_a_second_computer_takes_over_and_the_first_is_told(self):
        first_device, second_device = Client(), Client()
        first = self.started(device=first_device, seat="Seat 4")
        item = first["paper"]["items"][0]["id"]
        self.answer(1, item, 1, device=first_device, when=self.in_window(6))
        second = self.started(device=second_device, when=self.in_window(9), seat="Seat 9")
        self.assertEqual(second["deadline"], first["deadline"], "the clock did not stop or restart")
        self.assertEqual(second["answers"], {str(item): 1})
        self.assertTrue(second["resumed"])

        # The first computer, back on: told it is replaced; its outbox is still taken, by time.
        told = self.answer(2, item, 2, chosen_at=self.in_window(7), device=first_device, when=self.in_window(10))
        self.assertTrue(told.json()["replaced"])
        self.assertEqual(told.json()["acks"], [2])
        self.answer(1, item, 3, chosen_at=self.in_window(9) + timedelta(seconds=30), device=second_device, when=self.in_window(10))
        self.assertEqual(self.counted(), {item: 3})
        with self.at(self.in_window(11)):
            refused = self.sit("submit/", {}, device=first_device)
        self.assertEqual(refused.status_code, 409)
        self.assertTrue(refused.json()["replaced"])
        with connected_to(self.stmarys):
            sessions = list(AttemptSession.objects.order_by("id").values_list("seat", "ended_by"))
            replaced = AttemptEvent.objects.get(kind="replaced")
        self.assertEqual(sessions, [("Seat 4", "replaced"), ("Seat 9", "")])
        self.assertEqual((replaced.detail["from_seat"], replaced.detail["to_seat"]), ("Seat 4", "Seat 9"))
        self.assertEqual(self.events(), ["start", "replaced", "resume"])

    def test_of_two_computers_the_answer_chosen_later_counts_and_both_are_kept(self):
        first_device, second_device = Client(), Client()
        item = self.started(device=first_device)["paper"]["items"][0]["id"]
        self.started(device=second_device, when=self.in_window(8))
        # The second computer's answer arrives first but was chosen later.
        self.answer(1, item, 2, chosen_at=self.in_window(8) + timedelta(minutes=1), device=second_device, when=self.in_window(10))
        self.answer(1, item, 1, chosen_at=self.in_window(7), device=first_device, when=self.in_window(11))
        self.assertEqual(self.counted(), {item: 2})
        with connected_to(self.stmarys):
            loser = AnswerEvent.objects.get(chosen=1)
            winner = AnswerEvent.objects.get(chosen=2)
        self.assertEqual(loser.superseded_by_id, winner.pk)

    def test_two_choices_too_close_to_call_are_settled_by_which_arrived_later(self):
        first_device, second_device = Client(), Client()
        item = self.started(device=first_device)["paper"]["items"][0]["id"]
        self.started(device=second_device, when=self.in_window(8))
        at = self.in_window(9)
        self.answer(1, item, 2, chosen_at=at + timedelta(seconds=1), device=second_device, when=self.in_window(10))
        self.answer(1, item, 1, chosen_at=at, device=first_device, when=self.in_window(11))
        self.assertEqual(self.counted(), {item: 1})
        with connected_to(self.stmarys):
            self.assertTrue(AnswerEvent.objects.get(chosen=1).tie)

    def test_the_database_holds_one_open_session_per_attempt(self):
        self.started()
        with connected_to(self.stmarys):
            attempt = Attempt.objects.get()
            with self.assertRefusedBy("one_computer_holds_an_attempt"), transaction.atomic():
                AttemptSession.objects.create(
                    attempt=attempt, token_digest="x" * 64, signed_in_at=timezone.now(), last_seen_at=timezone.now()
                )


class WhoRunsASittingTests(SittingSetUp):
    def setUp(self):
        super().setUp()
        self.officer = grant_membership(
            User.objects.create_user("obi", "a-long-password-1", full_name="Obi Officer"), self.stmarys, Role.TEACHER
        )
        with connected_to(self.stmarys):
            officers.name_as(self.head.user, self.stmarys, self.officer.pk)

    def ada(self):
        return self.children["ada"].pk

    def test_extra_time_by_the_teacher_an_exam_officer_and_the_administrator_only(self):
        for who in (self.teacher, self.officer, self.admin, self.head):
            with self.subTest(who=who.user.username):
                response = self.staff(who, f"tests/{self.test_id}/students/{self.ada()}/extra-time/", {"minutes": 5, "reason": "Power cut"})
                self.assertEqual(response.status_code, 200, response.content)
        for who in (self.tayo, self.vp, self.bursar, self.their_head):
            with self.subTest(who=who.user.username):
                response = self.staff(who, f"tests/{self.test_id}/students/{self.ada()}/extra-time/", {"minutes": 5, "reason": "Power cut"})
                self.assertIn(response.status_code, (403, 404))
        empty = self.staff(self.teacher, f"tests/{self.test_id}/students/{self.ada()}/extra-time/", {"minutes": 5, "reason": " "})
        self.assertEqual(empty.status_code, 422)
        with connected_to(self.stmarys):
            rows = list(TimeExtension.objects.order_by("id").values_list("role", "minutes", "reason"))
        self.assertEqual([r[0] for r in rows], ["teacher", "exam officer", "administrator", "principal"])

    def test_extra_time_moves_one_students_deadline_and_none_after_their_attempt_closes(self):
        before = self.started()
        self.staff(self.teacher, f"tests/{self.test_id}/students/{self.ada()}/extra-time/", {"minutes": 10, "reason": "Power cut"})
        with self.at(self.in_window(6)):
            after = self.sit("sync/", {}).json()
        self.assertEqual(
            timezone.datetime.fromisoformat(after["deadline"]) - timezone.datetime.fromisoformat(before["deadline"]),
            timedelta(minutes=10),
        )
        with self.at(self.in_window(7)):
            self.sit("submit/", {})
        refused = self.staff(self.teacher, f"tests/{self.test_id}/students/{self.ada()}/extra-time/", {"minutes": 5, "reason": "More"})
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(self.events(kind="extra_time"), ["extra_time"])

    def test_extra_time_given_before_they_start_reaches_their_attempt(self):
        self.staff(self.admin, f"tests/{self.test_id}/students/{self.ada()}/extra-time/", {"minutes": 15, "reason": "Arrives late"})
        when = self.in_window()
        body = self.started(when=when)
        self.assertEqual(body["deadline"], (when + timedelta(minutes=self.duration + 15)).isoformat())

    def test_a_retake_by_the_teacher_or_an_exam_officer_only_after_the_attempt_closes(self):
        self.started()
        early = self.staff(self.teacher, f"tests/{self.test_id}/students/{self.ada()}/retake/", {"reason": "Ill"})
        self.assertEqual(early.status_code, 422, "still sitting")
        with self.at(self.in_window(7)):
            self.sit("submit/", {})
        for who in (self.admin, self.vp, self.tayo, self.bursar):
            with self.subTest(who=who.user.username):
                response = self.staff(who, f"tests/{self.test_id}/students/{self.ada()}/retake/", {"reason": "Ill"})
                self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.staff(self.teacher, f"tests/{self.test_id}/students/{self.ada()}/retake/", {"reason": ""}).status_code, 422)
        granted = self.staff(self.officer, f"tests/{self.test_id}/students/{self.ada()}/retake/", {"reason": "Was ill"})
        self.assertEqual(granted.status_code, 200, granted.content)
        again = self.started(when=self.in_window(9))
        self.assertEqual(again["attempt"]["number"], 2)
        self.assertFalse(again["resumed"])
        with connected_to(self.stmarys):
            self.assertEqual(RetakeGrant.objects.get().role, "exam officer")
            seeds = set(Attempt.objects.values_list("seed", flat=True))
        self.assertEqual(len(seeds), 2)

    def test_the_code_and_the_sitting_by_its_teachers_the_principal_and_the_administrator(self):
        for who in (self.teacher, self.head, self.admin):
            with self.subTest(who=who.user.username):
                response = self.staff(who, f"tests/{self.test_id}/code/")
                self.assertEqual(response.status_code, 200, response.content)
                code = response.json()["code"]
                self.assertRegex(code, r"^[A-Z]{6}$")
                self.assertEqual(self.open_by_hand(who).status_code, 200)
        # The exam officer gives time and retakes, and nothing else (docs/cbt.md).
        for who in (self.officer, self.tayo, self.vp, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertIn(self.staff(who, f"tests/{self.test_id}/code/").status_code, (403, 404))
                self.assertIn(self.open_by_hand(who).status_code, (403, 404))
        with connected_to(self.stmarys):
            changes = list(TestCodeChange.objects.order_by("id").values_list("kind", "role"))
            digest = Test.objects.get(pk=self.test_id).code_digest
        self.assertEqual(changes, [("set", "principal"), ("changed", "teacher"), ("changed", "principal"), ("changed", "administrator")])
        self.assertNotIn(code, digest)
        # The code is shown once: the log after does not carry it.
        self.assertIsNone(self.get(self.head, f"tests/{self.test_id}/sitting/").json()["code"])
        with self.at(self.in_window()):
            self.assertEqual(self.door(code=CODE).status_code, 404, "the old code stopped")
            self.assertEqual(self.door(code=code).status_code, 200)

    def test_a_student_already_sitting_is_not_signed_out_by_a_new_code(self):
        self.started()
        self.staff(self.head, f"tests/{self.test_id}/code/")
        with self.at(self.in_window(6)):
            self.assertEqual(self.sit("sync/", {}).status_code, 200)

    def test_closing_keeps_an_attempt_in_progress_unless_it_says_to_end_them(self):
        self.started()
        self.staff(self.head, f"tests/{self.test_id}/classes/{self.jss1a_id}/close/", {"reason": "Bell"})
        with self.at(self.in_window(6)):
            self.assertFalse(self.sit("sync/", {}).json()["closed"])
        self.staff(self.head, f"tests/{self.test_id}/classes/{self.jss1a_id}/close/", {"reason": "Bell", "end_attempts": True})
        with self.at(self.in_window(7)):
            self.assertTrue(self.sit("sync/", {}).json()["closed"])
        with connected_to(self.stmarys):
            self.assertEqual(Attempt.objects.get().ended_by, "teacher")
            self.assertEqual(AttemptEvent.objects.filter(kind="teacher_submit").count(), 1)


class TheSittingLogTests(SittingSetUp):
    def test_the_administrator_reads_it_and_it_carries_no_answer(self):
        body = self.started()
        item = body["paper"]["items"][0]
        self.answer(1, item["id"], item["options"][0]["index"])
        with self.at(self.in_window(7)):
            self.sit("sync/", {"events": [{"seq": 1, "kind": "left_page", "at": self.in_window(7).isoformat(), "seconds": 9}]})
        response = self.get(self.admin, f"tests/{self.test_id}/sitting/")
        self.assertEqual(response.status_code, 200, response.content)
        log = response.json()
        ada = next(r for r in log["rows"] if r["name"] == "Ada Obi")
        self.assertEqual((ada["state"], ada["computers"], ada["left_page"], ada["answers_received"]), ("Sitting", 1, 1, 1))
        self.assertEqual({r["state"] for r in log["rows"] if r["name"] != "Ada Obi"}, {"Not started"})
        text = response.content.decode()
        with connected_to(self.stmarys):
            for i in TestItem.objects.all():
                self.assertNotIn(i.stem, text)
                for option in i.options:
                    self.assertNotIn(f'"{option}"', text)
        self.assertNotIn('"chosen"', text)
        self.assertNotIn(f'"item": {item["id"]}', text)
        self.assertIsNone(KEYS.search(text))

    def test_who_reads_it(self):
        for who in (self.teacher, self.head, self.vp, self.admin):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.get(who, f"tests/{self.test_id}/sitting/").status_code, 200)
        for who in (self.tayo, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertIn(self.get(who, f"tests/{self.test_id}/sitting/").status_code, (403, 404))


class TheCookieOpensOneAttemptAtOneSchoolTests(SittingSetUp):
    def test_the_cookie_is_refused_at_the_other_school_and_on_every_staff_route(self):
        self.started()
        with self.at(self.in_window(6)):
            other = self.sit("sync/", {}, host=THEIR_HOST)
            attempt = self.sit("attempt/", method="get", host=THEIR_HOST)
        self.assertEqual((other.status_code, attempt.status_code), (401, 401))
        # The sit cookie is not an account session: a staff route sees nobody.
        for path in ("tests/", f"tests/{self.test_id}/", f"tests/{self.test_id}/sitting/", "slips/"):
            with self.subTest(path=path):
                response = self.device.get(f"{STAFF}{path}", HTTP_HOST=HOST)
                connection.set_schema_to_public()
                self.assertEqual(response.status_code, 401)

    def test_a_sitting_log_at_one_school_never_names_the_others(self):
        self.started()
        response = self.get(self.their_head, f"tests/{self.test_id}/sitting/", host=THEIR_HOST)
        self.assertEqual(response.status_code, 404)


class WhatTheDatabaseRefusesTests(SittingSetUp):
    def test_every_answer_and_the_log_are_kept(self):
        body = self.started()
        self.answer(1, body["paper"]["items"][0]["id"], 1)
        with connected_to(self.stmarys):
            for model, name in (
                (AnswerEvent, "cbt_answerevent is append-only"),
                (AttemptEvent, "cbt_attemptevent is append-only"),
            ):
                with self.subTest(model=model.__name__):
                    with self.assertRefusedBy(name), transaction.atomic():
                        model.objects.all().delete()
                    with self.assertRefusedBy(name), transaction.atomic():
                        model.objects.update(at=timezone.now()) if model is AttemptEvent else model.objects.update(chosen=0)

    def test_an_attempt_is_closed_once_and_never_rewritten(self):
        self.started()
        with connected_to(self.stmarys):
            with self.assertRefusedBy("an_attempt_is_closed_once"), transaction.atomic():
                Attempt.objects.update(base_deadline=F_later())
            Attempt.objects.update(submitted_at=timezone.now(), ended_by="student")
            with self.assertRefusedBy("an_attempt_is_closed_once"), transaction.atomic():
                Attempt.objects.update(ended_by="clock")
            with self.assertRefusedBy("an_attempt_is_closed_once"), transaction.atomic():
                # Past Django's own PROTECT, to the database's rule.
                Attempt.objects.all()._raw_delete(Attempt.objects.db)

    def test_a_session_is_ended_once(self):
        self.started()
        with connected_to(self.stmarys):
            AttemptSession.objects.update(ended_at=timezone.now(), ended_by="submit")
            with self.assertRefusedBy("a_session_is_ended_once"), transaction.atomic():
                AttemptSession.objects.update(ended_by="replaced")


def F_later():
    from django.db.models import F

    return F("base_deadline") + timedelta(hours=1)
