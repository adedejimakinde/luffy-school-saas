"""Setting a school up: its terms and its class groups, over HTTP.

Two schools in every test, because the failure most likely in a list like this
is that it is not scoped — a read on the wrong connection, a term belonging to
the other school. A single-school fixture cannot fail for either.

Both tables are tenant-local, so there is **no slug in any path**: the
connection has already been pointed at one schema, and a slug would be a second
opinion free to disagree with it.
"""

from datetime import date

from django.db import connection
from django.test.utils import CaptureQueriesContext

from academics.models import ClassGroup, Term, TermName
from results.tests.fixtures import HOST, PORTAL, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

SETUP = "/api/academics/setup/"
TERMS = "/api/academics/terms/"
CLASSES = "/api/academics/classes/"


class TheSetUpScreenTests(ChainSetUp):
    def as_user(self, user):
        self.client.force_login(user.user)

    def setup_for(self, user, host=HOST):
        self.as_user(user)
        return self.client.get(SETUP, HTTP_HOST=host)

    def new_term(self, user, host=HOST, **over):
        self.as_user(user)
        payload = {
            "session": "2026/2027",
            "name": TermName.FIRST.value,
            "starts_on": "2026-09-14",
            "ends_on": "2026-12-11",
        }
        payload.update(over)
        return self.client.post(
            TERMS, data=payload, content_type="application/json", HTTP_HOST=host
        )

    def new_class(self, user, host=HOST, **over):
        self.as_user(user)
        payload = {"name": "JSS 2A", "level": 2}
        payload.update(over)
        return self.client.post(
            CLASSES, data=payload, content_type="application/json", HTTP_HOST=host
        )

    # -- the control, and it runs first --------------------------------------

    def test_the_screen_really_lists_the_schools_shape(self):
        """Every exclusion below would pass against a screen that returned
        nothing for everybody."""
        body = self.setup_for(self.head).json()

        self.assertEqual(sorted(c["name"] for c in body["classes"]), ["JSS 1A", "JSS 1B"])
        self.assertEqual(len(body["terms"]), 2)

    def test_one_schools_shape_is_never_the_others(self):
        ours = self.setup_for(self.head).json()
        theirs = self.setup_for(self.their_head, host=THEIR_HOST).json()

        self.assertEqual(sorted(c["name"] for c in theirs["classes"]), ["JSS 1A"])
        self.assertNotIn("JSS 1B", [c["name"] for c in theirs["classes"]])
        self.assertEqual(len(ours["classes"]), 2)

    def test_the_screen_does_not_cost_more_as_the_school_grows(self):
        """A "45 enrolled" column per class would be a per-group read on the
        screen an administrator opens to add one more group."""
        self.as_user(self.head)
        self.client.get(SETUP, HTTP_HOST=HOST)

        with CaptureQueriesContext(connection) as small:
            self.client.get(SETUP, HTTP_HOST=HOST)

        with connected_to(self.stmarys):
            for n in range(6):
                ClassGroup.objects.create(name=f"JSS 3{n}", level=3)

        with CaptureQueriesContext(connection) as larger:
            body = self.client.get(SETUP, HTTP_HOST=HOST).json()

        self.assertEqual(len(body["classes"]), 8)
        self.assertEqual(
            len(larger.captured_queries),
            len(small.captured_queries),
            "the screen costs more when the school has more classes",
        )

    # -- who may ----------------------------------------------------------------

    def test_a_principal_and_an_administrator_may(self):
        self.assertEqual(self.setup_for(self.head).status_code, 200)
        self.assertEqual(self.new_class(self.head).status_code, 201)

    def test_a_teacher_may_not(self):
        """Office work, not a teacher's. `SETUP_ROLES` is `PLACEMENT_ROLES`."""
        self.assertEqual(self.setup_for(self.teacher).status_code, 403)
        self.assertEqual(self.new_class(self.teacher).status_code, 403)
        self.assertEqual(self.new_term(self.teacher).status_code, 403)

    def test_a_bursar_is_refused_before_anything_is_looked_up(self):
        response = self.setup_for(self.bursar)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("JSS 1A", response.content.decode())

    def test_the_portal_has_no_such_route(self):
        self.assertEqual(self.setup_for(self.head, host=PORTAL).status_code, 404)

    def test_an_administrator_at_one_school_cannot_shape_the_other(self):
        """`SchoolAccessMiddleware` answers before this router does."""
        self.as_user(self.head)

        response = self.client.post(
            CLASSES,
            data={"name": "Smuggled", "level": 9},
            content_type="application/json",
            HTTP_HOST=THEIR_HOST,
        )

        self.assertEqual(response.status_code, 403)
        with connected_to(self.grace):
            self.assertFalse(ClassGroup.objects.filter(name="Smuggled").exists())

    # -- creating a term ------------------------------------------------------

    def test_a_term_is_created_and_is_not_current(self):
        """**Two decisions, deliberately.** A school opening next term's record
        while this one is still being taught is ordinary."""
        body = self.new_term(self.head).json()

        self.assertFalse(body["is_current"])
        with connected_to(self.stmarys):
            self.assertTrue(Term.objects.filter(pk=body["term_id"], is_current=False).exists())
            self.assertEqual(Term.objects.filter(is_current=True).count(), 1)

    def test_a_term_that_ends_before_it_starts_is_refused_with_a_sentence(self):
        response = self.new_term(self.head, starts_on="2026-12-11", ends_on="2026-09-14")

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()["detail"])

    def test_a_next_term_beginning_before_this_one_ends_is_refused(self):
        response = self.new_term(self.head, next_term_starts_on="2026-10-01")

        self.assertEqual(response.status_code, 422)

    def test_a_session_and_name_already_used_is_refused(self):
        response = self.new_term(
            self.head, session="2025/2026", name=TermName.FIRST.value
        )

        self.assertEqual(response.status_code, 422)

    # -- setting the current term ---------------------------------------------

    def test_making_one_current_clears_the_old_one(self):
        """`one_current_term` is a unique constraint on `is_current` where
        true, so setting a second without clearing the first is refused by the
        database. The service does both."""
        created = self.new_term(self.head).json()

        self.as_user(self.head)
        response = self.client.put(
            f"{TERMS}{created['term_id']}/current/", HTTP_HOST=HOST
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_current"])
        with connected_to(self.stmarys):
            current = list(Term.objects.filter(is_current=True).values_list("pk", flat=True))
        self.assertEqual(current, [created["term_id"]], "two terms are current at once")

    def test_making_the_current_term_current_again_is_not_an_error(self):
        """A screen doing it on a double click is not a mistake worth a refusal."""
        self.as_user(self.head)

        response = self.client.put(f"{TERMS}{self.term_id}/current/", HTTP_HOST=HOST)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_current"])

    def test_a_teacher_cannot_change_which_term_is_current(self):
        self.as_user(self.teacher)

        response = self.client.put(f"{TERMS}{self.term_id}/current/", HTTP_HOST=HOST)

        self.assertEqual(response.status_code, 403)

    # -- creating a class group ------------------------------------------------

    def test_a_class_group_is_created_with_the_level_the_school_gave_it(self):
        """`level` is the school's own ordering and is not derived from the
        name: "JSS 1A" sorts before "JSS 10A" as text."""
        body = self.new_class(self.head, name="JSS 10A", level=10).json()

        self.assertEqual(body["level"], 10)
        with connected_to(self.stmarys):
            self.assertTrue(ClassGroup.objects.filter(pk=body["class_group_id"]).exists())

    def test_a_duplicate_class_name_is_refused_with_a_sentence(self):
        response = self.new_class(self.head, name="JSS 1A")

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()["detail"])

    def test_the_same_class_name_is_free_at_the_other_school(self):
        """Per-schema uniqueness. St Mary's having a JSS 1A does not stop Grace
        having one — which it already does, so this asserts the isolation that
        makes the refusal above school-local rather than global."""
        self.as_user(self.their_head)

        response = self.client.post(
            CLASSES,
            data={"name": "JSS 1B", "level": 1},
            content_type="application/json",
            HTTP_HOST=THEIR_HOST,
        )

        self.assertEqual(response.status_code, 201)
