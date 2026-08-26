"""Issue #27: the approval chain and the gradebook were never introduced.

`grep -rn "ResultSheet" gradebook/` returned nothing, and `set_score()` asked
two questions — is this our student, and can this assessment hold this mark —
neither of which was *has this term's results already been checked, approved or
released*. So a mark could be changed at any point after the chain left
`draft`, and the serious case is the last one: a parent holding a card the
database now disagrees with, with no revision and no audit row.

`results` spends two database guards and a long docstring making release
terminal — `nothing_moves_out_of_released` on the log, and `0003`'s trigger on
the sheet — and neither was in the way of the write that actually changes what
the card says. The chain's promise is "this is what was released"; it held for
the sheet's **state** and not for its **contents**.

**One rule covers all four states**, because "writable while the sheet is
absent or in `draft`" is the same sentence `ratings` already enforces. The
tests below walk the chain one step at a time rather than testing `released`
alone: a guard that caught release and let `submitted` through would pass a
smaller test, and the vice principal checking a sheet that moves underneath
them is the case nobody notices until a mark is wrong.

**Two layers, asserted separately.** The service refuses at every state past
`draft`; migration `0002` refuses the `released` case in the database, narrow
on purpose, and is reached here by `.update()` and `.delete()` — the callers
that skip the service, which is exactly the import and the `psql` session the
issue names.
"""

from django.db import IntegrityError, connection, transaction

from academics.models import ClassGroup, Term
from academics.services import assign_class_teacher, move_student
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from gradebook import services
from gradebook.models import Assessment, Score
from results import ratings, services as results_services
from results.models import TraitGroup
from results.tests.test_positions import (
    PASSWORD,
    PositionSetUp,
    connected_to,
)
from schools.models import Domain


class ReleaseGuardSetUp(PositionSetUp):
    """St Mary's, with a placed child, a class teacher, a VP and a First CA."""

    def setUp(self):
        super().setUp()
        self.ada = self.enrol(
            self.stmarys, "ada", "Ada Obi", self.group_id, self.term_id
        )
        self.kemi = self._staff("kemi", "Kemi Bello", Role.TEACHER)
        self.vp = self._staff("ify", "Ify Nwosu", Role.VICE_PRINCIPAL_ACADEMIC)

        with connected_to(self.stmarys):
            assign_class_teacher(
                ClassGroup.objects.get(pk=self.group_id),
                Term.objects.get(pk=self.term_id),
                self.kemi.memberships.get(school=self.stmarys, role=Role.TEACHER),
            )
            self.first_ca_id = Assessment.objects.create(
                term=Term.objects.get(pk=self.term_id),
                subject_id=self.maths_id,
                name="First CA",
                max_score=20,
            ).pk

    # -- fixtures ------------------------------------------------------------

    def _staff(self, username, full_name, role):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, self.stmarys, role)
        return user

    def first_ca(self):
        return Assessment.objects.get(pk=self.first_ca_id)

    def term(self):
        return Term.objects.get(pk=self.term_id)

    def group(self):
        return ClassGroup.objects.get(pk=self.group_id)

    def mark_ada(self, value=15, expected_version=None):
        return services.set_score(
            self.first_ca(), self.ada, value, expected_version=expected_version
        )

    def ada_score(self):
        return (
            Score.objects.filter(
                assessment_id=self.first_ca_id, student_membership_id=self.ada.pk
            )
            .values_list("value", flat=True)
            .first()
        )

    def open_sheet(self):
        return results_services.open_sheet(self.group(), self.term(), self.principal)

    def sheet_now(self):
        """The sheet as the database has it, not as an instance remembers it."""
        return results_services.sheet_for(self.group(), self.term())

    def walk_to(self, state):
        """Take the sheet as far as `state`, with the right person at each step.

        **Returns the sheet re-read**, not the instance the steps were driven
        with. `submit()` and the rest take their own row lock inside `_move()`
        and update the row they locked; the instance passed in is never
        refreshed, so its `state` stays `draft` however far the chain has
        actually gone. Returning it made `sheet.state` a field that silently
        lies — `test_the_database_permits_a_submitted_terms_marks` asserted
        against it and failed, which is the only reason this is written down
        rather than still true.
        """
        sheet = self.open_sheet()
        if state == "draft":
            return self.sheet_now()
        results_services.submit(sheet, self.kemi)
        if state == "submitted":
            return self.sheet_now()
        results_services.check(sheet, self.vp)
        if state == "checked":
            return self.sheet_now()
        results_services.approve(sheet, self.principal)
        if state == "approved":
            return self.sheet_now()
        results_services.release(sheet, self.principal)
        return self.sheet_now()

    def enable_the_conduct_section(self):
        """Turn the affective section on, which is what makes a release freeze.

        Off is the default and the ordinary state of a school that has never
        heard of the feature, so every test that wants a frozen card has to say
        so. That asymmetry is the point of
        `test_a_ratings_disabled_school_is_the_residue_issue_34_closes` below.
        """
        return ratings.set_group_enabled(TraitGroup.AFFECTIVE, True)

    def move_ada_to_a_new_class(self):
        """Release JSS 1A, then move the child out of it. The issue's case."""
        other = ClassGroup.objects.create(name="JSS 3B", level=3)
        move_student(other, self.term(), self.ada)
        return other


class TheChainReachesTheMarksTests(ReleaseGuardSetUp):
    """Walk the sheet one state at a time and watch the marks shut."""

    # -- the service half ----------------------------------------------------

    def test_a_mark_can_be_entered_while_the_sheet_is_a_draft(self):
        """The control. The guard must not shut the ordinary case."""
        with connected_to(self.stmarys):
            self.walk_to("draft")
            self.assertEqual(self.mark_ada().value, 15)

    def test_a_mark_can_be_entered_before_anybody_opens_a_sheet(self):
        """No sheet is open, not closed — marking starts before the chain does."""
        with connected_to(self.stmarys):
            self.assertEqual(self.mark_ada().value, 15)

    def test_every_state_past_draft_shuts_the_marks(self):
        """One rule, four states, and `released` is not the only one that matters.

        A guard that caught release alone would let the vice principal check a
        sheet moving underneath them, which is the case nobody notices until a
        mark is wrong. Walked forward once rather than re-opened per state
        because the states are a *sequence*: one sheet moves through them, and
        there is no way back to `draft` except a send-back. Not because
        `open_sheet()` would refuse the second call — it is a `get_or_create`
        whose docstring says the second person to look must not be an error, so
        re-opening would hand back this same sheet at whatever state it had
        already reached, and the loop would assert nothing.
        """
        with connected_to(self.stmarys):
            sheet = self.open_sheet()
            steps = (
                ("submitted", lambda: results_services.submit(sheet, self.kemi)),
                ("checked", lambda: results_services.check(sheet, self.vp)),
                ("approved", lambda: results_services.approve(sheet, self.principal)),
                ("released", lambda: results_services.release(sheet, self.principal)),
            )
            for state, advance in steps:
                advance()
                with self.subTest(state=state):
                    with self.assertRaises(services.MarksLocked) as refused:
                        self.mark_ada()
                    self.assertEqual(refused.exception.state, state)

    def test_the_refusal_says_which_state_it_is(self):
        """A teacher reads this. "Being reviewed" and "went home" differ."""
        with connected_to(self.stmarys):
            self.walk_to("submitted")
            with self.assertRaises(services.MarksLocked) as refused:
                self.mark_ada()
            self.assertIn("being reviewed", str(refused.exception))

    def test_a_released_sheet_says_revision_not_review(self):
        with connected_to(self.stmarys):
            self.walk_to("released")
            with self.assertRaises(services.MarksLocked) as refused:
                self.mark_ada()
            self.assertIn("revision", str(refused.exception))

    def test_a_send_back_opens_the_marks_again(self):
        """The reason the test is `draft` and not "has never been submitted"."""
        with connected_to(self.stmarys):
            sheet = self.walk_to("submitted")
            results_services.send_back(sheet, self.vp, "A mark looks wrong.")

            self.assertEqual(self.mark_ada().value, 15)

    def test_changing_an_existing_mark_is_refused_too(self):
        """The issue's actual case: not a new mark, a corrected one."""
        with connected_to(self.stmarys):
            existing = self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(services.MarksLocked):
                services.set_score(
                    self.first_ca(), self.ada, 3, expected_version=existing.version
                )
            self.assertEqual(self.ada_score(), 15)

    def test_clearing_a_mark_is_refused_too(self):
        """`clear_score()` deletes, which is the same edit by another name."""
        with connected_to(self.stmarys):
            existing = self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(services.MarksLocked):
                services.clear_score(
                    self.first_ca(), self.ada, expected_version=existing.version
                )
            self.assertEqual(self.ada_score(), 15)

    def test_a_child_with_no_placement_is_not_refused(self):
        """Marking never required a placement, and this does not add that rule.

        No placement means no class, which means no sheet governs the mark.
        There is nothing the guard could be checking against, and refusing here
        would be inventing a requirement under cover of a bug fix.
        """
        unplaced = enroll_student(
            User.objects.create_user("bisi", PASSWORD, full_name="Bisi Lawal"),
            self.stmarys,
        )
        with connected_to(self.stmarys):
            self.walk_to("released")

            self.assertEqual(
                services.set_score(self.first_ca(), unplaced, 12).value, 12
            )

    def test_another_classs_sheet_does_not_shut_ours(self):
        """The lock is per class group, not per term.

        JSS 3B goes the whole way while JSS 1A has no sheet at all. If the guard
        keyed on the term it would shut a class nobody has finished marking.
        """
        sade = self._staff("sade", "Sade Johnson", Role.TEACHER)
        with connected_to(self.stmarys):
            other = ClassGroup.objects.create(name="JSS 3B", level=3)
            assign_class_teacher(
                other,
                self.term(),
                sade.memberships.get(school=self.stmarys, role=Role.TEACHER),
            )
            theirs = results_services.open_sheet(other, self.term(), self.principal)
            results_services.submit(theirs, sade)
            results_services.check(theirs, self.vp)
            results_services.approve(theirs, self.principal)
            results_services.release(theirs, self.principal)

            self.assertEqual(self.mark_ada().value, 15)

    # -- the database half ---------------------------------------------------

    def test_the_database_refuses_an_update_after_release(self):
        """Reached by `.update()`, which no service guard sees."""
        with connected_to(self.stmarys):
            self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Score.objects.filter(
                        assessment_id=self.first_ca_id,
                        student_membership_id=self.ada.pk,
                    ).update(value=3)
            self.assertEqual(self.ada_score(), 15)

    def test_the_database_refuses_a_delete_after_release(self):
        with connected_to(self.stmarys):
            self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Score.objects.filter(
                        assessment_id=self.first_ca_id,
                        student_membership_id=self.ada.pk,
                    ).delete()
            self.assertEqual(self.ada_score(), 15)

    def test_the_database_refuses_a_new_mark_after_release(self):
        """INSERT too: a new mark for a released term is as wrong as an edit.

        And likelier — a teacher entering marks for a term that closed while
        their screen was open.
        """
        with connected_to(self.stmarys):
            self.walk_to("released")

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Score.objects.create(
                        assessment_id=self.first_ca_id,
                        student_membership_id=self.ada.pk,
                        value=9,
                    )

    def test_the_database_permits_a_mark_while_the_sheet_is_a_draft(self):
        """The control the trigger's own name promises, against a real draft.

        This test used to walk to `submitted` and call itself the draft case, so
        the state it named was not the state it exercised and no test asserted
        the trigger lets an ordinary mark through at all. The sheet's state is
        asserted rather than assumed, because that is the half that was wrong.
        """
        with connected_to(self.stmarys):
            sheet = self.walk_to("draft")
            self.assertEqual(sheet.state, "draft")

            Score.objects.create(
                assessment_id=self.first_ca_id,
                student_membership_id=self.ada.pk,
                value=9,
            )
            self.assertEqual(self.ada_score(), 9)

    def test_the_database_permits_a_submitted_terms_marks(self):
        """Narrow means narrow: the two layers disagree here, on purpose.

        `0002` refuses `released` only, matching `results` `0003` — that state
        is terminal and has no legitimate exception, while `submitted` and
        `checked` are a rule about a review in progress, which is the service's
        to hold and not the table's. Both halves are asserted in one test
        because the claim is about the *difference* between them: the service
        refuses, and the write that goes round the service does not.
        """
        with connected_to(self.stmarys):
            sheet = self.walk_to("submitted")
            self.assertEqual(sheet.state, "submitted")

            with self.assertRaises(services.MarksLocked):
                self.mark_ada()

            Score.objects.create(
                assessment_id=self.first_ca_id,
                student_membership_id=self.ada.pk,
                value=9,
            )
            self.assertEqual(self.ada_score(), 9)

    # -- the moved child ------------------------------------------------------

    def test_a_moved_child_is_refused_by_the_card_that_went_home(self):
        """The case the first draft of this PR filed as unclosable.

        `Score` reaches a class only through the placement, so the sheet check
        alone asks where the child sits *today* and finds JSS 3B's untouched
        draft. What closes it is not the placement but the artefact:
        `ReleasedTraitRating` holds a row per child per visible trait, written
        inside the release transaction, and a class move cannot touch it. Same
        key `0011` uses one table over.
        """
        with connected_to(self.stmarys):
            self.enable_the_conduct_section()
            self.mark_ada()
            self.walk_to("released")
            self.move_ada_to_a_new_class()

            with self.assertRaises(services.MarksLocked) as refused:
                services.set_score(self.first_ca(), self.ada, 3, expected_version=1)
            self.assertIn("released to a parent", str(refused.exception))
            self.assertEqual(self.ada_score(), 15)

    def test_a_moved_child_is_refused_by_the_database_too(self):
        """The write that goes round the service, for the moved child as well.

        The trigger gained the same artefact check the service did. Without it
        the two layers would disagree about the one case the whole finding was
        about, and `.update()` from a `psql` session is exactly the caller the
        issue names.
        """
        with connected_to(self.stmarys):
            self.enable_the_conduct_section()
            self.mark_ada()
            self.walk_to("released")
            self.move_ada_to_a_new_class()

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Score.objects.filter(
                        assessment_id=self.first_ca_id,
                        student_membership_id=self.ada.pk,
                    ).update(value=3)
            self.assertEqual(self.ada_score(), 15)

    def test_a_moved_child_with_no_mark_yet_is_refused_a_new_one(self):
        """INSERT, not just UPDATE — and through the service, not the table.

        The moved child's mark may never have been entered: the card went home
        with a blank, and a teacher enters it afterwards against the new class's
        draft. That is a change to what was released just as much as an edit is.
        """
        with connected_to(self.stmarys):
            self.enable_the_conduct_section()
            self.walk_to("released")
            self.move_ada_to_a_new_class()

            with self.assertRaises(services.MarksLocked):
                self.mark_ada()
            self.assertIsNone(self.ada_score())

    # -- the residue that is left ---------------------------------------------

    def test_a_ratings_disabled_school_is_the_residue_issue_34_closes(self):
        """What is left after the artefact check, stated rather than denied.

        `freeze_for_release()` returns early when no group is enabled, so a
        school with the conduct section off freezes nothing for anybody and the
        artefact check finds nothing to refuse with. That leaves the moved child
        of such a school looked up against the new class's draft — a per-*school*
        gap now, where before it was every school's.

        Asserted, so that the day #34's unconditional per-child marker lands,
        this fails and is deleted rather than quietly going stale. The
        precondition is asserted too: if some future default turned the section
        on, this test would pass for the wrong reason and stop guarding anything.
        """
        with connected_to(self.stmarys):
            self.assertEqual(ratings.enabled_groups(), [])

            self.mark_ada()
            self.walk_to("released")
            self.move_ada_to_a_new_class()

            services.set_score(self.first_ca(), self.ada, 3, expected_version=1)
            self.assertEqual(self.ada_score(), 3)

    def test_the_child_who_stayed_put_is_refused_either_way(self):
        """The common case, and it does not depend on the conduct section.

        The placement check carries this one on its own, which is why it stays
        even though the artefact check is the better key. With the section off
        there is no frozen row to find, and the child is still refused.
        """
        with connected_to(self.stmarys):
            self.assertEqual(ratings.enabled_groups(), [])

            self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(services.MarksLocked):
                services.set_score(self.first_ca(), self.ada, 3, expected_version=1)
            self.assertEqual(self.ada_score(), 15)

    # -- blocker 3: the promise `clear_score()` makes about a retry -----------

    def test_clearing_a_mark_that_is_already_gone_stays_a_no_op(self):
        """A retried DELETE must not fail because it succeeded the first time.

        `clear_score()`'s docstring promises exactly that, and the guard broke
        it: run before the check for a row to delete, it refused the second
        request on a sheet that had since been submitted — failing a request
        precisely because it had already worked. Nothing is being written here,
        so there is nothing for a closed sheet to protect.

        Walked all the way to `released`, which is the strongest form: both the
        service guard and the trigger are live, and neither has anything to fire
        on because no row is touched.
        """
        with connected_to(self.stmarys):
            existing = self.mark_ada()
            services.clear_score(
                self.first_ca(), self.ada, expected_version=existing.version
            )
            self.walk_to("released")

            services.clear_score(
                self.first_ca(), self.ada, expected_version=existing.version
            )
            self.assertIsNone(self.ada_score())

    def test_clearing_a_mark_that_is_there_is_still_refused(self):
        """The other half of the pair, so the fix above cannot swallow the rule.

        The idempotent path is entered only when there is nothing to delete. A
        mark that is actually there on a released sheet is a write, and it is
        refused — otherwise "already gone" would have become a way through.
        """
        with connected_to(self.stmarys):
            existing = self.mark_ada()
            self.walk_to("released")

            with self.assertRaises(services.MarksLocked):
                services.clear_score(
                    self.first_ca(), self.ada, expected_version=existing.version
                )
            self.assertEqual(self.ada_score(), 15)

    def test_a_mark_at_another_version_on_a_shut_sheet_is_locked_not_conflicted(self):
        """Which of the two refusals wins, and why it is this one.

        The caller was shown version 1, the mark now stands at version 2, and
        the sheet has been released. `ScoreChangedMeanwhile` would tell them to
        reload and send again — round a loop that cannot terminate, because
        reloading does not reopen the term. The sheet is the reason they are
        refused, so the sheet is what the refusal has to name.
        """
        with connected_to(self.stmarys):
            first = self.mark_ada()
            self.mark_ada(17, expected_version=first.version)
            self.walk_to("released")

            with self.assertRaises(services.MarksLocked):
                services.clear_score(
                    self.first_ca(), self.ada, expected_version=first.version
                )
            self.assertEqual(self.ada_score(), 17)


class TheApiSaysLockedRatherThanCrashingTests(ReleaseGuardSetUp):
    """The refusal as a teacher's browser actually receives it.

    `MarksLocked` reached neither endpoint's `except` clause, so every refusal
    this guard adds arrived as an unhandled traceback — a 500 where a sentence
    was written, and the one part of the feature a teacher would ever see. The
    service tests above prove the mark is not written; these prove somebody is
    told why.

    **423, and the two codes it is not.** A 409 in this API means "the row moved
    while you were typing", which a blur handler answers by reloading the cell
    and sending again; against a released term that retries for ever, because
    nothing it can reload reopens the term. A 403 is a refusal of the caller's
    authority, and the caller's authority has not changed — this same teacher
    may mark this same child the moment the sheet is sent back. What changed is
    the state of the resource.
    """

    HOST = "st-marys.testserver"

    def setUp(self):
        super().setUp()
        # The school's own host: `TenantMainMiddleware` picks the schema from
        # it, and these tables live in no other.
        Domain.objects.create(tenant=self.stmarys, domain=self.HOST, is_primary=True)
        self.client.force_login(self.kemi)

    def tearDown(self):
        """Or the next test starts life on `st_marys`. See `test_api.py`."""
        connection.set_schema_to_public()
        super().tearDown()

    def save(self, value=3, expected_version=None):
        return self.client.put(
            f"/api/gradebook/assessments/{self.first_ca_id}/scores/{self.ada.pk}/",
            data={"value": value, "expected_version": expected_version},
            content_type="application/json",
            HTTP_HOST=self.HOST,
        )

    def clear(self, expected_version):
        return self.client.delete(
            f"/api/gradebook/assessments/{self.first_ca_id}/scores/{self.ada.pk}/"
            f"?expected_version={expected_version}",
            HTTP_HOST=self.HOST,
        )

    def test_an_ordinary_save_is_untouched(self):
        """The control. A 423 that fired on the open case would be worse."""
        with connected_to(self.stmarys):
            self.walk_to("draft")

        response = self.save(15)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], 15)

    def test_saving_into_a_released_term_answers_423(self):
        with connected_to(self.stmarys):
            self.walk_to("released")

        response = self.save(15)
        self.assertEqual(response.status_code, 423)
        self.assertIn("revision", response.json()["detail"])

    def test_saving_into_a_term_under_review_answers_423_as_well(self):
        """Not only the terminal state: the vice principal is holding this one."""
        with connected_to(self.stmarys):
            self.walk_to("submitted")

        response = self.save(15)
        self.assertEqual(response.status_code, 423)
        self.assertIn("being reviewed", response.json()["detail"])

    def test_a_moved_childs_save_answers_423_too(self):
        """The artefact check reaches the endpoint, not just the service."""
        with connected_to(self.stmarys):
            self.enable_the_conduct_section()
            self.walk_to("released")
            self.move_ada_to_a_new_class()

        response = self.save(15)
        self.assertEqual(response.status_code, 423)
        self.assertIn("released to a parent", response.json()["detail"])

    def test_clearing_a_mark_on_a_released_term_answers_423(self):
        with connected_to(self.stmarys):
            existing = self.mark_ada()
            self.walk_to("released")

        response = self.clear(existing.version)
        self.assertEqual(response.status_code, 423)
        with connected_to(self.stmarys):
            self.assertEqual(self.ada_score(), 15)

    def test_a_retried_clear_of_a_gone_mark_still_answers_200(self):
        """`clear_score()`'s idempotency, over HTTP, where it actually matters.

        A blur fires twice, or the first response is lost and the client sends
        the DELETE again. The mark went the first time and the sheet has since
        been released. The second request asks for an end state that already
        holds, writes nothing, and must not be a 423 — a client that treats it
        as a failure shows a teacher an error for having succeeded.
        """
        with connected_to(self.stmarys):
            existing = self.mark_ada()

        self.assertEqual(self.clear(existing.version).status_code, 200)

        with connected_to(self.stmarys):
            self.walk_to("released")

        response = self.clear(existing.version)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["value"])
