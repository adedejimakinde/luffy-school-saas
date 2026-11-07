"""Question banks and tests: `docs/cbt.md`, Phase 2 step 3.

Two schools on their own hosts (`results.tests.fixtures.ChainSetUp`), whose first class,
term and subject share ids, so a bank, a question and a test at each share ids too. The
claims, each with a control in `docs/cbt.md` ("Built", step 3):

- **A teacher reads and writes only the banks of the subjects and levels they teach this
  term**, and sets tests only for those subjects and classes. A teacher with none has
  none. The vice principal reads every bank and test, and writes and approves nothing.
  The principal writes, sets and approves.
- **The administrator never reads a bank or a question**, named exam officer or not: the
  Tests list, with no question in it, is all they get. Bursars, parents and students get
  nothing at all.
- **Only the principal approves**, and only before the test opens. Sending back needs a
  reason. Every move, and every change of classes after a test leaves draft, is
  written down in a table that cannot be edited.
- **A test keeps the copy it was sent with**: editing, retiring or re-answering a bank
  question after that changes nothing in it, and the database refuses an edit to the
  copy or to what the test is.
- **Nothing shaped for a student carries an answer key**: the paper is
  `cbt.paper.for_device()`, and no route answers a student at all.
- **One school's banks, questions, tests and pictures are never another's**, and a role
  at one school is nothing at another.
"""

import json
import re
from datetime import timedelta
from io import BytesIO

from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from academics.models import ClassGroup, Term
from accounts.models import Membership, Role, User
from accounts.services import grant_membership, link_guardian
from cbt import access, paper, setting
from cbt.models import (
    Question,
    QuestionBank,
    Test,
    TestAudienceChange,
    TestItem,
    TestStateChange,
)
from gradebook.models import Subject, SubjectTeacher
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel
from tests.refusals import RefusalAssertions

BASE = "/api/cbt/"

#: Anything that would give an answer away, as a JSON key.
KEYS = re.compile(r'"(correct_index|explanation)"')


def a_png(width=40, height=30) -> bytes:
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


class BanksSetUp(RefusalAssertions, ChainSetUp):
    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )
        self.tayo = grant_membership(
            User.objects.create_user("tayo", PASSWORD, full_name="Tayo Ojo"), self.stmarys, Role.TEACHER
        )
        self.parent_user = User.objects.create_user("mama", PASSWORD, full_name="Mama Obi")
        link_guardian(self.parent_user, self.children["ada"])
        give_verified_channel(self.parent_user, "08030000071")
        self.student = self.children["ada"]
        with connected_to(self.stmarys):
            self.english_id = Subject.objects.create(name="English Language", code="ENG").pk
            self.jss2a_id = ClassGroup.objects.create(name="JSS 2A", level=2).pk
            # Kemi teaches Mathematics to JSS 1A only; Tayo teaches nothing.
            SubjectTeacher.objects.create(
                term_id=self.term_id, class_group_id=self.jss1a_id, subject_id=self.maths_id,
                teacher_membership_id=self.teacher.pk, assigned_by_id=self.head.user.pk,
            )
        with connected_to(self.grace):
            self.grace_maths_id = Subject.objects.get(code="MTH").pk
            SubjectTeacher.objects.create(
                term_id=self.grace_term_id, class_group_id=self.grace_group_id, subject_id=self.grace_maths_id,
                teacher_membership_id=self.grace_teacher.pk, assigned_by_id=self.their_head.user.pk,
            )
        self.opens = (timezone.now() + timedelta(days=2)).replace(microsecond=0)
        self.closes = self.opens + timedelta(hours=3)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    # -- HTTP -----------------------------------------------------------------------

    def as_(self, who):
        user = who.user if isinstance(who, Membership) else who
        self.client.force_login(user)
        return self.client

    def get(self, who, path, host=HOST):
        response = self.as_(who).get(f"{BASE}{path}", HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def post(self, who, path, data=None, host=HOST):
        response = self.as_(who).post(
            f"{BASE}{path}", data=json.dumps(data or {}), content_type="application/json", HTTP_HOST=host
        )
        connection.set_schema_to_public()
        return response

    def question(self, n=1, **over):
        body = {
            "stem": f"What is {n} + {n}?",
            "options": [str(2 * n), str(2 * n + 1), str(2 * n + 2), str(2 * n + 3)],
            "correct_index": 0,
            "marks": 1,
            "topic": "Number",
            "explanation": f"{n} and {n} make {2 * n}.",
        }
        body.update(over)
        return body

    def add(self, who, n=1, subject_id=None, level=1, host=HOST, **over):
        subject_id = subject_id or self.maths_id
        return self.post(who, f"banks/{subject_id}/{level}/questions/", self.question(n, **over), host=host)

    def fill(self, who=None, count=6, host=HOST, subject_id=None):
        who = who or self.teacher
        ids = []
        for n in range(1, count + 1):
            response = self.add(who, n, subject_id=subject_id, host=host)
            self.assertEqual(response.status_code, 200, response.content)
            ids.append(response.json()["id"])
        return ids

    def test_body(self, classes=None, count=4, **over):
        body = {
            "title": "First CA test",
            "subject_id": self.maths_id,
            "level": 1,
            "class_group_ids": classes or [self.jss1a_id],
            "question_count": count,
            "opens_at": self.opens.isoformat(),
            "closes_at": self.closes.isoformat(),
            "duration": 30,
        }
        body.update(over)
        return body

    def set_test(self, who=None, host=HOST, **over):
        response = self.post(who or self.teacher, "tests/", self.test_body(**over), host=host)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["id"]

    def published(self, who=None):
        """A test with its questions copied in, approved by the principal."""
        self.fill(who)
        test_id = self.set_test(who)
        self.assertEqual(self.post(who or self.teacher, f"tests/{test_id}/submit/").status_code, 200)
        self.assertEqual(self.post(self.head, f"tests/{test_id}/approve/").status_code, 200)
        return test_id

    def items(self, test_id, school=None):
        with connected_to(school or self.stmarys):
            return list(TestItem.objects.filter(test_id=test_id).order_by("position").values(
                "stem", "options", "correct_index", "marks", "explanation", "origin_question_id", "origin_version"
            ))


class ATeacherReachesOnlyTheirOwnSubjectsAndLevelsTests(BanksSetUp):
    def test_a_teacher_writes_and_reads_their_own_bank(self):
        response = self.add(self.teacher)

        self.assertEqual(response.status_code, 200, response.content)
        body = self.get(self.teacher, f"banks/{self.maths_id}/1/").json()
        self.assertEqual([q["stem"] for q in body["questions"]], ["What is 1 + 1?"])
        self.assertEqual(body["questions"][0]["correct_index"], 0)
        self.assertEqual(body["level_name"], "JSS 1")
        listed = self.get(self.teacher, "banks/").json()["banks"]
        self.assertEqual([(b["subject"], b["level"], b["in_use"], b["may_write"]) for b in listed], [("Mathematics", 1, 1, True)])

    def test_a_teacher_cannot_reach_a_subject_or_level_they_do_not_teach(self):
        for subject_id, level in ((self.english_id, 1), (self.maths_id, 2)):
            with self.subTest(subject=subject_id, level=level):
                self.assertEqual(self.add(self.teacher, subject_id=subject_id, level=level).status_code, 403)
                self.assertEqual(self.get(self.teacher, f"banks/{subject_id}/{level}/").status_code, 404)
        self.add(self.head, subject_id=self.english_id)
        with connected_to(self.stmarys):
            english = Question.objects.get(bank__subject_id=self.english_id)
        self.assertEqual(self.get(self.teacher, f"questions/{english.pk}/").status_code, 404)
        edited = self.post(self.teacher, f"questions/{english.pk}/", {**self.question(9), "version": 1})
        self.assertEqual(edited.status_code, 404)
        self.assertEqual(self.post(self.teacher, f"questions/{english.pk}/retire/").status_code, 404)
        with connected_to(self.stmarys):
            self.assertEqual(Question.objects.get(pk=english.pk).version, 1)

    def test_a_teacher_with_no_subject_this_term_has_no_bank(self):
        self.fill(self.teacher, 2)
        body = self.get(self.tayo, "banks/").json()

        self.assertEqual(body["banks"], [])
        self.assertIn("principal says who teaches what", body["empty_because"])
        self.assertEqual(self.add(self.tayo).status_code, 403)
        self.assertEqual(self.get(self.tayo, f"banks/{self.maths_id}/1/").status_code, 404)
        self.assertEqual(self.get(self.tayo, "tests/").json()["tests"], [])

    def test_a_teacher_sets_tests_only_for_the_classes_they_teach(self):
        self.fill()
        refused = self.post(self.teacher, "tests/", self.test_body(classes=[self.jss1a_id, self.jss1b_id]))

        self.assertEqual(refused.status_code, 403)
        self.assertIn("JSS 1B", refused.json()["detail"])
        self.assertEqual(self.post(self.teacher, "tests/", self.test_body(subject_id=self.english_id)).status_code, 403)
        self.assertEqual(self.post(self.tayo, "tests/", self.test_body()).status_code, 403)
        test_id = self.set_test()
        self.assertEqual(self.get(self.teacher, f"tests/{test_id}/").status_code, 200)
        self.assertEqual(self.get(self.tayo, f"tests/{test_id}/").status_code, 404)
        with connected_to(self.stmarys):
            self.assertEqual(Test.objects.count(), 1)

    def test_the_vice_principal_reads_every_bank_and_test_and_writes_nothing(self):
        self.fill()
        test_id = self.set_test()
        self.post(self.teacher, f"tests/{test_id}/submit/")

        listed = self.get(self.vp, "banks/").json()["banks"]
        self.assertEqual([(b["subject"], b["may_write"]) for b in listed], [("Mathematics", False)])
        self.assertEqual(len(self.get(self.vp, f"banks/{self.maths_id}/1/").json()["questions"]), 6)
        detail = self.get(self.vp, f"tests/{test_id}/").json()
        self.assertEqual(len(detail["items"]), 4)
        self.assertFalse(detail["may_approve"] or detail["may_edit"] or detail["may_withdraw"])
        self.assertEqual(self.get(self.vp, f"tests/{test_id}/preview/").status_code, 200)
        self.assertEqual(self.add(self.vp).status_code, 403)
        self.assertEqual(self.post(self.vp, "tests/", self.test_body()).status_code, 403)
        self.assertEqual(self.post(self.vp, f"tests/{test_id}/approve/").status_code, 403)
        self.assertEqual(self.post(self.vp, f"tests/{test_id}/send-back/", {"note": "No"}).status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(Test.objects.get(pk=test_id).state, "submitted")

    def test_the_principal_writes_any_bank_and_sets_any_class(self):
        self.assertEqual(self.add(self.head, subject_id=self.english_id, level=2).status_code, 200)
        self.fill(self.head)
        test_id = self.set_test(self.head, classes=[self.jss1a_id, self.jss1b_id])

        self.assertEqual(self.post(self.head, f"tests/{test_id}/submit/").status_code, 200)
        self.assertEqual(self.post(self.head, f"tests/{test_id}/approve/").status_code, 200)

    def test_a_principal_elsewhere_is_only_what_they_are_here(self):
        """Ngozi is St Mary's principal; at Grace she is a teacher with no subject."""
        grant_membership(self.head.user, self.grace, Role.TEACHER)
        self.fill(self.grace_teacher, 2, host=THEIR_HOST, subject_id=self.grace_maths_id)

        body = self.get(self.head, "banks/", host=THEIR_HOST).json()
        self.assertEqual(body["banks"], [])
        self.assertEqual(self.get(self.head, f"banks/{self.grace_maths_id}/1/", host=THEIR_HOST).status_code, 404)
        self.assertEqual(self.add(self.head, subject_id=self.grace_maths_id, host=THEIR_HOST).status_code, 403)
        with connected_to(self.grace):
            self.assertFalse(access.reach(self.head.user, self.grace, Term.objects.get(pk=self.grace_term_id)).reads_all)


class TheAdministratorNeverReadsABankOrAQuestionTests(BanksSetUp):
    def assert_no_way_in(self, test_id, question_id, key):
        for path in (
            "banks/",
            f"banks/{self.maths_id}/1/",
            f"questions/{question_id}/",
            f"tests/{test_id}/",
            f"tests/{test_id}/preview/",
            f"pictures/{key}/full.webp",
        ):
            with self.subTest(path=path):
                response = self.get(self.admin, path)
                self.assertEqual(response.status_code, 403, path)
                self.assertNotIn(b"What is", response.content)
        for path, data in (
            (f"banks/{self.maths_id}/1/questions/", self.question(7)),
            (f"questions/{question_id}/", {**self.question(7), "version": 1}),
            (f"questions/{question_id}/retire/", {}),
            (f"questions/{question_id}/delete/", {}),
            ("tests/", self.test_body()),
            (f"tests/{test_id}/submit/", {}),
            (f"tests/{test_id}/approve/", {}),
            (f"tests/{test_id}/classes/", {"class_group_ids": [self.jss1a_id]}),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.post(self.admin, path, data).status_code, 403, path)
        upload = self.as_(self.admin).post(
            f"{BASE}banks/{self.maths_id}/1/pictures/", {"picture": BytesIO(a_png())}, HTTP_HOST=HOST
        )
        self.assertEqual(upload.status_code, 403)

    def a_test_with_a_picture(self):
        upload = self.as_(self.teacher).post(
            f"{BASE}banks/{self.maths_id}/1/pictures/", {"picture": self.png_file()}, HTTP_HOST=HOST
        )
        self.assertEqual(upload.status_code, 200, upload.content)
        key = upload.json()["key"]
        self.add(self.teacher, 50, image_key=key, image_alt="A triangle")
        test_id = self.published()
        with connected_to(self.stmarys):
            question_id = Question.objects.filter(image_key=key).get().pk
        return test_id, question_id, key

    def png_file(self):
        f = BytesIO(a_png())
        f.name = "triangle.png"
        return f

    def test_the_administrator_has_no_way_to_a_bank_or_a_question(self):
        test_id, question_id, key = self.a_test_with_a_picture()
        self.assert_no_way_in(test_id, question_id, key)

    def test_nor_once_named_exam_officer(self):
        test_id, question_id, key = self.a_test_with_a_picture()
        response = self.post(self.head, "officers/", {"membership_id": self.admin.pk})
        self.assertEqual(response.status_code, 200)
        with connected_to(self.stmarys):
            self.assertTrue(access.is_exam_officer(self.admin.user, self.stmarys))
        self.assert_no_way_in(test_id, question_id, key)

    def test_the_administrator_sees_the_list_with_no_question_in_it(self):
        test_id = self.published()
        response = self.get(self.admin, "tests/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["summaries_only"])
        self.assertFalse(body["may_set"] or body["approves"])
        self.assertEqual(body["choices"], [])
        [row] = body["tests"]
        self.assertEqual(
            (row["id"], row["title"], [c["name"] for c in row["classes"]], row["size"], row["code_set"], row["state"]),
            (test_id, "First CA test", ["JSS 1A"], 4, False, "published"),
        )
        self.assertEqual(sorted(row), sorted(
            ["id", "title", "subject", "level_name", "classes", "state", "state_label", "opens_at", "closes_at",
             "opens", "closes", "duration", "size", "code_set", "set_by"]
        ))
        text = response.content.decode()
        self.assertNotRegex(text, r"What is|correct|explanation|options|stem")


class NobodyElseReachesAnythingTests(BanksSetUp):
    def test_a_bursar_a_parent_and_a_student_get_nothing_from_any_route(self):
        test_id = self.published()
        with connected_to(self.stmarys):
            question_id = Question.objects.first().pk
        for who in (self.bursar, self.parent_user, self.student):
            name = who.user.username if isinstance(who, Membership) else who.username
            for path in ("banks/", f"banks/{self.maths_id}/1/", f"questions/{question_id}/", "tests/",
                         f"tests/{test_id}/", f"tests/{test_id}/preview/"):
                with self.subTest(who=name, path=path):
                    response = self.get(who, path)
                    self.assertIn(response.status_code, (403, 404))
                    self.assertNotRegex(response.content.decode(), KEYS)
                    self.assertNotIn(b"What is", response.content)
            for path in (f"banks/{self.maths_id}/1/questions/", "tests/", f"tests/{test_id}/approve/"):
                with self.subTest(who=name, path=path):
                    self.assertIn(self.post(who, path, self.question(3)).status_code, (403, 404, 422))
        with connected_to(self.stmarys):
            self.assertEqual(Question.objects.count(), 6)

    def test_a_student_never_reaches_a_route_that_carries_a_key(self):
        """Every route a staff member reads a key through refuses a student first."""
        test_id = self.published()
        for path in (f"tests/{test_id}/", f"banks/{self.maths_id}/1/", "tests/", "banks/"):
            with self.subTest(path=path):
                response = self.get(self.student, path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(sorted(response.json()), ["detail"])


class NoAnswerKeyReachesADeviceTests(BanksSetUp):
    def test_the_paper_carries_no_key_and_no_explanation(self):
        test_id = self.published()
        response = self.get(self.teacher, f"tests/{test_id}/preview/")

        self.assertEqual(response.status_code, 200)
        self.assertNotRegex(response.content.decode(), KEYS)
        body = response.json()
        self.assertEqual(len(body["items"]), 4)
        for item in body["items"]:
            with self.subTest(item=item["number"]):
                self.assertEqual(sorted(item), ["id", "image", "image_alt", "marks", "number", "options", "stem"])
                for option in item["options"]:
                    self.assertEqual(sorted(option), ["index", "text"])
                self.assertNotIn("explanation", item)
                self.assertNotRegex(json.dumps(item), r"make \d")

    def test_for_device_reads_no_key(self):
        """`paper.SENT` is the list of what a device gets, and the answer is not on it."""
        self.assertEqual(set(paper.SENT) & {"correct_index", "explanation", "origin_question", "topic"}, set())
        test_id = self.published()
        with connected_to(self.stmarys):
            test = Test.objects.get(pk=test_id)
            items = list(TestItem.objects.filter(test=test))
            shown = paper.for_device(test, items, "seed")
        self.assertNotRegex(json.dumps(shown), KEYS)

    def test_one_seed_gives_one_order_and_marking_follows_the_original_index(self):
        test_id = self.published()
        with connected_to(self.stmarys):
            test = Test.objects.get(pk=test_id)
            items = list(TestItem.objects.filter(test=test))
            first, again = paper.for_device(test, items, "s1"), paper.for_device(test, items, "s1")
            orders = {tuple(i["id"] for i in paper.for_device(test, items, f"s{n}")["items"]) for n in range(30)}
            by_id = {i.pk: i for i in items}
        self.assertEqual(first, again)
        self.assertGreater(len(orders), 1)
        for item in first["items"]:
            texts = [o["text"] for o in sorted(item["options"], key=lambda o: o["index"])]
            self.assertEqual(texts, by_id[item["id"]].options)


class ATestKeepsTheCopyItWasSentWithTests(BanksSetUp):
    def test_editing_retiring_and_re_answering_the_bank_changes_nothing_in_the_test(self):
        ids = self.fill(count=4)
        test_id = self.set_test(count=4)
        self.post(self.teacher, f"tests/{test_id}/submit/")
        before = self.items(test_id)

        for qid in ids[:2]:
            edited = self.post(
                self.teacher, f"questions/{qid}/",
                {**self.question(99, correct_index=3, marks=5, explanation="Changed"), "version": 1},
            )
            self.assertEqual(edited.status_code, 200, edited.content)
            self.assertEqual(edited.json()["version"], 2)
        self.assertEqual(self.post(self.teacher, f"questions/{ids[2]}/retire/").status_code, 200)
        self.assertEqual(self.items(test_id), before)
        self.assertEqual(self.post(self.head, f"tests/{test_id}/approve/").status_code, 200)
        self.assertEqual(self.items(test_id), before)
        shown = self.get(self.vp, f"tests/{test_id}/").json()["items"]
        self.assertEqual([i["stem"] for i in shown], [b["stem"] for b in before])
        self.assertNotIn("What is 99 + 99?", [i["stem"] for i in shown])
        self.assertEqual({i["origin_version"] for i in shown}, {1})

    def test_the_database_refuses_an_edit_to_a_copied_question(self):
        test_id = self.published()
        with connected_to(self.stmarys):
            item = TestItem.objects.filter(test_id=test_id).first()
            with self.assertRefusedBy("a_published_item_is_frozen"), transaction.atomic():
                TestItem.objects.filter(pk=item.pk).update(correct_index=1)
            with self.assertRefusedBy("a_published_item_is_frozen"), transaction.atomic():
                TestItem.objects.filter(pk=item.pk).delete()

    def test_the_database_refuses_a_change_to_what_a_set_test_is(self):
        test_id = self.published()
        with connected_to(self.stmarys):
            for change in ({"opens_at": self.opens + timedelta(days=1)}, {"duration": 90}, {"require_pin": False, "may_send_to_ca": False}):
                with self.subTest(change=sorted(change)):
                    with self.assertRefusedBy("a_set_test_keeps_its_paper"), transaction.atomic():
                        Test.objects.filter(pk=test_id).update(**change)
            with self.assertRefusedBy("a_set_test_keeps_its_paper"), transaction.atomic():
                Test.objects.filter(pk=test_id).update(state="draft")
            with self.assertRefusedBy("a_set_tests_section_is_fixed"), transaction.atomic():
                Test.objects.get(pk=test_id).sections.update(question_count=2)
            # In SQL, past Django's own PROTECT, so it is the trigger that answers.
            with self.assertRefusedBy("a_set_test_keeps_its_paper"), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM cbt_test WHERE id = %s", [test_id])

    def test_a_draft_cannot_be_edited_once_sent_and_a_send_back_draws_again(self):
        self.fill(count=8)
        test_id = self.set_test(count=4)
        self.post(self.teacher, f"tests/{test_id}/submit/")
        refused = self.post(self.teacher, f"tests/{test_id}/", self.test_body(title="Changed"))
        self.assertEqual(refused.status_code, 422)

        self.assertEqual(self.post(self.head, f"tests/{test_id}/send-back/", {"note": ""}).status_code, 422)
        back = self.post(self.head, f"tests/{test_id}/send-back/", {"note": "Add two harder questions"})
        self.assertEqual(back.status_code, 200)
        self.assertEqual(back.json()["state"], "draft")
        self.assertEqual(self.items(test_id), [])
        self.assertEqual(self.post(self.teacher, f"tests/{test_id}/", self.test_body(title="Changed", count=6)).status_code, 200)
        self.assertEqual(self.post(self.teacher, f"tests/{test_id}/submit/").status_code, 200)
        self.assertEqual(len(self.items(test_id)), 6)


class OnlyThePrincipalApprovesAndEveryMoveIsWrittenDownTests(BanksSetUp):
    def test_the_chain_and_its_record(self):
        self.fill()
        test_id = self.set_test()
        self.assertEqual(self.post(self.head, f"tests/{test_id}/approve/").status_code, 422)  # a draft
        self.post(self.teacher, f"tests/{test_id}/submit/")
        self.assertEqual(self.post(self.teacher, f"tests/{test_id}/approve/").status_code, 403)
        self.post(self.teacher, f"tests/{test_id}/withdraw/")
        self.post(self.teacher, f"tests/{test_id}/submit/")
        approved = self.post(self.head, f"tests/{test_id}/approve/")

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["state"], "published")
        with connected_to(self.stmarys):
            moves = list(TestStateChange.objects.order_by("id").values_list("from_state", "to_state", "by_id", "note"))
            self.assertEqual(moves, [
                ("draft", "submitted", self.teacher.user.pk, ""),
                ("submitted", "draft", self.teacher.user.pk, "Withdrawn"),
                ("draft", "submitted", self.teacher.user.pk, ""),
                ("submitted", "published", self.head.user.pk, ""),
            ])
            with self.assertRefusedBy("cbt_teststatechange is append-only"), transaction.atomic():
                TestStateChange.objects.update(note="edited")
            with self.assertRefusedBy("cbt_teststatechange is append-only"), transaction.atomic():
                TestStateChange.objects.all().delete()

    def test_a_test_is_approved_only_before_it_opens(self):
        self.fill()
        test_id = self.set_test()
        self.post(self.teacher, f"tests/{test_id}/submit/")
        with connected_to(self.stmarys):
            # Its window has come while it waited (the clock moved, not the test).
            from unittest import mock

            later = self.opens + timedelta(minutes=1)
            with mock.patch("cbt.setting.timezone.now", return_value=later):
                with self.assertRaisesRegex(setting.Refused, "Send it back"):
                    setting.approve_as(self.head.user, self.stmarys, test_id)
            self.assertEqual(Test.objects.get(pk=test_id).state, "submitted")

    def test_changing_a_published_tests_classes_is_logged(self):
        self.fill(self.head)
        test_id = self.set_test(self.head)
        self.post(self.head, f"tests/{test_id}/submit/")
        self.post(self.head, f"tests/{test_id}/approve/")
        changed = self.post(self.head, f"tests/{test_id}/classes/", {"class_group_ids": [self.jss1b_id]})

        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.json()["class_group_ids"], [self.jss1b_id])
        with connected_to(self.stmarys):
            log = list(TestAudienceChange.objects.order_by("id").values_list("class_group_name", "kind", "test_state", "by_id"))
            self.assertEqual(log, [("JSS 1B", "added", "published", self.head.user.pk), ("JSS 1A", "removed", "published", self.head.user.pk)])
            with self.assertRefusedBy("cbt_testaudiencechange is append-only"), transaction.atomic():
                TestAudienceChange.objects.all().delete()
        self.assertEqual(self.post(self.teacher, f"tests/{test_id}/classes/", {"class_group_ids": [self.jss1a_id, self.jss1b_id]}).status_code, 404)

    def test_a_test_without_the_exam_pin_never_sends_to_ca(self):
        self.fill()
        test_id = self.set_test(require_pin=False)
        with connected_to(self.stmarys):
            test = Test.objects.get(pk=test_id)
            self.assertEqual((test.require_pin, test.may_send_to_ca), (False, False))
            with self.assertRefusedBy("a_test_without_the_exam_pin_never_sends_to_ca"), transaction.atomic():
                Test.objects.filter(pk=test_id).update(may_send_to_ca=True)


class OneSchoolsBanksAndTestsAreNeverAnothersTests(BanksSetUp):
    def test_equal_ids_at_two_schools_reach_only_their_own(self):
        mine = self.published()
        self.fill(self.grace_teacher, 6, host=THEIR_HOST, subject_id=self.grace_maths_id)
        body = self.test_body(classes=[self.grace_group_id], subject_id=self.grace_maths_id, title="Grace's own")
        theirs = self.post(self.grace_teacher, "tests/", body, host=THEIR_HOST).json()["id"]
        self.assertEqual(mine, theirs)
        with connected_to(self.grace):
            Question.objects.filter(pk=1).update(stem="Grace's first question")

        self.assertEqual(self.get(self.grace_teacher, f"tests/{theirs}/", host=THEIR_HOST).json()["title"], "Grace's own")
        self.assertEqual(self.get(self.teacher, f"tests/{mine}/").json()["title"], "First CA test")
        self.assertEqual(self.get(self.teacher, "questions/1/").json()["stem"], "What is 1 + 1?")
        self.assertEqual(self.get(self.grace_teacher, "questions/1/", host=THEIR_HOST).json()["stem"], "Grace's first question")
        # Grace's principal at Grace sees Grace's tests alone.
        titles = [t["title"] for t in self.get(self.their_head, "tests/", host=THEIR_HOST).json()["tests"]]
        self.assertEqual(titles, ["Grace's own"])
        # And a St Mary's login has no way into Grace's at all.
        self.assertIn(self.get(self.teacher, "banks/", host=THEIR_HOST).status_code, (403, 404))

    def test_a_picture_is_sent_only_at_its_own_school_and_to_who_reads_it(self):
        f = BytesIO(a_png())
        f.name = "x.png"
        upload = self.as_(self.teacher).post(f"{BASE}banks/{self.maths_id}/1/pictures/", {"picture": f}, HTTP_HOST=HOST)
        self.assertEqual(upload.status_code, 200, upload.content)
        key = upload.json()["key"]
        self.assertEqual(upload.json()["state"], "ready")
        self.add(self.teacher, 1, image_key=key, image_alt="A red square")

        self.assertEqual(self.get(self.teacher, f"pictures/{key}/full.webp").status_code, 200)
        self.assertEqual(self.get(self.vp, f"pictures/{key}/full.webp").status_code, 200)
        self.assertEqual(self.get(self.tayo, f"pictures/{key}/full.webp").status_code, 404)
        self.assertEqual(self.get(self.grace_teacher, f"pictures/{key}/full.webp", host=THEIR_HOST).status_code, 404)
        self.assertEqual(self.get(self.their_head, f"pictures/{key}/full.webp", host=THEIR_HOST).status_code, 404)
        # Nor on the generic files route, to anybody.
        for who in (self.head, self.admin):
            with self.subTest(who=who.user.username):
                response = self.as_(who).get(f"/files/{key}/full.webp", HTTP_HOST=HOST)
                connection.set_schema_to_public()
                self.assertEqual(response.status_code, 404)

    def test_a_question_needs_a_description_for_its_picture(self):
        f = BytesIO(a_png())
        f.name = "x.png"
        key = self.as_(self.teacher).post(f"{BASE}banks/{self.maths_id}/1/pictures/", {"picture": f}, HTTP_HOST=HOST).json()["key"]
        refused = self.add(self.teacher, 1, image_key=key, image_alt="")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("Describe the picture", refused.json()["detail"])
        # Another school's key is not a picture here.
        their = self.add(self.grace_teacher, 1, subject_id=self.grace_maths_id, host=THEIR_HOST, image_key=key, image_alt="x")
        self.assertEqual(their.status_code, 422)

    def test_the_reach_is_read_only_on_the_schools_own_connection(self):
        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
            self.assertEqual(access.reach(self.their_head.user, self.grace, term), access.NOBODY)
            self.assertTrue(access.reach(self.head.user, self.stmarys, term).reads_all)


class QuestionsArePlainAndCheckedTests(BanksSetUp):
    def test_what_a_question_refuses(self):
        cases = (
            ({"stem": "   "}, "cannot be empty"),
            ({"options": ["a", "b", "c"]}, "four options"),
            ({"options": ["a", "b", "c", "A"]}, "say the same thing"),
            ({"correct_index": 4}, "correct answer"),
            ({"marks": 0}, "1 to 10 marks"),
            ({"stem": "x" * 1001}, "at most 1000"),
        )
        for over, sentence in cases:
            with self.subTest(over=sorted(over)):
                response = self.add(self.teacher, **over)
                self.assertEqual(response.status_code, 422)
                self.assertIn(sentence, response.json()["detail"])
        with connected_to(self.stmarys):
            self.assertEqual(Question.objects.count(), 0)

    def test_markup_is_kept_as_text_and_control_characters_go(self):
        response = self.add(self.teacher, stem="<b>Bold</b>\x07 x² + H₂O\r\nnext line")
        self.assertEqual(response.json()["stem"], "<b>Bold</b> x² + H₂O\nnext line")

    def test_an_edit_over_somebody_elses_is_refused(self):
        qid = self.fill(count=1)[0]
        self.assertEqual(self.post(self.head, f"questions/{qid}/", {**self.question(5), "version": 1}).status_code, 200)
        stale = self.post(self.teacher, f"questions/{qid}/", {**self.question(6), "version": 1})
        self.assertEqual(stale.status_code, 422)
        self.assertIn("Ngozi Eze saved this question", stale.json()["detail"])

    def test_a_used_question_is_retired_not_deleted(self):
        self.published()
        with connected_to(self.stmarys):
            used = TestItem.objects.first().origin_question_id
            unused = Question.objects.exclude(test_items__isnull=False).first().pk
        self.assertEqual(self.post(self.teacher, f"questions/{used}/delete/").status_code, 422)
        self.assertEqual(self.post(self.teacher, f"questions/{unused}/delete/").status_code, 200)
        with connected_to(self.stmarys):
            self.assertTrue(Question.objects.filter(pk=used).exists())
            self.assertFalse(Question.objects.filter(pk=unused).exists())

    def test_a_test_draws_only_questions_in_use_and_says_when_there_are_too_few(self):
        ids = self.fill(count=4)
        self.post(self.teacher, f"questions/{ids[0]}/retire/")
        test_id = self.set_test(count=4)
        refused = self.post(self.teacher, f"tests/{test_id}/submit/")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("3 questions in use", refused.json()["detail"])


class TheRoutesCostWhatTheyCostTests(BanksSetUp):
    def test_the_test_list_is_a_fixed_number_of_statements(self):
        """For the principal and for a teacher, one test or three."""
        self.fill(self.teacher, 8)
        counts = {"principal": [], "teacher": []}
        for n in (1, 3):
            while True:
                with connected_to(self.stmarys):
                    have = Test.objects.count()
                if have >= n:
                    break
                self.set_test(self.teacher)
            for who in (self.head, self.teacher):
                self.client.force_login(who.user)
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(f"{BASE}tests/", HTTP_HOST=HOST)
                connection.set_schema_to_public()
                self.assertEqual(len(response.json()["tests"]), n)
                counts[who.role].append(len(queries))
        for role, (one, three) in counts.items():
            with self.subTest(role=role):
                self.assertEqual(one, three)


class NoQuestionIsSeededTests(BanksSetUp):
    def test_cbt_migrations_write_no_question(self):
        from pathlib import Path

        for migration in (Path(__file__).resolve().parent.parent / "migrations").glob("0*.py"):
            with self.subTest(migration=migration.name):
                text = migration.read_text()
                self.assertNotRegex(text, r"(?i)\bINSERT\s+INTO|RunPython|bulk_create")
        with connected_to(self.stmarys):
            self.assertEqual((QuestionBank.objects.count(), Question.objects.count()), (0, 0))
