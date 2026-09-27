"""GET .../sheet/ over a real request, with no ambient transaction.

Issue #179. `TestCase` wraps every test in a transaction, so
`ResultSheet.objects.select_for_update()` is legal there even when nothing in
the view opens one — Django only refuses `FOR UPDATE` outside a transaction,
and the test's own wrapper supplies one for free. A real request has no such
wrapper, so `marking_sheet()` calling `results_services.locked_sheet_for()` —
a write lock — on a GET raised:

    django.db.transaction.TransactionManagementError:
    select_for_update cannot be used outside of a transaction.

on the development server, and would have on any WSGI worker.
`gradebook/tests/test_api.py` never caught it for exactly the reason above; it
drives the same route and reads TestCase's transaction as the view's own.

`TransactionTestCase`, on the same reasoning as
`results/tests/test_approval_concurrency.py`: no wrapping transaction is the
whole point, so a real school (`School.save()`, not the cloned
`schools.tests.tenants.make_school()`, which that file's setup follows for the
same reason) and the Django test client, which is a real request through the
real middleware stack rather than a call into the view function.

The fix reads the sheet with `results_services.sheet_for()` instead, which
takes no lock — the read path's own convention, and the right one on a page
load besides: a `SELECT ... FOR UPDATE` on every GET would serialise a class's
marking screen against its own release.
"""

from datetime import date

from django.db import connection
from django.test import TransactionTestCase

from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from gradebook.models import Assessment, Subject
from schools.models import Domain, School
from schools.tests.tenants import connected_to

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"


class OpeningASheetOverHttpTests(TransactionTestCase):
    def setUp(self):
        self.school = School(name="St Mary's", slug="st-marys", schema_name="st_marys")
        self.school.save()
        Domain.objects.create(tenant=self.school, domain=HOST, is_primary=True)

        self.teacher = User.objects.create_user(
            "kemi", PASSWORD, full_name="Kemi Bello"
        )
        grant_membership(self.teacher, self.school, Role.TEACHER)

        with connected_to(self.school):
            term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )
            subject = Subject.objects.create(name="Mathematics", code="MTH")
            self.assessment_id = Assessment.objects.create(
                term=term, subject=subject, name="First CA", max_score=20
            ).pk
            self.class_group_id = ClassGroup.objects.create(
                name="JSS 1A", level=1
            ).pk

    def tearDown(self):
        # `results/tests/test_approval_concurrency.py` carries the reason at
        # length: `TransactionTestCase` flushes the *public* tables between
        # tests, but a tenant schema is not a table, so `st_marys` outlives
        # this test unless it is dropped by hand — and the request this test
        # makes leaves the connection's `search_path` set to it, which the next
        # `TransactionTestCase`'s `School.save()` then finds itself on. Missing
        # this the first time round left exactly that behind and broke a test
        # two modules away, in the same parallel worker.
        connection.set_schema_to_public()
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{self.school.schema_name}" CASCADE')
        super().tearDown()

    def test_a_teacher_can_open_a_sheet_with_no_wrapping_transaction(self):
        """CONTROL: reverting `marking_sheet()` to `locked_sheet_for()` makes
        this 500 — it does not need a `ResultSheet` row to fail, because the
        error is raised compiling the locking query itself, before it asks
        whether anything matches."""
        self.client.force_login(self.teacher)

        response = self.client.get(
            f"/api/gradebook/assessments/{self.assessment_id}/sheet/",
            HTTP_HOST=HOST,
        )

        self.assertEqual(response.status_code, 422, response.content)

        response = self.client.get(
            f"/api/gradebook/assessments/{self.assessment_id}/sheet/"
            f"?class_group_id={self.class_group_id}",
            HTTP_HOST=HOST,
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["locked"])
