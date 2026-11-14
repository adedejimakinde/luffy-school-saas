"""Audit F-07, F-08 and F-09 (`docs/audit/2026-11-security-and-correctness.md`).

Two schools on their own hosts, as in `test_sitting`: their first class, term, test,
item and student share ids, and their first students share the admission number SM/001.
Each claim has a control in the audit file's Status lines (broken, seen red, restored).

- **F-07, the server's deadline.** After the deadline an answer counts only if it comes
  in that computer's first contact since the deadline, by the server's own record of the
  computer's contacts, and by `deadline + late_window`; the device's clock can never make
  a late answer count. Refused answers are kept and logged with their reason.
- **F-08, a practice test.** Every test whose scores can go to CA or be released asks for
  the exam PIN; a test without it is never released, its scores never reach a student's
  or a parent's page, and the scores door always asks for the PIN.
- **F-09, wrong tries wait on the device and the address.** A classmate typing someone
  else's number makes their own computer wait; the student signs in from theirs. A
  correct sign-in resets nothing. The address still brakes guessing from many devices.
"""

from datetime import timedelta

from django.db import connection
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import SignInAttempts
from cbt import sitting, sittings
from cbt.models import AnswerEvent, Attempt, AttemptEvent, ReleasedTestScore, Test, TestItem, TestRelease
from cbt.release import NOT_RELEASED, PRACTICE_NOT_RELEASED
from cbt.sit_views import DEVICE_COOKIE
from cbt.sitting import NOT_OPENED, WAIT
from cbt.tests import test_marking, test_sitting
from results.tests.fixtures import HOST, THEIR_HOST
from schools.tests.tenants import connected_to

PRACTICE_CODE = "PRAKTZ"


def iso(value):
    return timezone.datetime.fromisoformat(value)


# -- F-07 ------------------------------------------------------------------------------


class TheServersRecordDecidesTests(test_sitting.SittingSetUp):
    """The test gives 30 minutes and the default late window of 2."""

    def heartbeat(self, when, device=None, host=HOST):
        with self.at(when):
            response = self.sit("sync/", {}, device=device, host=host)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def refusals(self, **filters):
        with connected_to(self.stmarys):
            return list(AnswerEvent.objects.filter(accepted=False, **filters).order_by("id").values_list("refusal", flat=True))

    def test_a_computer_offline_through_the_deadline_delivers_what_it_held_in_its_first_contact(self):
        body = self.started()
        deadline = iso(body["deadline"])
        first, second, third = [i["id"] for i in body["paper"]["items"][:3]]
        self.answer(1, first, 1, when=self.in_window(6))
        # Off the network from minute 6. Back 90 seconds after the deadline, inside the window.
        back = self.sit_batch(
            [(2, second, 2, deadline - timedelta(minutes=3)), (3, third, 0, deadline - timedelta(seconds=10))],
            when=deadline + timedelta(seconds=90),
        )
        self.assertEqual(back["refused"], [])
        self.assertEqual(self.counted(), {first: 1, second: 2, third: 0})

    def test_a_computer_heard_after_the_deadline_cannot_send_more_whatever_its_clock_says(self):
        """The audit's reproduction: the seat was online at the deadline, and later claims
        an answer was chosen a second before it. Refused, kept and logged."""
        body = self.started()
        deadline = iso(body["deadline"])
        first, second = [i["id"] for i in body["paper"]["items"][:2]]
        self.answer(1, first, 1, when=deadline - timedelta(seconds=20))
        self.heartbeat(deadline + timedelta(seconds=10))
        late = self.answer(2, second, 3, chosen_at=deadline - timedelta(seconds=1), when=deadline + timedelta(seconds=30))
        self.assertEqual(late.json()["refused"], [{"seq": 2, "why": "after_time"}])
        self.assertEqual(self.counted(), {first: 1})
        self.assertEqual(self.refusals(), ["after_time"])
        with connected_to(self.stmarys):
            logged = AttemptEvent.objects.get(kind="late_refused")
        self.assertEqual((logged.detail["count"], logged.detail["why"]), (1, {"after_time": 1}))
        self.assertEqual(iso(logged.detail["last_contact"]), deadline + timedelta(seconds=10))
        # A resend of the refused answer is the same row, and is not logged twice.
        self.answer(2, second, 3, chosen_at=deadline - timedelta(seconds=1), when=deadline + timedelta(seconds=40))
        self.assertEqual(self.events(kind="late_refused"), ["late_refused"])

    def test_an_answer_chosen_in_the_last_second_still_goes_with_the_submit(self):
        """A heartbeat crossing the deadline does not cost the answer chosen while it was in
        flight: `TIE_SECONDS` of slack."""
        body = self.started()
        deadline = iso(body["deadline"])
        item = body["paper"]["items"][0]["id"]
        self.heartbeat(deadline + timedelta(seconds=1))
        with self.at(deadline + timedelta(seconds=3)):
            done = self.sit("submit/", {"answers": [
                {"seq": 1, "item": item, "chosen": 2, "chosen_at": (deadline - timedelta(milliseconds=500)).isoformat()}
            ], "by_clock": True})
        self.assertEqual(done.json()["refused"], [])
        self.assertEqual(self.counted(), {item: 2})

    def test_nothing_counts_after_the_late_window_even_on_a_first_contact(self):
        body = self.started()
        deadline = iso(body["deadline"])
        item = body["paper"]["items"][0]["id"]
        late = self.answer(1, item, 1, chosen_at=deadline - timedelta(minutes=1), when=deadline + timedelta(minutes=2, seconds=1))
        self.assertEqual(late.json()["refused"], [{"seq": 1, "why": "after_submit"}])
        self.assertEqual(self.counted(), {})

    def test_the_device_saying_it_was_late_is_believed(self):
        body = self.started()
        deadline = iso(body["deadline"])
        item = body["paper"]["items"][0]["id"]
        said = self.answer(1, item, 1, chosen_at=deadline + timedelta(seconds=20), when=deadline + timedelta(seconds=30))
        self.assertEqual(said.json()["refused"], [{"seq": 1, "why": "after_time"}])

    def test_two_computers_each_judged_by_its_own_contacts(self):
        """Seat 4 holds answers offline; the student moves to seat 9, which is online after
        the deadline. Seat 4's first contact delivers what it held; seat 9, already heard
        from after time ran out, cannot add more, and nor can seat 4 a second time."""
        seat4, seat9 = Client(), Client()
        body = self.started(device=seat4, seat="Seat 4")
        deadline = iso(body["deadline"])
        a, b, c, d = [i["id"] for i in body["paper"]["items"][:4]]
        self.answer(1, a, 1, device=seat4, when=self.in_window(6))
        self.started(device=seat9, when=self.in_window(9), seat="Seat 9")
        self.answer(1, b, 1, device=seat9, when=self.in_window(10))
        self.heartbeat(deadline + timedelta(seconds=20), device=seat9)
        nine_late = self.answer(2, c, 3, chosen_at=deadline - timedelta(seconds=5), device=seat9, when=deadline + timedelta(seconds=40))
        four_back = self.answer(2, d, 2, chosen_at=self.in_window(8), device=seat4, when=deadline + timedelta(seconds=60))
        four_again = self.answer(3, c, 0, chosen_at=self.in_window(8), device=seat4, when=deadline + timedelta(seconds=70))
        self.assertEqual(nine_late.json()["refused"], [{"seq": 2, "why": "after_time"}])
        self.assertTrue(four_back.json()["replaced"])
        self.assertEqual(four_back.json()["refused"], [])
        self.assertEqual(four_again.json()["refused"], [{"seq": 3, "why": "after_time"}])
        self.assertEqual(self.counted(), {a: 1, b: 1, d: 2})

    def test_two_classmates_each_judged_by_their_own_deadline_and_contacts(self):
        ada = Client()
        emeka = Client()
        ada_body = self.started("SM/001", device=ada)
        emeka_body = self.started("SM/002", device=emeka, when=self.in_window(8))
        ada_deadline, emeka_deadline = iso(ada_body["deadline"]), iso(emeka_body["deadline"])
        self.assertEqual(emeka_deadline - ada_deadline, timedelta(minutes=3))
        item = ada_body["paper"]["items"][0]["id"]
        # Ada's computer is heard after her deadline; Emeka is still inside his time.
        self.heartbeat(ada_deadline + timedelta(seconds=10), device=ada)
        ada_late = self.answer(1, item, 1, chosen_at=ada_deadline - timedelta(seconds=2), device=ada, when=ada_deadline + timedelta(seconds=30))
        emeka_in_time = self.answer(1, item, 2, device=emeka, when=ada_deadline + timedelta(seconds=40))
        self.assertEqual(ada_late.json()["refused"], [{"seq": 1, "why": "after_time"}])
        self.assertEqual(emeka_in_time.json()["refused"], [])
        with connected_to(self.stmarys):
            counted = {
                a.admission_number: sitting.counted_answers(a) for a in Attempt.objects.filter(test_id=self.test_id)
            }
        self.assertEqual(counted, {"SM/001": {}, "SM/002": {item: 2}})

    def test_extra_time_moves_the_line_the_server_judges_by(self):
        body = self.started()
        deadline = iso(body["deadline"])
        item = body["paper"]["items"][0]["id"]
        self.heartbeat(deadline + timedelta(seconds=30))
        with self.at(deadline + timedelta(seconds=45)):
            given = self.staff(
                self.head, f"tests/{self.test_id}/students/{self.children['ada'].pk}/extra-time/",
                {"minutes": 5, "reason": "The power went in the lab"},
            )
        self.assertEqual(given.status_code, 200, given.content)
        inside = self.answer(1, item, 3, when=deadline + timedelta(minutes=1))
        self.assertEqual(inside.json()["refused"], [])
        self.assertEqual(self.counted(), {item: 3})

    def test_one_schools_contacts_never_decide_the_others(self):
        """Grace's first attempt and session share St Mary's ids. A Grace computer heard
        after the deadline does not make a St Mary's computer's first contact a second."""
        test_sitting.TheDoorTests.grace_published(self)
        grace = Client()
        with self.at(self.in_window()):
            door = self.sit("door/", {"code": test_sitting.GRACE_CODE, "admission_number": "SM/001", "pin": self.grace_pins["SM/001"]},
                            device=grace, host=THEIR_HOST)
            self.assertEqual(door.status_code, 200, door.content)
            theirs = self.sit("start/", {"ticket": door.json()["ticket"]}, device=grace, host=THEIR_HOST).json()
        ours = self.started()
        self.assertEqual((theirs["attempt"]["id"], theirs["attempt"]["session"]), (ours["attempt"]["id"], ours["attempt"]["session"]))
        deadline = iso(ours["deadline"])
        self.heartbeat(deadline + timedelta(seconds=10), device=grace, host=THEIR_HOST)
        item = ours["paper"]["items"][0]["id"]
        here = self.answer(1, item, 1, chosen_at=deadline - timedelta(seconds=30), when=deadline + timedelta(seconds=60))
        self.assertEqual(here.json()["refused"], [])
        with connected_to(self.grace):
            grace_item = TestItem.objects.filter(test_id=self.test_id).order_by("position").first().pk
        with self.at(deadline + timedelta(seconds=70)):
            there = self.sit("sync/", {"answers": [{"seq": 1, "item": grace_item, "chosen": 1,
                                                    "chosen_at": (deadline - timedelta(seconds=30)).isoformat()}]},
                             device=grace, host=THEIR_HOST)
        self.assertEqual(there.json()["refused"], [{"seq": 1, "why": "after_time"}])

    def sit_batch(self, answers, when, device=None):
        body = {"answers": [{"seq": s, "item": i, "chosen": c, "chosen_at": at.isoformat()} for s, i, c, at in answers]}
        with self.at(when):
            response = self.sit("sync/", body, device=device)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


# -- F-09 ------------------------------------------------------------------------------


@override_settings(SIT_MAX_FAILURES_PER_ADMISSION_NUMBER=3)
class TheDoorWaitsOnTheDeviceTests(test_sitting.SittingSetUp):
    def test_a_classmate_guessing_a_number_never_locks_its_student_out(self):
        classmate, ada = Client(), Client()
        with self.at(self.in_window()):
            for _ in range(5):
                self.door("SM/001", pin="11111111", device=classmate)
            # The classmate's own computer waits, for any number, the right PIN included.
            theirs = self.door("SM/001", device=classmate)
            own = self.door("SM/002", device=classmate)
            # Ada, at her own computer, is not made to wait.
            mine = self.door("SM/001", device=ada)
        self.assertEqual((theirs.status_code, theirs.json()["detail"]), (429, WAIT))
        self.assertEqual(own.status_code, 429)
        self.assertEqual(mine.status_code, 200, mine.content)
        self.assertEqual(mine.json()["student"]["name"], "Ada Obi")
        with self.at(self.in_window()):
            started = self.sit("start/", {"ticket": mine.json()["ticket"]}, device=ada)
        self.assertEqual(started.status_code, 200, started.content)

    def test_nothing_is_counted_against_the_number_typed(self):
        with self.at(self.in_window()):
            for _ in range(3):
                self.door("SM/001", pin="11111111", device=Client())
            self.assertEqual(self.door("SM/001", device=Client()).status_code, 200)
        keys = set(SignInAttempts.objects.filter(scope__in=[sitting.DEVICE_SCOPE, sitting.ADDRESS_SCOPE]).values_list("key", flat=True))
        from accounts.throttling import key_for

        self.assertNotIn(key_for(sitting.DEVICE_SCOPE, f"{self.stmarys.pk}:sm/001"), keys)
        self.assertNotIn(key_for(sitting.DEVICE_SCOPE, f"{self.stmarys.pk}:SM/001"), keys)

    def test_a_right_sign_in_resets_nothing(self):
        classmate = Client()
        with self.at(self.in_window()):
            for _ in range(2):
                self.assertEqual(self.door("SM/001", pin="11111111", device=classmate).status_code, 404)
            self.assertEqual(self.door("SM/002", device=classmate).status_code, 200, "their own slip opens")
            self.assertEqual(self.door("SM/001", pin="22222222", device=classmate).status_code, 404)
            self.assertEqual(self.door("SM/002", device=classmate).status_code, 429)

    @override_settings(SIT_MAX_FAILURES_PER_ADDRESS=4)
    def test_the_address_still_brakes_guessing_from_fresh_devices(self):
        with self.at(self.in_window()):
            for _ in range(4):
                self.assertEqual(self.door("SM/001", pin="11111111", device=Client()).status_code, 404)
            here = self.door("SM/001", device=Client())
            elsewhere = Client(REMOTE_ADDR="10.20.30.40")
            there = self.door("SM/001", device=elsewhere)
        self.assertEqual(here.status_code, 429)
        self.assertEqual(there.status_code, 200, there.content)

    def test_the_page_and_the_door_give_the_browser_a_device_id_that_names_nobody(self):
        browser = Client()
        page = browser.get("/sit/", HTTP_HOST=HOST)
        connection.set_schema_to_public()
        cookie = page.cookies[DEVICE_COOKIE]
        self.assertRegex(cookie.value, r"^[0-9a-f]{32}$")
        self.assertEqual((cookie["path"], cookie["samesite"]), ("/sit/", "Strict"))
        self.assertTrue(cookie["httponly"])
        with self.at(self.in_window()):
            again = self.door("SM/001", pin="11111111", device=browser)
            fresh = self.door("SM/001", pin="11111111", device=Client())
        self.assertNotIn(DEVICE_COOKIE, again.cookies, "a browser keeps the id it has")
        self.assertRegex(fresh.cookies[DEVICE_COOKIE].value, r"^[0-9a-f]{32}$")
        self.assertNotIn("SM/001", fresh.cookies[DEVICE_COOKIE].value)

    def test_a_device_waiting_at_one_school_is_not_waiting_at_the_other(self):
        test_sitting.TheDoorTests.grace_published(self)
        device = Client()
        with self.at(self.in_window()):
            for _ in range(3):
                self.door("SM/001", pin="11111111", device=device)
            here = self.door("SM/001", device=device)
            there = self.door("SM/001", pin=self.grace_pins["SM/001"], code=test_sitting.GRACE_CODE, device=device, host=THEIR_HOST)
        self.assertEqual(here.status_code, 429)
        self.assertEqual(there.status_code, 200, there.content)
        self.assertEqual(there.json()["student"]["name"], "Chidi Eze")


# -- F-08 and the scores door -------------------------------------------------------------


class PracticeTestsTests(test_marking.MarkingSetUp):
    def setUp(self):
        super().setUp()
        self.practice_id = self.set_test(title="Practice, no PIN", require_pin=False)
        self.assertEqual(self.post(self.teacher, f"tests/{self.practice_id}/submit/").status_code, 200)
        self.assertEqual(self.post(self.head, f"tests/{self.practice_id}/approve/").status_code, 200)
        with connected_to(self.stmarys):
            sittings.set_code_as(self.head.user, self.stmarys, self.practice_id, code=PRACTICE_CODE)
            self.practice_items = list(
                TestItem.objects.filter(test_id=self.practice_id).order_by("position").values_list("pk", flat=True)
            )

    def sit_practice(self, number="SM/001"):
        device = Client()
        with self.at(self.in_window()):
            door = self.door(number, pin="", code=PRACTICE_CODE, device=device)
            self.assertEqual(door.status_code, 200, door.content)
            self.sit("start/", {"ticket": door.json()["ticket"]}, device=device)
        with self.at(self.in_window(3)):
            answers = [{"seq": n + 1, "item": i, "chosen": 0, "chosen_at": self.in_window(2).isoformat()}
                       for n, i in enumerate(self.practice_items)]
            done = self.sit("submit/", {"answers": answers}, device=device)
        self.assertEqual(done.status_code, 200, done.content)

    def test_every_test_that_can_send_or_release_asks_for_the_pin(self):
        with connected_to(self.stmarys):
            marked = Test.objects.get(pk=self.test_id)
            practice = Test.objects.get(pk=self.practice_id)
        self.assertTrue(sitting.needs_pin(marked))
        self.assertFalse(sitting.needs_pin(practice))
        # Even a row the database would refuse: sending to CA means the PIN is asked.
        self.assertTrue(sitting.needs_pin(Test(require_pin=False, may_send_to_ca=True)))
        with self.at(self.in_window()):
            no_pin = self.door("SM/001", pin="")
            on_a_number = self.door("SM/001", pin="", code=PRACTICE_CODE)
        self.assertEqual((no_pin.status_code, no_pin.json()["detail"]), (404, NOT_OPENED))
        self.assertEqual(on_a_number.status_code, 200, "a practice test opens on a number")

    def test_a_practice_test_is_never_released(self):
        self.sit_practice()
        with self.after():
            refused = self.post(self.teacher, f"tests/{self.practice_id}/classes/{self.jss1a_id}/release/")
            by_head = self.post(self.head, f"tests/{self.practice_id}/classes/{self.jss1a_id}/release/")
            results = self.get(self.teacher, f"tests/{self.practice_id}/results/").json()
        self.assertEqual((refused.status_code, refused.json()["detail"]), (422, PRACTICE_NOT_RELEASED))
        self.assertEqual(by_head.status_code, 422)
        jss1a = next(c for c in results["classes"] if c["id"] == self.jss1a_id)
        self.assertEqual((jss1a["may_release"], jss1a["why_not"]), (False, PRACTICE_NOT_RELEASED))
        # The teacher still reads the practice scores.
        self.assertEqual({r["name"] for r in results["rows"] if r.get("score") is not None}, {"Ada Obi"})
        with connected_to(self.stmarys):
            self.assertFalse(TestRelease.objects.filter(test_id=self.practice_id).exists())

    def test_a_practice_score_never_reaches_a_student_or_a_parent_page(self):
        """Even a released row written for one (as before this fix) is never shown."""
        self.sit_practice()
        with connected_to(self.stmarys):
            practice = Test.objects.get(pk=self.practice_id)
            attempt = Attempt.objects.get(test=practice)
            release = TestRelease.objects.create(
                test=practice, class_group_id=self.jss1a_id, class_group_name="JSS 1A", count=1,
                by_id=self.teacher.user.pk, by_name="Kemi", role="teacher",
            )
            ReleasedTestScore.objects.create(
                release=release, test=practice, student_membership_id=attempt.student_membership_id,
                student_name=attempt.student_name, admission_number=attempt.admission_number,
                class_group_name="JSS 1A", test_title=practice.title, subject_name="Mathematics", attempt_number=1,
                score=4, out_of=4, right=4, questions=4, corrections=[], released_by_name="Kemi",
                released_at=timezone.now(),
            )
        with self.after():
            on_a_number = self.student_door(pin="", code=PRACTICE_CODE)
            with_the_pin = self.student_door(code=PRACTICE_CODE)
            family = self.get(self.parent_user, "scores/").json()["children"]
        self.assertEqual((on_a_number.status_code, on_a_number.json()["detail"]), (404, NOT_OPENED))
        self.assertEqual((with_the_pin.status_code, with_the_pin.json()["detail"]), (409, NOT_RELEASED))
        ada = next(c for c in family if c["name"] == "Ada Obi")
        self.assertEqual((ada["scores"], ada["waiting"]), ([], 0), "nothing shown, and nothing waiting")

    def test_a_practice_code_at_one_school_opens_nothing_at_the_other(self):
        test_sitting.TheDoorTests.grace_published(self)
        with self.at(self.in_window()):
            there = self.door("SM/001", pin="", code=PRACTICE_CODE, host=THEIR_HOST)
        self.assertEqual((there.status_code, there.json()["detail"]), (404, NOT_OPENED))


@override_settings(SIT_MAX_FAILURES_PER_ADMISSION_NUMBER=3)
class TheScoresDoorWaitsOnTheDeviceTests(test_marking.MarkingSetUp):
    def test_a_classmate_guessing_never_keeps_a_student_from_their_scores(self):
        self.sat()
        classmate, ada = Client(), Client()
        with self.after():
            self.assertEqual(self.release().status_code, 200)
            for _ in range(4):
                self.student_door("SM/001", pin="11111111", device=classmate)
            theirs = self.student_door("SM/001", device=classmate)
            mine = self.student_door("SM/001", device=ada)
        self.assertEqual(theirs.status_code, 429)
        self.assertEqual(mine.status_code, 200, mine.content)
        self.assertEqual(mine.json()["this"]["score"], 4)
        self.assertEqual(ada.cookies[DEVICE_COOKIE]["path"], "/test-scores/")

