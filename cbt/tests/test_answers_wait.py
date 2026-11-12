"""Answers wait until every class has finished the paper: audit finding G-03.

One paper, two classes (JSS 1A and JSS 1B), scores released a class at a time. Releasing
JSS 1A shows JSS 1A its scores and no right answer while JSS 1B has still to sit; the
answers show once every class has finished or the window has closed
(`cbt.release.classes_still_to_finish()`), and are held again if a sitting is opened
again by hand.

Two schools on their own hosts, as in `test_marking`: Grace's test has the same id as
St Mary's, and neither school's classes hold or free the other's answers.

Each claim here was checked against the fix broken on purpose (the hold switched off in
`student_scores()`): every test that asserts a held answer goes red, and green again
with the fix restored.
"""

import json
from datetime import timedelta

from django.test import Client

from cbt import pins, release
from cbt.models import ReleasedTestScore, Test
from cbt.release import ANSWERS_HELD, NOT_RELEASED
from cbt.tests import test_marking, test_sitting
from results.tests.fixtures import THEIR_HOST
from schools.tests.tenants import connected_to

#: Words that are only ever in a correction: the right option and why.
ANSWER_WORDS = ("right_letter", "right_text", "explanation", "make 2")


class TwoClassesSetUp(test_marking.MarkingSetUp):
    """The First CA test, set for JSS 1A and JSS 1B. Bimpe (SM/005) is JSS 1B's sitter."""

    def setUp(self):
        super().setUp()
        both = self.post(
            self.head, f"tests/{self.test_id}/classes/", {"class_group_ids": [self.jss1a_id, self.jss1b_id]}
        )
        self.assertEqual(both.status_code, 200, both.content)
        with connected_to(self.stmarys):
            slip = pins.print_student_as(self.head.user, self.stmarys, self.jss1b_id, self.bimpe.pk)
            self.pins["SM/005"] = slip.slips[0].pin
        self.CHOICES = {**self.CHOICES, "SM/005": [0, 0, 1, 1]}

    def close_by_hand(self, class_id, when, end_attempts=False, host=None, who=None):
        with self.at(when):
            response = self.post(
                who or self.head, f"tests/{self.test_id}/classes/{class_id}/close/",
                {"reason": "The class has finished", "end_attempts": end_attempts},
                **({"host": host} if host else {}),
            )
        self.assertEqual(response.status_code, 200, response.content)

    def open_class_by_hand(self, class_id, when):
        with self.at(when):
            response = self.post(
                self.head, f"tests/{self.test_id}/classes/{class_id}/open/", {"reason": "Two were absent"}
            )
        self.assertEqual(response.status_code, 200, response.content)

    def jss1a_sits_and_is_released(self):
        """Ada and Emeka sit, JSS 1A's sitting is closed by hand and its scores released,
        all inside the window: JSS 1B has not sat."""
        self.finish("SM/001")
        self.finish("SM/002")
        self.close_by_hand(self.jss1a_id, self.in_window(10))
        with self.at(self.in_window(11)):
            released = self.release()
        self.assertEqual(released.status_code, 200, released.content)

    def door_at(self, when, number="SM/001", **kw):
        with self.at(when):
            return self.student_door(number, **kw)

    def assertScoreOnly(self, response, score):
        self.assertEqual(response.status_code, 200, response.content)
        this = response.json()["this"]
        self.assertEqual(this["score"], score)
        self.assertEqual(this["corrections"], [])
        self.assertTrue(this["answers_held"])
        self.assertEqual(this["answers_held_why"], ANSWERS_HELD)
        text = response.content.decode()
        for word in ANSWER_WORDS:
            self.assertNotIn(word, text)

    def assertAnswersShown(self, response, score, questions=4):
        self.assertEqual(response.status_code, 200, response.content)
        this = response.json()["this"]
        self.assertEqual(this["score"], score)
        self.assertFalse(this["answers_held"])
        self.assertEqual(len(this["corrections"]), questions)
        self.assertTrue(all(c["right_letter"] and c["explanation"] for c in this["corrections"]))


class AnswersWaitForEveryClassTests(TwoClassesSetUp):
    def test_releasing_one_class_shows_it_its_score_and_no_answer_while_the_other_sits(self):
        self.jss1a_sits_and_is_released()

        ada = self.door_at(self.in_window(12))
        emeka = self.door_at(self.in_window(12), "SM/002")
        with self.at(self.in_window(12)):
            staff = self.results().json()
            office = self.results(self.head).json()

        self.assertScoreOnly(ada, 4)
        self.assertScoreOnly(emeka, 2)
        # The tally is the score said another way; it names no question.
        self.assertEqual((emeka.json()["this"]["right"], emeka.json()["this"]["questions"]), (2, 4))
        self.assertEqual(staff["answers_held_for"], ["JSS 1B"])
        self.assertEqual(office["answers_held_for"], ["JSS 1B"])
        # The corrections were frozen at release all the same: held, not lost.
        with connected_to(self.stmarys):
            self.assertTrue(all(len(r.corrections) == 4 for r in ReleasedTestScore.objects.all()))

    def test_the_answers_show_once_the_other_class_has_finished(self):
        self.jss1a_sits_and_is_released()
        self.finish("SM/005", when=self.in_window(13))
        still = self.door_at(self.in_window(16))
        self.close_by_hand(self.jss1b_id, self.in_window(17))

        ada = self.door_at(self.in_window(18))
        bimpe = self.door_at(self.in_window(18), "SM/005")
        with self.at(self.in_window(18)):
            staff = self.results().json()

        self.assertScoreOnly(still, 4)
        self.assertAnswersShown(ada, 4)
        self.assertEqual(staff["answers_held_for"], [])
        # Releasing JSS 1A released JSS 1A: JSS 1B's own scores wait for its own release.
        self.assertEqual(bimpe.status_code, 409)
        self.assertEqual(bimpe.json()["detail"], NOT_RELEASED)

    def test_the_answers_show_once_the_window_has_closed(self):
        self.jss1a_sits_and_is_released()

        before = self.door_at(self.closes - timedelta(minutes=1))
        after = self.door_at(self.closes + timedelta(minutes=1), "SM/002")

        self.assertScoreOnly(before, 4)
        self.assertAnswersShown(after, 2)

    def test_a_class_closed_by_hand_before_it_sat_has_not_finished(self):
        """Closed to wait its turn, with the window still running: it can be opened again."""
        self.jss1a_sits_and_is_released()
        self.close_by_hand(self.jss1b_id, self.in_window(12))

        held = self.door_at(self.in_window(13))
        with connected_to(self.stmarys), self.at(self.in_window(13)):
            names = release.classes_still_to_finish(Test.objects.get(pk=self.test_id))

        self.assertScoreOnly(held, 4)
        self.assertEqual(names, ["JSS 1B"])

    def test_a_sitting_opened_again_by_hand_holds_the_answers_again(self):
        self.jss1a_sits_and_is_released()
        late = self.closes + timedelta(minutes=30)
        shown = self.door_at(late)
        self.open_class_by_hand(self.jss1b_id, late + timedelta(minutes=1))

        held = self.door_at(late + timedelta(minutes=2))
        self.close_by_hand(self.jss1b_id, late + timedelta(minutes=3))
        again = self.door_at(late + timedelta(minutes=4))

        self.assertAnswersShown(shown, 4)
        self.assertScoreOnly(held, 4)
        self.assertAnswersShown(again, 4)

    def test_an_attempt_still_running_holds_the_answers_until_its_time_is_over(self):
        """Bimpe starts; her class's sitting is closed without ending her attempt."""
        self.jss1a_sits_and_is_released()
        started = self.in_window(13)
        self.started("SM/005", device=Client(), when=started)
        self.close_by_hand(self.jss1b_id, self.in_window(14))
        with connected_to(self.stmarys):
            test = Test.objects.get(pk=self.test_id)
        over = started + timedelta(minutes=test.duration + test.late_window)

        running = self.door_at(over - timedelta(minutes=1))
        with connected_to(self.stmarys), self.at(over - timedelta(minutes=1)):
            names = release.classes_still_to_finish(test)
        done = self.door_at(max(over, self.closes) + timedelta(minutes=1))

        self.assertScoreOnly(running, 4)
        self.assertEqual(names, ["JSS 1B"])
        self.assertAnswersShown(done, 4)

    def test_a_test_closed_for_good_shows_the_answers(self):
        self.jss1a_sits_and_is_released()
        with self.at(self.in_window(15)):
            held = self.student_door()
            closed = self.post(self.head, f"tests/{self.test_id}/close/")
            shown = self.student_door()

        self.assertEqual(closed.status_code, 200, closed.content)
        self.assertScoreOnly(held, 4)
        self.assertAnswersShown(shown, 4)

    def test_a_parent_sees_the_score_and_never_an_answer_held_or_not(self):
        from accounts.services import activate_guardian_links

        activate_guardian_links(self.parent_user, self.stmarys)
        self.jss1a_sits_and_is_released()

        with self.at(self.in_window(12)):
            held = self.get(self.parent_user, "scores/").json()["children"]
        with self.after():
            shown = self.get(self.parent_user, "scores/").json()["children"]

        for children in (held, shown):
            self.assertEqual([(c["name"], [s["score"] for s in c["scores"]]) for c in children], [("Ada Obi", [4])])
            for word in (*ANSWER_WORDS, "corrections", "stem"):
                self.assertNotIn(word, json.dumps(children))


class OneClassTests(test_marking.MarkingSetUp):
    def test_a_paper_one_class_sits_shows_its_answers_at_release_as_before(self):
        """The control: nobody else has still to sit, so nothing is held."""
        self.finish("SM/001")
        with self.at(self.in_window(10)):
            closed = self.post(
                self.head, f"tests/{self.test_id}/classes/{self.jss1a_id}/close/", {"reason": "Finished"}
            )
            released = self.release()
            ada = self.student_door()
            staff = self.results().json()

        self.assertEqual((closed.status_code, released.status_code), (200, 200))
        self.assertEqual(ada.status_code, 200, ada.content)
        self.assertFalse(ada.json()["this"]["answers_held"])
        self.assertEqual(len(ada.json()["this"]["corrections"]), 4)
        self.assertEqual(staff["answers_held_for"], [])


class TwoSchoolsTests(TwoClassesSetUp):
    """Grace's test shares St Mary's test id. Each school's answers wait for its own
    classes and for nobody else's."""

    def grace_sits_and_is_released(self):
        grace_test = test_marking.TwoSchoolsTests.grace_sat(self)
        self.assertEqual(grace_test, self.test_id, "the two schools' tests share an id")
        self.close_by_hand(self.grace_group_id, self.in_window(9), host=THEIR_HOST, who=self.their_head)
        with self.at(self.in_window(9)):
            released = self.post(
                self.grace_teacher, f"tests/{self.test_id}/classes/{self.grace_group_id}/release/", host=THEIR_HOST
            )
        self.assertEqual(released.status_code, 200, released.content)

    def chidi_at(self, when):
        return self.door_at(
            when, "SM/001", pin=self.grace_pins["SM/001"], code=test_sitting.GRACE_CODE, host=THEIR_HOST
        )

    def test_one_schools_class_still_sitting_holds_only_that_schools_answers(self):
        self.grace_sits_and_is_released()
        self.jss1a_sits_and_is_released()

        ada = self.door_at(self.in_window(12))
        chidi = self.chidi_at(self.in_window(12))
        with self.at(self.in_window(12)):
            here = self.results().json()
            there = self.results(self.grace_teacher, host=THEIR_HOST).json()

        # St Mary's JSS 1B has still to sit St Mary's paper: St Mary's waits.
        self.assertScoreOnly(ada, 4)
        self.assertEqual(here["answers_held_for"], ["JSS 1B"])
        # Grace's one class has finished Grace's paper: Grace does not wait for St Mary's.
        self.assertEqual(chidi.status_code, 200, chidi.content)
        self.assertEqual(chidi.json()["name"], "Chidi Eze")
        self.assertFalse(chidi.json()["this"]["answers_held"])
        self.assertEqual(len(chidi.json()["this"]["corrections"]), 4)
        self.assertEqual(there["answers_held_for"], [])

    def test_another_schools_open_sitting_holds_nothing_here(self):
        """The other way about: Grace's class is still sitting, St Mary's has finished."""
        test_sitting.TheDoorTests.grace_published(self)
        self.jss1a_sits_and_is_released()
        self.finish("SM/005", when=self.in_window(13))
        self.close_by_hand(self.jss1b_id, self.in_window(17))

        ada = self.door_at(self.in_window(18))
        with self.at(self.in_window(18)):
            there = self.results(self.grace_teacher, host=THEIR_HOST).json()
            # St Mary's code and Ada's PIN open nothing at Grace.
            refused = self.student_door(host=THEIR_HOST)

        self.assertAnswersShown(ada, 4)
        self.assertEqual(len(there["answers_held_for"]), 1, "Grace's own class has still to sit")
        self.assertEqual(refused.status_code, 404)
