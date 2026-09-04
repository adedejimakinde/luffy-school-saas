"""Who can see a position, asked of the HTTP surface rather than the function.

The rule is not a rendering preference and cannot be enforced in a template:

> Position is **staff-only**. It must not reach a parent or a student, in a card
> or in a payload. Enforced at the serializer, because omitting a field from a
> card while leaving it in the JSON is the same leak with an extra step.

So these tests ask the endpoint, through the real middleware stack, as each kind
of caller — and the parent's and student's assertions are about the *bytes that
came back*, not about a flag. `assertNotIn("position", response.content)` is
deliberately cruder than parsing: a leak that renamed the field, nested it, or
put it in an error body would still be a leak, and a structural assertion on
parsed JSON would walk straight past it.

Not `RequestFactory`, for the reason `gradebook/tests/test_api.py` gives: these
are tenant tables and `TenantMainMiddleware` chooses the schema from the
hostname. A test that skipped it would be querying whichever schema the
connection was left on.

Two schools, both with hosts, because "can St Mary's principal read Grace
Academy's broadsheet" is a question about the middleware and the authority check
together, and neither one alone answers it.
"""

from django.db import IntegrityError, connection, transaction

from academics.models import ClassGroup, ClassPlacement, Term
from accounts.models import Role, User
from accounts.services import grant_membership, link_guardian
from gradebook.models import Subject
from results.tests.test_positions import PASSWORD, PositionSetUp, connected_to
from schools.models import Domain, School

HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"


class BroadsheetApiSetUp(PositionSetUp):
    def setUp(self):
        super().setUp()

        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=THEIR_HOST, is_primary=True)

        # The portal. No schema of its own; it is the public one.
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        self.teacher = self._staff("kemi", "Kemi Bello", Role.TEACHER)
        self.vp = self._staff("ngozi", "Ngozi Eze", Role.VICE_PRINCIPAL_ACADEMIC)
        self.registrar = self._staff("bola", "Bola Ade", Role.ADMIN)
        self.bursar = self._staff("femi", "Femi Cash", Role.BURSAR)

        # A child with marks, and their parent.
        self.child = self.enrol(
            self.stmarys, "ada", "Ada A", self.group_id, self.term_id
        )
        self.classmate = self.enrol(
            self.stmarys, "bisi", "Bisi B", self.group_id, self.term_id
        )
        self.mark(self.stmarys, self.term_id, self.maths_id, self.child, 88)
        self.mark(self.stmarys, self.term_id, self.maths_id, self.classmate, 61)

        self.parent_user = User.objects.create_user(
            "mama", PASSWORD, full_name="Mama Ada"
        )
        link_guardian(self.parent_user, self.child)

        self.student_user = self.child.user

    def _staff(self, username, full_name, role):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, self.stmarys, role)
        return user

    def tearDown(self):
        # `TenantMainMiddleware` leaves the connection on the school's schema,
        # and `School.save()` refuses to create a tenant from anywhere but
        # public — so without this the failure lands in an unrelated suite.
        connection.set_schema_to_public()
        super().tearDown()

    def signed_in(self, user, host=HOST):
        self.client.force_login(user)
        return self.get(host=host)

    def get(self, host=HOST, group_id=None, term_id=None):
        return self.client.get(
            f"/api/results/classes/{group_id or self.group_id}/broadsheet/"
            f"?term_id={term_id or self.term_id}",
            HTTP_HOST=host,
        )

    def release_the_term(self):
        """JSS 1A's first term, all the way through the chain. Returns the sheet.

        A class teacher first, because the chain refuses to move without one:
        "JSS 1A has no class teacher for First term, so nobody may submit its
        results yet."
        """
        from academics.services import assign_class_teacher
        from accounts.models import Membership
        from results import services as results_services

        with connected_to(self.stmarys):
            assign_class_teacher(
                ClassGroup.objects.get(pk=self.group_id),
                Term.objects.get(pk=self.term_id),
                Membership.objects.get(
                    user=self.teacher, school=self.stmarys, role=Role.TEACHER
                ),
            )
            sheet = results_services.open_sheet(
                ClassGroup.objects.get(pk=self.group_id),
                Term.objects.get(pk=self.term_id),
                self.principal,
            )
            results_services.submit(sheet, self.teacher)
            results_services.check(sheet, self.vp)
            results_services.approve(sheet, self.principal)
            results_services.release(sheet, self.principal)
            return sheet

    def transfer_out(self, membership):
        """Move one child into a second group, the way a mid-term transfer does.

        This is the roster lever the tests below need, and it is the *only* one
        release leaves open: `gradebook`'s `0002` trigger refuses a mark on a
        released term outright, while nothing refuses a placement. Which is
        issue #55 in one sentence — the marks lock and the roster does not.
        """
        from academics.services import move_student

        with connected_to(self.stmarys):
            other = ClassGroup.objects.filter(name="JSS 1B").first() or (
                ClassGroup.objects.create(name="JSS 1B", level=1)
            )
            move_student(other, Term.objects.get(pk=self.term_id), membership)
            return other

    def live_results(self):
        """What `positions` says about JSS 1A *now* — the other of the two answers."""
        from results import positions

        with connected_to(self.stmarys):
            return positions.class_results(
                ClassGroup.objects.get(pk=self.group_id),
                Term.objects.get(pk=self.term_id),
            )

    def rows_of(self, payload):
        return {row["student_membership_id"]: row for row in payload["rows"]}


class StaffCanSeeThePositionTests(BroadsheetApiSetUp):
    def test_each_admitted_role_gets_the_broadsheet(self):
        for actor in (self.teacher, self.vp, self.principal, self.registrar):
            with self.subTest(actor=str(actor)):
                self.client.logout()
                response = self.signed_in(actor)
                self.assertEqual(response.status_code, 200, response.content)
                body = response.json()
                rows = {r["student_membership_id"]: r for r in body["rows"]}
                self.assertEqual(rows[self.child.pk]["current_rank"], 1)
                self.assertEqual(rows[self.classmate.pk]["current_rank"], 2)

    def test_the_class_average_is_staff_visible_and_computed_not_stored(self):
        response = self.signed_in(self.principal)
        self.assertEqual(response.json()["class_average"], "74.50")

    def test_a_subject_position_is_on_every_row(self):
        response = self.signed_in(self.principal)
        rows = {r["student_membership_id"]: r for r in response.json()["rows"]}
        maths = [
            s for s in rows[self.child.pk]["subjects"] if s["subject_id"] == self.maths_id
        ][0]
        self.assertEqual(maths["current_subject_rank"], 1)
        self.assertEqual(maths["percentage"], "88.00")

    def test_the_columns_are_the_subjects_the_class_was_marked_in(self):
        """Not every subject the school has a row for.

        `setUp` creates Mathematics *and* English and marks only Mathematics, so
        a broadsheet built from `Subject.objects.all()` carries an all-blank
        English column here. The subject table is per school and deliberately
        keeps subjects nobody is taught any more — `is_active` reads "a subject
        no longer taught. Kept, because old scores name it" — so on a real
        school that column is one per retired subject and one per subject taught
        only to another year group.

        Asserted at the API because that is the surface it reaches. The control
        run that broke `class_results()` into listing the whole table failed the
        unit test and left all sixteen tests in this module passing, which said
        the payload itself was unpinned.
        """
        with connected_to(self.stmarys):
            retired = Subject.objects.create(
                name="Technical Drawing", code="TD", is_active=False
            )

        response = self.signed_in(self.principal)
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["rows"]
        self.assertEqual(len(rows), 2)

        for row in rows:
            with self.subTest(student=row["student"]):
                self.assertEqual(
                    [s["subject_id"] for s in row["subjects"]],
                    [self.maths_id],
                    "a subject with no marks in this class became a column",
                )
                self.assertNotIn(
                    retired.pk, [s["subject_id"] for s in row["subjects"]]
                )

    def test_an_unmarked_child_comes_back_blank_rather_than_zero(self):
        absent = self.enrol(
            self.stmarys, "chika", "Chika C", self.group_id, self.term_id
        )
        response = self.signed_in(self.principal)
        rows = {r["student_membership_id"]: r for r in response.json()["rows"]}

        self.assertIsNone(rows[absent.pk]["average"])
        self.assertIsNone(rows[absent.pk]["current_rank"])


class PositionNeverReachesAFamilyTests(BroadsheetApiSetUp):
    """The half of the rule that matters, asserted on the raw bytes."""

    def test_a_parent_gets_nothing_and_the_response_carries_no_position(self):
        response = self.signed_in(self.parent_user)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"position", response.content.lower())

    def test_a_student_gets_nothing_and_the_response_carries_no_position(self):
        response = self.signed_in(self.student_user)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"position", response.content.lower())

    def test_an_unauthenticated_caller_gets_nothing(self):
        """**401, not the flat 404 the authenticated refusals give.**

        The router's `session_auth` answers before the view runs, so
        `_require_position_authority()` is never reached. That is not a hole in
        the oracle argument: a 401 is returned whether or not the class exists,
        so it discloses nothing either. The distinction only has to hold among
        callers who got *past* authentication.

        This is the shape the unauthenticated result checker will be. It does
        not exist yet, and when it does it must be built from its own schema
        rather than by filtering this one — issue #21.
        """
        response = self.get()

        self.assertEqual(response.status_code, 401)
        self.assertNotIn(b"position", response.content.lower())

    def test_a_bursar_is_not_admitted_either(self):
        """Staff, but not this staff. A bursar keeps the books."""
        response = self.signed_in(self.bursar)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"position", response.content.lower())

    def test_no_class_average_leaks_to_a_parent_either(self):
        """Settled with position: the class average is a fact about forty-five
        other children, so it is staff-only for the same reason."""
        response = self.signed_in(self.parent_user)

        self.assertNotIn(b"class_average", response.content.lower())
        self.assertNotIn(b"74.50", response.content)


class ARosterRowNamingAnotherSchoolsChildTests(BroadsheetApiSetUp):
    """The roster is bare integers, so the name lookup has to be narrow.

    `ClassPlacement.student_membership_id` points into the shared `public`
    membership table with **no foreign key and no database integrity** — the
    policy `docs/tenancy.md` settles for every cross-schema reference in this
    project. `academics.services.place_student()` checks the id names a student
    of this school, but that check runs at write time and is the only thing
    standing there: a row inserted by a bad import, a data migration or a hand
    edit carries whatever id it was given.

    So the question this asks is what the broadsheet does with a roster row it
    should never have had. Looking names up unscoped, it prints another school's
    child's real name — a cross-tenant disclosure produced by a *read*, from a
    view that is behaving correctly otherwise. Looked up narrowly, the row has no
    name and renders the same blank an unmarked child gets.

    Written by inserting the row directly, on purpose. Going through
    `place_student()` would be testing the write-time guard, which already has
    its own tests; this is about the read not trusting it.
    """

    def setUp(self):
        super().setUp()
        self.their_child = self.enrol(
            self.grace, "chika", "Chika C", self.their_group_id, self.their_term_id
        )
        with connected_to(self.stmarys):
            ClassPlacement.objects.create(
                class_group=ClassGroup.objects.get(pk=self.group_id),
                term=Term.objects.get(pk=self.term_id),
                student_membership_id=self.their_child.pk,
            )

    def test_the_other_schools_child_is_not_named_on_our_sheet(self):
        response = self.signed_in(self.principal)
        self.assertEqual(response.status_code, 200, response.content)

        self.assertNotIn(
            b"Chika C",
            response.content,
            "a placement row carrying another school's membership id put that "
            "child's real name on this school's broadsheet",
        )

    def test_the_row_renders_blank_rather_than_disappearing(self):
        """Blank, not dropped.

        The row is still on the roster and still wrong, and a sheet that hides
        it hides the corruption too. A dash is the same answer an unmarked child
        gets, and it is the one a school can see and ask about.
        """
        response = self.signed_in(self.principal)
        rows = {r["student_membership_id"]: r for r in response.json()["rows"]}

        self.assertIn(self.their_child.pk, rows)
        self.assertEqual(rows[self.their_child.pk]["student"], "—")
        self.assertIsNone(rows[self.their_child.pk]["average"])
        self.assertIsNone(rows[self.their_child.pk]["current_rank"])

    def test_our_own_children_are_still_named(self):
        """The control on the control: narrowing must not blank the whole sheet."""
        response = self.signed_in(self.principal)
        rows = {r["student_membership_id"]: r for r in response.json()["rows"]}

        self.assertEqual(rows[self.child.pk]["student"], "Ada A")
        self.assertEqual(rows[self.classmate.pk]["student"], "Bisi B")


class TheRefusalIsNotAnExistenceOracleTests(BroadsheetApiSetUp):
    """A 404, not a 403, on the reasoning `gradebook.api` settled.

    A parent who could tell "you may not read this class" from "no such class"
    could map the school's entire class list by walking ids. Both answers have
    to be the same answer.
    """

    def test_a_real_class_and_a_missing_one_refuse_identically(self):
        self.client.force_login(self.parent_user)
        real = self.get()
        missing = self.get(group_id=99999)

        self.assertEqual(real.status_code, missing.status_code)
        self.assertEqual(real.content, missing.content)

    def test_the_refusal_does_not_depend_on_the_term_existing(self):
        self.client.force_login(self.parent_user)
        real = self.get()
        missing_term = self.get(term_id=99999)

        self.assertEqual(real.status_code, missing_term.status_code)
        self.assertEqual(real.content, missing_term.content)


class OneSchoolsStaffCannotReadAnothersTests(BroadsheetApiSetUp):
    def test_our_principal_is_refused_at_the_other_schools_host(self):
        """**403 from the door, not this view's 404.**

        `SchoolAccessMiddleware` refuses anybody with no active membership at
        the school whose host they asked for, before routing. So the refusal
        never reaches `_require_position_authority()` at all — worth pinning as
        the layer that actually answers, because a change to this view's
        refusals would not change this case and somebody would assume it had.
        """
        response = self.signed_in(self.principal, host=THEIR_HOST)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"position", response.content.lower())

    def test_their_principal_reads_their_own_class_and_sees_only_their_children(self):
        theirs = self.enrol(
            self.grace, "uche", "Uche U", self.their_group_id, self.their_term_id
        )
        self.mark(self.grace, self.their_term_id, self.their_maths_id, theirs, 95)

        self.client.force_login(self.their_principal)
        response = self.get(
            host=THEIR_HOST,
            group_id=self.their_group_id,
            term_id=self.their_term_id,
        )

        self.assertEqual(response.status_code, 200, response.content)
        ids = {r["student_membership_id"] for r in response.json()["rows"]}
        self.assertEqual(ids, {theirs.pk})
        self.assertNotIn(self.child.pk, ids)

    def test_there_is_no_broadsheet_on_the_portal(self):
        """The tables are not there at all, so a 404 rather than a 403 — the
        answer `gradebook.api._school_of()` gives on the same host."""
        response = self.signed_in(self.principal, host="testserver")

        self.assertEqual(response.status_code, 404)


class AnUnreleasedTermStillReadsLiveMarksTests(BroadsheetApiSetUp):
    def test_a_new_mark_changes_the_position_immediately(self):
        """An unreleased term has no snapshot to serve, so it reads live marks —
        and must keep doing so, or a teacher would not see their own marking.

        This class used to be `TheEndpointReadsLiveMarksForNowTests` and its
        docstring said "once task 3 lands, a released term must be served from
        the snapshot instead". Task 3 landed in #44 and the switch was not made;
        issue #55 is what that cost. The "for now" is gone because the other
        half now exists — see `AReleasedTermIsServedFromTheSnapshotTests`.
        """
        before = self.signed_in(self.principal).json()
        rows = {r["student_membership_id"]: r for r in before["rows"]}
        self.assertEqual(rows[self.child.pk]["current_rank"], 1)
        self.assertEqual(rows[self.classmate.pk]["current_rank"], 2)

        # Maths stands at 88 and 61. English flips it: the child averages
        # (88 + 30) / 2 = 59, the classmate (61 + 100) / 2 = 80.5.
        self.mark(self.stmarys, self.term_id, self.english_id, self.child, 30)
        self.mark(self.stmarys, self.term_id, self.english_id, self.classmate, 100)

        after = self.signed_in(self.principal).json()
        rows = {r["student_membership_id"]: r for r in after["rows"]}
        self.assertEqual(rows[self.classmate.pk]["current_rank"], 1)
        self.assertEqual(rows[self.child.pk]["current_rank"], 2)


class TheSchemaComesFromTheHostNotThePathTests(BroadsheetApiSetUp):
    def test_the_same_class_id_means_a_different_class_on_each_host(self):
        """Per-schema sequences make the ids collide, so this is not academic.

        Both schools' first `ClassGroup` is `pk=1` and both terms are `pk=1`.
        The only thing separating them is the hostname the request arrived on,
        which is exactly why these paths carry no `{slug}` — a slug would be a
        second opinion free to disagree with the connection.
        """
        theirs = self.enrol(
            self.grace, "uche", "Uche U", self.their_group_id, self.their_term_id
        )
        self.mark(self.grace, self.their_term_id, self.their_maths_id, theirs, 95)

        self.assertEqual(self.group_id, self.their_group_id)
        self.assertEqual(self.term_id, self.their_term_id)

        self.client.force_login(self.principal)
        ours = self.get(host=HOST)
        self.client.logout()
        self.client.force_login(self.their_principal)
        theirs_response = self.get(
            host=THEIR_HOST, group_id=self.group_id, term_id=self.term_id
        )

        self.assertEqual(
            {r["student_membership_id"] for r in ours.json()["rows"]},
            {self.child.pk, self.classmate.pk},
        )
        self.assertEqual(
            {r["student_membership_id"] for r in theirs_response.json()["rows"]},
            {theirs.pk},
        )


class AReleasedTermIsServedFromTheSnapshotTests(BroadsheetApiSetUp):
    """Issue #55. A released term's broadsheet is the frozen cards, not the marks.

    The endpoint's docstring promised this — "once there is [a snapshot], a
    *released* term must be served from it rather than from here" — and task 3
    shipped in #44 without it being done.

    **What that cost is the roster.** Marks lock at release: `gradebook`'s
    `0002` trigger refuses an INSERT for a released term, and the second test
    below asserts that refusal rather than assuming it. Nothing refuses a
    *placement*, so the live roster kept moving under a frozen ranking, and the
    page and the cards answered two different questions in the same shape.
    """

    def test_the_page_says_which_question_it_answered(self):
        """`from_snapshot` exists so two broadsheets can be told apart. Without
        it, a released page and a live one are the same shape saying different
        things."""
        self.assertFalse(self.signed_in(self.principal).json()["from_snapshot"])

        self.release_the_term()

        self.assertTrue(self.signed_in(self.principal).json()["from_snapshot"])

    def test_a_placement_made_after_release_is_not_on_the_page(self):
        """The failure that made #55 live today, with no revision and no #54.

        The live roster gains her — asserted below, so this is a statement about
        the two answers rather than about one — and the page does not, because a
        child with no card was not in what went home. The revision path is what
        gives her one (issue #31), and she appears here once it has.
        """
        self.release_the_term()
        before = self.rows_of(self.signed_in(self.principal).json())

        latecomer = self.enrol(
            self.stmarys, "zainab", "Zainab Z", self.group_id, self.term_id
        )

        # The mark she would need to be *ranked* is refused outright, which is
        # why the roster is the whole of this bug: `restrict_violation` from
        # `gradebook_scores_stop_at_release()`, arriving as `IntegrityError`.
        # Its own atomic block — an IntegrityError marks the enclosing
        # transaction unusable, and this test goes on to make more queries.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.mark(self.stmarys, self.term_id, self.maths_id, latecomer, 99)

        self.assertIn(
            latecomer.pk,
            self.live_results().student_ids,
            "the live roster did not move, so this test proves nothing",
        )

        after = self.rows_of(self.signed_in(self.principal).json())
        self.assertNotIn(latecomer.pk, after, "a child with no card is on the page")
        self.assertEqual(after.keys(), before.keys())
        self.assertEqual(after[self.child.pk]["current_rank"], 1)
        self.assertEqual(after[self.classmate.pk]["current_rank"], 2)

    def test_a_child_who_transfers_out_after_release_keeps_her_row(self):
        """The mirror of the test above, and the one a school actually meets.

        Ada's card went home. A transfer in the last week of term takes her off
        JSS 1A's live roster — asserted, again, so the divergence is a fact of
        this test — and the released page must still show the class that was
        released, or forty-five cards are in parents' hands with no page that
        agrees with them.
        """
        self.release_the_term()
        before = self.rows_of(self.signed_in(self.principal).json())

        self.transfer_out(self.child)

        self.assertNotIn(
            self.child.pk,
            self.live_results().student_ids,
            "the transfer did not move the live roster",
        )

        after = self.rows_of(self.signed_in(self.principal).json())
        self.assertEqual(after.keys(), before.keys())
        self.assertEqual(after[self.child.pk]["current_rank"], 1)
        self.assertEqual(after[self.child.pk]["average"], "88.00")

    def test_the_class_average_is_the_mean_of_the_frozen_cards(self):
        """Derived from the rows displayed beside it, and still never stored.

        88 and 61 average to 74.50. After Ada transfers out, the live figure is
        61.00 over the one child left — both numbers are asserted here, because
        the point is that the page keeps saying the one its own rows add up to.
        """
        self.release_the_term()
        self.assertEqual(
            self.signed_in(self.principal).json()["class_average"], "74.50"
        )

        self.transfer_out(self.child)

        self.assertEqual(str(self.live_results().class_average), "61.00")
        self.assertEqual(
            self.signed_in(self.principal).json()["class_average"], "74.50"
        )

    def test_the_released_page_is_still_per_school(self):
        """Two schools, one released term, and colliding class ids.

        The snapshot is reached by a **new branch into new code**, so the
        isolation the live path is held to has to be asserted of this path
        separately rather than inherited by argument. `ReleasedCard` is a tenant
        table, and a reader that got the schema from anywhere but the connection
        would hand St Mary's frozen class to Grace Academy under the same id.
        """
        theirs = self.enrol(
            self.grace, "uche", "Uche U", self.their_group_id, self.their_term_id
        )
        self.mark(self.grace, self.their_term_id, self.their_maths_id, theirs, 95)

        self.release_the_term()  # St Mary's only.
        self.assertEqual(self.group_id, self.their_group_id)

        ours = self.signed_in(self.principal).json()
        self.client.logout()
        self.client.force_login(self.their_principal)
        theirs_page = self.get(
            host=THEIR_HOST, group_id=self.group_id, term_id=self.term_id
        ).json()

        # Each host answered a different question about the same class id.
        self.assertTrue(ours["from_snapshot"])
        self.assertFalse(theirs_page["from_snapshot"])
        self.assertEqual(
            {r["student_membership_id"] for r in ours["rows"]},
            {self.child.pk, self.classmate.pk},
        )
        self.assertEqual(
            {r["student_membership_id"] for r in theirs_page["rows"]},
            {theirs.pk},
        )

    def test_the_rank_is_derived_and_not_read_off_the_card(self):
        """`current_rank` comes from `dense_positions()` over the frozen
        `own_average` values, so it is a fact about the page. It happens to
        equal `ReleasedCard.position` when every card was frozen together —
        which is this case, and is what makes `TheRevisedChildTests` below
        meaningful rather than a coincidence."""
        from results.models import ReleasedCard

        self.release_the_term()
        rows = self.rows_of(self.signed_in(self.principal).json())

        with connected_to(self.stmarys):
            frozen = {
                card.student_membership_id: card.position
                for card in ReleasedCard.objects.all()
            }

        self.assertEqual(rows[self.child.pk]["current_rank"], 1)
        self.assertEqual(frozen[self.child.pk], 1)
        self.assertEqual(rows[self.classmate.pk]["current_rank"], 2)
        self.assertEqual(frozen[self.classmate.pk], 2)


class TheRevisedChildTests(BroadsheetApiSetUp):
    """The page rank and the card's stored `position` disagree, on purpose.

    **This class is the documentation for why `current_rank` is not called
    `position`.** They are two different numbers and both are correct:

    - `ReleasedCard.position` records where the child came **at that card's own
      freeze**. `revise()` reads the whole class as it stands at revision time,
      so a revised card's position is a statement about a later moment than the
      rest of the class.
    - `current_rank` is where the child comes **among the cards on this page**,
      derived from their frozen `own_average` values.

    Read the frozen positions off forty-five cards and the page can put two
    children at the same rank, because the numbers were not all computed against
    the same roster. That is why the page derives its own.

    The setup makes them differ by exactly one step: Ada transfers out after
    release, and then Bisi's card is corrected. The revision ranks Bisi against
    the one child left in JSS 1A; the page ranks her against the two cards that
    exist. It does **not** inherit from the class above — that would re-run
    every test in it under a second name for no second question asked.
    """

    def revise_the_classmate(self):
        from results import revision

        with connected_to(self.stmarys):
            return revision.revise(
                self.classmate,
                Term.objects.get(pk=self.term_id),
                self.principal,
                "Re-issued after a placement change.",
            )

    def test_the_page_rank_and_the_cards_stored_position_disagree(self):
        from results.models import ReleasedCard

        self.release_the_term()
        self.transfer_out(self.child)
        self.revise_the_classmate()

        with connected_to(self.stmarys):
            cards_now = {
                card.student_membership_id: card
                for card in ReleasedCard.objects.order_by(
                    "student_membership_id", "-version"
                ).distinct("student_membership_id")
            }

        rows = self.rows_of(self.signed_in(self.principal).json())

        # Bisi's own card, re-frozen against the one child left in the class.
        self.assertEqual(cards_now[self.classmate.pk].version, 2)
        self.assertEqual(cards_now[self.classmate.pk].position, 1)
        self.assertEqual(cards_now[self.classmate.pk].roster_size, 1)

        # The page, ranking the two cards that exist.
        self.assertEqual(rows[self.classmate.pk]["current_rank"], 2)

        # Both stated together, because the point is that they differ.
        self.assertNotEqual(
            rows[self.classmate.pk]["current_rank"],
            cards_now[self.classmate.pk].position,
        )

        # And Ada, unrevised, still agrees with her own card — so the divergence
        # belongs to the revision rather than to the derivation.
        self.assertEqual(rows[self.child.pk]["current_rank"], 1)
        self.assertEqual(cards_now[self.child.pk].position, 1)

    def test_the_page_never_repeats_a_rank(self):
        """What reading the frozen positions off the cards would have produced
        here: **two children at rank 1**, because each card was ranked against a
        different roster. The derivation cannot do that, because it ranks the
        set it displays."""
        from results.models import ReleasedCard

        self.release_the_term()
        self.transfer_out(self.child)
        self.revise_the_classmate()

        with connected_to(self.stmarys):
            frozen = sorted(
                card.position
                for card in ReleasedCard.objects.order_by(
                    "student_membership_id", "-version"
                ).distinct("student_membership_id")
            )

        rows = self.rows_of(self.signed_in(self.principal).json())
        derived = sorted(row["current_rank"] for row in rows.values())

        self.assertEqual(frozen, [1, 1], "the setup no longer collides two firsts")
        self.assertEqual(derived, [1, 2])

    def test_the_subject_rank_disagrees_with_the_frozen_line_too(self):
        """The per-subject half of the same divergence, and the reason
        `current_subject_rank` is derived rather than copied off
        `ReleasedSubjectResult.subject_position`.

        That field is frozen against the roster the card was frozen against, so
        Bisi's revision ranks her maths mark among the one child left in JSS 1A
        and writes `1`. The page ranks the two frozen maths lines it is showing
        and says `2`. Both are right about different questions, exactly as with
        `position` above.
        """
        from results.models import ReleasedCard

        self.release_the_term()
        self.transfer_out(self.child)
        self.revise_the_classmate()

        with connected_to(self.stmarys):
            revised = (
                ReleasedCard.objects.filter(student_membership_id=self.classmate.pk)
                .order_by("-version")
                .first()
            )
            frozen_line = revised.subject_results.get(subject_id=self.maths_id)

        rows = self.rows_of(self.signed_in(self.principal).json())
        served = next(
            line
            for line in rows[self.classmate.pk]["subjects"]
            if line["subject_id"] == self.maths_id
        )

        self.assertEqual(frozen_line.subject_position, 1)
        self.assertEqual(served["current_subject_rank"], 2)
        self.assertNotEqual(
            served["current_subject_rank"], frozen_line.subject_position
        )


class TheColumnsAreTheFrozenSubjectLinesTests(BroadsheetApiSetUp):
    """The subject half of a released page, which nothing above here touches.

    Every test in the two classes above asks about a rank or an average, and a
    control that replaced the frozen columns with `Subject.objects` broke none
    of them — so the columns, their frozen names, their print order and
    `current_subject_rank` were all claimed in a docstring and asserted nowhere.
    This class is that control's answer.

    The promise being kept is not new. `ReleasedSubjectResult.subject_name` is
    copied at release because "a subject renamed or retired next session must
    not relabel a line on a card that has gone home", and the broadsheet is read
    beside those cards: a page that relabelled the column would disagree with
    every card in the class over what the subject is called.
    """

    def columns_of(self, payload):
        """Ada's subject lines, as `(id, name)`, in the order they were served."""
        return [
            (line["subject_id"], line["subject"])
            for line in self.rows_of(payload)[self.child.pk]["subjects"]
        ]

    def maths_line(self, row):
        return next(
            line for line in row["subjects"] if line["subject_id"] == self.maths_id
        )

    def test_a_subject_renamed_after_release_keeps_the_name_it_went_home_with(self):
        self.release_the_term()
        self.assertEqual(
            self.columns_of(self.signed_in(self.principal).json()),
            [(self.maths_id, "Mathematics")],
        )

        with connected_to(self.stmarys):
            Subject.objects.filter(pk=self.maths_id).update(name="Further Maths")
            self.assertEqual(
                Subject.objects.get(pk=self.maths_id).name,
                "Further Maths",
                "the rename did not land, so this test proves nothing",
            )

        self.assertEqual(
            self.columns_of(self.signed_in(self.principal).json()),
            [(self.maths_id, "Mathematics")],
            "a live subject name reached a page that is served from the freeze",
        )

    def test_a_subject_the_class_was_never_marked_in_is_not_a_column(self):
        """English is taught and nobody in JSS 1A was marked in it, so no card
        carries a line for it — `cards.release()` freezes `subject_ids`, the
        subjects the class was actually marked in.

        `Subject.objects` is the wrong list here for the reason `broadsheet()`
        already gives on the live path, and for a second one that only applies
        after release: it is not what went home.
        """
        self.release_the_term()

        self.assertEqual(
            [
                name
                for _, name in self.columns_of(
                    self.signed_in(self.principal).json()
                )
            ],
            ["Mathematics"],
        )
        with connected_to(self.stmarys):
            self.assertTrue(
                Subject.objects.filter(pk=self.english_id).exists(),
                "the subject that must not be a column no longer exists",
            )

    def test_the_subject_rank_is_derived_from_the_lines_on_the_page(self):
        """`current_subject_rank` is a dense ranking over the frozen
        percentages on this page, by the same argument `current_rank` makes: a
        `subject_position` copied off a card records what was true at *that
        card's* freeze.

        Ada transfers out afterwards, which moves the live roster and leaves the
        ranking alone — the columns are ranked over the rows being displayed.
        """
        self.release_the_term()
        rows = self.rows_of(self.signed_in(self.principal).json())

        self.assertEqual(self.maths_line(rows[self.child.pk])["percentage"], "88.00")
        self.assertEqual(
            self.maths_line(rows[self.child.pk])["current_subject_rank"], 1
        )
        self.assertEqual(
            self.maths_line(rows[self.classmate.pk])["percentage"], "61.00"
        )
        self.assertEqual(
            self.maths_line(rows[self.classmate.pk])["current_subject_rank"], 2
        )

        self.transfer_out(self.child)

        after = self.rows_of(self.signed_in(self.principal).json())
        self.assertEqual(
            self.maths_line(after[self.classmate.pk])["current_subject_rank"],
            2,
            "the ranking followed the live roster instead of the frozen rows",
        )
