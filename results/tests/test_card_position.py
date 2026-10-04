"""The summary every card prints, and the position a school may choose to print.

`card_api.card_payload()`: `percentage` is marks obtained over marks
obtainable; `place_in_class` is present **only** on a card released while
the school's `show_position` was on, and frozen there
(`ReleasedCard.position_printed`). Off by default, so a school that never
asked prints no position anywhere, as before. Two schools, each its own
setting.
"""

from academics.models import TermName
from accounts.models import Role
from results import look, ogun, pdf
from results.models import ReleasedCard, ReportCardSettings
from results.tests.test_card_api import HOST, THEIR_HOST, ReportCardApiSetUp
from schools.tests.tenants import connected_to


class PositionSetUp(ReportCardApiSetUp):
    def turn_on(self, school=None):
        school = school or self.stmarys
        with connected_to(school):
            look.set_show_position_as(self.staff_of(school)[Role.PRINCIPAL], school, True)

    def card_body(self, child=None, school=None):
        child = child or self.ada
        school = school or self.stmarys
        response = self.fetch(self.mama if child == self.ada else None, school, child)
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def staff_fetch(self, child, school=None):
        school = school or self.stmarys
        return self.fetch(self.staff_of(school)[Role.PRINCIPAL], school, child)


class TheSummaryTests(PositionSetUp):
    def test_every_card_carries_obtained_obtainable_and_the_percentage(self):
        self.release()
        body = self.card_body().json()

        # Ada: 88 + 74 out of 100 + 100.
        self.assertEqual((body["total_scored"], body["total_available"], body["percentage"]), (162, 200, "81.00"))

    def test_the_pdf_and_the_page_print_it(self):
        self.release()
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            html = pdf.html_for(card)
        self.assertIn("162 of 200 obtainable", html)
        self.assertIn("81.00%", html)


class OffByDefaultTests(PositionSetUp):
    def test_the_control_staff_hold_a_position_for_this_card(self):
        """The leak tests below would pass for a card with no rank to leak."""
        self.release()
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
        self.assertEqual((card.position, card.position_printed), (1, False))

    def test_the_family_and_staff_payloads_carry_no_rank(self):
        self.release()
        for response in (self.card_body(), self.staff_fetch(self.ada)):
            with self.subTest(status=response.status_code):
                self.assertIsNone(response.json()["place_in_class"])
                self.assertNotIn(b"position", response.content)
                self.assertNotIn(b"1st", response.content)

    def test_the_pdf_prints_no_position(self):
        self.release()
        with connected_to(self.stmarys):
            html = pdf.html_for(ReleasedCard.objects.get(student_membership_id=self.ada.pk))
        self.assertNotIn("Position", html)
        self.assertNotIn("1st of 2", html)


class TurnedOnTests(PositionSetUp):
    def test_a_card_released_with_it_on_prints_the_place(self):
        self.turn_on()
        self.release()

        body = self.card_body().json()

        self.assertEqual(body["place_in_class"], {"place": 1, "out_of": 2, "label": "1st of 2"})
        with connected_to(self.stmarys):
            html = pdf.html_for(ReleasedCard.objects.get(student_membership_id=self.ada.pk))
        self.assertIn("1st of 2", html)

    def test_turning_it_off_later_leaves_a_released_card_as_it_was(self):
        self.turn_on()
        self.release()
        with connected_to(self.stmarys):
            look.set_show_position_as(self.principal, self.stmarys, False)

        self.assertEqual(self.card_body().json()["place_in_class"]["label"], "1st of 2")

    def test_turning_it_on_later_does_not_reach_a_card_already_home(self):
        self.release()
        self.turn_on()

        self.assertIsNone(self.card_body().json()["place_in_class"])

    def test_one_schools_setting_is_not_the_others(self):
        self.turn_on(self.stmarys)
        with connected_to(self.grace):
            self.assertFalse(look.settings().show_position)

    def test_choosing_the_ogun_card_turns_it_on(self):
        with connected_to(self.stmarys):
            ogun.set_template_as(self.principal, self.stmarys, "ogun")
            self.assertTrue(ReportCardSettings.objects.get().show_position)
        with connected_to(self.grace):
            self.assertFalse(look.settings().show_position)


class WhoMaySetItTests(PositionSetUp):
    def put(self, user, on=True, host=HOST):
        self.client.force_login(user)
        return self.client.put(
            "/api/academics/card/position/",
            data={"show_position": on},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def test_the_principal_sets_it_and_setup_says_so(self):
        response = self.put(self.principal)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["show_position"])

    def test_a_teacher_and_the_other_schools_principal_are_refused(self):
        self.assertEqual(self.put(self.teacher).status_code, 403)
        self.assertEqual(self.put(self.their_principal).status_code, 403)
        with connected_to(self.stmarys):
            self.assertFalse(look.settings().show_position)

    def test_ordinals(self):
        from results.card_api import ordinal

        self.assertEqual(
            [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112)],
            ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th", "112th"],
        )
