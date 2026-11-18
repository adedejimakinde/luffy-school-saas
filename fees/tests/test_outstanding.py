"""One meaning of "outstanding", on every screen that says it. Audit finding G-12.

Decided: the whole-account balance of the children placed this term, summed
over those who owe, labelled "Outstanding (all terms)", with "of which this
term" as a smaller line (`fees.outstanding`). The dashboard, the fees list, the
fee book's class page and fee reminders must give the same children and the
same amounts, so each is read here from its own route or service and compared.

St Mary's, this term, JSS 1A:

| child | another term | this term | account | counted | of which this term |
| --- | --- | --- | --- | --- | --- |
| Ada | ₦20,000 owed | ₦10,000 billed, paid | ₦20,000 | yes | ₦0 |
| Emeka | ₦5,000 in credit | ₦20,000 billed | ₦15,000 | yes | ₦15,000 |
| Bisi | | ₦10,000 billed | ₦10,000 | yes | ₦10,000 |
| Tunde | | ₦10,000 billed, ₦12,000 paid | -₦2,000 | no (credit) | |
| Kola | ₦50,000 owed | not placed | ₦50,000 | no (not placed this term) | |

So: three children, ₦45,000, of which this term ₦25,000. Grace's child owes
₦90,000, and that must reach none of St Mary's figures.
"""

from unittest import mock

from django.core.cache import cache
from django.db import connection

from academics.models import Term
from accounts.models import User
from accounts.services import enroll_student
from fees import outstanding
from fees import services as fees
from home import facts
from home.tests.test_dashboard import DashboardSetUp
from notices import reminders
from notices.models import NoticeSettings
from results.tests.fixtures import HOST, PASSWORD
from schools.tests.tenants import connected_to

N = 100  # kobo per naira


class EveryScreenSaysTheSameOutstandingTests(DashboardSetUp):
    def setUp(self):
        super().setUp()
        self.kola = enroll_student(
            User.objects.create_user("kola", PASSWORD, full_name="Kola Ade"), self.stmarys
        )
        c = self.children
        with connected_to(self.stmarys):
            NoticeSettings.objects.update_or_create(pk=1, defaults={"fee_reminders": True})
            this, other = self.this_term(), Term.objects.get(pk=self.second_term.pk)
            fees.charge(c["ada"], other, 20_000 * N, narration="Arrears")
            fees.charge(c["ada"], this, 10_000 * N, narration="Tuition")
            fees.record_payment(c["ada"], this, 10_000 * N, method="cash")
            fees.record_payment(c["emeka"], other, 5_000 * N, method="cash")
            fees.charge(c["emeka"], this, 20_000 * N, narration="Tuition")
            fees.charge(c["bisi"], this, 10_000 * N, narration="Tuition")
            fees.charge(c["tunde"], this, 10_000 * N, narration="Tuition")
            fees.record_payment(c["tunde"], this, 12_000 * N, method="cash")
            fees.charge(self.kola, this, 50_000 * N, narration="Arrears")
        with connected_to(self.grace):
            fees.charge(self.grace_child, Term.objects.get(pk=self.grace_term_id), 90_000 * N, narration="Tuition")
        self.expected_children = {c["ada"].pk: 20_000 * N, c["emeka"].pk: 15_000 * N, c["bisi"].pk: 10_000 * N}

    # -- each screen, read the way it is read -----------------------------------

    def dashboard(self):
        cache.clear()
        with connected_to(self.stmarys):
            money = facts.read(self.stmarys, self.day)["money"]
        connection.set_schema_to_public()
        return money["owing"]["n"], money["owing"]["kobo"], money["owing"]["this_term"]

    def fees_list(self):
        self.client.force_login(self.bursar.user)
        body = self.client.get(f"/api/fees/classes/?term_id={self.term_id}", HTTP_HOST=HOST).json()
        return body

    def class_page(self):
        self.client.force_login(self.bursar.user)
        return self.client.get(
            f"/api/fees/classes/{self.jss1a_id}/?term_id={self.term_id}", HTTP_HOST=HOST
        ).json()

    def reminded(self):
        with connected_to(self.stmarys):
            answer = reminders.preview_reminders(self.this_term(), actor=self.bursar.user)
        return {c["student_membership_id"]: c["amount_kobo"] for c in answer["children"]}

    # -- the figures --------------------------------------------------------------

    def test_the_dashboard_counts_the_whole_account_of_children_placed_this_term(self):
        """The finding's own test idea: Ada owes last term's ₦20,000 and has
        paid this term in full. The dashboard used to say she owed nothing.

        CONTROL G12-1: `home.facts._MONEY`'s `owing` back to this term's entries
        only (`SELECT sum(amt) FROM e GROUP BY sid HAVING sum(amt) > 0`) makes
        this red: (3, 3_500_000) — Ada missing, Emeka at ₦20,000."""
        self.assertEqual(self.dashboard(), (3, 45_000 * N, 25_000 * N))

    def test_a_child_not_placed_this_term_is_not_counted(self):
        """Kola owes ₦50,000 and sits in no class this term.

        CONTROL G12-2: `OWING_SQL` reading every child's account rather than the
        placed children's would count him; the dashboard goes to ₦95,000."""
        rows = self.run_owing()
        self.assertNotIn(self.kola.pk, rows)
        self.assertEqual(set(rows), set(self.expected_children))

    def test_of_which_this_term_never_exceeds_the_balance_nor_goes_below_nothing(self):
        """Emeka: ₦20,000 billed this term, ₦5,000 in credit before it, so
        ₦15,000 owed, all of it this term's. Ada: ₦0 of hers is this term's.

        CONTROL G12-3: `of_this_term` as the plain this-term sum (no LEAST/
        GREATEST) makes this red: Emeka ₦20,000 of ₦15,000."""
        rows = self.run_owing()
        self.assertEqual(rows[self.children["emeka"].pk].this_term_kobo, 15_000 * N)
        self.assertEqual(rows[self.children["ada"].pk].this_term_kobo, 0)
        self.assertEqual(rows[self.children["bisi"].pk].this_term_kobo, 10_000 * N)

    def test_dashboard_fees_list_fee_book_and_reminders_agree(self):
        """The decision's whole point: four screens, one answer.

        CONTROL G12-4: `notices.reminders._batch()` choosing by this term's
        entries rather than `fees.outstanding.owing()` makes this red."""
        n, kobo, this_term = self.dashboard()

        books = self.fees_list()
        self.assertEqual((books["owing"], books["outstanding_kobo"], books["outstanding_this_term_kobo"]),
                         (n, kobo, this_term))
        (jss1a,) = [c for c in books["classes"] if c["class_group_id"] == self.jss1a_id]
        self.assertEqual((jss1a["owing"], jss1a["outstanding_kobo"], jss1a["outstanding_this_term_kobo"]),
                         (n, kobo, this_term))

        page = self.class_page()
        self.assertEqual((page["owing"], page["outstanding_kobo"], page["outstanding_this_term_kobo"]),
                         (n, kobo, this_term))
        owing_rows = {c["student_membership_id"]: c["balance_kobo"] for c in page["children"] if c["balance_kobo"] > 0}
        self.assertEqual(owing_rows, self.expected_children)

        self.assertEqual(self.reminded(), self.expected_children)
        self.assertEqual(sum(self.reminded().values()), kobo)

    def test_the_card_says_all_terms_and_this_terms_part(self):
        html = self.shown(self.head)[3]
        self.assertIn("Outstanding (all terms)", html)
        self.assertIn("of which this term: ₦25,000", html)
        self.assertIn("3 students owe", html)

    def test_the_attention_item_says_the_same(self):
        html = self.shown(self.bursar)[3]
        self.assertIn("3 students owe fees", html)
        self.assertNotIn("fees for this term", html)
        self.assertIn("outstanding (all terms), of which this term", html)

    def test_the_other_schools_debt_reaches_none_of_these_figures(self):
        """Grace's child owes ₦90,000 in Grace's own schema; St Mary's figures
        are the same with or without it, and Grace's are its own."""
        self.assertEqual(self.dashboard()[1], 45_000 * N)
        self.assertNotIn(self.grace_child.pk, self.reminded())
        with connected_to(self.grace):
            theirs = outstanding.total(outstanding.owing(Term.objects.get(pk=self.grace_term_id)))
        connection.set_schema_to_public()
        self.assertEqual((theirs.children, theirs.kobo), (1, 90_000 * N))

    def run_owing(self):
        with connected_to(self.stmarys):
            rows = outstanding.owing(self.this_term())
        connection.set_schema_to_public()
        return rows
