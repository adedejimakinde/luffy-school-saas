"""Promotion follows the principal's decision: audit finding G-04.

Before this, `promote()` moved children with no reference to results or to the
principal: the page started every child at "promote", an administrator could
make any child repeat, leave or graduate with nothing on record, and
`sessions.decide_as()`, the weighting and the pass mark had no route.

St Mary's and Grace Academy at the end of a third term
(`test_promotion.PromotionSetUp`): JSS 1A (Ada, Emeka, Bisi, Tunde), JSS 1B
(Bimpe) and SS 3 (Chi, Dayo) at St Mary's; Grace's own JSS 1A with Chidi.

The claims, each controlled (the table is in the pull request):

- **Classnode suggests from the released, frozen year and the pass mark**, and
  from nothing else: no released third-term card, no suggestion;
- **the principal decides, through a route, with a reason**: the administrator,
  who may open the page and press Confirm, is refused; a blank reason is
  refused; every decision in a request is recorded or none is;
- **`promote()` refuses a child nobody decided about, and a choice that is not
  what was decided**, by name, with nothing moved;
- **leaving and graduating are decisions too**, kept with their reason, and a
  graduate's family keeps its way in (G-05 has its own module);
- **the pass mark and the weighting have a route**, for the principal and the
  administrator;
- one school's decisions, settings and children never reach the other's.
"""

from decimal import Decimal

from academics.models import ClassPlacement, Term
from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import grant_membership
from gradebook.models import Score
from results import services as chain
from results import sessions, unmarked
from results.models import PromotionDecision, ReleasedSessionResult, SessionSettings
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST
from schools.tests.tenants import connected_to

from .test_promotion import URL, PromotionSetUp

DECISIONS = f"{URL}decisions/"
SETTINGS = "/api/results/year-settings/"


class DecisionsSetUp(PromotionSetUp):
    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ope", PASSWORD, full_name="Ope Ajayi"),
            self.stmarys,
            Role.ADMIN,
        )
        self.their_admin = grant_membership(
            User.objects.create_user("gad", PASSWORD, full_name="Gad Udo"),
            self.grace,
            Role.ADMIN,
        )

    # -- the year ------------------------------------------------------------

    def release_jss1a(self, **marks):
        """Mark JSS 1A's one paper (out of 20) and release its third term.

        `marks` is `handle=score`; a child left out has no mark and no average.
        The year is then frozen from the cards (`ReleasedSessionResult`).
        """
        with connected_to(self.stmarys):
            for handle, value in marks.items():
                Score.objects.create(
                    assessment_id=self.first_ca_id,
                    student_membership_id=self.children[handle].pk,
                    value=value,
                )
            term = self.this_term()
            sheet = chain.open_sheet(self.jss1a, term, self.head.user)
            count = unmarked.count(sheet.class_group, sheet.term)
            chain.submit(sheet, self.teacher.user, unmarked=count)
            chain.check(sheet, self.vp.user, unmarked=count)
            chain.approve(sheet, self.head.user, unmarked=count)
            chain.release(sheet, self.head.user)

    # -- the routes ----------------------------------------------------------

    def decide(self, children, reason="Met the pass mark", member=None, host=HOST):
        self.client.force_login((member or self.head).user)
        return self.client.post(
            DECISIONS,
            data={"reason": reason, "children": {str(k): v for k, v in children.items()}},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def child_in(self, body, member):
        return next(
            k for c in body["classes"] for k in c["children"] if k["membership_id"] == member.pk
        )

    def decisions(self, school=None):
        with connected_to(school or self.stmarys):
            return list(
                PromotionDecision.objects.order_by("id").values_list(
                    "student_membership_id", "status", "note"
                )
            )

    def plan(self, **choices):
        """The default plan with these children's choices changed: `tunde="repeat"`."""
        plan = self.default_plan()
        everybody = {**self.children, **self.ss3_kids, "bimpe": self.bimpe}
        for handle, choice in choices.items():
            for entry in plan:
                key = str(everybody[handle].pk)
                if key in entry["children"]:
                    entry["children"][key] = choice
        return plan

    def decide_everybody(self, **different):
        """The principal promotes JSS 1A and 1B and graduates SS 3, bar `different`."""
        wanted = {c.pk: "promoted" for c in self.children.values()}
        wanted[self.bimpe.pk] = "promoted"
        wanted.update({k.pk: "graduated" for k in self.ss3_kids.values()})
        everybody = {**self.children, **self.ss3_kids, "bimpe": self.bimpe}
        for handle, status in different.items():
            wanted[everybody[handle].pk] = status
        response = self.decide(wanted)
        self.assertEqual(response.status_code, 200, response.content)


class ClassnodeSuggestsFromTheReleasedYearTests(DecisionsSetUp):
    def test_the_suggestion_is_the_frozen_average_against_the_pass_mark(self):
        # 14/20 is 70%, 8/20 is 40%; the school's pass mark is the default 50.
        self.release_jss1a(ada=14, emeka=8, bisi=10)

        body = self.get().json()

        ada, emeka, bisi = (self.child_in(body, self.children[h]) for h in ("ada", "emeka", "bisi"))
        self.assertEqual((ada["average"], ada["suggested"]), ("70.00", "promoted"))
        self.assertEqual((emeka["average"], emeka["suggested"]), ("40.00", "repeated"))
        # At the pass mark is a pass.
        self.assertEqual((bisi["average"], bisi["suggested"]), ("50.00", "promoted"))
        self.assertEqual(body["pass_mark"], "50.00")
        # The figure is the one frozen on the card, not one worked out here.
        with connected_to(self.stmarys):
            frozen = ReleasedSessionResult.objects.get(student_membership_id=self.children["ada"].pk)
        self.assertEqual(frozen.session_average, Decimal("70.00"))

    def test_a_child_with_no_released_year_gets_no_suggestion(self):
        """Marks alone suggest nothing: JSS 1B is marked and was never released."""
        self.release_jss1a(ada=14)
        with connected_to(self.stmarys):
            Score.objects.create(
                assessment_id=self.first_ca_id, student_membership_id=self.bimpe.pk, value=19
            )

        body = self.get().json()

        bimpe = self.child_in(body, self.bimpe)
        self.assertIsNone(bimpe["average"])
        self.assertEqual(bimpe["suggested"], "")
        # Released with no mark: a card, no average, and so nothing to suggest.
        tunde = self.child_in(body, self.children["tunde"])
        self.assertIsNone(tunde["average"])
        self.assertEqual(tunde["suggested"], "")

    def test_a_decision_before_release_records_no_suggestion(self):
        """`decide()` reads the frozen year only. Live marks propose nothing."""
        with connected_to(self.stmarys):
            Score.objects.create(
                assessment_id=self.first_ca_id, student_membership_id=self.children["ada"].pk, value=4
            )

        self.decide({self.children["ada"].pk: "promoted"})

        with connected_to(self.stmarys):
            row = PromotionDecision.objects.get()
        self.assertEqual((row.suggested, row.session_average, row.pass_mark_used), ("", None, None))

    def test_the_schools_own_pass_mark_decides_the_suggestion(self):
        self.release_jss1a(ada=14)
        self.client.force_login(self.head.user)
        self.client.put(SETTINGS, data={"pass_mark": "75"}, content_type="application/json", HTTP_HOST=HOST)

        body = self.get().json()

        self.assertEqual(self.child_in(body, self.children["ada"])["suggested"], "repeated")
        self.assertEqual(body["pass_mark"], "75.00")

    def test_a_decision_keeps_the_suggestion_and_the_figures_it_was_made_against(self):
        self.release_jss1a(emeka=8)

        self.decide({self.children["emeka"].pk: "on_trial"}, reason="Improving; to be watched")

        with connected_to(self.stmarys):
            row = PromotionDecision.objects.get()
        self.assertEqual(row.status, "on_trial")
        self.assertEqual(row.suggested, "repeated")
        self.assertEqual(row.session_average, Decimal("40.00"))
        self.assertEqual(row.pass_mark_used, Decimal("50.00"))
        self.assertEqual(row.note, "Improving; to be watched")
        self.assertEqual(row.decided_by_id, self.head.user.pk)
        # And the page shows the suggestion kept with the decision.
        self.client.put(SETTINGS, data={"pass_mark": "10"}, content_type="application/json", HTTP_HOST=HOST)
        shown = self.child_in(self.get().json(), self.children["emeka"])
        self.assertEqual(shown["suggested"], "repeated")
        self.assertEqual(shown["decision"]["status"], "on_trial")
        self.assertEqual(shown["decision"]["reason"], "Improving; to be watched")
        self.assertEqual(shown["decision"]["by"], "Ngozi Eze")
        self.assertEqual(shown["action"], "promote")


class ThePrincipalDecidesTests(DecisionsSetUp):
    def test_the_principal_records_a_class_with_one_reason(self):
        wanted = {c.pk: "promoted" for c in self.children.values()}
        wanted[self.children["tunde"].pk] = "repeated"

        response = self.decide(wanted, reason="  Staff meeting of 24 July  ")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"decided": 4})
        self.assertEqual(
            sorted(self.decisions()),
            sorted(
                (pk, status, "Staff meeting of 24 July") for pk, status in wanted.items()
            ),
        )
        body = self.get().json()
        self.assertEqual(body["undecided"], 3)
        self.assertEqual(self.child_in(body, self.children["tunde"])["action"], "repeat")
        self.assertEqual(self.child_in(body, self.children["ada"])["action"], "promote")

    def test_the_administrator_who_may_promote_may_not_decide(self):
        """The one place the two sets disagree: the office carries out, the principal decides."""
        self.assertEqual(self.get(self.admin).status_code, 200)
        self.assertFalse(self.get(self.admin).json()["may_decide"])
        self.assertTrue(self.get().json()["may_decide"])

        response = self.decide({self.children["ada"].pk: "repeated"}, member=self.admin)

        self.assertEqual(response.status_code, 403)
        self.assertIn("principal's decision", response.json()["detail"])
        self.assertEqual(self.decisions(), [])

    def test_a_teacher_a_vice_principal_and_a_bursar_are_refused(self):
        for member in (self.teacher, self.vp, self.bursar):
            with self.subTest(member=str(member)):
                response = self.decide({self.children["ada"].pk: "promoted"}, member=member)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.decisions(), [])

    def test_the_service_refuses_the_administrator_without_the_route(self):
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.NotAllowedToDecidePromotion):
                sessions.decide_many_as(
                    self.admin.user, "2025/2026", {self.children["ada"]: "promoted"}, reason="x"
                )
        self.assertEqual(self.decisions(), [])

    def test_a_reason_is_required(self):
        for reason in ("", "   ", "\n\t"):
            with self.subTest(reason=reason):
                response = self.decide({self.children["ada"].pk: "repeated"}, reason=reason)
                self.assertEqual(response.status_code, 422)
                self.assertIn("Say why", response.json()["detail"])
        self.assertEqual(self.decisions(), [])

    def test_the_service_requires_the_reason_without_the_route(self):
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.ReasonRequired):
                sessions.decide_as(self.head.user, self.children["ada"], "2025/2026", "repeated", note=" ")
        self.assertEqual(self.decisions(), [])

    def test_one_bad_outcome_and_nobody_is_decided(self):
        response = self.decide(
            {self.children["ada"].pk: "promoted", self.children["emeka"].pk: "expelled"}
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("not a promotion outcome", response.json()["detail"])
        self.assertEqual(self.decisions(), [])

    def test_a_child_not_on_this_terms_lists_is_refused_and_nobody_is_decided(self):
        with connected_to(self.stmarys):
            ClassPlacement.objects.filter(student_membership_id=self.children["tunde"].pk).delete()

        response = self.decide(
            {self.children["ada"].pk: "promoted", self.children["tunde"].pk: "promoted"}
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.decisions(), [])

    def test_changing_a_decision_writes_a_second_row_and_the_later_holds(self):
        self.decide({self.children["ada"].pk: "repeated"}, reason="Below the pass mark")
        self.decide({self.children["ada"].pk: "on_trial"}, reason="Appeal heard on 30 July")

        self.assertEqual(
            self.decisions(),
            [
                (self.children["ada"].pk, "repeated", "Below the pass mark"),
                (self.children["ada"].pk, "on_trial", "Appeal heard on 30 July"),
            ],
        )
        shown = self.child_in(self.get().json(), self.children["ada"])
        self.assertEqual(shown["decision"]["status"], "on_trial")

    def test_outside_the_end_of_the_session_there_is_nothing_to_decide(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.next_term.pk).delete()

        response = self.decide({self.children["ada"].pk: "promoted"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.decisions(), [])


class PromotionCarriesOutTheDecisionTests(DecisionsSetUp):
    def test_nobody_decided_nobody_moves(self):
        before = self.snapshot()

        response = self.post(self.default_plan(), decided=False)

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertIn("has not decided about 7 children", detail)
        self.assertIn("Ada Obi", detail)
        self.assertNothingMoved(before)

    def test_one_child_left_out_of_the_decisions(self):
        wanted = {c.pk: "promoted" for h, c in self.children.items() if h != "tunde"}
        wanted[self.bimpe.pk] = "promoted"
        wanted.update({k.pk: "graduated" for k in self.ss3_kids.values()})
        self.decide(wanted)
        before = self.snapshot()

        response = self.post(self.default_plan(), decided=False)

        self.assertEqual(response.status_code, 409)
        self.assertIn("has not decided about 1 child: Tunde Cole", response.json()["detail"])
        self.assertNothingMoved(before)

    def test_as_decided_everybody_moves(self):
        self.decide_everybody(tunde="repeated", emeka="on_trial", chi="withdrawn")

        response = self.post(self.plan(tunde="repeat", chi="leave"), decided=False)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"promoted": 4, "repeated": 1, "graduated": 1, "left": 1})

    def test_the_administrator_carries_out_what_the_principal_decided(self):
        self.decide_everybody()

        response = self.post(self.default_plan(), member=self.admin, decided=False)

        self.assertEqual(response.status_code, 200, response.content)

    def test_promoting_a_child_the_principal_said_repeats_is_refused(self):
        self.decide_everybody(tunde="repeated")
        before = self.snapshot()

        response = self.post(self.default_plan(), member=self.admin, decided=False)

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertIn("not what the principal decided", detail)
        self.assertIn("Tunde Cole (decided: repeating the class; this plan: is promoted to JSS 2A)", detail)
        self.assertNothingMoved(before)

    def test_every_choice_the_principal_did_not_make_is_refused(self):
        """Each way a plan can disagree with a decision, one at a time."""
        self.decide_everybody(emeka="repeated", bisi="withdrawn")
        before = self.snapshot()
        cases = {
            # decided promoted
            "a child decided promoted is made to repeat": self.plan(emeka="repeat", bisi="leave", ada="repeat"),
            "a child decided promoted is marked leaving": self.plan(emeka="repeat", bisi="leave", ada="leave"),
            # decided repeated
            "a child decided repeating is marked leaving": self.plan(emeka="leave", bisi="leave"),
            # decided withdrawn
            "a child decided leaving is promoted": self.plan(emeka="repeat", bisi="promote"),
            "a child decided leaving repeats": self.plan(emeka="repeat", bisi="repeat"),
            # decided graduated
            "a graduate is marked leaving": self.plan(emeka="repeat", bisi="leave", chi="leave"),
            "a graduate repeats": self.plan(emeka="repeat", bisi="leave", dayo="repeat"),
        }
        for what, plan in cases.items():
            with self.subTest(what=what):
                response = self.post(plan, member=self.admin, decided=False)
                self.assertEqual(response.status_code, 409, response.content)
                self.assertIn("not what the principal decided", response.json()["detail"])
                self.assertNothingMoved(before)
        # And the plan that is what was decided goes through.
        self.assertEqual(
            self.post(self.plan(emeka="repeat", bisi="leave"), member=self.admin, decided=False).status_code,
            200,
        )

    def test_a_class_decided_promoted_cannot_be_graduated_nor_a_graduating_class_moved_up(self):
        self.decide_everybody()
        before = self.snapshot()

        graduating = self.default_plan()
        entry = self.class_named(graduating, "JSS 1B")
        entry["graduate"], entry["destination_id"] = True, None
        response = self.post(graduating, decided=False)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Bimpe Ojo (decided: promoted; this plan: graduates)", response.json()["detail"])

        moving = self.default_plan()
        entry = self.class_named(moving, "SS 3")
        entry["graduate"], entry["destination_id"] = False, self.jss2a.pk
        response = self.post(moving, decided=False)
        self.assertEqual(response.status_code, 409)
        self.assertIn("decided: graduated; this plan: is promoted to JSS 2A", response.json()["detail"])
        self.assertNothingMoved(before)

    def test_the_service_refuses_without_the_route(self):
        """`promote()` itself, with no request behind it: there is no way round."""
        from academics import promotion

        with connected_to(self.stmarys):
            with self.assertRaises(promotion.NotDecided):
                promotion.promote(self.default_plan())
        self.decide_everybody(tunde="repeated")
        with connected_to(self.stmarys):
            with self.assertRaises(promotion.AgainstTheDecision):
                promotion.promote(self.default_plan())

    def test_the_latest_decision_is_the_one_carried_out(self):
        self.decide_everybody(tunde="repeated")
        self.decide({self.children["tunde"].pk: "promoted"}, reason="Appeal heard on 30 July")

        self.assertEqual(self.post(self.plan(tunde="repeat"), decided=False).status_code, 409)
        self.assertEqual(self.post(self.default_plan(), decided=False).status_code, 200)


class LeavingAndGraduatingAreDecidedTests(DecisionsSetUp):
    def test_a_leaver_and_a_graduate_are_ended_on_the_principals_word_with_the_reason(self):
        self.decide_everybody()
        self.decide({self.children["tunde"].pk: "withdrawn"}, reason="Family is moving to Ibadan")
        self.decide({k.pk: "graduated" for k in self.ss3_kids.values()}, reason="Completed SS 3")

        response = self.post(self.plan(tunde="leave"), member=self.admin, decided=False)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["left"], 1)
        self.assertEqual(response.json()["graduated"], 2)
        for member in (self.children["tunde"], *self.ss3_kids.values()):
            self.assertEqual(Membership.objects.get(pk=member.pk).status, MembershipStatus.ENDED)
        with connected_to(self.stmarys):
            tunde = sessions.promotion_of(self.children["tunde"], "2025/2026")
            chi = sessions.promotion_of(self.ss3_kids["chi"], "2025/2026")
        self.assertEqual((tunde.status, tunde.note), ("withdrawn", "Family is moving to Ibadan"))
        self.assertEqual((chi.status, chi.note), ("graduated", "Completed SS 3"))
        self.assertEqual(tunde.decided_by_id, self.head.user.pk)

    def test_nobody_leaves_or_graduates_on_the_administrators_say(self):
        """What the audit reproduced: an administrator posting `leave` and a graduation."""
        before = self.snapshot()

        response = self.post(self.plan(tunde="leave"), member=self.admin, decided=False)

        self.assertEqual(response.status_code, 409)
        self.assertNothingMoved(before)
        for member in (self.children["tunde"], *self.ss3_kids.values()):
            self.assertEqual(Membership.objects.get(pk=member.pk).status, MembershipStatus.ACTIVE)


class TheYearSettingsTests(DecisionsSetUp):
    def put(self, body, member=None, host=HOST):
        self.client.force_login((member or self.head).user)
        return self.client.put(SETTINGS, data=body, content_type="application/json", HTTP_HOST=host)

    def read(self, member=None, host=HOST):
        self.client.force_login((member or self.head).user)
        return self.client.get(SETTINGS, HTTP_HOST=host)

    def row(self, school=None):
        with connected_to(school or self.stmarys):
            row = sessions.settings()
            return row.averaging, row.first_weight, row.second_weight, row.third_weight, row.pass_mark

    def test_a_school_that_set_nothing_averages_equally_and_passes_at_fifty(self):
        self.assertEqual(
            self.read().json(),
            {"averaging": "equal", "first_weight": None, "second_weight": None,
             "third_weight": None, "pass_mark": "50"},
        )

    def test_the_principal_and_the_administrator_set_the_weighting_and_the_pass_mark(self):
        response = self.put(
            {"averaging": "weighted", "first_weight": "20", "second_weight": "20",
             "third_weight": "60", "pass_mark": "45"},
            member=self.admin,
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {"averaging": "weighted", "first_weight": "20", "second_weight": "20",
             "third_weight": "60", "pass_mark": "45"},
        )
        self.assertEqual(
            self.row(), ("weighted", Decimal("20"), Decimal("20"), Decimal("60"), Decimal("45"))
        )
        self.assertEqual(self.put({"averaging": "equal"}).json()["averaging"], "equal")
        self.assertEqual(self.row()[:4], ("equal", None, None, None))
        self.assertEqual(self.row()[4], Decimal("45"))

    def test_nobody_else_reads_or_changes_them(self):
        before = self.row()
        for member in (self.teacher, self.vp, self.bursar, self.children["ada"]):
            with self.subTest(member=str(member)):
                self.assertEqual(self.read(member).status_code, 403)
                self.assertEqual(self.put({"pass_mark": "1"}, member=member).status_code, 403)
        self.assertEqual(self.row(), before)

    def test_a_weighting_that_does_not_add_up_changes_nothing_and_neither_does_its_pass_mark(self):
        before = self.row()

        response = self.put(
            {"averaging": "weighted", "first_weight": "20", "second_weight": "20",
             "third_weight": "50", "pass_mark": "45"}
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("adds up to 90", response.json()["detail"])
        self.assertEqual(self.row(), before)

    def test_bad_numbers_are_refused_in_a_sentence(self):
        before = self.row()
        for body in (
            {"pass_mark": "101"},
            {"pass_mark": "-1"},
            {"pass_mark": "fifty"},
            {"pass_mark": "49.999"},
            {"averaging": "weighted"},
            {"averaging": "weighted", "first_weight": "33.333", "second_weight": "33.333", "third_weight": "33.334"},
            {"averaging": "weighted", "first_weight": "-10", "second_weight": "50", "third_weight": "60"},
            {"averaging": "sometimes"},
        ):
            with self.subTest(body=body):
                response = self.put(body)
                self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(self.row(), before)

    def test_a_frozen_year_and_a_recorded_decision_keep_what_they_were_made_with(self):
        self.release_jss1a(ada=14)
        self.decide({self.children["ada"].pk: "promoted"})

        self.put({"averaging": "weighted", "first_weight": "0", "second_weight": "0",
                  "third_weight": "100", "pass_mark": "90"})

        with connected_to(self.stmarys):
            frozen = ReleasedSessionResult.objects.get(student_membership_id=self.children["ada"].pk)
            decision = PromotionDecision.objects.get()
        self.assertEqual(frozen.averaging, "equal")
        self.assertEqual(decision.pass_mark_used, Decimal("50.00"))
        self.assertEqual(decision.suggested, "promoted")


class TwoSchoolsTests(DecisionsSetUp):
    def test_one_schools_principal_cannot_decide_about_the_others_child(self):
        response = self.decide({self.grace_child.pk: "repeated"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.decisions(self.stmarys), [])
        self.assertEqual(self.decisions(self.grace), [])
        # Nor on the other school's host, where they hold no role at all.
        response = self.decide({self.grace_child.pk: "repeated"}, host=THEIR_HOST)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.decisions(self.grace), [])

    def test_a_decision_at_one_school_decides_nothing_at_the_other(self):
        self.decide_everybody()

        self.assertEqual(self.decisions(self.grace), [])
        theirs = self.get(self.their_head, THEIR_HOST).json()
        self.assertEqual(theirs["undecided"], 1)
        before = self.snapshot()
        response = self.post(self.default_plan(THEIR_HOST, self.their_head), self.their_head, THEIR_HOST, decided=False)
        self.assertEqual(response.status_code, 409)
        self.assertNothingMoved(before)

    def test_each_school_has_its_own_pass_mark_and_weighting(self):
        self.client.force_login(self.head.user)
        self.client.put(SETTINGS, data={"pass_mark": "70"}, content_type="application/json", HTTP_HOST=HOST)

        with connected_to(self.grace):
            self.assertEqual(sessions.settings().pass_mark, Decimal("50.00"))
            self.assertFalse(SessionSettings.objects.exclude(pass_mark=Decimal("50.00")).exists())
        self.client.force_login(self.their_admin.user)
        theirs = self.client.get(SETTINGS, HTTP_HOST=THEIR_HOST).json()
        self.assertEqual(theirs["pass_mark"], "50")
        # St Mary's administrator has no say on Grace's host.
        self.client.force_login(self.admin.user)
        self.assertEqual(
            self.client.put(SETTINGS, data={"pass_mark": "1"}, content_type="application/json", HTTP_HOST=THEIR_HOST).status_code,
            403,
        )
