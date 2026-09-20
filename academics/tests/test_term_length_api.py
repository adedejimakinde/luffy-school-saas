"""The route that declares a term's length, and the page it does not have.

One PUT, admin-only. `academics.api`'s docstring carries the argument for why
there is no screen: D12, and the staff-UI problem the register screen already
has to solve once.
"""

import json

from academics.models import Term
from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain, School
from schools.tests.tenants import connected_to

from .test_term_length import PASSWORD, TermLengthSetUp

HOST = "st-marys.testserver"
ABSENT = 10**9


class TermLengthApiSetUp(TermLengthSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

    def put(self, days, term_id=None, host=HOST):
        term_id = self.term.pk if term_id is None else term_id
        return self.client.put(
            f"/api/academics/terms/{term_id}/length/",
            data=json.dumps({"school_days": days}),
            content_type="application/json",
            HTTP_HOST=host,
        )


class SettingItOverHttpTests(TermLengthApiSetUp):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.head.user)

    def test_a_principal_declares_the_length_and_gets_the_term_back(self):
        answer = self.put(61)

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["school_days"], 61)
        with connected_to(self.stmarys):
            self.assertEqual(Term.objects.get(pk=self.term.pk).school_days, 61)

    def test_the_answer_carries_the_ceiling_the_constraint_checks_against(self):
        """`calendar_days` is what a caller needs to pick a legal number."""
        self.assertEqual(self.put(61).json()["calendar_days"], 89)

    def test_clearing_it_is_a_real_act(self):
        self.put(61)
        answer = self.put(None)

        self.assertEqual(answer.status_code, 200)
        self.assertIsNone(answer.json()["school_days"])

    def test_more_days_than_the_term_holds_is_a_422(self):
        """The request disagreeing with the calendar it names, not a state."""
        answer = self.put(500)

        self.assertEqual(answer.status_code, 422)
        with connected_to(self.stmarys):
            self.assertIsNone(Term.objects.get(pk=self.term.pk).school_days)

    def test_zero_is_a_422(self):
        self.assertEqual(self.put(0).status_code, 422)


class AuthorityIsAskedFirstTests(TermLengthApiSetUp):
    """A teacher must not be able to tell a real term from an invented one."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.teacher.user)

    def test_a_teacher_cannot_tell_a_real_term_from_an_invented_one(self):
        real = self.put(61)
        invented = self.put(61, term_id=ABSENT)

        self.assertEqual(real.status_code, 403)
        self.assertEqual(invented.status_code, 403)
        self.assertEqual(real.json()["detail"], invented.json()["detail"])

    def test_a_refused_write_leaves_the_term_alone(self):
        self.put(61)
        with connected_to(self.stmarys):
            self.assertIsNone(Term.objects.get(pk=self.term.pk).school_days)


class ThereIsNoCalendarOnThePortalTests(TermLengthApiSetUp):
    def test_the_portal_host_has_no_such_route(self):
        self.client.force_login(self.head.user)
        self.assertEqual(self.put(61, host="testserver").status_code, 404)
