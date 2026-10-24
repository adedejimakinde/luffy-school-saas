"""The line under each role's name says what that role may do, and is true.

`accounts.models.ROLE_DESCRIPTIONS` is shown where a role is chosen (the staff
invite's picker). Each line makes claims, and each claim here is checked against
the role set that grants it, so a change to what a role may do fails this test
rather than leaving a sentence on the page that has stopped being true. The two
lines first offered for the principal and the teacher were not: the principal
cannot invite staff, admit a child or record a payment ("full access"), and a
teacher may take any class's register, not only an assigned one's.
"""

from django.test import SimpleTestCase

from accounts.models import MEMBERSHIP_GRANTING_ROLES, ROLE_DESCRIPTIONS, STAFF_ROLES, Role
from academics.services import PLACEMENT_ROLES, SETUP_ROLES
from attendance.services import MARKING_ROLES
from fees.authority import WRITING_ROLES as FEES_WRITING_ROLES
from gradebook.assignments import ASSIGNING_ROLES
from gradebook.services import MARK_ENTERING_ROLES
from results.comments_api import VIEWING_ROLES as REMARK_ROLES
from results.services import APPROVING_ROLES, CHECKING_ROLES, RELEASING_ROLES, SENDING_BACK_ROLES
from timetable.services import EDITING_ROLES as TIMETABLE_EDITING_ROLES

ADMIN = Role.ADMIN.value
BURSAR = Role.BURSAR.value
PRINCIPAL = Role.PRINCIPAL.value
TEACHER = Role.TEACHER.value
VP = Role.VICE_PRINCIPAL_ACADEMIC.value


class EveryStaffRoleHasALineTests(SimpleTestCase):
    def test_every_staff_role_and_no_other(self):
        self.assertEqual(set(ROLE_DESCRIPTIONS), set(STAFF_ROLES))

    def test_each_line_is_short_and_has_no_dash(self):
        for role, line in ROLE_DESCRIPTIONS.items():
            with self.subTest(role=role):
                self.assertLessEqual(len(line), 60)
                self.assertNotRegex(line, "[–—]")


class EachLineIsTrueTests(SimpleTestCase):
    def test_administrator_runs_the_records(self):
        """Admits children and invites staff, alone; sets the school up; takes payments."""
        self.assertEqual(ROLE_DESCRIPTIONS[ADMIN], "Runs day-to-day school records")
        self.assertEqual(MEMBERSHIP_GRANTING_ROLES, {ADMIN})
        for granted in (SETUP_ROLES, PLACEMENT_ROLES, FEES_WRITING_ROLES):
            self.assertIn(ADMIN, granted)

    def test_bursar_records_fees_and_payments(self):
        self.assertEqual(ROLE_DESCRIPTIONS[BURSAR], "Records fees and payments")
        self.assertIn(BURSAR, FEES_WRITING_ROLES)

    def test_principal_approves_and_releases_and_assigns(self):
        self.assertEqual(ROLE_DESCRIPTIONS[PRINCIPAL], "Approves and releases results, assigns subject teachers")
        self.assertEqual(APPROVING_ROLES, {PRINCIPAL})
        self.assertEqual(RELEASING_ROLES, {PRINCIPAL})
        self.assertEqual(ASSIGNING_ROLES, {PRINCIPAL})

    def test_principal_is_not_full_access(self):
        """Why "Full access and final approvals" was not used."""
        self.assertNotIn(PRINCIPAL, MEMBERSHIP_GRANTING_ROLES)
        self.assertNotIn(PRINCIPAL, FEES_WRITING_ROLES)
        self.assertNotIn("access", ROLE_DESCRIPTIONS[PRINCIPAL].lower())

    def test_teacher_takes_registers_enters_marks_and_writes_remarks(self):
        self.assertEqual(ROLE_DESCRIPTIONS[TEACHER], "Takes registers, enters marks and writes remarks")
        for granted in (MARKING_ROLES, MARK_ENTERING_ROLES, REMARK_ROLES):
            self.assertIn(TEACHER, granted)

    def test_teacher_line_does_not_say_assigned_classes(self):
        """Any teacher may take any class's register (`docs/attendance.md`, A5),
        and marking narrows only once a term has subject teachers, so "for
        assigned classes" would be untrue of registers."""
        self.assertNotIn("assigned", ROLE_DESCRIPTIONS[TEACHER])

    def test_vice_principal_oversees_results_and_teaching(self):
        """Checks results (alone) and sends them back; keeps the timetable."""
        self.assertEqual(ROLE_DESCRIPTIONS[VP], "Oversees results and teaching")
        self.assertEqual(CHECKING_ROLES, {VP})
        self.assertIn(VP, SENDING_BACK_ROLES)
        self.assertIn(VP, TIMETABLE_EDITING_ROLES)
