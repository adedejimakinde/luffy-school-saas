"""Attendance counts school days, not marks: audit finding G-11.

One mark per child per register and one register per class per day never meant
one mark per child per **day**. A child marked in JSS 1A and then on JSS 1B's
list for the same day (moved that morning, or JSS 1B's teacher filling in last
week) collected two marks for one day, and the card counted both.

Two things hold it now, and each has its control:

- `take_register()` does not write the second mark: the child is left unmarked
  in the second class and named (`marked_elsewhere`);
- `summary.for_term()` counts a day once whatever the tables hold, with the
  mark written last as the day's answer, so a double mark written before this
  (staged here directly) is not counted twice either.

St Mary's JSS 1A and JSS 1B; Grace Academy for the second school.
"""

from datetime import date, timedelta

from django.utils import timezone

from academics import services as academics
from attendance import services, summary
from attendance.models import AttendanceMark, AttendanceStatus, Register
from attendance.tests.fixtures import A_SCHOOL_DAY
from results.models import ReleasedCard
from results import services as chain
from results import unmarked
from results.tests.fixtures import HOST, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

NEXT_DAY = date(2025, 9, 18)


class DaysSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        self.tunde = self.children["tunde"]

    def counted(self, child=None, school=None, term=None):
        child = child or self.tunde
        with connected_to(school or self.stmarys):
            found = summary.for_term(term or self.term, [child.pk])[child.pk]
        return found.present, found.absent

    def put(self, class_id, on=A_SCHOOL_DAY, absent=(), who=None, host=HOST, term_id=None):
        self.client.force_login((who or self.teacher).user)
        return self.client.put(
            f"/api/attendance/classes/{class_id}/terms/{term_id or self.term_id}/{on}/",
            data={"absent_ids": list(absent)},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def double_mark(self, first, second, later_first=False):
        """Two registers for one day, both marking Tunde, written directly:
        the state the tables could already be in. `second`'s mark is the later
        one unless `later_first`."""
        with connected_to(self.stmarys):
            marks = []
            for group, status in ((self.jss1a, first), (self.jss1b, second)):
                register = Register.objects.create(class_group=group, term=self.term, taken_on=A_SCHOOL_DAY)
                marks.append(
                    AttendanceMark.objects.create(
                        register=register, student_membership_id=self.tunde.pk, status=status
                    )
                )
            early, late = (marks[1], marks[0]) if later_first else (marks[0], marks[1])
            now = timezone.now()
            AttendanceMark.objects.filter(pk=early.pk).update(updated_at=now - timedelta(hours=1))
            AttendanceMark.objects.filter(pk=late.pk).update(updated_at=now)


class ADayCountsOnceTests(DaysSetUp):
    def test_two_marks_for_one_day_are_one_day(self):
        """The audit's reproduction, with the marks as they used to be written."""
        self.double_mark(AttendanceStatus.PRESENT, AttendanceStatus.PRESENT)

        self.assertEqual(self.counted(), (1, 0))

    def test_the_mark_written_last_is_the_days_answer(self):
        self.double_mark(AttendanceStatus.PRESENT, AttendanceStatus.ABSENT)
        self.assertEqual(self.counted(), (0, 1))

    def test_whichever_class_wrote_it(self):
        self.double_mark(AttendanceStatus.PRESENT, AttendanceStatus.ABSENT, later_first=True)
        self.assertEqual(self.counted(), (1, 0))

    def test_different_days_in_different_classes_are_both_her_term(self):
        """The control: a child who moved was marked by both classes on
        different days, and both halves still count."""
        with connected_to(self.stmarys):
            services.take_register(self.jss1a, self.term, on=A_SCHOOL_DAY)
            academics.move_student(self.jss1b, self.term, self.tunde)
            services.take_register(self.jss1b, self.term, on=NEXT_DAY, absent_ids=[self.tunde.pk])

        self.assertEqual(self.counted(), (1, 1))

    def test_the_total_cannot_pass_the_days_registers_were_taken(self):
        self.double_mark(AttendanceStatus.PRESENT, AttendanceStatus.PRESENT)
        with connected_to(self.stmarys):
            days = Register.objects.filter(term=self.term).values("taken_on").distinct().count()

        self.assertLessEqual(sum(self.counted()), days)

    def test_the_card_carries_days(self):
        """What a parent reads: released with a double mark behind it, the
        card says one day."""
        self.double_mark(AttendanceStatus.PRESENT, AttendanceStatus.PRESENT)
        with connected_to(self.stmarys):
            academics.move_student(self.jss1b, self.term, self.tunde)
            academics.assign_class_teacher(self.jss1b, self.term, self.teacher, by=self.head)
            sheet = chain.open_sheet(self.jss1b, self.term, self.head.user)
            count = unmarked.count(sheet.class_group, sheet.term)
            chain.submit(sheet, self.teacher.user, unmarked=count)
            chain.check(sheet, self.vp.user, unmarked=count)
            chain.approve(sheet, self.head.user, unmarked=count)
            chain.release(sheet, self.head.user)
            card = ReleasedCard.objects.get(student_membership_id=self.tunde.pk)

        self.assertEqual((card.days_present, card.days_absent), (1, 0))


class TheSecondClassDoesNotMarkHerAgainTests(DaysSetUp):
    def setUp(self):
        super().setUp()
        # Monday in JSS 1A, with Tunde absent; then the office moves him.
        self.assertEqual(self.put(self.jss1a_id, absent=[self.tunde.pk]).status_code, 200)
        with connected_to(self.stmarys):
            academics.move_student(self.jss1b, self.term, self.tunde)

    def test_the_new_class_filling_in_that_day_leaves_her_unmarked_and_says_so(self):
        response = self.put(self.jss1b_id)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["marked_elsewhere"], [self.tunde.pk])
        self.assertEqual(body["present"], [self.bimpe.pk])
        self.assertNotIn(self.tunde.pk, body["appeared"])
        with connected_to(self.stmarys):
            marks = list(
                AttendanceMark.objects.filter(student_membership_id=self.tunde.pk).values_list(
                    "register__class_group_id", "status"
                )
            )
        # One mark for the day, and it is what JSS 1A saw.
        self.assertEqual(marks, [(self.jss1a_id, "absent")])
        self.assertEqual(self.counted(), (0, 1))

    def test_marking_her_absent_there_writes_nothing_for_her_either(self):
        body = self.put(self.jss1b_id, absent=[self.tunde.pk]).json()

        self.assertEqual(body["marked_elsewhere"], [self.tunde.pk])
        self.assertEqual(body["absent"], [])
        self.assertEqual(self.counted(), (0, 1))

    def test_with_a_base_she_is_left_out_the_same_way(self):
        self.client.force_login(self.teacher.user)
        response = self.client.put(
            f"/api/attendance/classes/{self.jss1b_id}/terms/{self.term_id}/{A_SCHOOL_DAY}/",
            data={
                "absent_ids": [],
                "shown_ids": [self.tunde.pk, self.bimpe.pk],
                "base": {"present_ids": [], "absent_ids": []},
            },
            content_type="application/json",
            HTTP_HOST=HOST,
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["marked_elsewhere"], [self.tunde.pk])
        self.assertEqual(self.counted(), (0, 1))

    def test_the_next_day_she_is_the_new_classs_to_mark(self):
        body = self.put(self.jss1b_id, on=NEXT_DAY).json()

        self.assertEqual(body["marked_elsewhere"], [])
        self.assertIn(self.tunde.pk, body["present"])
        self.assertEqual(self.counted(), (1, 1))

    def test_amending_the_same_classs_own_register_is_not_elsewhere(self):
        """The control on the exclusion: a class's own earlier mark is the mark
        it is amending, not another class's."""
        body = self.put(self.jss1b_id, on=NEXT_DAY).json()
        again = self.put(self.jss1b_id, on=NEXT_DAY, absent=[self.tunde.pk]).json()

        self.assertEqual((body["marked_elsewhere"], again["marked_elsewhere"]), ([], []))
        self.assertEqual(again["absent"], [self.tunde.pk])


class TwoSchoolsTests(DaysSetUp):
    def test_another_schools_register_for_the_same_day_is_not_elsewhere(self):
        """Grace's JSS 1A may share St Mary's class id and child ids are from
        one table; its register is in its own schema and holds nobody back."""
        self.put(self.jss1a_id)

        response = self.put(
            self.grace_group_id, who=self.grace_teacher, host=THEIR_HOST, term_id=self.grace_term_id
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["marked_elsewhere"], [])
        self.assertEqual(response.json()["present"], [self.grace_child.pk])
        with connected_to(self.grace):
            counted = summary.for_term(self.grace_term, [self.grace_child.pk, self.tunde.pk])
        self.assertEqual((counted[self.grace_child.pk].present, counted[self.tunde.pk].marked), (1, 0))
