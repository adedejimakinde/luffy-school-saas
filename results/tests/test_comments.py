"""The two remarks on a report card: who signs them, and what a card keeps.

Two schools throughout, as everywhere in this project, and here the second earns
its place three times over: the phrase bank is per schema, the authority
question is asked at the school on the connection, and the freeze must not reach
across a schema boundary.

The sections:

- **authority**, which is the point of the task: the class teacher of that group
  writes the teacher's remark and nobody else; the principal writes the
  principal's and nobody else; neither may write the other's, and no vice
  principal or administrator may write either;
- the text rules — free, stripped, non-blank, and 250 characters;
- **empty means absent**: a remark nobody wrote produces no line at all, not a
  labelled empty box, and no comment ever blocks the chain;
- remarks follow the chain, editable in `draft` and not after, with a send-back
  opening them again;
- **the freeze**: release a card, then edit and delete the phrases it was
  written from, and the released remark is unchanged — with a control showing
  the same edits do not move a *live* comment either, because a comment stores
  what the teacher left rather than a reference to a phrase;
- the frozen rows are append-only, and a released term's live remarks are shut,
  both in the database rather than only in the service.
"""

import contextlib
from datetime import date

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from results import comments, services
from results.models import (
    MAX_COMMENT_LENGTH,
    CommentAuthor,
    CommentPhrase,
    ReleasedComment,
    ReportCardComment,
)
from schools.models import School

PASSWORD = "correct-horse-battery"

TEACHER = CommentAuthor.CLASS_TEACHER
PRINCIPAL = CommentAuthor.PRINCIPAL


def make_school(name, slug, schema_name):
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.save()
    return school


@contextlib.contextmanager
def connected_to(school):
    with schema_context(school.schema_name):
        yield


class CommentsSetUp(TestCase):
    """Two schools. St Mary's teaches JSS 1A (Kemi) and JSS 3B (Sade)."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.kemi = self._staff("kemi", "Kemi Bello", self.stmarys, Role.TEACHER)
        self.sade = self._staff("sade", "Sade Johnson", self.stmarys, Role.TEACHER)
        self.registrar = self._staff("bola", "Bola Ade", self.stmarys, Role.ADMIN)
        self.principal = self._staff(
            "tunde", "Tunde Alabi", self.stmarys, Role.PRINCIPAL
        )
        self.vp = self._staff(
            "ify", "Ify Nwosu", self.stmarys, Role.VICE_PRINCIPAL_ACADEMIC
        )

        self.their_teacher = self._staff("chika", "Chika Obi", self.grace, Role.TEACHER)
        self.their_principal = self._staff(
            "amaka", "Amaka Eze", self.grace, Role.PRINCIPAL
        )

        self.ada = self._student("ada", "Ada Obi", self.stmarys)
        self.bisi = self._student("bisi", "Bisi Lawal", self.stmarys)
        self.their_child = self._student("ngozi", "Ngozi Eze", self.grace)

        self.term_id, self.jss1a_id, self.jss3b_id = self._academics(self.stmarys)
        self.their_term_id, self.their_jss1a_id, _ = self._academics(self.grace)

        self._assign(self.stmarys, self.kemi, self.jss1a_id, self.term_id)
        self._assign(self.stmarys, self.sade, self.jss3b_id, self.term_id)
        self._assign(
            self.grace, self.their_teacher, self.their_jss1a_id, self.their_term_id
        )

        self._place(self.stmarys, self.ada, self.jss1a_id, self.term_id)
        self._place(self.stmarys, self.bisi, self.jss1a_id, self.term_id)
        self._place(
            self.grace, self.their_child, self.their_jss1a_id, self.their_term_id
        )

    # -- fixtures ------------------------------------------------------------

    def _staff(self, username, full_name, school, role):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, school, role)
        return user

    def _student(self, username, full_name, school):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, school, Role.STUDENT)
        return user

    def _academics(self, school):
        with connected_to(school):
            term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )
            jss1a = ClassGroup.objects.create(name="JSS 1A", level=1)
            jss3b = ClassGroup.objects.create(name="JSS 3B", level=3)
            return term.pk, jss1a.pk, jss3b.pk

    def _assign(self, school, user, class_group_id, term_id):
        membership = user.memberships.get(school=school, role=Role.TEACHER)
        with connected_to(school):
            academics.assign_class_teacher(
                ClassGroup.objects.get(pk=class_group_id),
                Term.objects.get(pk=term_id),
                membership,
            )

    def _place(self, school, user, class_group_id, term_id):
        membership = self.membership_of(user, school)
        with connected_to(school):
            academics.place_student(
                ClassGroup.objects.get(pk=class_group_id),
                Term.objects.get(pk=term_id),
                membership,
            )

    def membership_of(self, user, school=None):
        return user.memberships.get(school=school or self.stmarys, role=Role.STUDENT)

    # -- shorthands ----------------------------------------------------------

    def term(self):
        return Term.objects.get(pk=self.term_id)

    def jss1a(self):
        return ClassGroup.objects.get(pk=self.jss1a_id)

    def write(self, actor, author, body, student=None):
        return comments.write_as(
            actor,
            self.term(),
            self.membership_of(student or self.ada),
            author,
            body,
        )

    def lines(self, student=None):
        return comments.card_comments(
            self.membership_of(student or self.ada).pk, self.jss1a(), self.term()
        )

    def walk_to_released(self):
        """Take JSS 1A's sheet the whole way, with four different people.

        Refreshed before it is handed back: every step writes the *row* it
        locked and not the instance it was passed, so an unrefreshed copy still
        claims to be a draft four transitions later.
        """
        sheet = services.open_sheet(self.jss1a(), self.term(), self.principal)
        services.submit(sheet, self.kemi)
        services.check(sheet, self.vp)
        services.approve(sheet, self.principal)
        services.release(sheet, self.principal)
        sheet.refresh_from_db()
        return sheet

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()


class WhoSignsWhichRemarkTests(CommentsSetUp):
    """The point of the task. Each remark has exactly one author.

    A remark is signed. Printing a sentence under a teacher's name that the
    teacher did not write is the failure this section exists to prevent, and it
    is symmetrical: the principal may not write the teacher's remark either.
    """

    def test_the_class_teacher_writes_the_teachers_remark(self):
        with connected_to(self.stmarys):
            written = self.write(self.kemi, TEACHER, "A diligent term. Well done.")

            self.assertEqual(written.body, "A diligent term. Well done.")
            self.assertEqual(written.author, TEACHER.value)
            self.assertEqual(written.written_by_id, self.kemi.pk)

    def test_the_principal_writes_the_principals_remark(self):
        with connected_to(self.stmarys):
            written = self.write(self.principal, PRINCIPAL, "A promising result.")

            self.assertEqual(written.author, PRINCIPAL.value)
            self.assertEqual(written.written_by_id, self.principal.pk)

    def test_the_principal_may_not_write_the_teachers_remark(self):
        """Not a hierarchy question. It is whose name is under the sentence."""
        with connected_to(self.stmarys):
            with self.assertRaises(comments.NotAllowedToComment) as refused:
                self.write(self.principal, TEACHER, "Must try harder.")

            self.assertFalse(ReportCardComment.objects.exists())

        self.assertIn("class teacher", str(refused.exception))

    def test_the_class_teacher_may_not_write_the_principals_remark(self):
        with connected_to(self.stmarys):
            with self.assertRaises(comments.NotAllowedToComment) as refused:
                self.write(self.kemi, PRINCIPAL, "Promoted to JSS 2.")

            self.assertFalse(ReportCardComment.objects.exists())

        self.assertIn("principal", str(refused.exception))

    def test_another_class_teacher_may_not_write_about_our_child(self):
        with connected_to(self.stmarys):
            with self.assertRaises(comments.NotAllowedToComment):
                self.write(self.sade, TEACHER, "Distracted this term.")

            self.assertFalse(ReportCardComment.objects.exists())

    def test_neither_the_vice_principal_nor_the_office_may_write_either(self):
        """The VP checks the sheet and the registrar may submit it. Neither signs it."""
        for actor in (self.vp, self.registrar):
            for author in (TEACHER, PRINCIPAL):
                with self.subTest(actor=str(actor), author=author.value):
                    with connected_to(self.stmarys):
                        with self.assertRaises(comments.NotAllowedToComment):
                            self.write(actor, author, "Satisfactory.")

        with connected_to(self.stmarys):
            self.assertFalse(ReportCardComment.objects.exists())

    def test_the_other_schools_teacher_may_not_write_about_our_child(self):
        """Authority is asked at the school on the connection, not at the actor's."""
        with connected_to(self.stmarys):
            with self.assertRaises(comments.NotAllowedToComment):
                self.write(self.their_teacher, TEACHER, "Improving.")

            self.assertFalse(ReportCardComment.objects.exists())

    def test_the_other_schools_principal_may_not_write_ours_either(self):
        """A principal signs every card *in their school*, and no others."""
        with connected_to(self.stmarys):
            with self.assertRaises(comments.NotAllowedToComment):
                self.write(self.their_principal, PRINCIPAL, "A fine term.")

            self.assertFalse(ReportCardComment.objects.exists())

    def test_a_group_with_no_class_teacher_says_so(self):
        with connected_to(self.stmarys):
            academics.unassign_class_teacher(self.jss1a(), self.term())

            with self.assertRaises(comments.NotAllowedToComment) as refused:
                self.write(self.kemi, TEACHER, "A good term.")

        self.assertIn("no class teacher", str(refused.exception))

    def test_the_principals_remark_does_not_need_a_class_teacher(self):
        """It is not scoped to a group, so an unassigned class does not stop it."""
        with connected_to(self.stmarys):
            academics.unassign_class_teacher(self.jss1a(), self.term())

            self.assertEqual(
                self.write(self.principal, PRINCIPAL, "Keep it up.").author,
                PRINCIPAL.value,
            )

    def test_a_child_in_no_class_group_cannot_be_written_about(self):
        with connected_to(self.stmarys):
            placement = academics.placement_of(
                self.membership_of(self.bisi).pk, self.term()
            )
            placement.delete()

            with self.assertRaises(comments.NotPlacedThisTerm):
                self.write(self.kemi, TEACHER, "A quiet term.", student=self.bisi)

    def test_another_schools_child_is_not_ours_to_write_about(self):
        with connected_to(self.stmarys):
            with self.assertRaises(comments.NotThisSchoolsStudent):
                comments.write_as(
                    self.kemi,
                    self.term(),
                    self.membership_of(self.their_child, self.grace),
                    TEACHER,
                    "Improving.",
                )


class WhatARemarkMaySayTests(CommentsSetUp):
    """Free text, stripped, saying something, and inside the box on the card."""

    def test_a_remark_is_stored_as_typed_apart_from_the_edges(self):
        with connected_to(self.stmarys):
            written = self.write(self.kemi, TEACHER, "  Excellent term.  ")

            self.assertEqual(written.body, "Excellent term.")

    def test_the_longest_remark_that_fits_is_accepted(self):
        with connected_to(self.stmarys):
            written = self.write(self.kemi, TEACHER, "x" * MAX_COMMENT_LENGTH)

            self.assertEqual(len(written.body), MAX_COMMENT_LENGTH)

    def test_one_character_more_is_refused_with_the_number_in_it(self):
        """The screen counts down against this limit, so it has to be the same one."""
        with connected_to(self.stmarys):
            with self.assertRaises(comments.CommentsError) as refused:
                self.write(self.kemi, TEACHER, "x" * (MAX_COMMENT_LENGTH + 1))

            self.assertFalse(ReportCardComment.objects.exists())

        self.assertIn(str(MAX_COMMENT_LENGTH), str(refused.exception))

    def test_a_blank_remark_is_refused_rather_than_stored(self):
        """Empty and absent are the same thing here, and absent is a missing row."""
        for blank in ("", "   ", "\n\t"):
            with self.subTest(blank=repr(blank)):
                with connected_to(self.stmarys):
                    with self.assertRaises(comments.CommentsError):
                        self.write(self.kemi, TEACHER, blank)

    def test_the_database_refuses_a_blank_one_too(self):
        """The service is not the guarantee — an import never calls it."""
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReportCardComment.objects.create(
                        term=self.term(),
                        student_membership_id=self.membership_of(self.ada).pk,
                        author=TEACHER.value,
                        body="   ",
                    )

    def test_clearing_removes_the_row_rather_than_blanking_it(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A good term.")

            self.assertTrue(
                comments.clear_as(
                    self.kemi, self.term(), self.membership_of(self.ada), TEACHER
                )
            )
            self.assertFalse(ReportCardComment.objects.exists())
            self.assertFalse(
                comments.clear_as(
                    self.kemi, self.term(), self.membership_of(self.ada), TEACHER
                ),
                "clearing what is not there is False, not an error",
            )


class AnEmptyRemarkIsAbsentTests(CommentsSetUp):
    """Not a labelled box with nothing in it. Nothing at all."""

    def test_a_card_with_no_remarks_has_no_lines(self):
        with connected_to(self.stmarys):
            self.assertEqual(self.lines(), [])

    def test_one_remark_prints_one_line_not_two(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")

            [line] = self.lines()
            self.assertEqual(line.author, TEACHER.value)
            self.assertEqual(line.body, "A diligent term.")
            self.assertEqual(line.heading, TEACHER.label)

    def test_both_print_in_declaration_order_not_alphabetical(self):
        with connected_to(self.stmarys):
            self.write(self.principal, PRINCIPAL, "A promising result.")
            self.write(self.kemi, TEACHER, "A diligent term.")

            self.assertEqual(
                [line.author for line in self.lines()],
                [TEACHER.value, PRINCIPAL.value],
                "the teacher's remark prints first, as the card is laid out",
            )

    def test_a_missing_remark_does_not_block_the_chain(self):
        """Schools release cards with a blank principal's remark. This is that."""
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            sheet = self.walk_to_released()

            self.assertEqual(sheet.state, "released")
            self.assertEqual([line.author for line in self.lines()], [TEACHER.value])

    def test_a_card_with_neither_remark_releases_and_freezes_nothing(self):
        with connected_to(self.stmarys):
            sheet = self.walk_to_released()

            self.assertEqual(sheet.state, "released")
            self.assertEqual(ReleasedComment.objects.count(), 0)
            self.assertEqual(self.lines(), [])

    def test_it_reports_what_is_outstanding_without_enforcing_it(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            outstanding = comments.missing(self.jss1a(), self.term())

        ada = self.membership_of(self.ada).pk
        bisi = self.membership_of(self.bisi).pk
        self.assertEqual(outstanding[ada], [PRINCIPAL.value])
        self.assertEqual(outstanding[bisi], [TEACHER.value, PRINCIPAL.value])

    def test_what_it_reports_is_what_write_as_takes(self):
        """Values, not labels — pinned by using them rather than by asserting.

        The screen this exists for links "still to write" to the box that writes
        it, so the two ends have to speak the same alphabet. Asserting the
        strings would pass just as well against labels that no caller can use;
        feeding them back to `write_as()` is the claim itself. A label arriving
        here would be refused by `_author()`, which is the regression.
        """
        with connected_to(self.stmarys):
            outstanding = comments.missing(self.jss1a(), self.term())

            for author in outstanding[self.membership_of(self.ada).pk]:
                actor = self.kemi if author == TEACHER.value else self.principal
                self.write(actor, author, f"Written from {author}.")

            self.assertEqual(comments.missing(self.jss1a(), self.term()).keys(),
                             {self.membership_of(self.bisi).pk})
            self.assertEqual(
                sorted(line.author for line in self.lines()),
                sorted([TEACHER.value, PRINCIPAL.value]),
            )


class ThePhraseBankTests(CommentsSetUp):
    """The school's own canned remarks — two lists, not one pool filtered."""

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            self.diligent = comments.add_phrase_as(
                self.principal, TEACHER, "A diligent term. Well done."
            )
            self.quiet = comments.add_phrase_as(
                self.principal, TEACHER, "Quiet, but improving steadily."
            )
            self.promoted = comments.add_phrase_as(
                self.principal, PRINCIPAL, "Promoted to the next class."
            )

    def texts(self, author):
        return [phrase.text for phrase in comments.phrases(author)]

    def test_each_signatory_has_their_own_list(self):
        with connected_to(self.stmarys):
            self.assertEqual(
                self.texts(TEACHER),
                ["A diligent term. Well done.", "Quiet, but improving steadily."],
            )
            self.assertEqual(self.texts(PRINCIPAL), ["Promoted to the next class."])

    def test_a_teachers_phrase_never_appears_in_the_principals_list(self):
        """The separation is the requirement, not a convenience of the screen."""
        with connected_to(self.stmarys):
            self.assertNotIn("A diligent term. Well done.", self.texts(PRINCIPAL))
            self.assertNotIn("Promoted to the next class.", self.texts(TEACHER))

    def test_a_phrase_lands_at_the_end_of_its_own_list(self):
        with connected_to(self.stmarys):
            comments.add_phrase_as(self.principal, TEACHER, "Must improve punctuality.")

            self.assertEqual(self.texts(TEACHER)[-1], "Must improve punctuality.")

    def test_a_school_may_reorder_and_the_tail_follows(self):
        with connected_to(self.stmarys):
            comments.add_phrase_as(self.principal, TEACHER, "Must improve punctuality.")
            before = self.texts(TEACHER)

            comments.reorder_phrases_as(
                self.principal, TEACHER, [self.quiet.pk, self.diligent.pk]
            )
            after = self.texts(TEACHER)

        self.assertEqual(after[:2], [self.quiet.text, self.diligent.text])
        self.assertEqual(
            after[2:],
            [text for text in before if text not in after[:2]],
            "phrases the screen did not name follow the ones it did",
        )

    def test_reordering_ignores_ids_from_the_other_list(self):
        with connected_to(self.stmarys):
            comments.reorder_phrases_as(self.principal, PRINCIPAL, [self.diligent.pk])
            self.diligent.refresh_from_db()

            self.assertEqual(self.diligent.author, TEACHER.value)
            self.assertEqual(self.texts(PRINCIPAL), ["Promoted to the next class."])

    def test_a_phrase_is_deleted_rather_than_hidden(self):
        """Nothing names a phrase, so there is no evidence to take with it."""
        with connected_to(self.stmarys):
            self.assertTrue(comments.remove_phrase_as(self.principal, self.quiet))
            self.assertEqual(self.texts(TEACHER), ["A diligent term. Well done."])

    def test_only_the_office_may_change_the_bank(self):
        with connected_to(self.stmarys):
            for actor in (self.kemi, self.vp):
                with self.subTest(actor=str(actor)):
                    with self.assertRaises(comments.NotAllowedToConfigurePhrases):
                        comments.add_phrase_as(actor, TEACHER, "Tries hard.")

    def test_one_schools_bank_is_not_the_others(self):
        with connected_to(self.grace):
            self.assertEqual(CommentPhrase.objects.count(), 0)

            comments.add_phrase_as(self.their_principal, TEACHER, "Doing well.")

        with connected_to(self.stmarys):
            self.assertNotIn("Doing well.", self.texts(TEACHER))


class RemarksFollowTheChainTests(CommentsSetUp):
    """Part of what gets submitted, checked and approved — so they stop moving."""

    def test_remarks_may_be_written_before_the_sheet_exists(self):
        with connected_to(self.stmarys):
            self.assertIsNone(comments.sheet_for(self.jss1a(), self.term()))
            self.assertEqual(
                self.write(self.kemi, TEACHER, "A diligent term.").body,
                "A diligent term.",
            )

    def test_a_submitted_sheet_shuts_its_remarks(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            sheet = services.open_sheet(self.jss1a(), self.term(), self.principal)
            services.submit(sheet, self.kemi)

            with self.assertRaises(comments.CommentsLocked) as refused:
                self.write(self.kemi, TEACHER, "On second thoughts.")

        self.assertEqual(refused.exception.state, "submitted")
        self.assertIn("being reviewed", str(refused.exception))

    def test_a_send_back_opens_them_again(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            sheet = services.open_sheet(self.jss1a(), self.term(), self.principal)
            services.submit(sheet, self.kemi)
            services.send_back(sheet, self.vp, "Ada's remark reads oddly.")

            self.assertEqual(
                self.write(self.kemi, TEACHER, "A diligent term, and improving.").body,
                "A diligent term, and improving.",
            )

    def test_a_released_sheet_shuts_them_for_good(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            self.walk_to_released()

            with self.assertRaises(comments.CommentsLocked) as refused:
                self.write(self.kemi, TEACHER, "On second thoughts.")

        self.assertEqual(refused.exception.state, "released")
        self.assertIn("revision", str(refused.exception))

    def test_another_classs_sheet_does_not_shut_ours(self):
        with connected_to(self.stmarys):
            jss3b = ClassGroup.objects.get(pk=self.jss3b_id)
            other = services.open_sheet(jss3b, self.term(), self.principal)
            services.submit(other, self.sade)

            self.assertEqual(
                self.write(self.kemi, TEACHER, "A diligent term.").body,
                "A diligent term.",
            )

    def test_the_database_shuts_them_too(self):
        """The service is not the guarantee — an import never calls it."""
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            self.walk_to_released()

            with self.assertRaises(IntegrityError) as refused:
                with transaction.atomic():
                    ReportCardComment.objects.filter(term=self.term()).update(
                        body="Rewritten from psql."
                    )

            self.assertIn("released", str(refused.exception))

    def test_the_database_refuses_a_new_remark_for_a_released_term(self):
        with connected_to(self.stmarys):
            self.walk_to_released()

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReportCardComment.objects.create(
                        term=self.term(),
                        student_membership_id=self.membership_of(self.ada).pk,
                        author=PRINCIPAL.value,
                        body="Written after the fact.",
                    )


class TheFreezeTests(CommentsSetUp):
    """**The one to get right.** A released card does not change. Ever.

    The task asks for the ratings shape: release a card, then edit and delete
    the phrases it was written from, and assert the released remark is
    unchanged. It passes, and the reason it passes is worth stating rather than
    leaving to be inferred — **a comment stores the sentence the teacher left,
    not a reference to a phrase.** The denormalisation happens at write time, so
    there is no join for a later edit to travel along.

    That makes the phrase half of this section a *structural* test: it fails the
    moment somebody replaces the copied text with a foreign key, which is the
    tidy-looking change this design is refusing. The control below proves the
    same edits do not move a live, unreleased comment either — if they did, the
    freeze would be hiding a bug rather than preventing one.

    The freeze itself then guards the other direction: edits to the *comment*.
    """

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            self.phrase = comments.add_phrase_as(
                self.principal, TEACHER, "A diligent term. Well done."
            )
            self.principal_phrase = comments.add_phrase_as(
                self.principal, PRINCIPAL, "Promoted to the next class."
            )

    def written_from_the_bank(self):
        """Both remarks, written by clicking a phrase and leaving it as it came."""
        self.write(self.kemi, TEACHER, self.phrase.text)
        self.write(self.principal, PRINCIPAL, self.principal_phrase.text)

    def test_a_released_card_survives_every_edit_to_the_phrase_bank(self):
        with connected_to(self.stmarys):
            self.written_from_the_bank()
            self.walk_to_released()
            before = [(line.author, line.body) for line in self.lines()]

            comments.edit_phrase_as(
                self.principal, self.phrase, "Must try considerably harder."
            )
            comments.remove_phrase_as(self.principal, self.principal_phrase)

            self.assertEqual(
                [(line.author, line.body) for line in self.lines()], before
            )

    def test_and_the_card_it_survived_as_is_the_right_one(self):
        """A card that never changes but was wrong at release is no better."""
        with connected_to(self.stmarys):
            self.written_from_the_bank()
            self.walk_to_released()

            self.assertEqual(
                [(line.heading, line.body) for line in self.lines()],
                [
                    (TEACHER.label, "A diligent term. Well done."),
                    (PRINCIPAL.label, "Promoted to the next class."),
                ],
            )

    def test_the_control_a_live_comment_does_not_move_either(self):
        """Because the text was copied at write time, not joined at read time.

        This is the half that would fail if a comment referred to its phrase.
        """
        with connected_to(self.stmarys):
            self.written_from_the_bank()

            comments.edit_phrase_as(
                self.principal, self.phrase, "Must try considerably harder."
            )
            comments.remove_phrase_as(self.principal, self.principal_phrase)

            self.assertEqual(
                [line.body for line in self.lines()],
                ["A diligent term. Well done.", "Promoted to the next class."],
            )

    def test_a_released_remark_survives_the_child_moving_class(self):
        """The freeze is about `(term, student, author)`, not where the child sits.

        Both halves of the guard — the service and 0009's trigger — used to ask
        "is this child's *current* class released?", which is a different
        question and gives the wrong answer the moment the office moves anybody.
        Release JSS 1A with Ada's remark frozen, move Ada to JSS 3B, whose sheet
        nobody has opened, and JSS 3B's class teacher inherits a child whose
        card is already in a parent's hand. Answering by placement, the guard
        looks at JSS 3B, finds a draft, and lets the rewrite through: the frozen
        card reads one thing and the school's screen another, which is the
        disagreement `0009`'s docstring exists to prevent.

        The move itself is legitimate and stays allowed — a child really does
        change class mid-term. It is the *rewrite* that is refused.
        """
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "Written in JSS 1A.")
            sheet = self.walk_to_released()
            frozen_before = list(
                ReleasedComment.objects.filter(sheet=sheet).values_list(
                    "student_membership_id", "author", "body"
                )
            )

            academics.move_student(
                ClassGroup.objects.get(pk=self.jss3b_id),
                self.term(),
                self.membership_of(self.ada),
            )

            # Sade teaches JSS 3B, so she is now Ada's class teacher — and still
            # may not rewrite a remark that has been released.
            with self.assertRaises(comments.CommentsLocked):
                comments.write_as(
                    self.sade,
                    self.term(),
                    self.membership_of(self.ada),
                    TEACHER,
                    "Rewritten in JSS 3B.",
                )

            with self.assertRaises(comments.CommentsLocked):
                comments.clear_as(
                    self.sade, self.term(), self.membership_of(self.ada), TEACHER
                )

            self.assertEqual(
                list(
                    ReleasedComment.objects.filter(sheet=sheet).values_list(
                        "student_membership_id", "author", "body"
                    )
                ),
                frozen_before,
            )
            self.assertEqual(
                ReportCardComment.objects.get(
                    term=self.term(),
                    student_membership_id=self.membership_of(self.ada).pk,
                    author=TEACHER.value,
                ).body,
                "Written in JSS 1A.",
                "the live row is untouched too, not merely the frozen copy",
            )

    def test_the_database_refuses_the_rewrite_even_without_the_service(self):
        """The trigger half, reached the way `.update()` reaches it.

        `_require_the_sheet_is_open()` can be bypassed — `.update()` never calls
        `save()`, and a management command or a shell does not go through the
        service at all. The guarantee has to hold in the database or it is not a
        guarantee, which is the argument `0007` and `0009` were written on.
        """
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "Written in JSS 1A.")
            self.walk_to_released()

            academics.move_student(
                ClassGroup.objects.get(pk=self.jss3b_id),
                self.term(),
                self.membership_of(self.ada),
            )

            with self.assertRaises(IntegrityError):
                ReportCardComment.objects.filter(
                    term=self.term(),
                    student_membership_id=self.membership_of(self.ada).pk,
                    author=TEACHER.value,
                ).update(body="Rewritten straight at the table.")

    def test_the_freeze_records_only_the_remarks_that_exist(self):
        """No row for a remark nobody wrote — absent stays absent, frozen too."""
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            sheet = self.walk_to_released()

            frozen = ReleasedComment.objects.filter(sheet=sheet)
            self.assertEqual(
                [(row.student_membership_id, row.author) for row in frozen],
                [(self.membership_of(self.ada).pk, TEACHER.value)],
                "Bisi has no remark and Ada has no principal's remark: no rows",
            )

    def test_every_child_with_a_remark_is_frozen_not_only_the_first(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            self.write(self.kemi, TEACHER, "A quiet term.", student=self.bisi)
            sheet = self.walk_to_released()

            self.assertEqual(ReleasedComment.objects.filter(sheet=sheet).count(), 2)

    def test_the_frozen_rows_are_append_only_in_the_database(self):
        """`.update()` never calls `save()`, which is why the trigger exists."""
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            sheet = self.walk_to_released()

            with self.assertRaises(IntegrityError) as refused:
                with transaction.atomic():
                    ReleasedComment.objects.filter(sheet=sheet).update(
                        body="Rewritten."
                    )

            self.assertIn("append-only", str(refused.exception))

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedComment.objects.filter(sheet=sheet).delete()

    def test_the_model_refuses_before_the_database_has_to(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            sheet = self.walk_to_released()
            row = ReleasedComment.objects.filter(sheet=sheet).first()
            row.body = "Rewritten."

            with self.assertRaises(Exception) as refused:
                row.save()

        self.assertIn("released", str(refused.exception))

    def test_the_other_schools_card_is_untouched_by_our_release(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            self.walk_to_released()

        with connected_to(self.grace):
            self.assertEqual(ReleasedComment.objects.count(), 0)


class ACorrectionKeepsItsAuthorTests(CommentsSetUp):
    """`written_by_id` names whose remark it is; `updated_by_id` moves."""

    def test_the_author_survives_a_correction(self):
        with connected_to(self.stmarys):
            first = self.write(self.kemi, TEACHER, "A diligent term.")
            # The office reassigns JSS 1A mid-term, and the new class teacher
            # rewrites the remark. Two different people on one row, which is the
            # only way this table sees two.
            academics.unassign_class_teacher(self.jss1a(), self.term())
            academics.assign_class_teacher(
                self.jss1a(),
                self.term(),
                self.sade.memberships.get(school=self.stmarys, role=Role.TEACHER),
            )
            corrected = self.write(self.sade, TEACHER, "A steady term.")

            self.assertEqual(ReportCardComment.objects.count(), 1)

        self.assertEqual(corrected.pk, first.pk, "a correction, not a second remark")
        self.assertEqual(corrected.body, "A steady term.")
        self.assertEqual(corrected.written_by_id, self.kemi.pk)
        self.assertEqual(corrected.updated_by_id, self.sade.pk)
        self.assertEqual(corrected.created_at, first.created_at)
        self.assertGreater(corrected.updated_at, first.updated_at)


class TheServiceRefusesWhatTheTableWouldTests(CommentsSetUp):
    """Every refusal a caller can trigger arrives as a `CommentsError`.

    The bug class task 4's review found four ways over, and this branch had
    reopened three of them. A raw `IntegrityError` or `ValueError` out of here
    is wrong twice: it is outside `ResultsError`, so a caller wrapping "get this
    class's results out" misses it and the screen shows a 500 naming a
    constraint — and an `IntegrityError` marks the enclosing transaction
    unusable, so a school saving a batch of phrases cannot go on to the next one
    after a duplicate.
    """

    def test_an_unknown_signatory_is_this_modules_refusal_not_a_value_error(self):
        """`CommentAuthor("form_master")` raises `ValueError`, which nothing catches."""
        with connected_to(self.stmarys):
            for act in (
                lambda: comments.phrases("form_master"),
                lambda: comments.add_phrase_as(
                    self.principal, "form_master", "Well done."
                ),
                lambda: comments.reorder_phrases_as(self.principal, "form_master", []),
                lambda: self.write(self.kemi, "form_master", "Well done."),
            ):
                with self.subTest(act=act):
                    with self.assertRaises(comments.CommentsError) as refused:
                        act()
                    self.assertIn("form_master", str(refused.exception))

    def test_the_computed_end_of_the_list_cannot_run_past_the_column(self):
        """Guarding the argument and not the computed value guards nothing.

        `add_phrase()` without a `position` appends at `last + 1`, and that sum
        was never checked — so a list whose last phrase sits at
        `HIGHEST_POSITION` overflowed `smallint` on the very next append, as a
        `DataError` outside the hierarchy that takes the transaction with it.
        The refusal the caller *did* pass through made no difference: it is the
        same escape, reached by the path the guard was not watching.
        """
        with connected_to(self.stmarys):
            comments.add_phrase_as(
                self.principal,
                TEACHER,
                "The last place there is.",
                position=comments.HIGHEST_POSITION,
            )

            with transaction.atomic():
                with self.assertRaises(comments.CommentsError) as refused:
                    comments.add_phrase_as(self.principal, TEACHER, "One too many.")

                # Still usable, which a `DataError` would not have left it.
                comments.add_phrase_as(
                    self.principal, TEACHER, "Somewhere earlier.", position=0
                )

        self.assertIn(str(comments.HIGHEST_POSITION), str(refused.exception))

    def test_a_phrase_id_is_taken_where_an_instance_is(self):
        """A screen posts an id, not a model. `phrase.pk` on an `int` is an
        `AttributeError` — outside the hierarchy, and a 500 naming nothing."""
        with connected_to(self.stmarys):
            phrase = comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")

            self.assertEqual(
                comments.edit_phrase_as(self.principal, phrase.pk, "Reworded.").text,
                "Reworded.",
            )
            self.assertTrue(comments.remove_phrase_as(self.principal, phrase.pk))

    def test_junk_where_a_phrase_belongs_is_this_modules_refusal(self):
        """An id that names nothing, and things that are not ids at all."""
        with connected_to(self.stmarys):
            for phrase in (9_999, "not-an-id", None, 1.5):
                with self.subTest(phrase=phrase):
                    with self.assertRaises(comments.CommentsError):
                        comments.remove_phrase_as(self.principal, phrase)

    def test_a_position_that_is_not_a_place_in_the_list_is_refused(self):
        """`position` is an exposed keyword, so a screen reaches the column with it.

        Each of these is a different escape from this module's hierarchy, which
        is why they are listed rather than summarised: `-1` and `70000` are the
        column's refusals (`IntegrityError`, then `smallint` overflow), `"first"`
        is a `DataError`, and `1.5` a `ValueError` out of the query compiler.
        `True` is the quiet one — it is an `int`, so nothing downstream objects
        and the phrase silently lands at position 1.
        """
        with connected_to(self.stmarys):
            for position in (-1, 70_000, "first", 1.5, True):
                with self.subTest(position=position):
                    with self.assertRaises(comments.CommentsError):
                        comments.add_phrase_as(
                            self.principal, TEACHER, "Tries hard.", position=position
                        )

            self.assertFalse(CommentPhrase.objects.exists())

    def test_a_refused_position_leaves_the_transaction_usable(self):
        """The half that matters: an `IntegrityError` would have poisoned it."""
        with connected_to(self.stmarys):
            with transaction.atomic():
                with self.assertRaises(comments.CommentsError):
                    comments.add_phrase_as(
                        self.principal, TEACHER, "Tries hard.", position=-1
                    )
                comments.add_phrase_as(self.principal, TEACHER, "A quiet term.")

            self.assertEqual(
                [phrase.text for phrase in comments.phrases(TEACHER)], ["A quiet term."]
            )

    def test_the_column_is_what_makes_that_guard_worth_having(self):
        """What the table does when the service does not go first.

        The test above shows the guard holding; this shows the cost of its
        absence, which is the half a passing test cannot demonstrate on its own.
        The same `-1` written straight at the column raises `IntegrityError` —
        outside `ResultsError`, so every caller wrapping "get this class's
        results out" misses it — and leaves the enclosing transaction unusable,
        so the school's next phrase cannot be saved either. That second sentence
        is what the guard is really for: the error is recoverable, the poisoned
        transaction is not.
        """
        with connected_to(self.stmarys):
            with transaction.atomic():
                with self.assertRaises(IntegrityError):
                    CommentPhrase.objects.create(
                        author=TEACHER.value,
                        text="Straight to the column.",
                        position=-1,
                    )

                with self.assertRaises(transaction.TransactionManagementError):
                    CommentPhrase.objects.exists()

    def test_a_string_of_ids_is_refused_rather_than_iterated(self):
        """`"12,9"` is a sequence — of characters. That is the whole bug.

        `int()` succeeds on "1", "2" and "9" and skips the comma, so the list is
        renumbered against three ids the school never named and the call reports
        success. It is the silent no-op `as_ids()` was extracted to prevent,
        wearing different clothes, and no exception marks it.
        """
        with connected_to(self.stmarys):
            first = comments.add_phrase_as(self.principal, TEACHER, "First.")
            second = comments.add_phrase_as(self.principal, TEACHER, "Second.")

            with self.assertRaises(services.ResultsError):
                comments.reorder_phrases_as(
                    self.principal, TEACHER, f"{second.pk},{first.pk}"
                )

            self.assertEqual(
                [phrase.text for phrase in comments.phrases(TEACHER)],
                ["First.", "Second."],
                "nothing moved",
            )

    def test_ids_that_are_not_a_sequence_at_all_are_this_modules_refusal(self):
        """`None` would iterate into a bare `TypeError`, outside the hierarchy."""
        with connected_to(self.stmarys):
            for phrase_ids in (None, 7):
                with self.subTest(phrase_ids=phrase_ids):
                    with self.assertRaises(services.ResultsError):
                        comments.reorder_phrases_as(
                            self.principal, TEACHER, phrase_ids
                        )

    def test_a_blank_phrase_is_refused_in_the_phrase_banks_own_words(self):
        """Same rule as a remark, different reader.

        "Clear it instead" is advice about `clear()`, which exists for a remark
        on a card and has no counterpart here — there is no card in front of an
        administrator curating the bank, and nothing to clear.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(comments.CommentsError) as refused:
                comments.add_phrase_as(self.principal, TEACHER, "   ")

        message = str(refused.exception)
        self.assertIn("phrase", message)
        self.assertNotIn("Clear it instead", message)

    def test_offering_the_same_phrase_twice_is_refused_before_it_is_inserted(self):
        with connected_to(self.stmarys):
            comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")

            with self.assertRaises(comments.CommentsError) as refused:
                comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")

            self.assertIn("A diligent term.", str(refused.exception))
            self.assertEqual(CommentPhrase.objects.for_author(TEACHER).count(), 1)

    def test_the_refusal_leaves_the_transaction_usable(self):
        """The half an `IntegrityError` cannot give you, and the reason to check first.

        A school pasting in its list wants the eleven good ones saved and the
        duplicate reported, not the whole block rolled back.
        """
        with connected_to(self.stmarys):
            with transaction.atomic():
                comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")
                with self.assertRaises(comments.CommentsError):
                    comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")
                comments.add_phrase_as(self.principal, TEACHER, "A quiet term.")

            self.assertEqual(
                [phrase.text for phrase in comments.phrases(TEACHER)],
                ["A diligent term.", "A quiet term."],
            )

    def test_the_same_sentence_for_the_other_signatory_is_fine(self):
        """Per author, not per school — the constraint says so and it is right."""
        with connected_to(self.stmarys):
            comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")
            comments.add_phrase_as(self.principal, PRINCIPAL, "A diligent term.")

            self.assertEqual(CommentPhrase.objects.count(), 2)

    def test_an_edit_onto_a_phrase_already_offered_is_refused(self):
        with connected_to(self.stmarys):
            comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")
            second = comments.add_phrase_as(self.principal, TEACHER, "A quiet term.")

            with self.assertRaises(comments.CommentsError):
                comments.edit_phrase_as(self.principal, second, "A diligent term.")

            second.refresh_from_db()
            self.assertEqual(second.text, "A quiet term.")

    def test_editing_a_phrase_to_what_it_already_says_is_not_a_clash(self):
        """`except_pk` — the row must not find itself."""
        with connected_to(self.stmarys):
            phrase = comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")

            self.assertEqual(
                comments.edit_phrase_as(
                    self.principal, phrase, "A diligent term."
                ).text,
                "A diligent term.",
            )

    def test_ids_that_arrive_as_strings_still_reorder(self):
        """A drag-and-drop posts JSON, and JSON ids arrive as text.

        Matched against a dict keyed by `pk`, every one misses: the list is
        renumbered into the order it was already in, nothing moves, and the
        screen is told 0 rows changed — a silent no-op reported as success.
        """
        with connected_to(self.stmarys):
            texts = ["First.", "Second.", "Third."]
            made = [
                comments.add_phrase_as(self.principal, TEACHER, text) for text in texts
            ]

            moved = comments.reorder_phrases_as(
                self.principal, TEACHER, [str(made[2].pk), str(made[0].pk)]
            )

            self.assertTrue(moved)
            self.assertEqual(
                [phrase.text for phrase in comments.phrases(TEACHER)],
                ["Third.", "First.", "Second."],
            )


class APhraseIsWrittenToTheRowNotTheInstanceTests(CommentsSetUp):
    """Both writes compile to `WHERE id = <pk>`; the checks must read that row.

    `ratings._the_trait_row()` states the case, and it holds here on the same
    two verbs: an instance read on another school's connection, deserialised
    from a cache or built by hand carries whatever its fields say, while the
    write lands on whichever of *our* rows holds that id.
    """

    def test_a_phrase_that_is_not_in_this_schema_is_refused_by_name(self):
        with connected_to(self.stmarys):
            missing = CommentPhrase(pk=9_999, author=TEACHER, text="Invented.")

            for act in (
                lambda: comments.edit_phrase_as(self.principal, missing, "Anything."),
                lambda: comments.remove_phrase_as(self.principal, missing),
            ):
                with self.subTest(act=act):
                    with self.assertRaises(comments.CommentsError) as refused:
                        act()
                    self.assertIn("9999", str(refused.exception).replace(",", ""))

    def test_the_duplicate_check_reads_the_rows_author_not_the_arguments(self):
        """An instance can claim any signatory. Believe it and the clash is
        looked for in the wrong list, so the edit is allowed through and
        `uniq_comment_phrase_per_author` refuses it as an `IntegrityError`.
        """
        with connected_to(self.stmarys):
            comments.add_phrase_as(self.principal, TEACHER, "A diligent term.")
            second = comments.add_phrase_as(self.principal, TEACHER, "A quiet term.")
            claiming_principal = CommentPhrase(
                pk=second.pk, author=PRINCIPAL, text=second.text
            )

            with self.assertRaises(comments.CommentsError):
                comments.edit_phrase_as(
                    self.principal, claiming_principal, "A diligent term."
                )

            second.refresh_from_db()
            self.assertEqual(second.text, "A quiet term.")


class TheGuardAndTheWriteShareOnePlacementTests(CommentsSetUp):
    """`write_as()` authorises against a placement; `write()` must use that one.

    Reading it twice is the shape `_require_class_teacher_scope()` was corrected
    on, and `ratings.rate()` after it. Here an `academics.move_student()`
    committing between the two reads would have a remark authorised against JSS
    1A's class teacher and its sheet state checked on JSS 1B's — so a remark
    could land in a term the guard would have refused.

    The race itself needs two connections; what is pinned here is the plumbing
    that removes it — that the write path honours the placement it is handed
    rather than looking one up.
    """

    def elsewhere(self):
        """Ada's placement, with JSS 3B's submitted sheet substituted for hers."""
        jss3b = ClassGroup.objects.get(pk=self.jss3b_id)
        other = services.open_sheet(jss3b, self.term(), self.principal)
        services.submit(other, self.sade)

        placement = academics.placement_of(self.membership_of(self.ada).pk, self.term())
        placement.class_group = jss3b
        return placement

    def test_the_sheet_checked_is_the_one_the_placement_names(self):
        with connected_to(self.stmarys):
            with self.assertRaises(comments.CommentsLocked) as refused:
                comments.write(
                    self.term(),
                    self.membership_of(self.ada),
                    TEACHER,
                    "A diligent term.",
                    placement=self.elsewhere(),
                )

        self.assertEqual(refused.exception.state, "submitted")

    def test_clearing_honours_the_placement_it_is_handed(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")

            with self.assertRaises(comments.CommentsLocked) as refused:
                comments.clear(
                    self.term(),
                    self.membership_of(self.ada),
                    TEACHER,
                    placement=self.elsewhere(),
                )

            self.assertEqual(refused.exception.state, "submitted")
            self.assertEqual(ReportCardComment.objects.count(), 1)

    def test_without_one_it_reads_the_placement_itself(self):
        """The primitive is still reachable from an import with no earlier read."""
        with connected_to(self.stmarys):
            self.assertEqual(
                comments.write(
                    self.term(),
                    self.membership_of(self.ada),
                    TEACHER,
                    "A diligent term.",
                ).body,
                "A diligent term.",
            )


class TheCardReadTakesNoJoinItDoesNotNeedTests(CommentsSetUp):
    """`sheet_for()` decides which source a card renders from, once per child.

    `ResultSheet.Meta.ordering` is `["term", "class_group"]` — two relations,
    each with a `Meta.ordering` of its own — and `.filter().first()` keeps it.
    So the spelling without `.order_by()` compiles to a three-table join sorted
    by the term's session and the class's level, per child, to find a row
    `one_result_sheet_per_class_term` guarantees is unique.

    Asserted on the SQL, so an ordering added later fails here first.
    `ratings.sheet_for()` shipped with exactly this and was corrected on it;
    `test_approval_concurrency.LockScopeTests` holds the same rule for the lock.

    **Selected on `FROM`, not on the table name appearing anywhere.** The card
    read asks a second question that reaches the sheet deliberately — the frozen
    rows are found through `sheet__term`, because `ReleasedComment` stores the
    sheet and the sheet carries the term — and that one joins because it has to.
    Matching the bare table name caught it too and read as a regression in a
    query this test has nothing to say about. What is asserted here is the
    *lookup*: the query that reads `results_resultsheet` as its own table is the
    one `sheet_for()` issues, and that one has no business joining anything.
    """

    def test_reading_a_card_does_not_join_the_term_and_the_class(self):
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")

            with CaptureQueriesContext(connection) as captured:
                self.lines()

        looked_up = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "results_resultsheet"' in query["sql"]
        ]
        self.assertTrue(looked_up, "the card never looked its sheet up")
        for sql in looked_up:
            self.assertNotIn("JOIN", sql, f"this read joins what it never uses:\n{sql}")


class ACardGoesHomeWholeNotRemarkByRemarkTests(CommentsSetUp):
    """Round two of the review, two findings, and they are one hole seen twice.

    `0010` closed the case where the *same* signatory's remark had been frozen:
    release JSS 1A with Ada's teacher's remark in it, move her to JSS 3B, and
    the rewrite is refused. What it left open was the signatory whose remark was
    **not** frozen. A card released carrying only the class teacher's remark
    freezes no principal's row, so a frozen-row check keyed on the author found
    nothing for the principal — and the placement check below it was looking at
    JSS 3B's untouched draft. The principal's remark landed on a card already in
    a parent's hand.

    **It is an inconsistency, not a policy question**, and that is what settles
    it without anyone having to rule on what a school ought to be allowed to do.
    Bisi stayed in JSS 1A and was refused that identical write the whole time,
    by the placement check, because for her the placement check still pointed at
    the released sheet. Two children, one card each, the same school, the same
    term, the same signatory, the same sentence — and the answer turned on
    whether the office had moved them. The fix makes the moved child agree with
    the one who stayed, and the pair of tests below is the assertion that would
    have caught it: they are the same scenario twice, differing only in the
    move.

    So the guard asks the child and the term, and asks neither who is writing
    nor where the child is sitting now.

    The read side is the same hole from the other end, and it compounded: with
    the write let through, re-printing Ada's card through JSS 3B rendered
    `[class teacher, principal]` while the copy in the parent's hand — and the
    same card printed through JSS 1A — said `[class teacher]`.
    """

    @contextlib.contextmanager
    def table_unguarded(self):
        """Write the way something that never calls the service would.

        The read fix defends against rows the write guard did not put there: an
        import, a management command, a `.update()`, or — until this branch —
        `write_as()` itself. Now that the trigger refuses all of those, that
        state is not reachable through Django at all, which is the trigger doing
        its job and also why observing the read fix needs it stood down for the
        one statement that sets the scene. The refusals are asserted with the
        trigger *on*, above; this only builds a card that has already diverged.
        """
        with connection.cursor() as cursor:
            # Django declares its foreign keys `DEFERRABLE INITIALLY DEFERRED`,
            # so the release above leaves constraint-trigger events queued on
            # this table and Postgres refuses to `ALTER` a table that has any.
            # Firing them early is what clears the queue; they are the checks
            # the transaction would have run at commit anyway.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "ALTER TABLE results_reportcardcomment "
                "DISABLE TRIGGER results_comments_stop_at_release"
            )
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(
                    "ALTER TABLE results_reportcardcomment "
                    "ENABLE TRIGGER results_comments_stop_at_release"
                )

    def released_carrying_only_the_teachers_remark(self):
        """JSS 1A goes home. Ada and Bisi each have a teacher's remark, no more.

        Both children, deliberately: the pair is what turns the finding from a
        judgement call into a contradiction.
        """
        self.write(self.kemi, TEACHER, "Written in JSS 1A.")
        self.write(self.kemi, TEACHER, "Also written in JSS 1A.", student=self.bisi)
        return self.walk_to_released()

    def move_ada_to_jss3b(self):
        academics.move_student(
            ClassGroup.objects.get(pk=self.jss3b_id),
            self.term(),
            self.membership_of(self.ada),
        )

    def signs_it_late(self, student):
        return comments.write_as(
            self.principal,
            self.term(),
            self.membership_of(student),
            PRINCIPAL,
            "Promoted to the next class.",
        )

    def principals_row(self, student):
        return ReportCardComment.objects.filter(
            term=self.term(),
            student_membership_id=self.membership_of(student).pk,
            author=PRINCIPAL.value,
        )

    # -- the write side ------------------------------------------------------

    def test_the_principal_may_not_sign_a_card_that_has_gone_home(self):
        """The finding. Nothing of the principal's was frozen, and it is still no."""
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            with self.assertRaises(comments.CommentsLocked) as refused:
                self.signs_it_late(self.ada)

            self.assertIn("released", str(refused.exception))
            self.assertFalse(
                self.principals_row(self.ada).exists(),
                "the refusal let the row through anyway",
            )

    def test_the_child_who_stayed_is_refused_the_identical_write(self):
        """The control, and the half that was passing before the fix.

        Its value is not that it passes — it is that it passes *for the same
        reason* now. Delete it and the test above is a rule somebody could read
        as a new restriction rather than as the removal of an exemption.
        """
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            with self.assertRaises(comments.CommentsLocked) as refused:
                self.signs_it_late(self.bisi)

            self.assertIn("released", str(refused.exception))
            self.assertFalse(self.principals_row(self.bisi).exists())

    def test_the_move_is_what_used_to_decide_it_and_now_decides_nothing(self):
        """Both children, one assertion: the answers agree.

        This is the finding written down as a test. It fails on the old guard at
        the first child and passes at the second.
        """
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            answers = {}
            for child, who in ((self.ada, "moved"), (self.bisi, "stayed")):
                try:
                    self.signs_it_late(child)
                except comments.CommentsLocked:
                    answers[who] = "refused"
                else:
                    answers[who] = "accepted"

            self.assertEqual(
                answers,
                {"moved": "refused", "stayed": "refused"},
                "a class move changed the answer to a question about a released card",
            )

    def test_clearing_it_after_the_move_is_refused_too(self):
        """`clear_as()` shares the guard, so it shares the fix."""
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            with self.assertRaises(comments.CommentsLocked):
                comments.clear_as(
                    self.principal, self.term(), self.membership_of(self.ada), PRINCIPAL
                )

            with self.assertRaises(comments.CommentsLocked):
                comments.clear_as(
                    self.sade, self.term(), self.membership_of(self.ada), TEACHER
                )

    def test_the_database_refuses_the_late_signature_too(self):
        """The trigger half. An import does not call the service, so the table asks.

        `0010`'s rewrite carries the same change: the first check dropped
        `rc.author = subject.author`, and both of its `IF FOUND`s became named
        booleans.
        """
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            with self.assertRaises(IntegrityError) as refused:
                with transaction.atomic():
                    ReportCardComment.objects.create(
                        term=self.term(),
                        student_membership_id=self.membership_of(self.ada).pk,
                        author=PRINCIPAL.value,
                        body="Written straight at the table.",
                    )

            self.assertIn("released", str(refused.exception))

    def test_the_frozen_card_is_untouched_by_the_attempt(self):
        """A refusal that still moved something is not a refusal."""
        with connected_to(self.stmarys):
            sheet = self.released_carrying_only_the_teachers_remark()
            before = sorted(
                ReleasedComment.objects.filter(sheet=sheet).values_list(
                    "student_membership_id", "author", "body"
                )
            )
            self.move_ada_to_jss3b()

            with self.assertRaises(comments.CommentsLocked):
                self.signs_it_late(self.ada)

            self.assertEqual(
                sorted(
                    ReleasedComment.objects.filter(sheet=sheet).values_list(
                        "student_membership_id", "author", "body"
                    )
                ),
                before,
            )

    # -- the read side -------------------------------------------------------

    def test_the_reprint_after_a_move_is_the_card_the_parent_holds(self):
        """Finding 3. The frozen rows decide, not the class the caller resolved.

        The live row is put there with the trigger stood down, because that is
        the state the write hole used to produce and the read has to be right
        about it independently — the two fixes are not one fix asserted twice.
        """
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            with self.table_unguarded():
                ReportCardComment.objects.create(
                    term=self.term(),
                    student_membership_id=self.membership_of(self.ada).pk,
                    author=PRINCIPAL.value,
                    body="Never went home.",
                )

            printed = comments.card_comments(
                self.membership_of(self.ada).pk,
                ClassGroup.objects.get(pk=self.jss3b_id),
                self.term(),
            )

            self.assertEqual(
                [(line.author, line.body) for line in printed],
                [(TEACHER.value, "Written in JSS 1A.")],
                "the reprint published a remark the parent's copy never carried",
            )

    def test_the_reprint_does_not_depend_on_which_class_it_is_asked_through(self):
        """JSS 1A and JSS 3B are the same card, because it is the same card."""
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            with self.table_unguarded():
                ReportCardComment.objects.create(
                    term=self.term(),
                    student_membership_id=self.membership_of(self.ada).pk,
                    author=PRINCIPAL.value,
                    body="Never went home.",
                )

            through = {
                name: [
                    (line.author, line.body)
                    for line in comments.card_comments(
                        self.membership_of(self.ada).pk,
                        ClassGroup.objects.get(pk=group_id),
                        self.term(),
                    )
                ]
                for name, group_id in (
                    ("JSS 1A", self.jss1a_id),
                    ("JSS 3B", self.jss3b_id),
                )
            }

            self.assertEqual(through["JSS 3B"], through["JSS 1A"])

    def test_the_moved_child_and_the_one_who_stayed_print_the_same_card(self):
        """The read-side twin of the write-side pair above."""
        with connected_to(self.stmarys):
            self.released_carrying_only_the_teachers_remark()
            self.move_ada_to_jss3b()

            moved = comments.card_comments(
                self.membership_of(self.ada).pk,
                ClassGroup.objects.get(pk=self.jss3b_id),
                self.term(),
            )
            stayed = comments.card_comments(
                self.membership_of(self.bisi).pk, self.jss1a(), self.term()
            )

            self.assertEqual(
                [line.author for line in moved], [line.author for line in stayed]
            )

    def test_a_child_with_nothing_frozen_still_reads_the_live_rows(self):
        """The over-fix control: not every card renders from the freeze.

        Without this, "read the frozen rows" could be implemented as "read the
        frozen rows and nothing else" and every draft card in the school would
        print blank with the suite still green.
        """
        with connected_to(self.stmarys):
            self.write(self.kemi, TEACHER, "A diligent term.")
            self.move_ada_to_jss3b()

            self.assertEqual(
                [
                    (line.author, line.body)
                    for line in comments.card_comments(
                        self.membership_of(self.ada).pk,
                        ClassGroup.objects.get(pk=self.jss3b_id),
                        self.term(),
                    )
                ],
                [(TEACHER.value, "A diligent term.")],
                "a draft card in the new class printed nothing",
            )

    def test_a_released_class_still_shuts_a_child_it_froze_nothing_for(self):
        """The check the frozen rows cannot replace, kept honest.

        Bisi's card carries no remark at all, so the release freezes no row for
        her and the first check finds nothing. The placement check is what
        refuses, and dropping it because the frozen rows "already cover it" is
        the mistake this asserts against.
        """
        with connected_to(self.stmarys):
            self.walk_to_released()

            with self.assertRaises(comments.CommentsLocked):
                comments.write_as(
                    self.kemi,
                    self.term(),
                    self.membership_of(self.bisi),
                    TEACHER,
                    "Written after the card went home.",
                )
