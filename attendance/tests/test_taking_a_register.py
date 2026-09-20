"""Taking a register: the default, the amendment, and the three kinds of drift.

The interaction under test is a teacher with a phone, a class of forty-five and
thirty seconds. Everything here is a property of that: the roster arrives
present, only the absentees are sent, a second submit amends rather than
duplicating, and a roster that moved under the screen produces a report rather
than a refusal.

The one rule that could not be a database constraint is tested here too — a
register's date inside its term — because `services.DayOutsideTheTerm` is where
it had to live once a `CheckConstraint` proved unable to span two tables.
"""

from datetime import date

from attendance import services
from attendance.models import AttendanceMark, AttendanceStatus, Register
from academics import services as academics
from schools.tests.tenants import connected_to

from .fixtures import A_SCHOOL_DAY, RegisterSetUp


class TheDefaultIsPresentTests(RegisterSetUp):
    def test_an_empty_submission_marks_the_whole_roster_present(self):
        """Not an empty register — a register saying everybody was there.

        This is the case the thirty-second budget is built around: a teacher
        with nobody away taps nothing and submits.
        """
        with connected_to(self.stmarys):
            taken = services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )

            self.assertEqual(taken.present, self.everyone())
            self.assertEqual(taken.absent, [])
            self.assertEqual(taken.marked, 4)
            self.assertEqual(
                set(services.marks_in(taken.register).values()), {"present"}
            )

    def test_only_the_tapped_children_are_absent(self):
        with connected_to(self.stmarys):
            away = self.ids("ada", "tunde")
            taken = services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                absent_ids=away,
                by=self.teacher,
            )

            self.assertEqual(taken.absent, away)
            self.assertEqual(taken.present, self.ids("bisi", "emeka"))
            marks = services.marks_in(taken.register)
            self.assertEqual(
                {sid for sid, status in marks.items() if status == "absent"},
                set(away),
            )

    def test_the_marker_is_stamped_on_the_register_and_on_every_mark(self):
        with connected_to(self.stmarys):
            taken = services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            self.assertEqual(taken.register.taken_by_id, self.teacher.pk)
            self.assertEqual(
                set(
                    AttendanceMark.objects.filter(
                        register=taken.register
                    ).values_list("marked_by_id", flat=True)
                ),
                {self.teacher.pk},
            )


class ASecondSubmitAmendsTests(RegisterSetUp):
    def test_submitting_twice_does_not_make_two_registers(self):
        """A slow first answer is not a second register.

        `one_register_per_group_per_period` forbids one; this asserts the
        service produces the amendment rather than the IntegrityError.
        """
        with connected_to(self.stmarys):
            first = services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            second = services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )

            self.assertEqual(first.register.pk, second.register.pk)
            self.assertEqual(Register.objects.count(), 1)
            self.assertEqual(AttendanceMark.objects.count(), 4)

    def test_a_correction_changes_the_status_rather_than_adding_a_row(self):
        with connected_to(self.stmarys):
            ada = self.children["ada"].pk
            services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                absent_ids=[ada],
                by=self.teacher,
            )
            taken = services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.head
            )

            self.assertEqual(AttendanceMark.objects.count(), 4)
            self.assertEqual(services.marks_in(taken.register)[ada], "present")

    def test_an_unchanged_resubmit_does_not_touch_the_rows(self):
        """Re-submitting an unchanged register is not re-marking the class.

        `updated_at` is an audit column, and forty-five rows bumped by a
        double-tap would say somebody went back over the register when nobody
        did.
        """
        with connected_to(self.stmarys):
            taken = services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            before = sorted(
                AttendanceMark.objects.values_list(
                    "id", "updated_at", "marked_by_id"
                )
            )
            # A *different* person re-submits, so a row that was rewritten shows
            # it twice over: `updated_at` moves, and `marked_by_id` becomes the
            # principal. Asserting both is what makes this test fail when the
            # "only what changed" branch is removed — the first draft compared
            # `updated_at` alone and survived that control, because
            # `bulk_update()` does not run `pre_save` and the column never moved.
            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.head
            )
            after = sorted(
                AttendanceMark.objects.values_list(
                    "id", "updated_at", "marked_by_id"
                )
            )

            self.assertEqual(before, after)
            self.assertEqual(taken.register.pk, Register.objects.get().pk)


class AnAmendmentIsVisibleInTheAuditTests(RegisterSetUp):
    """The positive half of "only what changed is touched".

    `bulk_update()` does not run `pre_save`, so `auto_now` on `updated_at` is a
    silent no-op there and the column has to be set by hand. This is the test
    that says the column actually moves; `test_an_unchanged_resubmit_does_not_touch_the_rows`
    is the one that says it moves only when something did.
    """

    def test_a_corrected_mark_records_when_and_by_whom(self):
        with connected_to(self.stmarys):
            ada = self.children["ada"].pk
            services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                absent_ids=[ada],
                by=self.teacher,
            )
            before = AttendanceMark.objects.get(student_membership_id=ada)

            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.head
            )
            after = AttendanceMark.objects.get(student_membership_id=ada)

            self.assertGreater(after.updated_at, before.updated_at)
            self.assertEqual(after.marked_by_id, self.head.pk)
            self.assertEqual(before.marked_by_id, self.teacher.pk)

    def test_a_child_nobody_corrected_is_left_where_she_was(self):
        """The same amendment, seen from the row it should not have touched."""
        with connected_to(self.stmarys):
            emeka = self.children["emeka"].pk
            services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                absent_ids=self.ids("ada"),
                by=self.teacher,
            )
            before = AttendanceMark.objects.get(student_membership_id=emeka)

            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.head
            )
            after = AttendanceMark.objects.get(student_membership_id=emeka)

            self.assertEqual(after.updated_at, before.updated_at)
            self.assertEqual(after.marked_by_id, self.teacher.pk)


class TheRosterMovedUnderTheScreenTests(RegisterSetUp):
    def test_a_child_who_appeared_after_the_screen_loaded_is_not_marked(self):
        """Nobody looked at her, so nothing is claimed about her.

        Marking her present would invent an observation, which is the one thing
        `AttendanceStatus` exists to refuse. She is reported instead.
        """
        with connected_to(self.stmarys):
            shown = self.ids("ada", "emeka", "bisi")
            tunde = self.children["tunde"].pk

            taken = services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                shown_ids=shown,
                by=self.teacher,
            )

            self.assertEqual(taken.appeared, [tunde])
            self.assertNotIn(tunde, services.marks_in(taken.register))
            self.assertEqual(taken.marked, 3)

    def test_an_absentee_who_has_left_the_group_is_refused_alone(self):
        """One child the office moved does not cost the teacher the register."""
        with connected_to(self.stmarys):
            tunde = self.children["tunde"]
            academics.move_student(self.jss1b, self.term, tunde)

            taken = services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                absent_ids=[tunde.pk],
                by=self.teacher,
            )

            self.assertEqual(taken.not_on_the_roster, [tunde.pk])
            self.assertNotIn(tunde.pk, services.marks_in(taken.register))
            self.assertEqual(taken.marked, 3)

    def test_a_child_the_screen_showed_who_has_since_left_is_not_marked(self):
        with connected_to(self.stmarys):
            tunde = self.children["tunde"]
            shown = self.everyone()
            academics.move_student(self.jss1b, self.term, tunde)

            taken = services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                shown_ids=shown,
                by=self.teacher,
            )

            self.assertNotIn(tunde.pk, taken.present)
            self.assertNotIn(tunde.pk, services.marks_in(taken.register))

    def test_a_caller_with_no_screen_takes_the_roster_as_it_stands(self):
        """`shown_ids=None` is the right default for an import or a shell."""
        with connected_to(self.stmarys):
            taken = services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            self.assertEqual(taken.appeared, [])
            self.assertEqual(taken.marked, 4)


class AMovedChildKeepsHerHistoryTests(RegisterSetUp):
    """Correctness requirement 2, and the reason the group is on the register.

    `ClassPlacement` is current state: `move_student()` mutates the row and
    leaves nothing saying where she sat before. If a mark resolved its group
    through the placement, this child's September register would be filed under
    the class she joined in October.
    """

    def test_marks_stay_with_the_group_that_took_them_after_a_move(self):
        with connected_to(self.stmarys):
            tunde = self.children["tunde"]
            services.take_register(
                self.jss1a,
                self.term,
                on=A_SCHOOL_DAY,
                absent_ids=[tunde.pk],
                by=self.teacher,
            )

            academics.move_student(self.jss1b, self.term, tunde)

            mark = AttendanceMark.objects.get(student_membership_id=tunde.pk)
            self.assertEqual(services.group_that_marked(mark), self.jss1a_id)
            self.assertEqual(mark.status, AttendanceStatus.ABSENT)
            self.assertEqual(
                academics.placement_of(tunde.pk, self.term).class_group_id,
                self.jss1b_id,
            )


class TheDayMustBeInsideTheTermTests(RegisterSetUp):
    """The rule no check constraint can hold, because it spans two tables."""

    def test_a_day_before_the_term_starts_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.DayOutsideTheTerm) as caught:
                services.take_register(
                    self.jss1a, self.term, on=date(2025, 9, 1), by=self.teacher
                )
            self.assertIn("2025-09-01", str(caught.exception))
            self.assertEqual(Register.objects.count(), 0)

    def test_a_day_after_the_term_ends_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.DayOutsideTheTerm):
                services.take_register(
                    self.jss1a, self.term, on=date(2026, 1, 20), by=self.teacher
                )
            self.assertEqual(Register.objects.count(), 0)

    def test_both_endpoints_are_school_days(self):
        with connected_to(self.stmarys):
            services.take_register(
                self.jss1a, self.term, on=self.term.starts_on, by=self.teacher
            )
            services.take_register(
                self.jss1a, self.term, on=self.term.ends_on, by=self.teacher
            )
            self.assertEqual(Register.objects.count(), 2)


class AGroupWithNobodyInItTests(RegisterSetUp):
    def test_an_empty_group_has_no_register_to_take(self):
        """Not an empty register: that would record marking nothing.

        A row saying somebody marked and nobody was there is indistinguishable
        from the admin gap `days_open` exists to measure.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(services.NoRoster) as caught:
                services.take_register(
                    self.jss1b, self.term, on=A_SCHOOL_DAY, by=self.teacher
                )
            self.assertIn("JSS 1B", str(caught.exception))
            self.assertEqual(Register.objects.count(), 0)


class DiscardingARegisterTests(RegisterSetUp):
    def test_a_register_filed_against_the_wrong_slot_goes_with_its_marks(self):
        with connected_to(self.stmarys):
            services.take_register(
                self.jss1a, self.term, on=A_SCHOOL_DAY, by=self.teacher
            )
            self.assertTrue(
                services.discard_register(self.jss1a, A_SCHOOL_DAY, 1)
            )
            self.assertEqual(Register.objects.count(), 0)
            self.assertEqual(AttendanceMark.objects.count(), 0)

    def test_discarding_nothing_is_false_rather_than_an_error(self):
        with connected_to(self.stmarys):
            self.assertFalse(
                services.discard_register(self.jss1a, A_SCHOOL_DAY, 1)
            )


class WhoMayTakeARegisterTests(RegisterSetUp):
    def test_a_teacher_a_principal_and_an_administrator_may(self):
        self.assertTrue(
            services.can_mark_attendance(self.teacher.user, self.stmarys)
        )
        self.assertTrue(services.can_mark_attendance(self.head.user, self.stmarys))

    def test_a_bursar_may_not(self):
        """A bursar keeps the books and does not mark."""
        self.assertFalse(
            services.can_mark_attendance(self.bursar.user, self.stmarys)
        )

    def test_a_student_may_not_mark_the_register_she_appears_in(self):
        self.assertFalse(
            services.can_mark_attendance(self.children["ada"].user, self.stmarys)
        )

    def test_a_teacher_at_another_school_may_not(self):
        self.assertFalse(
            services.can_mark_attendance(self.teacher.user, self.grace)
        )

    def test_the_refusal_names_who_may(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToMarkAttendance) as caught:
                services.take_register_as(
                    self.bursar.user,
                    self.jss1a,
                    self.term,
                    school=self.stmarys,
                    on=A_SCHOOL_DAY,
                )
            self.assertIn("teacher", str(caught.exception))
            self.assertEqual(Register.objects.count(), 0)
