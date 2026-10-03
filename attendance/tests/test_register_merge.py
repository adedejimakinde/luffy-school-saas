"""A register merged child by child against what the teacher was shown.

`docs/offline.md` slice S6, D4, and correctness requirements 1, 2 and 3. A
register sent with a `base` writes only the children the teacher changed, and
for each of those only if the school still has what the teacher was shown.

Every story runs at two schools, St Mary's and Grace, each with two children in
a class, a teacher and an office. The two are told apart throughout: what
happens to one school's register must leave the other's alone.
"""

import json
import uuid

from django.db import connection

from academics import services as academics
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from attendance.models import AttendanceMark, Register
from attendance.tests.fixtures import A_SCHOOL_DAY
from gradebook.tests.fixtures import PASSWORD, MarkingSetUp
from schools.models import Domain
from schools.tests.tenants import connected_to

HOST = "st-marys.testserver"
GRACE_HOST = "grace.testserver"
ABSENT, PRESENT = "absent", "present"


class MergeSetUp(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=GRACE_HOST, is_primary=True)
        self.grace_office = grant_membership(
            User.objects.create_user("bola", PASSWORD, full_name="Bola Ade"), self.grace, Role.PRINCIPAL
        )
        second = enroll_student(
            User.objects.create_user("ngozi.c", PASSWORD, full_name="Ngozi Okafor"), self.grace
        )
        with connected_to(self.grace):
            academics.place_student(self.grace_group, self.grace_term, second)
        self.schools = [
            dict(name="St Mary's", host=HOST, school=self.stmarys, teacher=self.teacher,
                 office=self.head, group=self.jss1a_id, term=self.term_id,
                 roster=sorted(c.pk for c in (self.children[h] for h in ("ada", "emeka", "bisi", "tunde")))),
            dict(name="Grace", host=GRACE_HOST, school=self.grace, teacher=self.grace_teacher,
                 office=self.grace_office, group=self.grace_group_id, term=self.grace_term_id,
                 roster=sorted([self.grace_child.pk, second.pk])),
        ]

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def take(self, s, who, absent, *, base=None, key=None):
        self.client.force_login(who.user)
        body = {"absent_ids": absent, "shown_ids": s["roster"]}
        if base is not None:
            body["base"] = {
                "absent_ids": [c for c, v in base.items() if v == ABSENT],
                "present_ids": [c for c, v in base.items() if v == PRESENT],
            }
        if key is not None:
            body["key"] = str(key)
        return self.client.put(
            f"/api/attendance/classes/{s['group']}/terms/{s['term']}/{A_SCHOOL_DAY}/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=s["host"],
        )

    def marks(self, s):
        with connected_to(s["school"]):
            return dict(
                AttendanceMark.objects.filter(
                    register__class_group_id=s["group"], register__taken_on=A_SCHOOL_DAY
                ).values_list("student_membership_id", "status")
            )

    def everyone(self, s, status):
        return {c: status for c in s["roster"]}


class NothingTheTeacherDidNotTouchIsWrittenTests(MergeSetUp):
    """Requirement 3. 8am: the office takes the register, everybody present, and
    the teacher's phone opens it (offline from here on). The teacher marks the
    first child absent. 10am: the office marks the second child absent. 4pm:
    the teacher's register arrives."""

    def story(self, s):
        first, second = s["roster"][0], s["roster"][1]
        self.assertEqual(self.take(s, s["office"], []).status_code, 200)
        shown = self.everyone(s, PRESENT)
        self.assertEqual(self.take(s, s["office"], [second]).status_code, 200)
        return first, second, self.take(s, s["teacher"], [first], base=shown)

    def test_the_offices_correction_stands_and_the_teachers_change_lands(self):
        for s in self.schools:
            with self.subTest(school=s["name"]):
                first, second, answer = self.story(s)

                self.assertEqual(answer.status_code, 200, answer.content)
                marks = self.marks(s)
                self.assertEqual(marks[first], ABSENT, "the teacher's change")
                self.assertEqual(marks[second], ABSENT, "the office's correction, untouched")
                body = answer.json()
                self.assertEqual(body["absent"], [first])
                self.assertEqual(body["present"], [])
                self.assertIn(second, body["untouched"])
                self.assertEqual(body["conflicts"], [])

    def test_untouched_marks_keep_who_wrote_them(self):
        for s in self.schools:
            with self.subTest(school=s["name"]):
                _, second, _ = self.story(s)
                with connected_to(s["school"]):
                    mark = AttendanceMark.objects.get(
                        register__class_group_id=s["group"], student_membership_id=second
                    )
                self.assertEqual(mark.marked_by_id, s["office"].user.pk)

    def test_without_a_base_the_late_register_would_have_undone_the_office(self):
        """The control for the test above, in the same story: the online
        behaviour, a whole-register amend, puts the second child back."""
        for s in self.schools:
            with self.subTest(school=s["name"]):
                first, second = s["roster"][0], s["roster"][1]
                self.take(s, s["office"], [])
                self.take(s, s["office"], [second])
                self.take(s, s["teacher"], [first])
                self.assertEqual(self.marks(s)[second], PRESENT)


class ChangedByBothIsAConflictForThatChildOnlyTests(MergeSetUp):
    """Requirement 2. 8am: the teacher opens a register nobody has taken, marks
    the first child absent and leaves the rest present, offline. 10am: the
    office takes the register with everybody present. 4pm: it arrives."""

    def story(self, s):
        shown = self.everyone(s, None)
        self.assertEqual(self.take(s, s["office"], []).status_code, 200)
        return self.take(s, s["teacher"], [s["roster"][0]], base=shown)

    def test_the_child_both_answered_is_a_conflict_and_is_not_written(self):
        for s in self.schools:
            with self.subTest(school=s["name"]):
                answer = self.story(s)
                first = s["roster"][0]

                self.assertEqual(answer.status_code, 200, answer.content)
                [conflict] = answer.json()["conflicts"]
                self.assertEqual(conflict["student_membership_id"], first)
                self.assertEqual((conflict["yours"], conflict["was"], conflict["now"]), (ABSENT, None, PRESENT))
                self.assertIsNotNone(conflict["since"])
                self.assertEqual(self.marks(s)[first], PRESENT, "the office's answer stands")

    def test_the_children_they_agree_on_are_not_conflicts(self):
        for s in self.schools:
            with self.subTest(school=s["name"]):
                body = self.story(s).json()
                self.assertEqual(body["already"], s["roster"][1:])
                self.assertEqual(body["present"] + body["absent"], [])

    def test_choosing_the_teachers_answer_is_a_deliberate_write_against_the_school(self):
        """D5: the teacher chooses. Choosing theirs sends that child again with
        the school's answer as the base, and it lands."""
        for s in self.schools:
            with self.subTest(school=s["name"]):
                self.story(s)
                first = s["roster"][0]
                again = self.take(s, s["teacher"], [first], base=self.everyone(s, PRESENT))
                self.assertEqual(again.status_code, 200)
                self.assertEqual(self.marks(s)[first], ABSENT)


class ANewRegisterIsTakenWholeTests(MergeSetUp):
    def test_a_register_nobody_took_marks_every_child_shown(self):
        """An empty base is every child unmarked, so every answer is a change."""
        for s in self.schools:
            with self.subTest(school=s["name"]):
                first = s["roster"][0]
                answer = self.take(s, s["teacher"], [first], base=self.everyone(s, None))
                self.assertEqual(answer.status_code, 200)
                self.assertEqual(self.marks(s), {**self.everyone(s, PRESENT), first: ABSENT})

    def test_a_merge_that_writes_nothing_leaves_no_empty_register(self):
        """The register was discarded after the teacher opened it: every child
        they changed meets nothing, which is not what they were shown."""
        for s in self.schools:
            with self.subTest(school=s["name"]):
                shown = self.everyone(s, PRESENT)
                answer = self.take(s, s["teacher"], [s["roster"][0]], base=shown)

                self.assertEqual(len(answer.json()["conflicts"]), 1)
                with connected_to(s["school"]):
                    self.assertFalse(
                        Register.objects.filter(class_group_id=s["group"], taken_on=A_SCHOOL_DAY).exists()
                    )


class AMergedRegisterReplaysOnceTests(MergeSetUp):
    """Requirement 1 with a base: the replay is answered from the receipt."""

    def test_a_replay_after_the_office_moved_on_changes_nothing(self):
        for s in self.schools:
            with self.subTest(school=s["name"]):
                key = uuid.uuid4()
                first, second = s["roster"][0], s["roster"][1]
                self.take(s, s["office"], [])
                shown = self.everyone(s, PRESENT)
                landed = self.take(s, s["teacher"], [first], base=shown, key=key)
                self.take(s, s["office"], [second])  # an amend of everybody
                replayed = self.take(s, s["teacher"], [first], base=shown, key=key)

                self.assertEqual(replayed.json(), landed.json())
                self.assertEqual(self.marks(s), {**self.everyone(s, PRESENT), second: ABSENT})


class OneSchoolsMergeLeavesTheOtherAloneTests(MergeSetUp):
    def test_grace_is_untouched_by_st_marys(self):
        marys, grace = self.schools
        self.take(grace, grace["office"], [grace["roster"][1]])
        before = self.marks(grace)

        self.take(marys, marys["teacher"], [marys["roster"][0]], base=self.everyone(marys, None))

        self.assertEqual(self.marks(grace), before)
