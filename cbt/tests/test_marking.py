"""Marking, key corrections, sending to CA, release and restore: `docs/cbt.md`, step 5.

Two schools on their own hosts (`results.tests.fixtures.ChainSetUp`), whose first class,
term, subject, assessment, test and student share ids. The claims, each with a control
in `docs/cbt.md` ("Built", step 5):

- **Marking** is computed on read from the counted answers and the keys; a key
  correction re-marks every attempt, says whose scores moved, needs a reason, and is
  refused after release, by the service and by the database.
- **Send to CA**: what the preview shows is what is written, through `set_score_as()`;
  a student who did not sit gets no mark; "keep" never overwrites; "replace" never
  overwrites a mark typed after the preview, and a mark typed by hand is replaced only
  when the send confirms it; a submitted class is untouched; a test without the exam PIN
  never sends, whatever the request says; another school's assessment cannot be named.
- **Release**: nothing reaches a student or a parent before it; each sees only their
  own; a released score never changes; a restore needs the principal and a reason, hides
  the scores again, and is kept.
- **Item analysis** counts match the attempts.
- **Who does what**, per role, and **the background job** closes what nobody read,
  stamped when it was due.
"""

import json
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import Client

from accounts.models import Role, User
from accounts.services import grant_membership, link_guardian
from cbt import ca, marking, officers
from cbt.models import (
    Attempt,
    CaTransfer,
    CaTransferLine,
    KeyCorrection,
    ReleasedTestScore,
    Test,
    TestItem,
    TestRelease,
    TestReleaseRestore,
)
from cbt.release import NOT_RELEASED
from cbt.sitting import NOT_OPENED
from cbt.tests import test_sitting
from gradebook.models import Assessment, Score
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

SCORES = "/test-scores/api/open/"


class MarkingSetUp(test_sitting.SittingSetUp):
    """Kemi's First CA test for JSS 1A, four questions of one mark, every key A (index 0).

    `finish()` sits a student and submits: Ada gets all four right, Emeka two, Bisi none
    (she answers B to everything), Tunde does not sit.
    """

    #: Each sitter's choices, by item position (original option index, or None).
    CHOICES = {
        "SM/001": [0, 0, 0, 0],
        "SM/002": [0, 1, 0, 2],
        "SM/003": [1, 1, 1, 1],
    }

    def finish(self, number, choices=None, when=None):
        device = Client()
        when = when or self.in_window()
        self.started(number, device=device, when=when)
        choices = self.CHOICES[number] if choices is None else choices
        answers = [
            {"seq": n + 1, "item": self.item_ids[n], "chosen": c, "chosen_at": (when + timedelta(minutes=1)).isoformat()}
            for n, c in enumerate(choices)
        ]
        with self.at(when + timedelta(minutes=2)):
            response = self.sit("submit/", {"answers": answers}, device=device)
        self.assertEqual(response.status_code, 200, response.content)

    def sat(self):
        for number in self.CHOICES:
            self.finish(number)

    def after(self, minutes=60):
        """After the window: every sitting is over and every attempt closed."""
        return self.at(self.closes + timedelta(minutes=minutes))

    def results(self, who=None, host=HOST):
        return self.get(who or self.teacher, f"tests/{self.test_id}/results/", host=host)

    def by_name(self, body):
        return {r["name"]: r for r in body["rows"]}

    def release(self, who=None, class_id=None):
        return self.post(who or self.teacher, f"tests/{self.test_id}/classes/{class_id or self.jss1a_id}/release/")

    def student_door(self, number="SM/001", pin=None, code=None, host=HOST, device=None):
        device = device or Client()
        pin = self.pins[number] if pin is None else pin
        response = device.post(
            SCORES, data=json.dumps({"code": code or test_sitting.CODE, "admission_number": number, "pin": pin}),
            content_type="application/json", HTTP_HOST=host,
        )
        connection.set_schema_to_public()
        return response

    def preview(self, who=None, existing="keep", assessment=None, host=HOST):
        return self.get(
            who or self.teacher,
            f"tests/{self.test_id}/ca/?assessment={assessment or self.first_ca_id}&existing={existing}", host=host,
        )

    def send(self, preview, who=None, existing="keep", confirm_replace=False, assessment=None):
        shown = {
            str(x["student_id"]): {"score": x["test_score"], "mark": x["mark"], "current": x["current"], "version": x["version"]}
            for x in preview["lines"]
        }
        return self.post(
            who or self.teacher, f"tests/{self.test_id}/ca/",
            {"assessment_id": assessment or self.first_ca_id, "existing": existing, "shown": shown,
             "confirm_replace": confirm_replace},
        )

    def scores_in_column(self, assessment_id=None):
        with connected_to(self.stmarys):
            return {
                s.student_membership_id: s.value
                for s in Score.objects.filter(assessment_id=assessment_id or self.first_ca_id)
            }

    def type_mark(self, student, value):
        from gradebook import services as gradebook

        with connected_to(self.stmarys):
            assessment = Assessment.objects.get(pk=self.first_ca_id)
            current = Score.objects.filter(assessment=assessment, student_membership_id=student.pk).first()
            gradebook.set_score_as(
                self.teacher.user, assessment, student, value, expected_version=current.version if current else None
            )


class MarkingTests(MarkingSetUp):
    def test_a_score_is_marked_on_read_from_the_counted_answers(self):
        self.sat()
        with self.after():
            body = self.results().json()
        rows = self.by_name(body)
        self.assertEqual(
            {n: (r["score"], r["out_of"], r["right"], r["answered"]) for n, r in rows.items()},
            {"Ada Obi": (4, 4, 4, 4), "Emeka Nwosu": (2, 4, 2, 4), "Bisi Ade": (0, 4, 0, 4),
             "Tunde Cole": (None, None, None, None)},
        )
        self.assertEqual(rows["Tunde Cole"]["state"], "Did not sit")
        self.assertEqual(body["stats"], {"sat": 3, "placed": 4, "average": 2.0, "percent": 50, "highest": 4,
                                         "highest_count": 1, "lowest": 0, "lowest_count": 1})
        with connected_to(self.stmarys):
            self.assertFalse(ReleasedTestScore.objects.exists(), "nothing is stored by marking")

    def test_the_later_answer_counts_in_the_mark(self):
        device = Client()
        self.started("SM/001", device=device)
        when = self.in_window(6)
        first = [{"seq": 1, "item": self.item_ids[0], "chosen": 1, "chosen_at": when.isoformat()}]
        second = [{"seq": 2, "item": self.item_ids[0], "chosen": 0, "chosen_at": (when + timedelta(seconds=30)).isoformat()}]
        with self.at(when + timedelta(seconds=40)):
            self.sit("sync/", {"answers": first}, device=device)
            self.sit("submit/", {"answers": second}, device=device)
        with self.after():
            self.assertEqual(self.by_name(self.results().json())["Ada Obi"]["score"], 1)

    def test_an_open_attempt_has_no_score_yet(self):
        self.started("SM/001")
        with self.at(self.in_window(10)):
            body = self.results().json()
        self.assertEqual(self.by_name(body)["Ada Obi"]["state"], "Sitting")
        self.assertIsNone(self.by_name(body)["Ada Obi"]["score"])
        self.assertEqual(body["open_attempts"], 1)

    def test_scaling_is_to_the_nearest_whole_mark_halves_up(self):
        cases = {(14, 20, 10): 7, (18, 20, 10): 9, (15, 20, 10): 8, (11, 20, 10): 6, (3, 4, 10): 8, (1, 3, 10): 3,
                 (2, 3, 10): 7, (5, 8, 10): 6, (7, 8, 10): 9, (1, 2, 5): 3, (0, 20, 10): 0, (20, 20, 10): 10,
                 (13, 20, 30): 20, (1, 40, 20): 1, (1, 41, 20): 0}
        for (score, out_of, max_score), expected in cases.items():
            with self.subTest(score=score, out_of=out_of, max_score=max_score):
                self.assertEqual(marking.round_half_up(score, out_of, max_score), expected)


class KeyCorrectionTests(MarkingSetUp):
    def correct(self, position=1, new_index=1, reason="Option B is the right answer", who=None):
        return self.post(
            who or self.teacher, f"tests/{self.test_id}/items/{self.item_ids[position]}/key/",
            {"new_index": new_index, "reason": reason},
        )

    def test_a_correction_re_marks_every_attempt_and_says_whose_scores_moved(self):
        self.sat()
        with self.after():
            response = self.correct()
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        rows = self.by_name(body)
        # Question 2's key is now B: Ada (A) loses one, Emeka and Bisi (B) gain one.
        self.assertEqual((rows["Ada Obi"]["score"], rows["Emeka Nwosu"]["score"], rows["Bisi Ade"]["score"]), (3, 3, 1))
        moved = {c["name"]: (c["before"], c["after"]) for c in body["corrected"]["changes"]}
        self.assertEqual(moved, {"Ada Obi": (4, 3), "Emeka Nwosu": (2, 3), "Bisi Ade": (0, 1)})
        with connected_to(self.stmarys):
            row = KeyCorrection.objects.get()
            self.assertEqual((row.old_index, row.new_index, row.by_name, row.reason), (0, 1, "Kemi Bello", "Option B is the right answer"))
            # The item itself is never edited.
            self.assertEqual(TestItem.objects.get(pk=self.item_ids[1]).correct_index, 0)
        item = next(i for i in body["items"] if i["item_id"] == self.item_ids[1])
        self.assertEqual((item["key"], item["key_corrected"], item["original_key"]), (1, True, 0))

    def test_a_correction_needs_a_reason_and_a_change(self):
        self.sat()
        with self.after():
            self.assertEqual(self.correct(reason="").status_code, 422)
            self.assertEqual(self.correct(new_index=0).status_code, 422)
            self.assertEqual(self.correct(new_index=7).status_code, 422)
        with connected_to(self.stmarys):
            self.assertFalse(KeyCorrection.objects.exists())

    def test_none_after_release_by_the_service_or_the_database(self):
        self.sat()
        with self.after():
            self.assertEqual(self.release().status_code, 200)
            refused = self.correct()
        self.assertEqual(refused.status_code, 422)
        self.assertIn("released", refused.json()["detail"])
        with connected_to(self.stmarys):
            item = TestItem.objects.get(pk=self.item_ids[1])
            with self.assertRaises(IntegrityError), transaction.atomic():
                KeyCorrection.objects.create(
                    test_id=self.test_id, item=item, old_index=0, new_index=1, reason="by hand", out_of=4,
                    by_id=1, by_name="x", role="teacher",
                )

    def test_after_a_restore_a_correction_is_allowed_and_a_re_release_freezes_the_new_scores(self):
        self.sat()
        with self.after():
            self.release()
            release_id = self._release_id()
            self.assertEqual(self.post(self.head, f"releases/{release_id}/restore/", {"reason": "Question 2's key was wrong"}).status_code, 200)
            self.assertEqual(self.correct().status_code, 200)
            self.assertEqual(self.release().status_code, 200)
        with connected_to(self.stmarys):
            first, second = TestRelease.objects.order_by("id")
            ada = self.children["ada"].pk
            self.assertEqual(ReleasedTestScore.objects.get(release=first, student_membership_id=ada).score, 4)
            self.assertEqual(ReleasedTestScore.objects.get(release=second, student_membership_id=ada).score, 3)

    def _release_id(self):
        with connected_to(self.stmarys):
            return TestRelease.objects.get(restore__isnull=True).pk

    def test_only_a_teacher_of_the_test_or_the_principal_corrects_a_key(self):
        self.sat()
        with self.after():
            for who, status in ((self.vp, 403), (self.admin, 403), (self.tayo, 403), (self.bursar, 404), (self.parent_user, 404)):
                with self.subTest(who=str(who)):
                    self.assertEqual(self.correct(who=who).status_code, status)
            self.assertEqual(self.correct(who=self.head).status_code, 200)


class ItemAnalysisTests(MarkingSetUp):
    def test_the_counts_match_the_attempts(self):
        self.sat()
        with self.after():
            body = self.results(self.head).json()
        items = {i["item_id"]: i for i in body["items"]}
        # Ada A A A A, Emeka A B A C, Bisi B B B B.
        expected = {
            0: ([2, 1, 0, 0], 67, 1),
            1: ([1, 2, 0, 0], 33, 1),
            2: ([2, 1, 0, 0], 67, 1),
            3: ([1, 1, 1, 0], 33, 1),
        }
        for position, (chose, facility, most_wrong) in expected.items():
            with self.subTest(question=position + 1):
                i = items[self.item_ids[position]]
                self.assertEqual((i["chose"], i["facility"], i["most_wrong"], i["blank"], i["key"]), (chose, facility, most_wrong, 0, 0))
        self.assertEqual(sum(items[self.item_ids[1]]["percent"]), 100)

    def test_only_the_answer_that_counts_is_counted(self):
        """Ada answers question 1 with B, then changes it to A: the analysis counts her A
        once, never the B she left, and her score is the A's."""
        device = Client()
        self.started("SM/001", device=device)
        when = self.in_window(6)
        first = [{"seq": 1, "item": self.item_ids[0], "chosen": 1, "chosen_at": when.isoformat()}]
        second = [{"seq": 2, "item": self.item_ids[0], "chosen": 0, "chosen_at": (when + timedelta(seconds=30)).isoformat()}]
        with self.at(when + timedelta(seconds=40)):
            self.sit("sync/", {"answers": first}, device=device)
            self.sit("submit/", {"answers": second}, device=device)
        with self.after():
            body = self.results().json()
        item = next(i for i in body["items"] if i["item_id"] == self.item_ids[0])
        self.assertEqual((item["chose"], item["facility"]), ([1, 0, 0, 0], 100))

    def test_a_blank_answer_is_counted_as_blank(self):
        self.finish("SM/001", [0, None, None, 0])
        with self.after():
            body = self.results().json()
        item = next(i for i in body["items"] if i["item_id"] == self.item_ids[1])
        self.assertEqual((item["chose"], item["blank"], item["facility"]), ([0, 0, 0, 0], 1, 0))


class SendToCaTests(MarkingSetUp):
    def test_the_preview_writes_nothing_and_is_what_the_send_writes(self):
        self.sat()
        with self.after():
            preview = self.preview().json()
            self.assertEqual(self.scores_in_column(), {})
            lines = {x["name"]: (x["test_score"], x["mark"], x["will"]) for x in preview["lines"]}
            # First CA is out of 20; the test out of 4.
            self.assertEqual(lines, {"Ada Obi": (4, 20, "new"), "Emeka Nwosu": (2, 10, "new"), "Bisi Ade": (0, 0, "new"),
                                     "Tunde Cole": (None, None, "not_sat")})
            response = self.send(preview)
        self.assertEqual(response.status_code, 200, response.content)
        written = self.scores_in_column()
        c = self.children
        self.assertEqual(written, {c["ada"].pk: 20, c["emeka"].pk: 10, c["bisi"].pk: 0})
        self.assertNotIn(c["tunde"].pk, written, "a student who did not sit gets no mark, not a zero")
        with connected_to(self.stmarys):
            outcomes = dict(CaTransferLine.objects.values_list("student_name", "outcome"))
            self.assertEqual(outcomes, {"Ada Obi": "written", "Emeka Nwosu": "written", "Bisi Ade": "written", "Tunde Cole": "not_sat"})
            self.assertEqual(CaTransfer.objects.get().by_name, "Kemi Bello")

    def test_keep_never_overwrites_a_mark_already_there(self):
        self.sat()
        self.type_mark(self.children["ada"], 7)
        with self.after():
            preview = self.preview().json()
            ada = next(x for x in preview["lines"] if x["name"] == "Ada Obi")
            self.assertEqual((ada["will"], ada["current"], ada["by_hand"]), ("kept", 7, True))
            self.assertEqual(self.send(preview).status_code, 200)
        self.assertEqual(self.scores_in_column()[self.children["ada"].pk], 7)

    def test_replacing_a_mark_typed_by_hand_is_shown_and_needs_confirming(self):
        self.sat()
        self.type_mark(self.children["ada"], 7)
        with self.after():
            preview = self.preview(existing="replace").json()
            self.assertEqual(preview["replaces_by_hand"], 1)
            refused = self.send(preview, existing="replace")
            self.assertEqual(refused.status_code, 422)
            self.assertEqual(self.scores_in_column()[self.children["ada"].pk], 7)
            with connected_to(self.stmarys):
                self.assertFalse(CaTransfer.objects.exists())
            self.assertEqual(self.send(preview, existing="replace", confirm_replace=True).status_code, 200)
        self.assertEqual(self.scores_in_column()[self.children["ada"].pk], 20)

    def test_replace_never_overwrites_a_mark_typed_after_the_preview(self):
        self.sat()
        self.type_mark(self.children["ada"], 7)
        with self.after():
            preview = self.preview(existing="replace").json()
            self.type_mark(self.children["ada"], 11)
            self.type_mark(self.children["emeka"], 5)
            self.assertEqual(self.send(preview, existing="replace", confirm_replace=True).status_code, 200)
        column = self.scores_in_column()
        self.assertEqual((column[self.children["ada"].pk], column[self.children["emeka"].pk]), (11, 5))
        with connected_to(self.stmarys):
            outcomes = dict(CaTransferLine.objects.values_list("student_name", "outcome"))
        self.assertEqual((outcomes["Ada Obi"], outcomes["Emeka Nwosu"], outcomes["Bisi Ade"]), ("changed_meanwhile", "changed_meanwhile", "written"))

    def test_a_score_that_moved_since_the_preview_refuses_the_whole_send(self):
        self.sat()
        with self.after():
            preview = self.preview().json()
            self.post(self.teacher, f"tests/{self.test_id}/items/{self.item_ids[1]}/key/", {"new_index": 1, "reason": "B is right"})
            refused = self.send(preview)
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(self.scores_in_column(), {})

    def test_sending_again_with_keep_writes_only_the_new_ones(self):
        self.finish("SM/001")
        with self.after():
            self.assertEqual(self.send(self.preview().json()).status_code, 200)
            again = self.preview().json()
            ada = next(x for x in again["lines"] if x["name"] == "Ada Obi")
            self.assertEqual((ada["will"], ada["by_hand"]), ("same", False))
            self.assertEqual(self.send(again).status_code, 200)
        with connected_to(self.stmarys):
            second = CaTransfer.objects.get(number=2)
            self.assertEqual(second.lines.get(student_name="Ada Obi").outcome, "kept")

    def test_a_submitted_class_is_locked_and_untouched(self):
        from academics.models import ClassGroup, Term
        from results import services as chain

        self.sat()
        with connected_to(self.stmarys):
            sheet = chain.open_sheet(ClassGroup.objects.get(pk=self.jss1a_id), Term.objects.get(pk=self.term_id), self.teacher.user)
            chain.submit(sheet, self.teacher.user)
        with self.after():
            preview = self.preview().json()
            self.assertEqual({x["will"] for x in preview["lines"] if x["test_score"] is not None}, {"locked"})
            self.assertEqual(preview["locked_classes"][0]["class_name"], "JSS 1A")
            self.assertEqual(self.send(preview).status_code, 200)
        self.assertEqual(self.scores_in_column(), {})
        with connected_to(self.stmarys):
            self.assertEqual(set(CaTransferLine.objects.exclude(outcome="not_sat").values_list("outcome", flat=True)), {"locked"})

    def test_a_test_without_the_exam_pin_never_sends(self):
        with connected_to(self.stmarys):
            # Set without the PIN: the database refuses the PIN off with sending on.
            with self.assertRaises(IntegrityError), transaction.atomic():
                Test.objects.filter(pk=self.test_id).update(require_pin=False)
        no_pin = self.set_test(title="Practice, no PIN", require_pin=False)
        self.assertEqual(self.post(self.teacher, f"tests/{no_pin}/submit/").status_code, 200)
        self.assertEqual(self.post(self.head, f"tests/{no_pin}/approve/").status_code, 200)
        for path, call in (("ca/?assessment=%d" % self.first_ca_id, self.get), ("ca/", None)):
            with self.subTest(path=path):
                if call:
                    response = call(self.teacher, f"tests/{no_pin}/{path}")
                else:
                    response = self.post(self.teacher, f"tests/{no_pin}/ca/", {"assessment_id": self.first_ca_id, "existing": "keep", "shown": {}})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], ca.NO_PIN)
        with connected_to(self.stmarys):
            with self.assertRaises(Exception):
                ca.send_as(self.teacher.user, self.stmarys, no_pin, self.first_ca_id, "keep", {})
            self.assertFalse(CaTransfer.objects.exists())

    def test_only_the_tests_teachers_and_the_principal_send(self):
        self.sat()
        with self.after():
            preview = self.preview().json()
            for who, status in ((self.vp, 403), (self.admin, 403), (self.tayo, 403), (self.bursar, 404), (self.parent_user, 404)):
                with self.subTest(who=str(who)):
                    self.assertEqual(self.preview(who=who).status_code, status)
                    self.assertEqual(self.send(preview, who=who).status_code, status)
            self.assertEqual(self.preview(who=self.head).status_code, 200)
        self.assertEqual(self.scores_in_column(), {})

    def test_only_the_tests_subject_and_term_columns_can_be_named(self):
        """A column of St Mary's own, but of another subject or another term, is refused."""
        self.sat()
        with connected_to(self.stmarys):
            english = Assessment.objects.create(term_id=self.term_id, subject_id=self.english_id, name="English CA", max_score=10).pk
            later = Assessment.objects.create(term_id=self.second_term.pk, subject_id=self.maths_id, name="Second term CA", max_score=10).pk
        with self.after():
            for column in (english, later):
                with self.subTest(column=column):
                    self.assertEqual(self.preview(assessment=column).status_code, 422)
                    self.assertEqual(self.send({"lines": []}, assessment=column).status_code, 422)
        with connected_to(self.stmarys):
            self.assertFalse(Score.objects.filter(assessment_id__in=[english, later]).exists())

    def test_another_schools_assessment_cannot_be_named(self):
        self.sat()
        with connected_to(self.grace):
            theirs = Assessment.objects.create(term_id=self.grace_term_id, subject_id=self.grace_maths_id, name="Grace's Second CA", max_score=10).pk
        with connected_to(self.stmarys):
            self.assertFalse(Assessment.objects.filter(pk=theirs).exists(), "the id exists only at Grace")
        with self.after():
            self.assertEqual(self.preview(assessment=theirs).status_code, 422)
        with connected_to(self.grace):
            self.assertFalse(Score.objects.filter(assessment_id=theirs).exists())


class ReleaseTests(MarkingSetUp):
    def setUp(self):
        super().setUp()
        self.other_parent = User.objects.create_user("baba", PASSWORD, full_name="Baba Nwosu")
        link_guardian(self.other_parent, self.children["emeka"])
        give_verified_channel(self.other_parent, "08030000072")
        from accounts.services import activate_guardian_links

        activate_guardian_links(self.parent_user, self.stmarys)
        activate_guardian_links(self.other_parent, self.stmarys)

    def family(self, who, host=HOST):
        return self.get(who, "scores/", host=host).json()["children"]

    def test_nothing_reaches_a_student_or_a_parent_before_release(self):
        self.sat()
        with self.after():
            response = self.student_door()
            self.assertEqual(response.status_code, 409, response.content)
            self.assertEqual(response.json()["detail"], NOT_RELEASED)
            ada = self.family(self.parent_user)
        self.assertEqual([(c["name"], c["scores"], c["waiting"]) for c in ada], [("Ada Obi", [], 1)])

    def test_a_class_is_released_once_its_sitting_is_over(self):
        self.sat()
        with self.at(self.in_window(20)):
            refused = self.release()
        self.assertEqual(refused.status_code, 422)
        self.assertIn("still open", refused.json()["detail"])
        with self.after():
            self.assertEqual(self.release().status_code, 200)
            self.assertEqual(self.release().status_code, 422, "released already")

    def test_after_release_each_sees_only_their_own(self):
        self.sat()
        with self.after():
            self.assertEqual(self.release().status_code, 200)
            mine = self.student_door()
            emeka = self.student_door("SM/002")
            wrong = self.student_door(pin=self.pins["SM/002"])
            ada_parent = self.family(self.parent_user)
            emeka_parent = self.family(self.other_parent)
        self.assertEqual(mine.status_code, 200, mine.content)
        body = mine.json()
        self.assertEqual((body["name"], body["this"]["score"], body["this"]["out_of"], body["this"]["right"]), ("Ada Obi", 4, 4, 4))
        self.assertEqual(len(body["this"]["corrections"]), 4)
        self.assertEqual(emeka.json()["this"]["score"], 2)
        wrongs = [c for c in emeka.json()["this"]["corrections"] if not c["right"]]
        self.assertEqual(len(wrongs), 2)
        self.assertTrue(all(c["right_letter"] and c["explanation"] for c in wrongs))
        self.assertEqual(wrong.status_code, 404)
        self.assertEqual(wrong.json()["detail"], NOT_OPENED)
        self.assertEqual([(c["name"], [s["score"] for s in c["scores"]]) for c in ada_parent], [("Ada Obi", [4])])
        self.assertEqual([(c["name"], [s["score"] for s in c["scores"]]) for c in emeka_parent], [("Emeka Nwosu", [2])])
        # A parent's page carries no question and no answer.
        self.assertNotIn("corrections", json.dumps(ada_parent))
        self.assertNotIn("stem", json.dumps(ada_parent))

    def test_the_letters_in_the_corrections_are_the_ones_the_student_saw(self):
        from cbt import sitting as sit

        self.sat()
        with self.after():
            self.release()
            body = self.student_door("SM/002").json()
        with connected_to(self.stmarys):
            attempt = Attempt.objects.get(student_membership_id=self.children["emeka"].pk)
            sent = sit.paper_for(attempt)
        for shown, kept in zip(sent["items"], body["this"]["corrections"]):
            with self.subTest(number=shown["number"]):
                self.assertEqual(shown["stem"], kept["stem"])
                letters = {o["index"]: "ABCDE"[n] for n, o in enumerate(shown["options"])}
                self.assertEqual(kept["right_letter"], letters[0])
                self.assertEqual([o["text"] for o in shown["options"]], [o["text"] for o in kept["options"]])

    def test_a_released_score_never_changes(self):
        self.sat()
        with self.after():
            self.release()
        with connected_to(self.stmarys):
            row = ReleasedTestScore.objects.first()
            for act in (lambda: ReleasedTestScore.objects.filter(pk=row.pk).update(score=0),
                        lambda: ReleasedTestScore.objects.filter(pk=row.pk).delete(),
                        lambda: TestRelease.objects.update(count=0)):
                with self.subTest(act=act):
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        act()

    def test_restore_needs_the_principal_and_a_reason_hides_the_scores_and_is_kept(self):
        self.sat()
        with self.after():
            self.release()
            with connected_to(self.stmarys):
                release_id = TestRelease.objects.get().pk
            path = f"releases/{release_id}/restore/"
            for who, status in ((self.teacher, 403), (self.vp, 403), (self.admin, 403), (self.bursar, 404)):
                with self.subTest(who=str(who)):
                    self.assertEqual(self.post(who, path, {"reason": "wrong key"}).status_code, status)
            self.assertEqual(self.post(self.head, path, {"reason": ""}).status_code, 422)
            done = self.post(self.head, path, {"reason": "Question 2's key was wrong"})
            self.assertEqual(done.status_code, 200, done.content)
            self.assertEqual(self.post(self.head, path, {"reason": "again"}).status_code, 422)
            self.assertEqual(self.student_door().status_code, 409)
            self.assertEqual(self.family(self.parent_user)[0]["scores"], [])
            klass = done.json()["classes"][0]
            self.assertEqual((klass["released"], klass["history"][0]["restored"], klass["history"][0]["reason"]),
                             (False, True, "Question 2's key was wrong"))
        with connected_to(self.stmarys):
            self.assertEqual(ReleasedTestScore.objects.count(), 3, "the frozen rows are kept")
            restore = TestReleaseRestore.objects.get()
            self.assertEqual((restore.by_name, restore.reason), ("Ngozi Eze", "Question 2's key was wrong"))
            with self.assertRaises(IntegrityError), transaction.atomic():
                TestReleaseRestore.objects.filter(pk=restore.pk).delete()

    def test_a_restore_never_touches_a_ca_mark_already_sent(self):
        self.sat()
        with self.after():
            self.send(self.preview().json())
            self.release()
            with connected_to(self.stmarys):
                release_id = TestRelease.objects.get().pk
            self.post(self.head, f"releases/{release_id}/restore/", {"reason": "Wrong key"})
        self.assertEqual(self.scores_in_column()[self.children["ada"].pk], 20)

    def test_who_releases(self):
        self.sat()
        with self.after():
            for who, status in ((self.vp, 403), (self.admin, 403), (self.tayo, 403), (self.bursar, 404), (self.parent_user, 404)):
                with self.subTest(who=str(who)):
                    self.assertEqual(self.release(who=who).status_code, status)
            with connected_to(self.stmarys):
                officers.name_as(self.head.user, self.stmarys, self.tayo.pk)
            self.assertEqual(self.release(who=self.tayo).status_code, 403, "an exam officer does not release")
            self.assertEqual(self.release(who=self.head).status_code, 200)

    def test_the_office_sees_scores_only_after_release_and_no_answer(self):
        self.sat()
        with self.after():
            before = self.results(self.admin).json()
            self.release()
            after = self.results(self.admin).json()
        self.assertTrue(before["released_only"])
        self.assertEqual((before["rows"], before["items"]), ([], []))
        self.assertEqual(sorted((r["name"], r["score"]) for r in after["rows"]), [("Ada Obi", 4), ("Bisi Ade", 0), ("Emeka Nwosu", 2)])
        self.assertEqual(after["items"], [])
        text = json.dumps(after)
        for word in ('"key"', '"chose"', '"stem"', "corrections\": [{"):
            self.assertNotIn(word, text)


class WhoReadsResultsTests(MarkingSetUp):
    def test_every_role(self):
        self.sat()
        with connected_to(self.stmarys):
            officers.name_as(self.head.user, self.stmarys, self.tayo.pk)
        with self.after():
            for who, status in ((self.teacher, 200), (self.head, 200), (self.vp, 200), (self.admin, 200),
                                (self.tayo, 403), (self.bursar, 404), (self.parent_user, 404), (self.student, 404)):
                with self.subTest(who=str(who)):
                    self.assertEqual(self.results(who).status_code, status)
            vp = self.results(self.vp).json()
        self.assertEqual((vp["may_correct"], vp["may_send"], vp["may_close"], vp["may_restore"]), (False, False, False, False))
        self.assertTrue(vp["items"], "the vice principal reads the item analysis")

    def test_a_teacher_reads_only_their_own_classes(self):
        from gradebook.models import SubjectTeacher

        # JSS 1B joins the test; Kemi does not teach it.
        with connected_to(self.stmarys):
            SubjectTeacher.objects.create(term_id=self.term_id, class_group_id=self.jss1b_id, subject_id=self.maths_id,
                                          teacher_membership_id=self.tayo.pk, assigned_by_id=self.head.user.pk)
        self.assertEqual(self.post(self.head, f"tests/{self.test_id}/classes/", {"class_group_ids": [self.jss1a_id, self.jss1b_id]}).status_code, 200)
        self.sat()
        with self.after():
            kemi = self.results().json()
            tayo = self.results(self.tayo).json()
            head = self.results(self.head).json()
        self.assertEqual({c["name"] for c in kemi["classes"]}, {"JSS 1A"})
        self.assertEqual({c["name"] for c in tayo["classes"]}, {"JSS 1B"})
        self.assertNotIn("Ada Obi", self.by_name(tayo))
        self.assertIn("Bimpe Ojo", self.by_name(tayo))
        self.assertEqual({c["name"] for c in head["classes"]}, {"JSS 1A", "JSS 1B"})
        with self.after():
            self.assertEqual(self.release(who=self.tayo).status_code, 403, "not Tayo's class")


class TwoSchoolsTests(MarkingSetUp):
    def grace_sat(self):
        grace_test = test_sitting.TheDoorTests.grace_published(self)
        self.assertEqual(grace_test, self.test_id)
        device = Client()
        with self.at(self.in_window()):
            door = self.sit("door/", {"code": test_sitting.GRACE_CODE, "admission_number": "SM/001", "pin": self.grace_pins["SM/001"]},
                            device=device, host=THEIR_HOST)
            self.assertEqual(door.status_code, 200, door.content)
            self.sit("start/", {"ticket": door.json()["ticket"]}, device=device, host=THEIR_HOST)
        with connected_to(self.grace):
            item = TestItem.objects.filter(test_id=grace_test).order_by("position").first().pk
        with self.at(self.in_window(7)):
            self.sit("submit/", {"answers": [{"seq": 1, "item": item, "chosen": 0, "chosen_at": self.in_window(6).isoformat()}]},
                     device=device, host=THEIR_HOST)
        return grace_test

    def test_results_scores_and_releases_stay_at_their_school(self):
        self.sat()
        self.grace_sat()
        with self.after():
            here = self.results().json()
            there = self.results(self.grace_teacher, host=THEIR_HOST).json()
            # A login with no membership at Grace is refused at Grace's door.
            self.assertEqual(self.results(self.teacher, host=THEIR_HOST).status_code, 403)
            self.assertEqual(self.release().status_code, 200)
            # St Mary's code and Ada's PIN open nothing at Grace, whose test shares the id.
            refused = self.student_door(host=THEIR_HOST)
            self.assertEqual(self.post(self.grace_teacher, f"tests/{self.test_id}/classes/{self.grace_group_id}/release/", host=THEIR_HOST).status_code, 200)
            theirs = self.student_door("SM/001", pin=self.grace_pins["SM/001"], code=test_sitting.GRACE_CODE, host=THEIR_HOST)
            ours = self.student_door()
            mama_there = self.get(self.parent_user, "scores/", host=THEIR_HOST)
        self.assertEqual({r["name"] for r in there["rows"]}, {"Chidi Eze"})
        self.assertNotIn("Chidi Eze", self.by_name(here))
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.json()["detail"], NOT_OPENED)
        self.assertEqual((theirs.json()["name"], theirs.json()["this"]["score"]), ("Chidi Eze", 1))
        self.assertEqual((ours.json()["name"], ours.json()["this"]["score"]), ("Ada Obi", 4))
        self.assertIn(mama_there.status_code, (200, 403))
        if mama_there.status_code == 200:
            self.assertEqual(mama_there.json()["children"], [])
        with connected_to(self.grace):
            self.assertEqual(list(ReleasedTestScore.objects.values_list("student_name", flat=True)), ["Chidi Eze"])


class ClosingTests(MarkingSetUp):
    def test_closing_a_test_keeps_everything_and_stops_new_starts(self):
        self.finish("SM/001")
        self.started("SM/002", device=Client(), when=self.in_window(10))
        with self.at(self.in_window(11)):
            refused = self.post(self.teacher, f"tests/{self.test_id}/close/")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("still sitting", refused.json()["detail"])
        with self.after():
            for who in (self.vp, self.admin, self.tayo):
                self.assertEqual(self.post(who, f"tests/{self.test_id}/close/").status_code, 403)
            closed = self.post(self.teacher, f"tests/{self.test_id}/close/")
            self.assertEqual(closed.status_code, 200, closed.content)
            self.assertEqual(closed.json()["state"], "closed")
            self.assertEqual(self.open_by_hand().status_code, 422, "a closed test is never opened again")
            self.assertEqual(self.release().status_code, 200, "a closed test is released as an open one")
        self.assertEqual(self.door("SM/003").status_code, 404)
        with connected_to(self.stmarys):
            self.assertEqual(list(Test.objects.get(pk=self.test_id).state_changes.values_list("to_state", flat=True)), ["closed", "published", "submitted"])


class BackgroundJobTests(MarkingSetUp):
    def test_the_job_closes_what_nobody_read_stamped_when_it_was_due(self):
        self.started("SM/001", device=Client())
        with connected_to(self.stmarys):
            attempt = Attempt.objects.get()
            due = attempt.base_deadline + timedelta(minutes=Test.objects.get(pk=self.test_id).late_window)
        with self.at(due - timedelta(seconds=1)):
            out = StringIO()
            call_command("close_overdue_attempts", stdout=out)
            self.assertEqual(out.getvalue().strip(), "Closed 0 attempts.")
        with self.at(due + timedelta(hours=3)):
            out = StringIO()
            call_command("close_overdue_attempts", stdout=out)
            self.assertEqual(out.getvalue().strip(), "Closed 1 attempt.")
            again = StringIO()
            call_command("close_overdue_attempts", stdout=again)
            self.assertEqual(again.getvalue().strip(), "Closed 0 attempts.")
        with connected_to(self.stmarys):
            attempt.refresh_from_db()
            self.assertEqual((attempt.submitted_at, attempt.ended_by), (due, "clock"))
        connection.set_schema_to_public()
