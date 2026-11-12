"""Making a term current carries every class list into it: audit finding G-01.

Until this, moving to a new term emptied every class. `PUT
/api/academics/terms/{id}/current/` now copies the lists of the term that was
current into a later term of the same session, in the same transaction
(`academics.term_change`), and `GET .../current/review/` says beforehand what it
will do.

St Mary's (`results.tests.fixtures.ChainSetUp`): JSS 1A with Ada, Emeka, Bisi and
Tunde, JSS 1B with Bimpe, first term current, second term opened. Grace Academy is
the second school; nothing done at St Mary's may move a row of it.

The claims:

- on day one of the new term **registers, marking, bills and fee reminders** have
  the carried children in them;
- **running it twice changes nothing**;
- **a child who left is not carried**, and the review names them;
- a child already placed by hand stays where the office put them;
- a new session's first term gets nothing here: that is promotion's;
- the switch and the carry are one transaction, and a school's lists are its own.

CONTROL: with `term_change.carry()` not called from the route, every test of the
first claim is red ("Nobody is placed in JSS 1A").
"""

from datetime import date
from unittest import mock

from academics import promotion, services, term_change
from academics.models import ClassPlacement, Term, TermName
from accounts.models import MembershipStatus
from accounts.services import release_student
from attendance import services as attendance
from fees import schedules
from fees import services as ledger
from fees.models import KOBO_PER_NAIRA, FeeLedgerEntry, FeeSchedule, FeeScheduleLine
from gradebook import services as gradebook
from gradebook.models import Assessment, Score
from notices import reminders
from notices.models import NoticeSettings
from results.tests.fixtures import HOST, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

TERMS = "/api/academics/terms/"
#: The first Monday of the second term: day one.
DAY_ONE = date(2026, 1, 12)
TUITION = 150_000 * KOBO_PER_NAIRA


class TermChangeSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        self.second_id = self.second_term.pk

    def review(self, who=None, term_id=None, host=HOST):
        self.client.force_login((who or self.head).user)
        return self.client.get(f"{TERMS}{term_id or self.second_id}/current/review/", HTTP_HOST=host)

    def make_current(self, who=None, term_id=None, host=HOST):
        self.client.force_login((who or self.head).user)
        return self.client.put(f"{TERMS}{term_id or self.second_id}/current/", HTTP_HOST=host)

    def lists(self, term_id=None, school=None):
        """`{class name: sorted child names}` for a term's placements."""
        with connected_to(school or self.stmarys):
            found = {}
            for class_name, student_id in ClassPlacement.objects.filter(
                term_id=term_id or self.second_id
            ).values_list("class_group__name", "student_membership_id"):
                found.setdefault(class_name, []).append(student_id)
            return {name: sorted(ids) for name, ids in found.items()}

    def second(self):
        return Term.objects.get(pk=self.second_id)


class TheListsGoWithTheTermTests(TermChangeSetUp):
    def test_every_class_list_is_carried_into_the_new_term(self):
        response = self.make_current()

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["is_current"])
        self.assertEqual(body["carried"], 5)
        self.assertEqual(
            self.lists(), {"JSS 1A": self.everyone(), "JSS 1B": [self.bimpe.pk]}
        )
        # Last term's lists are what they were: its cards are read from them.
        self.assertEqual(
            self.lists(self.term_id), {"JSS 1A": self.everyone(), "JSS 1B": [self.bimpe.pk]}
        )

    def test_a_register_can_be_taken_on_day_one(self):
        self.make_current()

        with connected_to(self.stmarys):
            taken = attendance.take_register_as(
                self.teacher.user, self.jss1a, self.second(), school=self.stmarys,
                on=DAY_ONE, absent_ids=[self.children["tunde"].pk],
            )
            marks = attendance.marks_in(taken.register)

        self.assertEqual(sorted(marks), self.everyone())
        self.assertEqual(sum(1 for status in marks.values() if status == "absent"), 1)

    def test_before_the_fix_there_was_nobody_to_mark(self):
        """The control for the test above: the second term as it used to open."""
        with connected_to(self.stmarys):
            services.set_current_term(self.second())
            with self.assertRaises(attendance.NoRoster):
                attendance.take_register_as(
                    self.teacher.user, self.jss1a, self.second(), school=self.stmarys, on=DAY_ONE
                )

    def test_the_marking_sheet_has_the_children_and_takes_a_mark_on_day_one(self):
        self.make_current()
        with connected_to(self.stmarys):
            paper = Assessment.objects.create(
                term=self.second(), subject=self.maths, name="First CA", max_score=20
            )
        self.client.force_login(self.teacher.user)

        sheet = self.client.get(
            f"/api/gradebook/assessments/{paper.pk}/sheet/?class_group_id={self.jss1a_id}", HTTP_HOST=HOST
        )
        with connected_to(self.stmarys):
            gradebook.set_score_as(self.teacher.user, paper, self.children["ada"], 17)
            marked = dict(Score.objects.filter(assessment=paper).values_list("student_membership_id", "value"))

        self.assertEqual(sheet.status_code, 200, sheet.content)
        self.assertIn("Ada Obi", sheet.content.decode())
        self.assertIn("Tunde Cole", sheet.content.decode())
        self.assertNotIn("Bimpe Ojo", sheet.content.decode(), "JSS 1B's child is on JSS 1A's sheet")
        self.assertEqual(marked, {self.children["ada"].pk: 17})

    def test_a_bill_applied_on_day_one_charges_every_carried_child(self):
        self.make_current()

        with connected_to(self.stmarys):
            bill = FeeSchedule.objects.create(term=self.second(), class_group=self.jss1a)
            FeeScheduleLine.objects.create(schedule=bill, description="Tuition", amount_kobo=TUITION, position=1)
            summary = schedules.apply_to_class(bill, by=self.bursar.user)
            owed = {
                child.pk: FeeLedgerEntry.objects.for_student(child.pk).balance()
                for child in (*self.children.values(), self.bimpe)
            }

        self.assertEqual(summary.students, 4)
        self.assertEqual(summary.charges_posted, 4)
        for child in self.children.values():
            self.assertEqual(owed[child.pk], TUITION)
        self.assertEqual(owed[self.bimpe.pk], 0, "JSS 1B was not billed")

    def test_fee_reminders_find_the_carried_children_on_day_one(self):
        with connected_to(self.stmarys):
            NoticeSettings.objects.create(pk=1, fee_reminders=True)
            ledger.charge(self.children["ada"], Term.objects.get(pk=self.term_id), TUITION, narration="First term tuition")
            ledger.charge(self.bimpe, Term.objects.get(pk=self.term_id), TUITION, narration="First term tuition")
        self.make_current()

        with connected_to(self.stmarys):
            whole_school = reminders.preview_reminders(self.second(), actor=self.bursar.user)
            one_class = reminders.preview_reminders(
                self.second(), actor=self.bursar.user, class_group=self.jss1a
            )

        self.assertEqual(
            sorted(child["student"] for child in whole_school["children"]), ["Ada Obi", "Bimpe Ojo"]
        )
        self.assertEqual([child["student"] for child in one_class["children"]], ["Ada Obi"])
        self.assertEqual(one_class["children"][0]["amount_kobo"], TUITION)


class TwiceChangesNothingTests(TermChangeSetUp):
    def test_making_it_current_twice_carries_once(self):
        first = self.make_current()
        with connected_to(self.stmarys):
            before = list(
                ClassPlacement.objects.filter(term_id=self.second_id)
                .order_by("pk")
                .values_list("pk", "class_group_id", "student_membership_id", "placed_by_id", "updated_at")
            )

        second = self.make_current()

        with connected_to(self.stmarys):
            after = list(
                ClassPlacement.objects.filter(term_id=self.second_id)
                .order_by("pk")
                .values_list("pk", "class_group_id", "student_membership_id", "placed_by_id", "updated_at")
            )
            current = list(Term.objects.filter(is_current=True).values_list("pk", flat=True))
        self.assertEqual((first.json()["carried"], second.json()["carried"]), (5, 0))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(after, before)
        self.assertEqual(len(after), 5)
        self.assertEqual(current, [self.second_id])

    def test_the_carry_itself_run_again_makes_nothing(self):
        self.make_current()

        with connected_to(self.stmarys):
            first, second = Term.objects.get(pk=self.term_id), self.second()
            again = term_change.carry(first, second, by=self.head.user)
            copied = services.carry_forward_placements(first, second, by=self.head.user)
            rows = ClassPlacement.objects.filter(term=second).count()

        self.assertEqual((again, copied, rows), (0, 0, 5))

    def test_going_back_and_forward_again_changes_nothing(self):
        self.make_current()
        back = self.make_current(term_id=self.term_id)
        forward = self.make_current()

        self.assertEqual((back.json()["carried"], forward.json()["carried"]), (0, 0))
        self.assertEqual(self.lists(), {"JSS 1A": self.everyone(), "JSS 1B": [self.bimpe.pk]})
        self.assertEqual(
            self.lists(self.term_id), {"JSS 1A": self.everyone(), "JSS 1B": [self.bimpe.pk]}
        )


class WhoIsNotCarriedTests(TermChangeSetUp):
    def test_a_child_who_left_is_not_carried(self):
        release_student(self.children["tunde"])

        response = self.make_current()

        self.assertEqual(response.json()["carried"], 4)
        self.assertEqual(self.lists()["JSS 1A"], self.ids("ada", "emeka", "bisi"))
        # They were in JSS 1A last term, and last term still says so.
        self.assertIn(self.children["tunde"].pk, self.lists(self.term_id)["JSS 1A"])
        self.children["tunde"].refresh_from_db()
        self.assertEqual(self.children["tunde"].status, MembershipStatus.ENDED)

    def test_a_child_placed_by_hand_already_stays_where_the_office_put_them(self):
        with connected_to(self.stmarys):
            services.place_student(self.jss1b, self.second(), self.children["ada"], by=self.head.user)

        response = self.make_current()

        self.assertEqual(response.json()["carried"], 4)
        self.assertEqual(
            self.lists(),
            {"JSS 1A": self.ids("emeka", "bisi", "tunde"), "JSS 1B": sorted([self.bimpe.pk, self.children["ada"].pk])},
        )

    def test_a_suspended_child_is_still_ours_and_is_carried(self):
        from accounts.models import Membership

        Membership.objects.filter(pk=self.children["bisi"].pk).update(status=MembershipStatus.SUSPENDED)

        self.make_current()

        self.assertIn(self.children["bisi"].pk, self.lists()["JSS 1A"])


class TheReviewTests(TermChangeSetUp):
    def test_it_lists_each_class_its_count_and_who_is_not_carried(self):
        release_student(self.children["tunde"])
        with connected_to(self.stmarys):
            services.place_student(self.jss1b, self.second(), self.children["ada"], by=self.head.user)

        response = self.review()

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["carries"])
        self.assertEqual((body["from_term"]["term_id"], body["term"]["term_id"]), (self.term_id, self.second_id))
        classes = {line["name"]: line for line in body["classes"]}
        self.assertEqual(list(classes), ["JSS 1A", "JSS 1B"])
        self.assertEqual((classes["JSS 1A"]["carried"], classes["JSS 1A"]["already_placed"]), (2, 1))
        self.assertEqual(
            [(child["name"], child["why"]) for child in classes["JSS 1A"]["not_carried"]],
            [("Tunde Cole", term_change.LEFT)],
        )
        self.assertEqual((classes["JSS 1B"]["carried"], classes["JSS 1B"]["not_carried"]), (1, []))
        self.assertEqual((body["carried"], body["already_placed"], body["not_carried"]), (3, 1, 1))

    def test_it_writes_nothing(self):
        self.review()

        self.assertEqual(self.lists(), {})
        with connected_to(self.stmarys):
            self.assertEqual(list(Term.objects.filter(is_current=True).values_list("pk", flat=True)), [self.term_id])

    def test_what_it_says_is_what_the_switch_does(self):
        release_student(self.children["emeka"])

        said = self.review().json()
        done = self.make_current().json()
        after = self.review().json()

        self.assertEqual(said["carried"], done["carried"])
        self.assertEqual(done["carried"], 4)
        # Asked again once it is current: there is nothing left to carry.
        self.assertFalse(after["carries"])
        self.assertIn("already the current term", after["why_not"])

    def test_only_the_office_reads_it(self):
        self.assertEqual(self.review(self.teacher).status_code, 403)
        self.assertEqual(self.review(self.bursar).status_code, 403)
        self.assertNotIn("Tunde", self.review(self.teacher).content.decode())
        self.assertEqual(self.make_current(self.teacher).status_code, 403)
        self.assertEqual(self.lists(), {})


class ANewSessionIsPromotionsTests(TermChangeSetUp):
    """Third term to next session's first term: nothing is carried, and promotion
    still works afterwards, because it refuses children already placed there."""

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            third = Term.objects.create(
                session="2025/2026", name=TermName.THIRD, starts_on=date(2026, 4, 27), ends_on=date(2026, 7, 24)
            )
            next_first = Term.objects.create(
                session="2026/2027", name=TermName.FIRST, starts_on=date(2026, 9, 14), ends_on=date(2026, 12, 11)
            )
            self.third_id, self.next_first_id = third.pk, next_first.pk

    def test_the_whole_year_carries_term_to_term_and_stops_at_the_session(self):
        second = self.make_current()
        third = self.make_current(term_id=self.third_id)
        said = self.review(term_id=self.next_first_id).json()
        new_session = self.make_current(term_id=self.next_first_id)

        self.assertEqual((second.json()["carried"], third.json()["carried"]), (5, 5))
        self.assertEqual(self.lists(self.third_id), {"JSS 1A": self.everyone(), "JSS 1B": [self.bimpe.pk]})
        self.assertFalse(said["carries"])
        self.assertIn("Promotion", said["why_not"])
        self.assertEqual(said["classes"], [])
        self.assertEqual(new_session.status_code, 200)
        self.assertEqual(new_session.json()["carried"], 0)
        self.assertEqual(self.lists(self.next_first_id), {})

    def test_promotion_is_still_the_step_that_fills_the_new_session(self):
        self.make_current()
        self.make_current(term_id=self.third_id)

        with connected_to(self.stmarys):
            found = promotion.review()
            plan = [
                {
                    "class_group_id": line.class_group.pk,
                    "graduate": True,
                    "destination_id": None,
                    "children": {child.membership_id: promotion.REPEAT for child in line.children},
                }
                for line in found.classes
            ]
            outcome = promotion.promote(plan, by=self.head.user)

        self.assertIsNone(found.problem)
        self.assertEqual(outcome.repeated, 5)
        self.assertEqual(
            self.lists(self.next_first_id), {"JSS 1A": self.everyone(), "JSS 1B": [self.bimpe.pk]}
        )


class OneTransactionTests(TermChangeSetUp):
    def test_if_the_carry_fails_the_term_is_not_changed(self):
        with mock.patch(
            "academics.services.carry_forward_placements",
            side_effect=services.ResultsInTheChain("JSS 1A's results are waiting for approval."),
        ):
            response = self.make_current()

        self.assertEqual(response.status_code, 422)
        self.assertIn("not changed", response.json()["detail"])
        with connected_to(self.stmarys):
            self.assertEqual(list(Term.objects.filter(is_current=True).values_list("pk", flat=True)), [self.term_id])
        self.assertEqual(self.lists(), {})


class TwoSchoolsTests(TermChangeSetUp):
    def test_one_schools_term_change_moves_nothing_at_the_other(self):
        with connected_to(self.grace):
            theirs = Term.objects.create(
                session="2025/2026", name=TermName.SECOND, starts_on=date(2026, 1, 12), ends_on=date(2026, 4, 2)
            )

        self.make_current()

        with connected_to(self.grace):
            self.assertEqual(ClassPlacement.objects.filter(term=theirs).count(), 0)
            self.assertEqual(
                list(Term.objects.filter(is_current=True).values_list("pk", flat=True)), [self.grace_term_id]
            )
        # St Mary's principal has no say at Grace, and Grace's own switch carries Grace's.
        self.assertEqual(self.make_current(term_id=theirs.pk, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.review(term_id=theirs.pk, host=THEIR_HOST).status_code, 403)
        mine = self.make_current(self.their_head, term_id=theirs.pk, host=THEIR_HOST)
        self.assertEqual(mine.json()["carried"], 1)
        self.assertEqual(self.lists(theirs.pk, self.grace), {"JSS 1A": [self.grace_child.pk]})
        self.assertEqual(self.lists(), {"JSS 1A": self.everyone(), "JSS 1B": [self.bimpe.pk]})
