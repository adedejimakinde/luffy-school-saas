"""The three routes, and the two things their shape has to get right.

**Authority is asked before either lookup.** `get_object_or_404()` answers 404
for a row that is not there and lets the request go on to a 403 for one that is,
so asking authority second would turn every route here into an existence oracle
for anybody signed in at the school — a parent could walk the id space and learn
which class groups and which terms are real by reading the status code. The
tests that hold this compare a real id against an invented one and demand the
same answer.

**One request per register.** The whole point of the write route is that forty
five children are marked in one PUT, so the tests submit whole registers rather
than cells and assert on the four lists that come back.
"""

import json

from django.test import TestCase

from academics import services as academics
from academics.models import Term
from accounts.models import Role, User
from accounts.services import grant_membership
from attendance.models import AttendanceMark, Register
from schools.models import Domain, School
from schools.tests.tenants import connected_to

from .fixtures import A_SCHOOL_DAY, PASSWORD, RegisterSetUp

HOST = "st-marys.testserver"

#: An id no membership has. The "is this real" half of every oracle test.
ABSENT = 10**9


class RegisterApiSetUp(RegisterSetUp):
    def setUp(self):
        super().setUp()

        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)

        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        self.parent = grant_membership(
            User.objects.create_user("uche", PASSWORD, full_name="Uche Obi"),
            self.stmarys,
            Role.PARENT,
        )

    def url(self, *, group=None, term=None, on=A_SCHOOL_DAY):
        group = self.jss1a_id if group is None else group
        term = self.term_id if term is None else term
        return f"/api/attendance/classes/{group}/terms/{term}/{on}/"

    def get(self, **kwargs):
        return self.client.get(self.url(**kwargs), HTTP_HOST=HOST)

    def put(self, *, absent_ids=None, shown_ids=None, **kwargs):
        body = {}
        if absent_ids is not None:
            body["absent_ids"] = absent_ids
        if shown_ids is not None:
            body["shown_ids"] = shown_ids
        return self.client.put(
            self.url(**kwargs),
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=HOST,
        )


class ReadingARegisterTests(RegisterApiSetUp):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.teacher.user)

    def test_an_untaken_register_answers_the_roster_with_nothing_marked(self):
        """One request for the screen a teacher opens, not two.

        Making the client assemble this from a 404 plus a separate roster call
        would be two round trips for one screen, on the connection this feature
        can least afford them.
        """
        answer = self.get()

        self.assertEqual(answer.status_code, 200)
        body = answer.json()
        self.assertFalse(body["taken"])
        self.assertEqual(len(body["rows"]), 4)
        self.assertEqual({row["status"] for row in body["rows"]}, {None})
        self.assertIn("Ada Obi", [row["student"] for row in body["rows"]])

    def test_taken_is_what_tells_an_untaken_register_from_an_unmarked_one(self):
        self.assertFalse(self.get().json()["taken"])
        self.put(absent_ids=[])
        self.assertTrue(self.get().json()["taken"])

    def test_a_taken_register_answers_with_the_statuses(self):
        ada = self.children["ada"].pk
        self.put(absent_ids=[ada])

        rows = {row["student_membership_id"]: row["status"] for row in self.get().json()["rows"]}
        self.assertEqual(rows[ada], "absent")
        self.assertEqual(rows[self.children["emeka"].pk], "present")


class TakingARegisterOverHttpTests(RegisterApiSetUp):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.teacher.user)

    def test_one_request_marks_the_whole_class(self):
        answer = self.put(absent_ids=self.ids("ada"))

        self.assertEqual(answer.status_code, 200)
        body = answer.json()
        self.assertEqual(body["absent"], self.ids("ada"))
        self.assertEqual(body["present"], self.ids("bisi", "emeka", "tunde"))
        with connected_to(self.stmarys):
            self.assertEqual(AttendanceMark.objects.count(), 4)
            self.assertEqual(Register.objects.count(), 1)

    def test_an_omitted_body_is_a_register_saying_everybody_was_there(self):
        answer = self.put()

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["present"], self.everyone())

    def test_a_second_put_amends_rather_than_duplicating(self):
        ada = self.children["ada"].pk
        self.put(absent_ids=[ada])
        answer = self.put(absent_ids=[])

        self.assertEqual(answer.status_code, 200)
        self.assertIn(ada, answer.json()["present"])
        with connected_to(self.stmarys):
            self.assertEqual(Register.objects.count(), 1)

    def test_a_child_who_appeared_is_reported_and_not_marked(self):
        tunde = self.children["tunde"].pk
        answer = self.put(shown_ids=self.ids("ada", "emeka", "bisi"))

        self.assertEqual(answer.json()["appeared"], [tunde])
        with connected_to(self.stmarys):
            self.assertEqual(AttendanceMark.objects.count(), 3)

    def test_an_absentee_off_the_roster_is_reported_and_the_rest_are_written(self):
        with connected_to(self.stmarys):
            tunde = self.children["tunde"]
            academics.move_student(self.jss1b, self.term, tunde)

        answer = self.put(absent_ids=[tunde.pk])

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["not_on_the_roster"], [tunde.pk])
        with connected_to(self.stmarys):
            self.assertEqual(AttendanceMark.objects.count(), 3)

    def test_a_second_day_is_a_second_register(self):
        self.put(absent_ids=[])
        answer = self.put(absent_ids=self.ids("ada"), on="2025-09-18")

        self.assertEqual(answer.status_code, 200)
        with connected_to(self.stmarys):
            self.assertEqual(Register.objects.count(), 2)

    def test_an_empty_group_is_a_409_not_a_404(self):
        """The group and the term exist; the school's state is wrong for this."""
        answer = self.put(group=self.jss1b_id)

        self.assertEqual(answer.status_code, 409)
        self.assertIn("JSS 1B", answer.json()["detail"])

    def test_a_day_outside_the_term_is_a_422(self):
        answer = self.put(on="2025-09-01")

        self.assertEqual(answer.status_code, 422)
        self.assertIn("2025-09-01", answer.json()["detail"])

    def test_a_malformed_date_is_refused_rather_than_routed_past(self):
        """The segment has no converter, so the schema is what validates it."""
        answer = self.client.put(
            f"/api/attendance/classes/{self.jss1a_id}/terms/{self.term_id}/not-a-date/",
            data="{}",
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(answer.status_code, 422)


class DiscardingOverHttpTests(RegisterApiSetUp):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.head.user)

    def url_for_discard(self, on=A_SCHOOL_DAY):
        return f"/api/attendance/classes/{self.jss1a_id}/{on}/"

    def test_a_register_and_its_marks_go_together(self):
        self.client.put(
            self.url(),
            data="{}",
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        answer = self.client.delete(self.url_for_discard(), HTTP_HOST=HOST)

        self.assertEqual(answer.status_code, 204)
        with connected_to(self.stmarys):
            self.assertEqual(Register.objects.count(), 0)
            self.assertEqual(AttendanceMark.objects.count(), 0)

    def test_discarding_nothing_is_a_404(self):
        answer = self.client.delete(self.url_for_discard(), HTTP_HOST=HOST)
        self.assertEqual(answer.status_code, 404)


class AuthorityIsAskedFirstTests(RegisterApiSetUp):
    """A non-marker must not be able to tell a real id from an invented one."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def test_a_parent_cannot_tell_a_real_class_from_an_invented_one(self):
        real = self.put()
        invented = self.put(group=ABSENT)

        self.assertEqual(real.status_code, 403)
        self.assertEqual(invented.status_code, 403)
        self.assertEqual(real.json()["detail"], invented.json()["detail"])

    def test_a_parent_cannot_tell_a_real_term_from_an_invented_one(self):
        self.assertEqual(self.put(term=ABSENT).status_code, 403)
        self.assertEqual(self.get(term=ABSENT).status_code, 403)

    def test_a_bursar_may_not_read_a_register_either(self):
        self.client.force_login(self.bursar.user)
        self.assertEqual(self.get().status_code, 403)

    def test_a_student_may_not_mark_the_register_she_appears_in(self):
        self.client.force_login(self.children["ada"].user)
        self.assertEqual(self.put().status_code, 403)

    def test_a_refused_write_leaves_nothing_behind(self):
        self.put(absent_ids=self.everyone())
        with connected_to(self.stmarys):
            self.assertEqual(Register.objects.count(), 0)
            self.assertEqual(AttendanceMark.objects.count(), 0)


class ThereIsNoRegisterOnThePortalTests(RegisterApiSetUp):
    """A 404, not a 403: on the portal there is no such register to refuse."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.head.user)

    def test_the_portal_host_has_no_such_route(self):
        answer = self.client.get(self.url(), HTTP_HOST="testserver")
        self.assertEqual(answer.status_code, 404)


class WhereToMarkTests(RegisterApiSetUp):
    """The chooser's data: which classes, and which term.

    Without this route the register screen is keyed on three values nothing
    ever handed it — the same gap the card index closed for a family, where the
    page shipped openable only by typing two integers into a URL.
    """

    WHERE = "/api/attendance/where/"

    def where(self, host=HOST):
        return self.client.get(self.WHERE, HTTP_HOST=host)

    def test_a_marker_is_told_the_classes_and_the_current_term(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=True)
        self.client.force_login(self.teacher.user)

        body = self.where().json()

        self.assertEqual(body["term_id"], self.term_id)
        self.assertEqual(
            sorted(group["name"] for group in body["classes"]),
            ["JSS 1A", "JSS 1B"],
        )

    def test_every_class_is_listed_and_not_only_the_ones_she_is_answerable_for(self):
        """**Asserted because it is a gap, not because it is a feature.**

        `can_mark_attendance()` is school-wide and carries no reference to
        `ClassTeacher`, so any teacher may take any class's register. A screen
        showing a shorter list would be a scope the platform does not enforce,
        drawn as though it did — which is the restriction-that-looks-enforced
        this codebase keeps finding.

        Issue #125 is where narrowing it is argued, together with the domain
        question behind it: a subject teacher covering an absent form teacher.
        **This test goes red the day #125 is closed**, and that is the point of
        it; when it does, move its case into whatever the new rule is.
        """
        self.client.force_login(self.teacher.user)

        names = [group["name"] for group in self.where().json()["classes"]]

        self.assertIn(
            "JSS 1B",
            names,
            "the list narrowed without the route narrowing with it",
        )

    def test_no_current_term_is_reported_rather_than_guessed(self):
        """A term worked out from today's date would disagree with the school
        the first time a term ran late, and the register would be filed against
        the wrong one with nothing on the row to say so."""
        self.client.force_login(self.teacher.user)

        body = self.where().json()

        self.assertIsNone(body["term_id"])
        self.assertIsNone(body["term"])

    def test_a_bursar_is_refused_before_anything_is_looked_up(self):
        """The authority check runs first, so this cannot become a directory of
        the school's class groups for anybody signed in there."""
        self.client.force_login(self.bursar.user)

        answer = self.where()

        self.assertEqual(answer.status_code, 403)
        self.assertNotIn("JSS 1A", answer.content.decode())

    def test_a_parent_is_refused_too(self):
        self.client.force_login(self.parent.user)

        self.assertEqual(self.where().status_code, 403)

    def test_the_portal_has_no_such_route(self):
        """404 and not 403: there is no register on the portal to refuse."""
        self.client.force_login(self.head.user)

        self.assertEqual(self.where(host="testserver").status_code, 404)
