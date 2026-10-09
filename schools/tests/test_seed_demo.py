"""`manage.py seed_demo`: two fake schools, and never in production.

The schools are created the real way — `School.save()` migrates each schema —
because the command's whole job is to leave a database somebody can click
through, and a clone would test the template rather than that.
"""

import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django_tenants.utils import schema_context

from academics.models import ClassPlacement, Term
from accounts.models import GuardianContact, Membership, MembershipStatus, Role, User
from attendance.models import Register
from fees.models import FeeConcession, FeeEntryKind, FeeLedgerEntry, FeeSchedule
from gradebook.models import Score
from messaging.tests.fake import SendsThroughTheFake
from notices.models import Notice
from schools.models import Domain, School
from timetable.models import Period, TimetableSlot, Weekday

SLUGS = ("sunrise-demo", "harbour-demo")


class SeedDemoTests(SendsThroughTheFake, TestCase):
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

    @override_settings(DEBUG=True, MESSAGING_PROVIDERS={"email": "", "phone": ""})
    def test_it_will_not_run_without_the_fake_phone_provider(self):
        """CONTROL 3: removing the provider guard makes this red.

        The parent's phone number is a real number's shape, and `tell_families()`
        would hand it straight to whatever `MESSAGING_PHONE_PROVIDER` names.
        """
        with self.assertRaisesMessage(CommandError, "only runs with the fake message provider"):
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
                parent_membership = Membership.objects.get(school=school, role=Role.PARENT)
                self.assertEqual(parent_membership.status, MembershipStatus.ACTIVE)
                # A verified channel too, so "tell families" below has
                # somewhere real to land.
                contact = GuardianContact.objects.get(guardian__user=parent_membership.user)
                self.assertTrue(contact.is_live)
                self.assertEqual(contact.value, "+2348031234567")

                with schema_context(school.schema_name):
                    term = Term.objects.get(is_current=True)
                    self.assertEqual(ClassPlacement.objects.filter(term=term).count(), 20)
                    # A first CA in every subject for everybody (60), and an
                    # exam for JSS 1B alone (10 children x 3 subjects) —
                    # released, so a released card with every exam a dash
                    # would be a card that lied about the term it printed.
                    self.assertEqual(Score.objects.count(), 90)
                    self.assertEqual(Register.objects.count(), 20)
                    # The card's "Next term begins" line has something to
                    # read, and it does not fall after the term it follows.
                    self.assertTrue(term.next_term_starts_on)
                    self.assertGreater(term.next_term_starts_on, term.ends_on)
                    # "Tell families" (D9) was turned on and pressed for JSS 1B's
                    # release: one guardian, the demo parent, is reachable there.
                    [notice] = Notice.objects.all()
                    self.assertEqual(notice.contact_id, contact.pk)
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

                    # JSS 1A is left open with four of ten principal's
                    # remarks written, so the principal's home has a class
                    # waiting on her, and a teacher still has a sheet to mark.
                    from results.models import CommentAuthor, ReportCardComment, ResultSheet, TraitRating

                    self.assertEqual(
                        ResultSheet.objects.get(term=term, class_group__name="JSS 1A").state, "draft"
                    )
                    jss1a = ClassPlacement.objects.filter(term=term, class_group__name="JSS 1A")
                    self.assertEqual(
                        ReportCardComment.objects.filter(
                            term=term, author=CommentAuthor.PRINCIPAL,
                            student_membership_id__in=jss1a.values("student_membership_id"),
                        ).count(),
                        4,
                    )

                    # JSS 1B is released, so its card has to carry every
                    # section the report card page and PDF can show: both
                    # signatories' remarks and a rating on every trait,
                    # rather than one remark and a blank conduct section.
                    jss1b = ClassPlacement.objects.filter(term=term, class_group__name="JSS 1B")
                    jss1b_ids = jss1b.values("student_membership_id")
                    for author in (CommentAuthor.CLASS_TEACHER, CommentAuthor.PRINCIPAL):
                        self.assertEqual(
                            ReportCardComment.objects.filter(
                                term=term, author=author, student_membership_id__in=jss1b_ids,
                            ).count(),
                            10,
                            author,
                        )
                    self.assertEqual(
                        TraitRating.objects.filter(term=term, student_membership_id__in=jss1b_ids).count(),
                        10 * 11,
                        "not every child rated on every trait",
                    )

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


PASSWORD = "a-long-demo-password-1"


class LoadDemoTests(TestCase):
    """`manage.py load_demo`: the same schools on a server with DEBUG off."""

    def tearDown(self):
        connection.set_schema_to_public()

    def load(self, env=None, **options):
        out = StringIO()
        base = {"DEMO_SERVER": "1", "LOAD_DEMO_PASSWORD": PASSWORD}
        with mock.patch.dict(os.environ, {**base, **(env or {})}):
            call_command("load_demo", "--domain-suffix=classnode.test", stdout=out, **options)
        return out.getvalue()

    def refused(self, env, message):
        for key in ("DEMO_SERVER", "LOAD_DEMO_PASSWORD"):
            os.environ.pop(key, None)
        with mock.patch.dict(os.environ, env):
            with self.assertRaisesMessage(CommandError, message):
                call_command("load_demo", "--domain-suffix=classnode.test", stdout=StringIO())
        self.assertFalse(School.objects.filter(slug__in=SLUGS).exists())

    @override_settings(DEBUG=False)
    def test_it_refuses_without_demo_server(self):
        """CONTROL 1: removing the DEMO_SERVER guard makes this red."""
        self.refused({"LOAD_DEMO_PASSWORD": PASSWORD}, "DEMO_SERVER=1")
        self.refused({"DEMO_SERVER": "0", "LOAD_DEMO_PASSWORD": PASSWORD}, "DEMO_SERVER=1")

    @override_settings(DEBUG=False)
    def test_it_has_no_default_password(self):
        """CONTROL 2: falling back to seed_demo's published password makes this red."""
        self.refused({"DEMO_SERVER": "1"}, "LOAD_DEMO_PASSWORD")
        self.refused({"DEMO_SERVER": "1", "LOAD_DEMO_PASSWORD": "short"}, "at least 12")

    @override_settings(DEBUG=False)
    def test_with_debug_off_it_loads_the_same_schools_with_the_given_password(self):
        out = self.load()

        self.assertNotIn(PASSWORD, out)
        self.assertNotIn("demo-pass-2026", out)
        for slug in SLUGS:
            school = School.objects.get(slug=slug)
            self.assertTrue(Domain.objects.filter(tenant=school, domain=f"{slug}.classnode.test").exists())
            self.assertEqual(Membership.objects.filter(school=school, role=Role.STUDENT.value).count(), 20)
            with schema_context(school.schema_name):
                self.assertEqual(ClassPlacement.objects.filter(term=Term.objects.get(is_current=True)).count(), 20)
        admin = User.objects.get(username="sunrise.admin")
        self.assertTrue(admin.check_password(PASSWORD))
        self.assertFalse(admin.check_password("demo-pass-2026"))

    @override_settings(DEBUG=False)
    def test_nobody_is_messaged_and_no_phone_is_stored(self):
        """CONTROL 3: telling families, or storing the phone, makes this red."""
        self.load()

        self.assertFalse(GuardianContact.objects.exists())
        for slug in SLUGS:
            with schema_context(School.objects.get(slug=slug).schema_name):
                self.assertFalse(Notice.objects.exists())

    @override_settings(DEBUG=False)
    def test_it_will_not_run_twice(self):
        self.load()

        with self.assertRaisesMessage(CommandError, "already here"):
            self.load()

    def a_real_school(self):
        return School.objects.create(name="Real School", slug="real-school", schema_name="real_school")

    @override_settings(DEBUG=False)
    def test_it_refuses_when_a_school_that_is_not_a_demo_school_exists(self):
        """CONTROL 4: removing the real-school guard makes this red."""
        self.a_real_school()

        with self.assertRaisesMessage(CommandError, "real-school"):
            self.load()
        with self.assertRaisesMessage(CommandError, "real-school"):
            self.load(showcase=True)

        self.assertFalse(School.objects.filter(slug__in=SLUGS + ("showcase-demo",)).exists())

    @override_settings(DEBUG=False)
    def test_the_demo_schools_do_not_trip_it(self):
        self.load(showcase=True)

        self.assertTrue(School.objects.filter(slug="showcase-demo").exists())
        with self.assertRaisesMessage(CommandError, "already here"):
            self.load(showcase=True)
        self.load()
        self.assertEqual(School.objects.filter(slug__in=SLUGS).count(), 2)


class ShowcaseTests(TestCase):
    """`load_demo --showcase`: the school the homepage's screenshots are taken from.

    A good day, held rather than hoped for: the star's card, nothing waiting on
    the principal, nobody on the absences list, and the one open class with no
    sheet to raise a row for.
    """

    def tearDown(self):
        connection.set_schema_to_public()

    def load(self, env=None):
        out = StringIO()
        base = {"DEMO_SERVER": "1", "LOAD_DEMO_PASSWORD": PASSWORD}
        with mock.patch.dict(os.environ, {**base, **(env or {})}):
            call_command("load_demo", "--showcase", "--domain-suffix=classnode.test", stdout=out)
        return out.getvalue()

    @override_settings(DEBUG=False)
    def test_it_refuses_without_demo_server(self):
        os.environ.pop("DEMO_SERVER", None)
        with mock.patch.dict(os.environ, {"LOAD_DEMO_PASSWORD": PASSWORD}):
            with self.assertRaisesMessage(CommandError, "DEMO_SERVER=1"):
                call_command("load_demo", "--showcase", "--domain-suffix=classnode.test", stdout=StringIO())
        self.assertFalse(School.objects.filter(slug="showcase-demo").exists())

    @override_settings(DEBUG=False)
    def test_a_school_having_a_good_day(self):
        from attendance import absences
        from home import summary
        from results.cards import card_for
        from results.models import ResultSheet, SheetState

        out = self.load()
        self.assertNotIn(PASSWORD, out)
        school = School.objects.get(slug="showcase-demo")
        self.assertFalse(School.objects.filter(slug__in=SLUGS).exists(), "only the showcase is made")
        principal = User.objects.get(username="crestfield.principal")
        star = Membership.objects.get(user__username="crestfield.s01")
        self.assertTrue(star.guardianships.filter(guardian__username="crestfield.parent").exists())

        with schema_context(school.schema_name):
            term = Term.objects.get(is_current=True)
            card = card_for(star, term)
            self.assertAlmostEqual(float(card.own_average), 78, delta=1.5)
            grades = list(card.subject_results.values_list("grade_letter", flat=True))
            self.assertEqual(len(grades), 6)
            self.assertLessEqual(set(grades), {"A1", "B2", "B3"})
            self.assertGreater(card.days_present, 0)
            self.assertEqual(card.comments.count(), 2, "both remarks")

            states = dict(ResultSheet.objects.values_list("class_group__name", "state"))
            self.assertEqual(states, {"JSS 2A": SheetState.RELEASED, "JSS 2B": SheetState.RELEASED})
            self.assertEqual(absences.flagged(school, term), [])
            roles = frozenset(principal.roles_at(school))
            self.assertEqual(summary.waiting(principal, roles, term, summary.lagos_today()), [])
            # Every register in today but SS 1A's, which the screenshots take on screen.
            taken = set(Register.objects.filter(taken_on=summary.lagos_today()).values_list("class_group__name", flat=True))
            self.assertEqual(taken, {"JSS 2A", "JSS 2B"})
            self.assertTrue(Score.objects.filter(assessment__name="First CA").exists())

    @override_settings(DEBUG=False)
    def test_it_will_not_run_twice(self):
        self.load()
        with self.assertRaisesMessage(CommandError, "already here"):
            self.load()
