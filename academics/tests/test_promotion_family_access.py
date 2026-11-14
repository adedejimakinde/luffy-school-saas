"""Graduating or leaving does not lock the family out of the cards that went
home: audit finding G-05.

**Checked first, as the audit asked.** Before this, promotion ended a graduate's
or a leaver's enrolment through `release_student()`, which also ended the
PARENT membership of a guardian with no other child at the school; a signed-in
user with no active membership is refused on every page that is not a door. So
on the day promotion was confirmed, an SS 3 family could no longer open the
third-term card. `test_before_the_fix_...` is that state, reproduced on the
service that used to be called.

Now:

- **the guardian** keeps their PARENT membership (`keep_family_access`), as a
  leaver's family already did (G-16);
- **the child** signs in on the school's host with an ended membership and
  reaches their own cards and nothing else (`accounts.former`). No role is
  granted: every other route still refuses them.

St Mary's JSS 1A is released for its third term and then, in different tests,
graduates or loses one child. Grace Academy is the second school.
"""

from django.db import connection
from django.test import Client

from academics import services as academics
from accounts import former, services as memberships
from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import enroll_student, release_student
from results.models import ReleasedCard
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

    def sign_in(self, identifier, host=HOST):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/csrf/", HTTP_HOST=host).json()["csrf_token"]
        response = client.post(
            "/api/login/",
            data={"identifier": identifier, "password": PASSWORD},
            content_type="application/json",
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=token,
        )
        connection.set_schema_to_public()
        return client, response

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


class TheChildKeepsTheirOwnCardsTests(FamilySetUp):
    def test_a_graduate_signs_in_and_reads_their_final_card(self):
        self.graduate_jss1a()

        client, response = self.sign_in("ada")

        self.assertEqual(response.status_code, 200, response.content)
        listed = client.get(CARDS, HTTP_HOST=HOST)
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertIn("Ada Obi", listed.content.decode())
        card = client.get(self.card_url(), HTTP_HOST=HOST)
        self.assertEqual(card.status_code, 200, card.content)
        self.assertEqual(card.json()["student_name"], "Ada Obi")
        self.assertEqual(client.get("/cards/", HTTP_HOST=HOST).status_code, 200)

    def test_a_child_who_left_at_promotion_does_too(self):
        self.ada_leaves()

        client, response = self.sign_in("ada")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(client.get(self.card_url(), HTTP_HOST=HOST).status_code, 200)

    def test_before_the_fix_the_door_and_the_host_refused_them(self):
        """The companion: with the former-student rule switched off, both gates
        are real. Sign-in is refused and a session is refused at the host."""
        from unittest import mock

        self.graduate_jss1a()
        with mock.patch.object(former, "was_a_student_here", return_value=False):
            _client, response = self.sign_in("ada")
            self.assertEqual(response.status_code, 401)
            self.client.force_login(self.ada.user)
            self.assertEqual(self.client.get(self.card_url(), HTTP_HOST=HOST).status_code, 403)

    def test_they_reach_their_cards_and_nothing_else(self):
        """No role is granted. Every other page and route answers as it does to
        a login with no membership: refused by the host, 403."""
        self.graduate_jss1a()
        client, _ = self.sign_in("ada")

        self.assertEqual(set(self.ada.user.roles_at(self.stmarys)), set())
        for path in (
            "/home/",
            "/roll/",
            "/fees/",
            "/promotion/",
            "/register/",
            "/api/home/",
            "/api/academics/promotion/",
            "/api/academics/setup/",
            "/api/enrolment/roll/",
            "/api/results/year-settings/",
            f"/api/results/health/{self.ada.pk}/?term_id={self.term_id}",
            "/api/fees/",
            "/cards-of-everybody/",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.get(path, HTTP_HOST=HOST).status_code, 403)

    def test_another_childs_card_is_not_theirs(self):
        self.graduate_jss1a()
        client, _ = self.sign_in("ada")

        self.assertEqual(client.get(self.card_url(self.children["emeka"]), HTTP_HOST=HOST).status_code, 404)
        self.assertEqual(client.get(self.card_url(self.bimpe), HTTP_HOST=HOST).status_code, 404)

    def test_a_suspended_student_is_not_a_former_one(self):
        Membership.objects.filter(pk=self.ada.pk).update(status=MembershipStatus.SUSPENDED)

        _client, response = self.sign_in("ada")

        self.assertEqual(response.status_code, 401)
        self.client.force_login(self.ada.user)
        self.assertEqual(self.client.get(self.card_url(), HTTP_HOST=HOST).status_code, 403)

    def test_a_former_teacher_is_not_let_in(self):
        """Only an ended STUDENT membership opens the door."""
        Membership.objects.filter(pk=self.teacher.pk).update(status=MembershipStatus.ENDED)

        _client, response = self.sign_in("kemi")

        self.assertEqual(response.status_code, 401)
        self.client.force_login(self.teacher.user)
        self.assertEqual(self.client.get(CARDS, HTTP_HOST=HOST).status_code, 403)

    def test_having_left_one_school_opens_nothing_at_another(self):
        self.graduate_jss1a()

        _client, response = self.sign_in("ada", host=THEIR_HOST)
        self.assertEqual(response.status_code, 401)
        self.client.force_login(self.ada.user)
        self.assertEqual(self.client.get(CARDS, HTTP_HOST=THEIR_HOST).status_code, 403)
        # And Grace's own former student reads nothing at St Mary's.
        release_student(Membership.objects.get(pk=self.grace_child.pk))
        self.client.force_login(self.grace_child.user)
        self.assertEqual(self.client.get(CARDS, HTTP_HOST=HOST).status_code, 403)
        self.assertEqual(self.client.get(self.card_url(), HTTP_HOST=HOST).status_code, 403)
        self.assertEqual(self.client.get(CARDS, HTTP_HOST=THEIR_HOST).status_code, 200)
