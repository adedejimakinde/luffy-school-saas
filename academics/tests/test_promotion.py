"""End-of-session promotion: `GET`/`POST /api/academics/promotion/`.

Two schools throughout, and both are promoted in some tests: Grace Academy has
its own "JSS 1A" and its own third term, so a promotion that read or wrote the
wrong schema, or matched a class by name, has somewhere to show.

What is held above all: **nothing moves until confirmed, and it moves all at
once or not at all.** Every refusal test asserts the placements *and* the
memberships are exactly as they were, not just that a status code came back.
"""

from datetime import date
from unittest import mock

from academics import promotion
from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import enroll_student, grant_membership
from academics import services as academics
from attendance.tests.fixtures import a_term
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

URL = "/api/academics/promotion/"


class PromotionSetUp(ChainSetUp):
    """Both schools at the end of a third term, with next session's first term open."""

    def setUp(self):
        super().setUp()
        self.ss3_kids = {
            handle: enroll_student(
                User.objects.create_user(handle, PASSWORD, full_name=name), self.stmarys
            )
            for handle, name in (("chi", "Chi Okafor"), ("dayo", "Dayo Bello"))
        }
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(name=TermName.THIRD)
            self.next_term = a_term(
                session="2026/2027", starts=date(2026, 9, 14), ends=date(2026, 12, 11)
            )
            self.jss2a = ClassGroup.objects.create(name="JSS 2A", level=2)
            self.jss2b = ClassGroup.objects.create(name="JSS 2B", level=2)
            self.ss3 = ClassGroup.objects.create(name="SS 3", level=6)
            for kid in self.ss3_kids.values():
                academics.place_student(self.ss3, self.this_term(), kid)

        with connected_to(self.grace):
            Term.objects.filter(pk=self.grace_term_id).update(name=TermName.THIRD)
            self.grace_next = a_term(
                session="2026/2027", starts=date(2026, 9, 14), ends=date(2026, 12, 11)
            )
            self.grace_2a = ClassGroup.objects.create(name="JSS 2A", level=2)

    # -- helpers -------------------------------------------------------------

    def this_term(self):
        return Term.objects.get(pk=self.term_id)

    def get(self, member=None, host=HOST):
        self.client.force_login((member or self.head).user)
        return self.client.get(URL, HTTP_HOST=host)

    def post(self, plan, member=None, host=HOST):
        self.client.force_login((member or self.head).user)
        return self.client.post(URL, data={"classes": plan}, content_type="application/json", HTTP_HOST=host)

    def default_plan(self, host=HOST, member=None):
        """The page's own defaults, as the page would post them back."""
        body = self.get(member, host=host).json()
        return [
            {
                "class_group_id": c["class_group_id"],
                "destination_id": c["destination_id"],
                "graduate": c["graduate"],
                "children": {str(k["membership_id"]): k["action"] for k in c["children"]},
            }
            for c in body["classes"]
        ]

    def placements(self, school, term_pk=None):
        with connected_to(school):
            rows = ClassPlacement.objects.all()
            if term_pk is not None:
                rows = rows.filter(term_id=term_pk)
            return sorted(
                (p.term_id, p.class_group.name, p.student_membership_id) for p in rows
            )

    def statuses(self):
        return dict(Membership.objects.filter(role=Role.STUDENT).values_list("pk", "status"))

    def assertNothingMoved(self, before):
        self.assertEqual(self.placements(self.stmarys), before[0])
        self.assertEqual(self.placements(self.grace), before[1])
        self.assertEqual(self.statuses(), before[2])

    def snapshot(self):
        return self.placements(self.stmarys), self.placements(self.grace), self.statuses()

    def class_named(self, plan, name):
        with connected_to(self.stmarys):
            pk = ClassGroup.objects.get(name=name).pk
        return next(c for c in plan if c["class_group_id"] == pk)


class TheReviewTests(PromotionSetUp):
    def test_every_class_and_every_child_is_shown_defaulting_to_promote(self):
        body = self.get().json()

        names = {c["name"]: c for c in body["classes"]}
        self.assertEqual(set(names), {"JSS 1A", "JSS 1B", "SS 3"})
        self.assertEqual(len(names["JSS 1A"]["children"]), 4)
        self.assertEqual(len(names["SS 3"]["children"]), 2)
        for row in body["classes"]:
            for child in row["children"]:
                self.assertEqual(child["action"], "promote")
        self.assertIsNone(body["problem"])
        self.assertEqual(body["to_term"], str(self.next_term))

    def test_jss_1a_goes_to_jss_2a_and_the_top_class_graduates(self):
        body = self.get().json()
        by_name = {c["name"]: c for c in body["classes"]}
        target_names = {t["class_group_id"]: t["name"] for t in body["targets"]}

        self.assertEqual(target_names[by_name["JSS 1A"]["destination_id"]], "JSS 2A")
        self.assertEqual(target_names[by_name["JSS 1B"]["destination_id"]], "JSS 2B")
        self.assertTrue(by_name["SS 3"]["graduate"])
        self.assertIsNone(by_name["SS 3"]["destination_id"])

    def test_looking_writes_nothing(self):
        before = self.snapshot()

        self.get()

        self.assertNothingMoved(before)

    def test_it_is_one_schools_children_only(self):
        body = self.get().json()
        ids = {k["membership_id"] for c in body["classes"] for k in c["children"]}

        self.assertNotIn(self.grace_child.pk, ids)
        theirs = self.get(self.their_head, THEIR_HOST).json()
        self.assertEqual(
            {k["membership_id"] for c in theirs["classes"] for k in c["children"]},
            {self.grace_child.pk},
        )

    def test_before_the_third_term_there_is_nothing_to_promote(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(name=TermName.FIRST)

        body = self.get().json()

        self.assertIn("third term", body["problem"])
        self.assertEqual(body["classes"], [])

    def test_without_next_sessions_first_term_it_says_so(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.next_term.pk).delete()

        body = self.get().json()

        self.assertIn("2026/2027", body["problem"])
        self.assertEqual(body["classes"], [])


class TheConfirmTests(PromotionSetUp):
    def test_confirming_the_defaults_moves_everybody_up_and_graduates_the_top(self):
        response = self.post(self.default_plan())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"promoted": 5, "repeated": 0, "graduated": 2})
        landed = {(name, m) for _, name, m in self.placements(self.stmarys, self.next_term.pk)}
        self.assertEqual(
            landed,
            {("JSS 2A", self.children[h].pk) for h in ("ada", "emeka", "bisi", "tunde")}
            | {("JSS 2B", self.bimpe.pk)},
        )
        for kid in self.ss3_kids.values():
            member = Membership.objects.get(pk=kid.pk)
            self.assertEqual(member.status, MembershipStatus.ENDED)
        # The old term's placements are history and stay exactly as they were.
        self.assertEqual(len(self.placements(self.stmarys, self.term_id)), 7)

    def test_a_repeater_stays_in_their_class(self):
        plan = self.default_plan()
        self.class_named(plan, "JSS 1A")["children"][str(self.children["tunde"].pk)] = "repeat"

        response = self.post(plan)

        self.assertEqual(response.json()["repeated"], 1)
        landed = dict(
            (m, name) for _, name, m in self.placements(self.stmarys, self.next_term.pk)
        )
        self.assertEqual(landed[self.children["tunde"].pk], "JSS 1A")
        self.assertEqual(landed[self.children["ada"].pk], "JSS 2A")

    def test_a_repeater_in_the_top_class_stays_and_is_not_graduated(self):
        plan = self.default_plan()
        self.class_named(plan, "SS 3")["children"][str(self.ss3_kids["chi"].pk)] = "repeat"

        self.post(plan)

        self.assertEqual(Membership.objects.get(pk=self.ss3_kids["chi"].pk).status, MembershipStatus.ACTIVE)
        self.assertEqual(Membership.objects.get(pk=self.ss3_kids["dayo"].pk).status, MembershipStatus.ENDED)
        landed = dict((m, name) for _, name, m in self.placements(self.stmarys, self.next_term.pk))
        self.assertEqual(landed[self.ss3_kids["chi"].pk], "SS 3")

    def test_the_office_may_send_a_class_somewhere_other_than_the_suggestion(self):
        plan = self.default_plan()
        row = self.class_named(plan, "JSS 1B")
        row["destination_id"] = self.jss2a.pk

        self.post(plan)

        landed = dict((m, name) for _, name, m in self.placements(self.stmarys, self.next_term.pk))
        self.assertEqual(landed[self.bimpe.pk], "JSS 2A")

    def test_the_second_school_is_not_touched_by_the_first_being_promoted(self):
        before_grace = self.placements(self.grace)
        grace_status = Membership.objects.get(pk=self.grace_child.pk).status

        self.post(self.default_plan())

        self.assertEqual(self.placements(self.grace), before_grace)
        self.assertEqual(Membership.objects.get(pk=self.grace_child.pk).status, grace_status)

    def test_each_school_promotes_on_its_own_and_not_with_the_others_plan(self):
        st_marys_plan = self.default_plan()
        before = self.snapshot()

        # St Mary's plan, posted at Grace: its classes are not Grace's.
        crossed = self.post(st_marys_plan, member=self.their_head, host=THEIR_HOST)
        self.assertEqual(crossed.status_code, 409)
        self.assertNothingMoved(before)

        ok = self.post(self.default_plan(THEIR_HOST, self.their_head), member=self.their_head, host=THEIR_HOST)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json(), {"promoted": 1, "repeated": 0, "graduated": 0})
        # Grace's one child moved up to Grace's own JSS 2A; St Mary's is exactly
        # as it was.
        self.assertEqual(self.placements(self.stmarys), before[0])
        self.assertEqual(
            [name for _, name, _ in self.placements(self.grace, self.grace_next.pk)], ["JSS 2A"]
        )

    def test_a_second_confirm_does_not_move_them_twice(self):
        plan = self.default_plan()
        self.post(plan)
        after_first = self.snapshot()

        again = self.post(plan)

        self.assertEqual(again.status_code, 409)
        self.assertNothingMoved(after_first)


class AllOrNothingTests(PromotionSetUp):
    def test_a_bad_destination_in_the_last_class_moves_nobody_in_the_first(self):
        plan = self.default_plan()
        # Order the bad one last so the good classes would already be written
        # if anything were written class by class.
        self.class_named(plan, "SS 3")["destination_id"] = 999999
        self.class_named(plan, "SS 3")["graduate"] = False
        before = self.snapshot()

        response = self.post(plan)

        self.assertEqual(response.status_code, 422)
        self.assertNothingMoved(before)

    def test_a_class_with_neither_a_destination_nor_graduation_is_refused(self):
        plan = self.default_plan()
        row = self.class_named(plan, "JSS 1A")
        row["destination_id"], row["graduate"] = None, False
        before = self.snapshot()

        self.assertEqual(self.post(plan).status_code, 422)
        self.assertNothingMoved(before)

    def test_a_child_already_placed_next_term_refuses_the_whole_promotion(self):
        with connected_to(self.stmarys):
            academics.place_student(self.jss1a, self.next_term, self.children["ada"])
        before = self.snapshot()

        response = self.post(self.default_plan())

        self.assertEqual(response.status_code, 409)
        self.assertIn("1 of these children", response.json()["detail"])
        self.assertNothingMoved(before)

    def test_a_failure_after_the_placements_are_written_rolls_them_back(self):
        """The strongest form: the writes really happened, then were undone."""
        before = self.snapshot()

        with mock.patch("academics.promotion.release_student", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.post(self.default_plan())

        self.assertNothingMoved(before)

    def test_a_plan_that_leaves_a_child_out_is_refused(self):
        plan = self.default_plan()
        row = self.class_named(plan, "JSS 1A")
        row["children"].pop(str(self.children["ada"].pk))
        before = self.snapshot()

        self.assertEqual(self.post(plan).status_code, 409)
        self.assertNothingMoved(before)

    def test_a_plan_that_leaves_a_class_out_is_refused(self):
        plan = [c for c in self.default_plan() if c["graduate"] is False][:1]
        before = self.snapshot()

        self.assertEqual(self.post(plan).status_code, 409)
        self.assertNothingMoved(before)

    def test_a_child_who_arrived_after_the_page_was_drawn_makes_the_plan_stale(self):
        plan = self.default_plan()
        late = enroll_student(User.objects.create_user("late", PASSWORD, full_name="Late Comer"), self.stmarys)
        with connected_to(self.stmarys):
            academics.place_student(self.jss1a, self.this_term(), late)
        before = self.snapshot()

        self.assertEqual(self.post(plan).status_code, 409)
        self.assertNothingMoved(before)

    def test_a_choice_that_is_neither_promote_nor_repeat_is_refused(self):
        plan = self.default_plan()
        self.class_named(plan, "JSS 1A")["children"][str(self.children["ada"].pk)] = "skip"
        before = self.snapshot()

        self.assertEqual(self.post(plan).status_code, 422)
        self.assertNothingMoved(before)

    def test_not_at_the_end_of_the_session_nothing_can_be_confirmed(self):
        plan = self.default_plan()
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(name=TermName.FIRST)
        before = self.snapshot()

        self.assertEqual(self.post(plan).status_code, 409)
        self.assertNothingMoved(before)


class AuthorityTests(PromotionSetUp):
    def test_only_the_principal_and_an_administrator_may_look_or_confirm(self):
        admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )
        plan = self.default_plan()
        before = self.snapshot()

        for member in (self.teacher, self.vp, self.bursar, self.children["ada"]):
            with self.subTest(role=member.role):
                self.assertEqual(self.get(member).status_code, 403)
                self.assertEqual(self.post(plan, member).status_code, 403)
        self.assertNothingMoved(before)

        self.assertEqual(self.get(admin).status_code, 200)
        self.assertEqual(self.post(plan, admin).status_code, 200)

    def test_a_principal_elsewhere_has_no_say_here(self):
        before = self.snapshot()
        response = self.post(self.default_plan(), member=self.their_head, host=HOST)

        self.assertIn(response.status_code, (403, 404))
        self.assertNothingMoved(before)

    def test_the_portal_has_no_such_route(self):
        self.client.force_login(self.head.user)
        self.assertEqual(self.client.get(URL, HTTP_HOST="testserver").status_code, 404)


class TheSuggestionTests(PromotionSetUp):
    def test_next_session_is_the_next_pair_of_years(self):
        self.assertEqual(promotion.next_session("2025/2026"), "2026/2027")
        self.assertIsNone(promotion.next_session("2025-26"))

    def test_with_two_arms_above_and_no_matching_letter_nothing_is_guessed(self):
        with connected_to(self.stmarys):
            odd = ClassGroup.objects.create(name="JSS 1C", level=1)
            kid = enroll_student(User.objects.create_user("cee", PASSWORD, full_name="Cee"), self.stmarys)
            academics.place_student(odd, self.this_term(), kid)
        body = self.get().json()

        row = next(c for c in body["classes"] if c["name"] == "JSS 1C")
        self.assertIsNone(row["destination_id"])
        self.assertFalse(row["graduate"])
        # ...and the plan as it stands is refused until somebody chooses.
        plan = self.default_plan()
        self.assertEqual(self.post(plan).status_code, 422)
