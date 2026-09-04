"""Task 8: reissuing a card that has already gone home.

What a revision has to be true of, and the two things it must not do.

**It must not rewrite the card in the parent's hand.** Version 1 goes on saying
what it said, for ever; the revision is a second row beside it. Every test here
that asserts something about version 2 also asserts version 1 did not move.

**It must not move the sheet.** `services._move()` refuses every transition out
of `released` — "corrected by issuing a revision, which keeps this one standing,
not by moving it back" — so a revision that reopened the chain would be the same
act by another name.

Two schools throughout, and Grace releases and revises too rather than sitting
there as a decoration (#38's finding 10): a revision is a tenant act, and a
suite that only ever revises at St Mary's cannot tell "the right school" from
"the only school".
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from academics.models import ClassGroup, Term, TermName
from academics.services import move_student, place_student
from accounts.models import Role, User
from accounts.services import enroll_student
from gradebook.models import Assessment
from gradebook import services as gradebook_services
from results import cards, comments, positions, ratings, revision, sessions
from results import services as results_services
from results.models import (
    CardRevision,
    CommentAuthor,
    ReleasedCard,
    ReleasedComment,
    ReleasedSessionResult,
    ReleasedSubjectResult,
    ReleasedTraitRating,
    ResultSheet,
    ResultSheetTransition,
    RevisionsAreAppendOnly,
    SheetState,
    Trait,
    TraitGroup,
)
from results.services import NotAllowedToActOnResults
from results.tests.test_cards import SESSION, CardSetUp
from results.tests.test_positions import PASSWORD, make_school
from schools.tests.tenants import connected_to


class RevisionSetUp(CardSetUp):
    """St Mary's with a released first term, and a Grace Academy that releases too.

    `CardSetUp.term()` and `.group()` read **St Mary's** ids whatever school
    they are handed — a trap PR #49 hit — so everything about Grace here goes
    through `self.their_terms` and `self.their_group` explicitly.
    """

    def setUp(self):
        super().setUp()
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.their_staff = self._staff_for(self.grace)
        self.their_principal = self.their_staff[Role.PRINCIPAL]
        # Before `_academics(self.grace)`, which reaches back through
        # `CardSetUp._staff_for_school()` for the class teacher to assign.
        self.their_teacher = self.their_staff[Role.TEACHER]

        self.their_terms, their_group_id, _ = self._academics(self.grace)
        self.their_child = enroll_student(
            User.objects.create_user("chidi", PASSWORD, full_name="Chidi Nwosu"),
            self.grace,
        )
        with connected_to(self.grace):
            self.their_group = ClassGroup.objects.get(pk=their_group_id)
            for name in TermName:
                place_student(
                    self.their_group,
                    Term.objects.get(pk=self.their_terms[name.value]),
                    self.their_child,
                )

        self.mark(self.stmarys, "first", self.ada, "maths", "Exam", 80)
        self.mark(self.stmarys, "first", self.bola, "maths", "Exam", 50)

    # -- St Mary's -----------------------------------------------------------

    def release_first_term(self):
        with connected_to(self.stmarys):
            return self.release_the_term()

    def first_term(self):
        return self.term(self.stmarys, TermName.FIRST.value)

    # -- Grace ---------------------------------------------------------------

    def their_first_term(self):
        return Term.objects.get(pk=self.their_terms[TermName.FIRST.value])

    def release_first_term_at_grace(self):
        """Grace's own chain, with Grace's own people. Nothing borrowed."""
        with connected_to(self.grace):
            term = self.their_first_term()
            sheet = results_services.open_sheet(
                self.their_group, term, self.their_principal
            )
            results_services.submit(sheet, self.their_teacher)
            results_services.check(sheet, self.their_staff[Role.VICE_PRINCIPAL_ACADEMIC])
            results_services.approve(sheet, self.their_principal)
            results_services.release(sheet, self.their_principal)
            return sheet


class ARevisionIsASecondCardTests(RevisionSetUp):
    """Both stand, and the first one does not move."""

    def test_a_revision_writes_a_second_version_and_leaves_the_first(self):
        self.release_first_term()

        with connected_to(self.stmarys):
            first = cards.card_for(self.ada, self.first_term())
            before = (first.pk, first.version, first.student_name, first.own_average)

            new = revision.revise(
                self.ada, self.first_term(), self.principal, "Maths exam mismarked."
            )

            first.refresh_from_db()
            self.assertEqual(
                (first.pk, first.version, first.student_name, first.own_average),
                before,
                "Version 1 changed. A card in a parent's hand does not move.",
            )
            self.assertEqual(new.version, 2)
            self.assertNotEqual(new.pk, first.pk)
            self.assertEqual(
                ReleasedCard.objects.filter(
                    student_membership_id=self.ada.pk, term=self.first_term()
                ).count(),
                2,
            )

    def test_the_card_for_this_child_is_now_the_revision(self):
        """`cards.card_for()` already ordered on version. This is the row it meant."""
        self.release_first_term()

        with connected_to(self.stmarys):
            revised = revision.revise(
                self.ada, self.first_term(), self.principal, "Wrong remark printed."
            )
            self.assertEqual(cards.card_for(self.ada, self.first_term()).pk, revised.pk)

    def test_a_third_version_supersedes_the_second_not_the_first(self):
        """Version is the running number, and `previous_card` is the one before."""
        self.release_first_term()

        with connected_to(self.stmarys):
            second = revision.revise(
                self.ada, self.first_term(), self.principal, "First correction."
            )
            third = revision.revise(
                self.ada, self.first_term(), self.principal, "Second correction."
            )

            self.assertEqual(third.version, 3)
            self.assertEqual(
                CardRevision.objects.get(card=third).previous_card_id, second.pk
            )

    def test_only_the_revised_child_gets_a_new_card(self):
        """Bola is on the same sheet and is not reissued."""
        self.release_first_term()

        with connected_to(self.stmarys):
            revision.revise(
                self.ada, self.first_term(), self.principal, "Ada's name misspelled."
            )
            self.assertEqual(
                ReleasedCard.objects.filter(
                    student_membership_id=self.bola.pk
                ).count(),
                1,
            )

    def test_the_revised_card_is_ranked_against_the_class_not_against_itself(self):
        """One card is written; the whole class is read to write it.

        `roster_size` and `position` are statements about the other children.
        A revision that read only the child being revised would rank every
        revised card first out of one — and it would look right, because 1 of 1
        is a plausible number.
        """
        self.release_first_term()

        with connected_to(self.stmarys):
            revised = revision.revise(
                self.ada, self.first_term(), self.principal, "Reissue."
            )
            self.assertEqual(revised.roster_size, 2)
            self.assertEqual(revised.position, 1)


class WhatActuallyChangesTests(RevisionSetUp):
    """A revision re-freezes from live data. This is what live data can be."""

    def test_a_corrected_name_reaches_the_new_card_and_not_the_old_one(self):
        """The commonest real correction, and the one the copy rule makes hard.

        `student_name` is copied at freeze precisely so that a rename in
        `accounts` — a **shared** schema — cannot rewrite a card that has gone
        home. The other side of that rule is that a misspelling stays
        misspelled, and a revision is the only thing that fixes it.
        """
        self.release_first_term()

        with connected_to(self.stmarys):
            original = cards.card_for(self.ada, self.first_term())
            self.assertEqual(original.student_name, "Ada Obi")

        User.objects.filter(pk=self.ada.user_id).update(full_name="Ada Obiora")

        with connected_to(self.stmarys):
            revised = revision.revise(
                self.ada, self.first_term(), self.principal, "Surname misspelled."
            )
            original.refresh_from_db()

            self.assertEqual(revised.student_name, "Ada Obiora")
            self.assertEqual(original.student_name, "Ada Obi")


class TheSectionsAreReFrozenTests(RevisionSetUp):
    """The three tables whose keys refused a second version until `0019`.

    `ReleasedTraitRating`, `ReleasedComment` and `ReleasedSessionResult` were
    unique on `(sheet, student_membership_id, ...)` — keys written before `card`
    existed — so every one of these tests failed with an IntegrityError naming a
    constraint rather than with a wrong answer. That is what the migration is
    for, and these are the tests that would go red if it were reverted.
    """

    def setUp(self):
        super().setUp()
        # Both sections switched **on** and actually filled in, before the
        # release. Every assertion below compares the revision's section against
        # the first release's, and a school with the conduct section off freezes
        # nothing for either — so the comparison would be `0 == 0` and would go
        # on passing with the whole re-freeze deleted. It did, until it was
        # asserted that the number is not zero.
        with connected_to(self.stmarys):
            for group in (TraitGroup.AFFECTIVE, TraitGroup.PSYCHOMOTOR):
                ratings.set_group_enabled(group, True)
            first = self.first_term()
            ratings.rate(
                first,
                Trait.objects.filter(group=TraitGroup.AFFECTIVE).first(),
                self.ada,
                4,
            )
            comments.write(
                first, self.ada, CommentAuthor.CLASS_TEACHER, "A steady term."
            )
            comments.write(
                first, self.ada, CommentAuthor.PRINCIPAL, "Keep it up."
            )

        self.sheet = self.release_first_term()

    def _revise(self):
        with connected_to(self.stmarys):
            return revision.revise(
                self.ada, self.first_term(), self.principal, "Reissue with sections."
            )

    def test_the_conduct_section_is_frozen_against_the_new_card(self):
        revised = self._revise()
        with connected_to(self.stmarys):
            for_new = ReleasedTraitRating.objects.filter(card=revised).count()
            for_old = ReleasedTraitRating.objects.filter(
                sheet=self.sheet, student_membership_id=self.ada.pk
            ).exclude(card=revised).count()

        self.assertEqual(for_new, for_old, "The revision froze a different section.")
        self.assertGreater(for_new, 0)

    def test_the_remarks_are_frozen_against_the_new_card(self):
        revised = self._revise()
        with connected_to(self.stmarys):
            for_new = ReleasedComment.objects.filter(card=revised).count()
            for_old = (
                ReleasedComment.objects.filter(
                    sheet=self.sheet, student_membership_id=self.ada.pk
                )
                .exclude(card=revised)
                .count()
            )

        self.assertEqual(for_new, for_old)
        # Both signatories wrote one in `setUp`. Without this the equality is
        # `0 == 0` and holds with the re-freeze deleted.
        self.assertEqual(for_new, 2)

    def test_the_subject_lines_and_score_cells_come_with_it(self):
        revised = self._revise()
        with connected_to(self.stmarys):
            self.assertGreater(
                ReleasedSubjectResult.objects.filter(card=revised).count(), 0
            )
            self.assertEqual(
                ReleasedSubjectResult.objects.filter(card=revised).count(),
                ReleasedSubjectResult.objects.filter(
                    card__student_membership_id=self.ada.pk, card__version=1
                ).count(),
            )

    def test_the_session_line_is_frozen_against_the_new_card_at_third_term(self):
        """Third term only, which is where a session line exists at all."""
        for name in (TermName.SECOND.value, TermName.THIRD.value):
            self.mark(self.stmarys, name, self.ada, "maths", "Exam", 70)
            self.mark(self.stmarys, name, self.bola, "maths", "Exam", 60)
        with connected_to(self.stmarys):
            self.release_the_term(TermName.SECOND.value)
            self.release_the_term(TermName.THIRD.value)
            third = self.term(self.stmarys, TermName.THIRD.value)

            before = ReleasedSessionResult.objects.filter(
                card__student_membership_id=self.ada.pk, card__term=third
            ).count()
            revised = revision.revise(
                self.ada, third, self.principal, "Third-term reissue."
            )

            self.assertEqual(before, 1)
            self.assertEqual(
                ReleasedSessionResult.objects.filter(card=revised).count(), 1
            )


class WhoMayReviseTests(RevisionSetUp):
    """Principal only, plus platform staff who say that is what they are."""

    def setUp(self):
        super().setUp()
        self.release_first_term()

    def test_the_principal_may(self):
        with connected_to(self.stmarys):
            self.assertEqual(
                revision.revise(
                    self.ada, self.first_term(), self.principal, "Reissue."
                ).version,
                2,
            )

    def test_a_teacher_a_vice_principal_and_an_administrator_may_not(self):
        """Release is the principal's act, so revision is too.

        All three, not just one: an authority test that names a single refused
        role passes against a check that admits the other two.
        """
        for role in (Role.TEACHER, Role.VICE_PRINCIPAL_ACADEMIC, Role.ADMIN):
            with self.subTest(role=role.value):
                with connected_to(self.stmarys):
                    with self.assertRaises(NotAllowedToActOnResults):
                        revision.revise(
                            self.ada,
                            self.first_term(),
                            self.staff[role],
                            "Not mine to do.",
                        )

    def test_a_refused_revision_writes_no_card_and_no_audit_row(self):
        """The refusal is worth nothing if the rows land anyway."""
        with connected_to(self.stmarys):
            with self.assertRaises(NotAllowedToActOnResults):
                revision.revise(
                    self.ada, self.first_term(), self.teacher, "Not mine to do."
                )
            self.assertEqual(
                ReleasedCard.objects.filter(
                    student_membership_id=self.ada.pk, version=2
                ).count(),
                0,
            )
            self.assertEqual(CardRevision.objects.count(), 0)

    def test_platform_staff_may_by_saying_so_and_it_is_recorded_as_theirs(self):
        """The school locked out of its own correction has one other road."""
        operator = User.objects.create_user(
            "operator", PASSWORD, full_name="Platform Operator", is_platform_staff=True
        )

        with connected_to(self.stmarys):
            revised = revision.revise(
                self.ada,
                self.first_term(),
                operator,
                "School locked out; corrected on request.",
                by_platform_staff=True,
            )
            record = CardRevision.objects.get(card=revised)

        self.assertTrue(record.by_platform_staff)
        self.assertEqual(record.revised_by_id, operator.pk)

    def test_a_principal_cannot_record_their_own_act_as_the_platforms(self):
        """The flag is not a shortcut past the role check; it is a different claim.

        A school reading its own audit must never be told the platform did
        something the platform did not do — the mirror of the reason the flag
        exists at all.
        """
        with connected_to(self.stmarys):
            with self.assertRaisesMessage(
                NotAllowedToActOnResults, "is not platform staff"
            ):
                revision.revise(
                    self.ada,
                    self.first_term(),
                    self.principal,
                    "Trying it on.",
                    by_platform_staff=True,
                )

    def test_platform_staff_without_the_flag_get_no_quiet_second_door(self):
        """Platform staff hold no role at the school, so the ordinary path refuses.

        The two checks are deliberately not a union: a union would let a
        platform staffer revise without the flag, and the row would then read as
        the school's own principal-shaped act.
        """
        operator = User.objects.create_user(
            "operator2", PASSWORD, full_name="Another Operator", is_platform_staff=True
        )
        with connected_to(self.stmarys):
            with self.assertRaises(NotAllowedToActOnResults):
                revision.revise(
                    self.ada, self.first_term(), operator, "No flag, no door."
                )


class ARevisionSaysWhyTests(RevisionSetUp):
    """Required, and required by a constraint as well as by a sentence."""

    def setUp(self):
        super().setUp()
        self.release_first_term()

    def test_a_blank_reason_is_refused_before_anything_is_written(self):
        for reason in ("", "   ", "\n\t"):
            with self.subTest(reason=repr(reason)):
                with connected_to(self.stmarys):
                    with self.assertRaisesMessage(
                        revision.RevisionError, "has to say why"
                    ):
                        revision.revise(
                            self.ada, self.first_term(), self.principal, reason
                        )
                    self.assertEqual(CardRevision.objects.count(), 0)

    def test_the_constraint_holds_it_too_and_it_is_named(self):
        """`assertRaises(IntegrityError)` cannot tell this constraint from the
        several ways of never reaching it, so the constraint's own name is
        asserted — the lesson `test_sessions` learned the hard way."""
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.first_term())
            with self.assertRaises(IntegrityError) as caught:
                with transaction.atomic():
                    CardRevision.objects.create(
                        card=card, reason="   ", revised_by_id=self.principal.pk
                    )
            self.assertIn("a_revision_says_why", str(caught.exception))

    def test_a_revision_cannot_supersede_itself(self):
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.first_term())
            with self.assertRaises(IntegrityError) as caught:
                with transaction.atomic():
                    CardRevision.objects.create(
                        card=card,
                        previous_card=card,
                        reason="Pointing at the wrong one.",
                        revised_by_id=self.principal.pk,
                    )
            self.assertIn("a_revision_supersedes_a_different_card", str(caught.exception))


class TheAuditIsAppendOnlyTests(RevisionSetUp):
    """The record of a card being reissued is not one that can be rewritten."""

    def setUp(self):
        super().setUp()
        self.release_first_term()
        with connected_to(self.stmarys):
            self.revised = revision.revise(
                self.ada, self.first_term(), self.principal, "Original reason."
            )
            self.record = CardRevision.objects.get(card=self.revised)

    def test_the_reason_cannot_be_rewritten(self):
        with connected_to(self.stmarys):
            self.record.reason = "A better story."
            with self.assertRaises(RevisionsAreAppendOnly):
                self.record.save()

    def test_the_row_cannot_be_deleted(self):
        with connected_to(self.stmarys):
            with self.assertRaises(RevisionsAreAppendOnly):
                self.record.delete()


class ARevisionDoesNotMoveTheSheetTests(RevisionSetUp):
    """`_move()` says a released sheet is corrected "not by moving it back"."""

    def test_the_sheet_stays_released_on_the_same_cycle_with_no_new_transition(self):
        sheet = self.release_first_term()

        with connected_to(self.stmarys):
            before = ResultSheetTransition.objects.filter(sheet=sheet).count()
            cycle = ResultSheet.objects.get(pk=sheet.pk).cycle

            revision.revise(
                self.ada, self.first_term(), self.principal, "Reissue only."
            )

            after = ResultSheet.objects.get(pk=sheet.pk)
            self.assertEqual(after.state, SheetState.RELEASED)
            self.assertEqual(after.cycle, cycle)
            self.assertEqual(
                ResultSheetTransition.objects.filter(sheet=sheet).count(), before
            )


class RevisedIsSaidByTheVersionTests(RevisionSetUp):
    """`is_revised` is `version > 1`, and the difference is a real child."""

    def test_the_first_version_does_not_say_revised_and_the_second_does(self):
        self.release_first_term()

        with connected_to(self.stmarys):
            first = cards.card_for(self.ada, self.first_term())
            self.assertFalse(first.is_revised)

            second = revision.revise(
                self.ada, self.first_term(), self.principal, "Reissue."
            )
            first.refresh_from_db()

            self.assertTrue(second.is_revised)
            self.assertFalse(first.is_revised, "Version 1 started saying Revised.")


class AChildPlacedAfterTheReleaseTests(RevisionSetUp):
    """Issue #31, reached by this road: her first card comes from the revision path.

    She is placed into the term *after* it was released, so the release that
    happened never saw her and no card went home. The revision path is what
    finally gives her one — at version 1, superseding nothing — and it must not
    tell her family a correction was made to something they never received.
    """

    def setUp(self):
        super().setUp()
        self.release_first_term()
        self.latecomer = enroll_student(
            User.objects.create_user("ngozi", PASSWORD, full_name="Ngozi Ada"),
            self.stmarys,
        )
        with connected_to(self.stmarys):
            place_student(
                self.group(self.stmarys), self.first_term(), self.latecomer
            )

    def test_she_has_no_card_until_one_is_issued(self):
        with connected_to(self.stmarys):
            self.assertIsNone(cards.card_for(self.latecomer, self.first_term()))

    def test_the_revision_path_gives_her_a_first_version_superseding_nothing(self):
        with connected_to(self.stmarys):
            card = revision.revise(
                self.latecomer,
                self.first_term(),
                self.principal,
                "Placed after release; card issued.",
            )
            record = CardRevision.objects.get(card=card)

            self.assertEqual(card.version, 1)
            self.assertIsNone(record.previous_card_id)

    def test_her_card_does_not_print_revised(self):
        """The whole reason `is_revised` reads the version and not this row."""
        with connected_to(self.stmarys):
            card = revision.revise(
                self.latecomer,
                self.first_term(),
                self.principal,
                "Placed after release; card issued.",
            )
            self.assertTrue(CardRevision.objects.filter(card=card).exists())
            self.assertFalse(
                card.is_revised,
                "A child's only card told her family it was a correction.",
            )

    def test_a_child_in_no_class_group_for_the_term_cannot_be_issued_one(self):
        """A revision reissues a release. It does not invent one."""
        stranger = enroll_student(
            User.objects.create_user("emeka", PASSWORD, full_name="Emeka Uche"),
            self.stmarys,
        )
        with connected_to(self.stmarys):
            with self.assertRaises(revision.NothingToRevise):
                revision.revise(
                    stranger, self.first_term(), self.principal, "No placement."
                )


class NothingToReviseTests(RevisionSetUp):
    """A sheet that has not been released has no card to reissue."""

    def test_an_unreleased_term_is_refused(self):
        with connected_to(self.stmarys):
            results_services.open_sheet(
                self.group(self.stmarys), self.first_term(), self.principal
            )
            with self.assertRaises(revision.NothingToRevise):
                revision.revise(
                    self.ada, self.first_term(), self.principal, "Too early."
                )


class TwoSchoolsTests(RevisionSetUp):
    """A revision is a tenant act, and Grace does its own.

    Grace releases and revises with Grace's own people, on Grace's own term, for
    Grace's own child. A suite whose second school only ever gets asked "do you
    have nothing?" cannot tell a working tenant boundary from a broken one.
    """

    def test_a_revision_at_one_school_writes_nothing_at_the_other(self):
        self.release_first_term()
        self.release_first_term_at_grace()

        with connected_to(self.stmarys):
            revision.revise(
                self.ada, self.first_term(), self.principal, "St Mary's reissue."
            )
            here = CardRevision.objects.count()

        with connected_to(self.grace):
            there = CardRevision.objects.count()
            their_versions = list(
                ReleasedCard.objects.filter(
                    student_membership_id=self.their_child.pk
                ).values_list("version", flat=True)
            )

        self.assertEqual(here, 1)
        self.assertEqual(there, 0)
        self.assertEqual(their_versions, [1])

    def test_grace_revises_its_own_card_with_its_own_principal(self):
        self.release_first_term_at_grace()

        with connected_to(self.grace):
            revised = revision.revise(
                self.their_child,
                self.their_first_term(),
                self.their_principal,
                "Grace's own correction.",
            )
            self.assertEqual(revised.version, 2)
            self.assertTrue(revised.is_revised)
            self.assertEqual(CardRevision.objects.count(), 1)

        with connected_to(self.stmarys):
            self.assertEqual(CardRevision.objects.count(), 0)

    def test_st_marys_principal_cannot_revise_a_grace_card(self):
        """Authority is per school, and the connection decides which school."""
        self.release_first_term_at_grace()

        with connected_to(self.grace):
            with self.assertRaises(NotAllowedToActOnResults):
                revision.revise(
                    self.their_child,
                    self.their_first_term(),
                    self.principal,
                    "Not my school.",
                )
            self.assertEqual(CardRevision.objects.count(), 0)


class AChildMovedOutOfTheClassTests(RevisionSetUp):
    """A revision re-freezes from the released class's marks. She has none there.

    `ClassPlacement` is one group per child per term, so moving Ada from JSS 1A
    to JSS 1B after JSS 1A released takes her off the roster the release was
    computed from. `positions.class_results()` for JSS 1A then has nothing to
    say about her — and every value it would produce is individually legal, so
    without a guard the revision writes a **blank version 2** over a card that
    had marks on it, and no constraint objects.
    """

    def setUp(self):
        super().setUp()
        self.sheet = self.release_first_term()
        with connected_to(self.stmarys):
            self.other_group = ClassGroup.objects.create(name="JSS 1B", level=1)
            move_student(self.other_group, self.first_term(), self.ada)

    def test_the_control_she_really_is_off_the_released_classs_roster(self):
        """Without this the guard below could be refusing for any other reason."""
        with connected_to(self.stmarys):
            self.assertNotIn(
                self.ada.pk,
                positions.roster_ids(self.group(self.stmarys), self.first_term()),
            )

    def test_reviving_her_card_is_refused_rather_than_blanked(self):
        with connected_to(self.stmarys):
            with self.assertRaises(revision.TheChildHasLeftThisClass):
                revision.revise(
                    self.ada, self.first_term(), self.principal, "Reissue."
                )

    def test_the_card_that_went_home_is_untouched(self):
        """The refusal is worth nothing if a partial write survived it."""
        with connected_to(self.stmarys):
            before = cards.card_for(self.ada, self.first_term())
            snapshot = (before.pk, before.version, before.own_average, before.position)

            with self.assertRaises(revision.TheChildHasLeftThisClass):
                revision.revise(
                    self.ada, self.first_term(), self.principal, "Reissue."
                )

            after = cards.card_for(self.ada, self.first_term())
            self.assertEqual(
                (after.pk, after.version, after.own_average, after.position), snapshot
            )
            self.assertEqual(
                ReleasedCard.objects.filter(
                    student_membership_id=self.ada.pk, version=2
                ).count(),
                0,
            )
            self.assertEqual(CardRevision.objects.count(), 0)

    def test_bola_who_stayed_can_still_be_revised(self):
        """The guard is about this child, not about the sheet having lost one."""
        with connected_to(self.stmarys):
            self.assertEqual(
                revision.revise(
                    self.bola, self.first_term(), self.principal, "Bola's reissue."
                ).version,
                2,
            )


class WhatARevisionCannotFixTests(RevisionSetUp):
    """The honest limit of this feature, pinned so it cannot be forgotten.

    A revision re-freezes a card from the live tables — and once a term is
    released, **every one of those tables refuses a write**.
    `gradebook.services`, `results.ratings` and `results.comments` all gate on
    `results.services.is_open_for_writing()`, which is false for anything past
    `draft`. So a revision issued to fix a wrong mark, a wrong rating or a wrong
    remark reproduces it exactly, and the only thing that can actually differ
    between two versions is a name copied from a table that is not gated on
    sheet state.

    That is issue #54. These tests are its shape written down; they go red when
    it is closed, which is the point of them.
    """

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            ratings.set_group_enabled(TraitGroup.AFFECTIVE, True)
            first = self.first_term()
            self.trait = Trait.objects.filter(group=TraitGroup.AFFECTIVE).first()
            ratings.rate(first, self.trait, self.ada, 4)
            comments.write(
                first, self.ada, CommentAuthor.CLASS_TEACHER, "A steady term."
            )
        self.release_first_term()

    def test_all_three_inputs_refuse_a_write_once_the_term_is_released(self):
        """Not just the marks, which is what #54 originally said."""
        with connected_to(self.stmarys):
            first = self.first_term()
            assessment = Assessment.objects.filter(term=first).first()

            with self.assertRaises(gradebook_services.MarksLocked):
                gradebook_services.set_score(
                    assessment, self.ada, 41, expected_version=1
                )
            with self.assertRaises(ratings.RatingsLocked):
                ratings.rate(first, self.trait, self.ada, 1)
            with self.assertRaises(comments.CommentsLocked):
                comments.write(
                    first, self.ada, CommentAuthor.CLASS_TEACHER, "Rewritten."
                )

    def test_none_of_the_three_refusals_promises_a_revision_will_fix_it(self):
        """All six of those messages said "correcting one is a revision rather
        than an edit" — true of the shape and false of the outcome, because
        there is no revision that can carry the correction. A teacher reading it
        went looking for a remedy that does not exist, and once task 8 shipped
        would have found a button that produces a byte-identical card.
        """
        with connected_to(self.stmarys):
            first = self.first_term()
            assessment = Assessment.objects.filter(term=first).first()

            refusals = []
            for attempt in (
                lambda: gradebook_services.set_score(
                    assessment, self.ada, 41, expected_version=1
                ),
                lambda: ratings.rate(first, self.trait, self.ada, 1),
                lambda: comments.write(
                    first, self.ada, CommentAuthor.CLASS_TEACHER, "Rewritten."
                ),
            ):
                with self.assertRaises(Exception) as caught:
                    attempt()
                refusals.append(str(caught.exception))

        for message in refusals:
            with self.subTest(message=message[:48]):
                self.assertNotIn("revision rather than an edit", message)
                self.assertIn("reissuing cannot yet reach", message)

    def test_a_revision_reproduces_the_card_because_nothing_upstream_could_move(self):
        """The consequence, stated as a fact about two rows rather than a mood.

        Everything a family sees is identical across the two versions. This is
        what #54 costs, and it is why that issue is blocking rather than tidy:
        the feature works exactly as designed and cannot yet do the thing a
        school would reach for it to do.
        """
        with connected_to(self.stmarys):
            first = self.first_term()
            before = cards.card_for(self.ada, first)
            was = (
                before.total_scored,
                before.total_available,
                before.own_average,
                before.student_name,
            )
            was_ratings = sorted(
                ReleasedTraitRating.objects.filter(card=before).values_list(
                    "trait_name", "score"
                )
            )
            was_remarks = sorted(
                ReleasedComment.objects.filter(card=before).values_list(
                    "author", "body"
                )
            )

            after = revision.revise(
                self.ada, first, self.principal, "Trying to fix a mark."
            )

            self.assertEqual(
                (
                    after.total_scored,
                    after.total_available,
                    after.own_average,
                    after.student_name,
                ),
                was,
            )
            self.assertEqual(
                sorted(
                    ReleasedTraitRating.objects.filter(card=after).values_list(
                        "trait_name", "score"
                    )
                ),
                was_ratings,
            )
            self.assertEqual(
                sorted(
                    ReleasedComment.objects.filter(card=after).values_list(
                        "author", "body"
                    )
                ),
                was_remarks,
            )
            # And the one thing it *can* fix is proven separately, in
            # `WhatActuallyChangesTests` — a name, from a table nothing here
            # gates on sheet state.


class WhatTheOtherReadersSawTests(RevisionSetUp):
    """Three readers that agreed with themselves until a second version existed.

    `cards.card_for()` states the rule for the whole card — **the earliest
    release, then its highest version** — and each of these implemented half of
    it or none, which was invisible while a sheet could hold only one card per
    child. Migration `0019` is what makes the second version possible, so this
    PR is what breaks them, and these are the tests that say so.
    """

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            ratings.set_group_enabled(TraitGroup.AFFECTIVE, True)
            self.trait = Trait.objects.filter(group=TraitGroup.AFFECTIVE).first()
            ratings.rate(self.first_term(), self.trait, self.ada, 4)

    def sections(self):
        return ratings.card_sections(
            self.ada.pk, self.group(self.stmarys), self.first_term()
        )

    def test_the_conduct_section_is_not_printed_twice_after_a_revision(self):
        """`_frozen_sections()` filtered on `(sheet, student)`.

        That pair was unique per child while
        `one_frozen_rating_per_student_per_trait` held it, so it could only ever
        select one card's worth of rows. `0019` re-keys that constraint onto the
        card, a revision writes a second set on the same sheet, and the filter
        returned **both** — every trait appended into `by_group` twice and the
        whole section printed doubled on the card a family reads.
        """
        self.release_first_term()
        with connected_to(self.stmarys):
            before = [line.name for section in self.sections() for line in section.lines]

            revision.revise(self.ada, self.first_term(), self.principal, "Reissued.")

            after = [line.name for section in self.sections() for line in section.lines]

        # The control. Every assertion below passes against a school that froze
        # no conduct section at all, which is why the rating is set up above.
        self.assertGreater(len(before), 0)
        self.assertEqual(len(after), len(before))
        self.assertEqual(sorted(after), sorted(set(after)), "A trait printed twice.")

    def test_the_frozen_session_line_read_back_is_the_revisions_not_the_first(self):
        """`released_session_line()` took the *earliest* row, always.

        Right between sheets — a released card keeps saying what it said — and
        wrong between versions of one sheet, where a revision is the whole
        point. `decide()` freezes `session_average` and the promotion
        *suggestion* off this row, so it read version 1 while `card_api` served
        version 2 to the family, and the two can genuinely differ: the line is
        recomputed from live first- and second-term marks and live weights.
        """
        for name in (TermName.SECOND.value, TermName.THIRD.value):
            self.mark(self.stmarys, name, self.ada, "maths", "Exam", 70)
            self.mark(self.stmarys, name, self.bola, "maths", "Exam", 60)

        with connected_to(self.stmarys):
            self.release_the_term(TermName.SECOND.value)
            self.release_the_term(TermName.THIRD.value)
            third = self.term(self.stmarys, TermName.THIRD.value)

            was = sessions.released_session_line(self.ada, SESSION)
            revised = revision.revise(
                self.ada, third, self.principal, "Third-term reissue."
            )
            now = sessions.released_session_line(self.ada, SESSION)

            # Asserted **inside** the context. `.card` is a lazy relation, so
            # reading it after `connected_to()` has landed the connection back
            # on `public` queries a schema where the table does not exist —
            # issue #58, which this test hit while being written.
            self.assertIsNotNone(was)
            self.assertEqual(was.card.version, 1)
            self.assertEqual(now.card_id, revised.pk)
            self.assertEqual(now.card.version, 2)

    def test_a_class_of_two_is_still_two_cards_on_the_sheet_after_a_revision(self):
        """`cards_on()` had no version filter at all.

        Its docstring names task 7's batch as the caller, so a forty-five child
        class coming back as forty-six is a superseded card rendered to PDF and
        sent home beside the one that replaced it.
        """
        sheet = self.release_first_term()
        with connected_to(self.stmarys):
            before = cards.cards_on(sheet)
            revised = revision.revise(
                self.ada, self.first_term(), self.principal, "Reissued."
            )
            after = cards.cards_on(sheet)

        self.assertEqual(len(before), 2)
        self.assertEqual(len(after), 2, "The superseded version came back as well.")
        self.assertEqual(
            {card.student_membership_id for card in after},
            {self.ada.pk, self.bola.pk},
        )
        self.assertIn(revised.pk, [card.pk for card in after])
        self.assertEqual(
            next(card for card in after if card.student_membership_id == self.ada.pk).version,
            2,
        )
