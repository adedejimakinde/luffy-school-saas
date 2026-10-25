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
from django.test import SimpleTestCase, TestCase, override_settings
from django_tenants.utils import schema_context

from academics.models import ClassPlacement, Term
from accounts.models import GuardianContact, Membership, MembershipStatus, Role, User
from attendance.models import Register
from fees.models import FeeConcession, FeeEntryKind, FeeLedgerEntry, FeeSchedule
from gradebook.models import Assessment, Score
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

    def the_cards_match_the_template(self, slug):
        """Sunrise prints the Ogun sheet and its cards say so; Harbour is Standard.

        What a card froze is what it prints: the Ogun layout, the sheet's twelve
        trait lines and its rating key, and the child's learner's ID, sex and date
        of birth (made up) filled in. Harbour's carry the Standard card's.
        """
        from academics.models import StudentDetails
        from results import ogun
        from results.models import ReleasedCard, ReleasedTraitRating, ReportCardSettings

        cards = ReleasedCard.objects.all()
        self.assertEqual(cards.count(), 10, "JSS 1B was released, JSS 1A was not")
        if slug == "sunrise-demo":
            self.assertEqual(ReportCardSettings.objects.get().template, "ogun")
            self.assertEqual({c.template for c in cards}, {"ogun"})
            for card in cards:
                names = list(ReleasedTraitRating.objects.filter(card=card).order_by("group", "position").values_list("trait_name", flat=True))
                self.assertEqual(names, [*ogun.AFFECTIVE, *ogun.PSYCHOMOTOR], card.student_name)
                self.assertEqual([tuple(p) for p in card.rating_scale], [(v, label) for v, label in ogun.SCALE])
            details = StudentDetails.objects.all()
            self.assertEqual(details.count(), 20, "every Sunrise child has details")
            for row in details:
                self.assertTrue(row.learner_id and row.sex and row.date_of_birth, row.student_membership_id)
            self.assertEqual(len({row.learner_id for row in details}), 20)
        else:
            self.assertEqual(ReportCardSettings.objects.get().template, "standard")
            self.assertEqual({c.template for c in cards}, {"standard"})
            self.assertFalse(StudentDetails.objects.exists())

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
                    # The first paper in every subject for everybody (60), and
                    # the rest for JSS 1B alone (10 children x 3 subjects x 3
                    # papers at Sunrise, which sets four; x 1 at Harbour, which
                    # sets two) — released, so a released card with a paper a
                    # dash would be a card that lied about the term it printed.
                    papers = [(a.name, a.max_score) for a in Assessment.objects.filter(subject__name="Mathematics", term=term).order_by("position")]
                    if slug == "sunrise-demo":
                        # The Ogun sheet's papers, so the headings are its own.
                        self.assertEqual(papers, [("1st Test", 10), ("2nd Test", 10), ("Assignment", 10), ("Exam", 70)])
                        self.assertEqual(Score.objects.count(), 150)
                    else:
                        self.assertEqual(papers, [("First CA", 20), ("Exam", 60)])
                        self.assertEqual(Score.objects.count(), 90)
                    self.assertEqual(Register.objects.count(), 20)
                    self.the_cards_match_the_template(slug)
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
                        # Sunrise prints the Ogun sheet's twelve lines, Harbour the seeded eleven.
                        10 * (12 if slug == "sunrise-demo" else 11),
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


class SeedUiTests(SendsThroughTheFake, TestCase):
    """`seed_ui`: a class and children of its own for each file in `tests/ui/`.

    The files run side by side against one demo, and two that wrote to one class
    raced: the offline register was held whenever the import admitted children
    into the same class mid-test. No two files may share a class again.
    """

    def tearDown(self):
        connection.set_schema_to_public()

    @override_settings(DEBUG=True)
    def test_each_file_gets_a_class_and_children_nobody_else_has(self):
        from academics.models import ClassGroup
        from schools.management.commands.seed_ui import CLASSES, LEVEL

        with self.assertRaisesMessage(CommandError, "Run seed_demo first"):
            call_command("seed_ui", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())
        call_command("seed_ui", stdout=StringIO())

        school = School.objects.get(slug="sunrise-demo")
        with schema_context(school.schema_name):
            term = Term.objects.get(is_current=True)
            seen = set()
            for name, _, count in CLASSES:
                with self.subTest(name=name):
                    group = ClassGroup.objects.get(name=name)
                    self.assertEqual(group.level, LEVEL, "after JSS 1A and JSS 1B in every list")
                    members = set(ClassPlacement.objects.filter(class_group=group, term=term).values_list("student_membership_id", flat=True))
                    self.assertEqual(len(members), count)
                    self.assertFalse(members & seen, "a child in two of the tests' classes")
                    seen |= members
            demo = set(ClassPlacement.objects.filter(class_group__name__in=("JSS 1A", "JSS 1B")).values_list("student_membership_id", flat=True))
            self.assertFalse(seen & demo, "a test's child in a demo class")
        with self.assertRaisesMessage(CommandError, "already here"):
            call_command("seed_ui", stdout=StringIO())

    def test_it_will_not_run_in_production(self):
        with override_settings(DEBUG=False):
            with self.assertRaisesMessage(CommandError, "only runs with DEBUG on"):
                call_command("seed_ui", stdout=StringIO())

    def test_no_two_browser_test_files_name_the_same_class(self):
        """Each class the browser tests use is named in one file of `tests/ui/`
        only, and every file that writes names its own: none picks "the first"."""
        from pathlib import Path

        from django.conf import settings

        from schools.management.commands.seed_ui import CLASSES

        files = {path.name: path.read_text() for path in (Path(settings.BASE_DIR) / "tests" / "ui").glob("*.test.js")}
        names = ["JSS 1A", "JSS 1B", *(name for name, _, _ in CLASSES)]
        for name in names:
            with self.subTest(name=name):
                using = [file for file, text in files.items() if name in text]
                self.assertEqual(len(using), 1, f"{name} is named in {using}")
        owners = {"offline.test.js": "UI Offline", "marking_clear.test.js": "UI Marking Clear",
                  "marking_focus.test.js": "UI Marking Focus", "roll_import_gap.test.js": "UI Import",
                  "teaching.test.js": "UI Teaching", "screens.test.js": "JSS 1A"}
        # Files that write no school's data at all, so have no class to own:
        # the blog's, which writes only the blog (`docs/blog.md`), the
        # picker's, which refuses every write in the browser, and a school
        # website's, which only reads Harbour's published pages. Each must name
        # no class, which is what keeps it out of the others' way.
        classless = {"blog.test.js", "picker.test.js", "school_site.test.js"}
        self.assertEqual(set(owners) | classless, set(files), "a browser test file with no class of its own")
        for file in classless:
            with self.subTest(file=file):
                self.assertFalse([name for name in names if name in files[file]])
        for file, name in owners.items():
            with self.subTest(file=file):
                self.assertIn(name, files[file])
                self.assertNotRegex(files[file], r"""\[data-action="(open|pick-class|pick-assessment)"\]'\)\.first\(\)""")


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

    A full, ordinary day at the size of a real school, held rather than hoped
    for, because the homepage prints these figures beside the screens: 612
    students, ₦48.6m of ₦71.2m paid, seven classes waiting on the principal and
    nothing else asked of her, about 94% in each day and nobody on the absences
    list, and the star's card on the Ogun State sheet.
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
    def test_a_school_having_a_full_ordinary_day(self):
        from attendance import absences
        from home import summary
        from results.cards import card_for
        from results.models import ReportCardSettings, ResultSheet, SheetState
        from schools import showcase

        out = self.load()
        self.assertNotIn(PASSWORD, out)
        school = School.objects.get(slug="showcase-demo")
        self.assertIn("Demo", school.name, "the name says it is a demo")
        self.assertFalse(School.objects.filter(slug__in=SLUGS).exists(), "only the showcase is made")
        principal = User.objects.get(username="crestfield.principal")
        star = Membership.objects.get(user__username="crestfield.s001")
        self.assertTrue(star.guardianships.filter(guardian__username="crestfield.parent").exists())
        students = Membership.objects.filter(school=school, role=Role.STUDENT)
        self.assertEqual(students.count(), 612)
        self.assertFalse(any(u.has_usable_password() for u in User.objects.filter(memberships__in=students)))
        # The screens' avatars carry the letters of the name the home greets:
        # Mr Oyelaran is MO, not MS (`menu.initials`, `home.dashboard.first_name`).
        from home.dashboard import first_name
        from menu import initials

        for user in User.objects.filter(username__startswith="crestfield.").exclude(memberships__in=students):
            with self.subTest(login=user.username):
                self.assertEqual(initials(user.full_name), initials(first_name(user)))

        with schema_context(school.schema_name):
            term = Term.objects.get(is_current=True)
            self.assertEqual(ReportCardSettings.objects.get().template, "ogun")
            card = card_for(star, term)
            self.assertAlmostEqual(float(card.own_average), 78, delta=1.5)
            # "Times school opened" is a number on the sheet: the term's 61 weekdays.
            self.assertEqual(term.school_days, 61)
            self.assertEqual(card.days_open, 61)
            # One school code: the learner ID and the admission number agree.
            from academics.models import StudentDetails

            self.assertEqual(star.reference, "CFC/001")
            self.assertEqual(StudentDetails.objects.get(student_membership_id=star.pk).learner_id, "CFC-2013-0001")
            grades = list(card.subject_results.values_list("grade_letter", flat=True))
            self.assertEqual(len(grades), 6)
            self.assertLessEqual(set(grades), {"A1", "B2", "B3"})
            self.assertGreater(card.days_present, 0)
            self.assertEqual(card.comments.count(), 2, "both remarks")

            states = dict(ResultSheet.objects.values_list("class_group__name", "state"))
            self.assertEqual(states, {**{name: SheetState.RELEASED for name in showcase.RELEASED},
                                      **{name: SheetState.CHECKED for name in showcase.WAITING}})
            self.assertEqual(absences.flagged(school, term), [])
            roles = frozenset(principal.roles_at(school))
            waiting = summary.waiting(principal, roles, term, summary.lagos_today())
            self.assertEqual({row.kind for row in waiting}, {summary.APPROVE})
            self.assertEqual(len(waiting), 7)

            # Every register in today but SS 1A's, which the screenshots take on screen,
            # and about 94% in on each day.
            today = summary.lagos_today()
            taken = set(Register.objects.filter(taken_on=today).values_list("class_group__name", flat=True))
            self.assertEqual(taken, {name for name, _ in showcase.CLASSES} - {"SS 1A"})
            from attendance.models import AttendanceMark, AttendanceStatus
            marks = AttendanceMark.objects.filter(register__taken_on=today)
            present = marks.exclude(status=AttendanceStatus.ABSENT).count() / marks.count()
            self.assertAlmostEqual(present, 0.94, delta=0.015)
            self.assertTrue(Score.objects.filter(assessment__name="1st Test").exists())

            billed = sum(FeeLedgerEntry.objects.filter(kind=FeeEntryKind.CHARGE).values_list("amount_kobo", flat=True))
            paid = sum(FeeLedgerEntry.objects.filter(kind=FeeEntryKind.PAYMENT).values_list("amount_kobo", flat=True))
            self.assertEqual(billed, 71_206_200 * 100)
            self.assertEqual(abs(paid), 48_600_000 * 100)

        with self.assertRaisesMessage(CommandError, "already here"):
            self.load()


class TheShowcaseRegistersAreAboutNinetyFourPercentOnEveryDayTests(SimpleTestCase):
    """`showcase._away_on()`, for every day of the week and across month ends.

    `ShowcaseTests` seeds the showcase on the day it runs and asserts that today's
    registers are about 94% in. The dealing of absences depends on how many days
    there are to deal over, which depends on the weekday: on a Wednesday there are
    28, 7 divides 28, and the registers were 80% in, so that test failed every
    Wednesday and passed every other day. It passed on Tuesday the 20th and failed
    on Wednesday the 21st of October 2026, in the same commit. A date-dependent
    result is only caught by running on every date, so this does: the dealing is
    a pure function of the children and the days, and runs here for 28 dates.
    """

    CHILDREN = 612

    def deal(self, today):
        from datetime import timedelta
        from types import SimpleNamespace

        from schools import showcase

        starts = today - timedelta(days=today.weekday()) - timedelta(weeks=5)
        days = sorted(set(showcase._weekdays(starts, today)) | {today})
        children = [SimpleNamespace(pk=i + 1) for i in range(self.CHILDREN)]
        star = children[0]
        return days, children, star, showcase._away_on(children, star, days)

    def dates(self):
        from datetime import date, timedelta

        # Four whole weeks, so every weekday four times, straddling a month end.
        return [date(2026, 10, 19) + timedelta(days=n) for n in range(28)]

    def test_about_94_percent_are_in_on_every_date(self):
        for today in self.dates():
            with self.subTest(today=str(today), weekday=today.strftime("%A")):
                days, children, star, away = self.deal(today)
                absent_today = sum(1 for pks in away.values() if today in pks)
                share_in = 1 - absent_today / (len(children) - 1)
                self.assertAlmostEqual(share_in, 0.94, delta=0.015)

    def test_every_other_child_is_away_once_or_twice_and_the_star_never(self):
        for today in self.dates():
            with self.subTest(today=str(today)):
                days, children, star, away = self.deal(today)
                self.assertNotIn(star.pk, away)
                self.assertEqual(len(away), len(children) - 1)
                self.assertTrue(all(1 <= len(pks) <= 2 for pks in away.values()))
                self.assertTrue(all(pks <= set(days) for pks in away.values()))

    def test_a_day_the_old_stride_worked_on_is_dealt_exactly_as_before(self):
        from math import gcd

        for today in self.dates():
            days, children, star, away = self.deal(today)
            if gcd(7, len(days)) != 1:
                continue
            with self.subTest(today=str(today)):
                old = {
                    c.pk: {days[(i * 7) % len(days)]} | ({days[(i * 7 + 13) % len(days)]} if i % 5 else set())
                    for i, c in enumerate(children) if c is not star
                }
                self.assertEqual(away, old)
