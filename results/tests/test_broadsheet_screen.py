"""The broadsheet screen's two new routes, and its frame.

`/api/results/broadsheets/` lists the terms a reader can choose; `/overview/`
is every class's average for one term, with no names and no ranks. Both are
behind the broadsheet's own authority and its flat 404: a list of terms and
classes is a directory of the school, and "you may not" must read the same as
"there is no such thing".

**The overview's number is the page's number.** The test that holds that is
the one on a released class whose roster moved after release — issue #55's
shape, and the one place the live marks and the frozen cards disagree.

Terms and classes are tenant tables, so what keeps Grace's out of St Mary's
answer is the schema the host selects, not a filter here; the two-school tests
say so rather than implying a `school=` that does not exist.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext

from academics.models import ClassGroup, Term
from results.tests.test_positions import connected_to
from results.tests.test_positions_api import HOST, THEIR_HOST, BroadsheetApiSetUp

TERMS = "/api/results/broadsheets/"


class BroadsheetScreenSetUp(BroadsheetApiSetUp):
    def terms(self, user, host=HOST):
        self.client.force_login(user)
        return self.client.get(TERMS, HTTP_HOST=host)

    def overview(self, user, host=HOST, term_id=None):
        self.client.force_login(user)
        return self.client.get(
            f"/api/results/overview/?term_id={term_id or self.term_id}", HTTP_HOST=host
        )

    def jss1a(self, body):
        return next(c for c in body["classes"] if c["class_group_id"] == self.group_id)


class TheTermsTests(BroadsheetScreenSetUp):
    def test_the_terms_really_list(self):
        """The control, and it runs first."""
        response = self.terms(self.principal)

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.term_id, [t["term_id"] for t in response.json()["terms"]])

    def test_every_role_that_reads_a_broadsheet_reads_the_terms(self):
        for user in (self.teacher, self.vp, self.principal, self.registrar):
            with self.subTest(user=user.username):
                self.assertEqual(self.terms(user).status_code, 200)

    def test_a_parent_a_student_and_a_bursar_get_the_broadsheets_own_refusal(self):
        """**The refusal's identity, not its status.** Each gets exactly the
        body the broadsheet route refuses them with — the flat 404 — so a 403
        from anywhere else, or a route that is simply missing, cannot pass.

        CONTROL 1: the route skipping `_require_position_authority()` makes this
        red. CONTROL 2: the route refusing with a 403 instead makes it red too.
        """
        for user in (self.parent_user, self.student_user, self.bursar):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                refused_there = self.get()
                self.assertEqual(refused_there.status_code, 404, "the fixture's refusal moved")

                response = self.terms(user)

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, refused_there.content)
                self.assertNotIn(b"term", response.content)

    def test_there_are_no_terms_on_the_portal(self):
        self.assertEqual(self.terms(self.principal, host="testserver").status_code, 404)

    def test_another_schools_term_is_not_listed(self):
        """Isolation by schema: Grace's term lives in Grace's tables."""
        with connected_to(self.grace):
            theirs = Term.objects.create(
                session="2031/2032", name="first", starts_on="2031-09-08", ends_on="2031-12-12"
            )

        ours = self.terms(self.principal).json()["terms"]

        self.assertNotIn("2031/2032", str(ours))
        self.assertNotIn(theirs.pk, [t["term_id"] for t in ours if t["term"].startswith("2031")])


class TheOverviewTests(BroadsheetScreenSetUp):
    def test_the_overview_really_lists_the_class(self):
        """The control: Ada on 88, Bisi on 61."""
        row = self.jss1a(self.overview(self.principal).json())

        self.assertEqual(row["class_average"], "74.50")
        self.assertEqual(row["children_with_an_average"], 2)
        self.assertFalse(row["from_snapshot"])

    def test_no_names_and_no_ranks(self):
        """It compares classes. Whoever wants children opens the class."""
        response = self.overview(self.principal)

        for absent in (b"Ada A", b"Bisi B", b"rank", b"position", b"student"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, response.content)

    def test_the_overview_equals_the_page_while_the_term_is_live(self):
        self.client.force_login(self.principal)
        page = self.get().json()

        self.assertEqual(
            self.jss1a(self.overview(self.principal).json())["class_average"],
            page["class_average"],
        )

    def test_the_overview_equals_the_page_for_a_released_class_whose_roster_moved(self):
        """**Issue #55's shape.** After release, Ada transfers out: the live
        roster now says 61.00 and the frozen cards still say 74.50. The page
        says 74.50, and so must the overview — the figures that went home.

        CONTROL 6: the overview reading live marks for a released term makes
        this red.
        """
        self.release_the_term()
        self.transfer_out(self.child)
        self.assertNotEqual(
            str(self.live_results().class_average),
            "74.50",
            "the live roster did not move, so this proves nothing",
        )
        self.client.force_login(self.principal)
        page = self.get().json()

        row = self.jss1a(self.overview(self.principal).json())

        self.assertTrue(page["from_snapshot"])
        self.assertEqual(page["class_average"], "74.50")
        self.assertEqual(row["class_average"], page["class_average"])
        self.assertEqual(row["children_with_an_average"], 2)
        self.assertTrue(row["from_snapshot"])

    def test_a_class_with_no_marks_is_a_dash_not_a_zero(self):
        with connected_to(self.stmarys):
            empty = ClassGroup.objects.create(name="JSS 3C", level=3)

        row = next(
            c for c in self.overview(self.principal).json()["classes"]
            if c["class_group_id"] == empty.pk
        )

        self.assertIsNone(row["class_average"])
        self.assertEqual(row["children_with_an_average"], 0)

    def test_a_class_retired_after_release_keeps_its_row_for_that_term(self):
        self.release_the_term()
        with connected_to(self.stmarys):
            ClassGroup.objects.filter(pk=self.group_id).update(is_active=False)

        row = self.jss1a(self.overview(self.principal).json())

        self.assertEqual(row["class_average"], "74.50")

    def test_it_is_refused_exactly_as_the_broadsheet_is(self):
        for user in (self.parent_user, self.bursar):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                refused_there = self.get()

                response = self.overview(user)

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, refused_there.content)

    def test_a_missing_term_and_a_refusal_are_not_told_apart(self):
        self.client.force_login(self.bursar)
        refused = self.overview(self.bursar)
        missing = self.overview(self.bursar, term_id=99999)

        self.assertEqual(refused.content, missing.content)

    def test_their_principal_sees_their_classes_on_their_host(self):
        body = self.overview(self.their_principal, host=THEIR_HOST).json()

        self.assertNotIn("74.50", str(body))

    def test_the_overview_does_not_cost_more_as_a_class_grows(self):
        """A fixed number of queries per class, none per child.

        Counts the route's **data** queries only. The first version counted
        everything and failed 36 != 56 on plumbing alone — the session writes
        `force_login()` makes, savepoints, and `SET search_path`, whose count
        depends on which schema the fixture's own helpers left the connection
        on. None of that is the overview's work, and a count that includes it
        measures the fixture.
        """
        plumbing = ("SET search_path", "SAVEPOINT", "RELEASE SAVEPOINT", "django_session")

        def data_queries():
            self.client.force_login(self.principal)
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(
                    f"/api/results/overview/?term_id={self.term_id}", HTTP_HOST=HOST
                )
            return response, [
                q["sql"] for q in captured.captured_queries
                if not any(word in q["sql"] for word in plumbing)
            ]

        _, small = data_queries()
        for n in range(3):
            child = self.enrol(self.stmarys, f"extra{n}", f"Extra {n}", self.group_id, self.term_id)
            self.mark(self.stmarys, self.term_id, self.maths_id, child, 50 + n)
        response, larger = data_queries()

        self.assertEqual(self.jss1a(response.json())["children_with_an_average"], 5)
        self.assertEqual(len(larger), len(small), "the overview costs more per child")


class TheFrameTests(BroadsheetScreenSetUp):
    def test_the_frame_names_no_child_and_no_class(self):
        self.client.force_login(self.principal)
        self.assertIn("Ada A", str(self.get().json()), "the control: Ada is on the sheet")

        page = self.client.get("/broadsheet/", HTTP_HOST=HOST).content.decode()

        self.assertIn('id="broadsheet"', page)
        self.assertIn('data-on-school="yes"', page)
        for absent in ("Ada A", "JSS 1A", "74.50", "St Mary"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_the_portal_frame_says_it_is_not_a_school(self):
        self.client.force_login(self.principal)

        page = self.client.get("/broadsheet/", HTTP_HOST="testserver").content.decode()

        self.assertIn('data-on-school=""', page)
