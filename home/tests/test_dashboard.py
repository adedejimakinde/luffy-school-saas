"""The school dashboard: who sees what, and that no school sees another's.

Two schools in every test, for the reason every fixture here gives: a figure
that forgot its schema would pass any single-school test, and a dashboard is a
page of totals, cached, where that mistake would hide twice over.

What is asserted is what reaches the page: which tiles (`data-tile`), which
attention items (`data-item`) and which activity lines (`data-event`) a login
is handed, and the figures in them. The sums underneath are the fee book's and
the register's, and have their own tests.

## Controls

Each claim below was broken on purpose, seen red, and restored (rule 5 of
`docs/operating-rules.md`). The table is in the pull request that added this
file and in `docs/design.md`'s dashboard section.
"""

import re
from datetime import datetime, time, timedelta
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from academics.models import ClassGroup, Term
from accounts.models import Role, User
from academics import services as academics
from accounts.services import enroll_student, grant_membership
from attendance import services as registers
from attendance.tests.fixtures import A_SCHOOL_DAY
from fees import services as fees
from gradebook import services as gradebook
from home import charts, facts
from results import services as chain
from results.tests.fixtures import HOST, PASSWORD, PORTAL, THEIR_HOST, ChainSetUp
from schools import invitations
from schools.models import Domain
from schools.tests.tenants import connected_to, make_school
from typography import NBSP, keep_together

URL = "/home/"

_TILE = re.compile(r'data-tile="([\w-]+)"')
_ITEM = re.compile(r'data-item="([\w-]+)"')
_EVENT = re.compile(r'data-event="([\w-]+)"')


def on(day):
    """The dashboard's "today", pinned: the fixture's term is in 2025."""
    return mock.patch.object(facts, "lagos_today", return_value=day)


def lagos(day, hour=9):
    return timezone.make_aware(datetime.combine(day, time(hour)))


class DashboardSetUp(ChainSetUp):
    day = A_SCHOOL_DAY

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )

    def page(self, member, host=HOST):
        self.client.force_login(member.user)
        with on(self.day), mock.patch("django.utils.timezone.now", return_value=lagos(self.day, 10)):
            response = self.client.get(URL, HTTP_HOST=host)
        connection.set_schema_to_public()
        return response

    def shown(self, member, host=HOST):
        html = self.page(member, host).content.decode()
        return set(_TILE.findall(html)), set(_ITEM.findall(html)), set(_EVENT.findall(html)), html

    def this_term(self):
        return Term.objects.get(pk=self.term_id)

    def a_busy_week_at_st_marys(self):
        """Something for every role to see: money, a register, a sheet waiting
        on the principal, a paper half marked, and an invitation out."""
        ada, emeka = self.children["ada"], self.children["emeka"]
        with connected_to(self.stmarys), mock.patch(
            "django.utils.timezone.now", return_value=lagos(self.day, 8)
        ):
            term = self.this_term()
            fees.charge(ada, term, 5_000_000, narration="Tuition")
            fees.charge(emeka, term, 5_000_000, narration="Tuition")
            fees.record_payment(ada, term, 3_500_000, method="cash")
            registers.take_register(
                ClassGroup.objects.get(pk=self.jss1a_id), term, on=self.day,
                absent_ids=[emeka.pk], by=self.teacher.user,
            )
            gradebook.set_score(self.first_ca, ada, 14, by=self.teacher.user)
            sheet = chain.open_sheet(ClassGroup.objects.get(pk=self.jss1a_id), term, self.teacher.user)
            chain.submit(sheet, self.teacher.user)
            chain.check(sheet, self.vp.user)
        invitations.invite_staff(
            self.admin.user, self.stmarys, Role.TEACHER, email="new.teacher@example.com",
            full_name="New Teacher", accept_url_for=lambda token: f"https://portal/i/{token}/",
        )


# -- who sees what -------------------------------------------------------------------


class EachRoleSeesItsOwnTests(DashboardSetUp):
    """Every role, against one busy week: the tiles, attention items and
    activity each is handed are exactly the ones it may open or act on."""

    def setUp(self):
        super().setUp()
        self.a_busy_week_at_st_marys()

    def test_the_principal(self):
        tiles, items, events, _ = self.shown(self.head)

        self.assertEqual(tiles, {"students", "fees", "attendance", "results"})
        # JSS 1A's sheet is checked: approving is the principal's. JSS 1B has
        # no sheet yet, so its remarks are still the principal's to write.
        self.assertEqual(items, {"results-checked", "scores", "remarks", "contact"})
        self.assertEqual(events, {"results", "payment", "registers"})

    def test_the_vice_principal(self):
        tiles, items, events, _ = self.shown(self.vp)

        self.assertEqual(tiles, {"fees", "attendance", "results"})
        # Checked already: nothing on the chain waits on the vice principal,
        # and the rest is other people's to act on.
        self.assertEqual(items, set())
        self.assertEqual(events, {"results", "payment", "registers"})

    def test_the_administrator(self):
        tiles, items, events, _ = self.shown(self.admin)

        self.assertEqual(tiles, {"students", "fees", "attendance", "results"})
        self.assertEqual(items, {"fees", "scores", "invites", "contact"})
        self.assertEqual(events, {"results", "payment", "registers"})

    def test_the_bursar(self):
        tiles, items, events, _ = self.shown(self.bursar)

        self.assertEqual(tiles, {"fees"})
        self.assertEqual(items, {"fees"})
        self.assertEqual(events, {"payment"})

    def test_the_teacher(self):
        tiles, items, events, _ = self.shown(self.teacher)

        self.assertEqual(tiles, {"attendance", "scores"})
        self.assertEqual(items, {"scores"})
        self.assertEqual(events, {"results", "register"})

    def test_the_results_tile_names_whose_step_it_is(self):
        for member, label in (
            (self.head, "Results to approve"),
            (self.vp, "Results to check"),
            (self.admin, "Awaiting approval"),
        ):
            with self.subTest(role=member.role):
                self.assertIn(label, self.shown(member)[3])

    def test_a_parent_is_refused_in_one_sentence(self):
        parent = grant_membership(
            User.objects.create_user("pat", PASSWORD, full_name="Pat Parent"), self.stmarys, Role.PARENT
        )

        response = self.page(parent)

        self.assertEqual(response.status_code, 403)
        self.assertIn('data-state="not-yours"', response.content.decode())
        self.assertNotRegex(response.content.decode(), r"data-(tile|item|event)=")


class ATeacherSeesNoMoneyTests(DashboardSetUp):
    def test_no_fee_figure_payment_or_payer_reaches_a_teacher(self):
        self.a_busy_week_at_st_marys()

        tiles, items, events, html = self.shown(self.teacher)

        self.assertNotIn("fees", tiles)
        self.assertNotIn("fees", items)
        self.assertNotIn("payment", events)
        self.assertNotIn("₦", html)
        self.assertNotIn("Fee collection", html)
        self.assertNotIn(self.children["ada"].user.full_name, html)

    def test_the_control_the_same_page_shows_the_bursar_the_money(self):
        """The assertions above would pass on a page that drew no money for
        anybody."""
        self.a_busy_week_at_st_marys()

        html = self.shown(self.bursar)[3]

        self.assertIn("₦35,000", html)
        self.assertIn("Fee collection", html)


class ATeacherSeesTheirOwnClassTests(DashboardSetUp):
    def test_attendance_counts_the_class_they_teach_and_not_the_school(self):
        newcomer = enroll_student(
            User.objects.create_user("bola", PASSWORD, full_name="Bola Ige"), self.stmarys
        )
        with connected_to(self.stmarys):
            registers.take_register(
                ClassGroup.objects.get(pk=self.jss1a_id), self.this_term(), on=self.day,
                absent_ids=[self.children["emeka"].pk], by=self.teacher.user,
            )
            # Another class, its one child absent: the school's figure, not hers.
            jss1b = ClassGroup.objects.get(pk=self.jss1b_id)
            academics.place_student(jss1b, self.this_term(), newcomer)
            registers.take_register(jss1b, self.this_term(), on=self.day, absent_ids=[newcomer.pk], by=self.head.user)

        teacher = self.shown(self.teacher)[3]
        principal = self.shown(self.head)[3]

        self.assertIn(f"3 of 4 present in JSS{NBSP}1A", teacher)
        self.assertIn("75%", teacher)
        # The school: JSS 1A's three, and one of JSS 1B's two.
        self.assertIn("4 of 6 present", principal)
        self.assertIn("66.7%", principal)

    def test_a_teacher_with_no_class_has_no_attendance_or_scores_tile(self):
        loner = grant_membership(
            User.objects.create_user("lone", PASSWORD, full_name="Lone Teacher"), self.stmarys, Role.TEACHER
        )

        tiles, items, events, html = self.shown(loner)

        self.assertEqual(tiles, set())
        self.assertIn("Nothing needs you right now", html)


# -- one school's numbers, never another's ------------------------------------------


class EachSchoolsNumbersAreItsOwnTests(DashboardSetUp):
    def money_at_grace(self, kobo):
        child = self.grace_child
        with connected_to(self.grace):
            term = Term.objects.get(pk=self.grace_term_id)
            fees.charge(child, term, kobo, narration="Tuition")
            fees.record_payment(child, term, kobo, method="cash")

    def test_one_schools_figures_never_reach_the_other(self):
        self.money_at_grace(9_000_000)

        st_marys = self.shown(self.head)[3]
        grace = self.shown(self.their_head, host=THEIR_HOST)[3]

        self.assertIn("₦90,000", grace)
        self.assertNotIn("₦90,000", st_marys)
        self.assertIn("Nothing billed this term yet", st_marys)

    def test_a_cached_school_is_never_served_to_the_next_school_that_asks(self):
        """St Mary's is read and cached first; Grace, asking on the same day,
        must get Grace's numbers and not St Mary's cached copy."""
        self.money_at_grace(9_000_000)

        st_marys_first = self.shown(self.head)[3]
        grace_second = self.shown(self.their_head, host=THEIR_HOST)[3]
        st_marys_again = self.shown(self.head)[3]

        self.assertNotIn("₦90,000", st_marys_first)
        self.assertIn("₦90,000", grace_second)
        self.assertNotIn("₦90,000", st_marys_again)
        self.assertEqual(
            sorted(k for k in cache._cache if "home:facts" in k),
            sorted(
                cache.make_key(facts.cache_key(school.schema_name, school.pk, self.day))
                for school in (self.stmarys, self.grace)
            ),
        )

    def test_the_cache_key_names_the_schema_and_the_day(self):
        key = facts.cache_key("st_marys", 7, self.day)

        self.assertIn("st_marys", key)
        self.assertNotEqual(key, facts.cache_key("grace", 7, self.day))
        self.assertNotEqual(key, facts.cache_key("st_marys", 7, self.day + timedelta(days=1)))


# -- what it costs -------------------------------------------------------------------


class ThreeStatementsAndThenNoneTests(DashboardSetUp):
    def aggregates(self, member, host=HOST):
        self.client.force_login(member.user)
        with on(self.day), CaptureQueriesContext(connection) as queries:
            self.client.get(URL, HTTP_HOST=host)
        connection.set_schema_to_public()
        return [q["sql"] for q in queries.captured_queries if "json_build_object" in q["sql"]]

    def test_three_aggregate_statements_on_a_cold_cache_and_none_on_a_warm_one(self):
        self.assertEqual(len(self.aggregates(self.head)), 3)
        self.assertEqual(self.aggregates(self.head), [])
        # Another role at the same school is served from the same copy.
        self.assertEqual(self.aggregates(self.teacher), [])

    def test_the_count_does_not_grow_with_the_school(self):
        small = len(self.aggregates(self.head))
        cache.clear()
        with connected_to(self.stmarys):
            for n in range(5):
                ClassGroup.objects.create(name=f"SS {n + 1}A", level=10 + n)

        self.assertEqual(len(self.aggregates(self.head)), small)


# -- a school being set up -------------------------------------------------------------


class ANewSchoolTests(DashboardSetUp):
    def setUp(self):
        super().setUp()
        self.fresh = make_school("Fresh Start College", "fresh", "fresh")
        Domain.objects.create(tenant=self.fresh, domain="fresh.testserver", is_primary=True)
        self.fresh_admin = grant_membership(
            User.objects.create_user("fola", PASSWORD, full_name="Fola Admin"), self.fresh, Role.ADMIN
        )

    def test_no_students_is_the_set_up_checklist_and_no_figures(self):
        with connected_to(self.fresh):
            ClassGroup.objects.create(name="JSS 1A", level=1)

        tiles, items, events, html = self.shown(self.fresh_admin, host="fresh.testserver")

        self.assertIn("Set up your school", html)
        self.assertIn("1 of 3 done", html)
        self.assertEqual((tiles, items, events), (set(), set(), set()))
        for href in ("/setup/", "/staff/", "/roll/import/"):
            self.assertIn(f'href="{href}"', html)

    def test_the_checklist_is_not_cached_so_a_step_ticks_at_once(self):
        self.shown(self.fresh_admin, host="fresh.testserver")
        with connected_to(self.fresh):
            ClassGroup.objects.create(name="JSS 1A", level=1)

        self.assertIn("1 of 3 done", self.shown(self.fresh_admin, host="fresh.testserver")[3])

    def test_a_teacher_at_a_new_school_is_told_and_offered_nothing_to_open(self):
        teacher = grant_membership(
            User.objects.create_user("tobi", PASSWORD, full_name="Tobi Teacher"), self.fresh, Role.TEACHER
        )

        html = self.shown(teacher, host="fresh.testserver")[3]

        self.assertIn("Your school is being set up", html)
        self.assertNotIn("Set up your school", html)

    def test_the_control_a_school_with_students_gets_no_checklist(self):
        self.assertNotIn("Set up your school", self.shown(self.admin)[3])


# -- the doors -----------------------------------------------------------------------


class TheDoorsTests(DashboardSetUp):
    def test_signed_out_is_told_where_to_sign_in_and_shown_nothing(self):
        self.client.logout()
        response = self.client.get(URL, HTTP_HOST=HOST)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-state="signed-out"', response.content.decode())
        self.assertNotIn("St Mary", response.content.decode())

    def test_the_portal_points_to_the_schools_own_address(self):
        self.client.force_login(self.head.user)
        response = self.client.get(URL, HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 404)
        self.assertIn('data-state="elsewhere"', response.content.decode())


# -- the parts -----------------------------------------------------------------------


class ThePartsTests(DashboardSetUp):
    def test_class_and_level_names_never_break(self):
        self.assertEqual(keep_together("JSS 3A, SS 1C and SS 2B"), f"JSS{NBSP}3A, SS{NBSP}1C and SS{NBSP}2B")
        self.assertEqual(keep_together("JSS 1 to SS 3"), f"JSS{NBSP}1 to SS{NBSP}3")
        self.assertEqual(keep_together("SS 2 Science"), f"SS{NBSP}2 Science")

    def test_a_day_with_no_register_is_an_empty_slot_not_a_low_bar(self):
        mon, tue = charts.bars([("Mon", 90, False, False), ("Tue", None, True, True)])

        self.assertEqual((mon.percent, tue.percent, tue.pending), (90, None, True))
        self.assertGreater(tue.h, mon.h, "the slot is the chart's full height")

    def test_no_sparkline_without_a_point(self):
        self.assertIsNone(charts.sparkline([], 13))
        self.assertIsNotNone(charts.sparkline([0], 13))
