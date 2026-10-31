"""Crestfield College, Classnode's demo school on the production server (`schools.crestfield`).

Built the real way, `School.save()` and a migrated schema, at two children a
class rather than 25 (`per_class`), beside a real school, St Mary's, which has a
term, a class, a child, a register and a principal of its own. What these hold:

- **The demo is what the brochure says** and is put back exactly by a reset.
- **It cannot see or touch another school**, over HTTP in both directions, and
  a reset changes nothing of St Mary's, in its schema or in the shared tables.
- **Nothing is sent for it**, whatever is pressed, and the second lock (the
  real phone provider refusing a fictional number) holds on its own.
- **It is never indexed**, though its website is published.
- **The demo-name guard is not loosened**: `crestfield` is not a demo name, and
  the flag cannot be put on any other school.
"""

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import (
    ContactChannel,
    GuardianAccount,
    GuardianContact,
    Guardianship,
    Membership,
    MembershipStatus,
    Role,
    User,
)
from accounts.services import enroll_student, grant_membership, link_guardian
from attendance import services as attendance
from attendance.models import Register
from gradebook.models import Score
from messaging.models import CodeDeliveryOutcome, FakeMessage, Outcome
from messaging.providers import Outbound, Refused
from messaging.tests.fake import SendsThroughTheFake
from schools import crestfield, demo_slugs, quiet
from schools.crestfield import people, questions
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school

PASSWORDS = {"principal": "principal-pass-123", "teacher": "teacher-pass-1234", "parent": "parent-pass-12345"}
SUFFIX = "testserver"
DEMO = f"crestfield.{SUFFIX}"
OTHER = f"stmarys.{SUFFIX}"
PER_CLASS = 2


def build_demo():
    return crestfield.create(PASSWORDS, SUFFIX, write=lambda *_: None, per_class=PER_CLASS)


def build_st_marys():
    """A real school beside the demo, with something in it to see or break."""
    school = make_school("St Mary's", "stmarys", "stmarys")
    Domain.objects.create(tenant=school, domain=OTHER, is_primary=True)
    principal = grant_membership(User.objects.create_user("stm.principal", "stm-pass-12345", full_name="Mrs Bello"),
                                 school, Role.PRINCIPAL)
    child = enroll_student(User.objects.create_user("stm.ada", None, full_name="Ada Obi"), school, reference="STM/001")
    parent = User.objects.create_user("stm.parent", "stm-parent-1234", full_name="Mr Obi")
    link_guardian(parent, child)
    with connected_to(school):
        today = timezone.localdate()
        term = academics.create_term("2026/2027", TermName.FIRST, today - timedelta(days=30), today + timedelta(days=30))
        academics.set_current_term(term)
        group = ClassGroup.objects.create(name="JSS 1A", level=1)
        academics.place_student(group, term, child)
        day = today - timedelta(days=max(0, today.weekday() - 4))
        attendance.take_register(group, term, on=day, absent_ids=[], by=principal.user)
    connection.set_schema_to_public()
    return school, principal, child, parent, group.pk, term.pk, day


def counts(school):
    """Every row in a school's own schema, table by table, read from Postgres."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select tablename from pg_tables where schemaname = %s order by 1", [school.schema_name]
        )
        tables = [row[0] for row in cursor.fetchall()]
        found = {}
        for table in tables:
            cursor.execute(f'select count(*) from "{school.schema_name}"."{table}"')
            found[table] = cursor.fetchone()[0]
    return found


def public_rows(school):
    return {
        "memberships": sorted(Membership.objects.filter(school=school).values_list("pk", "status", "role")),
        "guardianships": sorted(Guardianship.objects.filter(student__school=school).values_list("pk", flat=True)),
        "school": School.objects.filter(pk=school.pk).values().get(),
        "domains": sorted(Domain.objects.filter(tenant=school).values_list("domain", flat=True)),
    }


class DemoSchoolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.other, cls.other_principal, cls.other_child, cls.other_parent, cls.other_group, cls.other_term, cls.other_day = (
            build_st_marys()
        )
        # St Mary's as it was before the demo existed: neither making the demo
        # nor resetting it may change a row of it.
        cls.other_before = counts(cls.other), public_rows(cls.other)
        cls.school = build_demo()
        connection.set_schema_to_public()

    def tearDown(self):
        connection.set_schema_to_public()

    def member(self, key):
        return Membership.objects.get(school=self.school, user__username=f"cfc.{key}")

    # -- what it is -----------------------------------------------------------

    def test_it_is_the_school_the_brochure_shows(self):
        school = self.school
        self.assertEqual((school.slug, school.schema_name, school.name), ("crestfield", "crestfield", crestfield.NAME))
        self.assertTrue(school.sales_demo)
        self.assertEqual(list(Domain.objects.filter(tenant=school).values_list("domain", flat=True)), [DEMO])
        roles = list(Membership.objects.filter(school=school, status=MembershipStatus.ACTIVE).values_list("role", flat=True))
        self.assertEqual(roles.count(Role.STUDENT), 12 * PER_CLASS)
        self.assertEqual(roles.count(Role.TEACHER), 15)
        for role in (Role.PRINCIPAL, Role.VICE_PRINCIPAL_ACADEMIC, Role.ADMIN, Role.BURSAR):
            self.assertEqual(roles.count(role), 1, role)
        self.assertIsNotNone(school.setup_completed_at, "every setup step holds, so it is written down")

        from fees.models import FeeLedgerEntry
        from results.models import ReleasedCard, ResultSheet
        from schoolsite.services import live_revision

        with schema_context(school.schema_name):
            states = dict(ResultSheet.objects.values_list("class_group__name", "state"))
            self.assertEqual(sorted(n for n, s in states.items() if s == "released"), sorted(crestfield.RELEASED))
            self.assertEqual(sorted(n for n, s in states.items() if s == "draft"), sorted(crestfield.OPEN))
            self.assertEqual(ReleasedCard.objects.count(), len(crestfield.RELEASED) * PER_CLASS)
            self.assertEqual({c.template for c in ReleasedCard.objects.all()}, {"ogun"})
            # Every paper of every subject each child's class takes.
            papers = sum(len(crestfield.subjects_of(name)) * 4 for name, _ in crestfield.CLASSES)
            self.assertEqual(Score.objects.count(), papers * PER_CLASS)
            self.assertEqual(Register.objects.count(), 12 * len(crestfield.term_dates(timezone.localdate())[3]))
            self.assertTrue(FeeLedgerEntry.objects.filter(kind="payment").exists())
            self.assertIsNotNone(live_revision(school), "the website is published")
            from cbt.models import ExamPin

            self.assertEqual(ExamPin.objects.filter(cancelled_at__isnull=True).count(), PER_CLASS)

    def test_the_parent_sees_two_released_cards(self):
        parent = User.objects.get(username="cfc.parent")
        children = Guardianship.objects.filter(guardian=parent).values_list("student__user__full_name", flat=True)
        self.assertEqual(sorted(children), sorted(full for _, full, _ in people.PARENT_CHILDREN))
        self.client.force_login(parent)
        index = self.client.get("/api/results/cards/", HTTP_HOST=DEMO)
        self.assertEqual(index.status_code, 200, index.content)

    def test_only_three_logins_have_a_password_and_they_take_the_ones_given(self):
        for key, password in PASSWORDS.items():
            user = User.objects.get(username=f"cfc.{key}")
            self.assertTrue(user.check_password(password), key)
        others = User.objects.filter(username__startswith="cfc.").exclude(username__in=[f"cfc.{k}" for k in PASSWORDS])
        self.assertTrue(others.exists())
        self.assertFalse([u.username for u in others if u.has_usable_password()])

    def test_every_contact_is_reserved_for_fiction(self):
        emails = User.objects.filter(username__startswith="cfc.").exclude(email=None).values_list("email", flat=True)
        self.assertTrue(emails)
        self.assertTrue(all(e.endswith("@example.com") for e in emails), emails)
        phones = GuardianContact.objects.filter(guardian__user__username__startswith="cfc.")
        self.assertTrue(phones.exists())
        from messaging.reserved import is_fictional_phone

        self.assertTrue(all(is_fictional_phone(c.value) for c in phones))
        self.assertFalse(User.objects.filter(username__startswith="cfc.").exclude(phone=None).exists())

    # -- making it twice, and the guard ---------------------------------------

    def test_a_second_create_refuses_and_changes_nothing(self):
        before = public_rows(self.school)
        with self.assertRaisesMessage(crestfield.Refused, "already here"):
            build_demo()
        self.assertEqual(public_rows(self.school), before)

    def test_the_command_wants_every_password_before_it_does_anything(self):
        schools = School.objects.count()
        with mock.patch.dict("os.environ", {"CRESTFIELD_PRINCIPAL_PASSWORD": "long-enough-123"}, clear=False):
            with self.assertRaisesMessage(CommandError, "CRESTFIELD_TEACHER_PASSWORD"):
                call_command("crestfield", "create", "--domain-suffix", SUFFIX, stdout=StringIO())
        self.assertEqual(School.objects.count(), schools)

    def test_crestfield_is_not_a_demo_name_and_the_guard_is_as_it_was(self):
        self.assertFalse(demo_slugs.is_demo_name(crestfield.SLUG))
        self.assertEqual(demo_slugs.DEMO_SLUGS, frozenset({"sunrise-demo", "harbour-demo", "showcase-demo"}))
        with override_settings(DEBUG=False), mock.patch.dict("os.environ", {"DEMO_SERVER": ""}):
            demo_slugs.refuse_if_demo_schools_exist()  # production starts with the demo school in it

    def test_no_other_school_can_carry_the_flag(self):
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            School.objects.filter(pk=self.other.pk).update(sales_demo=True)
        self.assertIn("only_crestfield_is_the_sales_demo", str(caught.exception))

    def test_reset_refuses_a_crestfield_that_is_not_the_demo(self):
        School.objects.filter(pk=self.school.pk).update(sales_demo=False)
        before = counts(self.school)
        with self.assertRaisesMessage(crestfield.Refused, "not Classnode's demo school"):
            crestfield.reset({}, write=lambda *_: None, per_class=PER_CLASS)
        self.assertEqual(counts(self.school), before)

    # -- reset ------------------------------------------------------------------

    def test_making_the_demo_touched_no_other_school(self):
        self.assertEqual((counts(self.other), public_rows(self.other)), self.other_before)

    def test_reset_puts_back_what_a_demo_changed_and_touches_no_other_school(self):
        other_schema, other_public = self.other_before
        principal = self.member("principal")
        ids = dict(Membership.objects.filter(school=self.school).values_list("user__username", "pk"))

        # What a visit might leave behind: a mark changed, a teacher suspended,
        # a child added, a stranger linked as a guardian.
        with schema_context(self.school.schema_name):
            from academics.models import ClassPlacement

            still_open = ClassGroup.objects.get(name="JSS 2B")
            ids_there = ClassPlacement.objects.student_ids(still_open, Term.objects.get(is_current=True))
            score = Score.objects.filter(student_membership_id__in=ids_there).order_by("pk").first()
            Score.objects.filter(pk=score.pk).update(value=0)
            which = (score.assessment.subject.code, score.assessment.name, score.student_membership_id)
        Membership.objects.filter(pk=self.member("t03").pk).update(status=MembershipStatus.SUSPENDED)
        newcomer = enroll_student(User.objects.create_user("walk.in", None, full_name="Walk In"), self.school)
        stranger = User.objects.create_user("stranger", None, full_name="A Stranger")
        link_guardian(stranger, self.member("s001"))

        crestfield.reset({}, write=lambda *_: None, per_class=PER_CLASS)

        self.assertEqual(counts(self.other), other_schema, "St Mary's own schema is untouched")
        self.assertEqual(public_rows(self.other), other_public, "and so are its shared rows")
        self.assertEqual(Membership.objects.get(pk=self.member("t03").pk).status, MembershipStatus.ACTIVE)
        self.assertEqual(Membership.objects.get(pk=newcomer.pk).status, MembershipStatus.ENDED)
        self.assertFalse(Guardianship.objects.filter(guardian=stranger).exists())
        # The same people keep the same memberships, so nothing in the new schema dangles.
        again = dict(Membership.objects.filter(school=self.school).values_list("user__username", "pk"))
        self.assertEqual({k: v for k, v in again.items() if k in ids}, ids)
        with schema_context(self.school.schema_name):
            back = Score.objects.get(assessment__subject__code=which[0], assessment__name=which[1],
                                     student_membership_id=which[2])
            self.assertNotEqual(back.value, 0)
        self.assertTrue(User.objects.get(pk=principal.user_id).check_password(PASSWORDS["principal"]),
                        "a reset without passwords keeps them")

    def test_the_schema_reset_drops_is_the_demos_and_no_other(self):
        """`rebuild_schema` asks the database, not the row in hand, before it drops."""
        impostor = School.objects.get(pk=self.other.pk)
        impostor.sales_demo, impostor.slug, impostor.schema_name = True, "crestfield", "stmarys"
        before = counts(self.other)
        with self.assertRaises(AssertionError):
            crestfield.rebuild_schema(impostor)
        self.assertEqual(counts(self.other), before)

    # -- access ----------------------------------------------------------------

    def register_url(self, group, term, day):
        return f"/api/attendance/classes/{group}/terms/{term}/{day}/"

    def test_the_demo_principal_reads_the_demo_and_not_st_marys(self):
        self.client.force_login(self.member("principal").user)
        with schema_context(self.school.schema_name):
            group = ClassGroup.objects.get(name="JSS 1A")
            term = Term.objects.get(is_current=True)
        own = self.client.get(self.register_url(group.pk, term.pk, term.ends_on), HTTP_HOST=DEMO)
        self.assertEqual(own.status_code, 200, "the control: the same session reads its own school")
        theirs = self.client.get(self.register_url(self.other_group, self.other_term, self.other_day), HTTP_HOST=OTHER)
        self.assertEqual(theirs.status_code, 403)

    def test_the_demo_principal_cannot_write_at_st_marys(self):
        self.client.force_login(self.member("principal").user)
        before = counts(self.other)
        answer = self.client.put(
            self.register_url(self.other_group, self.other_term, self.other_day),
            data=json.dumps({"absent_ids": [self.other_child.pk]}), content_type="application/json", HTTP_HOST=OTHER,
        )
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(counts(self.other), before)

    def test_the_demo_parent_cannot_read_a_st_marys_card(self):
        self.client.force_login(User.objects.get(username="cfc.parent"))
        answer = self.client.get(f"/api/results/cards/{self.other_child.pk}/{self.other_term}/", HTTP_HOST=OTHER)
        self.assertEqual(answer.status_code, 403)
        own = self.client.get("/api/results/cards/", HTTP_HOST=DEMO)
        self.assertEqual(own.status_code, 200)
        self.assertNotIn("Ada Obi", own.content.decode())

    def test_st_marys_cannot_read_or_write_the_demo(self):
        self.client.force_login(self.other_principal.user)
        with schema_context(self.school.schema_name):
            group = ClassGroup.objects.get(name="JSS 1A")
            term = Term.objects.get(is_current=True)
        url = self.register_url(group.pk, term.pk, term.ends_on)
        self.assertEqual(self.client.get(url, HTTP_HOST=DEMO).status_code, 403)
        before = counts(self.school)
        answer = self.client.put(url, data=json.dumps({"absent_ids": []}), content_type="application/json", HTTP_HOST=DEMO)
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(counts(self.school), before)

    # -- never indexed ----------------------------------------------------------

    def test_its_published_site_is_never_indexed(self):
        home = self.client.get("/", HTTP_HOST=DEMO)
        self.assertEqual(home.status_code, 200)
        self.assertIn("Crestfield", home.content.decode())
        self.assertEqual(home.get("X-Robots-Tag"), "noindex, nofollow")
        self.assertEqual(self.client.get("/sitemap.xml", HTTP_HOST=DEMO).status_code, 404)
        robots = self.client.get("/robots.txt", HTTP_HOST=DEMO).content.decode()
        self.assertTrue(robots.rstrip().endswith("Disallow: /"), robots)
        self.assertNotIn("Sitemap:", robots)

    # -- nothing is sent --------------------------------------------------------

    def test_an_invitation_is_refused_and_leaves_nothing_behind(self):
        self.client.force_login(self.member("admin").user)
        before = Membership.objects.count(), User.objects.count()
        answer = self.client.post(
            f"/api/schools/{crestfield.SLUG}/invitations/",
            data=json.dumps({"role": "teacher", "email": "someone@realschool.ng", "full_name": "Some One"}),
            content_type="application/json", HTTP_HOST=DEMO,
        )
        self.assertEqual(answer.status_code, 409, answer.content)
        self.assertIn("switched off", answer.content.decode())
        self.assertEqual((Membership.objects.count(), User.objects.count()), before)

    def test_its_notices_cannot_be_switched_on(self):
        from notices.models import NoticeSettings

        self.client.force_login(self.member("principal").user)
        answer = self.client.post(
            "/api/notices/settings/", data=json.dumps({"payment_receipts": True, "absence_alerts": True}),
            content_type="application/json", HTTP_HOST=DEMO,
        )
        self.assertEqual(answer.status_code, 409, answer.content)
        with schema_context(self.school.schema_name):
            row = NoticeSettings.objects.filter(pk=1).first()
            self.assertFalse(row and (row.payment_receipts or row.absence_alerts))


class NothingLeavesTests(SendsThroughTheFake, TestCase):
    """The switch at each send, with the fake provider on: nothing reaches its outbox."""

    @classmethod
    def setUpTestData(cls):
        cls.school = build_demo()
        cls.other = build_st_marys()[0]
        connection.set_schema_to_public()

    def tearDown(self):
        connection.set_schema_to_public()

    def result_notices_written_anyway(self):
        """Write result notices (switched on by hand) and send each: what each send said."""
        from notices import services as notices
        from notices import tasks
        from notices.models import Notice, NoticeOutcome, NoticeSettings
        from results.models import ResultSheet

        principal = Membership.objects.get(school=self.school, role=Role.PRINCIPAL).user
        with schema_context(self.school.schema_name):
            NoticeSettings.objects.update_or_create(pk=1, defaults={"result_notices": True})
            sheet = ResultSheet.objects.get(class_group__name="JSS 2A")
            # 10:00 UTC (11:00 in Lagos, inside the sending hours) *yesterday*, so the
            # notices are already due whatever time of day this runs. 10:00 today was
            # still to come before 10:00 UTC, and `send_notice` holds a notice that is
            # not yet due without saying anything: the test failed every morning.
            now = (timezone.now() - timedelta(days=1)).replace(hour=10)
            with mock.patch("notices.tasks.send_notice.apply_async"):
                with self.captureOnCommitCallbacks(execute=True):
                    notices.tell_families(sheet, actor=principal, now=now)
            ids = list(Notice.objects.values_list("pk", flat=True))
            self.assertTrue(ids, "the parents have verified phones, so notices were written")
            with mock.patch("notices.hours.send_after", side_effect=lambda when: when):
                for pk in ids:
                    tasks.send_notice(self.school.schema_name, pk)
            return set(NoticeOutcome.objects.values_list("said", flat=True))

    def test_result_notices_written_anyway_are_not_sent(self):
        """The second lock: notices that got written (say, switched on by hand) go nowhere."""
        from notices.models import NoticeOutcome

        self.assertEqual(self.result_notices_written_anyway(), {NoticeOutcome.Said.SWITCHED_OFF})
        self.assertFalse(FakeMessage.objects.exists())

    def test_the_same_at_eight_in_the_morning_utc(self):
        """The time of day the test above used to fail at: before 10:00 UTC, with the clock stopped there."""
        from notices.models import NoticeOutcome

        eight = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        with mock.patch("django.utils.timezone.now", return_value=eight):
            said = self.result_notices_written_anyway()
        self.assertEqual(said, {NoticeOutcome.Said.SWITCHED_OFF})
        self.assertFalse(FakeMessage.objects.exists())

    def test_a_guardian_only_here_gets_no_sign_in_code(self):
        from accounts.guardian_contacts import request_sign_in_code

        contact = GuardianContact.objects.get(guardian__user__username="cfc.parent")
        self.deliver(lambda: request_sign_in_code(contact))
        self.assertEqual(
            list(CodeDeliveryOutcome.objects.values_list("outcome", flat=True)), [Outcome.SWITCHED_OFF]
        )
        self.assertFalse(FakeMessage.objects.exists())

    def test_a_guardian_also_at_a_real_school_still_gets_their_code(self):
        """The control: the switch is the demo's, not every guardian's who was typed into it."""
        from accounts.guardian_contacts import request_sign_in_code

        parent = User.objects.get(username="cfc.g001")
        child = enroll_student(User.objects.create_user("stm.kid", None, full_name="Kid"), self.other)
        link_guardian(parent, child)
        Membership.objects.filter(user=parent, school=self.other).update(status=MembershipStatus.ACTIVE)
        contact = GuardianContact.objects.get(guardian__user=parent)
        self.deliver(lambda: request_sign_in_code(contact))
        self.assertEqual(list(CodeDeliveryOutcome.objects.values_list("outcome", flat=True)), [Outcome.ACCEPTED])

    def test_a_code_the_demo_asks_for_is_not_sent(self):
        from accounts.guardian_contacts import request_verification

        parent = User.objects.create_user("typed.in", None, full_name="Typed In")
        link_guardian(parent, Membership.objects.get(school=self.school, user__username="cfc.s002"))
        account = GuardianAccount.objects.create(user=parent)
        contact = GuardianContact.objects.create(
            guardian=account, channel_type=ContactChannel.PHONE, value="+2348031234567",
            created_by=Membership.objects.get(school=self.school, role=Role.ADMIN).user,
        )
        self.deliver(lambda: request_verification(contact, school_id=self.school.pk))
        self.assertEqual(list(CodeDeliveryOutcome.objects.values_list("outcome", flat=True)), [Outcome.SWITCHED_OFF])
        self.assertFalse(FakeMessage.objects.exists())

    def test_the_daily_money_summary_is_not_processed(self):
        from notices import daily_summary
        from notices.models import MoneySummarySent, NoticeSettings

        with connected_to(self.school):
            NoticeSettings.objects.update_or_create(pk=1, defaults={"daily_money_summary": True})
            self.assertFalse(daily_summary.send_summary(self.school, timezone.localdate()))
            self.assertFalse(MoneySummarySent.objects.exists())


class FictionalNumbersTests(SimpleTestCase):
    def test_the_real_phone_provider_refuses_a_fictional_number_before_it_calls_out(self):
        from messaging.termii import TermiiProvider

        outbound = Outbound(channel_type="phone", address="+12015550123", kind="x", text="t")
        with override_settings(TERMII_API_KEY="k", TERMII_SENDER_ID="Classnode"), \
                mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(Refused):
                TermiiProvider().send(outbound)
        urlopen.assert_not_called()

    def test_which_numbers_are_fictional(self):
        from messaging.reserved import is_fictional_phone

        for number in ("+12015550100", "+12075550199", people.guardian_phone(0), people.guardian_phone(599)):
            self.assertTrue(is_fictional_phone(number), number)
        for number in ("+2348031234567", "+12015550200", "+12015551234", ""):
            self.assertFalse(is_fictional_phone(number), number)

    def test_is_quiet_reads_the_flag(self):
        self.assertTrue(quiet.is_quiet(School(sales_demo=True)))
        self.assertFalse(quiet.is_quiet(School()))
        self.assertFalse(quiet.is_quiet(None))


class TheDemoDataTests(SimpleTestCase):
    def test_the_question_bank_is_well_formed(self):
        self.assertEqual(sorted(questions.BANK), ["Basic Science", "English Language", "Mathematics"])
        for subject, bank in questions.BANK.items():
            self.assertEqual(len(bank), 10, subject)
            for text, options, answer in bank:
                self.assertEqual(len(options), 4, text)
                self.assertEqual(len(set(options)), 4, text)
                self.assertIn(answer, range(4), text)

    def test_every_name_and_sentence_is_plainly_spelt(self):
        """No tone marks, under-dots or hooked letters: names as schools record them.

        Money keeps its naira sign and the questions their maths signs; nothing
        else in the demo's data is outside plain ASCII.
        """
        from schools.crestfield import site

        names = [n for pool in people.FIRST.values() for n in pool]
        names += [n for pool in people.SURNAMES.values() for n in pool]
        names += [n for _, _, n in people.OFFICE] + [n for _, n, _ in people.TEACHERS]
        names += [people.PARENT] + [n for _, n, _ in people.PARENT_CHILDREN]
        names += [crestfield.NAME, crestfield.ABOUT, crestfield.ADDRESS, crestfield.LGA]
        names += [name for name, _ in crestfield.SUBJECTS]
        names += [json.dumps(v, ensure_ascii=False) for v in (site.HERO, site.MOTTO, site.MESSAGE, site.FACTS,
                                                               site.ADMISSIONS, site.ABOUT, site.CONTACT, site.FOOTER)]
        names += [line for lines in (crestfield.TEACHER_SAYS, crestfield.PRINCIPAL_SAYS)
                  for _, said in lines for line in (said if isinstance(said, tuple) else (said,))]
        for text in names:
            self.assertTrue(text.isascii(), text)
        allowed = set("₦−°×")
        for bank in questions.BANK.values():
            for text, options, _ in bank:
                for part in (text, *options):
                    self.assertEqual({c for c in part if not c.isascii()} - allowed, set(), part)

    def test_the_roll_is_the_same_every_time_and_names_nobody_twice(self):
        names = [name for name, _ in crestfield.CLASSES]
        first, guardians = people.roll(names, 25, "crestfield")
        again, _ = people.roll(names, 25, "crestfield")
        self.assertEqual([c.name for n in names for c in first[n]], [c.name for n in names for c in again[n]])
        everyone = [c.name for n in names for c in first[n]]
        self.assertEqual(len(everyone), 300)
        self.assertEqual(len(set(everyone)), 300)
        self.assertLess(len(guardians), len(people.AREA_CODES) * 100, "a fictional number for every guardian")
        self.assertTrue(any(len(g.children) > 1 for g in guardians), "some families have two children here")
