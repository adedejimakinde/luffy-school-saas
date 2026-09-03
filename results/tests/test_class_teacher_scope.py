"""Submission is scoped to the class teacher of *that* group, not to teachers.

The hole this closes was live in the chain as merged (issue #25).
`_require_authority()` asks `roles_at(school)`, which is school-wide, and nothing
bound the actor to the `class_group` on the sheet — so any teacher could submit
any class group's results, and the transition row would record them as the
submitting signatory of a class they do not teach.

Two schools throughout, as everywhere in this project. "Is this person the class
teacher of this group" is a question with a schema in it: the assignment lives in
the tenant schema and the membership lives in the shared one, so a check that
compared the wrong pair would answer correctly at one school and wrongly at two.

The sections:

- the class teacher of the group may submit it;
- another class's teacher may not, though their role is identical;
- a group with nobody assigned refuses every teacher, and says why;
- an administrator is unaffected, which is a decision and not an oversight;
- the other school's teacher is not this school's class teacher, even holding
  the same membership id.
"""

import contextlib
from datetime import date

from django.db import connection
from django.test import TestCase
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, ClassTeacher, Term, TermName
from accounts.models import MembershipStatus, Role, User
from accounts.services import grant_membership
from results import services
from results.models import ResultSheet, ResultSheetTransition, SheetState
from schools.tests.tenants import make_school

PASSWORD = "correct-horse-battery"


@contextlib.contextmanager
def connected_to(school):
    with schema_context(school.schema_name):
        yield


class ClassTeacherSetUp(TestCase):
    """Two schools, each with two class groups and two teachers."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.kemi = self._staff("kemi", "Kemi Bello", self.stmarys, Role.TEACHER)
        self.sade = self._staff("sade", "Sade Johnson", self.stmarys, Role.TEACHER)
        self.registrar = self._staff("bola", "Bola Ade", self.stmarys, Role.ADMIN)
        self.principal = self._staff(
            "tunde", "Tunde Alabi", self.stmarys, Role.PRINCIPAL
        )
        self.their_teacher = self._staff(
            "chika", "Chika Obi", self.grace, Role.TEACHER
        )

        self.term_id, self.jss1a_id, self.jss3b_id = self._academics(self.stmarys)
        (
            self.their_term_id,
            self.their_jss1a_id,
            self.their_jss3b_id,
        ) = self._academics(self.grace)

        # Kemi teaches JSS 1A. Sade teaches JSS 3B. Both are TEACHERs here.
        self.assign(self.stmarys, self.kemi, self.jss1a_id, self.term_id)
        self.assign(self.stmarys, self.sade, self.jss3b_id, self.term_id)
        self.assign(
            self.grace, self.their_teacher, self.their_jss1a_id, self.their_term_id
        )

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

    def _staff(self, username, full_name, school, role):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, school, role)
        return user

    def assign(self, school, user, class_group_id, term_id):
        membership = user.memberships.get(school=school, role=Role.TEACHER)
        with connected_to(school):
            return academics.assign_class_teacher(
                ClassGroup.objects.get(pk=class_group_id),
                Term.objects.get(pk=term_id),
                membership,
            )

    def sheet_for(self, school, class_group_id, term_id, actor):
        with connected_to(school):
            return services.open_sheet(
                ClassGroup.objects.get(pk=class_group_id),
                Term.objects.get(pk=term_id),
                actor,
            )

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()


class OnlyTheClassTeacherSubmitsTests(ClassTeacherSetUp):
    def test_the_class_teacher_of_the_group_may_submit_it(self):
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.kemi)

        with connected_to(self.stmarys):
            services.submit(sheet, self.kemi)
            self.assertEqual(
                ResultSheet.objects.get(pk=sheet.pk).state, SheetState.SUBMITTED
            )

    def test_another_class_teacher_may_not_submit_this_group(self):
        """Sade is a teacher here, and of a different group.

        This is the hole. Her role is identical to Kemi's and the old check saw
        nothing else, so she could submit JSS 1A and be recorded as its
        signatory.
        """
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.kemi)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(sheet, self.sade)

            self.assertIn("not the class teacher", str(refused.exception))
            self.assertEqual(
                ResultSheet.objects.get(pk=sheet.pk).state,
                SheetState.DRAFT,
                "the refusal has to leave the sheet where it was",
            )

    def test_the_refusal_writes_no_transition_row(self):
        """A refused step is not a step. The audit log must not carry it."""
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.kemi)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults):
                services.submit(sheet, self.sade)

            self.assertEqual(
                ResultSheetTransition.objects.filter(sheet=sheet).count(), 0
            )

    def test_a_group_with_no_class_teacher_refuses_and_says_so(self):
        """Not "wrong state" and not a silent pass — a configuration problem.

        JSS 3B has Sade. Take her off it and nobody is answerable for the group,
        so nobody may submit it. The message has to name that, because a teacher
        reading "you are not the class teacher" about a group with no class
        teacher would go looking for the person who is.
        """
        with connected_to(self.stmarys):
            academics.unassign_class_teacher(
                ClassGroup.objects.get(pk=self.jss3b_id),
                Term.objects.get(pk=self.term_id),
            )

        sheet = self.sheet_for(self.stmarys, self.jss3b_id, self.term_id, self.sade)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(sheet, self.sade)

        self.assertIn("has no class teacher", str(refused.exception))

    def test_an_administrator_is_unaffected(self):
        """The office path, kept deliberately.

        `SUBMITTING_ROLES` admits ADMIN because entering and submitting a paper
        sheet is office work in most schools. An administrator is not a teacher
        of anything, so "which class are they the class teacher of" is not a
        question about them. Narrowing that is a separate decision; this test
        exists so it cannot happen by accident.
        """
        sheet = self.sheet_for(self.stmarys, self.jss3b_id, self.term_id, self.registrar)

        with connected_to(self.stmarys):
            services.submit(sheet, self.registrar)
            self.assertEqual(
                ResultSheet.objects.get(pk=sheet.pk).state, SheetState.SUBMITTED
            )


class TheScopeIsPerTermTests(ClassTeacherSetUp):
    """The assignment is per (group, term), like `ClassPlacement`."""

    def test_last_terms_class_teacher_cannot_submit_this_term(self):
        """People change class in January, and the check has to notice.

        Kemi has JSS 1A for the first term. The second term is a different row
        and nobody has been assigned to it, so her authority does not follow her
        into it.
        """
        with connected_to(self.stmarys):
            second = Term.objects.create(
                session="2025/2026",
                name=TermName.SECOND,
                starts_on=date(2026, 1, 12),
                ends_on=date(2026, 4, 3),
            )
            second_id = second.pk

        sheet = self.sheet_for(self.stmarys, self.jss1a_id, second_id, self.kemi)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(sheet, self.kemi)

        self.assertIn("has no class teacher", str(refused.exception))

    def test_reassignment_replaces_rather_than_accumulating(self):
        """One class teacher at a time, by constraint.

        Two rows would make "who is the class teacher" ambiguous the first time
        anybody was replaced, and `is_class_teacher()` would answer yes for both.
        """
        self.assign(self.stmarys, self.sade, self.jss1a_id, self.term_id)

        with connected_to(self.stmarys):
            rows = ClassTeacher.objects.for_class(
                ClassGroup.objects.get(pk=self.jss1a_id),
                Term.objects.get(pk=self.term_id),
            )
            self.assertEqual(rows.count(), 1)

        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.sade)
        with connected_to(self.stmarys):
            services.submit(sheet, self.sade)
            self.assertEqual(
                ResultSheet.objects.get(pk=sheet.pk).state, SheetState.SUBMITTED
            )

    def test_the_replaced_teacher_can_no_longer_submit(self):
        self.assign(self.stmarys, self.sade, self.jss1a_id, self.term_id)
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.sade)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults):
                services.submit(sheet, self.kemi)


class TheOtherSchoolsTeacherIsNotOursTests(ClassTeacherSetUp):
    """Two tenants, because this check spans both schemas.

    The assignment row is tenant-local and the membership it names is in the
    shared schema. A check that compared a membership id against another
    school's assignment table — or that trusted the id without asking which
    school it belongs to — would pass at one school and leak at two.
    """

    def test_grace_academys_teacher_may_not_submit_st_marys_results(self):
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.kemi)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(sheet, self.their_teacher)

        # Refused for having no role *here* at all, before class teaching is
        # even reached — the outer guard, which this test pins is still there.
        self.assertIn("may not submit results", str(refused.exception))

    def test_assigning_another_schools_teacher_is_refused(self):
        """The write-time guard, which is what the read-time one leans on."""
        their_membership = self.their_teacher.memberships.get(
            school=self.grace, role=Role.TEACHER
        )

        with connected_to(self.stmarys):
            with self.assertRaises(academics.NotThisSchoolsTeacher) as refused:
                academics.assign_class_teacher(
                    ClassGroup.objects.get(pk=self.jss1a_id),
                    Term.objects.get(pk=self.term_id),
                    their_membership,
                )

        self.assertIn("Grace Academy", str(refused.exception))

    def test_a_non_teacher_membership_is_refused(self):
        """A class-teacher assignment naming a bursar is not a near miss."""
        membership = self.principal.memberships.get(
            school=self.stmarys, role=Role.PRINCIPAL
        )

        with connected_to(self.stmarys):
            with self.assertRaises(academics.NotThisSchoolsTeacher) as refused:
                academics.assign_class_teacher(
                    ClassGroup.objects.get(pk=self.jss1a_id),
                    Term.objects.get(pk=self.term_id),
                    membership,
                )

        self.assertIn("not a teacher membership", str(refused.exception))

    def test_each_school_reads_its_own_assignment(self):
        """The same group name in both schools, answering differently."""
        with connected_to(self.stmarys):
            ours = academics.class_teacher_of(
                ClassGroup.objects.get(pk=self.jss1a_id),
                Term.objects.get(pk=self.term_id),
            )
        with connected_to(self.grace):
            theirs = academics.class_teacher_of(
                ClassGroup.objects.get(pk=self.their_jss1a_id),
                Term.objects.get(pk=self.their_term_id),
            )

        kemi_membership = self.kemi.memberships.get(
            school=self.stmarys, role=Role.TEACHER
        )
        their_membership = self.their_teacher.memberships.get(
            school=self.grace, role=Role.TEACHER
        )

        self.assertEqual(ours.teacher_membership_id, kemi_membership.pk)
        self.assertEqual(theirs.teacher_membership_id, their_membership.pk)
        self.assertNotEqual(ours.teacher_membership_id, theirs.teacher_membership_id)


class WhoMayAssignTests(ClassTeacherSetUp):
    """Assigning is an office act, like placing a child in a group."""

    def test_a_principal_may_assign(self):
        membership = self.sade.memberships.get(
            school=self.stmarys, role=Role.TEACHER
        )
        with connected_to(self.stmarys):
            row = academics.assign_class_teacher_as(
                self.principal,
                ClassGroup.objects.get(pk=self.jss1a_id),
                Term.objects.get(pk=self.term_id),
                membership,
            )
        self.assertEqual(row.teacher_membership_id, membership.pk)
        self.assertEqual(row.assigned_by_id, self.principal.pk)

    def test_a_teacher_may_not_assign_themselves(self):
        """The act this table exists to scope must not be self-granted.

        A teacher who could assign themselves to a class group could grant
        themselves the authority to submit its results, which would give back
        exactly what issue #25 took away.
        """
        membership = self.kemi.memberships.get(
            school=self.stmarys, role=Role.TEACHER
        )
        with connected_to(self.stmarys):
            with self.assertRaises(academics.NotAllowedToAssignClassTeachers):
                academics.assign_class_teacher_as(
                    self.kemi,
                    ClassGroup.objects.get(pk=self.jss3b_id),
                    Term.objects.get(pk=self.term_id),
                    membership,
                )


class TheScopeIsCheckedOnTheLockedRowTests(ClassTeacherSetUp):
    """The scope check has to read the row, not the instance handed in.

    `_move()`'s contract is that every decision is taken on the copy re-read
    under `select_for_update()` — the module docstring says so in as many words,
    and `_locked()`'s says why. `_require_class_teacher_scope()` was the one
    check that did not: it read `class_group` and `term` off the caller's
    instance, while the row it authorised a write to was fetched by `pk` alone.

    An instance whose `class_group` disagrees with the row is not exotic. A
    deserialised one, a cached one, or a row whose `class_group` was corrected
    by a bulk `.update()` — nothing guards that column, only `state` has a
    trigger — all produce one. The result is the audit failure issue #25 exists
    to close, reached through the single input the check trusted: Kemi is
    authorised against JSS 1A and JSS 3B is submitted with her name on it.
    """

    def test_a_mismatched_instance_cannot_borrow_another_groups_authority(self):
        jss3b_sheet = self.sheet_for(
            self.stmarys, self.jss3b_id, self.term_id, self.sade
        )

        with connected_to(self.stmarys):
            # Kemi's own group, on an instance pointing at Sade's sheet.
            pretending = ResultSheet(
                pk=jss3b_sheet.pk,
                class_group=ClassGroup.objects.get(pk=self.jss1a_id),
                term=Term.objects.get(pk=self.term_id),
                state=SheetState.DRAFT,
            )

            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(pretending, self.kemi)

            self.assertIn("not the class teacher", str(refused.exception))
            self.assertEqual(
                ResultSheet.objects.get(pk=jss3b_sheet.pk).state,
                SheetState.DRAFT,
                "JSS 3B is Sade's, and stays where it was",
            )
            self.assertEqual(
                ResultSheetTransition.objects.filter(sheet_id=jss3b_sheet.pk).count(),
                0,
                "a refused step leaves no signature behind",
            )


class AStaleAssignmentSaysSoTests(ClassTeacherSetUp):
    """An assignment can outlive the access it was made against.

    `assign_class_teacher()` does not refuse a membership without access, and
    that is deliberate — `place_student()` gives the reasoning about ended
    memberships, and backfilling a past term's register is the case it protects.
    The consequence is that a group's class teacher can be suspended or can
    leave while the row still names them, and then **no teacher can submit that
    group at all**: not the assigned one, who has no TEACHER role left, and not
    anybody else, who is not the class teacher.

    That much is correct. What was wrong was the sentence: every colleague was
    told "you are not the class teacher of JSS 1A", which is true, unhelpful,
    and sends them looking for somebody who cannot act either.
    """

    def suspend(self, user):
        membership = user.memberships.get(school=self.stmarys, role=Role.TEACHER)
        membership.status = MembershipStatus.SUSPENDED
        membership.save(update_fields=["status"])

    def test_a_colleague_is_told_the_class_teacher_cannot_act(self):
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.kemi)
        self.suspend(self.kemi)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(sheet, self.sade)

        message = str(refused.exception)
        self.assertIn("cannot currently act", message)
        self.assertIn("Kemi Bello", message)
        self.assertNotIn(
            "not the class teacher",
            message,
            "the unhelpful sentence is the one this test exists to keep out",
        )

    def test_the_suspended_class_teacher_is_refused_on_her_role(self):
        """She loses the role before she loses the assignment.

        `roles_at()` is access-scoped, so a suspended teacher holds no TEACHER
        role and never reaches the class-teacher check at all.
        """
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.kemi)
        self.suspend(self.kemi)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(sheet, self.kemi)

        self.assertIn("may not submit results", str(refused.exception))

    def test_an_ordinary_wrong_group_still_gets_the_ordinary_refusal(self):
        """The control: with the class teacher present, the message is the plain one."""
        sheet = self.sheet_for(self.stmarys, self.jss1a_id, self.term_id, self.kemi)

        with connected_to(self.stmarys):
            with self.assertRaises(services.NotAllowedToActOnResults) as refused:
                services.submit(sheet, self.sade)

        self.assertIn("not the class teacher", str(refused.exception))
        self.assertNotIn("cannot currently act", str(refused.exception))


class WhoMayUnassignTests(ClassTeacherSetUp):
    """Taking the class teacher off a group is an office act, like putting one on.

    It is not the harmless half of the pair. A group with nobody assigned cannot
    be submitted by anyone, so an unchecked `unassign_class_teacher()` would let
    a teacher stop a class they do not teach from being submitted at all.
    """

    def test_a_teacher_may_not_unassign(self):
        with connected_to(self.stmarys):
            with self.assertRaises(academics.NotAllowedToAssignClassTeachers):
                academics.unassign_class_teacher_as(
                    self.sade,
                    self.stmarys,
                    ClassGroup.objects.get(pk=self.jss1a_id),
                    Term.objects.get(pk=self.term_id),
                )

            self.assertTrue(
                ClassTeacher.objects.filter(
                    class_group_id=self.jss1a_id, term_id=self.term_id
                ).exists(),
                "the refusal has to leave the assignment standing",
            )

    def test_a_principal_may_unassign(self):
        with connected_to(self.stmarys):
            removed = academics.unassign_class_teacher_as(
                self.principal,
                self.stmarys,
                ClassGroup.objects.get(pk=self.jss1a_id),
                Term.objects.get(pk=self.term_id),
            )

        self.assertTrue(removed)
        with connected_to(self.stmarys):
            self.assertFalse(
                ClassTeacher.objects.filter(
                    class_group_id=self.jss1a_id, term_id=self.term_id
                ).exists()
            )

    def test_the_other_schools_principal_may_not_unassign_ours(self):
        """Authority is asked at the school passed in, and theirs is not ours."""
        their_principal = self._staff(
            "ngozi", "Ngozi Eze", self.grace, Role.PRINCIPAL
        )

        with connected_to(self.stmarys):
            with self.assertRaises(academics.NotAllowedToAssignClassTeachers):
                academics.unassign_class_teacher_as(
                    their_principal,
                    self.stmarys,
                    ClassGroup.objects.get(pk=self.jss1a_id),
                    Term.objects.get(pk=self.term_id),
                )
