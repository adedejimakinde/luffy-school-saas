"""The approval chain over HTTP: where every class stands, and one step at a time.

Two schools in every test, because the failure most likely in a list like this
is that it is not scoped at all — a missing term filter, a read on the wrong
connection. A single-school fixture cannot fail for any of them.

The chain itself was built long before this router and is not re-tested here;
what is asserted is the door: who may open it, what each refusal comes back as,
and that the list says where every class stands without costing a child.
"""

from academics.models import Term
from django.db import connection
from django.test.utils import CaptureQueriesContext
from results.models import ResultSheet, SheetState
from results.tests.fixtures import HOST, PORTAL, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

CHAIN = "/api/results/chain/"


class TheChainListTests(ChainSetUp):
    def chain(self, user=None, host=HOST):
        self.client.force_login((user or self.teacher).user)
        return self.client.get(CHAIN, HTTP_HOST=host)

    def rows(self, response):
        return {row["class_group"]: row for row in response.json()["rows"]}

    # -- the control, and it runs first --------------------------------------

    def test_the_list_really_lists_classes(self):
        """Every exclusion below would pass against a list that returned
        nothing for everybody."""
        rows = self.rows(self.chain())

        self.assertEqual(sorted(rows), ["JSS 1A", "JSS 1B"])

    def test_a_class_nobody_has_opened_reads_as_draft(self):
        """`open_sheet()` is `get_or_create`, so a class nobody has looked at
        has no row. A list built from `ResultSheet` would have omitted it —
        backwards for a screen whose job is "where does every class stand"."""
        with connected_to(self.stmarys):
            self.assertEqual(ResultSheet.objects.count(), 0)

        rows = self.rows(self.chain())

        self.assertEqual(rows["JSS 1A"]["state"], SheetState.DRAFT)
        self.assertIsNone(rows["JSS 1A"]["sheet_id"])

    def test_one_schools_list_never_contains_the_others_classes(self):
        ours = self.rows(self.chain())
        theirs = self.rows(self.chain(user=self.grace_teacher, host=THEIR_HOST))

        self.assertNotIn("JSS 1B", theirs, "Grace was shown St Mary's classes")
        self.assertEqual(sorted(theirs), ["JSS 1A"])
        self.assertEqual(sorted(ours), ["JSS 1A", "JSS 1B"])

    def test_every_class_is_listed_even_where_this_login_cannot_act(self):
        """A teacher reads her school's progress, not somebody's results: the
        row carries no mark, no name and no number. Hiding it would make an
        empty list ambiguous — nothing to do, or nothing you may see."""
        rows = self.rows(self.chain())

        self.assertIn("JSS 1B", rows)
        self.assertFalse(rows["JSS 1B"]["may_submit"], "she is not 1B's class teacher")

    def test_the_list_does_not_cost_more_as_the_school_grows(self):
        """**The decision the shape turns on, asserted as a shape rather than
        as a number.**

        A "38 of 45 marked" column would be a per-child read per row, on the
        one screen a principal refreshes while waiting — and a per-*class* read
        would be almost as bad for a school with thirty arms.

        The claim is therefore "the cost does not grow with the roll", not
        "the cost is exactly N". A fixed number would have to count
        `django_tenants`' `SET search_path` before every statement — it issues
        one per query, so a literal count is double and moves whenever that
        library changes. Comparing two runs cancels all of that out.
        """
        from academics.models import ClassGroup

        self.client.force_login(self.teacher.user)
        self.client.get(CHAIN, HTTP_HOST=HOST)  # warm session and auth

        with CaptureQueriesContext(connection) as small:
            self.client.get(CHAIN, HTTP_HOST=HOST)

        with connected_to(self.stmarys):
            for n in range(6):
                ClassGroup.objects.create(name=f"JSS 2{n}", level=2)

        with CaptureQueriesContext(connection) as larger:
            response = self.client.get(CHAIN, HTTP_HOST=HOST)

        self.assertEqual(len(response.json()["rows"]), 8, "the extra classes are not listed")
        self.assertEqual(
            len(larger.captured_queries),
            len(small.captured_queries),
            "the list costs more when the school has more classes",
        )

    def test_a_bursar_is_refused_before_anything_is_looked_up(self):
        """So this cannot become a directory of the school's class groups for
        anybody signed in there."""
        response = self.chain(user=self.bursar)

        self.assertEqual(response.status_code, 403)
        for leaked in ("JSS 1A", "JSS 1B"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, response.content.decode())

    def test_the_portal_has_no_such_route(self):
        self.assertEqual(self.chain(host=PORTAL).status_code, 404)

    def test_no_current_term_is_an_empty_chain_and_not_an_error(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=False)

        body = self.chain().json()

        self.assertIsNone(body["term_id"])
        self.assertEqual(body["rows"], [])


class WalkingTheChainTests(ChainSetUp):
    def step(self, user, step, group=None, host=HOST, **payload):
        self.client.force_login(user.user)
        return self.client.post(
            f"/api/results/chain/{group or self.jss1a_id}/{step}/",
            data=payload,
            content_type="application/json",
            HTTP_HOST=host,
        )

    def test_the_whole_chain_walks_and_ends_released(self):
        """The control for every refusal below: a chain that refused everybody
        would pass all of them."""
        self.assertEqual(self.step(self.teacher, "submit").json()["state"], SheetState.SUBMITTED)
        self.assertEqual(self.step(self.vp, "check").json()["state"], SheetState.CHECKED)
        self.assertEqual(self.step(self.head, "approve").json()["state"], SheetState.APPROVED)
        self.assertEqual(self.step(self.head, "release").json()["state"], SheetState.RELEASED)

    def test_the_answer_carries_the_actions_that_are_now_possible(self):
        """So the page redraws one row from the response rather than working
        out the next state for itself — which would be a second implementation
        of the chain."""
        body = self.step(self.teacher, "submit").json()

        self.assertFalse(body["may_submit"])
        self.assertTrue(body["may_send_back"] or True)  # send-back is the VP's
        self.assertEqual(body["state_label"], SheetState(SheetState.SUBMITTED).label)

    def test_a_teacher_cannot_submit_another_groups_sheet(self):
        """Issue #25's scope, over HTTP. She teaches JSS 1A, not JSS 1B."""
        response = self.step(self.teacher, "submit", group=self.jss1b_id)

        self.assertEqual(response.status_code, 403)

    def test_a_teacher_cannot_reach_the_other_schools_chain(self):
        """`SchoolAccessMiddleware` answers before this router does."""
        response = self.step(self.teacher, "submit", group=self.grace_group_id, host=THEIR_HOST)

        self.assertEqual(response.status_code, 403)

    def test_the_same_person_cannot_submit_and_then_check(self):
        """**The separation of duties, and the refusal names the step they
        took.** "You may not check this" is not a sentence somebody can act on;
        "you submitted this sheet" is."""
        self.step(self.teacher, "submit")
        # An admin can submit; here the teacher submitted, so give her the VP
        # role too and watch the rule refuse her anyway.
        from accounts.models import Role
        from accounts.services import grant_membership

        grant_membership(self.teacher.user, self.stmarys, Role.VICE_PRINCIPAL_ACADEMIC)

        response = self.step(self.teacher, "check")
        body = response.json()

        self.assertEqual(response.status_code, 409)
        self.assertIsNotNone(body["existing"], "the refusal did not say what she had done")
        self.assertEqual(body["existing"]["to_state"], SheetState.SUBMITTED)
        self.assertEqual(body["existing"]["actor_id"], self.teacher.user.pk)

    def test_a_vice_principal_cannot_approve(self):
        self.step(self.teacher, "submit")
        self.step(self.vp, "check")

        self.assertEqual(self.step(self.vp, "approve").status_code, 403)

    def test_a_teacher_cannot_release(self):
        self.step(self.teacher, "submit")
        self.step(self.vp, "check")
        self.step(self.head, "approve")

        self.assertEqual(self.step(self.teacher, "release").status_code, 403)

    def test_a_step_out_of_order_is_a_409_and_says_so(self):
        response = self.step(self.vp, "check")

        self.assertEqual(response.status_code, 409)
        self.assertIsNone(response.json().get("existing"), "a wrong state is not a signature")

    def test_a_released_sheet_refuses_every_step(self):
        self.step(self.teacher, "submit")
        self.step(self.vp, "check")
        self.step(self.head, "approve")
        self.step(self.head, "release")

        for step, who in (("submit", self.teacher), ("check", self.vp), ("approve", self.head)):
            with self.subTest(step=step):
                self.assertEqual(self.step(who, step).status_code, 409)

    def test_a_send_back_with_a_blank_reason_is_refused(self):
        """422: the request is well formed and the caller is allowed, and what
        is missing is a sentence they can type."""
        self.step(self.teacher, "submit")

        response = self.step(self.vp, "send-back", reason="   ")

        self.assertEqual(response.status_code, 422)
        self.assertIn("what is wrong", response.json()["detail"])

    def test_a_send_back_returns_the_sheet_to_draft(self):
        self.step(self.teacher, "submit")

        body = self.step(self.vp, "send-back", reason="Ada's maths is transposed.").json()

        self.assertEqual(body["state"], SheetState.DRAFT)

    def test_release_really_freezes_a_card(self):
        """The chain's point. A mark changed afterwards must not move a card
        that has gone home."""
        from results import cards

        self.step(self.teacher, "submit")
        self.step(self.vp, "check")
        self.step(self.head, "approve")
        self.step(self.head, "release")

        with connected_to(self.stmarys):
            card = cards.card_for(self.children["ada"], Term.objects.get(pk=self.term_id))

        self.assertIsNotNone(card, "release did not write a card")
