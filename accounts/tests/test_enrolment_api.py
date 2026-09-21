"""Admitting a child and putting them in a class, over HTTP.

Two schools in every test. Admission writes **shared** tables — a `User` and a
`Membership` — so the isolation that protects them is a real authority check
rather than the tenant schema, and a single-school fixture cannot fail for the
one thing most likely to be wrong: an administrator reaching into the other
school's roll.

The two authorities are different sets and the tests keep them apart:
`MEMBERSHIP_GRANTING_ROLES` is ADMIN alone, and `PLACEMENT_ROLES` is principal
and admin. A principal may move a child and may not admit one.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext

from academics.models import ClassPlacement, Term
from accounts.models import Membership, Role, User
from accounts.services import grant_membership
from results.tests.fixtures import HOST, PASSWORD, PORTAL, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

ROLL = "/api/enrolment/roll/"


class EnrolmentSetUp(ChainSetUp):
    """The chain fixture plus an administrator at each school.

    `RegisterSetUp` gives a teacher, a principal and a bursar; nobody in it can
    admit a child, because that is ADMIN alone.
    """

    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("amaka", PASSWORD, full_name="Amaka Obi"),
            self.stmarys,
            Role.ADMIN,
        )
        self.their_admin = grant_membership(
            User.objects.create_user("abeg", PASSWORD, full_name="Abeg Nwosu"),
            self.grace,
            Role.ADMIN,
        )

    def as_user(self, user):
        self.client.force_login(user.user)

    def get_roll(self, user, host=HOST):
        self.as_user(user)
        return self.client.get(ROLL, HTTP_HOST=host)

    def admit(self, user, host=HOST, **over):
        self.as_user(user)
        payload = {"full_name": "Chike Obi", "username": "STM/2026/0042", "reference": "0042"}
        payload.update(over)
        return self.client.post(
            ROLL, data=payload, content_type="application/json", HTTP_HOST=host
        )

    def place(self, user, membership_id, group_id, host=HOST):
        self.as_user(user)
        return self.client.put(
            f"{ROLL}{membership_id}/class/",
            data={"class_group_id": group_id},
            content_type="application/json",
            HTTP_HOST=host,
        )


class TheRollTests(EnrolmentSetUp):
    def names(self, response):
        return sorted(c["student"] for c in response.json()["children"])

    def test_the_roll_really_lists_children(self):
        """The control, and it runs first: every exclusion below would pass
        against a roll that returned nothing for everybody."""
        self.assertEqual(
            self.names(self.get_roll(self.admin)),
            ["Ada Obi", "Bimpe Ojo", "Bisi Ade", "Emeka Nwosu", "Tunde Cole"],
        )

    def test_one_schools_roll_never_contains_the_others_children(self):
        ours = self.names(self.get_roll(self.admin))
        theirs = self.names(self.get_roll(self.their_admin, host=THEIR_HOST))

        self.assertEqual(theirs, ["Chidi Eze"])
        self.assertNotIn("Chidi Eze", ours)

    def test_a_child_with_no_class_is_listed_with_a_null_group(self):
        """A child admitted in August and placed in September is ordinary. A
        roll that hid them would make the office think admission had failed."""
        admitted = self.admit(self.admin).json()

        rows = {c["student"]: c for c in self.get_roll(self.admin).json()["children"]}

        self.assertIn("Chike Obi", rows)
        self.assertIsNone(rows["Chike Obi"]["class_group_id"])
        self.assertEqual(rows["Chike Obi"]["student_membership_id"], admitted["student_membership_id"])

    def test_the_roll_does_not_cost_more_as_the_school_grows(self):
        """A per-child placement read would be one query per row on the page an
        office refreshes while admitting a class."""
        self.as_user(self.admin)
        self.client.get(ROLL, HTTP_HOST=HOST)

        with CaptureQueriesContext(connection) as small:
            self.client.get(ROLL, HTTP_HOST=HOST)

        for n in range(5):
            self.admit(self.admin, username=f"STM/2026/10{n}", full_name=f"Extra {n}")

        self.as_user(self.admin)
        with CaptureQueriesContext(connection) as larger:
            body = self.client.get(ROLL, HTTP_HOST=HOST).json()

        self.assertEqual(len(body["children"]), 10)
        self.assertEqual(
            len(larger.captured_queries),
            len(small.captured_queries),
            "the roll costs more when the school has more children",
        )

    def test_a_principal_sees_the_roll_and_is_told_she_may_not_admit(self):
        """**The two authorities are different sets.** A principal may move a
        child between classes and may not admit one."""
        body = self.get_roll(self.head).json()

        self.assertFalse(body["may_admit"])
        self.assertTrue(body["may_place"])

    def test_an_administrator_may_do_both(self):
        body = self.get_roll(self.admin).json()

        self.assertTrue(body["may_admit"])
        self.assertTrue(body["may_place"])

    def test_a_teacher_is_refused_before_anything_is_looked_up(self):
        response = self.get_roll(self.teacher)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Ada Obi", response.content.decode())

    def test_the_portal_has_no_such_route(self):
        self.assertEqual(self.get_roll(self.admin, host=PORTAL).status_code, 404)


class AdmittingAChildTests(EnrolmentSetUp):
    def test_a_child_is_admitted_with_the_handle_the_school_gave(self):
        """The control for every refusal below. The handle is school-issued and
        this does not invent one."""
        body = self.admit(self.admin).json()

        self.assertEqual(body["username"], "STM/2026/0042")
        self.assertEqual(body["reference"], "0042")
        membership = Membership.objects.get(pk=body["student_membership_id"])
        self.assertEqual(membership.school, self.stmarys)
        self.assertEqual(membership.role, Role.STUDENT)

    def test_the_new_account_cannot_be_signed_into_yet(self):
        """`create_user(username, None)` leaves an unusable password, and
        `IdentifierBackend` refuses one at the door. The account exists and
        nobody can use it, which is the honest state for a child just admitted."""
        body = self.admit(self.admin).json()

        user = Membership.objects.get(pk=body["student_membership_id"]).user
        self.assertFalse(user.has_usable_password())

    def test_a_principal_cannot_admit(self):
        """ADMIN alone. `accounts/models.py` says to add principals to
        `MEMBERSHIP_GRANTING_ROLES` if that changes, rather than widening here."""
        self.assertEqual(self.admit(self.head).status_code, 403)

    def test_a_teacher_cannot_admit(self):
        self.assertEqual(self.admit(self.teacher).status_code, 403)

    def test_an_administrator_at_one_school_cannot_admit_at_the_other(self):
        """`SchoolAccessMiddleware` answers before this router does — and the
        service's own `_require_grant_authority()` would refuse her too."""
        response = self.admit(self.admin, host=THEIR_HOST, username="GRC/2026/0001")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="GRC/2026/0001").exists())

    def test_a_handle_already_in_use_is_refused_without_saying_where(self):
        """The username is unique across the platform, so naming the school
        that holds it would tell a St Mary's administrator which children exist
        at Grace."""
        self.admit(self.admin)

        response = self.admit(self.admin, full_name="Somebody Else")
        detail = response.json()["detail"]

        self.assertEqual(response.status_code, 409)
        self.assertIn("STM/2026/0042", detail)
        for leaked in ("Grace", "St Mary", "school"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, detail)

    def test_a_failed_admission_leaves_no_account_behind(self):
        """**One transaction over both writes.** A failure between them would
        leave an account belonging to no school — unreachable, and something
        the next admission with that handle collides with."""
        before = User.objects.count()

        self.admit(self.admin, class_group_id=999_999)

        self.assertEqual(User.objects.count(), before, "an orphan account survived")

    def test_admitting_into_a_class_places_them_in_one_go(self):
        body = self.admit(self.admin, class_group_id=self.jss1a_id).json()

        self.assertEqual(body["class_group_id"], self.jss1a_id)
        with connected_to(self.stmarys):
            self.assertTrue(
                ClassPlacement.objects.filter(
                    student_membership_id=body["student_membership_id"],
                    class_group_id=self.jss1a_id,
                ).exists()
            )


class PlacingAChildTests(EnrolmentSetUp):
    def child(self):
        return self.children["ada"].pk

    def test_a_principal_may_place_and_move(self):
        """The control: placing and moving are one route and two services, and
        which is which is a fact about the child rather than the caller."""
        moved = self.place(self.head, self.child(), self.jss1b_id)

        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["class_group_id"], self.jss1b_id)

    def test_moving_back_is_an_ordinary_move(self):
        self.place(self.head, self.child(), self.jss1b_id)

        back = self.place(self.head, self.child(), self.jss1a_id)

        self.assertEqual(back.status_code, 200)
        self.assertEqual(back.json()["class_group_id"], self.jss1a_id)

    def test_an_unplaced_child_is_placed_rather_than_moved(self):
        admitted = self.admit(self.admin).json()

        placed = self.place(self.head, admitted["student_membership_id"], self.jss1a_id)

        self.assertEqual(placed.status_code, 200)
        self.assertEqual(placed.json()["class_group_id"], self.jss1a_id)

    def test_a_teacher_cannot_place(self):
        self.assertEqual(self.place(self.teacher, self.child(), self.jss1b_id).status_code, 403)

    def test_a_principal_at_one_school_cannot_place_at_the_other(self):
        response = self.place(
            self.head, self.grace_child.pk, self.grace_group_id, host=THEIR_HOST
        )

        self.assertEqual(response.status_code, 403)

    def test_the_other_schools_child_is_not_found_here(self):
        """Scoped in the lookup itself, so a membership at another school is
        simply absent rather than found and then refused."""
        response = self.place(self.admin, self.grace_child.pk, self.jss1a_id)

        self.assertEqual(response.status_code, 404)
