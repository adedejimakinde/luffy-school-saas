"""Taking a child off the roll mid-session. Audit finding G-16.

`academics.leaving.take_off_the_roll_as()` through `POST /api/enrolment/roll/{id}/leave/`.
The principal's decision, with a reason, written down (`Departure`, append-only);
the child comes out of every class of a term they had not finished, unless that
term's card went home; the enrolment ends; the family can still read the cards
that went home.

The session is 2025/2026 and Ada leaves on 1 February 2026: first term over and
released, second term running, third to come. Two schools: Grace's principal and
Grace's child must neither reach nor be reached.
"""

from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from academics.leaving import take_off_the_roll_as
from academics.models import ClassPlacement, Departure, TermName
from accounts.models import Membership, MembershipStatus, Role
from accounts.services import release_student
from fees import outstanding
from fees import services as fees
from fees.models import FeeLedgerEntry
from results import services as results_services
from results import unmarked
from results.tests.test_card_api import HOST, THEIR_HOST, ReportCardApiSetUp
from schools.tests.tenants import connected_to

FEB = date(2026, 2, 1)
LEAVE = "/api/enrolment/roll/{}/leave/"


class LeavingSetUp(ReportCardApiSetUp):
    def setUp(self):
        super().setUp()
        # Enrolled when the session began: the fixture admits them today, and a
        # day left before the day joined is refused.
        Membership.objects.filter(role=Role.STUDENT).update(started_on=date(2025, 9, 1))
        for child in (self.ada, self.bola, self.ngozi):
            child.refresh_from_db()

    def leave(self, user, child, host=HOST, reason="Moving to Abuja with the family.", left_on=FEB.isoformat()):
        self.client.force_login(user)
        body = {"reason": reason}
        if left_on is not None:
            body["left_on"] = left_on
        return self.client.post(LEAVE.format(child.pk), data=body, content_type="application/json", HTTP_HOST=host)

    def terms_placed(self, child, school=None):
        school = school or self.stmarys
        with connected_to(school):
            return sorted(
                ClassPlacement.objects.filter(student_membership_id=child.pk).values_list("term__name", flat=True)
            )

    def departures(self, school=None):
        with connected_to(school or self.stmarys):
            return list(Departure.objects.all())


class ThePrincipalTakesAChildOffTests(LeavingSetUp):
    def setUp(self):
        super().setUp()
        self.release(term_name=TermName.FIRST.value)

    def test_the_child_leaves_every_class_of_a_term_not_finished_and_keeps_the_rest(self):
        """CONTROL G16-1: `take_off_the_roll_as()` without the placement delete
        makes this red: Ada is still in JSS 1A for the second and third terms."""
        response = self.leave(self.principal, self.ada)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.terms_placed(self.ada), [TermName.FIRST.value])
        self.ada.refresh_from_db()
        self.assertEqual((self.ada.status, self.ada.ended_on), (MembershipStatus.ENDED, FEB))
        self.assertEqual(self.terms_placed(self.bola), sorted(t.value for t in TermName))

    def test_it_is_written_down_who_decided_when_and_why(self):
        self.leave(self.principal, self.ada)

        (row,) = self.departures()
        self.assertEqual(row.student_membership_id, self.ada.pk)
        self.assertEqual(row.left_on, FEB)
        self.assertEqual(row.reason, "Moving to Abuja with the family.")
        self.assertEqual(row.decided_by_id, self.principal.pk)
        self.assertEqual(row.student_name, "Ada Obi")
        self.assertIn("JSS 1A, Second", row.classes_left)
        self.assertIn("JSS 1A, Third", row.classes_left)

        self.client.force_login(self.principal)
        listed = self.client.get("/api/enrolment/roll/departures/", HTTP_HOST=HOST).json()
        self.assertEqual([d["student"] for d in listed], ["Ada Obi"])
        self.assertEqual(listed[0]["decided_by"], self.principal.full_name)

    def test_the_child_is_off_the_roll_and_off_this_terms_money(self):
        """No longer on the roll, and not counted as outstanding in a term they
        did not finish, however much they owe."""
        with connected_to(self.stmarys):
            fees.charge(self.ada, self.term_of(self.stmarys, TermName.SECOND.value), 1_000_000, narration="Tuition")

        self.leave(self.principal, self.ada)

        self.client.force_login(self.staff[Role.ADMIN])
        roll = self.client.get("/api/enrolment/roll/", HTTP_HOST=HOST).json()
        self.assertNotIn("Ada Obi", [c["student"] for c in roll["children"]])
        with connected_to(self.stmarys):
            owing = outstanding.owing(self.term_of(self.stmarys, TermName.SECOND.value))
            self.assertNotIn(self.ada.pk, owing)
            # Her account is still there to read.
            self.assertEqual(FeeLedgerEntry.objects.for_student(self.ada.pk).balance(), 1_000_000)

    def test_a_term_whose_card_went_home_keeps_its_placement(self):
        """The second term released, and Ada leaving on 1 April, the day before
        it ends: its placement is what the card was reckoned from, so it stays.

        CONTROL G16-2: the placement read without `a_card_went_home()` makes this
        red: the second term's placement, which its card was reckoned from, goes."""
        self.release(term_name=TermName.SECOND.value)

        self.leave(self.principal, self.ada, left_on="2026-04-01")

        self.assertEqual(self.terms_placed(self.ada), sorted([TermName.FIRST.value, TermName.SECOND.value]))


class TheFamilyKeepsItsWayInTests(LeavingSetUp):
    def setUp(self):
        super().setUp()
        self.release(term_name=TermName.FIRST.value)

    def cards_seen_by_mama(self):
        self.client.force_login(self.mama)
        return self.client.get("/api/results/cards/", HTTP_HOST=HOST)

    def test_the_guardian_still_reads_the_card_that_went_home(self):
        """CONTROL G16-3: `release_student()` ignoring `keep_family_access`
        makes this red: Mama's parent membership ends and the host refuses her."""
        self.leave(self.principal, self.ada)

        listed = self.cards_seen_by_mama()
        self.assertEqual(listed.status_code, 200)
        self.assertIn("Ada Obi", listed.content.decode())
        self.client.force_login(self.mama)
        card = self.client.get(self.card_url(self.stmarys, self.ada), HTTP_HOST=HOST)
        self.assertEqual(card.status_code, 200)
        self.assertTrue(
            Membership.objects.filter(user=self.mama, school=self.stmarys, role=Role.PARENT,
                                      status=MembershipStatus.ACTIVE).exists()
        )

    def test_the_companion_an_ordinary_release_does_shut_the_family_out(self):
        """The gate the test above gets past is real: the same child released
        without the leaving act, and Mama is refused at the host."""
        release_student(self.ada)

        self.assertFalse(
            Membership.objects.filter(user=self.mama, school=self.stmarys, role=Role.PARENT,
                                      status=MembershipStatus.ACTIVE).exists()
        )
        self.assertNotEqual(self.cards_seen_by_mama().status_code, 200)


class OnlyThePrincipalTests(LeavingSetUp):
    def test_the_administrator_the_teacher_and_the_bursar_are_refused_and_nothing_moves(self):
        """CONTROL G16-4: `may_take_off_the_roll()` admitting `PLACEMENT_ROLES`
        makes this red for the administrator."""
        for user in (self.staff[Role.ADMIN], self.teacher, self.bursar, self.mama):
            with self.subTest(user=user.username):
                self.assertEqual(self.leave(user, self.ada).status_code, 403)
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.is_live)
        self.assertEqual(self.departures(), [])

    def test_a_principal_cannot_reach_the_other_schools_child(self):
        response = self.leave(self.principal, self.ngozi)
        self.assertEqual(response.status_code, 404)
        self.ngozi.refresh_from_db()
        self.assertTrue(self.ngozi.is_live)
        self.assertEqual(self.terms_placed(self.ngozi, self.grace), sorted(t.value for t in TermName))

    def test_each_school_lists_only_its_own_departures(self):
        self.leave(self.principal, self.ada)
        self.leave(self.their_principal, self.ngozi, host=THEIR_HOST)

        self.client.force_login(self.their_principal)
        theirs = self.client.get("/api/enrolment/roll/departures/", HTTP_HOST=THEIR_HOST).json()
        self.assertEqual([d["student"] for d in theirs], ["Ngozi Ade"])
        self.assertEqual([d.student_name for d in self.departures()], ["Ada Obi"])


class WhatIsRefusedTests(LeavingSetUp):
    def assert_nothing_written(self):
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.is_live)
        self.assertEqual(self.departures(), [])
        self.assertEqual(self.terms_placed(self.ada), sorted(t.value for t in TermName))

    def test_a_reason_is_required(self):
        """CONTROL G16-5: the service without its blank-reason refusal makes this
        red: the table's check refuses instead, as a 500."""
        response = self.leave(self.principal, self.ada, reason="   ")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Say why", response.json()["detail"])
        self.assert_nothing_written()

    def test_a_day_after_today_or_before_they_joined_is_refused(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        for day in (tomorrow, "1999-01-01", "not a date"):
            with self.subTest(day=day):
                self.assertEqual(self.leave(self.principal, self.ada, left_on=day).status_code, 422)
        self.assert_nothing_written()

    def test_a_class_with_results_with_a_signatory_is_refused(self):
        """F-01's rule: the roster the vice principal checked holds still.

        CONTROL G16-6: the placement loop without
        `_require_results_not_in_the_chain()` makes this red."""
        with connected_to(self.stmarys):
            sheet = results_services.open_sheet(
                self.group_of(self.stmarys), self.term_of(self.stmarys, TermName.SECOND.value), self.principal
            )
            results_services.submit(sheet, self.teacher, unmarked=unmarked.count(sheet.class_group, sheet.term))

        response = self.leave(self.principal, self.ada)

        self.assertEqual(response.status_code, 422)
        self.assert_nothing_written()

    def test_a_child_who_has_already_left_is_told_so(self):
        self.leave(self.principal, self.ada)
        response = self.leave(self.principal, self.ada)
        self.assertEqual(response.status_code, 422)
        self.assertIn("already left", response.json()["detail"])
        self.assertEqual(len(self.departures()), 1)


class TheRecordHoldsStillTests(LeavingSetUp):
    def test_a_departure_is_not_edited_or_deleted(self):
        """CONTROL G16-7: migration 0007 without its trigger makes this red."""
        with connected_to(self.stmarys):
            take_off_the_roll_as(self.principal, self.ada, reason="Moved away", left_on=FEB)
            row = Departure.objects.get()
            for attempt in (
                lambda: Departure.objects.filter(pk=row.pk).update(reason="Expelled"),
                lambda: Departure.objects.filter(pk=row.pk).delete(),
            ):
                with self.subTest(), self.assertRaises(IntegrityError) as caught, transaction.atomic():
                    attempt()
                self.assertIn("academics_departure is append-only", str(caught.exception))

    def test_the_table_refuses_a_blank_reason_by_name(self):
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError) as caught, transaction.atomic():
                Departure.objects.create(
                    student_membership_id=self.ada.pk, left_on=FEB, reason="",
                    decided_by_id=self.principal.pk, student_name="Ada Obi",
                )
        self.assertEqual(caught.exception.__cause__.diag.constraint_name, "a_departure_gives_a_reason")
