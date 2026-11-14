"""The Ogun card and the year's summary: audit findings G-06 to G-09, and the
"left" of G-02.

Built on the report card fixtures: two schools, a whole session each. St Mary's
prints the Ogun State card (`OgunCardSetUp`); Grace Academy prints the Standard
one and is where anything that has to be done to a *second* school is done.

- **G-06** the promotion line is the principal's recorded decision, not a guess
  from where the child sits next session;
- **G-07** a subject with no paper named exactly "Exam" still prints its marks;
- **G-08** percentage, annual score and position come from one set of frozen
  figures, rounded one way;
- **G-09** the conduct settings and the template hold still while a class is
  waiting for release;
- **G-02 (left)** reissuing a first- or second-term card updates the year
  summary frozen on the third-term card, in the same transaction, logged.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts.models import Role
from gradebook.models import Score
from results import cards, ogun, ogun_card, ratings, revision, sessions
from results import services as chain
from results import unmarked
from results.models import (
    CardRevision,
    CardTemplate,
    ReleasedCard,
    ReleasedSessionResult,
    ReleasedTraitRating,
    ReportCardSettings,
    SheetState,
    Trait,
    TraitRating,
)
from results.tests.test_card_api import HOST, THEIR_HOST, ReportCardApiSetUp
from results.tests.test_conduct_settings import AFFECTIVE, PSYCHOMOTOR, URL, ConductSetUp
from results.tests.test_ogun_card import OgunCardSetUp
from schools.tests.tenants import connected_to

FIRST, SECOND, THIRD = (name.value for name in (TermName.FIRST, TermName.SECOND, TermName.THIRD))
SESSION = "2025/2026"
TEMPLATE = "/api/academics/card/template/"


def subjects_of(sheet):
    return {s["name"]: s for g in sheet["groups"] for s in g["subjects"]}


# ---------------------------------------------------------------------------
# G-06: the promotion line
# ---------------------------------------------------------------------------


class ThePromotionLineIsTheDecisionTests(OgunCardSetUp):
    def setUp(self):
        super().setUp()
        self.ogun_papers(THIRD, self.ada, "maths", 9, 9, 9, 63)
        self.release(term_name=THIRD)
        with connected_to(self.stmarys):
            self.next_first = Term.objects.create(
                session="2026/2027", name=TermName.FIRST,
                starts_on=date(2026, 9, 14), ends_on=date(2026, 12, 11),
            )
            self.jss1b = ClassGroup.objects.create(name="JSS 1B", level=1)
            self.jss2a = ClassGroup.objects.create(name="JSS 2A", level=2)

    def place_next(self, group):
        with connected_to(self.stmarys):
            ClassPlacement.objects.filter(term=self.next_first, student_membership_id=self.ada.pk).delete()
            ClassPlacement.objects.create(
                class_group=group, term=self.next_first, student_membership_id=self.ada.pk
            )

    def decide(self, status, school=None, child=None, by=None):
        with connected_to(school or self.stmarys):
            sessions.decide(child or self.ada, SESSION, status, note="Decided", by=by or self.principal)

    def line(self):
        return self.payload(THIRD)["ogun"]["promotion"]

    def test_where_the_child_sits_next_session_says_nothing(self):
        """Each of these used to print a line no principal had decided."""
        for group, was in (
            (self.jss2a, "Promoted to JSS 2A"),
            (self.jss1b, "Promoted to JSS 1B"),  # repeating in the other arm
            (ClassGroup(pk=self.group_id), "Not promoted, to repeat JSS 1A"),
        ):
            with self.subTest(was=was):
                self.place_next(group)
                self.assertIsNone(self.line())

    def test_the_line_is_what_the_principal_decided(self):
        for status, line in (
            ("promoted", "Promoted"),
            ("on_trial", "Promoted on trial"),
            ("repeated", "Not promoted, to repeat JSS 1A"),
            ("graduated", "Graduated"),
            ("withdrawn", "Withdrawn"),
        ):
            with self.subTest(status=status):
                self.decide(status)
                self.assertEqual(self.line(), line)

    def test_a_child_repeating_in_another_arm_is_not_told_they_were_promoted(self):
        self.decide("repeated")
        self.place_next(self.jss1b)

        self.assertEqual(self.line(), "Not promoted, to repeat JSS 1A")

    def test_a_move_in_october_does_not_reword_last_sessions_card(self):
        self.decide("promoted")
        self.place_next(self.jss2a)
        before = self.line()

        self.place_next(ClassGroup(pk=self.group_id))

        self.assertEqual(self.line(), before)
        self.assertEqual(before, "Promoted")

    def test_the_standard_card_and_the_ogun_sheet_say_the_same_decision(self):
        self.decide("on_trial")
        body = self.payload(THIRD)

        self.assertEqual(body["promotion"]["status"], "on_trial")
        self.assertEqual(body["ogun"]["promotion"], body["promotion"]["status_label"])

    def test_no_line_on_another_terms_card(self):
        self.release()
        self.decide("promoted")

        self.assertIsNone(self.payload(FIRST)["ogun"]["promotion"])

    def test_another_schools_decision_is_not_this_childs(self):
        """Grace's child may share Ada's membership-less id space; the decision
        is in Grace's own schema and never reaches St Mary's card."""
        self.decide("repeated", school=self.grace, child=self.ngozi, by=self.their_principal)

        self.assertIsNone(self.line())


# ---------------------------------------------------------------------------
# G-07 and G-08: the subject grid and the summary
# ---------------------------------------------------------------------------


class ASubjectWithNoPaperNamedExamTests(OgunCardSetUp):
    def test_it_prints_its_marks_and_is_counted(self):
        """The audit's case: papers "CA" (40) and "Examination" (60), all marked."""
        self._mark(self.stmarys, SECOND, self.ada, "english", "CA", 30, out_of=40)
        self._mark(self.stmarys, SECOND, self.ada, "english", "Examination", 45, out_of=60)
        self.ogun_papers(SECOND, self.ada, "maths", 8, 9, 7, 61)
        self.release(term_name=SECOND)

        sheet = self.payload(SECOND)["ogun"]
        english, maths = (subjects_of(sheet)[n] for n in ("English", "Mathematics"))

        self.assertEqual(english["weighted"], "75")
        # The split the sheet cannot make is left blank, not guessed.
        self.assertEqual((english["ca"], english["exam"]), (None, None))
        self.assertEqual((maths["ca"], maths["exam"], maths["weighted"]), (24, 61, "85"))
        self.assertEqual(sheet["summary"]["left_out"], 0)
        self.assertEqual((sheet["summary"]["obtainable"], sheet["summary"]["obtained"]), (200, 160))
        self.assertEqual(sheet["summary"]["percentage"], "80")
        # The labels come from the subjects that have the split.
        self.assertEqual((sheet["ca_out_of"], sheet["exam_out_of"]), (30, 70))

    def test_a_whole_school_of_kept_papers_is_not_a_column_of_dashes(self):
        """The first term's papers were kept when Ogun was chosen: one "Exam"
        out of 100 each, and nothing else. Every subject used to print "-"."""
        self.release()

        sheet = self.payload(FIRST)["ogun"]
        by_name = subjects_of(sheet)

        self.assertEqual((by_name["Mathematics"]["weighted"], by_name["English"]["weighted"]), ("88", "74"))
        self.assertEqual(sheet["summary"]["left_out"], 0)
        self.assertEqual(sheet["summary"]["percentage"], "81")

    def test_a_subject_with_a_paper_unmarked_still_waits(self):
        """The control: the rule that was kept. An unmarked paper is not nought."""
        self._mark(self.stmarys, SECOND, self.ada, "english", "CA", 30, out_of=40)
        self._mark(self.stmarys, SECOND, self.bola, "english", "Examination", 45, out_of=60)
        self.ogun_papers(SECOND, self.ada, "maths", 8, 9, 7, 61)
        self.release(term_name=SECOND)

        sheet = self.payload(SECOND)["ogun"]

        self.assertIsNone(subjects_of(sheet)["English"]["weighted"])
        self.assertEqual(sheet["summary"]["left_out"], 1)
        self.assertEqual((sheet["summary"]["obtainable"], sheet["summary"]["obtained"]), (100, 85))


class OneSetOfFrozenFiguresTests(OgunCardSetUp):
    def test_the_percentage_is_the_average_the_position_is_ranked_on(self):
        """Subjects out of different totals: the two sums divided are 83.33,
        the card's own average is 70, and the position is ranked on 70."""
        self.ogun_papers(SECOND, self.ada, "maths", 9, 9, 9, 63)
        self._mark(self.stmarys, SECOND, self.ada, "english", "Project", 10, out_of=20)
        self.release(term_name=SECOND)

        body = self.payload(SECOND)
        summary = body["ogun"]["summary"]
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk, term__name=SECOND)

        self.assertEqual((summary["obtainable"], summary["obtained"]), (120, 100))
        self.assertEqual(card.own_average, Decimal("70.00"))
        self.assertEqual(summary["percentage"], "70")
        self.assertEqual(Decimal(body["own_average"]), Decimal(summary["percentage"]))

    def test_the_annual_score_rounds_half_up_like_every_other_percentage(self):
        """70.02 and 70.03 are 70.025: 70.03 by the house rule, 70.02 half-even."""
        equal = {name: Decimal(1) for name in (FIRST, SECOND, THIRD)}

        self.assertEqual(
            ogun_card._annual(
                {FIRST: Decimal("70.02"), SECOND: Decimal("70.03"), THIRD: None}, equal
            ),
            Decimal("70.03"),
        )
        self.assertEqual(
            ogun_card._annual({FIRST: Decimal("70.12"), SECOND: Decimal("70.13"), THIRD: None}, equal),
            Decimal("70.13"),
        )
        self.assertIsNone(ogun_card._annual({FIRST: None, SECOND: None, THIRD: None}, equal))

    def _a_year(self):
        # First term: the fixture's marks (Ada: Mathematics 88, English 74).
        self.release()
        self.ogun_papers(SECOND, self.ada, "maths", 7, 7, 6, 50)
        self.release(term_name=SECOND)
        self.ogun_papers(THIRD, self.ada, "maths", 9, 9, 9, 63)
        self.ogun_papers(THIRD, self.ada, "english", 8, 8, 8, 56)

    def test_the_annual_score_uses_the_weighting_frozen_on_the_card(self):
        self._a_year()
        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 20, 60)
        self.release(term_name=THIRD)

        by_name = subjects_of(self.payload(THIRD)["ogun"])

        # 0.2 x 88 + 0.2 x 70 + 0.6 x 90, and English over the two terms it has.
        self.assertEqual(by_name["Mathematics"]["annual"], "85.6")
        self.assertEqual(by_name["English"]["annual"], "78.5")
        with connected_to(self.stmarys):
            frozen = ReleasedSessionResult.objects.get(student_membership_id=self.ada.pk)
        # The same weights the year's average on this card was made with:
        # terms 81, 70 and 85 at 20/20/60.
        self.assertEqual(frozen.session_average, Decimal("81.20"))
        self.assertEqual(
            (frozen.first_weight_used, frozen.second_weight_used, frozen.third_weight_used),
            (Decimal("20.00"), Decimal("20.00"), Decimal("60.00")),
        )

    def test_changing_the_weighting_afterwards_does_not_move_a_released_card(self):
        self._a_year()
        self.release(term_name=THIRD)
        before = subjects_of(self.payload(THIRD)["ogun"])["Mathematics"]["annual"]

        with connected_to(self.stmarys):
            sessions.use_a_weighting(0, 0, 100)

        self.assertEqual(before, "82.67")
        self.assertEqual(subjects_of(self.payload(THIRD)["ogun"])["Mathematics"]["annual"], before)

    def test_a_term_the_year_did_not_count_is_not_in_the_annual_score(self):
        """Second term never released: the year's line leaves it out, and so
        does each subject's annual score, with the term's column a dash."""
        self.release()
        self.ogun_papers(SECOND, self.ada, "maths", 7, 7, 6, 50)
        self.ogun_papers(THIRD, self.ada, "maths", 9, 9, 9, 63)
        self.release(term_name=THIRD)

        maths = subjects_of(self.payload(THIRD)["ogun"])["Mathematics"]

        self.assertEqual([maths[k] for k in ("first", "second", "third", "annual")], ["88", None, "90", "89"])

    def test_an_earlier_term_released_late_does_not_reword_the_third_term_card(self):
        """The year was frozen without it; the card says what it said."""
        self.ogun_papers(SECOND, self.ada, "maths", 7, 7, 6, 50)
        self.ogun_papers(THIRD, self.ada, "maths", 9, 9, 9, 63)
        self.release(term_name=THIRD)
        before = subjects_of(self.payload(THIRD)["ogun"])["Mathematics"]

        self.release(term_name=SECOND)

        after = subjects_of(self.payload(THIRD)["ogun"])["Mathematics"]
        self.assertEqual(before, after)
        self.assertIsNone(after["second"])


# ---------------------------------------------------------------------------
# G-09: the settings hold still while a class is waiting for release
# ---------------------------------------------------------------------------


class SettingsHoldStillInTheChainTests(ConductSetUp):
    """Grace Academy: both sections on, every trait rated, its class walked
    part of the way. St Mary's is the school that must not be held by it."""

    def setUp(self):
        super().setUp()
        self.switch(self.grace, self.their_principal, **{AFFECTIVE: True, PSYCHOMOTOR: True})
        self.rate_everything(self.grace)
        with connected_to(self.grace):
            self.sheet = chain.open_sheet(
                self.group_of(self.grace), self.term_of(self.grace, FIRST), self.their_principal
            )

    def walk(self, *steps):
        people = self.their_staff
        with connected_to(self.grace):
            count = unmarked.count(self.sheet.class_group, self.sheet.term)
            acts = {
                "submit": lambda: chain.submit(self.sheet, people[Role.TEACHER], unmarked=count),
                "check": lambda: chain.check(self.sheet, people[Role.VICE_PRINCIPAL_ACADEMIC], unmarked=count),
                "approve": lambda: chain.approve(self.sheet, people[Role.PRINCIPAL], unmarked=count),
                "release": lambda: chain.release(self.sheet, people[Role.PRINCIPAL]),
                "send_back": lambda: chain.send_back(self.sheet, people[Role.PRINCIPAL], reason="Look again"),
            }
            for step in steps:
                acts[step]()

    def settings(self):
        """Everything the conduct settings and the template decide, as one value."""
        with connected_to(self.grace):
            row = ReportCardSettings.objects.get(pk=1)
            return (
                ratings.enabled_groups(),
                [(t.group, t.name, t.is_hidden, t.position) for t in Trait.objects.order_by("pk")],
                ratings.scale_labels(),
                row.template,
                row.show_position,
            )

    def changes(self):
        trait = self.trait(self.grace, AFFECTIVE)
        with connected_to(self.grace):
            order = [t.pk for t in Trait.objects.in_group(AFFECTIVE).visible()][::-1]
        return (
            ("switch a section off", "put", f"{URL}{AFFECTIVE}/enabled/", {"enabled": False}),
            ("add a trait", "post", f"{URL}{AFFECTIVE}/traits/", {"name": "Kindness"}),
            ("rename a trait", "put", f"{URL}traits/{trait.pk}/", {"name": "Renamed"}),
            ("hide a trait", "put", f"{URL}traits/{trait.pk}/", {"hidden": True}),
            ("reorder the traits", "put", f"{URL}{AFFECTIVE}/order/", {"trait_ids": order}),
            ("reword the scale", "put", f"{URL}scale/5/", {"label": "Superb"}),
            ("choose the Ogun card", "put", TEMPLATE, {"template": "ogun"}),
            ("choose the Standard card again", "put", TEMPLATE, {"template": "standard"}),
        )

    def test_submitted_checked_and_approved_each_refuse_every_change(self):
        for step, state in (("submit", "submitted"), ("check", "checked"), ("approve", "approved")):
            self.walk(step)
            before = self.settings()
            for what, method, path, body in self.changes():
                with self.subTest(state=state, what=what):
                    response = self.send(method, path, self.their_principal, body, host=THEIR_HOST)
                    self.assertEqual(response.status_code, 422, response.content)
                    detail = response.json()["detail"]
                    self.assertIn("JSS 1A's results for", detail)
                    self.assertIn("Release them or send them back first", detail)
                    self.assertEqual(self.settings(), before)

    def test_what_is_released_is_what_was_approved(self):
        """The audit's reproduction: ratings entered, the class approved, then
        the Ogun template chosen. The released section used to be the sheet's
        own list, with the lines just added printed blank."""
        self.walk("submit", "check", "approve")
        with connected_to(self.grace):
            approved = [(t.group, t.name) for t in ratings.traits().filter(group__in=ratings.enabled_groups())]

        response = self.send("put", TEMPLATE, self.their_principal, {"template": "ogun"}, host=THEIR_HOST)
        self.assertEqual(response.status_code, 422)
        self.walk("release")

        with connected_to(self.grace):
            released = list(
                ReleasedTraitRating.objects.filter(student_membership_id=self.ngozi.pk)
                .order_by("pk")
                .values_list("group", "trait_name", "score")
            )
            card = ReleasedCard.objects.get(student_membership_id=self.ngozi.pk)
        self.assertEqual([(g, n) for g, n, _ in released], approved)
        self.assertTrue(all(score == 5 for _, _, score in released), released)
        self.assertEqual(card.template, CardTemplate.STANDARD)

    def test_the_service_refuses_without_the_routes(self):
        self.walk("submit")
        trait = self.trait(self.grace, AFFECTIVE)
        who = self.their_principal
        with connected_to(self.grace):
            for act in (
                lambda: ratings.set_group_enabled_as(who, AFFECTIVE, False),
                lambda: ratings.add_trait_as(who, AFFECTIVE, "Kindness"),
                lambda: ratings.rename_trait_as(who, trait, "Renamed"),
                lambda: ratings.set_trait_hidden_as(who, trait, True),
                lambda: ratings.reorder_as(who, AFFECTIVE, [trait.pk]),
                lambda: ratings.set_scale_label_as(who, 5, "Superb"),
            ):
                with self.assertRaises(ratings.ClassesAwaitingRelease):
                    act()
            with self.assertRaises(ogun.TemplateRefused):
                ogun.set_template_as(who, self.grace, "ogun")

    def test_draft_sent_back_and_released_leave_the_settings_free(self):
        path, body = f"{URL}scale/5/", {"label": "Superb"}
        # Draft: the sheet is open and nothing is with a signatory.
        self.assertEqual(self.send("put", path, self.their_principal, body, host=THEIR_HOST).status_code, 200)
        self.walk("submit")
        self.assertEqual(self.send("put", path, self.their_principal, {"label": "Top"}, host=THEIR_HOST).status_code, 422)
        self.walk("send_back")
        self.assertEqual(self.send("put", path, self.their_principal, {"label": "Top"}, host=THEIR_HOST).status_code, 200)
        self.walk("submit", "check", "approve", "release")
        response = self.send("put", TEMPLATE, self.their_principal, {"template": "ogun"}, host=THEIR_HOST)
        self.assertEqual(response.status_code, 200, response.content)

    def test_one_schools_class_in_the_chain_holds_nothing_at_the_other(self):
        self.walk("submit")

        response = self.send("put", f"{URL}scale/5/", self.principal, {"label": "Superb"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.send("put", TEMPLATE, self.principal, {"template": "ogun"}).status_code, 200
        )
        with connected_to(self.grace):
            self.assertNotEqual(ratings.scale_labels()[5], "Superb")
            self.assertEqual(ReportCardSettings.objects.get(pk=1).template, CardTemplate.STANDARD)

    def test_an_earlier_terms_class_in_the_chain_holds_them_too(self):
        """The settings are the school's, and release freezes them whichever
        term the class is of."""
        with connected_to(self.grace):
            Term.objects.filter(pk=self.their_terms[SECOND]).update(is_current=True)
        self.walk("submit")

        response = self.send("put", f"{URL}scale/5/", self.their_principal, {"label": "Superb"}, host=THEIR_HOST)

        self.assertEqual(response.status_code, 422)


# ---------------------------------------------------------------------------
# G-02 (left): a revised earlier card updates the year on the third-term card
# ---------------------------------------------------------------------------


class TheYearFollowsARevisedCardTests(ReportCardApiSetUp):
    """Grace Academy, three terms released: Ngozi's Mathematics 90, 60 and 75.

    The earlier card's figure is moved the only way it can move today: a live
    mark changed underneath a released term. The marks lock refuses that in the
    service; the database's own refusal keys off frozen ratings, and Grace
    prints no conduct section, so a direct write gets through. It stands in for
    any correction that reaches an earlier card: what is under test is what a
    reissue of that card then does to the year.
    """

    def setUp(self):
        super().setUp()
        self._mark(self.grace, SECOND, self.ngozi, "maths", "Exam", 60)
        self._mark(self.grace, THIRD, self.ngozi, "maths", "Exam", 75)
        for term in (FIRST, SECOND, THIRD):
            self.release(self.grace, term)
        # St Mary's has a whole year too, and nothing below may touch it.
        self._mark(self.stmarys, SECOND, self.ada, "maths", "Exam", 50)
        self._mark(self.stmarys, THIRD, self.ada, "maths", "Exam", 50)
        for term in (FIRST, SECOND, THIRD):
            self.release(self.stmarys, term)

    def move_the_mark(self, term_name, value, school=None, child=None):
        school = school or self.grace
        with connected_to(school):
            Score.objects.filter(
                assessment__term=self.term_of(school, term_name),
                student_membership_id=(child or self.ngozi).pk,
            ).update(value=value)

    def revise(self, term_name, reason="The first term's mark was entered wrongly"):
        with connected_to(self.grace):
            return revision.revise(
                self.ngozi, self.term_of(self.grace, term_name), self.their_principal, reason
            )

    def year(self, school=None, child=None):
        with connected_to(school or self.grace):
            row = sessions.released_session_line(child or self.ngozi, SESSION)
            return row.first_average, row.second_average, row.third_average, row.session_average

    def versions(self, term_name, school=None, child=None):
        school = school or self.grace
        with connected_to(school):
            return list(
                ReleasedCard.objects.filter(
                    student_membership_id=(child or self.ngozi).pk, term=self.term_of(school, term_name)
                )
                .order_by("version")
                .values_list("version", flat=True)
            )

    def test_the_control_the_year_was_frozen_from_the_cards(self):
        self.assertEqual(
            self.year(), (Decimal("90.00"), Decimal("60.00"), Decimal("75.00"), Decimal("75.00"))
        )

    def test_a_revised_first_term_card_updates_the_year_on_the_third_term_card(self):
        self.move_the_mark(FIRST, 60)

        card = self.revise(FIRST)

        self.assertEqual((card.version, card.own_average), (2, Decimal("60.00")))
        self.assertEqual(self.versions(THIRD), [1, 2])
        self.assertEqual(
            self.year(), (Decimal("60.00"), Decimal("60.00"), Decimal("75.00"), Decimal("65.00"))
        )
        # And it is what the family is served on the third-term card.
        body = self.fetch(self.their_principal, self.grace, self.ngozi, THIRD).json()
        self.assertEqual(
            (body["session_line"]["first_average"], body["session_line"]["session_average"]),
            ("60.00", "65.00"),
        )
        self.assertEqual(body["version"], 2)

    def test_a_revised_second_term_card_does_too(self):
        self.move_the_mark(SECOND, 90)

        self.revise(SECOND, reason="Second term script re-marked")

        self.assertEqual(
            self.year(), (Decimal("90.00"), Decimal("90.00"), Decimal("75.00"), Decimal("85.00"))
        )

    def test_it_is_logged_as_a_revision_of_the_third_term_card_naming_the_cause(self):
        self.move_the_mark(FIRST, 60)

        self.revise(FIRST, reason="Script re-marked on appeal")

        with connected_to(self.grace):
            third = cards.card_for(self.ngozi, self.term_of(self.grace, THIRD))
            first = cards.card_for(self.ngozi, self.term_of(self.grace, FIRST))
            log = CardRevision.objects.get(card=third)
            own = CardRevision.objects.get(card=first)
        self.assertEqual(log.previous_card.version, 1)
        self.assertEqual(log.revised_by_id, self.their_principal.pk)
        self.assertIn("first term card was revised", log.reason)
        self.assertIn("Script re-marked on appeal", log.reason)
        self.assertEqual(own.reason, "Script re-marked on appeal")
        self.assertTrue(third.is_revised)

    def test_a_reissue_that_moves_no_figure_leaves_the_third_term_card_alone(self):
        """A name corrected on the first-term card: the year says what it said,
        so the third-term card is not reissued and grows no "Revised" mark."""
        from accounts.models import Membership

        Membership.objects.filter(pk=self.ngozi.pk).update(display_name="Ngozi Adeyemi")

        card = self.revise(FIRST, reason="Surname corrected")

        self.assertEqual((card.version, card.student_name), (2, "Ngozi Adeyemi"))
        self.assertEqual(self.versions(THIRD), [1])
        with connected_to(self.grace):
            self.assertEqual(CardRevision.objects.count(), 1)

    def test_both_cards_or_neither(self):
        """One transaction: if the third-term card cannot be written, the
        first-term card is not reissued either."""
        self.move_the_mark(FIRST, 60)
        real = revision._reissue

        def fail_on_the_third(student_id, term, *args, **kwargs):
            if term.name == THIRD:
                raise RuntimeError("the third-term card could not be written")
            return real(student_id, term, *args, **kwargs)

        with mock.patch.object(revision, "_reissue", side_effect=fail_on_the_third):
            with self.assertRaises(RuntimeError):
                self.revise(FIRST)

        self.assertEqual(self.versions(FIRST), [1])
        self.assertEqual(self.versions(THIRD), [1])
        self.assertEqual(self.year()[0], Decimal("90.00"))
        with connected_to(self.grace):
            self.assertEqual(CardRevision.objects.count(), 0)

    def test_if_the_third_term_card_cannot_follow_nothing_is_changed_and_it_says_why(self):
        self.move_the_mark(FIRST, 60)
        with connected_to(self.grace):
            ClassPlacement.objects.filter(
                term=self.term_of(self.grace, THIRD), student_membership_id=self.ngozi.pk
            ).delete()

        with self.assertRaises(revision.TheYearsSummaryCannotFollow) as refused:
            self.revise(FIRST)

        self.assertIn("year's summary", str(refused.exception))
        self.assertIn("Nothing was changed", str(refused.exception))
        self.assertEqual(self.versions(FIRST), [1])
        self.assertEqual(self.versions(THIRD), [1])

    def test_revising_the_third_term_card_itself_is_one_new_version(self):
        self.move_the_mark(THIRD, 90)

        self.revise(THIRD, reason="Third term script re-marked")

        self.assertEqual(self.versions(THIRD), [1, 2])
        self.assertEqual(self.year()[2:], (Decimal("90.00"), Decimal("80.00")))
        with connected_to(self.grace):
            self.assertEqual(CardRevision.objects.count(), 1)

    def test_with_no_third_term_card_there_is_no_year_to_update(self):
        """A child with no third-term card has no frozen year, and a reissue of
        their first-term card reissues nothing else."""
        kemi = self._child(self.grace, "kemi", "Kemi Bello")
        with connected_to(self.grace):
            # Placed in every term after they were released: no card anywhere.
            card = revision.revise(kemi, self.term_of(self.grace, FIRST), self.their_principal, "Placed late")
            self.assertEqual(card.version, 1)
            self.assertIsNone(sessions.released_session_line(kemi, SESSION))
            self.assertEqual(CardRevision.objects.count(), 1)

    def test_a_card_given_late_for_an_earlier_term_enters_the_year(self):
        """A child whose first-term card did not exist when the year was frozen
        (issue #31's case), given one afterwards: the year's line said "not
        released" for that term and now carries the card."""
        kemi = self._child(self.grace, "kemi", "Kemi Bello")
        with connected_to(self.grace):
            for term in (SECOND, THIRD):
                revision.revise(kemi, self.term_of(self.grace, term), self.their_principal, "Placed late")
            frozen = sessions.released_session_line(kemi, SESSION)
            self.assertEqual(frozen.first_absence, "not_released")
            versions_before = list(
                ReleasedCard.objects.filter(student_membership_id=kemi.pk, term=self.term_of(self.grace, THIRD))
                .values_list("version", flat=True)
            )

            revision.revise(kemi, self.term_of(self.grace, FIRST), self.their_principal, "Placed late")

            after = sessions.released_session_line(kemi, SESSION)
            versions_after = sorted(
                ReleasedCard.objects.filter(student_membership_id=kemi.pk, term=self.term_of(self.grace, THIRD))
                .values_list("version", flat=True)
            )
        self.assertEqual(versions_before, [1])
        self.assertEqual(versions_after, [1, 2])
        # She has no marks, so the card carries no average: the reason changes.
        self.assertEqual(after.first_absence, "unmarked")

    def test_the_other_schools_cards_and_year_are_untouched(self):
        before = (
            self.versions(FIRST, self.stmarys, self.ada),
            self.versions(THIRD, self.stmarys, self.ada),
            self.year(self.stmarys, self.ada),
        )
        self.move_the_mark(FIRST, 60)

        self.revise(FIRST)

        self.assertEqual(
            (
                self.versions(FIRST, self.stmarys, self.ada),
                self.versions(THIRD, self.stmarys, self.ada),
                self.year(self.stmarys, self.ada),
            ),
            before,
        )
        with connected_to(self.stmarys):
            self.assertEqual(CardRevision.objects.count(), 0)

    def test_an_earlier_card_is_read_as_it_stood_when_the_later_card_was_issued(self):
        """`cards.card_as_of()`: what the Ogun sheet's 1st and 2nd term scores
        read through. A reissue that moves no average leaves the third-term
        card at version 1, and that card goes on quoting the version it was
        issued beside."""
        from accounts.models import Membership

        Membership.objects.filter(pk=self.ngozi.pk).update(display_name="Ngozi Adeyemi")
        self.revise(FIRST, reason="Surname corrected")

        with connected_to(self.grace):
            first_term = self.term_of(self.grace, FIRST)
            third = cards.card_for(self.ngozi, self.term_of(self.grace, THIRD))
            then = cards.card_as_of(self.ngozi, first_term, third.created_at)
            now = cards.card_for(self.ngozi, first_term)
            before_anything = cards.card_as_of(
                self.ngozi, first_term, third.created_at.replace(year=2000)
            )
        self.assertEqual((then.version, now.version), (1, 2))
        self.assertIsNone(before_anything)
