"""The sheet is one class group's, at one school — asserted across two schemas.

**Two schools in every test here, and that is the point rather than
thoroughness.** The failure most likely in a roster query is that it is not
scoped at all: a missing `term` filter, a uniqueness that should be per-schema,
a read on the wrong connection. A single-school fixture cannot fail for any of
them, which is the argument `attendance.tests.fixtures` makes at length and the
reason this module subclasses its fixture rather than building a third one.

The scope here is a **view** scope, not an authority narrowing.
`can_enter_marks()` is untouched and still school-wide; who may mark is issue
#128. And a sheet cannot be scoped by *subject* at all — issue #127, because
nothing models which students take which subject.
"""

from academics.models import Term
from gradebook.tests.fixtures import MarkingSetUp
from results.models import ResultSheet, SheetState
from schools.models import Domain, School
from schools.tests.tenants import connected_to

HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"


class TheSheetIsOneGroupsTests(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=THEIR_HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

    def sheet(self, *, assessment, group, host=HOST, user=None):
        self.client.force_login((user or self.teacher).user)
        return self.client.get(
            f"/api/gradebook/assessments/{assessment}/sheet/?class_group_id={group}",
            HTTP_HOST=host,
        )

    def names_in(self, response):
        return sorted(row["student"] for row in response.json()["rows"])

    # -- the control, and it runs first --------------------------------------

    def test_the_sheet_really_lists_children(self):
        """Every exclusion below would pass against a sheet that returned
        nothing for everybody."""
        names = self.names_in(self.sheet(assessment=self.first_ca_id, group=self.jss1a_id))

        self.assertEqual(
            names, ["Ada Obi", "Bisi Ade", "Emeka Nwosu", "Tunde Cole"]
        )

    # -- the class scope -----------------------------------------------------

    def test_another_group_at_the_same_school_is_absent(self):
        """JSS 1B has its own child, so this is a scope test rather than a
        claim about an empty group."""
        names = self.names_in(self.sheet(assessment=self.first_ca_id, group=self.jss1b_id))

        self.assertEqual(names, ["Bimpe Ojo"])

    def test_the_whole_school_is_no_longer_one_sheet(self):
        """What this change removed. `Assessment` carries a term and a subject
        and no class group, so the sheet used to be `school_directory()` —
        every student in the school, Primary 1 beside JSS 3B."""
        jss1a = self.names_in(self.sheet(assessment=self.first_ca_id, group=self.jss1a_id))

        self.assertNotIn("Bimpe Ojo", jss1a, "a child from another group is on this sheet")

    # -- the school scope ----------------------------------------------------

    def test_a_sheet_at_one_school_cannot_answer_for_the_other(self):
        """Grace has its own term, group, child and assessment, with ids
        numbered independently — so this cannot pass on a coincidence."""
        ours = self.names_in(self.sheet(assessment=self.first_ca_id, group=self.jss1a_id))
        theirs = self.names_in(
            self.sheet(
                assessment=self.grace_ca_id,
                group=self.grace_group_id,
                host=THEIR_HOST,
                user=self.grace_teacher,
            )
        )

        self.assertNotIn("Chidi Eze", ours)
        self.assertEqual(theirs, ["Chidi Eze"])

    def test_a_teacher_at_one_school_is_refused_at_the_other(self):
        """`SchoolAccessMiddleware` answers before the gradebook does. Asserted
        so the isolation above is not resting on the ids alone."""
        self.client.force_login(self.teacher.user)

        response = self.client.get(
            f"/api/gradebook/assessments/{self.grace_ca_id}/sheet/"
            f"?class_group_id={self.grace_group_id}",
            HTTP_HOST=THEIR_HOST,
        )

        self.assertEqual(response.status_code, 403)

    # -- locked --------------------------------------------------------------

    def test_an_open_sheet_says_so_before_anybody_types(self):
        body = self.sheet(assessment=self.first_ca_id, group=self.jss1a_id).json()

        self.assertFalse(body["locked"])
        self.assertIsNone(body["locked_reason"])

    def test_a_submitted_sheet_is_reported_locked_with_a_reason(self):
        """**The whole point of the flag.** This screen saves on blur, so
        without it a teacher types a mark into a cell that cannot accept it and
        learns from the 423 afterwards."""
        with connected_to(self.stmarys):
            ResultSheet.objects.create(
                class_group=self.jss1a,
                term=Term.objects.get(pk=self.term_id),
                state=SheetState.SUBMITTED,
            )

        body = self.sheet(assessment=self.first_ca_id, group=self.jss1a_id).json()

        self.assertTrue(body["locked"])
        self.assertIn("JSS 1A", body["locked_reason"])

    def test_locking_one_group_does_not_lock_the_other(self):
        """The flag is a fact about *this* sheet. A sheet-level flag that was
        really a school-level one would fail here."""
        with connected_to(self.stmarys):
            ResultSheet.objects.create(
                class_group=self.jss1a,
                term=Term.objects.get(pk=self.term_id),
                state=SheetState.SUBMITTED,
            )

        other = self.sheet(assessment=self.first_ca_id, group=self.jss1b_id).json()

        self.assertFalse(other["locked"], "locking JSS 1A locked JSS 1B too")


class WhereToMarkTests(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

    def where(self, user=None, host=HOST):
        self.client.force_login((user or self.teacher).user)
        return self.client.get("/api/gradebook/where/", HTTP_HOST=host)

    def test_a_marker_is_told_the_assessments_and_the_current_term(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=True)

        body = self.where().json()

        self.assertEqual(body["term_id"], self.term_id)
        self.assertEqual(
            [(a["subject"], a["name"]) for a in body["assessments"]],
            [("Mathematics", "First CA")],
        )
        self.assertEqual(
            sorted(g["name"] for g in body["classes"]), ["JSS 1A", "JSS 1B"]
        )

    def test_no_current_term_is_reported_rather_than_guessed(self):
        body = self.where().json()

        self.assertIsNone(body["term_id"])
        self.assertEqual(body["assessments"], [])

    def test_a_bursar_is_refused_before_anything_is_looked_up(self):
        """So this cannot become a directory of the school's subjects and
        classes for anybody signed in there."""
        response = self.where(user=self.bursar)

        self.assertEqual(response.status_code, 403)
        for leaked in ("Mathematics", "JSS 1A", "First CA"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, response.content.decode())

    def test_the_portal_has_no_such_route(self):
        self.assertEqual(self.where(host="testserver").status_code, 404)
