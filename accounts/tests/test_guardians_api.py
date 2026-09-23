"""A child's guardians on the roll: who they are here, and whether they can see the child.

Two schools in every test. `Membership` and `Guardianship` are **shared**
tables, so what keeps a St Mary's child's guardians away from a Grace
administrator is a `school=` filter doing real work — there is no tenant
schema behind it. And a contact typed at St Mary's can belong to a parent
already verified at Grace, which is the case #135 is about.

Every refusal is asserted by its own sentence, not by a bare status: a 403
from the route's authority check and a 403 from anywhere else are the same
number.
"""

from accounts import guardian_contacts
from accounts.models import (
    GuardianAccount,
    GuardianContact,
    Guardianship,
    Membership,
    MembershipStatus,
    Role,
    User,
)
from accounts.services import link_guardian
from accounts.tests.test_enrolment_api import EnrolmentSetUp
from results.tests.fixtures import HOST, PORTAL, THEIR_HOST
from tests.guardians import give_verified_channel

ROLL = "/api/enrolment/roll/"
MAY_NOT_LINK = "linked by an administrator"
NO_SUCH_CHILD = "no such child on this school's roll"


class GuardiansSetUp(EnrolmentSetUp):
    def setUp(self):
        super().setUp()
        students = Membership.objects.filter(school=self.stmarys, role=Role.STUDENT)
        self.ada = students.get(user__full_name="Ada Obi")
        self.bisi = students.get(user__full_name="Bisi Ade")
        self.chidi = Membership.objects.get(school=self.grace, role=Role.STUDENT)

    def url(self, child, *rest):
        return f"{ROLL}{child.pk}/guardians/" + "".join(f"{part}/" for part in rest)

    def read(self, user, child, host=HOST):
        self.client.force_login(user.user)
        return self.client.get(self.url(child), HTTP_HOST=host)

    def link(self, user, child, name="Mama Obi", contact="0803 123 4567", host=HOST, **extra):
        self.client.force_login(user.user)
        return self.client.post(
            self.url(child),
            data={"full_name": name, "contact": contact, **extra},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def remove(self, user, child, link_id, host=HOST):
        self.client.force_login(user.user)
        return self.client.post(self.url(child, link_id, "remove"), HTTP_HOST=host)

    def only(self, response):
        self.assertEqual(response.status_code, 201, response.content)
        guardians = response.json()["guardians"]
        self.assertEqual(len(guardians), 1, guardians)
        return guardians[0]


class LinkingTests(GuardiansSetUp):
    # -- the control, and it runs first ----------------------------------------

    def test_the_panel_really_lists_a_guardian(self):
        """Every exclusion below would pass against a panel that listed
        nobody for anybody."""
        self.link(self.admin, self.ada)

        body = self.read(self.admin, self.ada).json()

        self.assertEqual(body["student"], "Ada Obi")
        self.assertEqual([g["name"] for g in body["guardians"]], ["Mama Obi"])
        self.assertEqual(body["guardians"][0]["contact"], "+2348031234567")
        self.assertTrue(body["may_link"])

    # -- not live until the guardian answers this school -----------------------

    def test_a_new_link_reads_pending_verification(self):
        """PR A's decision 4: say plainly that the link is not live yet.

        Read back from the membership, which is why control 4 — `link_guardian()`
        granting ACTIVE — turns this red: a panel that *assumed* "pending" would
        survive that control, and go on saying "pending" after a guardian had
        answered.
        """
        guardian = self.only(self.link(self.admin, self.ada))

        self.assertEqual(guardian["status"], "pending verification")
        self.assertEqual(guardian["channel"], "not verified here")
        parent = User.objects.get(phone="+2348031234567")
        self.assertEqual(
            Membership.objects.get(user=parent, school=self.stmarys, role=Role.PARENT).status,
            MembershipStatus.INVITED,
        )
        self.assertFalse(parent.has_access_to(self.stmarys))

    def test_a_guardian_who_has_answered_here_reads_live(self):
        """The control for the one above: without it, a panel printing
        "pending" whatever the membership said would pass."""
        self.link(self.admin, self.ada)
        give_verified_channel(User.objects.get(phone="+2348031234567"), "08031234567")

        guardian = self.read(self.admin, self.ada).json()["guardians"][0]

        self.assertEqual(guardian["status"], "live")
        self.assertEqual(guardian["channel"], "verified")

    def test_a_parent_verified_at_the_other_school_is_pending_here_and_named_as_typed(self):
        """**#135.** The number St Mary's typed belongs to a parent Grace has
        already verified. They are pending here like anybody new — no child
        goes to them unasked — and St Mary's is shown what St Mary's typed:
        not Grace's name for them, and not "verified", either of which would
        tell this office that the number is a parent somewhere else.
        """
        theirs = User.objects.create_user(
            "funke", None, full_name="Funke Adeyemi", phone="08031234567"
        )
        link_guardian(theirs, self.chidi)
        give_verified_channel(theirs, "08031234567")
        self.assertTrue(theirs.has_access_to(self.grace), "the fixture is not live at Grace")

        response = self.link(self.admin, self.ada, name="Mama Obi")

        guardian = self.only(response)
        self.assertEqual(guardian["status"], "pending verification")
        self.assertEqual(guardian["channel"], "not verified here")
        self.assertEqual(guardian["name"], "Mama Obi")
        self.assertNotIn("Funke", response.content.decode())
        self.assertFalse(theirs.has_access_to(self.stmarys), "a typo handed Grace's parent a child")
        self.assertEqual(
            Guardianship.objects.get(student=self.ada).guardian,
            theirs,
            "one parent became two accounts",
        )

    # -- one code path, one guardian, one channel -------------------------------

    def test_the_import_and_the_screen_make_one_guardian_with_one_channel(self):
        """D10: whichever door, one guardian record and one verification
        story. The import comes **first**, because it is the door that used to
        make its own `User` and record no channel — so the channel has to be
        there before the screen has a chance to record one.

        CONTROL 7: the import creating its guardian outside
        `link_by_contact_as()` makes this go red.
        """
        self.client.force_login(self.admin.user)
        imported = self.client.post(
            f"{ROLL}import/",
            data={"csv": "full_name,class_group,guardian_name,guardian_contact\n"
                         "Kemi Obi,JSS 1A,Mama Obi,08031234567\n"},
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(imported.status_code, 200, imported.content)
        guardian = User.objects.get(phone="+2348031234567")
        self.assertEqual(
            GuardianContact.objects.filter(guardian__user=guardian).count(),
            1,
            "the import made a guardian with no channel to verify",
        )

        self.link(self.admin, self.ada, contact="0803 123 4567")

        self.assertEqual(User.objects.filter(phone="+2348031234567").count(), 1)
        self.assertEqual(GuardianContact.objects.filter(guardian__user=guardian).count(), 1)
        self.assertEqual(Guardianship.objects.filter(guardian=guardian).count(), 2)

    def test_a_channel_is_recorded_for_a_new_guardian(self):
        self.link(self.admin, self.ada)

        contact = GuardianAccount.objects.get(
            user__phone="+2348031234567"
        ).live_contact()

        self.assertEqual(contact.value, "+2348031234567")
        self.assertIsNone(contact.verified_at)

    def test_a_malformed_contact_is_refused_with_a_sentence(self):
        response = self.link(self.admin, self.ada, contact="0803")

        self.assertEqual(response.status_code, 422)
        self.assertIn("neither a phone number nor an email", response.json()["detail"])
        self.assertFalse(Guardianship.objects.filter(student=self.ada).exists())

    def test_a_guardian_needs_a_name(self):
        response = self.link(self.admin, self.ada, name="  ")

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Guardianship.objects.filter(student=self.ada).exists())

    # -- who may ---------------------------------------------------------------

    def test_a_principal_reads_the_panel_and_may_not_link(self):
        """She reads the roll, so she reads a child's guardians; linking is
        ADMIN alone, like admitting.

        CONTROL 1: the write routes skipping the admin check makes this red.
        """
        self.link(self.admin, self.ada)

        read = self.read(self.head, self.ada)
        self.assertEqual(read.status_code, 200)
        self.assertFalse(read.json()["may_link"])

        response = self.link(self.head, self.ada, name="Papa Obi", contact="08039999999")
        self.assertEqual(response.status_code, 403)
        self.assertIn(MAY_NOT_LINK, response.json()["detail"])
        self.assertFalse(User.objects.filter(phone="+2348039999999").exists())

    def test_a_teacher_is_refused_before_any_child_is_looked_up(self):
        """Authority before the read: a child id that does not exist and one
        that does get the same answer, so the refusal says nothing about the
        roll."""
        for child_id in (self.ada.pk, 999999):
            with self.subTest(child_id=child_id):
                self.client.force_login(self.teacher.user)
                response = self.client.get(f"{ROLL}{child_id}/guardians/", HTTP_HOST=HOST)
                self.assertEqual(response.status_code, 403)

        response = self.link(self.teacher, self.ada)
        self.assertEqual(response.status_code, 403)
        self.assertIn(MAY_NOT_LINK, response.json()["detail"])

    # -- the other school ------------------------------------------------------

    def test_a_grace_administrator_cannot_reach_a_st_marys_child(self):
        """**`school=` is the whole of the isolation.** On Grace's own host,
        with a St Mary's child's id, reading and linking both find no child.

        CONTROL 2: dropping `school=` from `_child_here()` makes this red.
        """
        self.link(self.admin, self.ada)

        read = self.read(self.their_admin, self.ada, host=THEIR_HOST)
        self.assertEqual(read.status_code, 404)
        self.assertIn(NO_SUCH_CHILD, read.json()["detail"])

        linked = self.link(
            self.their_admin, self.ada, name="Stranger", contact="08037777777", host=THEIR_HOST
        )
        self.assertEqual(linked.status_code, 404)
        self.assertIn(NO_SUCH_CHILD, linked.json()["detail"])
        self.assertEqual(Guardianship.objects.filter(student=self.ada).count(), 1)

    def test_there_are_no_guardians_on_the_portal(self):
        self.client.force_login(self.admin.user)

        response = self.client.get(self.url(self.ada), HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 404)


class RemovingTests(GuardiansSetUp):
    def linked(self, child, **kw):
        response = self.link(self.admin, child, **kw)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["guardians"][-1]["link_id"]

    def test_removing_the_last_child_here_ends_the_parent_membership(self):
        link_id = self.linked(self.ada)
        parent = User.objects.get(phone="+2348031234567")

        response = self.remove(self.admin, self.ada, link_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["guardians"], [])
        self.assertEqual(
            Membership.objects.get(user=parent, school=self.stmarys, role=Role.PARENT).status,
            MembershipStatus.ENDED,
        )

    def test_removing_one_siblings_guardian_leaves_the_other_link(self):
        ada_link = self.linked(self.ada)
        self.linked(self.bisi)
        parent = User.objects.get(phone="+2348031234567")

        self.remove(self.admin, self.ada, ada_link)

        self.assertFalse(Guardianship.objects.filter(student=self.ada).exists())
        self.assertTrue(Guardianship.objects.filter(student=self.bisi, guardian=parent).exists())
        self.assertNotEqual(
            Membership.objects.get(user=parent, school=self.stmarys, role=Role.PARENT).status,
            MembershipStatus.ENDED,
        )

    def test_a_principal_cannot_remove(self):
        link_id = self.linked(self.ada)

        response = self.remove(self.head, self.ada, link_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(MAY_NOT_LINK, response.json()["detail"])
        self.assertTrue(Guardianship.objects.filter(pk=link_id).exists())

    def test_a_link_cannot_be_removed_through_another_childs_address(self):
        link_id = self.linked(self.ada)

        response = self.remove(self.admin, self.bisi, link_id)

        self.assertEqual(response.status_code, 404)
        self.assertIn("not linked to this child", response.json()["detail"])
        self.assertTrue(Guardianship.objects.filter(pk=link_id).exists())

    def test_a_grace_administrator_cannot_remove_a_st_marys_link(self):
        link_id = self.linked(self.ada)

        response = self.remove(self.their_admin, self.ada, link_id, host=THEIR_HOST)

        self.assertEqual(response.status_code, 404)
        self.assertIn(NO_SUCH_CHILD, response.json()["detail"])
        self.assertTrue(Guardianship.objects.filter(pk=link_id).exists())


class TheServiceRefusesBeforeItCreatesTests(GuardiansSetUp):
    def test_a_refused_link_leaves_no_account_behind(self):
        """Authority before anything is created, so a refusal is not an
        orphan `User` with a stranger's number on it."""
        with self.assertRaises(guardian_contacts.NotPermitted):
            guardian_contacts.link_by_contact_as(
                self.head.user, self.ada, "Papa Obi", "08039999999"
            )

        self.assertFalse(User.objects.filter(phone="+2348039999999").exists())
