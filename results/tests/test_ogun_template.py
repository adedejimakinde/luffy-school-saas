"""Choosing the Ogun State template, and what choosing it sets up.

`results.ogun`. Two schools in every test: the template is a row in each
school's own schema and the presets write that school's assessments, traits
and scale, so a choice at St Mary's must leave Grace's sheet exactly as it was.

The rule every class below is a case of: **nothing already marked or rated is
changed.**
"""

from datetime import date

from academics.models import Term, TermName
from attendance.tests.fixtures import a_term
from gradebook import services as gradebook
from gradebook.models import Assessment, Score, Subject
from results import ogun
from results import services as results_services
from results.models import (
    CardTemplate,
    RatingScalePoint,
    ReleasedAssessmentScore,
    ReportCardSettings,
    Trait,
    TraitRating,
)
from results.tests.fixtures import HOST, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

TEMPLATE = "/api/academics/card/template/"
OGUN_PAPERS = [("1st Test", 10), ("2nd Test", 10), ("Assignment", 10), ("Exam", 70)]


class OgunSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        self.admin = self.head  # The principal may set the school up.

    def choose(self, who, template="ogun", host=HOST):
        self.client.force_login(who.user)
        return self.client.put(
            TEMPLATE, data={"template": template}, content_type="application/json", HTTP_HOST=host
        )

    def papers(self, school, subject_name="Mathematics", term=None):
        with connected_to(school):
            term = term or Term.objects.get(is_current=True)
            return [
                (a.name, a.max_score)
                for a in Assessment.objects.filter(term=term, subject__name=subject_name).order_by("position", "id")
            ]

    def visible(self, school, group):
        with connected_to(school):
            return list(Trait.objects.in_group(group).visible().values_list("name", flat=True))


class ChoosingTheTemplateTests(OgunSetUp):
    def test_the_control_choosing_ogun_sets_up_the_sheet_at_this_school_only(self):
        response = self.choose(self.head)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["template"], "ogun")
        self.assertEqual(
            body["applied"]["assessments_set"],
            ["Mathematics, First term 2025/2026", "Mathematics, Second term 2025/2026"],
        )
        self.assertEqual(self.papers(self.stmarys), OGUN_PAPERS)
        self.assertEqual(self.papers(self.grace), [("First CA", 20)], "Grace's papers were touched")
        with connected_to(self.grace):
            self.assertEqual(ReportCardSettings.objects.get().template, "standard")

    def test_the_traits_are_the_sheets_in_its_order_with_both_sections_on(self):
        self.choose(self.head)

        self.assertEqual(self.visible(self.stmarys, "affective"), list(ogun.AFFECTIVE))
        self.assertEqual(self.visible(self.stmarys, "psychomotor"), list(ogun.PSYCHOMOTOR))
        with connected_to(self.stmarys):
            row = ReportCardSettings.objects.get()
            self.assertTrue(row.affective_enabled and row.psychomotor_enabled)
        with connected_to(self.grace):
            self.assertIn("Politeness", list(Trait.objects.visible().values_list("name", flat=True)))

    def test_the_scale_says_the_sheets_words(self):
        self.choose(self.head)

        with connected_to(self.stmarys):
            self.assertEqual(
                list(RatingScalePoint.objects.values_list("value", "label")),
                [(5, "Excellent"), (4, "Good"), (3, "Average"), (2, "Below Average"), (1, "Unsatisfactory")],
            )
        with connected_to(self.grace):
            self.assertEqual(RatingScalePoint.objects.get(value=4).label, "Very Good")

    def test_choosing_twice_changes_nothing_the_second_time(self):
        self.choose(self.head)
        with connected_to(self.stmarys):
            first = list(Assessment.objects.values_list("pk", flat=True))

        again = self.choose(self.head).json()["applied"]

        self.assertEqual(again["assessments_set"], [])
        self.assertEqual((again["traits_added"], again["traits_hidden"], again["traits_renamed"]), ([], [], []))
        with connected_to(self.stmarys):
            self.assertEqual(list(Assessment.objects.values_list("pk", flat=True)), first)

    def test_switching_back_to_standard_undoes_nothing(self):
        self.choose(self.head)
        body = self.choose(self.head, "standard").json()

        self.assertEqual((body["template"], body["applied"]), ("standard", None))
        self.assertEqual(self.papers(self.stmarys), OGUN_PAPERS)

    def test_every_term_from_the_current_one_is_set_and_an_earlier_one_is_not(self):
        with connected_to(self.stmarys):
            earlier = a_term(
                session="2024/2025", name=TermName.THIRD, starts=date(2025, 4, 22), ends=date(2025, 7, 18)
            )
            Assessment.objects.create(term=earlier, subject=self.maths, name="Old CA", max_score=40)

        self.choose(self.head)

        self.assertEqual(self.papers(self.stmarys, term=self.second_term), OGUN_PAPERS)
        self.assertEqual(self.papers(self.stmarys, term=earlier), [("Old CA", 40)])

    def test_a_term_opened_afterwards_gets_the_papers(self):
        self.choose(self.head)
        with connected_to(self.stmarys):
            Subject.objects.create(name="English", code="ENG")
        self.client.force_login(self.head.user)
        response = self.client.post(
            "/api/academics/terms/",
            data={"session": "2025/2026", "name": "third", "starts_on": "2026-04-20", "ends_on": "2026-07-17"},
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(response.status_code, 201, response.content)
        with connected_to(self.stmarys):
            third = Term.objects.get(pk=response.json()["term_id"])
        self.assertEqual(self.papers(self.stmarys, "English", term=third), OGUN_PAPERS)

    def test_a_standard_schools_new_term_gets_nothing(self):
        self.client.force_login(self.their_head.user)
        response = self.client.post(
            "/api/academics/terms/",
            data={"session": "2025/2026", "name": "second", "starts_on": "2026-01-12", "ends_on": "2026-04-02"},
            content_type="application/json",
            HTTP_HOST=THEIR_HOST,
        )
        with connected_to(self.grace):
            self.assertFalse(Assessment.objects.filter(term_id=response.json()["term_id"]).exists())


class NeverOverAMarkOrARatingTests(OgunSetUp):
    def test_a_subject_with_a_mark_keeps_its_papers_and_the_mark(self):
        with connected_to(self.stmarys):
            score = gradebook.set_score(self.first_ca, self.children["ada"], 17, by=self.teacher.user)

        applied = self.choose(self.head).json()["applied"]

        self.assertEqual(applied["assessments_kept"], ["Mathematics, First term 2025/2026"])
        self.assertEqual(self.papers(self.stmarys), [("First CA", 20)])
        with connected_to(self.stmarys):
            self.assertEqual(Score.objects.get(pk=score.pk).value, 17)

    def test_marked_in_one_term_still_sets_the_next(self):
        with connected_to(self.stmarys):
            gradebook.set_score(self.first_ca, self.children["ada"], 17, by=self.teacher.user)

        self.choose(self.head)

        self.assertEqual(self.papers(self.stmarys, term=self.second_term), OGUN_PAPERS)

    def test_a_released_term_keeps_its_papers(self):
        with connected_to(self.stmarys):
            gradebook.set_score(self.first_ca, self.children["ada"], 17, by=self.teacher.user)
            sheet = results_services.open_sheet(self.jss1a, self.term, self.head.user)
            results_services.submit(sheet, self.teacher.user)
            results_services.check(sheet, self.vp.user)
            results_services.approve(sheet, self.head.user)
            results_services.release(sheet, self.head.user)
            released = ReleasedAssessmentScore.objects.count()
            self.assertGreater(released, 0)

        self.choose(self.head)

        self.assertEqual(self.papers(self.stmarys), [("First CA", 20)])
        with connected_to(self.stmarys):
            self.assertEqual(ReleasedAssessmentScore.objects.count(), released)

    def test_a_rated_trait_the_sheet_does_not_print_stays_on_the_sheet(self):
        with connected_to(self.stmarys):
            politeness = Trait.objects.get(name="Politeness")
            TraitRating.objects.create(
                term=self.term, trait=politeness, student_membership_id=self.children["ada"].pk, score=4
            )

        applied = self.choose(self.head).json()["applied"]

        self.assertIn("Politeness", applied["traits_kept"])
        self.assertIn("Politeness", self.visible(self.stmarys, "affective"))
        self.assertNotIn("Attendance", self.visible(self.stmarys, "affective"))
        with connected_to(self.stmarys):
            self.assertEqual(TraitRating.objects.get(trait=politeness).score, 4)

    def test_a_seeded_line_with_another_spelling_is_renamed_and_its_rating_kept(self):
        with connected_to(self.stmarys):
            games = Trait.objects.get(name="Games/Sports")
            TraitRating.objects.create(
                term=self.term, trait=games, student_membership_id=self.children["ada"].pk, score=5
            )

        applied = self.choose(self.head).json()["applied"]

        self.assertIn("Games/Sports → Games & Sports", applied["traits_renamed"])
        with connected_to(self.stmarys):
            self.assertEqual(TraitRating.objects.get(trait_id=games.pk).trait.name, "Games & Sports")


class WhoMayChooseTests(OgunSetUp):
    def test_the_service_refuses_a_teacher_without_the_route(self):
        with connected_to(self.stmarys), self.assertRaises(ogun.NotAllowedToChooseTheTemplate):
            ogun.set_template_as(self.teacher.user, self.stmarys, "ogun")


    def test_a_teacher_and_a_bursar_are_refused_and_nothing_changes(self):
        for who in (self.teacher, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.choose(who).status_code, 403)
        self.assertEqual(self.papers(self.stmarys), [("First CA", 20)])
        with connected_to(self.stmarys):
            self.assertEqual(ReportCardSettings.objects.get().template, CardTemplate.STANDARD)

    def test_the_other_schools_principal_is_refused_here(self):
        self.assertEqual(self.choose(self.their_head).status_code, 403)
        self.assertEqual(self.papers(self.stmarys), [("First CA", 20)])

    def test_a_template_that_is_not_one_is_refused(self):
        self.assertEqual(self.choose(self.head, "lagos").status_code, 422)

    def test_setup_says_which_template(self):
        self.choose(self.head)
        self.client.force_login(self.head.user)
        self.assertEqual(self.client.get("/api/academics/setup/", HTTP_HOST=HOST).json()["card"]["template"], "ogun")
