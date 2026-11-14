"""A register is locked with the results it feeds: audit finding G-10.

Before this, `PUT /api/attendance/classes/{class}/terms/{term}/{date}/` and its
`DELETE` checked the caller and the date and nothing else, so a register could
be taken, amended or discarded for any term at any time: between approval and
release (changing what goes on a card after the principal approved it) and for
ever after release (leaving a register that no longer supports the card).

The rule now is the one marks, ratings and remarks keep
(`results.services.is_open_for_writing()`): open while the class's sheet for
the term is unopened or in draft; refused once it is submitted, checked or
approved, until it is **sent back**; refused for good once released.

St Mary's JSS 1A and JSS 1B, and Grace Academy with a JSS 1A of its own, whose
class and term ids may coincide with St Mary's.
"""

from datetime import date

from attendance import services, summary
from attendance.models import AttendanceMark, Register
from attendance.tests.fixtures import A_SCHOOL_DAY
from results import services as chain
from results import unmarked
from results.models import ReleasedCard, SheetState
from results.tests.fixtures import HOST, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

OTHER_DAY = date(2025, 9, 18)


class LockSetUp(ChainSetUp):
    def url(self, class_id=None, term_id=None, on=A_SCHOOL_DAY):
        return f"/api/attendance/classes/{class_id or self.jss1a_id}/terms/{term_id or self.term_id}/{on}/"

    def take(self, absent=(), on=A_SCHOOL_DAY, class_id=None, who=None, host=HOST, term_id=None):
        self.client.force_login((who or self.teacher).user)
        return self.client.put(
            self.url(class_id, term_id, on),
            data={"absent_ids": list(absent)},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def discard(self, on=A_SCHOOL_DAY, class_id=None, who=None, host=HOST):
        self.client.force_login((who or self.teacher).user)
        return self.client.delete(
            f"/api/attendance/classes/{class_id or self.jss1a_id}/{on}/", HTTP_HOST=host
        )

    def walk(self, to, school=None):
        """Move JSS 1A's sheet (or Grace's) along the chain as far as `to`."""
        school = school or self.stmarys
        ours = school == self.stmarys
        group, term_id = (self.jss1a, self.term_id) if ours else (self.grace_group, self.grace_term_id)
        teacher, vp, head = (
            (self.teacher, self.vp, self.head) if ours else (self.grace_teacher, self.their_vp, self.their_head)
        )
        with connected_to(school):
            from academics.models import Term

            sheet = chain.open_sheet(group, Term.objects.get(pk=term_id), head.user)
            count = unmarked.count(sheet.class_group, sheet.term)
            steps = [
                (SheetState.SUBMITTED, lambda: chain.submit(sheet, teacher.user, unmarked=count)),
                (SheetState.CHECKED, lambda: chain.check(sheet, vp.user, unmarked=count)),
                (SheetState.APPROVED, lambda: chain.approve(sheet, head.user, unmarked=count)),
                (SheetState.RELEASED, lambda: chain.release(sheet, head.user)),
            ]
            for state, step in steps:
                step()
                if state == to:
                    break
            return sheet

    def marks(self, school=None):
        with connected_to(school or self.stmarys):
            return sorted(
                AttendanceMark.objects.values_list(
                    "register__class_group_id", "register__taken_on", "student_membership_id", "status"
                )
            )


class OpenUntilSubmittedTests(LockSetUp):
    def test_a_register_is_taken_amended_and_discarded_while_nothing_is_submitted(self):
        self.assertEqual(self.take([self.children["tunde"].pk]).status_code, 200)
        self.assertEqual(self.take([]).status_code, 200)
        self.assertEqual(self.discard().status_code, 204)

    def test_a_draft_sheet_leaves_it_open(self):
        with connected_to(self.stmarys):
            chain.open_sheet(self.jss1a, self.term, self.head.user)

        self.assertEqual(self.take([self.children["tunde"].pk]).status_code, 200)


class LockedInTheChainTests(LockSetUp):
    def test_submitted_checked_and_approved_each_refuse_a_new_register_an_amendment_and_a_discard(self):
        self.assertEqual(self.take([self.children["tunde"].pk]).status_code, 200)
        before = self.marks()
        with connected_to(self.stmarys):
            sheet = chain.open_sheet(self.jss1a, self.term, self.head.user)
            count = unmarked.count(sheet.class_group, sheet.term)
        steps = (
            ("submitted", lambda: chain.submit(sheet, self.teacher.user, unmarked=count)),
            ("checked", lambda: chain.check(sheet, self.vp.user, unmarked=count)),
            ("approved", lambda: chain.approve(sheet, self.head.user, unmarked=count)),
        )
        for state, step in steps:
            with connected_to(self.stmarys):
                step()
            with self.subTest(state=state):
                for response in (
                    self.take([], on=OTHER_DAY),
                    self.take([self.children["ada"].pk]),
                    self.discard(),
                    # Whoever asks: the principal and the office are refused too.
                    self.take([self.children["ada"].pk], who=self.head),
                ):
                    self.assertEqual(response.status_code, 409, response.content)
                    self.assertIn("Send the results back first", response.json()["detail"])
                self.assertEqual(self.marks(), before)

    def test_sent_back_it_is_open_again(self):
        self.take([self.children["tunde"].pk])
        sheet = self.walk(SheetState.CHECKED)
        self.assertEqual(self.take([]).status_code, 409)

        with connected_to(self.stmarys):
            chain.send_back(sheet, self.head.user, reason="Tunde was in school on the 17th")

        self.assertEqual(self.take([]).status_code, 200)
        self.assertEqual(self.take([], on=OTHER_DAY).status_code, 200)
        self.assertEqual(self.discard(on=OTHER_DAY).status_code, 204)

    def test_the_service_refuses_without_the_route(self):
        self.take([self.children["tunde"].pk])
        self.walk(SheetState.APPROVED)

        with connected_to(self.stmarys):
            with self.assertRaises(services.RegisterLocked) as taken:
                services.take_register(self.jss1a, self.term, on=A_SCHOOL_DAY, absent_ids=[])
            self.assertEqual(taken.exception.state, SheetState.APPROVED)
            with self.assertRaises(services.RegisterLocked):
                services.discard_register(self.jss1a, A_SCHOOL_DAY)
            self.assertTrue(Register.objects.filter(class_group=self.jss1a).exists())

    def test_what_was_approved_is_what_is_released(self):
        """The audit's second bullet: a register changed between approval and
        release used to change the card after the principal approved it."""
        self.take([self.children["tunde"].pk])
        sheet = self.walk(SheetState.APPROVED)

        self.assertEqual(self.take([]).status_code, 409)
        with connected_to(self.stmarys):
            chain.release(sheet, self.head.user)
            card = ReleasedCard.objects.get(student_membership_id=self.children["tunde"].pk)
        self.assertEqual((card.days_present, card.days_absent), (0, 1))


class LockedForGoodAfterReleaseTests(LockSetUp):
    def test_after_release_the_register_cannot_be_changed_or_discarded(self):
        """The audit's reproduction: release a class, then mark a child absent."""
        self.take([])
        self.walk(SheetState.RELEASED)
        before = self.marks()

        for response in (
            self.take([self.children["ada"].pk]),
            self.take([], on=OTHER_DAY),
            self.discard(),
            self.take([self.children["ada"].pk], who=self.head),
        ):
            self.assertEqual(response.status_code, 409, response.content)
            self.assertIn("released to parents", response.json()["detail"])
            self.assertNotIn("Send the results back", response.json()["detail"])
        self.assertEqual(self.marks(), before)
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.children["ada"].pk)
            now = summary.for_term(self.term, [self.children["ada"].pk])[self.children["ada"].pk]
        # The register still supports the card it issued.
        self.assertEqual((card.days_present, card.days_absent), (now.present, now.absent))

    def test_another_class_and_another_term_are_not_locked_by_it(self):
        self.walk(SheetState.RELEASED)

        # JSS 1B's sheet is its own, and the second term's is not yet opened.
        self.assertEqual(self.take([], class_id=self.jss1b_id).status_code, 200)
        self.assertEqual(
            self.take([], on=date(2026, 1, 14), term_id=self.second_term.pk).status_code, 409
        )  # nobody is placed in JSS 1A for the second term: the existing refusal
        with connected_to(self.stmarys):
            from academics import services as academics

            academics.place_student(self.jss1a, self.second_term, self.children["ada"])
        self.assertEqual(
            self.take([], on=date(2026, 1, 14), term_id=self.second_term.pk).status_code, 200
        )


class TwoSchoolsTests(LockSetUp):
    def test_one_schools_release_locks_nothing_at_the_other(self):
        self.walk(SheetState.RELEASED)

        response = self.take([], class_id=self.grace_group_id, term_id=self.grace_term_id,
                             who=self.grace_teacher, host=THEIR_HOST)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(self.marks(self.grace)), 1)

    def test_and_the_other_way_round(self):
        self.walk(SheetState.SUBMITTED, school=self.grace)

        self.assertEqual(self.take([]).status_code, 200)
        response = self.take([], class_id=self.grace_group_id, term_id=self.grace_term_id,
                             who=self.grace_teacher, host=THEIR_HOST)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.marks(self.grace), [])
