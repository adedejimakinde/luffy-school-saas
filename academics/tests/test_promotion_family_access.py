"""Graduating or leaving does not lock the family out of the cards that went
home: audit finding G-05.

**Checked first, as the audit asked.** Before this, promotion ended a graduate's
or a leaver's enrolment through `release_student()`, which also ended the
PARENT membership of a guardian with no other child at the school; a signed-in
user with no active membership is refused on every page that is not a door. So
on the day promotion was confirmed, an SS 3 family could no longer open the
third-term card. `test_before_the_fix_...` is that state, reproduced on the
service that used to be called.

Now promotion ends a graduate's or a leaver's enrolment with
`release_student(keep_family_access=True)`: **the mechanism #349 built for
taking a child off the roll (G-16), reused, not a second one.** The guardian
keeps their PARENT membership, with no end date, and `card_api` serves the
ended child's released cards to them.

St Mary's JSS 1A is released for its third term and then, in different tests,
graduates or loses one child. Grace Academy is the second school.
"""

from accounts import services as memberships
from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import release_student
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

from .test_promotion_decisions import DecisionsSetUp

CARDS = "/api/results/cards/"


class FamilySetUp(DecisionsSetUp):
    def setUp(self):
        super().setUp()
        self.ada = self.children["ada"]
        self.mama = User.objects.create_user("mama", PASSWORD, full_name="Mama Ada")
        memberships.link_guardian(self.mama, self.ada)
        give_verified_channel(self.mama)
        self.release_jss1a(ada=14, emeka=12, bisi=10, tunde=9)

    def card_url(self, child=None):
        return f"{CARDS}{(child or self.ada).pk}/{self.term_id}/"

    def graduate_jss1a(self):
        """The principal graduates JSS 1A; the administrator confirms."""
        self.decide_everybody(ada="graduated", emeka="graduated", bisi="graduated", tunde="graduated")
        plan = self.default_plan()
        entry = self.class_named(plan, "JSS 1A")
        entry["graduate"], entry["destination_id"] = True, None
        response = self.post(plan, member=self.admin, decided=False)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Membership.objects.get(pk=self.ada.pk).status, MembershipStatus.ENDED)

    def ada_leaves(self):
        self.decide_everybody(ada="withdrawn")
        response = self.post(self.plan(ada="leave"), decided=False)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Membership.objects.get(pk=self.ada.pk).status, MembershipStatus.ENDED)

    def parent_is_active(self):
        return Membership.objects.filter(
            user=self.mama, school=self.stmarys, role=Role.PARENT, status=MembershipStatus.ACTIVE
        ).exists()


class TheGuardianKeepsTheCardsTests(FamilySetUp):
    def test_before_the_fix_a_graduates_only_guardian_was_refused_at_the_host(self):
        """The audit's "needs checking", settled: the release promotion used to
        make ends the guardian's membership, and the host then refuses her."""
        release_student(Membership.objects.get(pk=self.ada.pk))

        self.assertFalse(self.parent_is_active())
        self.client.force_login(self.mama)
        self.assertEqual(self.client.get(CARDS, HTTP_HOST=HOST).status_code, 403)
        self.assertEqual(self.client.get(self.card_url(), HTTP_HOST=HOST).status_code, 403)

    def test_the_guardian_of_a_graduate_still_reads_the_final_card(self):
        self.graduate_jss1a()

        self.assertTrue(self.parent_is_active())
        self.client.force_login(self.mama)
        listed = self.client.get(CARDS, HTTP_HOST=HOST)
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertIn("Ada Obi", listed.content.decode())
        card = self.client.get(self.card_url(), HTTP_HOST=HOST)
        self.assertEqual(card.status_code, 200, card.content)
        self.assertEqual(card.json()["student_name"], "Ada Obi")

    def test_the_guardian_of_a_child_who_leaves_at_promotion_still_reads_it(self):
        self.ada_leaves()

        self.assertTrue(self.parent_is_active())
        self.client.force_login(self.mama)
        self.assertEqual(self.client.get(self.card_url(), HTTP_HOST=HOST).status_code, 200)

    def test_she_still_reads_only_her_own_childs(self):
        self.graduate_jss1a()

        self.client.force_login(self.mama)
        self.assertEqual(
            self.client.get(self.card_url(self.children["emeka"]), HTTP_HOST=HOST).status_code, 404
        )


class OneMechanismForLeaversAndGraduatesTests(FamilySetUp):
    def test_promotion_and_taking_a_child_off_the_roll_end_an_enrolment_the_same_way(self):
        """Both reach `release_student()` with `keep_family_access=True`."""
        from unittest import mock

        with mock.patch(
            "academics.promotion.release_student", wraps=release_student
        ) as released:
            self.graduate_jss1a()

        # JSS 1A's four and SS 3's two.
        self.assertEqual(len(released.call_args_list), 6)
        self.assertTrue(
            all(call.kwargs.get("keep_family_access") is True for call in released.call_args_list)
        )
        # The leaving path's own use of the flag is #349's to assert
        # (`academics/tests/test_leaving.py`, control G16-3).

    def test_the_other_schools_family_is_untouched(self):
        """Grace's guardian, whose child is not promoted anywhere, keeps exactly
        what they had, and reads nothing of St Mary's."""
        papa = User.objects.create_user("papa", PASSWORD, full_name="Papa Chidi")
        memberships.link_guardian(papa, self.grace_child)
        give_verified_channel(papa, "08030000009")
        before = list(Membership.objects.filter(user=papa).values_list("school_id", "role", "status"))

        self.graduate_jss1a()

        self.assertEqual(
            list(Membership.objects.filter(user=papa).values_list("school_id", "role", "status")), before
        )
        self.client.force_login(papa)
        self.assertEqual(self.client.get(self.card_url(), HTTP_HOST=HOST).status_code, 403)
        self.client.force_login(self.mama)
        self.assertEqual(self.client.get(CARDS, HTTP_HOST=THEIR_HOST).status_code, 403)
