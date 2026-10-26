"""Guided onboarding: the administrator's steps, who may open them, where
sign-in lands, the setup chip, help, the first-days cards and the handover.

Two schools in every test that touches a school's data, for the reason every
fixture in this repository gives: a step that read the wrong schema would pass
any single-school test, and "done" is exactly the kind of answer that looks
right whichever school it was read from.

## Controls

Each claim below marked "control" was broken on purpose, seen red, and
restored; the pull request that added this file lists what was broken and
which tests went red.
"""

import json
import re
from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from academics.models import ClassGroup, Term
from accounts.models import MembershipStatus, Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from fees.models import FeeSchedule, FeeScheduleLine
from gradebook.models import Assessment, Subject
from onboarding import first, handover, progress
from results.models import ReportCardSettings
from schools.delivery import EmailChannel
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school

PASSWORD = "a-long-password-1"
PORTAL = "testserver"
HOST_A = "sunrise.testserver"
HOST_B = "harbour.testserver"

_STEP = re.compile(r'data-step="([\w-]+)" data-step-state="(\w+)"')


class TwoSchools(TestCase):
    """Sunrise and Harbour, each with an administrator, and everybody else at
    Sunrise. Nothing set up at either."""

    @classmethod
    def setUpTestData(cls):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

        cls.a = make_school("Sunrise College", "sunrise", "sunrise")
        cls.b = make_school("Harbour College", "harbour", "harbour")
        Domain.objects.create(tenant=cls.a, domain=HOST_A, is_primary=True)
        Domain.objects.create(tenant=cls.b, domain=HOST_B, is_primary=True)

        def member(username, school, role, name):
            return grant_membership(
                User.objects.create_user(username, PASSWORD, full_name=name, email=f"{username}@example.com"),
                school,
                role,
            )

        cls.admin_a = member("folake", cls.a, Role.ADMIN, "Folake Adebayo")
        cls.admin_b = member("bisi", cls.b, Role.ADMIN, "Bisi Ojo")
        cls.teacher_a = member("chidi", cls.a, Role.TEACHER, "Chidi Okonkwo")
        cls.bursar_a = member("aisha", cls.a, Role.BURSAR, "Aisha Bello")
        cls.principal_a = member("kunle", cls.a, Role.PRINCIPAL, "Kunle Lawal")
        cls.parent_a = member("tunde", cls.a, Role.PARENT, "Tunde Adeyemi")
        cls.ops = User.objects.create_user("ops", PASSWORD, full_name="Ola Operator", is_platform_staff=True)

    def setUp(self):
        # The dashboard caches a school's figures per schema and day, and
        # every test here reuses the same two schools.
        cache.clear()
        self.addCleanup(cache.clear)

    def tearDown(self):
        connection.set_schema_to_public()

    # -- making things exist ------------------------------------------------------

    def details(self, school):
        School.objects.filter(pk=school.pk).update(contact_email=f"office@{school.slug}.example")
        school.refresh_from_db()
        with connected_to(school):
            ReportCardSettings.objects.filter(pk=1).update(crest=b"\x89PNG")

    def term(self, school):
        with connected_to(school):
            return Term.objects.create(
                session="2026/2027", name="first", starts_on=date(2026, 9, 14),
                ends_on=date(2026, 12, 18), is_current=True,
            )

    def a_class(self, school, name="JSS 1A"):
        with connected_to(school):
            return ClassGroup.objects.create(name=name, level=1)

    def subject(self, school):
        with connected_to(school):
            return Subject.objects.create(name="Mathematics", code="MTH")

    def teacher(self, school, username):
        return grant_membership(User.objects.create_user(username, PASSWORD, full_name="T"), school, Role.TEACHER)

    def student(self, school, username):
        return enroll_student(User.objects.create_user(username, PASSWORD, full_name="S"), school)

    def fee_line(self, school, term, group):
        with connected_to(school):
            schedule = FeeSchedule.objects.create(term=term, class_group=group)
            FeeScheduleLine.objects.create(schedule=schedule, description="School fees", amount_kobo=4_500_000)

    def paper(self, school, term, subject):
        with connected_to(school):
            Assessment.objects.create(term=term, subject=subject, name="First CA", max_score=20)

    def set_up_everything(self, school, prefix):
        self.details(school)
        term = self.term(school)
        group = self.a_class(school)
        subject = self.subject(school)
        self.teacher(school, f"{prefix}-t")
        self.student(school, f"{prefix}-s")
        self.paper(school, term, subject)
        return term, group

    # -- reading ------------------------------------------------------------------

    def steps_of(self, school):
        school.refresh_from_db()
        return progress.progress_for(school)

    def states(self, school):
        return {s.step.key: s.state for s in self.steps_of(school).steps}

    def get(self, member, path, host=HOST_A, **extra):
        if member is None:
            self.client.logout()
        else:
            self.client.force_login(member.user if hasattr(member, "user") else member)
        response = self.client.get(path, HTTP_HOST=host, **extra)
        connection.set_schema_to_public()
        return response


# -- done is read from the data ---------------------------------------------------------


class DoneStatesFlipAsDataArrivesTests(TwoSchools):
    def test_a_new_school_has_nothing_done_and_nothing_locked(self):
        states = self.states(self.a)

        self.assertEqual(
            states,
            {
                "school-details": "next",
                "session-and-term": "todo",
                "classes": "todo",
                "subjects": "todo",
                # The fixture's teacher is already invited at Sunrise.
                "teachers": "done",
                "students": "todo",
                "fees": "todo",
                "report-card": "todo",
            },
        )
        self.assertEqual(self.steps_of(self.a).done, 1)

    def test_each_step_is_done_the_moment_its_data_exists(self):
        self.details(self.a)
        self.assertEqual(self.states(self.a)["school-details"], "done")

        term = self.term(self.a)
        self.assertEqual(self.states(self.a)["session-and-term"], "done")

        group = self.a_class(self.a)
        self.assertEqual(self.states(self.a)["classes"], "done")

        subject = self.subject(self.a)
        self.assertEqual(self.states(self.a)["subjects"], "done")

        self.teacher(self.a, "new-teacher")
        self.assertEqual(self.states(self.a)["teachers"], "done")

        self.student(self.a, "new-student")
        self.assertEqual(self.states(self.a)["students"], "done")

        self.fee_line(self.a, term, group)
        self.assertEqual(self.states(self.a)["fees"], "done")

        self.paper(self.a, term, subject)
        steps = self.steps_of(self.a)
        self.assertEqual(steps.by_key["report-card"].state, "done")
        self.assertEqual(steps.done, 8)
        self.assertTrue(steps.complete)

    def test_the_school_details_need_both_the_email_and_the_crest(self):
        School.objects.filter(pk=self.a.pk).update(contact_email="office@sunrise.example")
        self.assertNotEqual(self.states(self.a)["school-details"], "done")

        with connected_to(self.a):
            ReportCardSettings.objects.filter(pk=1).update(crest=b"\x89PNG")
        self.assertEqual(self.states(self.a)["school-details"], "done")

    def test_undone_again_when_the_data_goes(self):
        group = self.a_class(self.a)
        self.assertEqual(self.states(self.a)["classes"], "done")

        with connected_to(self.a):
            ClassGroup.objects.filter(pk=group.pk).update(is_active=False)
        self.assertNotEqual(self.states(self.a)["classes"], "done")

    def test_fees_are_optional_and_never_the_next_step(self):
        self.set_up_everything(self.a, "a")
        steps = self.steps_of(self.a)

        self.assertEqual(steps.by_key["fees"].state, "todo")
        self.assertTrue(steps.complete)
        self.assertIsNone(steps.next)

    def test_finishing_is_written_down_once(self):
        self.set_up_everything(self.a, "a")
        self.steps_of(self.a)
        first_time = School.objects.get(pk=self.a.pk).setup_completed_at

        self.assertIsNotNone(first_time)
        self.steps_of(self.a)
        self.assertEqual(School.objects.get(pk=self.a.pk).setup_completed_at, first_time)


class NoStepIsLockedTests(TwoSchools):
    """Every step opens with its own action whatever else is done. Control:
    the step page's action was hidden while a hint shows (`may_do and not
    hint`), and the every-step and students-before-classes tests went red;
    restored."""

    def test_every_step_page_offers_its_own_action(self):
        for step in progress.STEPS:
            if step.key == "school-details":
                continue
            with self.subTest(step=step.key):
                html = self.get(self.admin_a, f"/start/{step.key}/").content.decode()
                self.assertIn(f'data-step="{step.key}" data-step-state=', html)
                self.assertIn(f'href="{step.href}"', html)
                self.assertNotIn('data-step-state="locked"', html)

    def test_students_before_classes_is_a_hint_with_the_import_still_offered(self):
        html = self.get(self.admin_a, "/start/students/").content.decode()

        self.assertIn('data-hint="classes"', html)
        self.assertIn('href="/start/classes/"', html)
        self.assertIn('href="/roll/import/"', html)

    def test_the_hint_goes_once_what_it_names_is_there(self):
        self.a_class(self.a)

        html = self.get(self.admin_a, "/start/students/").content.decode()

        self.assertNotIn("data-hint=", html)
        self.assertIn('href="/roll/import/"', html)

    def test_students_imported_before_classes_count_as_done(self):
        self.student(self.a, "early")

        self.assertEqual(self.states(self.a)["students"], "done")

    def test_the_term_step_no_longer_says_saving_makes_it_current(self):
        html = self.get(self.admin_a, "/start/session-and-term/").content.decode()

        self.assertNotIn("It becomes the current term", html)
        self.assertIn("Tap Make current", html)

    def test_a_term_saved_but_not_current_is_not_done_and_says_so(self):
        with connected_to(self.a):
            Term.objects.create(
                session="2026/2027", name="first", starts_on=date(2026, 9, 14), ends_on=date(2026, 12, 18),
            )
        html = self.get(self.admin_a, "/start/session-and-term/").content.decode()

        self.assertNotEqual(self.states(self.a)["session-and-term"], "done")
        self.assertIn("A term is saved but not current yet", html)


# -- "Add later" for the contact email and the crest --------------------------------


class AddLaterTests(TwoSchools):
    """Control: `put_off_as()` lost its `can_set_up()` check, and the
    service-level test went red (the page's gate and the school host's
    membership check still stopped the HTTP callers, as they should); restored."""

    def later(self, member, what, host=HOST_A):
        self.client.force_login(member.user)
        response = self.client.post("/start/school-details/", {"what": what}, HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def log_of(self, school):
        from audit.models import Change

        with connected_to(school):
            return list(Change.objects.order_by("id").values_list("action", "kind", "by_id"))

    def test_both_put_off_moves_the_administrator_on_and_is_logged(self):
        for what in ("contact-email", "crest"):
            self.assertEqual(self.later(self.admin_a, what).status_code, 302)

        steps = self.steps_of(self.a)
        self.assertEqual(steps.by_key["school-details"].state, "done")
        self.assertEqual(steps.next.step.key, "session-and-term")
        self.assertEqual(
            self.log_of(self.a),
            [("put-off", "contact-email", self.admin_a.user.pk), ("put-off", "crest", self.admin_a.user.pk)],
        )

    def test_the_principal_may_put_off_too(self):
        self.assertEqual(self.later(self.principal_a, "contact-email").status_code, 302)
        self.assertIsNotNone(School.objects.get(pk=self.a.pk).contact_email_later_at)

    def test_saying_it_twice_is_one_record(self):
        self.later(self.admin_a, "crest")
        self.later(self.admin_a, "crest")

        self.assertEqual(len(self.log_of(self.a)), 1)

    def test_a_teacher_a_bursar_and_a_parent_may_not(self):
        for member in (self.teacher_a, self.bursar_a, self.parent_a):
            with self.subTest(role=member.role):
                self.assertEqual(self.later(member, "crest").status_code, 403)
        self.assertIsNone(School.objects.get(pk=self.a.pk).crest_later_at)
        self.assertEqual(self.log_of(self.a), [])

    def test_another_schools_administrator_may_not_put_off_this_schools(self):
        response = self.later(self.admin_b, "contact-email", host=HOST_A)

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(School.objects.get(pk=self.a.pk).contact_email_later_at)
        self.assertIsNone(School.objects.get(pk=self.b.pk).contact_email_later_at)
        self.assertEqual(self.log_of(self.a), [])
        self.assertEqual(self.log_of(self.b), [])

    def test_the_service_itself_refuses_a_teacher_and_another_schools_administrator(self):
        """Behind the page's own gate and the school host's: called directly."""
        from onboarding import later

        school = School.objects.get(pk=self.a.pk)
        for actor in (self.teacher_a.user, self.admin_b.user):
            with self.subTest(actor=actor.username), self.assertRaises(later.NotAllowedToPutOff):
                later.put_off_as(actor, school, "crest")
        self.assertIsNone(School.objects.get(pk=self.a.pk).crest_later_at)

    def test_something_else_is_refused_and_changes_nothing(self):
        response = self.later(self.admin_a, "name")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.log_of(self.a), [])

    def test_the_page_offers_add_later_and_says_why_it_is_safe(self):
        html = self.get(self.admin_a, "/start/school-details/").content.decode()

        self.assertIn('data-later="contact-email"', html)
        self.assertIn('data-later="crest"', html)
        self.assertIn("Neither is needed to sign in or to get back into an account", html)

    def test_once_put_off_start_here_and_then_the_dashboard_remind(self):
        self.later(self.admin_a, "contact-email")
        self.later(self.admin_a, "crest")
        start = self.get(self.admin_a, "/start/").content.decode()

        # The dashboard's list of things to do starts once the school has
        # students; until then Start here carries the reminder.
        self.student(self.a, "first-child")
        home = self.get(self.admin_a, "/home/").content.decode()

        self.assertIn("Add your school&#x27;s contact email", home)
        self.assertIn("Add your school&#x27;s crest", home)
        self.assertIn("data-later-card", start)

    def test_the_reminder_goes_once_the_email_is_given(self):
        self.later(self.admin_a, "contact-email")
        School.objects.filter(pk=self.a.pk).update(contact_email="office@sunrise.example")

        start = self.get(self.admin_a, "/start/").content.decode()

        self.assertNotIn("Your school&#x27;s contact email", start)


# -- tenant isolation ---------------------------------------------------------------------


class OneSchoolsProgressNeverReflectsAnothersTests(TwoSchools):
    """Control: `_read_here()` was pointed at the other school's schema id,
    and both tests went red."""

    def test_harbour_set_up_in_full_leaves_sunrise_at_nothing(self):
        self.set_up_everything(self.b, "b")

        # Sunrise's one step done is its own teacher, from the fixture.
        self.assertEqual(self.steps_of(self.a).done, 1)
        self.assertEqual(self.steps_of(self.b).done, 7)

        html = self.get(self.admin_a, "/start/").content.decode()
        self.assertIn("1 of 8 done", html)
        self.assertIn('data-step="classes" data-step-state="todo"', html)

    def test_read_from_another_schools_connection_still_reads_its_own(self):
        self.set_up_everything(self.b, "b")

        with connected_to(self.b):
            facts = progress.read(self.a)
            self.assertEqual(connection.schema_name, "harbour")

        self.assertEqual(facts["classes"], 0)
        self.assertEqual(facts["students"], 0)
        self.assertFalse(facts["term"])

    def test_memberships_are_counted_at_this_school_only(self):
        self.teacher(self.b, "b-teacher")
        self.student(self.b, "b-student")

        facts = progress.read(self.a)

        # Sunrise has its one teacher from the fixture, and no student.
        self.assertEqual(facts["teachers"], 1)
        self.assertEqual(facts["students"], 0)


# -- who may open what ---------------------------------------------------------------------


class TheAdministratorAndThePrincipalOpenTheStepsTests(TwoSchools):
    """Control: `ONBOARDING_ROLES` was widened to every staff role and the
    refusal tests went red; and narrowed back to the administrator alone, and
    the principal's went red."""

    PATHS = ("/start/", "/start/school-details/", "/start/classes/", "/start/students/")

    def test_the_administrator_and_the_principal_open_every_step(self):
        for member in (self.admin_a, self.principal_a):
            for path in self.PATHS + tuple(f"/start/{s.key}/" for s in progress.STEPS):
                with self.subTest(role=member.role, path=path):
                    self.assertEqual(self.get(member, path).status_code, 200)

    def test_the_principal_gets_no_setup_chip_on_the_steps(self):
        for path in ("/start/", "/start/classes/"):
            with self.subTest(path=path):
                self.assertNotIn("setup-chip", self.get(self.principal_a, path).content.decode())
                self.assertIn("setup-chip", self.get(self.admin_a, path).content.decode())

    def test_a_step_the_principal_cannot_do_says_who_does(self):
        html = self.get(self.principal_a, "/start/students/").content.decode()

        self.assertIn("This step is done by your school administrator.", html)
        self.assertNotIn('href="/roll/import/"', html)

    def test_a_teacher_a_bursar_and_a_parent_are_refused(self):
        for member in (self.teacher_a, self.bursar_a, self.parent_a):
            for path in self.PATHS:
                with self.subTest(role=member.role, path=path):
                    response = self.get(member, path)
                    html = response.content.decode()
                    self.assertEqual(response.status_code, 403)
                    self.assertIn("This page is not yours", html)
                    self.assertNotIn("data-step=", html)
                    self.assertNotIn("Your next step", html)

    def test_another_schools_administrator_is_refused(self):
        response = self.get(self.admin_b, "/start/", host=HOST_A)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"Sunrise College", response.content)

    def test_signed_out_is_told_to_sign_in_and_shown_nothing(self):
        html = self.get(None, "/start/classes/").content.decode()

        self.assertIn("Please sign in", html)
        self.assertNotIn("data-step=", html)

    def test_an_unknown_step_is_not_found(self):
        self.assertEqual(self.get(self.admin_a, "/start/nonsense/").status_code, 404)


class TheHandoverPageIsThePlatformsAloneTests(TwoSchools):
    """Control: the platform-staff check in `handover_page()` was removed and
    the refusal tests went red."""

    def test_platform_staff_see_every_school(self):
        html = self.get(self.ops, "/platform/handover/", host=PORTAL).content.decode()

        self.assertIn("New school handover", html)
        self.assertIn("Sunrise College", html)
        self.assertIn("Harbour College", html)

    def test_the_page_has_the_platforms_menu_and_a_sign_out(self):
        """It was a logo and a card: an operator on a shared computer could not end the session."""
        html = self.get(self.ops, "/platform/handover/", host=PORTAL).content.decode()

        for href in ("/platform/", "/platform/handover/", "/admin/"):
            self.assertIn(f'href="{href}"', html)
        self.assertIn('action="/sign-out/"', html)

    def test_a_schools_own_staff_and_strangers_are_refused(self):
        for member in (self.admin_a, self.teacher_a, self.bursar_a, self.principal_a, self.parent_a, None):
            with self.subTest(member=getattr(member, "role", "signed out")):
                response = self.get(member, "/platform/handover/", host=PORTAL)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(b"Sunrise College", response.content)
                self.assertNotIn(b"data-welcome", response.content)

    def test_a_schools_host_has_no_such_page(self):
        for member in (self.admin_a, self.ops):
            self.assertEqual(self.get(member, "/platform/handover/").status_code, 404)

    def test_a_school_administrator_cannot_record_the_agreement(self):
        self.client.force_login(self.admin_a.user)
        response = self.client.post(
            "/platform/handover/", {"school": "sunrise", "signed_on": "2026-10-01"}, HTTP_HOST=PORTAL
        )

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(School.objects.get(pk=self.a.pk).pilot_agreement_signed_on)


# -- where signing in lands ------------------------------------------------------------------


class SignInSendsAnUnfinishedAdministratorToStartHereTests(TwoSchools):
    def sign_in(self, username):
        self.client.logout()
        token = self.client.get("/api/csrf/", HTTP_HOST=PORTAL).json()["csrf_token"]
        response = self.client.post(
            "/api/login/",
            data=json.dumps({"identifier": username, "password": PASSWORD}),
            content_type="application/json",
            HTTP_HOST=PORTAL,
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        return {s["slug"]: s["start_here"] for s in response.json()["schools"]}

    def test_an_administrator_with_setup_unfinished_goes_to_start_here(self):
        self.assertEqual(self.sign_in("folake"), {"sunrise": True})

    def test_a_finished_administrator_keeps_the_normal_landing(self):
        self.set_up_everything(self.a, "a")

        self.assertEqual(self.sign_in("folake"), {"sunrise": False})

    def test_finished_once_never_redirects_again_even_if_a_step_comes_undone(self):
        self.set_up_everything(self.a, "a")
        self.steps_of(self.a)
        with connected_to(self.a):
            ClassGroup.objects.update(is_active=False)

        self.assertEqual(self.sign_in("folake"), {"sunrise": False})

    def test_nobody_else_is_sent_anywhere(self):
        for username in ("chidi", "aisha", "kunle"):
            with self.subTest(username=username):
                self.assertEqual(self.sign_in(username), {"sunrise": False})

    def test_one_schools_finished_setup_does_not_stop_the_other_schools_administrator(self):
        """Control: `_schools_of()` was made to read "has any school finished"
        and this went red. It first survived that control, because Sunrise's
        finish had never been written down; it is written down here first."""
        self.set_up_everything(self.a, "a")
        self.steps_of(self.a)
        self.assertIsNotNone(School.objects.get(pk=self.a.pk).setup_completed_at)

        self.assertEqual(self.sign_in("bisi"), {"harbour": True})


class HomeNeverRedirectsTests(TwoSchools):
    def test_an_unfinished_administrator_gets_home_with_the_next_step_on_top(self):
        response = self.get(self.admin_a, "/home/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-next="school-details"', html)
        self.assertLess(html.index('data-next="school-details"'), html.index('data-setup='))

    def test_a_finished_administrator_gets_home_with_no_card_and_no_chip(self):
        self.set_up_everything(self.a, "a")
        html = self.get(self.admin_a, "/home/").content.decode()

        self.assertNotIn("data-next=", html)
        self.assertNotIn("setup-chip", html)

    def test_start_here_always_offers_the_dashboard(self):
        for state in ("new", "finished"):
            if state == "finished":
                self.set_up_everything(self.a, "a")
            with self.subTest(state=state):
                html = self.get(self.admin_a, "/start/").content.decode()
                self.assertIn('href="/home/">Skip to dashboard', html)

    def test_finished_start_here_is_the_first_register(self):
        self.set_up_everything(self.a, "a")
        html = self.get(self.admin_a, "/start/").content.decode()

        self.assertIn("Take your first register", html)
        self.assertIn('href="/register/"', html)


# -- the setup chip ---------------------------------------------------------------------------


class TheSetupChipTests(TwoSchools):
    def test_an_unfinished_administrator_sees_it_on_staff_pages(self):
        for path in ("/home/", "/setup/", "/roll/", "/help/"):
            with self.subTest(path=path):
                self.assertIn("Setup 1 of 8", self.get(self.admin_a, path).content.decode())

    def test_never_on_the_pages_kept_offline(self):
        for path in ("/register/", "/marking/"):
            with self.subTest(path=path):
                html = self.get(self.admin_a, path).content.decode()
                self.assertNotIn("setup-chip", html)
                self.assertNotIn("Setup 1 of 8", html)

    def test_nobody_but_the_administrator_sees_it(self):
        """The principal may open Start here, but setup is not pushed at them."""
        for member in (self.teacher_a, self.bursar_a, self.principal_a):
            with self.subTest(role=member.role):
                self.assertNotIn("setup-chip", self.get(member, "/home/").content.decode())

    def test_gone_once_setup_is_finished(self):
        self.set_up_everything(self.a, "a")

        self.assertNotIn("setup-chip", self.get(self.admin_a, "/setup/").content.decode())

    def test_the_count_is_this_schools(self):
        self.set_up_everything(self.b, "b")
        self.details(self.a)

        self.assertIn("Setup 2 of 8", self.get(self.admin_a, "/setup/").content.decode())


# -- a fixed number of queries ------------------------------------------------------------------


#: What the handover page costs: the floor (session, user, the schools, their
#: hosts, the portal's host) and, per school, its administrator, its first
#: invitation, and its steps with the search path set and put back.
FLOOR = 18
PER_SCHOOL = 6


class AFixedNumberOfQueriesTests(TwoSchools):
    def count(self, member, path, host=HOST_A):
        self.client.force_login(getattr(member, "user", member))
        self.client.get(path, HTTP_HOST=host)  # warm the session
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path, HTTP_HOST=host)
        connection.set_schema_to_public()
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_start_here_costs_the_same_at_a_bare_school_and_a_busy_one(self):
        bare = self.count(self.admin_a, "/start/")
        self.set_up_everything(self.b, "b")
        for n in range(5):
            self.a_class(self.b, f"JSS {n}B")
            self.student(self.b, f"b-more-{n}")
        busy = self.count(self.admin_b, "/start/", host=HOST_B)

        self.assertEqual(bare, busy)

    def test_the_steps_are_one_statement(self):
        with CaptureQueriesContext(connection) as queries:
            progress.read(self.a)
        own = [q for q in queries.captured_queries if "search_path" not in q["sql"].lower()]

        self.assertEqual(len(own), 1)

    def test_the_chip_costs_an_administrator_one_statement_and_anyone_else_none(self):
        unfinished = self.count(self.admin_a, "/setup/")
        teacher = self.count(self.teacher_a, "/timetable/")
        self.set_up_everything(self.a, "a")
        self.steps_of(self.a)  # finished, and written down
        finished = self.count(self.admin_a, "/setup/")
        teacher_after = self.count(self.teacher_a, "/timetable/")

        self.assertEqual(unfinished - finished, 2)  # the statement and its search path
        self.assertEqual(teacher, teacher_after)

    def another_school(self, slug):
        school = make_school(f"{slug.title()} College", slug, slug)
        grant_membership(User.objects.create_user(f"{slug}-admin", PASSWORD, full_name="A"), school, Role.ADMIN)

    def test_the_handover_page_costs_a_fixed_amount_per_school(self):
        """A platform page over every school: a fixed floor, and a fixed few
        statements per school (its administrator, its invitation, its steps
        in its own schema), however much each school holds."""
        two = self.count(self.ops, "/platform/handover/", host=PORTAL)
        self.another_school("third")
        three = self.count(self.ops, "/platform/handover/", host=PORTAL)
        self.set_up_everything(self.b, "b")
        busy = self.count(self.ops, "/platform/handover/", host=PORTAL)
        self.another_school("fourth")
        four = self.count(self.ops, "/platform/handover/", host=PORTAL)

        self.assertEqual(two, PER_SCHOOL * 2 + FLOOR)
        self.assertEqual(three - two, PER_SCHOOL)
        self.assertEqual(busy, three)
        self.assertEqual(four - three, PER_SCHOOL)


# -- help and next steps -------------------------------------------------------------------------


class HelpTests(TwoSchools):
    def test_tips_for_the_page_you_came_from_and_back_to_it(self):
        html = self.get(self.admin_a, "/help/", HTTP_REFERER=f"http://{HOST_A}/roll/").content.decode()

        self.assertIn('data-tips="roll"', html)
        self.assertIn('href="/roll/">Go back', html)

    def test_a_referer_from_another_site_is_ignored_and_back_is_home(self):
        html = self.get(self.admin_a, "/help/", HTTP_REFERER="https://evil.example/roll/").content.decode()

        self.assertIn('data-tips="general"', html)
        self.assertIn('href="/home/">Go back', html)
        self.assertNotIn("evil.example", html)

    def test_no_referer_is_home(self):
        self.assertIn('href="/home/">Go back', self.get(self.teacher_a, "/help/").content.decode())

    def test_a_teacher_reads_nothing_about_fees_whatever_the_referer_says(self):
        html = self.get(self.teacher_a, "/help/", HTTP_REFERER=f"http://{HOST_A}/fees/").content.decode()

        tips = html.split('data-tips="general"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("fee", tips.lower())
        self.assertNotIn('data-tips="fees"', html)

    def test_support_is_the_email_and_two_working_days(self):
        html = self.get(self.bursar_a, "/help/").content.decode()

        self.assertIn("hello@classnode.co", html)
        self.assertIn("We reply within two working days.", html)

    def test_a_parent_is_not_offered_the_staff_help_page(self):
        self.assertEqual(self.get(self.parent_a, "/help/").status_code, 403)

    def test_every_staff_role_has_it_in_the_sidebar(self):
        for member in (self.admin_a, self.teacher_a, self.bursar_a, self.principal_a):
            with self.subTest(role=member.role):
                self.assertIn('href="/help/"', self.get(member, "/home/").content.decode())


# -- first days -----------------------------------------------------------------------------------


class FirstDaysCardsTests(TwoSchools):
    def home(self, member, now=None):
        if now is None:
            return self.get(member, "/home/").content.decode()
        with mock.patch("onboarding.first.now", return_value=now):
            return self.get(member, "/home/").content.decode()

    def test_a_teacher_sees_the_register_and_marks_and_nothing_about_fees(self):
        html = self.home(self.teacher_a)

        self.assertIn('data-first="teacher"', html)
        self.assertIn('data-first-action="register"', html)
        self.assertIn('data-first-action="marks"', html)
        self.assertNotIn('data-first="bursar"', html)
        self.assertNotIn('data-first-action="fees"', html)

    def test_a_bursar_sees_fees_and_a_payment(self):
        html = self.home(self.bursar_a)

        self.assertIn('data-first="bursar"', html)
        self.assertNotIn('data-first="teacher"', html)

    def test_the_administrator_and_the_principal_get_no_first_days_card(self):
        for member in (self.admin_a, self.principal_a):
            self.assertNotIn("data-first=", self.home(member))

    def test_gone_once_the_teacher_has_done_both(self):
        term = self.term(self.a)
        group = self.a_class(self.a)
        subject = self.subject(self.a)
        child = self.student(self.a, "kid")
        from attendance import services as registers
        from gradebook import services as gradebook

        with connected_to(self.a):
            from academics.models import ClassPlacement

            ClassPlacement.objects.create(class_group=group, term=term, student_membership_id=child.pk)
            paper = Assessment.objects.create(term=term, subject=subject, name="First CA", max_score=20)
            registers.take_register(group, term, on=date(2026, 10, 12), absent_ids=[], by=self.teacher_a.user)
        self.assertIn('data-first-action="register"', self.home(self.teacher_a))

        with connected_to(self.a):
            gradebook.set_score(paper, child, 14, by=self.teacher_a.user)
        self.assertNotIn('data-first="teacher"', self.home(self.teacher_a))

    def test_gone_fourteen_days_after_the_first_sign_in(self):
        self.home(self.teacher_a)  # the first sign-in is written here
        first_at = User.objects.get(pk=self.teacher_a.user.pk).first_signed_in_at

        self.assertIn('data-first="teacher"', self.home(self.teacher_a, first_at + timedelta(days=13)))
        self.assertNotIn('data-first="teacher"', self.home(self.teacher_a, first_at + timedelta(days=14)))

    def test_the_first_sign_in_is_written_once(self):
        self.client.force_login(self.teacher_a.user)
        first_at = User.objects.get(pk=self.teacher_a.user.pk).first_signed_in_at
        self.client.force_login(self.teacher_a.user)

        self.assertIsNotNone(first_at)
        self.assertEqual(User.objects.get(pk=self.teacher_a.user.pk).first_signed_in_at, first_at)


class AParentsWelcomeTests(TwoSchools):
    def test_only_their_own_children_and_only_in_their_first_days(self):
        mine = self.student(self.a, "mine")
        self.student(self.a, "not-mine")
        link_guardian(self.parent_a.user, mine, relationship="father")

        self.client.force_login(self.parent_a.user)
        body = self.client.get("/api/results/cards/", HTTP_HOST=HOST_A).json()
        connection.set_schema_to_public()

        self.assertTrue(body["first_days"])
        self.assertEqual([c["student_membership_id"] for c in body["children"]], [mine.pk])

        later = timezone.now() + timedelta(days=15)
        with mock.patch("onboarding.first.now", return_value=later):
            body = self.client.get("/api/results/cards/", HTTP_HOST=HOST_A).json()
        connection.set_schema_to_public()
        self.assertFalse(body["first_days"])


# -- the invitation and the welcome message -----------------------------------------------------------


class PlainWordsAboutStepOneTests(TwoSchools):
    def body(self, member):
        invitation = mock.Mock()
        invitation.invited_by.get_full_name.return_value = "Ola Operator"
        invitation.school.name = "Sunrise College"
        invitation.membership = member
        invitation.expires_at = timezone.now() + timedelta(days=7)
        return EmailChannel()._body(invitation, "https://app.example/invitations/t/")

    def test_the_administrators_invitation_points_at_step_one(self):
        body = self.body(self.admin_a)

        self.assertIn("Start here", body)
        self.assertIn("Step 1 is your school's contact email and crest", body)

    def test_a_teachers_invitation_says_register_and_marks_and_nothing_about_fees(self):
        body = self.body(self.teacher_a)

        self.assertIn("take a register and enter marks", body)
        self.assertNotIn("fee", body.lower())

    def test_the_welcome_message_says_hello_and_the_name_and_carries_no_link(self):
        from schools.models import Invitation

        Invitation.objects.create(
            membership=self.admin_a, invited_by=self.ops, token_hash="x" * 64, sent_to="folake@example.com",
            expires_at=timezone.now() + timedelta(days=7),
        )
        text = handover.handover_for(self.a, host=HOST_A, portal=PORTAL).welcome

        self.assertTrue(text.startswith("Hello Folake Adebayo,"))
        self.assertNotIn("Good morning", text)
        self.assertNotIn("/invitations/", text)
        self.assertIn("Step 1 is your school's contact email and crest", text)
        self.assertIn("folake@example.com", text)


# -- the pilot agreement --------------------------------------------------------------------------------


class ThePilotAgreementDateTests(TwoSchools):
    """Control: the future-date check in `record_pilot_agreement()` and the
    `pilot_agreement_is_not_signed_after_it_was_recorded` constraint were each
    removed in turn, and the matching test went red."""

    def test_platform_staff_record_it_with_who_and_when(self):
        handover.record_pilot_agreement(self.ops, self.a, date(2026, 10, 1))
        school = School.objects.get(pk=self.a.pk)

        self.assertEqual(school.pilot_agreement_signed_on, date(2026, 10, 1))
        self.assertEqual(school.pilot_agreement_recorded_by, self.ops)
        self.assertIsNotNone(school.pilot_agreement_recorded_at)
        self.assertIsNone(School.objects.get(pk=self.b.pk).pilot_agreement_signed_on)

    def test_a_future_date_is_refused_by_the_service(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        with self.assertRaises(handover.HandoverRefused):
            handover.record_pilot_agreement(self.ops, self.a, tomorrow)
        self.assertIsNone(School.objects.get(pk=self.a.pk).pilot_agreement_signed_on)

    def test_a_future_date_is_refused_by_the_database_too(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            School.objects.filter(pk=self.a.pk).update(
                pilot_agreement_signed_on=tomorrow,
                pilot_agreement_recorded_by=self.ops,
                pilot_agreement_recorded_at=timezone.now(),
            )
        self.assertIn("pilot_agreement_is_not_signed_after_it_was_recorded", str(caught.exception))

    def test_a_date_without_who_and_when_is_refused_by_the_database(self):
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            School.objects.filter(pk=self.a.pk).update(pilot_agreement_signed_on=date(2026, 10, 1))
        self.assertIn("pilot_agreement_is_recorded_whole", str(caught.exception))

    def test_nobody_but_platform_staff_may_record_it(self):
        for actor in (self.admin_a.user, self.teacher_a.user):
            with self.assertRaises(handover.HandoverRefused):
                handover.record_pilot_agreement(actor, self.a, date(2026, 10, 1))

    def test_the_page_records_it_and_refuses_a_future_date_in_words(self):
        self.client.force_login(self.ops)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()

        refused = self.client.post("/platform/handover/", {"school": "sunrise", "signed_on": tomorrow}, HTTP_HOST=PORTAL)
        self.assertEqual(refused.status_code, 422)
        self.assertIn(b"cannot be in the future", refused.content)

        done = self.client.post("/platform/handover/", {"school": "sunrise", "signed_on": "2026-10-01"}, HTTP_HOST=PORTAL)
        self.assertEqual(done.status_code, 302)
        self.assertEqual(School.objects.get(pk=self.a.pk).pilot_agreement_signed_on, date(2026, 10, 1))

    def test_the_checklist_reads_the_rest_from_the_data(self):
        self.client.force_login(self.admin_a.user)  # signed in once
        rows = {c.key: c.done for c in handover.handover_for(School.objects.get(pk=self.a.pk)).checks}

        self.assertEqual(
            rows, {"created": True, "invited": False, "signed-in": True, "setup": False, "pilot": False}
        )
        rows_b = {c.key: c.done for c in handover.handover_for(School.objects.get(pk=self.b.pk)).checks}
        self.assertFalse(rows_b["signed-in"])


class TheJudgingIsPureTests(TestCase):
    """`judge()` alone, with no database: every rule in a line."""

    FACTS = dict(
        contact_email=False, crest=False, term=False, classes=0, subjects=0,
        teachers=0, students=0, fees=False, papers=False, registers=False,
    )

    def test_nothing_is_eight_to_do_and_none_locked(self):
        steps = progress.judge(dict(self.FACTS))

        self.assertEqual(steps.done, 0)
        self.assertEqual({s.state for s in steps.steps}, {"next", "todo"})
        self.assertEqual(steps.next.step.key, "school-details")

    def test_every_step_done_in_reverse_order_is_done(self):
        """The tester's case: later steps first. Each is judged on its own data."""
        facts = dict(self.FACTS)
        for key, fact in (
            ("report-card", dict(papers=True, term=True, subjects=1)),
            ("fees", dict(fees=True)),
            ("students", dict(students=2)),
            ("teachers", dict(teachers=1)),
        ):
            facts.update(fact)
            self.assertEqual(progress.judge(dict(facts)).by_key[key].state, "done")
        self.assertEqual(progress.judge(dict(facts)).next.step.key, "school-details")

    def test_the_first_step_is_done_with_each_part_given_or_put_off(self):
        for email, email_later, crest, crest_later, done in (
            (False, False, False, False, False),
            (True, False, False, False, False),
            (False, True, False, False, False),
            (False, True, False, True, True),
            (True, False, False, True, True),
            (False, True, True, False, True),
            (True, False, True, False, True),
        ):
            with self.subTest(email=email, email_later=email_later, crest=crest, crest_later=crest_later):
                steps = progress.judge(dict(
                    self.FACTS, contact_email=email, contact_email_later=email_later,
                    crest=crest, crest_later=crest_later,
                ))
                self.assertEqual(steps.by_key["school-details"].done, done)

    def test_what_was_put_off_is_named_on_the_step(self):
        steps = progress.judge(dict(self.FACTS, contact_email_later=True, crest=True))

        self.assertEqual(steps.by_key["school-details"].later, ("contact email",))
        self.assertIn("Contact email to add later", steps.by_key["school-details"].status)

    def test_a_term_saved_but_not_current_says_what_to_tap(self):
        steps = progress.judge(dict(self.FACTS, terms=1))

        self.assertNotEqual(steps.by_key["session-and-term"].state, "done")
        self.assertIn("Tap Make current", steps.by_key["session-and-term"].status)

    def test_a_step_done_out_of_order_is_still_done(self):
        steps = progress.judge(dict(self.FACTS, students=3))

        self.assertEqual(steps.by_key["students"].state, "done")

    def test_minutes_left_counts_only_what_is_required_and_not_done(self):
        steps = progress.judge(dict(self.FACTS))

        self.assertEqual(steps.minutes_left, sum(s.minutes for s in progress.REQUIRED))
