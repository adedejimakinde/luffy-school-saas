"""The principal's home over HTTP: who may open it, and what each figure counts.

Two schools in every test, for the reason every fixture here gives: a figure
that forgot its schema would pass any single-school test, and a home page is
exactly a page of totals where that mistake would hide.

The figures are other modules' tables summed; what is asserted is the sum's
meaning (a reversed payment is not money received, a discount is not money
billed) rather than the modules underneath, which have their own tests.
"""

from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from academics import services as academics
from academics.models import ClassGroup, Term
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from attendance import absences
from attendance import services as registers
from attendance.tests.fixtures import A_SCHOOL_DAY
from fees import authority as fees_authority
from fees import services as fees
from home import summary
from results import comments
from results import services as chain
from results.models import CommentAuthor
from results.tests.fixtures import HOST, PASSWORD, PORTAL, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

HOME = "/api/home/"


def on(day):
    """The home's "today", pinned: the fixture's term is in 2025."""
    return mock.patch.object(summary, "lagos_today", return_value=day)


def clock(moment):
    """Whatever is written now is written at `moment`. The transition log is
    append-only, a trigger and not a convention, so a step's time can only be
    set as it is taken."""
    return mock.patch("django.utils.timezone.now", return_value=moment)


def lagos(day, hour=9, minute=0):
    return summary.timezone.make_aware(summary.datetime.combine(day, summary.time(hour, minute)))


class HomeSetUp(ChainSetUp):
    #: The home's today. The fixture's school day unless a test says otherwise.
    day = A_SCHOOL_DAY

    def home(self, member=None, host=HOST):
        self.client.force_login((member or self.head).user)
        with on(self.day):
            return self.client.get(HOME, HTTP_HOST=host)

    def this_term(self):
        return Term.objects.get(pk=self.term_id)

    def group(self):
        return ClassGroup.objects.get(pk=self.jss1a_id)

    def sheet_at(self, *steps):
        """JSS 1A's sheet walked through `steps`, by the people who take them."""
        with connected_to(self.stmarys):
            sheet = chain.open_sheet(self.group(), self.this_term(), self.teacher.user)
            who = {
                "submit": self.teacher, "check": self.vp,
                "approve": self.head, "release": self.head,
            }
            for step in steps:
                getattr(chain, step)(sheet, who[step].user)
                sheet.refresh_from_db()
            return sheet


class TheDoorTests(HomeSetUp):
    def test_the_principal_gets_the_home(self):
        """The control: every refusal below would pass against a route that
        refused everybody."""
        response = self.home()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["school"], "St Mary's")
        self.assertEqual(body["released"], {"released": 0, "classes": 2})

    def test_the_vice_principal_gets_it_too(self):
        self.assertEqual(self.home(self.vp).status_code, 200)

    def test_everybody_else_is_refused_in_one_sentence_naming_nothing(self):
        for member in (self.teacher, self.bursar, self.children["ada"]):
            with self.subTest(role=member.role):
                response = self.home(member)
                self.assertEqual(response.status_code, 403)
                for leaked in ("JSS 1A", "St Mary's", "released"):
                    self.assertNotIn(leaked, response.content.decode())

    def test_they_are_refused_before_anything_is_read(self):
        """The oracle rule `chain_api._refuse_outsiders()` states: a refusal
        that read the tables first would cost what a real answer costs."""
        self.client.force_login(self.bursar.user)
        self.client.get(HOME, HTTP_HOST=HOST)
        with CaptureQueriesContext(connection) as seen:
            self.client.get(HOME, HTTP_HOST=HOST)
        read = " ".join(q["sql"] for q in seen.captured_queries)
        for table in ("results_resultsheet", "fees_feeledgerentry", "attendance_"):
            self.assertNotIn(table, read)

    def test_the_portal_has_no_such_route(self):
        self.assertEqual(self.home(host=PORTAL).status_code, 404)

    def test_a_principal_elsewhere_is_refused_here(self):
        """Grace's principal holds no role at St Mary's."""
        self.assertIn(self.home(self.their_head).status_code, (403, 404))

    def test_every_figure_is_readable_by_everyone_the_home_admits(self):
        """Why no figure is withheld card by card: the home admits only
        people every figure's own page would admit. Narrow any of those sets
        and this goes red before the home starts showing a figure its page
        would refuse."""
        for name, readers in (
            ("results chain", chain.OPENING_ROLES),
            ("absences", absences.VIEWING_ROLES),
            ("fees", fees_authority.READING_ROLES),
        ):
            with self.subTest(figure=name):
                self.assertLessEqual(summary.HOME_ROLES, readers)


class TheFiguresTests(HomeSetUp):
    def test_one_schools_figures_never_include_the_others(self):
        with connected_to(self.grace):
            fees.charge(
                self._grace_child(), Term.objects.get(pk=self.grace_term_id),
                900_000, narration="Tuition",
            )

        body = self.home().json()

        self.assertEqual(body["fees"], {"collected_kobo": 0, "billed_kobo": 0})
        self.assertEqual(body["released"]["classes"], 2)

    def _grace_child(self):
        return enroll_student(
            User.objects.create_user("gift", PASSWORD, full_name="Gift Obi"), self.grace
        )

    def test_billed_is_net_of_discounts_and_collected_is_money_that_stayed(self):
        ada, emeka = self.children["ada"], self.children["emeka"]
        with connected_to(self.stmarys):
            term = self.this_term()
            fees.charge(ada, term, 100_000, narration="Tuition")
            wrong = fees.charge(emeka, term, 70_000, narration="Charged in error")
            fees.reverse_entry(wrong, narration="Not his")
            fees.charge(emeka, term, 100_000, narration="Tuition")
            fees.discount(ada, term, 20_000, narration="Scholarship")
            fees.record_payment(ada, term, 50_000, method="cash")
            typo = fees.record_payment(emeka, term, 10_000, method="cash")
            fees.reverse_entry(typo, narration="Keyed twice")
            fees.refund(ada, term, 5_000, method="cash")
            # Another term's money is another term's.
            fees.record_payment(
                emeka, Term.objects.get(pk=self.second_term.pk), 999_000, method="cash"
            )

        figures = self.home().json()["fees"]

        # 100k + 100k charged (the reversed 70k is gone), less 20k discount.
        self.assertEqual(figures["billed_kobo"], 180_000)
        # 50k paid, the reversed 10k was never money, 5k went back.
        self.assertEqual(figures["collected_kobo"], 45_000)

    def test_present_today_is_out_of_who_was_marked(self):
        with connected_to(self.stmarys):
            registers.take_register(
                self.group(), self.this_term(), on=A_SCHOOL_DAY,
                absent_ids=[self.children["ada"].pk], by=self.teacher,
            )
            registers.take_register(
                self.group(), self.this_term(), on=A_SCHOOL_DAY - timedelta(days=1),
                absent_ids=[], by=self.teacher,
            )
            # Next week is not this week.
            registers.take_register(
                self.group(), self.this_term(), on=A_SCHOOL_DAY + timedelta(days=7),
                absent_ids=[], by=self.teacher,
            )

        present = self.home().json()["present"]

        self.assertEqual(present["today"], {"on": str(A_SCHOOL_DAY), "present": 3, "marked": 4})
        self.assertEqual([d["on"] for d in present["week"]], [
            str(A_SCHOOL_DAY - timedelta(days=1)), str(A_SCHOOL_DAY),
        ])
        # One register today, of the two classes with anybody placed in them.
        self.assertEqual((present["registers"], present["classes"]), (1, 2))

    def test_released_counts_classes_not_sheets(self):
        self.sheet_at("submit", "check", "approve", "release")

        self.assertEqual(self.home().json()["released"], {"released": 1, "classes": 2})

    def test_no_current_term_is_dashes_and_not_zeros(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=False)

        body = self.home().json()

        for figure in ("released", "fees", "absent"):
            self.assertIsNone(body[figure], figure)
        self.assertEqual(body["waiting"], [])

    def test_the_home_does_not_cost_more_as_the_school_grows(self):
        """Asserted as a shape, `test_chain_api`'s way: two runs compared, so
        `django_tenants`' per-query `SET search_path` cancels out."""
        # Every kind of row present in the small school too, so the larger one
        # asks nothing the smaller did not: one class in flight, one open.
        self.sheet_at("submit")
        with connected_to(self.stmarys):
            chain.open_sheet(ClassGroup.objects.get(pk=self.jss1b_id), self.this_term(), self.head.user)
        self.home()

        with CaptureQueriesContext(connection) as small:
            self.home()

        with connected_to(self.stmarys):
            term = self.this_term()
            for n in range(5):
                group = ClassGroup.objects.create(name=f"JSS 2{n}", level=2)
                child = enroll_student(
                    User.objects.create_user(f"kid{n}", PASSWORD, full_name=f"Kid {n}"),
                    self.stmarys,
                )
                academics.place_student(group, term, child)
                fees.charge(child, term, 1_000, narration="Tuition")
                chain.open_sheet(group, term, self.head.user)

        with CaptureQueriesContext(connection) as larger:
            response = self.home()

        self.assertEqual(response.json()["released"]["classes"], 7)
        self.assertEqual(len(larger.captured_queries), len(small.captured_queries))


class WaitingForYouTests(HomeSetUp):
    day = A_SCHOOL_DAY + timedelta(days=5)

    def rows(self, member=None):
        return {(r["kind"], r["class_group"]): r for r in self.home(member).json()["waiting"]}

    def at(self, moment, *steps):
        with clock(moment):
            return self.sheet_at(*steps)

    def test_an_approved_class_waits_on_the_principal_to_release_it(self):
        self.at(lagos(self.day), "submit", "check", "approve")

        row = self.rows()[("release", "JSS 1A")]

        self.assertEqual(row["href"], f"/results/?class={self.jss1a_id}")
        self.assertEqual(row["days"], 0)

    def test_a_submitted_class_waits_on_the_vice_principal_not_the_principal(self):
        self.at(lagos(self.day), "submit")

        self.assertIn(("check", "JSS 1A"), self.rows(self.vp))
        self.assertNotIn(("check", "JSS 1A"), self.rows())

    def test_days_are_counted_from_the_step_that_put_it_there(self):
        with clock(lagos(self.day - timedelta(days=9))):
            self.sheet_at("submit")
        sheet = self.at(lagos(self.day - timedelta(days=3), 23, 30), "check")
        self.assertEqual(sheet.state, "checked")

        # 23:30 in Lagos three days ago is three days ago, not two: the day is
        # the school's, and in UTC that step was 22:30 the same day.
        self.assertEqual(self.rows()[("approve", "JSS 1A")]["days"], 3)

    def test_oldest_first(self):
        with clock(lagos(self.day - timedelta(days=4))):
            self.sheet_at("submit", "check", "approve")
        with connected_to(self.stmarys):
            with clock(lagos(self.day - timedelta(days=1))):
                other = chain.open_sheet(
                    ClassGroup.objects.get(pk=self.jss1b_id), self.this_term(), self.head.user
                )
                self.assertEqual(other.state, "draft")

        kinds = [(r["kind"], r["class_group"]) for r in self.home().json()["waiting"]]

        self.assertEqual(kinds[0], ("release", "JSS 1A"))

    def test_remarks_missing_counts_children_without_the_principals_remark(self):
        self.at(lagos(self.day - timedelta(days=2)))
        with connected_to(self.stmarys):
            comments.write(self.this_term(), self.children["ada"], CommentAuthor.PRINCIPAL, "Good term.")
            # The class teacher's remark is not the principal's.
            comments.write(self.this_term(), self.children["emeka"], CommentAuthor.CLASS_TEACHER, "Fine.")

        row = self.rows()[("remarks", "JSS 1A")]

        self.assertEqual(row["missing"], 3)
        self.assertEqual(row["days"], 2)
        self.assertEqual(row["href"], f"/comments/?class={self.jss1a_id}")

    def test_remarks_are_the_principals_to_write_so_nobody_else_is_told(self):
        self.at(lagos(self.day))

        self.assertIn(("remarks", "JSS 1A"), self.rows())
        self.assertNotIn(("remarks", "JSS 1A"), self.rows(self.vp))

    def test_a_submitted_class_asks_for_no_remarks_because_none_can_be_written(self):
        """`comments.write()` refuses a remark once the sheet is submitted. A
        row sending the principal to a page where nothing can be done would
        be a false remedy."""
        self.at(lagos(self.day), "submit")

        self.assertNotIn(("remarks", "JSS 1A"), self.rows())

    def test_a_class_with_every_remark_written_is_not_waiting(self):
        self.at(lagos(self.day))
        with connected_to(self.stmarys):
            for child in self.children.values():
                comments.write(self.this_term(), child, CommentAuthor.PRINCIPAL, "Good term.")

        self.assertNotIn(("remarks", "JSS 1A"), self.rows())

    def test_sent_back_waits_on_whoever_sent_it_back(self):
        sheet = self.at(lagos(self.day), "submit", "check")
        with connected_to(self.stmarys), clock(lagos(self.day)):
            chain.send_back(sheet, self.head.user, "Maths is transposed.")

        self.assertIn(("sent_back", "JSS 1A"), self.rows())
        self.assertNotIn(("sent_back", "JSS 1A"), self.rows(self.vp))

    def test_a_released_class_waits_on_nobody(self):
        self.at(lagos(self.day), "submit", "check", "approve", "release")

        self.assertEqual(
            [k for k in self.rows() if k[1] == "JSS 1A"], [], "a released class is still waiting"
        )


class TodayTests(HomeSetUp):
    def test_steps_taken_today_are_listed_with_their_times(self):
        with clock(lagos(A_SCHOOL_DAY - timedelta(days=1), 16)):
            sheet = self.sheet_at("submit")
        with connected_to(self.stmarys), clock(lagos(A_SCHOOL_DAY, 10, 15)):
            chain.check(sheet, self.vp.user)

        body = self.home().json()["happened"]

        # Yesterday's submission is not today's news.
        self.assertEqual(body["steps"], [{"at": "10:15", "text": "JSS 1A checked"}])

    def test_payments_are_counted_on_the_day_they_were_recorded(self):
        """`recorded_at` and not `effective_on`: "recorded today" is what the
        office did today, and the ledger refuses an UPDATE, so the day is
        pinned to the real one rather than the fixture's."""
        with connected_to(self.stmarys):
            fees.record_payment(self.children["ada"], self.this_term(), 1_000, method="cash")
            fees.record_payment(self.children["emeka"], self.this_term(), 1_000, method="cash")

        self.client.force_login(self.head.user)
        with on(summary.timezone.localdate()):
            today = self.client.get(HOME, HTTP_HOST=HOST).json()["happened"]
        with on(summary.timezone.localdate() - timedelta(days=1)):
            yesterday = self.client.get(HOME, HTTP_HOST=HOST).json()["happened"]

        self.assertEqual(today["payments"], 2)
        self.assertEqual(yesterday["payments"], 0)


class TwoRolesTests(HomeSetUp):
    def test_a_member_with_two_roles_is_admitted_by_either(self):
        both = grant_membership(self.teacher.user, self.stmarys, Role.VICE_PRINCIPAL_ACADEMIC)

        self.assertEqual(self.home(both).status_code, 200)


def tearDownModule():
    connection.set_schema_to_public()
