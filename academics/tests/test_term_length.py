"""Declaring how many days a term taught, and who may.

`Term.school_days` is the denominator of every attendance figure a card prints,
and until this slice it had three constraints, a paragraph of documentation and
**no writer** — reachable only from the ORM, so `days_open` was null on every
card that could ever have been released. D12 settles the door: a service
function and a route, admin-only, and deliberately no screen.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from academics import services
from academics.models import Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from schools.tests.tenants import connected_to, make_school

PASSWORD = "correct-horse-battery"


class TermLengthSetUp(TestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.head = grant_membership(
            User.objects.create_user("ngozi", PASSWORD, full_name="Ngozi Eze"),
            self.stmarys,
            Role.PRINCIPAL,
        )
        self.admin = grant_membership(
            User.objects.create_user("aisha", PASSWORD, full_name="Aisha Bala"),
            self.stmarys,
            Role.ADMIN,
        )
        self.teacher = grant_membership(
            User.objects.create_user("kemi", PASSWORD, full_name="Kemi Bello"),
            self.stmarys,
            Role.TEACHER,
        )
        self.ada = enroll_student(
            User.objects.create_user("ada", PASSWORD, full_name="Ada Obi"),
            self.stmarys,
        )
        with connected_to(self.stmarys):
            self.term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )

    def tearDown(self):
        from django.db import connection

        connection.set_schema_to_public()


class SettingTheLengthTests(TermLengthSetUp):
    def test_a_term_starts_with_no_declared_length(self):
        with connected_to(self.stmarys):
            self.assertIsNone(self.term.school_days)

    def test_the_school_declares_it_and_it_sticks(self):
        with connected_to(self.stmarys):
            services.set_school_days(self.term, 61, by=self.head)
            self.term.refresh_from_db()
            self.assertEqual(self.term.school_days, 61)

    def test_it_can_be_cleared_because_a_blank_beats_a_number_nobody_believes(self):
        with connected_to(self.stmarys):
            services.set_school_days(self.term, 61, by=self.head)
            services.set_school_days(self.term, None, by=self.head)
            self.term.refresh_from_db()
            self.assertIsNone(self.term.school_days)

    def test_it_is_not_computed_from_the_dates(self):
        """`calendar_days` is the ceiling; `school_days` is what was taught."""
        with connected_to(self.stmarys):
            services.set_school_days(self.term, 61, by=self.head)
            self.term.refresh_from_db()
            self.assertNotEqual(self.term.school_days, self.term.calendar_days)


class TheConstraintsStillHoldThroughTheServiceTests(TermLengthSetUp):
    def test_more_days_than_the_term_contains_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ValidationError):
                services.set_school_days(self.term, 500, by=self.head)
            self.term.refresh_from_db()
            self.assertIsNone(self.term.school_days)

    def test_zero_school_days_is_not_a_term(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ValidationError):
                services.set_school_days(self.term, 0, by=self.head)

    def test_the_whole_span_is_allowed(self):
        with connected_to(self.stmarys):
            services.set_school_days(self.term, self.term.calendar_days, by=self.head)
            self.term.refresh_from_db()
            self.assertEqual(self.term.school_days, self.term.calendar_days)


class WhoMayDeclareATermsLengthTests(TermLengthSetUp):
    def test_a_principal_and_an_administrator_may(self):
        self.assertTrue(services.can_set_school_days(self.head.user, self.stmarys))
        self.assertTrue(services.can_set_school_days(self.admin.user, self.stmarys))

    def test_a_teacher_may_not(self):
        """A teacher marks the register; the calendar is an office act."""
        self.assertFalse(services.can_set_school_days(self.teacher.user, self.stmarys))

    def test_a_student_may_not(self):
        self.assertFalse(services.can_set_school_days(self.ada.user, self.stmarys))

    def test_a_principal_of_another_school_may_not(self):
        self.assertFalse(services.can_set_school_days(self.head.user, self.grace))

    def test_the_refusal_is_its_own_class_and_names_who_may(self):
        """Not `NotAllowedToPlace`, even though the role set matches today.

        Two questions that happen to share an answer are still two questions,
        and a caller explaining a calendar refusal with a placement sentence
        would print the wrong thing the moment either set moves.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToSetTermLength) as caught:
                services.set_school_days_as(
                    self.teacher.user, self.term, 61, school=self.stmarys
                )
            self.assertIn("principal", str(caught.exception))
            self.term.refresh_from_db()
            self.assertIsNone(self.term.school_days)
