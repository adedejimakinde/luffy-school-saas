"""The principal's list: who is absent too often.

Decided 2026-09-24 (docs/attendance.md, OPEN-2): the absent share of **marked**
days, past a floor of marked days, against a threshold **the school sets**
(10% and 10 days by default); read by the principal, the vice principal
(academic) and the administrator, and refused to everybody else with a flat 404.

Each of those four clauses has the test that fails without it:

- a day with no register counts for nothing — neither absent nor present;
- a child marked twice and absent once is not 50% absent;
- one school's threshold is not another's;
- the refusal is the list's own, not a 403 and not a missing route.
"""

import json
from datetime import date, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext

from academics import services as academics
from academics.models import ClassGroup, Term
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from attendance import services
from attendance.models import AbsenceSettings
from schools.models import Domain
from schools.tests.tenants import connected_to

from .fixtures import PASSWORD, a_term
from .test_api import HOST, RegisterApiSetUp

LIST = "/api/attendance/absences/"
THRESHOLD = "/api/attendance/absences/threshold/"
GRACE_HOST = "grace.testserver"


def school_days(n, start=date(2025, 9, 15)):
    """`n` distinct days inside the fixture's first term."""
    return [start + timedelta(days=i) for i in range(n)]


class AbsenceSetUp(RegisterApiSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=True)
        self.vp = grant_membership(
            User.objects.create_user("vera", PASSWORD, full_name="Vera Vp"),
            self.stmarys,
            Role.VICE_PRINCIPAL_ACADEMIC,
        )
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"),
            self.stmarys,
            Role.ADMIN,
        )
        self.student = self.children["tunde"]

    def take(self, days, absent=None, group=None, school=None, term=None):
        """A register on each of `days`. `absent` maps a child to how many of
        those days — the first ones — they missed."""
        absent = absent or {}
        with connected_to(school or self.stmarys):
            group = ClassGroup.objects.get(pk=group or self.jss1a_id)
            term = Term.objects.get(pk=term or self.term_id)
            for i, day in enumerate(days):
                services.take_register(
                    group,
                    term,
                    on=day,
                    absent_ids=[child.pk for child, n in absent.items() if i < n],
                )

    def read(self, user, host=HOST, term_id=None):
        self.client.force_login(user)
        url = LIST if term_id is None else f"{LIST}?term_id={term_id}"
        return self.client.get(url, HTTP_HOST=host)

    def listed(self, user=None, host=HOST):
        body = self.read(user or self.head.user, host=host).json()
        return {row["student"]: row for row in body["children"]}

    def set_threshold(self, user, percent, days, host=HOST):
        self.client.force_login(user)
        return self.client.put(
            THRESHOLD,
            data=json.dumps({"threshold_percent": percent, "min_marked_days": days}),
            content_type="application/json",
            HTTP_HOST=host,
        )


class WhatCountsTests(AbsenceSetUp):
    def test_the_list_really_lists(self):
        """The control, and it runs first: Emeka absent 3 of 10, Ada 1 of 10,
        and both at or over 10%, worst first."""
        self.take(school_days(10), absent={self.children["emeka"]: 3, self.children["ada"]: 1})

        body = self.read(self.head.user).json()

        self.assertEqual(
            [(r["student"], r["absent"], r["marked"], r["rate"]) for r in body["children"]],
            [("Emeka Nwosu", 3, 10, "30.0"), ("Ada Obi", 1, 10, "10.0")],
        )
        self.assertEqual(body["children"][0]["class_group"], "JSS 1A")
        self.assertEqual(body["term_id"], self.term_id)
        self.assertEqual(body["registers_taken"], 10)

    def test_a_day_with_no_register_counts_for_nothing(self):
        """**A4.** The term declares 60 school days and JSS 1A has been marked
        on 12 of them. Emeka missed 3 of the 12: that is 25%, and he is on the
        list — the 48 unmarked days did not make him present. Bisi was there
        all 12: she is not on the list — the 48 unmarked days did not make her
        absent either.

        CONTROL 2: measuring the rate over the declared school days instead
        of the days marked makes this red.
        """
        with connected_to(self.stmarys):
            academics.set_school_days(Term.objects.get(pk=self.term_id), 60)
        self.take(school_days(12), absent={self.children["emeka"]: 3})

        listed = self.listed()

        self.assertIn("Emeka Nwosu", listed, "unmarked days were counted as present")
        self.assertEqual((listed["Emeka Nwosu"]["marked"], listed["Emeka Nwosu"]["rate"]), (12, "25.0"))
        self.assertNotIn("Bisi Ade", listed, "unmarked days were counted as absent")

    def test_a_child_marked_twice_and_absent_once_is_not_fifty_percent_absent(self):
        """**The floor.** Two marked days is not a pattern.

        CONTROL 3: dropping the marked-days floor makes this red.
        """
        self.take(school_days(2), absent={self.children["emeka"]: 1})

        body = self.read(self.head.user).json()

        self.assertEqual(body["registers_taken"], 2, "no register was taken, so this proves nothing")
        self.assertEqual(body["children"], [])

    def test_the_floor_is_met_at_the_floor(self):
        """At exactly the floor and exactly the threshold, a child is on the
        list — compared in integers, so 1 of 10 is 10% and not 9.999…"""
        self.take(school_days(10), absent={self.children["ada"]: 1})
        self.assertIn("Ada Obi", self.listed())

    def test_a_child_who_moved_class_counts_both_classes_registers(self):
        """`summary.for_term()`'s rule: a child's term is every register that
        marked her, whichever class took it. Listed under the class she is in
        now, because that is where the principal will look for her."""
        ada = self.children["ada"]
        self.take(school_days(6), absent={ada: 1})
        with connected_to(self.stmarys):
            academics.move_student(
                ClassGroup.objects.get(pk=self.jss1b_id), Term.objects.get(pk=self.term_id), ada
            )
        self.take(school_days(6, start=date(2025, 10, 1)), absent={ada: 1}, group=self.jss1b_id)

        row = self.listed()["Ada Obi"]

        self.assertEqual((row["absent"], row["marked"], row["class_group"]), (2, 12, "JSS 1B"))

    def test_nobody_on_the_list_and_nobody_marked_are_told_apart(self):
        body = self.read(self.head.user).json()

        self.assertEqual((body["children"], body["registers_taken"]), ([], 0))

    def test_another_terms_absences_are_not_this_terms(self):
        self.take(school_days(10), absent={self.children["emeka"]: 5})

        body = self.read(self.head.user, term_id=self.second_term.pk).json()

        self.assertEqual(body["term_id"], self.second_term.pk)
        self.assertEqual(body["children"], [])


class TheSchoolsOwnThresholdTests(AbsenceSetUp):
    """Grace, with its own principal, class, child and registers."""

    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.grace, domain=GRACE_HOST, is_primary=True)
        self.their_head = grant_membership(
            User.objects.create_user("gbenga", PASSWORD, full_name="Gbenga Head"),
            self.grace,
            Role.PRINCIPAL,
        )
        self.their_child = enroll_student(
            User.objects.create_user("zainab", PASSWORD, full_name="Zainab Musa"), self.grace
        )
        with connected_to(self.grace):
            term = a_term()
            term.is_current = True
            term.save()
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(group, term, self.their_child)
        self.their_term_id, self.their_group_id = term.pk, group.pk

    def test_each_school_draws_its_list_by_its_own_threshold(self):
        """St Mary's raises its line to 30%; Grace keeps the default 10%. A
        child absent 2 days in 10 is off St Mary's list and on Grace's.

        CONTROL 4: reading the default threshold instead of the school's own
        setting makes this red.
        """
        self.assertEqual(self.set_threshold(self.head.user, 30, 10).status_code, 200)
        self.take(school_days(10), absent={self.children["emeka"]: 2})
        self.take(
            school_days(10),
            absent={self.their_child: 2},
            group=self.their_group_id,
            school=self.grace,
            term=self.their_term_id,
        )

        ours = self.read(self.head.user).json()
        theirs = self.read(self.their_head.user, host=GRACE_HOST).json()

        self.assertEqual((ours["threshold_percent"], theirs["threshold_percent"]), (30, 10))
        self.assertNotIn("Emeka Nwosu", str(ours["children"]))
        self.assertIn("Zainab Musa", str(theirs["children"]))

    def test_a_school_never_set_is_the_default(self):
        body = self.read(self.their_head.user, host=GRACE_HOST).json()

        self.assertEqual((body["threshold_percent"], body["min_marked_days"]), (10, 10))
        with connected_to(self.grace):
            self.assertFalse(AbsenceSettings.objects.exists())

    def test_our_principal_sees_none_of_their_children(self):
        self.take(
            school_days(10),
            absent={self.their_child: 5},
            group=self.their_group_id,
            school=self.grace,
            term=self.their_term_id,
        )
        self.assertIn("Zainab Musa", self.listed(self.their_head.user, host=GRACE_HOST))

        self.assertNotIn(b"Zainab", self.read(self.head.user).content)


class ChangingTheThresholdTests(AbsenceSetUp):
    def test_the_principal_and_the_administrator_may_change_it(self):
        for user, percent in ((self.head.user, 15), (self.admin.user, 20)):
            with self.subTest(user=user.username):
                answer = self.set_threshold(user, percent, 8)

                self.assertEqual(answer.status_code, 200)
                self.assertEqual(answer.json(), {"threshold_percent": percent, "min_marked_days": 8})
                self.assertEqual(self.read(user).json()["threshold_percent"], percent)

    def test_the_vice_principal_reads_it_and_may_not_change_it(self):
        """She knows the list exists, so her refusal can say so — a 403 with
        the sentence, not the flat 404."""
        self.assertFalse(self.read(self.vp.user).json()["may_change_threshold"])

        answer = self.set_threshold(self.vp.user, 50, 10)

        self.assertEqual(answer.status_code, 403)
        self.assertIn("principal or an administrator", answer.json()["detail"])
        self.assertEqual(self.read(self.head.user).json()["threshold_percent"], 10)

    def test_a_number_out_of_range_is_a_sentence(self):
        for percent, days in ((0, 10), (101, 10), (10, 0), (10, 366)):
            with self.subTest(percent=percent, days=days):
                answer = self.set_threshold(self.head.user, percent, days)

                self.assertEqual(answer.status_code, 422)
                self.assertTrue(answer.json()["detail"])


class WhoMayReadItTests(AbsenceSetUp):
    def test_the_principal_the_vp_and_the_administrator_read_it(self):
        for user in (self.head.user, self.vp.user, self.admin.user):
            with self.subTest(user=user.username):
                self.assertEqual(self.read(user).status_code, 200)

    def test_everybody_else_gets_the_lists_own_flat_404(self):
        """**The refusal's identity, not its status.** A teacher, a bursar, a
        parent and a student each get exactly the body a principal gets for a
        term that does not exist — so "you may not" reads as "there is no such
        thing", and neither a 403 nor a missing route can pass.

        CONTROL 1: the route skipping the authority check makes this red.
        """
        self.take(school_days(10), absent={self.children["emeka"]: 5})
        missing = self.read(self.head.user, term_id=10**9)
        self.assertEqual(missing.status_code, 404, "the fixture's refusal moved")
        self.assertEqual(missing.json(), {"detail": "Not Found"})

        for user in (self.teacher.user, self.bursar.user, self.parent.user, self.student.user):
            with self.subTest(user=user.username):
                for term_id in (None, self.term_id, 10**9):
                    answer = self.read(user, term_id=term_id)

                    self.assertEqual(answer.status_code, 404)
                    self.assertEqual(answer.content, missing.content)
                    self.assertNotIn(b"Emeka", answer.content)

    def test_the_threshold_route_is_refused_the_same_way(self):
        missing = self.read(self.head.user, term_id=10**9)

        for user in (self.teacher.user, self.parent.user):
            with self.subTest(user=user.username):
                answer = self.set_threshold(user, 50, 10)

                self.assertEqual(answer.status_code, 404)
                self.assertEqual(answer.content, missing.content)
        self.assertEqual(self.read(self.head.user).json()["threshold_percent"], 10)

    def test_there_is_no_list_on_the_portal(self):
        self.assertEqual(self.read(self.head.user, host="testserver").status_code, 404)


class TheListIsNotPerChildTests(AbsenceSetUp):
    def test_the_list_does_not_cost_more_as_the_school_grows(self):
        """A fixed number of queries, none per child. **Every** query the
        request makes is counted, and the login is outside the measured
        block, because it is setup."""

        def queries_for_the_list():
            self.client.force_login(self.head.user)
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(LIST, HTTP_HOST=HOST)
            return response, len(captured.captured_queries)

        self.take(school_days(10), absent={self.children["emeka"]: 3})
        _, small = queries_for_the_list()
        extra = []
        with connected_to(self.stmarys):
            group = ClassGroup.objects.get(pk=self.jss1a_id)
            term = Term.objects.get(pk=self.term_id)
        for n in range(3):
            child = enroll_student(
                User.objects.create_user(f"extra{n}", PASSWORD, full_name=f"Extra {n}"), self.stmarys
            )
            with connected_to(self.stmarys):
                academics.place_student(group, term, child)
            extra.append(child)
        self.take(school_days(10, start=date(2025, 10, 1)), absent={c: 5 for c in extra})
        response, larger = queries_for_the_list()

        self.assertEqual(len(response.json()["children"]), 4)
        self.assertEqual(larger, small, "the list costs more per child")


class TheFrameTests(AbsenceSetUp):
    def test_the_frame_names_no_child(self):
        self.take(school_days(10), absent={self.children["emeka"]: 5})
        self.assertIn("Emeka Nwosu", self.listed(), "the control: Emeka is on the list")
        self.client.force_login(self.head.user)

        page = self.client.get("/absences/", HTTP_HOST=HOST).content.decode()

        self.assertIn('id="absences"', page)
        self.assertIn('data-on-school="yes"', page)
        for absent in ("Emeka", "JSS 1A", "St Mary"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_the_portal_frame_says_it_is_not_a_school(self):
        page = self.client.get("/absences/", HTTP_HOST="testserver").content.decode()

        self.assertIn('data-on-school=""', page)
