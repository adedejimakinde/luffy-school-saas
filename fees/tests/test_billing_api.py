"""The billing routes: a class's bill, charging the class, and a child's
concessions. Fees B2, decided 2026-09-24.

B1's two schools and its people (`FeesApiSetUp`): St Mary's is under test,
Grace Academy has its own child.

Claims, each with the test that fails without it:

1. The same people as B1: the bursar and the administrator set bills and
   concessions; the principal and the vice principal (academic) read them and
   are told they may not; everybody else gets the books' flat 404.
2. Charging a class twice charges nobody twice, and says so.
3. A child already charged for the term by another class's bill is not
   charged again, and is named.
4. Revoking a concession needs a reason (422, nothing written); the answer
   says who revoked it, when and why.
5. Another school's child has no concessions here — not found, not refused.
"""

import json
import uuid

from academics import services as academics
from academics.models import ClassGroup, Term
from fees.models import FeeConcession, FeeConcessionRevocation, FeeEntryKind, FeeLedgerEntry
from fees.tests.test_fees_api import TUITION, FeesApiSetUp
from schools.tests.tenants import connected_to


class BillingApiSetUp(FeesApiSetUp):
    def put(self, user, path, body):
        self.client.force_login(user)
        return self.client.put(
            f"/api/fees/{path}", data=json.dumps(body), content_type="application/json",
            HTTP_HOST="st-marys.testserver",
        )

    def delete(self, user, path):
        self.client.force_login(user)
        return self.client.delete(f"/api/fees/{path}", HTTP_HOST="st-marys.testserver")

    def add_line(self, user=None, description="Tuition", amount="150,000", group_id=None):
        return self.post(
            user or self.bursar,
            f"classes/{group_id or self.group_id}/bill/lines/",
            {"term_id": self.term_id, "description": description, "amount": amount},
        )

    def charge_class(self, user=None, group_id=None):
        return self.post(
            user or self.bursar,
            f"classes/{group_id or self.group_id}/bill/charges/",
            {"term_id": self.term_id},
        )

    def grant(self, user=None, child=None, **overrides):
        body = {"amount": "50,000", "reason": "Staff child", "form_key": str(uuid.uuid4())}
        body.update(overrides)
        return self.post(user or self.bursar, f"students/{(child or self.ada).pk}/concessions/", body)

    def schedule_charges(self, child):
        with connected_to(self.stmarys):
            return FeeLedgerEntry.objects.filter(
                student_membership_id=child.pk, kind=FeeEntryKind.CHARGE, source_line__isnull=False
            ).count()


class WhoMayBillTests(BillingApiSetUp):
    """Claim 1."""

    def test_the_bursar_and_the_admin_set_a_bill(self):
        for user, description in ((self.bursar, "Tuition"), (self.admin, "PTA levy")):
            with self.subTest(user=user.username):
                answer = self.add_line(user, description=description)
                self.assertEqual(answer.status_code, 201, answer.content)
        body = self.get(self.principal, f"classes/{self.group_id}/bill/?term_id={self.term_id}").json()
        self.assertEqual([l["description"] for l in body["lines"]], ["Tuition", "PTA levy"])
        self.assertEqual(body["total_kobo"], 2 * 150_000_00)
        self.assertEqual(body["children"], 2)

    def test_the_principal_and_the_vp_read_it_and_are_told_they_may_not_set_it(self):
        self.add_line()
        with connected_to(self.stmarys):
            concession = FeeConcession.objects.create(
                student_membership_id=self.ada.pk, amount_kobo=TUITION, reason="Staff child"
            )
        for user in (self.principal, self.vp):
            with self.subTest(user=user.username):
                self.assertEqual(self.get(user, f"bills/?term_id={self.term_id}").status_code, 200)
                self.assertEqual(self.get(user, f"students/{self.ada.pk}/concessions/").status_code, 200)
                for answer in (
                    self.add_line(user, description="Uniform"),
                    self.charge_class(user),
                    self.grant(user),
                    self.post(user, f"concessions/{concession.pk}/revocation/", {"reason": "Left"}),
                ):
                    self.assertEqual(answer.status_code, 403)
                    self.assertEqual(
                        answer.json(),
                        {"detail": "Bills and concessions are set by the bursar or an administrator."},
                    )
        self.assertEqual(len(self.entries(FeeEntryKind.CHARGE)), 1, "only the fixture's own charge")
        with connected_to(self.stmarys):
            self.assertEqual(FeeConcession.objects.count(), 1)
            self.assertFalse(FeeConcessionRevocation.objects.exists())

    def test_a_teacher_a_parent_and_a_student_get_the_books_own_flat_404(self):
        """CONTROL B2-10: the billing routes skipping `_require_reader()` make
        this red."""
        missing = self.missing()
        paths = (
            f"bills/?term_id={self.term_id}",
            f"classes/{self.group_id}/bill/?term_id={self.term_id}",
            f"students/{self.ada.pk}/concessions/",
        )
        for user in (self.teacher, self.parent, self.student_user):
            for path in paths:
                with self.subTest(user=user.username, path=path):
                    answer = self.get(user, path)
                    self.assertEqual(answer.status_code, 404)
                    self.assertEqual(answer.content, missing)
            with self.subTest(user=user.username, write="line"):
                self.assertEqual(self.add_line(user).content, missing)
            with self.subTest(user=user.username, write="grant"):
                self.assertEqual(self.grant(user).content, missing)
        with connected_to(self.stmarys):
            self.assertFalse(FeeConcession.objects.exists())


class ChargingTwiceTests(BillingApiSetUp):
    """Claims 2 and 3: applying a bill never double-charges a child for the
    term."""

    def test_charging_a_class_twice_charges_nobody_twice(self):
        """The second press is an answer, not a refusal: nothing charged,
        everything skipped.

        CONTROL B2-6: `apply_to_class()` without its already-charged skip
        makes this red — the second press dies on
        `a_schedule_line_charges_a_child_once` instead of answering."""
        self.add_line()
        self.add_line(description="PTA levy", amount="15,000")

        first = self.charge_class()
        second = self.charge_class()

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual((first.json()["charges_posted"], first.json()["charges_skipped"]), (4, 0))
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual((second.json()["charges_posted"], second.json()["charges_skipped"]), (0, 4))
        self.assertEqual(second.json()["summary"], "0 charged, 4 skipped; 0 discounts, 0 skipped")
        for child in (self.ada, self.chidi):
            self.assertEqual(self.schedule_charges(child), 2)

    def test_a_child_billed_by_another_class_this_term_is_named_and_not_charged(self):
        """Ada is charged by JSS 1A's bill and moves to JSS 3A. Charging
        JSS 3A charges Ada's new classmate, and names Ada.

        CONTROL B2-1 (the schedule test's control) makes this red too."""
        self.add_line()
        self.charge_class()
        with connected_to(self.stmarys):
            senior = ClassGroup.objects.create(name="JSS 3A", level=3)
            term = Term.objects.get(pk=self.term_id)
            academics.move_student(senior, term, self.ada)
            dayo = self.child("dayo", "Dayo Ade", self.stmarys)
            academics.place_student(senior, term, dayo)
        self.add_line(group_id=senior.pk, description="Tuition", amount="180,000")

        answer = self.charge_class(group_id=senior.pk)

        self.assertEqual(answer.status_code, 200, answer.content)
        body = answer.json()
        self.assertEqual(body["charges_posted"], 1)
        self.assertEqual(
            body["billed_elsewhere"], [{"student_membership_id": self.ada.pk, "student": "Ada Obi"}]
        )
        self.assertIn("1 already billed by another class's bill", body["summary"])
        self.assertEqual(self.schedule_charges(self.ada), 1)
        self.assertEqual(self.schedule_charges(dayo), 1)

    def test_a_class_with_no_bill_is_told_to_start_one(self):
        answer = self.charge_class()
        self.assertEqual(answer.status_code, 422)
        self.assertIn("has no bill", answer.json()["detail"])


class EditingTheBillTests(BillingApiSetUp):
    def test_a_double_click_adds_one_line(self):
        first = self.add_line()
        again = self.add_line()

        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(len(again.json()["lines"]), 1)

    def test_the_same_name_at_another_amount_is_a_409(self):
        self.add_line()
        answer = self.add_line(amount="140,000")
        self.assertEqual(answer.status_code, 409)
        self.assertIn("already has a line called", answer.json()["detail"])

    def test_a_third_decimal_place_is_refused_here_too(self):
        answer = self.add_line(amount="150,000.005")
        self.assertEqual(answer.status_code, 422)

    def test_a_line_that_has_charged_is_kept_and_says_how_many(self):
        line_id = self.add_line().json()["lines"][0]["line_id"]
        self.charge_class()

        kept = self.delete(self.bursar, f"bill-lines/{line_id}/")
        changed = self.put(self.bursar, f"bill-lines/{line_id}/", {"description": "Tuition", "amount": "160,000"})

        self.assertEqual(kept.status_code, 409)
        self.assertEqual(changed.status_code, 200)
        [line] = changed.json()["lines"]
        self.assertEqual((line["amount_kobo"], line["charged"]), (160_000_00, 2))

    def test_an_unused_line_is_removed(self):
        self.add_line()
        line_id = self.add_line(description="Uniform", amount="5,000").json()["lines"][1]["line_id"]

        answer = self.delete(self.bursar, f"bill-lines/{line_id}/")

        self.assertEqual(answer.status_code, 200)
        self.assertEqual([l["description"] for l in answer.json()["lines"]], ["Tuition"])

    def test_every_class_in_use_is_listed_billed_or_not(self):
        with connected_to(self.stmarys):
            ClassGroup.objects.create(name="JSS 2A", level=2)
        self.add_line()

        body = self.get(self.bursar, f"bills/?term_id={self.term_id}").json()

        self.assertEqual(
            [(c["class_group"], c["children"], c["lines"], c["total_kobo"]) for c in body["classes"]],
            [("JSS 1A", 2, 1, 150_000_00), ("JSS 2A", 0, 0, 0)],
        )


class ConcessionRouteTests(BillingApiSetUp):
    """Claims 4 and 5."""

    def test_a_grant_is_listed_and_the_same_form_twice_grants_once(self):
        body = self.grant(form_key="0c8c3a52-3a38-4d0c-9d0a-6a2c8a5e9b11")
        again = self.grant(form_key="0c8c3a52-3a38-4d0c-9d0a-6a2c8a5e9b11")

        self.assertEqual((body.status_code, again.status_code), (201, 200))
        listed = self.get(self.vp, f"students/{self.ada.pk}/concessions/").json()
        self.assertEqual(
            [(c["amount_kobo"], c["reason"], c["revoked"]) for c in listed["concessions"]],
            [(50_000_00, "Staff child", None)],
        )

    def test_revoking_says_who_when_and_why(self):
        concession_id = self.grant().json()["concession"]["concession_id"]

        answer = self.post(self.admin, f"concessions/{concession_id}/revocation/", {"reason": "Parent left"})

        self.assertEqual(answer.status_code, 201, answer.content)
        revoked = answer.json()["revoked"]
        self.assertEqual((revoked["reason"], revoked["revoked_by"]), ("Parent left", "Ade Admin"))
        self.assertTrue(revoked["revoked_at"])
        listed = self.get(self.principal, f"students/{self.ada.pk}/concessions/").json()
        self.assertEqual(listed["concessions"][0]["revoked"]["reason"], "Parent left")

    def test_revoking_without_a_reason_is_refused_and_writes_nothing(self):
        """The user's control, decided 2026-09-24: a revocation without a
        reason is refused. CONTROL B2-7 makes this red."""
        concession_id = self.grant().json()["concession"]["concession_id"]

        for blank in ("", "   "):
            with self.subTest(reason=blank):
                answer = self.post(self.bursar, f"concessions/{concession_id}/revocation/", {"reason": blank})
                self.assertEqual(answer.status_code, 422)
                self.assertEqual(answer.json(), {"detail": "Say why, in a few words. The books keep the reason."})
        with connected_to(self.stmarys):
            self.assertFalse(FeeConcessionRevocation.objects.exists())

    def test_revoking_twice_is_a_409(self):
        concession_id = self.grant().json()["concession"]["concession_id"]
        self.post(self.bursar, f"concessions/{concession_id}/revocation/", {"reason": "Left"})

        again = self.post(self.bursar, f"concessions/{concession_id}/revocation/", {"reason": "Again"})

        self.assertEqual(again.status_code, 409)
        with connected_to(self.stmarys):
            self.assertEqual(FeeConcessionRevocation.objects.count(), 1)

    def test_a_revoked_concession_is_not_given_by_the_next_bill(self):
        self.add_line()
        concession_id = self.grant().json()["concession"]["concession_id"]
        self.post(self.bursar, f"concessions/{concession_id}/revocation/", {"reason": "Left"})

        answer = self.charge_class()

        self.assertEqual(answer.json()["discounts_posted"], 0)

    def test_another_schools_child_is_not_found_and_nothing_is_written_anywhere(self):
        missing = self.missing()

        for answer in (
            self.get(self.bursar, f"students/{self.zainab.pk}/concessions/"),
            self.grant(child=self.zainab),
        ):
            self.assertEqual(answer.status_code, 404)
            self.assertEqual(answer.content, missing)
        for school in (self.stmarys, self.grace):
            with connected_to(school):
                self.assertFalse(FeeConcession.objects.exists())
