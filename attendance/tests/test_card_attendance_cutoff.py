"""The card's attendance is counted to a cut-off and frozen at release; the
register is never locked. Audit finding G-10, as decided.

The finding was that a register could be changed for any term at any time,
including after the cards went home, so the register and the card could part.
The decision: teachers can always correct a register. What a card prints is
the school days counted to the term's attendance cut-off (set by the school;
blank is the term's last day), read once at release and frozen on the card.
A register corrected afterwards changes the register, not a card that has gone
home.

St Mary's JSS 1A and JSS 1B, first term 15 September to 12 December 2025;
Grace Academy has its own term and class, whose ids may coincide with St
Mary's.
"""

from datetime import date

from academics import services as academics
from academics.models import Term
from attendance import services, summary
from attendance.models import AttendanceMark
from results import revision
from results import services as chain
from results import unmarked
from results.models import ReleasedCard, SheetState
from results.tests.fixtures import HOST, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

MONDAY, TUESDAY, WEDNESDAY = date(2025, 9, 15), date(2025, 9, 16), date(2025, 9, 17)
EXAM_WEEK = date(2025, 12, 8)


class CutoffSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        self.tunde = self.children["tunde"]

    # -- registers, over the route ---------------------------------------------

    def take(self, on, absent=(), class_id=None, who=None, host=HOST, term_id=None):
        self.client.force_login((who or self.teacher).user)
        return self.client.put(
            f"/api/attendance/classes/{class_id or self.jss1a_id}/terms/{term_id or self.term_id}/{on}/",
            data={"absent_ids": list(absent)},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def discard(self, on, who=None):
        self.client.force_login((who or self.teacher).user)
        return self.client.delete(f"/api/attendance/classes/{self.jss1a_id}/{on}/", HTTP_HOST=HOST)

    # -- the cut-off, over the route -------------------------------------------

    def set_cutoff(self, day, who=None, host=HOST, term_id=None):
        self.client.force_login((who or self.head).user)
        return self.client.put(
            f"/api/academics/terms/{term_id or self.term_id}/attendance-cutoff/",
            data={"attendance_cutoff": day.isoformat() if day else None},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def cutoff(self, school=None, term_id=None):
        with connected_to(school or self.stmarys):
            return Term.objects.get(pk=term_id or self.term_id).attendance_cutoff

    # -- the chain ---------------------------------------------------------------

    def walk(self, to):
        with connected_to(self.stmarys):
            sheet = chain.open_sheet(self.jss1a, self.term, self.head.user)
            count = unmarked.count(sheet.class_group, sheet.term)
            for state, step in (
                (SheetState.SUBMITTED, lambda: chain.submit(sheet, self.teacher.user, unmarked=count)),
                (SheetState.CHECKED, lambda: chain.check(sheet, self.vp.user, unmarked=count)),
                (SheetState.APPROVED, lambda: chain.approve(sheet, self.head.user, unmarked=count)),
                (SheetState.RELEASED, lambda: chain.release(sheet, self.head.user)),
            ):
                step()
                if state == to:
                    return sheet
        return sheet

    def card(self, child=None):
        with connected_to(self.stmarys):
            return (
                ReleasedCard.objects.filter(student_membership_id=(child or self.tunde).pk, term_id=self.term_id)
                .order_by("-version")
                .first()
            )

    def figures(self, child=None):
        card = self.card(child)
        return card.days_present, card.days_absent


class ARegisterCanAlwaysBeCorrectedTests(CutoffSetUp):
    def test_in_the_chain_and_after_release_a_register_is_taken_amended_and_discarded(self):
        self.assertEqual(self.take(MONDAY, [self.tunde.pk]).status_code, 200)
        sheet = None
        for state in (SheetState.SUBMITTED, SheetState.CHECKED, SheetState.APPROVED, SheetState.RELEASED):
            with connected_to(self.stmarys):
                if sheet is None:
                    sheet = chain.open_sheet(self.jss1a, self.term, self.head.user)
                count = unmarked.count(sheet.class_group, sheet.term)
                {
                    SheetState.SUBMITTED: lambda: chain.submit(sheet, self.teacher.user, unmarked=count),
                    SheetState.CHECKED: lambda: chain.check(sheet, self.vp.user, unmarked=count),
                    SheetState.APPROVED: lambda: chain.approve(sheet, self.head.user, unmarked=count),
                    SheetState.RELEASED: lambda: chain.release(sheet, self.head.user),
                }[state]()
            with self.subTest(state=state):
                self.assertEqual(self.take(MONDAY, []).status_code, 200)
                self.assertEqual(self.take(TUESDAY, [self.tunde.pk]).status_code, 200)
                self.assertEqual(self.discard(TUESDAY).status_code, 204)
        with connected_to(self.stmarys):
            self.assertEqual(
                services.marks_in(services.register_for(self.jss1a, MONDAY))[self.tunde.pk], "present"
            )

    def test_a_register_corrected_after_release_does_not_move_the_card(self):
        self.take(MONDAY, [self.tunde.pk])
        self.take(TUESDAY)
        self.walk(SheetState.RELEASED)
        frozen = self.figures()

        self.take(MONDAY, [])
        self.take(WEDNESDAY, [self.tunde.pk])

        self.assertEqual(frozen, (1, 1))
        self.assertEqual(self.figures(), frozen)
        with connected_to(self.stmarys):
            now = summary.for_the_card(self.term, [self.tunde.pk])[self.tunde.pk]
        # The register moved; the card did not.
        self.assertEqual((now.present, now.absent), (2, 1))

    def test_a_revision_after_a_correction_keeps_the_figures_that_went_home(self):
        self.take(MONDAY, [self.tunde.pk])
        self.walk(SheetState.RELEASED)
        self.take(MONDAY, [])

        with connected_to(self.stmarys):
            revision.revise(self.tunde, self.term, self.head.user, "Name corrected")

        self.assertEqual(self.card().version, 2)
        self.assertEqual(self.figures(), (0, 1))


class TheCardCountsToTheCutoffTests(CutoffSetUp):
    def test_with_no_cutoff_the_card_counts_to_the_terms_last_day(self):
        self.take(MONDAY)
        self.take(EXAM_WEEK, [self.tunde.pk])
        self.walk(SheetState.RELEASED)

        self.assertIsNone(self.cutoff())
        self.assertEqual(self.figures(), (1, 1))

    def test_a_register_after_the_cutoff_is_not_on_the_card(self):
        self.assertEqual(self.set_cutoff(date(2025, 12, 5)).status_code, 200)
        self.take(MONDAY)
        self.take(EXAM_WEEK, [self.tunde.pk])

        self.walk(SheetState.RELEASED)

        self.assertEqual(self.figures(), (1, 0))
        # Taken, and kept: the register is not lost, only not on the card.
        with connected_to(self.stmarys):
            self.assertTrue(
                AttendanceMark.objects.filter(register__taken_on=EXAM_WEEK, student_membership_id=self.tunde.pk).exists()
            )
            whole = summary.for_term(self.term, [self.tunde.pk])[self.tunde.pk]
        self.assertEqual((whole.present, whole.absent), (1, 1))

    def test_the_cutoff_day_itself_is_counted(self):
        self.set_cutoff(TUESDAY)
        self.take(MONDAY)
        self.take(TUESDAY, [self.tunde.pk])
        self.take(WEDNESDAY, [self.tunde.pk])

        self.walk(SheetState.RELEASED)

        self.assertEqual(self.figures(), (1, 1))

    def test_a_child_who_changed_class_is_counted_once_to_the_cutoff(self):
        self.set_cutoff(TUESDAY)
        self.take(MONDAY)
        with connected_to(self.stmarys):
            academics.move_student(self.jss1b, self.term, self.tunde)
        # JSS 1B fills in Monday too; then marks Tuesday and Wednesday.
        for day in (MONDAY, TUESDAY, WEDNESDAY):
            self.assertEqual(self.take(day, class_id=self.jss1b_id).status_code, 200)

        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)  # as it is now, with its cut-off
            found = summary.for_the_card(term, [self.tunde.pk])[self.tunde.pk]

        self.assertEqual((found.present, found.absent), (2, 0))

    def test_the_route_answers_with_the_day_counted_to(self):
        body = self.set_cutoff(date(2025, 12, 5)).json()
        self.assertEqual((body["attendance_cutoff"], body["attendance_through"]), ("2025-12-05", "2025-12-05"))

        cleared = self.set_cutoff(None).json()
        self.assertEqual((cleared["attendance_cutoff"], cleared["attendance_through"]), (None, "2025-12-12"))
        self.client.force_login(self.head.user)
        terms = self.client.get("/api/academics/setup/", HTTP_HOST=HOST).json()["terms"]
        mine = next(t for t in terms if t["term_id"] == self.term_id)
        self.assertEqual((mine["attendance_cutoff"], mine["attendance_through"]), (None, "2025-12-12"))


class SettingTheCutoffTests(CutoffSetUp):
    def test_a_day_outside_the_term_is_refused_in_a_sentence(self):
        for day in (date(2025, 9, 14), date(2025, 12, 13)):
            with self.subTest(day=day):
                response = self.set_cutoff(day)
                self.assertEqual(response.status_code, 422)
                self.assertIn("has to be a day of the term", response.json()["detail"])
        self.assertIsNone(self.cutoff())

    def test_the_database_refuses_it_too(self):
        from django.db import IntegrityError, transaction

        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError) as refused, transaction.atomic():
                Term.objects.filter(pk=self.term_id).update(attendance_cutoff=date(2026, 1, 5))
        self.assertIn("the_attendance_cutoff_is_a_day_of_the_term", str(refused.exception))

    def test_only_the_principal_and_the_administrator_set_it(self):
        for who in (self.teacher, self.bursar, self.vp, self.children["ada"]):
            with self.subTest(who=str(who)):
                self.assertEqual(self.set_cutoff(date(2025, 12, 5), who=who).status_code, 403)
        self.assertIsNone(self.cutoff())

    def test_authority_is_asked_before_the_term_is_looked_up(self):
        """A teacher asking about a term that does not exist is told what they
        are told about one that does: no existence oracle."""
        missing = self.set_cutoff(date(2025, 12, 5), who=self.teacher, term_id=self.term_id + 9999)

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing.json(), self.set_cutoff(date(2025, 12, 5), who=self.teacher).json())

    def test_the_service_refuses_without_the_route(self):
        with connected_to(self.stmarys):
            for who in (self.teacher, self.bursar):
                with self.subTest(who=str(who)), self.assertRaises(academics.NotAllowedToSetTermLength):
                    academics.set_attendance_cutoff_as(
                        who.user, self.term, date(2025, 12, 5), school=self.stmarys
                    )
            academics.set_attendance_cutoff_as(
                self.head.user, self.term, date(2025, 12, 5), school=self.stmarys
            )
        self.assertEqual(self.cutoff(), date(2025, 12, 5))

    def test_it_holds_once_a_class_of_the_term_is_past_draft_and_is_free_again_sent_back(self):
        self.set_cutoff(date(2025, 12, 5))
        sheet = self.walk(SheetState.SUBMITTED)

        response = self.set_cutoff(date(2025, 12, 1))

        self.assertEqual(response.status_code, 409)
        self.assertIn("JSS 1A's results for", response.json()["detail"])
        self.assertIn("5 December 2025", response.json()["detail"])
        self.assertEqual(self.cutoff(), date(2025, 12, 5))
        # Setting it to what it already is is not a change.
        self.assertEqual(self.set_cutoff(date(2025, 12, 5)).status_code, 200)
        with connected_to(self.stmarys):
            chain.send_back(sheet, self.head.user, reason="Look again")
        self.assertEqual(self.set_cutoff(date(2025, 12, 1)).status_code, 200)

    def test_after_release_it_holds_for_good(self):
        self.walk(SheetState.RELEASED)

        self.assertEqual(self.set_cutoff(date(2025, 12, 1)).status_code, 409)
        self.assertIsNone(self.cutoff())


class TwoSchoolsTests(CutoffSetUp):
    def test_one_schools_cutoff_is_its_own(self):
        self.set_cutoff(TUESDAY)

        self.assertIsNone(self.cutoff(self.grace, self.grace_term_id))
        response = self.take(
            WEDNESDAY, class_id=self.grace_group_id, term_id=self.grace_term_id,
            who=self.grace_teacher, host=THEIR_HOST,
        )
        self.assertEqual(response.status_code, 200)
        with connected_to(self.grace):
            term = Term.objects.get(pk=self.grace_term_id)
            self.assertEqual(summary.for_the_card(term, [self.grace_child.pk])[self.grace_child.pk].present, 1)

    def test_one_schools_staff_cannot_set_the_others(self):
        response = self.set_cutoff(TUESDAY, who=self.head, host=THEIR_HOST, term_id=self.grace_term_id)

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.cutoff(self.grace, self.grace_term_id))

    def test_one_schools_class_in_the_chain_holds_nothing_at_the_other(self):
        self.walk(SheetState.SUBMITTED)

        response = self.set_cutoff(TUESDAY, who=self.their_head, host=THEIR_HOST, term_id=self.grace_term_id)

        self.assertEqual(response.status_code, 200, response.content)
