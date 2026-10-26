"""Start again: the principal clears the setup while there are no real records.

Two schools in every test, each set up the same way, so a clear that reached
the wrong schema, or a refusal that read the wrong school's records, shows.

## Controls

Each was broken on purpose, seen red, and restored:

- `may_start_again()` admitted the administrator as well: the administrator,
  teacher and other-school tests went red.
- One of `_BLOCKERS` (marks) was removed: `test_marks_stop_it` went red, and
  the clear went through with a mark in place.
- `_same_name()` returned True for anything: the wrong-name test went red.
- The fingerprint check was removed: the stale-plan test went red.
- Another school's principal: the page's role gate removed, `may_start_again()`
  made to accept a principal of any school, and `SchoolAccessMiddleware`'s
  no-membership refusal switched off, all three at once (each alone is enough
  to stop them): the other-school tests went red.
"""

from datetime import date, time

from django.db import connection
from django.test import TestCase

from academics.models import ClassGroup, ClassPlacement, ClassTeacher, StudentDetails, Term
from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from attendance.models import Register
from audit.models import Change
from fees import services as fees
from fees.models import FeeSchedule, FeeScheduleLine
from gradebook.models import Assessment, Score, Subject, SubjectTeacher, SubjectTeacherChange
from onboarding import again
from results.models import ResultSheet
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from timetable.models import Period, TimetableSlot

PASSWORD = "a-long-password-1"
HOST_A = "sunrise.testserver"
HOST_B = "harbour.testserver"


class StartAgainSetUp(TestCase):
    @classmethod
    def setUpTestData(cls):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)
        cls.a = make_school("Sunrise College", "sunrise", "sunrise")
        cls.b = make_school("Harbour College", "harbour", "harbour")
        Domain.objects.create(tenant=cls.a, domain=HOST_A, is_primary=True)
        Domain.objects.create(tenant=cls.b, domain=HOST_B, is_primary=True)

        def member(username, school, role):
            user = User.objects.create_user(username, PASSWORD, full_name=username.title())
            return grant_membership(user, school, role)

        cls.principal_a = member("kunle", cls.a, Role.PRINCIPAL)
        cls.admin_a = member("folake", cls.a, Role.ADMIN)
        cls.teacher_a = member("chidi", cls.a, Role.TEACHER)
        cls.bursar_a = member("aisha", cls.a, Role.BURSAR)
        cls.principal_b = member("bisi", cls.b, Role.PRINCIPAL)
        cls.teacher_b = member("emeka", cls.b, Role.TEACHER)
        cls.parent = User.objects.create_user("tunde", PASSWORD, full_name="Tunde Adeyemi")

        cls.made = {}
        for school, prefix, teacher in ((cls.a, "a", cls.teacher_a), (cls.b, "b", cls.teacher_b)):
            student = enroll_student(User.objects.create_user(f"{prefix}-s", PASSWORD, full_name="S"), school)
            if school is cls.a:
                link_guardian(cls.parent, student)
            with connected_to(school):
                term = Term.objects.create(
                    session="2026/2027", name="first", starts_on=date(2026, 9, 14),
                    ends_on=date(2026, 12, 18), is_current=True,
                )
                group = ClassGroup.objects.create(name="JSS 1A", level=1)
                subject = Subject.objects.create(name="Mathematics", code="MTH")
                paper = Assessment.objects.create(term=term, subject=subject, name="First CA", max_score=20)
                ClassPlacement.objects.create(class_group=group, term=term, student_membership_id=student.pk)
                ClassTeacher.objects.create(class_group=group, term=term, teacher_membership_id=teacher.pk)
                SubjectTeacher.objects.create(
                    term=term, class_group=group, subject=subject, teacher_membership_id=teacher.pk,
                )
                schedule = FeeSchedule.objects.create(term=term, class_group=group)
                FeeScheduleLine.objects.create(schedule=schedule, description="School fees", amount_kobo=4_500_000)
                period = Period.objects.create(starts_at=time(8), ends_at=time(8, 40), label="1")
                TimetableSlot.objects.create(
                    term=term, class_group=group, weekday=1, period=period, subject=subject,
                    teacher_membership_id=teacher.pk,
                )
                StudentDetails.objects.create(student_membership_id=student.pk, learner_id=f"{prefix.upper()}1")
                ResultSheet.objects.create(class_group=group, term=term)
            cls.made[school.pk] = dict(student=student, term=term, group=group, subject=subject, paper=paper)

    def tearDown(self):
        connection.set_schema_to_public()

    def page(self, member, host=HOST_A):
        if member is None:
            self.client.logout()
        else:
            self.client.force_login(member.user)
        response = self.client.get("/start/again/", HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def plan_of(self, school):
        with connected_to(school):
            return again.plan(school)

    def post(self, member, name, fingerprint=None, host=HOST_A, school=None):
        school = school or self.a
        if fingerprint is None:
            fingerprint = self.plan_of(school).fingerprint
        self.client.force_login(member.user)
        response = self.client.post(
            "/start/again/", {"school_name": name, "plan": fingerprint}, HTTP_HOST=host,
        )
        connection.set_schema_to_public()
        return response

    def counts(self, school):
        with connected_to(school):
            return {
                "terms": Term.objects.count(),
                "classes": ClassGroup.objects.count(),
                "subjects": Subject.objects.count(),
                "papers": Assessment.objects.count(),
                "fees": FeeScheduleLine.objects.count(),
                "slots": TimetableSlot.objects.count(),
                "placements": ClassPlacement.objects.count(),
                "details": StudentDetails.objects.count(),
                "log": Change.objects.count(),
            }

    def live_students(self, school):
        return Membership.objects.filter(
            school=school, role=Role.STUDENT, status=MembershipStatus.ACTIVE,
        ).count()

    FULL = {
        "terms": 1, "classes": 1, "subjects": 1, "papers": 1, "fees": 1, "slots": 1,
        "placements": 1, "details": 1, "log": 0,
    }


class ThePrincipalStartsAgainTests(StartAgainSetUp):
    def test_the_page_lists_exactly_what_will_be_cleared_and_what_stays(self):
        response = self.page(self.principal_a)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-again="possible"', html)
        self.assertIn("Terms: 1", html)
        self.assertIn("First term 2026/2027", html)
        self.assertIn("Classes: 1", html)
        self.assertIn("JSS 1A", html)
        self.assertIn("Students on the roll, and their details here: 1", html)
        self.assertIn("Subjects: 1", html)
        self.assertIn("Fee items: 1", html)
        self.assertIn("Every member of staff, their accounts, and invitations still waiting", html)
        self.assertIn("Type your school's name to confirm", html)

    def test_typing_the_name_clears_the_setup_and_nothing_else(self):
        response = self.post(self.principal_a, "  sunrise   COLLEGE ")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/start/?started-again=1")
        cleared = self.counts(self.a)
        self.assertEqual({k: v for k, v in cleared.items() if k != "log"}, {k: 0 for k in self.FULL if k != "log"})
        self.assertEqual(self.live_students(self.a), 0)
        ended = Membership.objects.get(pk=self.made[self.a.pk]["student"].pk)
        self.assertEqual(ended.status, MembershipStatus.ENDED)

        # Never the school, never a member of staff or their account.
        self.assertTrue(School.objects.filter(pk=self.a.pk).exists())
        for staff in (self.principal_a, self.admin_a, self.teacher_a, self.bursar_a):
            staff.refresh_from_db()
            staff.user.refresh_from_db()
            self.assertEqual(staff.status, MembershipStatus.ACTIVE)
            self.assertTrue(staff.user.is_active)
        # The parent's access went with their only child; their account did not.
        self.parent.refresh_from_db()
        self.assertTrue(self.parent.is_active)

    def test_it_is_logged_with_who_and_when(self):
        self.post(self.principal_a, "Sunrise College")

        with connected_to(self.a):
            row = Change.objects.get()
        self.assertEqual(row.action, "started-again")
        self.assertEqual(row.by_id, self.principal_a.user.pk)
        self.assertEqual(row.by_name, "Kunle")
        self.assertIn("principal", row.by_roles)
        self.assertIsNotNone(row.at)
        self.assertIn("1 classes", row.summary)

    def test_the_other_school_is_untouched(self):
        self.post(self.principal_a, "Sunrise College")

        self.assertEqual(self.counts(self.b), self.FULL)
        self.assertEqual(self.live_students(self.b), 1)

    def test_start_here_shows_it_happened_and_the_log(self):
        self.post(self.principal_a, "Sunrise College")
        self.client.force_login(self.principal_a.user)
        html = self.client.get("/start/?started-again=1", HTTP_HOST=HOST_A).content.decode()

        self.assertIn("Started again", html)
        self.assertIn("Started the setup again.", html)

    def test_a_term_a_permanent_record_names_is_kept_and_listed(self):
        made = self.made[self.a.pk]
        with connected_to(self.a):
            SubjectTeacherChange.objects.create(
                term=made["term"], kind="added", class_group_id=made["group"].pk,
                subject_id=made["subject"].pk, teacher_membership_id=self.teacher_a.pk,
                by_id=self.principal_a.user.pk, by_name="Kunle",
            )

        html = self.page(self.principal_a).content.decode()
        self.assertIn("The term First term 2026/2027", html)
        self.assertIn("the record of who taught what in it is kept for good", html)

        self.post(self.principal_a, "Sunrise College")
        cleared = self.counts(self.a)
        self.assertEqual(cleared["terms"], 1)
        self.assertEqual(cleared["classes"], 0)


class OnlyThePrincipalOfThisSchoolTests(StartAgainSetUp):
    def test_the_administrator_a_teacher_and_a_bursar_are_refused(self):
        for member in (self.admin_a, self.teacher_a, self.bursar_a):
            with self.subTest(role=member.role):
                self.assertEqual(self.page(member).status_code, 403)
                self.assertEqual(self.post(member, "Sunrise College").status_code, 403)
        self.assertEqual(self.counts(self.a), self.FULL)

    def test_another_schools_principal_cannot_clear_this_school(self):
        response = self.post(self.principal_b, "Sunrise College", host=HOST_A)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.counts(self.a), self.FULL)
        self.assertEqual(self.counts(self.b), self.FULL)

    def test_another_schools_principal_sees_nothing_of_this_schools_setup(self):
        html = self.page(self.principal_b, host=HOST_A).content.decode()

        self.assertNotIn("JSS 1A", html)
        self.assertNotIn("data-again", html)

    def test_signed_out_is_told_to_sign_in(self):
        html = self.page(None).content.decode()

        self.assertIn("Please sign in", html)
        self.assertNotIn("data-again", html)

    def test_start_here_offers_it_to_the_principal_only(self):
        for member, shown in ((self.principal_a, True), (self.admin_a, False)):
            self.client.force_login(member.user)
            html = self.client.get("/start/", HTTP_HOST=HOST_A).content.decode()
            with self.subTest(role=member.role):
                self.assertEqual("data-start-again" in html, shown)


class ItNeedsTheNameAndTheSamePlanTests(StartAgainSetUp):
    def test_the_wrong_name_clears_nothing(self):
        for typed in ("", "Sunrise", "Harbour College"):
            with self.subTest(typed=typed):
                response = self.post(self.principal_a, typed)
                self.assertEqual(response.status_code, 422)
                self.assertIn("Type your school", response.content.decode())
        self.assertEqual(self.counts(self.a), self.FULL)

    def test_a_plan_that_moved_on_clears_nothing(self):
        stale = self.plan_of(self.a).fingerprint
        with connected_to(self.a):
            ClassGroup.objects.create(name="JSS 1B", level=1)

        response = self.post(self.principal_a, "Sunrise College", fingerprint=stale)

        self.assertEqual(response.status_code, 422)
        self.assertIn("Something changed since this page was opened", response.content.decode())
        self.assertEqual(self.counts(self.a)["classes"], 2)


class RealRecordsStopItTests(StartAgainSetUp):
    def assertStopped(self, why):
        html = self.page(self.principal_a).content.decode()
        self.assertIn('data-again="refused"', html)
        self.assertIn(why, html.lower())
        self.assertNotIn("<form", html.split('data-again="refused"')[1].split("</article>")[0])

        response = self.post(self.principal_a, "Sunrise College")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.counts(self.a)["classes"], 1)
        self.assertEqual(self.counts(self.a)["log"], 0)
        self.assertEqual(self.live_students(self.a), 1)

    def test_marks_stop_it(self):
        made = self.made[self.a.pk]
        with connected_to(self.a):
            Score.objects.create(assessment=made["paper"], student_membership_id=made["student"].pk, value=12)
        self.assertStopped("marks have been entered")

    def test_attendance_stops_it(self):
        made = self.made[self.a.pk]
        with connected_to(self.a):
            Register.objects.create(
                class_group=made["group"], term=made["term"], taken_on=date(2026, 9, 15),
                taken_by_id=self.teacher_a.pk,
            )
        self.assertStopped("a register has been taken")

    def test_fees_stop_it(self):
        made = self.made[self.a.pk]
        with connected_to(self.a):
            fees.charge(made["student"], made["term"], 100_000, narration="School fees")
        self.assertStopped("fees have been charged")

    def test_released_results_stop_it(self):
        made = self.made[self.a.pk]
        with connected_to(self.a):
            ResultSheet.objects.filter(class_group=made["group"], term=made["term"]).delete()
            ResultSheet.objects.create(class_group=made["group"], term=made["term"], state="released")
        self.assertStopped("results have been released")

    def test_another_schools_records_do_not_stop_this_one(self):
        made = self.made[self.b.pk]
        with connected_to(self.b):
            Score.objects.create(assessment=made["paper"], student_membership_id=made["student"].pk, value=12)

        self.assertEqual(self.post(self.principal_a, "Sunrise College").status_code, 302)
        self.assertEqual(self.counts(self.b)["papers"], 1)
