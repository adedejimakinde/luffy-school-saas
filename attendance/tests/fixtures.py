"""One school, one class, one term and four children, in a real schema.

`attendance` is tenant-scoped, so everything here runs inside a school schema
rather than against `public` — `attendance_register` does not exist there at
all, which is the point of `docs/tenancy.md` and what
`test_the_register_tables_are_absent_from_public` pins directly.

Two schools in the fixture rather than one, for the reason
`academics.tests.test_classes` gives at length: a single-tenant fixture cannot
fail for any of the reasons a roster query is most likely to be got wrong — a
missing `term` filter, a uniqueness that should be per-schema, a write on the
wrong connection.
"""

from datetime import date

from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from schools.tests.tenants import connected_to, make_school

PASSWORD = "correct-horse-battery"

#: Inside the term below, and a Wednesday. Every test that does not care which
#: day it is uses this one, so a failure naming a date names a deliberate one.
A_SCHOOL_DAY = date(2025, 9, 17)


def a_term(session="2025/2026", name=TermName.FIRST, starts=None, ends=None):
    return Term.objects.create(
        session=session,
        name=name,
        starts_on=starts or date(2025, 9, 15),
        ends_on=ends or date(2025, 12, 12),
    )


class RegisterSetUp(TestCase):
    """St Mary's with JSS 1A and four children placed in it."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.children = {}
        for handle, name in (
            ("ada", "Ada Obi"),
            ("emeka", "Emeka Nwosu"),
            ("bisi", "Bisi Ade"),
            ("tunde", "Tunde Cole"),
        ):
            self.children[handle] = enroll_student(
                User.objects.create_user(handle, PASSWORD, full_name=name),
                self.stmarys,
            )

        self.teacher = grant_membership(
            User.objects.create_user("kemi", PASSWORD, full_name="Kemi Bello"),
            self.stmarys,
            Role.TEACHER,
        )
        self.head = grant_membership(
            User.objects.create_user("ngozi", PASSWORD, full_name="Ngozi Eze"),
            self.stmarys,
            Role.PRINCIPAL,
        )
        self.bursar = grant_membership(
            User.objects.create_user("femi", PASSWORD, full_name="Femi Sanni"),
            self.stmarys,
            Role.BURSAR,
        )

        with connected_to(self.stmarys):
            self.term = a_term()
            self.second_term = a_term(
                name=TermName.SECOND,
                starts=date(2026, 1, 12),
                ends=date(2026, 4, 2),
            )
            self.jss1a = ClassGroup.objects.create(name="JSS 1A", level=1)
            self.jss1b = ClassGroup.objects.create(name="JSS 1B", level=1)
            for child in self.children.values():
                academics.place_student(self.jss1a, self.term, child)

        self.term_id = self.term.pk
        self.jss1a_id = self.jss1a.pk
        self.jss1b_id = self.jss1b.pk

    def tearDown(self):
        # `schema_context` leaves the connection wherever it was last set, and
        # the next test's `School.save()` refuses to run outside `public`. The
        # same teardown `academics.tests.test_classes` carries, for the same
        # reason.
        from django.db import connection

        connection.set_schema_to_public()

    def ids(self, *handles):
        return sorted(self.children[h].pk for h in handles)

    def everyone(self):
        return sorted(child.pk for child in self.children.values())
