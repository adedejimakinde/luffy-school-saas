"""`manage.py seed_demo`: two fake schools, and never in production.

The schools are created the real way — `School.save()` migrates each schema —
because the command's whole job is to leave a database somebody can click
through, and a clone would test the template rather than that.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django_tenants.utils import schema_context

from academics.models import ClassPlacement, Term
from accounts.models import Membership, MembershipStatus, Role
from attendance.models import Register
from fees.models import FeeConcession, FeeEntryKind, FeeLedgerEntry, FeeSchedule
from gradebook.models import Score
from schools.models import Domain, School
from timetable.models import Period, TimetableSlot, Weekday

SLUGS = ("sunrise-demo", "harbour-demo")


class SeedDemoTests(TestCase):
    def tearDown(self):
        connection.set_schema_to_public()

    def seed(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        return out.getvalue()

    def test_it_will_not_run_in_production(self):
        """CONTROL 1: removing the `DEBUG` guard makes this red."""
        with override_settings(DEBUG=False):
            with self.assertRaisesMessage(CommandError, "only runs with DEBUG on"):
                self.seed()

        self.assertFalse(School.objects.filter(slug__in=SLUGS).exists())

    @override_settings(DEBUG=True)
    def test_two_schools_each_with_a_term_of_data_and_a_login_per_role(self):
        out = self.seed()

        for slug in SLUGS:
            with self.subTest(school=slug):
                school = School.objects.get(slug=slug)
                self.assertTrue(Domain.objects.filter(tenant=school, domain=f"{slug}.localhost").exists())
                roles = list(
                    Membership.objects.filter(school=school).values_list("role", flat=True)
                )
                self.assertEqual(roles.count(Role.STUDENT.value), 20)
                for role in (Role.ADMIN, Role.PRINCIPAL, Role.VICE_PRINCIPAL_ACADEMIC,
                             Role.BURSAR, Role.PARENT):
                    self.assertEqual(roles.count(role.value), 1, role)
                # One per subject, so the timetable can be clash-free.
                self.assertEqual(roles.count(Role.TEACHER.value), 3)
                # CONTROL 2: leaving the parent INVITED, as `link_guardian()`
                # grants it, makes this red — and the demo parent sees nothing.
                self.assertEqual(
                    Membership.objects.get(school=school, role=Role.PARENT).status,
                    MembershipStatus.ACTIVE,
                )

                with schema_context(school.schema_name):
                    term = Term.objects.get(is_current=True)
                    self.assertEqual(ClassPlacement.objects.filter(term=term).count(), 20)
                    self.assertEqual(Score.objects.count(), 60)
                    self.assertEqual(Register.objects.count(), 20)
                    # Every child charged both lines of their class's bill, by the
                    # bill: each charge names the line that billed it.
                    charges = FeeLedgerEntry.objects.filter(kind=FeeEntryKind.CHARGE)
                    self.assertEqual(charges.count(), 40)
                    self.assertFalse(charges.filter(source_line__isnull=True).exists())
                    later = FeeSchedule.objects.get(term=term, class_group__name="JSS 1B").lines.get(
                        description="Excursion"
                    )
                    self.assertFalse(later.entries.exists(), "the line added later was charged")
                    [revoked] = FeeConcession.objects.filter(revocation__isnull=False)
                    self.assertEqual(
                        (revoked.revocation.reason, bool(revoked.revocation.revoked_by_name)),
                        ("The bursary ended with last session", True),
                    )
                    self.assertFalse(revoked.entries.exists(), "a revoked concession was given")
                    self.assertTrue(FeeConcession.objects.standing().get().entries.exists())
                    balances = {
                        child: FeeLedgerEntry.objects.for_student(child).balance()
                        for child in FeeLedgerEntry.objects.values_list("student_membership_id", flat=True).distinct()
                    }
                    self.assertTrue(any(b < 0 for b in balances.values()), "nobody is in credit")
                    self.assertTrue(any(b > 0 for b in balances.values()), "nobody owes anything")
                    self.assertTrue(FeeLedgerEntry.objects.filter(kind=FeeEntryKind.DISCOUNT).exists())

                    # The week: five periods, both classes, one free period.
                    self.assertEqual(Period.objects.count(), 5)
                    week = TimetableSlot.objects.filter(term=term)
                    self.assertEqual(week.count(), 5 * 5 * 2 - 1)
                    last = Period.objects.order_by("-starts_at").first()
                    combined = week.filter(weekday=Weekday.FRIDAY, period=last)
                    self.assertEqual(
                        len({(s.subject_id, s.teacher_membership_id) for s in combined}), 1,
                        "Friday's last period is not one lesson for both classes",
                    )
                    self.assertEqual(combined.count(), 2)
                    self.assertTrue(
                        Term.objects.filter(starts_on__gt=term.starts_on).exists(),
                        "no next term to copy the timetable into",
                    )
                    self.assertFalse(TimetableSlot.objects.exclude(term=term).exists())
        self.assertIn("Every password:", out)
        self.assertIn("sunrise.bursar", out)

    @override_settings(DEBUG=True)
    def test_a_second_run_is_refused_and_changes_nothing(self):
        self.seed()
        users = Membership.objects.count()

        with self.assertRaisesMessage(CommandError, "already here"):
            self.seed()

        self.assertEqual(Membership.objects.count(), users)
