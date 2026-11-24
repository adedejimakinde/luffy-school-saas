"""The exam door for a class opened by hand, and the staff attempt log of what it refused.

`docs/cbt.md`, "The staff attempt log". Two schools on their own hosts, as in
`test_sitting`; their first students share the admission number SM/001.

**The bug report this answers.** A test approved for 24 Nov 08:00 and opened by hand for
one class on 23 Nov at 18:14; a student of that class, with the code, the admission number
and the PIN from their latest slip, was told "That test code, admission number and PIN do
not open a test here." The first class (`HandOpenedBeforeItsPlannedStartTests`) holds
what the door does with exactly that: the window is **not** one of the checks behind that
sentence, so a class opened by hand signs in, starts, answers and submits before the plan.
The sentence is the door's one refusal for the code, the number and the PIN
(`cbt.sitting`, "The door"), and the other classes hold what each of those refusals is,
now written down where staff, and only staff, read it.

Each claim has a control in the PR's description (broken, seen red, restored).

- **Every reason is written**: wrong code, wrong PIN, a PIN from another term's slip, not
  in a class sitting this test, test not open, already sat, locked until HH:MM.
- **The student is told what they were told before**: the same bytes for each of the
  three, the same sentence for the rest, no reason in any `/sit/` answer.
- **Nothing typed is kept**: not the PIN, not the code, not an address; and a number
  nobody here has writes nothing.
- **A lockout is one line, not a flood**, and a proved door pressed again and again before
  the test opens is one line in two minutes.
- **One school's log is its own**; the table is append-only.
"""

import json
from datetime import timedelta

from django.db import transaction
from django.test import Client, override_settings
from django.utils import timezone

from academics import services as academics
from academics.models import ClassGroup, Term
from cbt import pins, sittings
from cbt.models import Attempt, ExamPin, SignInRefusal, Test
from cbt.sitting import ALREADY_SAT, NOT_OPEN_NOW, NOT_OPENED, WAIT
from cbt.tests import test_sitting
from results.tests.fixtures import HOST, THEIR_HOST
from schools.tests.tenants import connected_to

REASONS = {label: value for value, label in SignInRefusal.Reason.choices}


class LogSetUp(test_sitting.SittingSetUp):
    def log(self, who=None, host=HOST):
        response = self.get(who or self.head, f"tests/{self.test_id}/sitting/", host=host)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def sign_ins(self, name, who=None):
        """`[reason, ...]` the log gives for one student, oldest first."""
        row = next((r for r in self.log(who)["rows"] if r["name"] == name), None)
        return [] if row is None else [s["reason"] for s in row["sign_ins"]]

    def row(self, name):
        return next(r for r in self.log()["rows"] if r["name"] == name)

    def rows_kept(self, school=None):
        with connected_to(school or self.stmarys):
            return list(SignInRefusal.objects.order_by("id").values())

    def add_class_1b(self):
        """JSS 1B sits the test as well, after it was approved, and gets its own latest slip
        (the report's JSS 2B). Bimpe is its one student."""
        response = self.post(self.head, f"tests/{self.test_id}/classes/", {"class_group_ids": [self.jss1a_id, self.jss1b_id]})
        self.assertEqual(response.status_code, 200, response.content)
        with connected_to(self.stmarys):
            pins.print_class_as(self.head.user, self.stmarys, self.jss1b_id)  # a first slip, since lost
            return pins.print_student_as(self.head.user, self.stmarys, self.jss1b_id, self.bimpe.pk).slips[0].pin

    def open_1b_by_hand(self):
        response = self.staff(
            self.head, f"tests/{self.test_id}/classes/{self.jss1b_id}/open/", {"reason": "Moved to period 2"}
        )
        self.assertEqual(response.status_code, 200, response.content)


# -- the report ----------------------------------------------------------------------------


class HandOpenedBeforeItsPlannedStartTests(LogSetUp):
    """The report, reproduced at the door, and every check it could have been."""

    def test_a_class_opened_by_hand_signs_in_and_sits_before_the_planned_start(self):
        pin = self.add_class_1b()
        self.open_1b_by_hand()
        night_before = self.opens - timedelta(hours=14)
        with self.at(night_before):
            door = self.door("SM/005", pin=pin)
        self.assertEqual(door.status_code, 200, door.content)
        self.assertEqual(door.json()["student"]["class_name"], "JSS 1B")
        with self.at(night_before):
            started = self.sit("start/", {"ticket": door.json()["ticket"], "seat": "Seat 7"})
        self.assertEqual(started.status_code, 200, started.content)
        item = started.json()["paper"]["items"][0]["id"]
        answered = self.answer(1, item, 1, when=night_before + timedelta(minutes=3))
        self.assertEqual((answered.status_code, answered.json()["refused"]), (200, []))
        with self.at(night_before + timedelta(minutes=5)):
            done = self.sit("submit/", {})
        self.assertEqual((done.status_code, done.json()["closed"], done.json()["received"]), (200, True, 1))
        self.assertEqual(self.sign_ins("Bimpe Ojo"), [], "nothing was refused on the way")

    def test_it_is_the_hand_control_that_opens_it_and_only_for_its_class(self):
        pin = self.add_class_1b()
        night_before = self.opens - timedelta(hours=14)
        with self.at(night_before):
            before = self.door("SM/005", pin=pin)
        self.assertEqual((before.status_code, before.json()["detail"]), (409, NOT_OPEN_NOW), "proved, and not yet open")
        self.open_1b_by_hand()
        with self.at(night_before):
            by_hand = self.door("SM/005", pin=pin)
            neighbour = self.door("SM/001")
        self.assertEqual(by_hand.status_code, 200, by_hand.content)
        self.assertEqual((neighbour.status_code, neighbour.json()["detail"]), (409, NOT_OPEN_NOW))

    def test_only_the_latest_slip_opens_it_and_the_window_is_not_what_refuses_the_old_one(self):
        pin = self.add_class_1b()
        with connected_to(self.stmarys):
            newer = pins.print_student_as(self.head.user, self.stmarys, self.jss1b_id, self.bimpe.pk).slips[0].pin
        self.open_1b_by_hand()
        night_before = self.opens - timedelta(hours=14)
        with self.at(night_before):
            old = self.door("SM/005", pin=pin)
            latest = self.door("SM/005", pin=newer)
        self.assertEqual((old.status_code, old.json()["detail"]), (404, NOT_OPENED))
        self.assertEqual(latest.status_code, 200, latest.content)
        # What refused the old slip is the PIN, and the log says so.
        self.assertEqual(self.sign_ins("Bimpe Ojo"), ["wrong_pin"])

    def test_the_refusal_in_the_report_is_the_three_never_the_window_or_the_wait(self):
        """Each of the door's other answers has its own sentence and its own status. The
        report's sentence (404) is only ever the code, the number or the PIN."""
        sentences = {NOT_OPENED: 404, NOT_OPEN_NOW: 409, ALREADY_SAT: 409, WAIT: 429}
        self.assertEqual(len(set(sentences)), 4)
        pin = self.add_class_1b()
        night_before = self.opens - timedelta(hours=14)
        with self.at(night_before):
            window = self.door("SM/005", pin=pin)
            wrong = self.door("SM/005", pin="00000000")
        self.assertEqual((window.status_code, window.json()["detail"]), (409, NOT_OPEN_NOW))
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (404, NOT_OPENED))


# -- each reason ------------------------------------------------------------------------------


class EveryRefusalIsWrittenForStaffTests(LogSetUp):
    def setUp(self):
        super().setUp()
        # Class 1A is open by hand for everything below, so an open sitting is waiting.
        self.assertEqual(self.open_by_hand().status_code, 200)
        self.now = self.in_window()

    def refused(self, name, **door):
        with self.at(self.now):
            response = self.door(**door)
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json()["detail"], NOT_OPENED)
        return self.sign_ins(name)

    def test_a_wrong_test_code(self):
        self.assertEqual(self.refused("Ada Obi", number="SM/001", code="ZZZZZZ"), ["wrong_code"])
        self.assertEqual(self.refused("Ada Obi", number="SM/001", code="KMT"), ["wrong_code", "wrong_code"])

    def test_a_wrong_pin_and_somebody_elses_and_a_cancelled_one(self):
        old = self.pins["SM/002"]
        with connected_to(self.stmarys):
            pins.print_student_as(self.head.user, self.stmarys, self.jss1a_id, self.children["emeka"].pk)
        self.assertEqual(self.refused("Ada Obi", number="SM/001", pin="12345678"), ["wrong_pin"])
        self.assertEqual(self.refused("Ada Obi", number="SM/001", pin=self.pins["SM/003"]), ["wrong_pin"] * 2)
        self.assertEqual(self.refused("Emeka Nwosu", number="SM/002", pin=old), ["wrong_pin"])
        self.assertEqual(self.refused("Ada Obi", number="SM/001", pin=""), ["wrong_pin"] * 3)

    def test_a_pin_from_another_terms_slip_is_told_from_a_wrong_one(self):
        """The slip was printed after the school moved to its next term: it is live and
        correct, for a term this test is not in."""
        with connected_to(self.stmarys):
            second = Term.objects.get(pk=self.second_term.pk)
            academics.set_current_term(second)
            academics.place_student(ClassGroup.objects.get(pk=self.jss1a_id), second, self.children["ada"])
            newer = {s.admission_number: s.pin for s in pins.print_class_as(self.head.user, self.stmarys, self.jss1a_id, replace=True).slips}
            self.assertEqual(ExamPin.objects.filter(student_membership_id=self.children["ada"].pk, cancelled_at__isnull=True).count(), 2)
        self.assertEqual(self.refused("Ada Obi", number="SM/001", pin=newer["SM/001"]), ["other_term_slip"])
        self.assertEqual(self.refused("Ada Obi", number="SM/001", pin="12345678"), ["other_term_slip", "wrong_pin"])

    def test_a_student_in_no_class_sitting_this_test(self):
        """Bimpe's PIN and the code are both right; JSS 1B does not sit this test. She has a
        line in the log, with her own class, and the state says why."""
        with connected_to(self.stmarys):
            bimpe = pins.print_student_as(self.head.user, self.stmarys, self.jss1b_id, self.bimpe.pk).slips[0].pin
        self.assertEqual(self.refused("Bimpe Ojo", number="SM/005", pin=bimpe), ["not_in_class"])
        row = self.row("Bimpe Ojo")
        self.assertEqual((row["state"], row["class_name"], row["failed_sign_ins"]), ("Not in this test's classes", "JSS 1B", 1))
        self.assertEqual(row["number"], 0)

    def test_the_test_not_open_to_their_class_is_written_once_a_press_and_twice_a_wait(self):
        """Proved, and the plan says not yet (the class was not opened by hand)."""
        pin = self.add_class_1b()
        early = self.opens - timedelta(hours=1)
        for minutes in (0, 0.5, 1):
            with self.at(early + timedelta(minutes=minutes)):
                response = self.door("SM/005", pin=pin)
            self.assertEqual((response.status_code, response.json()["detail"]), (409, NOT_OPEN_NOW))
        self.assertEqual(self.sign_ins("Bimpe Ojo"), ["not_open"], "three presses inside two minutes are one line")
        with self.at(early + timedelta(minutes=5)):
            self.door("SM/005", pin=pin)
        self.assertEqual(self.sign_ins("Bimpe Ojo"), ["not_open", "not_open"])

    def test_a_student_who_has_sat_it_already(self):
        self.started()
        with self.at(self.in_window(8)):
            self.sit("submit/", {})
        with self.at(self.in_window(10)):
            again = self.door()
        self.assertEqual((again.status_code, again.json()["detail"]), (409, ALREADY_SAT))
        self.assertEqual(self.sign_ins("Ada Obi"), ["already_sat"])

    @override_settings(SIT_MAX_FAILURES_PER_ADMISSION_NUMBER=3)
    def test_a_lockout_says_until_when_and_is_one_line_while_it_lasts(self):
        with self.at(self.now):
            for _ in range(3):
                self.assertEqual(self.door(pin="11111111").status_code, 404)
            locked = [self.door() for _ in range(4)]
        self.assertEqual({r.status_code for r in locked}, {429})
        self.assertEqual(locked[0].json()["detail"], WAIT)
        row = self.row("Ada Obi")
        self.assertEqual([s["reason"] for s in row["sign_ins"]], ["wrong_pin"] * 3 + ["locked"])
        until = timezone.datetime.fromisoformat(row["sign_ins"][-1]["until"])
        self.assertEqual(until, self.now + timedelta(seconds=locked[0].json()["retry_after"]))
        self.assertGreater(until, self.now)
        # Another computer is not locked, and its sign-in is no refusal.
        with self.at(self.now):
            self.assertEqual(self.door(device=Client()).status_code, 200)
        self.assertEqual(self.sign_ins("Ada Obi").count("locked"), 1)

    def test_every_reason_has_a_sentence_for_staff(self):
        self.assertEqual(
            set(REASONS), {
                "Wrong test code", "Wrong exam PIN", "PIN is from another term's slip", "Not in a class sitting this test",
                "Test not open to their class", "Has sat it already", "Locked out for too many wrong tries",
            },
        )


# -- who is never told, and what is never kept --------------------------------------------------


class TheStudentIsToldNothingMoreAndNothingTypedIsKeptTests(LogSetUp):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.open_by_hand().status_code, 200)
        self.now = self.in_window()

    def test_the_three_refusals_are_the_same_bytes_with_or_without_a_line_in_the_log(self):
        with connected_to(self.stmarys):
            bimpe = pins.print_student_as(self.head.user, self.stmarys, self.jss1b_id, self.bimpe.pk).slips[0].pin
        cases = {
            "a wrong code": dict(number="SM/001", code="ZZZZZZ"),
            "a wrong PIN": dict(number="SM/001", pin="12345678"),
            "not in a class": dict(number="SM/005", pin=bimpe),
            "an unknown number, which writes nothing": dict(number="SM/999", pin="12345678"),
        }
        bodies = set()
        with self.at(self.now):
            for why, case in cases.items():
                with self.subTest(why):
                    response = self.door(device=Client(), **case)
                    self.assertEqual(response.status_code, 404)
                    bodies.add(response.content)
        self.assertEqual(len(bodies), 1)
        self.assertEqual([r["reason"] for r in self.rows_kept()], ["wrong_code", "wrong_pin", "not_in_class"])

    def test_no_sit_answer_names_a_reason(self):
        with self.at(self.now):
            self.door(pin="11111111")
            self.door(code="ZZZZZZ")
        for response in self.responses:
            text = response.content.decode()
            for word in ("wrong_pin", "wrong_code", "not_in_class", "other_term_slip", "sign_ins", "device"):
                self.assertNotIn(word, text)

    def test_the_pin_and_the_code_typed_are_kept_nowhere(self):
        typed_pin, typed_code = "13572468", "QWRTYX"
        with self.at(self.now):
            self.door(pin=typed_pin)
            self.door(code=typed_code)
        text = json.dumps(self.rows_kept(), default=str) + json.dumps(self.log())
        self.assertEqual(self.sign_ins("Ada Obi"), ["wrong_pin", "wrong_code"])
        for secret in (typed_pin, "1357 2468", typed_code, "127.0.0.1", self.pins["SM/001"]):
            self.assertNotIn(secret, text)
        fields = {f.name for f in SignInRefusal._meta.get_fields()}
        self.assertEqual(fields, {
            "id", "test", "student_membership_id", "student_name", "admission_number", "reason", "until", "device_tag", "at",
        })

    def test_a_number_nobody_has_and_no_number_at_all_write_nothing(self):
        with self.at(self.now):
            self.door("SM/999", pin="12345678")
            self.door("", pin="12345678")
        self.assertEqual(self.rows_kept(), [])

    def test_the_device_is_a_tag_that_says_same_computer_and_nothing_more(self):
        one, two = Client(), Client()
        with self.at(self.now):
            self.door(pin="11111111", device=one)
            self.door(pin="11111111", device=one)
            self.door(pin="11111111", device=two)
        tags = [s["device"] for s in self.row("Ada Obi")["sign_ins"]]
        self.assertEqual((tags[0] == tags[1], tags[0] == tags[2]), (True, False))
        self.assertEqual({len(t) for t in tags}, {6})
        self.assertNotIn(one.cookies["sit_device"].value, tags)
        self.assertNotIn(one.cookies["sit_device"].value[:6], tags)


class OneSchoolsLogIsItsOwnTests(LogSetUp):
    def test_equal_ids_and_numbers_at_two_schools_never_meet(self):
        self.assertEqual(self.open_by_hand().status_code, 200)
        with self.at(self.in_window()):
            # Grace's student types St Mary's code and number at Grace's host: no test there has it.
            theirs = self.door("SM/001", pin="12345678", host=THEIR_HOST)
            mine = self.door(pin="12345678")
        self.assertEqual((theirs.status_code, mine.status_code), (404, 404))
        self.assertEqual([r["reason"] for r in self.rows_kept()], ["wrong_pin"])
        self.assertEqual(self.rows_kept(self.grace), [])

    def test_the_other_schools_staff_cannot_read_it(self):
        with self.at(self.in_window()):
            self.door(pin="12345678")
        self.assertEqual(self.get(self.their_head, f"tests/{self.test_id}/sitting/", host=THEIR_HOST).status_code, 404)


class WhoReadsItAndWhatTheDatabaseRefusesTests(LogSetUp):
    def test_the_log_is_read_by_exactly_who_reads_the_sitting_log(self):
        self.assertEqual(self.open_by_hand().status_code, 200)
        with self.at(self.in_window()):
            self.door(pin="12345678")
        for who in (self.teacher, self.head, self.vp, self.admin):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.sign_ins("Ada Obi", who), ["wrong_pin"])
        for who in (self.tayo, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertIn(self.get(who, f"tests/{self.test_id}/sitting/").status_code, (403, 404))

    def test_a_student_a_parent_and_a_guardian_session_never_reach_it(self):
        with self.at(self.in_window()):
            self.door(pin="12345678")
        for path in (f"tests/{self.test_id}/sitting/",):
            for who in (self.children["ada"], self.parent_user):
                with self.subTest(who=str(who)):
                    response = self.get(who, path)
                    self.assertIn(response.status_code, (401, 403, 404))
                    self.assertNotIn("wrong_pin", response.content.decode())

    def test_a_refused_sign_in_is_kept_for_good(self):
        with self.at(self.in_window()):
            self.door(pin="12345678")
        with connected_to(self.stmarys):
            with self.assertRefusedBy("cbt_signinrefusal is append-only"), transaction.atomic():
                SignInRefusal.objects.update(reason="wrong_code")
            with self.assertRefusedBy("cbt_signinrefusal is append-only"), transaction.atomic():
                SignInRefusal.objects.all()._raw_delete(SignInRefusal.objects.db)

    def test_a_lockout_has_an_end_and_nothing_else_does(self):
        self.open_by_hand()
        with self.at(self.in_window()):
            self.door(pin="12345678")
        with connected_to(self.stmarys):
            row = SignInRefusal.objects.get()
            with self.assertRefusedBy("only_a_lockout_has_an_end"), transaction.atomic():
                SignInRefusal.objects.create(
                    test_id=row.test_id, student_membership_id=row.student_membership_id, student_name="x",
                    admission_number="SM/001", reason="locked", at=timezone.now(),
                )
            with self.assertRefusedBy("only_a_lockout_has_an_end"), transaction.atomic():
                SignInRefusal.objects.create(
                    test_id=row.test_id, student_membership_id=row.student_membership_id, student_name="x",
                    admission_number="SM/001", reason="wrong_pin", until=timezone.now(), at=timezone.now(),
                )
            with self.assertRefusedBy("a_refused_sign_in_has_a_known_reason"), transaction.atomic():
                SignInRefusal.objects.create(
                    test_id=row.test_id, student_membership_id=row.student_membership_id, student_name="x",
                    admission_number="SM/001", reason="because", at=timezone.now(),
                )
