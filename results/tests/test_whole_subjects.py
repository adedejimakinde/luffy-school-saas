"""A subject with a paper unmarked has no total, and its child is not ranked.

`results.positions` ("A subject with a paper unmarked"), frozen by
`results.cards`, served by `card_api`, read by the broadsheet. Two schools in
every class: St Mary's prints the Ogun State card and Grace the Standard one, each
with a child whose last paper in Mathematics is not yet marked, so what one
school's marks do to the other is a thing that could be asserted.

The cast, in each school (a paper named in brackets is the one missing):

| | Mathematics | English | |
| --- | --- | --- | --- |
| Ada / Ngozi | whole | whole | the best of those whole |
| Bola / Kemi | whole | whole | the other child who is whole |
| Dayo / Femi | (2nd Test) | whole | the highest marks of the three, so the old rule ranked them 1st |

The rule is the same on both cards, so most classes below walk both schools.
"""

from decimal import Decimal
from unittest import mock

from academics.models import TermName
from accounts.models import Role
from gradebook.models import Assessment, Score
from results import cards, grades, look, ogun, pdf, positions, ratings
from results.models import CardsAreFrozenAtRelease, ReleasedCard, ReleasedSubjectResult, TraitGroup
from results.tests.test_card_api import HOST, THEIR_HOST, ReportCardApiSetUp
from results.tests.test_ogun_card import OgunCardSetUp
from schools.tests.tenants import connected_to

FIRST = TermName.FIRST.value

#: Paper, out of, per subject.
PAPERS = {
    "maths": (("1st Test", 10), ("2nd Test", 10), ("Exam", 100)),
    "english": (("1st Test", 10), ("Exam", 100)),
}


class TwoSchoolsOneMissingPaper(OgunCardSetUp):
    """St Mary's on the Ogun card, Grace on the Standard one, each with its cast."""

    def put(self, school, child, subject, paper, value):
        out_of = dict(PAPERS[subject])[paper]
        with connected_to(school):
            assessment, _ = Assessment.objects.get_or_create(
                term=self.term_of(school, FIRST),
                subject_id=self.subjects_of(school)[subject],
                name=paper,
                defaults={"max_score": out_of},
            )
            Score.objects.update_or_create(
                assessment=assessment, student_membership_id=child.pk, defaults={"value": value}
            )

    def mark(self, school, child, maths, english):
        """`maths` and `english` are `{paper: mark}`; a paper left out is not marked."""
        for subject, marks in (("maths", maths), ("english", english)):
            for paper, value in marks.items():
                self.put(school, child, subject, paper, value)

    def setUp(self):
        super().setUp()
        self.dayo = self._child(self.stmarys, "dayo", "Dayo Ade")
        self.mark(self.stmarys, self.ada, {"1st Test": 9, "2nd Test": 8}, {"1st Test": 8})
        self.mark(self.stmarys, self.bola, {"1st Test": 6, "2nd Test": 5}, {"1st Test": 5})
        self.mark(
            self.stmarys, self.dayo, {"1st Test": 9, "Exam": 95}, {"1st Test": 9, "Exam": 90}
        )

        self.kemi = self._child(self.grace, "kemi", "Kemi Bello")
        self.femi = self._child(self.grace, "femi", "Femi Adu")
        self.mark(self.grace, self.ngozi, {"1st Test": 9, "2nd Test": 8}, {"1st Test": 7, "Exam": 70})
        self.mark(self.grace, self.kemi, {"1st Test": 5, "2nd Test": 4, "Exam": 60}, {"1st Test": 4, "Exam": 50})
        self.mark(self.grace, self.femi, {"1st Test": 9, "Exam": 99}, {"1st Test": 9, "Exam": 92})
        with connected_to(self.grace):
            look.set_show_position_as(self.their_principal, self.grace, True)

    # -- reading ------------------------------------------------------------

    def card_of(self, school, child):
        """The family-facing payload, read as the principal (who may read any card)."""
        who = self.principal if school == self.stmarys else self.their_principal
        response = self.fetch(who, school, child)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def line(self, body, subject):
        return next(s for s in body["subjects"] if s["subject_name"].startswith(subject))

    def schools(self):
        """`(school, [whole best, whole other, the one with a paper missing])`."""
        return (
            (self.stmarys, [self.ada, self.bola, self.dayo]),
            (self.grace, [self.ngozi, self.kemi, self.femi]),
        )

    def release_both(self):
        self.release(self.stmarys)
        self.release(self.grace)

    def broadsheet(self, school, who=None):
        group = self.group_id if school == self.stmarys else self.their_group_id
        term = self.terms_of(school)[FIRST]
        self.client.force_login(who or (self.principal if school == self.stmarys else self.their_principal))
        response = self.client.get(
            f"/api/results/classes/{group}/broadsheet/?term_id={term}",
            HTTP_HOST=HOST if school == self.stmarys else THEIR_HOST,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def row(self, sheet, child):
        return next(r for r in sheet["rows"] if r["student_membership_id"] == child.pk)


class AMissingPaperLeavesTheSubjectWithoutATotalTests(TwoSchoolsOneMissingPaper):
    """Rule 3. The family's card shows "-" for that subject's total, and leaves it
    out of the summary (marks obtained, percentage) and the average."""

    def test_the_control_the_papers_that_are_in_still_show_and_the_other_subject_is_whole(self):
        self.release_both()
        for school, (_, _, short) in ((s, c) for s, c in self.schools()):
            with self.subTest(school=school.slug):
                body = self.card_of(school, short)
                maths = self.line(body, "Mathematics")
                shown = {c["assessment_name"]: c["score"] for c in maths["assessments"]}
                self.assertEqual(shown["1st Test"], 9)
                self.assertIsNone(shown["2nd Test"], "an unmarked paper is not a nought")
                self.assertTrue(self.line(body, "English")["is_complete"])

    def test_the_subject_has_no_total_percentage_or_grade_on_either_card(self):
        self.release_both()
        for school, (_, _, short) in self.schools():
            with self.subTest(school=school.slug):
                maths = self.line(self.card_of(school, short), "Mathematics")
                self.assertFalse(maths["is_complete"])
                self.assertEqual(
                    (maths["total_scored"], maths["total_available"], maths["percentage"]),
                    (None, None, None),
                )
                self.assertEqual((maths["grade_letter"], maths["grade_remark"]), ("", ""))

    def test_the_summary_and_average_count_the_whole_subjects_only(self):
        self.release_both()

        dayo = self.card_of(self.stmarys, self.dayo)

        # English alone: 9 + 90 out of 10 + 100.
        self.assertEqual((dayo["total_scored"], dayo["total_available"]), (99, 110))
        self.assertEqual((dayo["percentage"], dayo["own_average"]), ("90.00", "90.00"))
        self.assertEqual(dayo["left_out"], 1)
        # A child whole in both is summed over both, with nothing left out.
        ada = self.card_of(self.stmarys, self.ada)
        self.assertEqual((ada["total_scored"], ada["total_available"], ada["left_out"]), (187, 230, 0))
        self.assertEqual(ada["own_average"], "81.03")

    def test_the_standard_school_gets_the_same_rule(self):
        self.release_both()

        femi = self.card_of(self.grace, self.femi)

        # English alone: 9 + 92 out of 10 + 100.
        self.assertEqual((femi["total_scored"], femi["total_available"], femi["left_out"]), (101, 110, 1))
        self.assertIsNone(femi["ogun"], "Grace prints the Standard card")

    def test_the_standard_pdf_prints_the_dash_and_says_how_many_were_left_out(self):
        self.release_both()
        with connected_to(self.grace):
            html = pdf.html_for(ReleasedCard.objects.get(student_membership_id=self.femi.pk))
        self.assertIn("101 of 110 obtainable", html)
        self.assertIn("(1 subject not counted: a paper is not marked)", html)
        # Mathematics: "-" for the total and the percentage, and no grade.
        maths = html[html.index("Mathematics"):]
        maths = maths[: maths.index("</tr>")]
        self.assertEqual(maths.count('<span class="blank">-</span>'), 2 + 1, maths)

    def test_the_figures_staff_hold_are_kept_on_the_line_marked_incomplete(self):
        self.release_both()
        with connected_to(self.stmarys):
            line = ReleasedSubjectResult.objects.get(
                card__student_membership_id=self.dayo.pk, subject_name="Mathematics"
            )
            self.assertFalse(line.is_complete)
            # 9 + 95 out of 10 + 100: what is in, not a total.
            self.assertEqual((line.total_scored, line.total_available, line.percentage), (104, 110, Decimal("94.55")))
            self.assertEqual((line.grade_letter, line.subject_position), ("", None))


class OnTheOgunCardTests(TwoSchoolsOneMissingPaper):
    def sheet_of(self, child):
        return self.card_of(self.stmarys, child)["ogun"]

    def subject(self, sheet, name):
        return next(s for g in sheet["groups"] for s in g["subjects"] if s["name"] == name)

    def test_a_half_with_a_paper_unmarked_is_a_dash_and_the_weighted_average_too(self):
        self.release_both()

        maths = self.subject(self.sheet_of(self.dayo), "Mathematics")

        # 1st Test is in (9), 2nd Test is not: the CA is not 9 out of 20.
        self.assertIsNone(maths["ca"])
        self.assertEqual(maths["exam"], 95)
        self.assertIsNone(maths["weighted"])

    def test_the_summary_leaves_the_subject_out_and_says_so(self):
        self.release_both()

        summary = self.sheet_of(self.dayo)["summary"]

        self.assertEqual(
            (summary["obtainable"], summary["obtained"], summary["percentage"], summary["left_out"]),
            (110, 99, "90", 1),
        )

    def test_the_ogun_pdf_prints_the_dashes(self):
        self.release_both()
        with connected_to(self.stmarys):
            html = pdf.html_for(ReleasedCard.objects.get(student_membership_id=self.dayo.pk))
        self.assertIn("Not counted: 1 subject with a paper not yet marked.", html)
        self.assertIn("not ranked", html)


class OnlyTheWholeAreRankedTests(TwoSchoolsOneMissingPaper):
    """Rule 4. Others show "not ranked"; "of N" counts the ranked; dense as before."""

    def places(self, school, children):
        return [self.card_of(school, child)["place_in_class"] for child in children]

    def test_the_old_rule_would_have_put_dayo_first_and_this_one_does_not_rank_them(self):
        # The control: on the marks so far, Dayo is ahead of both.
        with connected_to(self.stmarys):
            results = positions.class_results(self.group_of(self.stmarys), self.term_of(self.stmarys, FIRST))
        average = results.averages
        self.assertGreater(average[self.dayo.pk], average[self.ada.pk])
        self.assertNotIn(self.dayo.pk, results.positions)

    def test_ranks_are_among_the_whole_and_out_of_how_many_were_ranked(self):
        self.release_both()
        for school, (first, second, short) in self.schools():
            with self.subTest(school=school.slug):
                a, b, c = self.places(school, [first, second, short])
                self.assertEqual((a["place"], a["out_of"], a["label"]), (1, 2, "1st of 2"))
                self.assertEqual((b["place"], b["out_of"], b["label"]), (2, 2, "2nd of 2"))
                self.assertEqual((c["place"], c["out_of"], c["label"]), (None, 2, "not ranked"))

    def test_the_frozen_card_holds_no_position_and_the_ranked_count(self):
        self.release_both()
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.dayo.pk)
            self.assertTrue(card.whole_subjects_only)
            self.assertEqual((card.position, card.roster_size), (None, 2))

    def test_a_tie_among_the_ranked_is_dense_as_before(self):
        eze = self._child(self.stmarys, "eze", "Eze Obi")
        self.mark(self.stmarys, eze, {"1st Test": 9, "2nd Test": 8, "Exam": 88}, {"1st Test": 8, "Exam": 74})
        self.release(self.stmarys)

        places = {
            child.pk: self.card_of(self.stmarys, child)["place_in_class"]["label"]
            for child in (self.ada, eze, self.bola, self.dayo)
        }

        self.assertEqual(places[self.ada.pk], "1st of 3")
        self.assertEqual(places[eze.pk], "1st of 3")
        self.assertEqual(places[self.bola.pk], "2nd of 3", "dense: a tie does not take the place below")
        self.assertEqual(places[self.dayo.pk], "not ranked")

    def test_a_card_that_does_not_print_a_position_says_nothing_of_ranking(self):
        with connected_to(self.grace):
            look.set_show_position_as(self.their_principal, self.grace, False)
        self.release(self.grace)

        femi = self.card_of(self.grace, self.femi)

        self.assertIsNone(femi["place_in_class"])
        self.assertNotIn("not ranked", str(femi))

    def test_a_child_with_no_marks_at_all_is_not_ranked_either(self):
        nobody = self._child(self.stmarys, "nobody", "No Marks")
        self.release(self.stmarys)

        self.assertEqual(self.card_of(self.stmarys, nobody)["place_in_class"]["label"], "not ranked")

    def test_the_other_schools_papers_do_not_decide_this_ones(self):
        # Grace adds a paper to Mathematics that nobody there has marked.
        with connected_to(self.grace):
            Assessment.objects.create(
                term=self.term_of(self.grace, FIRST),
                subject_id=self.subjects_of(self.grace)["maths"],
                name="Project",
                max_score=20,
            )
        self.release(self.stmarys)
        self.release(self.grace)

        self.assertEqual([p["label"] for p in self.places(self.stmarys, [self.ada, self.bola, self.dayo])], ["1st of 2", "2nd of 2", "not ranked"])
        grace = self.places(self.grace, [self.ngozi, self.kemi, self.femi])
        self.assertEqual([p["label"] for p in grace], ["not ranked"] * 3, "nobody at Grace is whole in Mathematics now")
        self.assertEqual({p["out_of"] for p in grace}, {0})


class TheBroadsheetShowsThePartialFiguresAsIncompleteTests(TwoSchoolsOneMissingPaper):
    def check(self, school, first, second, short):
        sheet = self.broadsheet(school)
        self.assertEqual(sheet["ranked"], 2)
        top, other, partial = (self.row(sheet, c) for c in (first, second, short))
        self.assertEqual((top["current_rank"], other["current_rank"]), (1, 2))
        self.assertTrue(top["is_complete"] and other["is_complete"])
        # The staff see the figure over what is in, and that it is not whole.
        self.assertFalse(partial["is_complete"])
        self.assertIsNone(partial["current_rank"])
        self.assertIsNotNone(partial["average"])
        maths = next(s for s in partial["subjects"] if s["subject"] == "Mathematics")
        self.assertFalse(maths["is_complete"])
        self.assertIsNotNone(maths["percentage"])
        self.assertIsNone(maths["current_subject_rank"])
        english = next(s for s in partial["subjects"] if s["subject"] == "English")
        self.assertTrue(english["is_complete"])
        self.assertEqual(english["current_subject_rank"], 1, "ranked in a subject they are whole in")
        return sheet

    def test_live_marks_in_both_schools(self):
        for school, (first, second, short) in self.schools():
            with self.subTest(school=school.slug):
                self.assertFalse(self.broadsheet(school)["from_snapshot"])
                self.check(school, first, second, short)

    def test_the_released_term_says_the_same_from_the_cards(self):
        self.release_both()
        for school, (first, second, short) in self.schools():
            with self.subTest(school=school.slug):
                self.assertTrue(self.broadsheet(school)["from_snapshot"])
                self.check(school, first, second, short)

    def test_the_staff_average_and_the_class_average_are_what_they_were_live_and_released(self):
        live = self.broadsheet(self.stmarys)
        self.release(self.stmarys)
        released = self.broadsheet(self.stmarys)

        self.assertEqual(live["class_average"], released["class_average"])
        self.assertEqual(
            [self.row(live, c)["average"] for c in (self.ada, self.bola, self.dayo)],
            [self.row(released, c)["average"] for c in (self.ada, self.bola, self.dayo)],
        )
        # Dayo's: (94.55 + 90.00) / 2 over what is in, the same as before the rule.
        self.assertEqual(self.row(released, self.dayo)["average"], "92.28")

    def test_a_rank_in_a_subject_is_among_those_whole_in_it(self):
        sheet = self.broadsheet(self.stmarys)

        maths = {
            c.pk: next(s for s in self.row(sheet, c)["subjects"] if s["subject"] == "Mathematics")
            for c in (self.ada, self.bola, self.dayo)
        }

        self.assertEqual([maths[c.pk]["current_subject_rank"] for c in (self.ada, self.bola)], [1, 2])
        self.assertIsNone(maths[self.dayo.pk]["current_subject_rank"])

    def test_the_overview_still_counts_every_child_with_an_average(self):
        self.client.force_login(self.principal)
        term = self.terms_of(self.stmarys)[FIRST]
        body = self.client.get(f"/api/results/overview/?term_id={term}", HTTP_HOST=HOST).json()
        ours = next(c for c in body["classes"] if c["class_group"] == "JSS 1A")
        self.assertEqual(ours["children_with_an_average"], 3)


class _OldRulesResults:
    """A `positions.ClassResults` as it answered before the whole-subjects rule.

    `cards._card_for()` and `_subject_line()` below are the pre-rule functions
    verbatim; what they ask of `results` used to mean "everyone with an average
    is ranked" and "ranked in a subject among everyone marked in it", so this
    answers that way, over the same marks.
    """

    def __init__(self, results):
        self._r = results
        self.student_ids = results.student_ids
        self.subject_ids = results.subject_ids
        self.averages = results.averages
        self.positions = positions.dense_positions(results.averages)

    def scored_and_available(self, student_id, subject_id):
        return self._r.scored_and_available(student_id, subject_id)

    def percentage(self, student_id, subject_id):
        return self._r.percentage(student_id, subject_id)

    def subject_position(self, student_id, subject_id):
        return positions.dense_positions(
            {s: v for (s, sub), v in self._r.percentages.items() if sub == subject_id}
        ).get(student_id)


def _old_card_for(
    sheet, term, school_name, names, results, student_id, released_by_id,
    version=1, attendance=None, *, position_printed=False, rating_scale=None,
):
    """`results.cards._card_for` at f0b89d8 (before #283), verbatim."""
    results = _OldRulesResults(results)
    scored = available = 0
    for subject_id in results.subject_ids:
        subject_scored, subject_available = results.scored_and_available(student_id, subject_id)
        scored += subject_scored
        available += subject_available

    return ReleasedCard(
        sheet=sheet,
        student_membership_id=student_id,
        term=term,
        version=version,
        session=term.session,
        term_name=term.name,
        class_group=sheet.class_group,
        class_group_name=str(sheet.class_group),
        school_name=school_name,
        student_name=names.get(student_id, ""),
        total_scored=scored,
        total_available=available,
        own_average=results.averages.get(student_id),
        position=results.positions.get(student_id),
        roster_size=len(results.student_ids),
        position_printed=position_printed,
        rating_scale=rating_scale,
        days_present=attendance.present if attendance else None,
        days_absent=attendance.absent if attendance else None,
        days_open=attendance.open if attendance else None,
        released_by_id=released_by_id,
    )


def _old_subject_line(card, subject, position, results, student_id, bands):
    """`results.cards._subject_line` at f0b89d8 (before #283), verbatim."""
    results = _OldRulesResults(results)
    scored, available = results.scored_and_available(student_id, subject.pk)
    percentage = results.percentage(student_id, subject.pk)
    band = grades.grade_for(percentage, bands=bands)

    return ReleasedSubjectResult(
        card=card,
        subject=subject,
        subject_name=subject.name,
        subject_code=subject.code,
        position=position,
        total_scored=scored,
        total_available=available,
        percentage=percentage,
        grade_letter=band.letter if band else "",
        grade_remark=band.remark if band else "",
        subject_position=results.subject_position(student_id, subject.pk),
    )


class AReleasedCardIsNeverChangedTests(TwoSchoolsOneMissingPaper):
    """Rule 5. A card released before the rule keeps exactly what it printed.

    Written by freezing a card with the pre-rule `_card_for()` and
    `_subject_line()` (above), then reading it with the code as it is now. The
    same claim was also checked end to end, outside the suite, against real
    pre-#283 code: cards released by a checkout of f0b89d8 in two schools (one
    Standard, one Ogun, each with a paper unmarked), the same database migrated to
    this code, and all 40 cards, 4 broadsheets and 40 PDF pages read back: every
    one identical to what the old code served, but for the added fields.
    """

    def old_freeze(self, school):
        return mock.patch.multiple(cards, _card_for=_old_card_for, _subject_line=_old_subject_line)

    def release_the_old_way(self, school):
        with self.old_freeze(school):
            self.release(school)

    def rate_every_trait(self, school, child, score):
        teacher = self.staff_of(school)[Role.TEACHER]
        with connected_to(school):
            term = self.term_of(school, FIRST)
            for group in TraitGroup:
                ratings.set_group_enabled(group.value, True)
                for trait in ratings.traits(group.value):
                    ratings.rate(term, trait, child, score, by=teacher)

    def test_a_card_released_before_reads_exactly_as_it_was_frozen_totals_place_traits_and_key(self):
        """Both schools, every number written out. Nothing here is the new rule's."""
        self.rate_every_trait(self.stmarys, self.dayo, 4)
        self.rate_every_trait(self.grace, self.femi, 4)
        self.release_the_old_way(self.stmarys)
        self.release_the_old_way(self.grace)

        dayo = self.card_of(self.stmarys, self.dayo)
        femi = self.card_of(self.grace, self.femi)

        # St Mary's, the Ogun layout. Mathematics 9 + 95 of 10 + 100 (2nd Test unmarked), English 9 + 90.
        self.assertEqual((dayo["total_scored"], dayo["total_available"], dayo["percentage"]), (203, 220, "92.27"))
        self.assertEqual((dayo["own_average"], dayo["place_in_class"]["label"]), ("92.28", "1st of 3"))
        self.assertEqual(
            [(s["subject_name"], s["total_scored"], s["total_available"], s["percentage"]) for s in dayo["subjects"]],
            [("English", 99, 110, "90.00"), ("Mathematics", 104, 110, "94.55")],
        )
        self.assertEqual(
            [(sec["group"], [(t["trait_name"], t["score"]) for t in sec["traits"]]) for sec in dayo["sections"]],
            [
                ("affective", [(n, 4) for n in ogun.AFFECTIVE]),
                ("psychomotor", [(n, 4) for n in ogun.PSYCHOMOTOR]),
            ],
        )
        self.assertEqual(
            [(k["value"], k["label"]) for k in dayo["ogun"]["key"]],
            [(5, "Excellent"), (4, "Good"), (3, "Average"), (2, "Below Average"), (1, "Unsatisfactory")],
        )
        maths = next(s for g in dayo["ogun"]["groups"] for s in g["subjects"] if s["name"] == "Mathematics")
        self.assertEqual((maths["ca"], maths["exam"], maths["weighted"]), (9, 95, None))
        self.assertEqual(
            {k: dayo["ogun"]["summary"][k] for k in ("obtainable", "obtained", "percentage", "left_out")},
            {"obtainable": 110, "obtained": 99, "percentage": "90", "left_out": 1},
        )

        # Grace, the Standard layout. Mathematics 9 + 99 of 10 + 100, English 9 + 92.
        self.assertEqual((femi["total_scored"], femi["total_available"], femi["percentage"]), (209, 220, "95.00"))
        self.assertEqual((femi["own_average"], femi["place_in_class"]["label"]), ("95.00", "1st of 3"))
        self.assertEqual(
            [(s["subject_name"], s["total_scored"], s["percentage"], s["grade_letter"]) for s in femi["subjects"]],
            [("English", 101, "91.82", "A1"), ("Mathematics", 108, "98.18", "A1")],
        )
        self.assertEqual(
            [(sec["group"], len(sec["traits"]), {t["score"] for t in sec["traits"]}) for sec in femi["sections"]],
            [("affective", 7, {4}), ("psychomotor", 4, {4})],
        )
        self.assertEqual(femi["left_out"], 0)
        self.assertIsNone(femi["ogun"])

    def test_the_settings_changing_after_release_still_leaves_that_card_as_it_was(self):
        """The template, the trait list and the scale all move; the card does not."""
        self.rate_every_trait(self.grace, self.femi, 4)
        self.release_the_old_way(self.grace)
        before = self.card_of(self.grace, self.femi)

        with connected_to(self.grace):
            ogun.set_template_as(self.their_principal, self.grace, "ogun")
            ratings.set_scale_label(4, "Splendid")

        after = self.card_of(self.grace, self.femi)
        for key in ("total_scored", "total_available", "own_average", "percentage", "place_in_class", "sections", "subjects"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual({t["score_label"] for sec in after["sections"] for t in sec["traits"]}, {"Very Good"})

    def test_the_control_the_old_freeze_really_writes_an_unmarked_card(self):
        self.release_the_old_way(self.stmarys)
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.dayo.pk)
        self.assertEqual((card.whole_subjects_only, card.position, card.roster_size), (False, 1, 3))

    def test_a_standard_card_prints_the_partial_total_the_grade_and_the_place_it_did(self):
        self.release_the_old_way(self.grace)

        femi = self.card_of(self.grace, self.femi)

        maths = self.line(femi, "Mathematics")
        self.assertTrue(maths["is_complete"])
        self.assertIsNotNone(maths["total_scored"])
        self.assertIsNotNone(maths["percentage"])
        self.assertNotEqual(maths["grade_letter"], "")
        self.assertEqual(femi["left_out"], 0)
        self.assertEqual(femi["place_in_class"]["label"], "1st of 3")

    def test_an_ogun_card_keeps_its_partial_continuous_assessment(self):
        self.release_the_old_way(self.stmarys)

        maths = next(
            s for g in self.card_of(self.stmarys, self.dayo)["ogun"]["groups"] for s in g["subjects"] if s["name"] == "Mathematics"
        )

        self.assertEqual(maths["ca"], 9, "the old card summed the papers that were in")

    def test_a_card_with_no_marks_prints_no_position_not_not_ranked(self):
        nobody = self._child(self.grace, "nobody2", "No Marks")
        self.release_the_old_way(self.grace)

        self.assertIsNone(self.card_of(self.grace, nobody)["place_in_class"])

    def test_the_old_released_term_ranks_everybody_with_an_average_on_the_broadsheet(self):
        self.release_the_old_way(self.stmarys)

        sheet = self.broadsheet(self.stmarys)

        self.assertEqual(
            [self.row(sheet, c)["current_rank"] for c in (self.dayo, self.ada, self.bola)], [1, 2, 3]
        )
        self.assertTrue(all(r["is_complete"] for r in sheet["rows"]))
        self.assertEqual(sheet["ranked"], 3)
        self.assertEqual(self.row(sheet, self.dayo)["average"], "92.28")

    def test_the_new_rule_leaves_the_other_school_s_old_cards_alone(self):
        self.release_the_old_way(self.grace)
        self.release(self.stmarys)

        self.assertEqual(self.card_of(self.grace, self.femi)["place_in_class"]["label"], "1st of 3")
        self.assertEqual(self.card_of(self.stmarys, self.dayo)["place_in_class"]["label"], "not ranked")
        with connected_to(self.grace):
            self.assertFalse(ReleasedCard.objects.filter(whole_subjects_only=True).exists())

    def test_nothing_in_a_released_card_can_be_changed_to_say_otherwise(self):
        self.release(self.stmarys)
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.dayo.pk)
            card.whole_subjects_only = False
            with self.assertRaises(CardsAreFrozenAtRelease):
                card.save()


class TheYearsLastLineIsNotMovedTests(TwoSchoolsOneMissingPaper):
    """Not part of this change: the average the session line is built on."""

    def test_averages_still_count_every_subject_a_child_has_a_mark_in(self):
        with connected_to(self.stmarys):
            results = positions.class_results(self.group_of(self.stmarys), self.term_of(self.stmarys, FIRST))
            self.assertEqual(positions.overall_percentages(self.group_of(self.stmarys), self.term_of(self.stmarys, FIRST)), results.averages)
        self.assertEqual(results.averages[self.dayo.pk], Decimal("92.28"))
        self.assertEqual(results.card_averages[self.dayo.pk], Decimal("90.00"))
