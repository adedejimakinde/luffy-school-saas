"""Create accounts for this class: `POST /api/fees/virtual/classes/{id}/`.

Two schools throughout, and **both schools' first class has the same id**, so a press that
reached across schools would find somebody else's class by number.

The claims, each with the test that fails without it:

1. **It makes the missing accounts and skips the rest**: every child in the class gets
   one, a child who already has one is skipped and counted, and pressing twice makes
   nothing twice (no second Paystack customer, no second account).
2. **It reports honestly**: how many were made, how many skipped, each failure by name
   with its sentence, and how many are left. One child's failure does not stop the others
   or leave a half-made account behind.
3. **Paystack being down stops the batch** and says so, with nothing kept; a big class is
   done in batches.
4. **Bursar and administrator press it; the principal is told they may not; everyone else
   gets the flat 404**, and it never touches another school.
"""

from unittest import mock

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from fees import virtual
from fees.models import VirtualAccount
from fees.tests.paystack_fake import _Response
from fees.tests.test_bank import GRACE_HOST, HOST
from fees.tests.test_virtual import VirtualSetUp
from schools.models import PaystackRoute
from schools.tests.tenants import connected_to


class ClassSetUp(VirtualSetUp):
    def setUp(self):
        super().setUp()
        self.emeka = self.child("emeka", "Emeka Eze", self.stmarys)
        with connected_to(self.stmarys):
            self.jss1a = ClassGroup.objects.get(pk=self.group_id)
            self.term = Term.objects.get(pk=self.term_id)
            academics.place_student(self.jss1a, self.term, self.emeka)
        # Grace has a class of its own: its first class has the same id as St Mary's.
        self.zed = self.child("zed", "Zed Zulu", self.grace)
        with connected_to(self.grace):
            self.grace_term = Term.objects.get(is_current=True)
            self.grace_class = ClassGroup.objects.create(name="Year 7", level=1)
            for child in (self.zainab, self.zed):
                academics.place_student(self.grace_class, self.grace_term, child)

    def press(self, user=None, *, group=None, host=HOST, term_id=None):
        body = {} if term_id is None else {"term_id": term_id}
        return self.post(user or self.bursar, f"virtual/classes/{group or self.group_id}/", body, host=host)

    def numbers(self, school):
        with connected_to(school):
            return {a.student_membership_id: a.account_number for a in VirtualAccount.objects.all()}

    def refuse_customer(self, code):
        original = self.paystack._route

        def route(record):
            if record["path"] == "/dedicated_account" and (record["body"] or {}).get("customer") == code:
                return _Response(400, {"status": False, "message": "Customer is not eligible"})
            return original(record)

        self.paystack._route = route


class MakingTheMissingOnes(ClassSetUp):
    def test_every_child_in_the_class_gets_an_account_against_the_schools_split(self):
        self.connect_bank()
        split = self.rows(self.stmarys)[0].split_code

        response = self.press()

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["made"], body["skipped"], body["failed"], body["remaining"], body["stopped"]),
                         (3, 0, [], 0, None))
        numbers = self.numbers(self.stmarys)
        self.assertEqual(set(numbers), {self.ada.pk, self.chidi.pk, self.emeka.pk})
        self.assertEqual(len(set(numbers.values())), 3)
        self.assertEqual({r.school_id for r in PaystackRoute.objects.all()}, {self.stmarys.pk})
        splits = [d["body"]["split_code"] for d in self.paystack.sent("POST", "/dedicated_account")]
        self.assertEqual(splits, [split] * 3)

    def test_children_who_already_have_one_are_skipped_and_nobody_gets_two(self):
        """CONTROL: dropping `ensure()`'s existing-account check makes this red."""
        self.connect_bank()
        self.make()  # Ada, on her own page
        customers = len(self.paystack.sent("POST", "/customer"))

        body = self.press().json()

        self.assertEqual((body["made"], body["skipped"]), (2, 1))
        self.assertEqual(len(self.paystack.sent("POST", "/customer")), customers + 2)
        self.assertEqual(len(self.numbers(self.stmarys)), 3)

    def test_pressing_it_twice_makes_nothing_the_second_time(self):
        self.connect_bank()
        self.press()
        calls = len(self.paystack.requests)
        before = self.numbers(self.stmarys)

        again = self.press().json()

        self.assertEqual((again["made"], again["skipped"], again["failed"], again["remaining"]), (0, 3, [], 0))
        self.assertEqual(len(self.paystack.requests), calls, "a second press asked Paystack for something")
        self.assertEqual(self.numbers(self.stmarys), before)

    def test_a_class_where_everyone_has_one_is_a_200_that_asks_paystack_nothing(self):
        self.connect_bank()
        self.press()
        calls = len(self.paystack.requests)

        response = self.press()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.paystack.requests), calls)

    def test_only_this_classs_children_are_touched(self):
        self.connect_bank()
        other = self.child("outsider", "Olu Outsider", self.stmarys)  # in the school, in no class

        self.press()

        self.assertNotIn(other.pk, self.numbers(self.stmarys))

    def test_a_child_placed_in_a_different_term_is_not_in_this_terms_class(self):
        self.connect_bank()
        with connected_to(self.stmarys):
            later = Term.objects.create(
                session="2025/2026", name=TermName.SECOND, starts_on="2026-01-12", ends_on="2026-04-02", is_current=False
            )
        newcomer = self.child("newcomer", "New Comer", self.stmarys)
        with connected_to(self.stmarys):
            academics.place_student(self.jss1a, later, newcomer)

        current = self.press().json()
        chosen = self.press(term_id=later.pk).json()

        self.assertEqual(current["made"], 3)
        self.assertEqual((chosen["made"], chosen["skipped"]), (1, 0))
        self.assertIn(newcomer.pk, self.numbers(self.stmarys))


class ReportingHonestly(ClassSetUp):
    def test_one_childs_failure_is_reported_by_name_and_the_others_still_get_theirs(self):
        self.connect_bank()
        self.refuse_customer("CUS_test0002")  # the second child, by name order: Chidi

        body = self.press().json()

        self.assertEqual((body["made"], body["skipped"], body["remaining"]), (2, 0, 0))
        (failed,) = body["failed"]
        self.assertEqual(failed["student"], "Chidi Okafor")
        self.assertEqual(failed["student_membership_id"], self.chidi.pk)
        self.assertIn("Customer is not eligible", failed["detail"])
        numbers = self.numbers(self.stmarys)
        self.assertEqual(set(numbers), {self.ada.pk, self.emeka.pk})
        self.assertEqual(PaystackRoute.objects.count(), 2, "the failed child left a route behind")

    def test_the_failed_child_is_made_on_the_next_press_and_only_that_child(self):
        self.connect_bank()
        self.refuse_customer("CUS_test0002")
        self.press()
        self.paystack._route = type(self.paystack)._route.__get__(self.paystack)  # Paystack is well again

        body = self.press().json()

        self.assertEqual((body["made"], body["skipped"], body["failed"]), (1, 2, []))
        self.assertEqual(set(self.numbers(self.stmarys)), {self.ada.pk, self.chidi.pk, self.emeka.pk})

    def test_paystack_being_down_stops_the_batch_with_nothing_kept_and_says_so(self):
        self.connect_bank()
        self.paystack.down()

        body = self.press().json()

        self.assertEqual((body["made"], body["failed"], body["remaining"]), (0, [], 3))
        self.assertIn("not available", body["stopped"])
        self.assertNotIn("no route", str(body))
        self.assertEqual(self.numbers(self.stmarys), {})
        self.assertFalse(PaystackRoute.objects.exists())
        self.paystack.down(False)
        again = self.press().json()
        self.assertEqual((again["made"], again["stopped"]), (3, None))

    def test_paystack_rejecting_the_key_stops_it_and_leaks_nothing(self):
        self.connect_bank()
        self.paystack.fail_next(401, b'{"status": false, "message": "Invalid key"}')

        body = self.press().json()

        self.assertEqual(body["made"], 0)
        self.assertIsNotNone(body["stopped"])
        self.assertNotIn("Invalid key", str(body))

    def test_a_big_class_is_done_in_batches_and_the_person_is_told_how_many_are_left(self):
        self.connect_bank()
        with mock.patch.object(virtual, "CLASS_BATCH", 2):
            first = self.press().json()
            second = self.press().json()

        self.assertEqual((first["made"], first["remaining"]), (2, 1))
        self.assertEqual((second["made"], second["skipped"], second["remaining"]), (1, 2, 0))
        self.assertEqual(len(self.numbers(self.stmarys)), 3)

    def test_the_result_has_the_shape_the_page_reads(self):
        self.connect_bank()

        body = self.press().json()

        self.assertEqual(set(body), {"made", "skipped", "failed", "remaining", "stopped"})
        for key in ("made", "skipped", "remaining"):
            self.assertIsInstance(body[key], int)


class WhenItCannotRun(ClassSetUp):
    def test_without_the_schools_bank_it_says_so_and_asks_paystack_nothing(self):
        response = self.press()

        self.assertEqual(response.status_code, 409)
        self.assertIn("Connect the school's bank", response.json()["detail"])
        self.assertEqual(self.paystack.requests, [])
        self.assertEqual(self.numbers(self.stmarys), {})

    def test_with_no_current_term_and_none_named_it_says_so(self):
        self.connect_bank()
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)

        response = self.press()

        self.assertEqual(response.status_code, 422)
        self.assertIn("no current term", response.json()["detail"])

    def test_a_class_or_term_that_does_not_exist_is_a_404(self):
        self.connect_bank()

        self.assertEqual(self.press(group=999_999).status_code, 404)
        self.assertEqual(self.press(term_id=999_999).status_code, 404)


class WhoMayPress(ClassSetUp):
    def setUp(self):
        super().setUp()
        self.connect_bank()

    def test_the_administrator_may_press_it_too(self):
        self.assertEqual(self.press(self.admin).json()["made"], 3)

    def test_a_principal_is_told_they_may_not_and_nothing_is_made(self):
        self.assertEqual(self.press(self.principal).status_code, 403)
        self.assertEqual(self.numbers(self.stmarys), {})

    def test_a_teacher_a_parent_and_a_student_get_the_flat_404(self):
        for user in (self.teacher, self.parent, self.student_user):
            with self.subTest(user=user.username):
                self.assertEqual(self.press(user).status_code, 404)
        self.assertEqual(self.numbers(self.stmarys), {})

    def test_the_portal_has_none(self):
        self.assertEqual(self.press(host="testserver").status_code, 404)

    def test_another_schools_bursar_cannot_reach_this_one(self):
        self.assertEqual(self.press(self.their_bursar).status_code, 403)
        self.assertEqual(self.numbers(self.stmarys), {})


class TwoSchools(ClassSetUp):
    def test_each_schools_first_class_has_the_same_id_and_the_press_stays_in_its_own_school(self):
        self.connect_bank("stmarys")
        self.connect_bank("grace")
        self.assertEqual(self.group_id, self.grace_class.pk)  # both are the same number on purpose

        theirs = self.press(self.their_bursar, group=self.grace_class.pk, host=GRACE_HOST)

        self.assertEqual(theirs.json()["made"], 2)
        self.assertEqual(set(self.numbers(self.grace)), {self.zainab.pk, self.zed.pk})
        self.assertEqual(self.numbers(self.stmarys), {}, "Grace's press made accounts at St Mary's")

    def test_each_schools_children_settle_through_its_own_split_and_route_to_it(self):
        self.connect_bank("stmarys")
        self.connect_bank("grace")

        self.press()
        self.press(self.their_bursar, group=self.grace_class.pk, host=GRACE_HOST)

        ours, theirs = self.numbers(self.stmarys), self.numbers(self.grace)
        routes = {r.account_number: r.school_id for r in PaystackRoute.objects.all()}
        self.assertEqual({routes[n] for n in ours.values()}, {self.stmarys.pk})
        self.assertEqual({routes[n] for n in theirs.values()}, {self.grace.pk})
        self.assertEqual(len(routes), 5)
        with connected_to(self.stmarys):
            self.assertEqual({a.split_code for a in VirtualAccount.objects.all()}, {self.rows(self.stmarys)[0].split_code})
        with connected_to(self.grace):
            self.assertEqual({a.split_code for a in VirtualAccount.objects.all()}, {self.rows(self.grace)[0].split_code})

    def test_a_school_with_no_bank_is_refused_while_the_other_is_not(self):
        self.connect_bank("stmarys")

        ours = self.press()
        theirs = self.press(self.their_bursar, group=self.grace_class.pk, host=GRACE_HOST)

        self.assertEqual((ours.status_code, theirs.status_code), (200, 409))


class TheClassPage(ClassSetUp):
    def page(self, user, group=None, host=HOST):
        return self.get(user, f"classes/{group or self.group_id}/?term_id={self.term_id}", host=host).json()

    def test_it_says_how_many_children_have_none_and_offers_the_button_to_a_writer_with_a_bank(self):
        self.connect_bank()

        before = self.page(self.bursar)
        self.press()
        after = self.page(self.bursar)

        self.assertEqual((before["may_make_accounts"], before["accounts_missing"]), (True, 3))
        self.assertEqual((after["may_make_accounts"], after["accounts_missing"]), (True, 0))

    def test_a_partly_done_class_counts_only_the_missing(self):
        self.connect_bank()
        self.make()

        self.assertEqual(self.page(self.bursar)["accounts_missing"], 2)

    def test_a_principal_and_a_school_with_no_bank_are_not_offered_it(self):
        no_bank = self.page(self.bursar)
        self.connect_bank()
        principal = self.page(self.principal)

        self.assertEqual((no_bank["may_make_accounts"], no_bank["accounts_missing"]), (False, 3))
        self.assertEqual((principal["may_make_accounts"], principal["accounts_missing"]), (False, 0))
