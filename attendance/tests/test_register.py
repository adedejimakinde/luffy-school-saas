"""The two tables, and the three things Postgres refuses to store.

Every rule below is a database constraint rather than a `clean()` check, for the
reason `docs/tenancy.md` gives about the one-current-term index and
`academics.tests.test_term` repeats: a rule that lives only in Python is a rule
a data import, a shell session or a future service function walks straight
around.

The fourth rule — a register's date falls inside its term — is deliberately
**not** here, because it cannot be. A `CheckConstraint` sees one row of one
table and this one spans two, so it lives in `services.DayOutsideTheTerm` and is
tested in `test_taking_a_register`. Recorded here so the absence reads as a
decision rather than an oversight, which is the shape `gradebook.Score.Meta`
already uses for the same kind of gap.
"""

from datetime import date

from django.db import IntegrityError, connection, transaction

from attendance.models import AttendanceMark, AttendanceStatus, Register
from schools.tests.tenants import connected_to

from .fixtures import A_SCHOOL_DAY, RegisterSetUp


class RegisterRecordTests(RegisterSetUp):
    def test_a_register_records_the_group_the_term_the_day_and_the_period(self):
        with connected_to(self.stmarys):
            register = Register.objects.create(
                class_group=self.jss1a,
                term=self.term,
                taken_on=A_SCHOOL_DAY,
                period=1,
                taken_by_id=self.teacher.pk,
            )

            register.refresh_from_db()
            self.assertEqual(register.class_group_id, self.jss1a_id)
            self.assertEqual(register.term_id, self.term_id)
            self.assertEqual(register.taken_on, A_SCHOOL_DAY)
            self.assertEqual(register.period, 1)
            self.assertEqual(register.taken_by_id, self.teacher.pk)

    def test_a_period_defaults_to_one_because_most_schools_take_one_register(self):
        with connected_to(self.stmarys):
            register = Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY
            )
            self.assertEqual(register.period, 1)

    def test_taken_on_is_the_school_day_not_the_day_it_was_entered(self):
        """A form teacher catching up on Friday is entering Wednesday's register.

        `created_at` is where "when was this typed" lives, and the two columns
        exist because they are different questions.
        """
        with connected_to(self.stmarys):
            register = Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=date(2025, 9, 15)
            )
            self.assertEqual(register.taken_on, date(2025, 9, 15))
            self.assertNotEqual(register.created_at.date(), register.taken_on)


class OneRegisterPerSlotTests(RegisterSetUp):
    def test_a_group_cannot_have_two_registers_for_one_period_of_one_day(self):
        with connected_to(self.stmarys):
            Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY, period=1
            )
            with transaction.atomic():
                with self.assertRaises(IntegrityError) as caught:
                    Register.objects.create(
                        class_group=self.jss1a,
                        term=self.term,
                        taken_on=A_SCHOOL_DAY,
                        period=1,
                    )
            self.assertIn("one_register_per_group_per_period", str(caught.exception))

    def test_two_periods_of_the_same_day_are_two_registers(self):
        with connected_to(self.stmarys):
            Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY, period=1
            )
            Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY, period=5
            )
            self.assertEqual(Register.objects.count(), 2)

    def test_two_groups_may_both_be_marked_in_the_same_period(self):
        with connected_to(self.stmarys):
            Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY, period=1
            )
            Register.objects.create(
                class_group=self.jss1b, term=self.term, taken_on=A_SCHOOL_DAY, period=1
            )
            self.assertEqual(Register.objects.count(), 2)


class APeriodIsNumberedFromOneTests(RegisterSetUp):
    def test_a_zeroth_period_is_refused(self):
        """Not tidiness: period 0 sorts ahead of the morning register.

        The card's day rule reads the earliest period taken that day, so a row
        numbered zero would quietly become the day's verdict.
        """
        with connected_to(self.stmarys):
            with transaction.atomic():
                with self.assertRaises(IntegrityError) as caught:
                    Register.objects.create(
                        class_group=self.jss1a,
                        term=self.term,
                        taken_on=A_SCHOOL_DAY,
                        period=0,
                    )
            self.assertIn("a_period_is_numbered_from_one", str(caught.exception))


class OneMarkPerStudentPerRegisterTests(RegisterSetUp):
    def a_register(self):
        return Register.objects.create(
            class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY
        )

    def test_a_child_cannot_be_marked_twice_in_one_register(self):
        with connected_to(self.stmarys):
            register = self.a_register()
            ada = self.children["ada"].pk
            AttendanceMark.objects.create(
                register=register,
                student_membership_id=ada,
                status=AttendanceStatus.PRESENT,
            )
            with transaction.atomic():
                with self.assertRaises(IntegrityError) as caught:
                    AttendanceMark.objects.create(
                        register=register,
                        student_membership_id=ada,
                        status=AttendanceStatus.ABSENT,
                    )
            self.assertIn("one_mark_per_student_per_register", str(caught.exception))

    def test_the_same_child_is_marked_once_in_each_of_two_registers(self):
        with connected_to(self.stmarys):
            morning = self.a_register()
            afternoon = Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY, period=5
            )
            ada = self.children["ada"].pk
            AttendanceMark.objects.create(
                register=morning,
                student_membership_id=ada,
                status=AttendanceStatus.PRESENT,
            )
            AttendanceMark.objects.create(
                register=afternoon,
                student_membership_id=ada,
                status=AttendanceStatus.ABSENT,
            )
            self.assertEqual(AttendanceMark.objects.count(), 2)


class UnmarkedIsNotAStatusTests(RegisterSetUp):
    """A4 in `docs/attendance.md`, held by the schema rather than by a comment.

    "Not marked" is the absence of a row and "no register" is the absence of its
    parent. Neither is an absence, and neither has a `AttendanceStatus` member —
    which is what stops a future caller writing the row that says otherwise.
    """

    def test_the_status_set_has_exactly_present_and_absent(self):
        self.assertEqual(
            sorted(AttendanceStatus.values), ["absent", "present"]
        )

    def test_a_register_with_a_child_missing_from_it_is_a_real_row(self):
        """The shape that makes "skipped" distinguishable from "absent"."""
        with connected_to(self.stmarys):
            register = Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY
            )
            AttendanceMark.objects.create(
                register=register,
                student_membership_id=self.children["ada"].pk,
                status=AttendanceStatus.PRESENT,
            )
            marked = set(
                AttendanceMark.objects.values_list("student_membership_id", flat=True)
            )
            self.assertEqual(marked, {self.children["ada"].pk})
            self.assertEqual(len(self.everyone()), 4)


class TheRegisterTablesAreTenantScopedTests(RegisterSetUp):
    def test_the_register_tables_are_absent_from_public(self):
        """Not empty in `public` — absent. The whole point of `docs/tenancy.md`."""
        connection.set_schema_to_public()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN "
                "('attendance_register', 'attendance_attendancemark')"
            )
            self.assertEqual(cursor.fetchall(), [])

    def test_two_schools_may_both_mark_the_same_group_name_on_the_same_day(self):
        with connected_to(self.stmarys):
            Register.objects.create(
                class_group=self.jss1a, term=self.term, taken_on=A_SCHOOL_DAY
            )
            self.assertEqual(Register.objects.count(), 1)
        with connected_to(self.grace):
            self.assertEqual(Register.objects.count(), 0)


class NoIndexIsBuiltTwiceTests(RegisterSetUp):
    """No *declared* index repeats a constraint's btree.

    The rule `results.tests.test_ratings.NoIndexIsBuiltTwiceTests` holds for the
    frozen tables, applied to the two new ones. Django's automatic
    per-`ForeignKey` index is excluded for the reason that test gives: turning
    one off is a `db_index=False` decision about delete-time lookups that
    belongs to the whole repository rather than to one table, and it is
    [issue #32](https://github.com/adedejimakinde/luffy-school-saas/issues/32).

    Asserted against `pg_indexes` rather than against `Meta`, because the rule
    is about what Postgres builds and `UniqueConstraint` builds one too.
    """

    #: Indexes Django builds for a foreign key that nothing here objects to.
    #: `attendance_register.class_group_id` and
    #: `attendance_attendancemark.register_id` are each a strict prefix of their
    #: table's unique constraint and are redundant by the same argument as the
    #: five frozen tables — listed anyway, under #32, so that the list says what
    #: exists rather than what ought to.
    AUTOMATIC = {
        "attendance_register": [["class_group_id"], ["term_id"]],
        "attendance_attendancemark": [
            ["register_id"],
            ["student_membership_id"],
        ],
    }

    def indexes_of(self, table):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = %s",
                [self.stmarys.schema_name, table],
            )
            return cursor.fetchall()

    def columns_in(self, indexdef):
        inside = indexdef[indexdef.index("(") + 1 : indexdef.rindex(")")]
        return [part.strip().split()[0] for part in inside.split(",")]

    def test_no_declared_index_repeats_a_constraints_leading_columns(self):
        with connected_to(self.stmarys):
            for table, automatic in self.AUTOMATIC.items():
                seen = []
                for name, indexdef in self.indexes_of(table):
                    columns = self.columns_in(indexdef)
                    if columns in automatic or name.endswith("_pkey"):
                        continue
                    for earlier in seen:
                        self.assertNotEqual(
                            columns[: len(earlier)],
                            earlier,
                            f"{name} on {table} repeats the btree already led by "
                            f"{earlier}",
                        )
                    seen.append(columns)

    def test_every_whitelisted_index_names_a_column_that_exists(self):
        """A whitelist is only a tripwire if the names in it are real.

        An entry for an index that cannot be built costs nothing the day it is
        written and silently pre-approves the real index the day somebody adds
        that relation — the trap the same test in `results` nearly shipped.
        """
        with connected_to(self.stmarys):
            for table, automatic in self.AUTOMATIC.items():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s",
                        [self.stmarys.schema_name, table],
                    )
                    columns = {row[0] for row in cursor.fetchall()}
                for entry in automatic:
                    for column in entry:
                        self.assertIn(column, columns, f"{table}.{column}")
