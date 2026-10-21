"""A released card prints in the layout it was released under.

`ReleasedCard.template`, frozen at release; `ogun_card.prints_ogun()` is the one
place a card's layout is decided, for the family's page (it draws the Ogun sheet
when the payload carries one) and the PDF alike. Two schools in every test: St
Mary's and Grace each choose, and what one chooses never reaches the other's
cards. A card released before layouts were frozen has none and follows the
school's current template, as it always did.
"""

from unittest import mock

from academics.models import TermName
from results import cards, ogun, pdf, revision
from results.models import ReleasedCard
from results.tests.test_card_api import ReportCardApiSetUp
from schools.tests.tenants import connected_to

FIRST, SECOND = TermName.FIRST.value, TermName.SECOND.value


class LayoutSetUp(ReportCardApiSetUp):
    def choose(self, school, template):
        people = self.staff_of(school)
        from accounts.models import Role

        with connected_to(school):
            ogun.set_template_as(people[Role.PRINCIPAL], school, template)

    def payload(self, school, child, term=FIRST):
        who = self.principal if school == self.stmarys else self.their_principal
        response = self.fetch(who, school, child, term)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def html(self, school, child, term=FIRST):
        with connected_to(school):
            card = ReleasedCard.objects.filter(
                student_membership_id=child.pk, term=self.term_of(school, term)
            ).order_by("-version").first()
            return pdf.html_for(card)

    def prints_ogun(self, school, child, term=FIRST):
        """Both ways the layout reaches a reader: the payload and the PDF."""
        on_page = self.payload(school, child, term)["ogun"] is not None
        html = self.html(school, child, term)
        on_paper = "CONTINUOUS ASSESSMENT REPORT SHEET" in html
        self.assertEqual(on_page, on_paper, "the page and the PDF disagree about the layout")
        return on_page

    def old_freeze(self):
        """`_card_for()` as it was before layouts were frozen: a card with none."""
        real = cards._card_for

        def without_a_layout(*args, **kwargs):
            card = real(*args, **kwargs)
            card.template = ""
            return card

        return mock.patch.object(cards, "_card_for", without_a_layout)


class ReleasedOnStandardStaysStandardTests(LayoutSetUp):
    def test_the_control_the_card_remembers_the_layout_it_was_released_under(self):
        self.release(self.stmarys)
        with connected_to(self.stmarys):
            self.assertEqual(ReleasedCard.objects.get(student_membership_id=self.ada.pk).template, "standard")

    def test_release_on_standard_then_switch_to_ogun_the_card_still_prints_standard(self):
        self.release(self.stmarys)
        self.release(self.grace)

        self.choose(self.stmarys, "ogun")

        self.assertFalse(self.prints_ogun(self.stmarys, self.ada))
        self.assertFalse(self.prints_ogun(self.stmarys, self.bola))
        # The family's page, as a parent opens it.
        self.assertIsNone(self.fetch(self.mama, self.stmarys, self.ada).json()["ogun"])

    def test_release_on_ogun_then_switch_to_standard_the_card_still_prints_ogun(self):
        self.choose(self.stmarys, "ogun")
        self.release(self.stmarys)

        self.choose(self.stmarys, "standard")

        self.assertTrue(self.prints_ogun(self.stmarys, self.ada))
        self.assertIsNotNone(self.fetch(self.mama, self.stmarys, self.ada).json()["ogun"])

    def test_a_term_released_after_the_switch_prints_the_new_layout_and_the_old_one_does_not_move(self):
        self.release(self.stmarys)
        self.choose(self.stmarys, "ogun")
        self._mark(self.stmarys, SECOND, self.ada, "maths", "Exam", 70, out_of=100)
        self.release(self.stmarys, term_name=SECOND)

        self.assertFalse(self.prints_ogun(self.stmarys, self.ada, FIRST))
        self.assertTrue(self.prints_ogun(self.stmarys, self.ada, SECOND))

    def test_the_other_schools_cards_do_not_follow_this_schools_choice(self):
        self.release(self.stmarys)
        self.release(self.grace)
        self.choose(self.grace, "ogun")

        self.assertFalse(self.prints_ogun(self.stmarys, self.ada))
        self.assertFalse(self.prints_ogun(self.grace, self.ngozi), "Grace released on Standard too")
        with connected_to(self.stmarys):
            self.assertEqual(
                set(ReleasedCard.objects.values_list("template", flat=True)), {"standard"}
            )


class ARevisionKeepsTheLayoutTests(LayoutSetUp):
    def test_reissuing_a_card_does_not_redraw_it_in_a_template_chosen_since(self):
        self.release(self.stmarys)
        self.choose(self.stmarys, "ogun")

        with connected_to(self.stmarys):
            revision.revise(
                self.ada, self.term_of(self.stmarys, FIRST), self.principal, "A name was misspelled."
            )

        self.assertEqual(self.payload(self.stmarys, self.ada)["version"], 2)
        self.assertFalse(self.prints_ogun(self.stmarys, self.ada))
        with connected_to(self.stmarys):
            self.assertEqual(
                list(ReleasedCard.objects.filter(student_membership_id=self.ada.pk).order_by("version").values_list("template", flat=True)),
                ["standard", "standard"],
            )

    def test_a_revision_of_a_card_with_no_frozen_layout_freezes_the_one_now(self):
        with self.old_freeze():
            self.release(self.stmarys)
        self.choose(self.stmarys, "ogun")

        with connected_to(self.stmarys):
            revision.revise(
                self.ada, self.term_of(self.stmarys, FIRST), self.principal, "A name was misspelled."
            )

        with connected_to(self.stmarys):
            versions = list(
                ReleasedCard.objects.filter(student_membership_id=self.ada.pk)
                .order_by("version")
                .values_list("version", "template")
            )
        self.assertEqual(versions, [(1, ""), (2, "ogun")])


class ACardFromBeforeLayoutsWereFrozenTests(LayoutSetUp):
    """Old cards keep today's behaviour: they follow the school's current template."""

    def test_the_control_such_a_card_carries_no_layout(self):
        with self.old_freeze():
            self.release(self.stmarys)
        with connected_to(self.stmarys):
            self.assertEqual(ReleasedCard.objects.get(student_membership_id=self.ada.pk).template, "")

    def test_it_prints_whatever_the_school_prints_now(self):
        with self.old_freeze():
            self.release(self.stmarys)
            self.release(self.grace)

        self.assertFalse(self.prints_ogun(self.stmarys, self.ada))
        self.choose(self.stmarys, "ogun")
        self.assertTrue(self.prints_ogun(self.stmarys, self.ada))
        self.choose(self.stmarys, "standard")
        self.assertFalse(self.prints_ogun(self.stmarys, self.ada))

    def test_one_schools_old_cards_follow_that_school_only(self):
        with self.old_freeze():
            self.release(self.stmarys)
            self.release(self.grace)

        self.choose(self.stmarys, "ogun")

        self.assertTrue(self.prints_ogun(self.stmarys, self.ada))
        self.assertFalse(self.prints_ogun(self.grace, self.ngozi))
