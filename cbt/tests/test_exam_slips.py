"""Exam officers, exam PINs and their slips: `docs/cbt.md`, Phase 2 step 2.

Two schools in every class, on their own hosts (`results.tests.fixtures.ChainSetUp`),
whose first class, term and child share ids, and whose first children share an
admission number. The claims, each with a control in `docs/cbt.md`:

- **Only the principal, the administrator and an exam officer print slips**, for any
  class; nobody else, whatever subjects and classes they are assigned. A refused print
  writes nothing.
- **Only the principal names and ends exam officers**, and only this school's teacher,
  vice principal or administrator. Every naming and ending is written down, who and
  when, in a table that cannot be edited.
- **Printing again cancels the old PINs**, for every student now on the class, wherever
  their old slip was printed; a lost slip cancels only that student's. At most one live
  PIN per student per term, by constraint. The old PIN then fails.
- **A PIN is kept only as a keyed digest**, under a server secret; no PIN is in the
  database, and the PDF is stored nowhere.
- **One school's officers, slips and PINs are never another's.**
- **The administrator has no way to a bank or a question**, named exam officer or not.
"""

import hashlib
import re
from unittest import mock

from django.db import connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from academics import services as academics
from academics.models import Term
from accounts.models import Membership, MembershipStatus, Role, User
from accounts.services import grant_membership
from cbt import access, pins
from cbt import pdf as cbt_pdf
from cbt.models import ExamOfficerGrant, ExamPin, PinSlipPrint
from gradebook.models import SubjectTeacher
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to
from tests.refusals import RefusalAssertions

BASE = "/api/cbt/"

#: The admission numbers. Grace's first child has St Mary's first child's number.
NUMBERS = {"ada": "SM/001", "emeka": "SM/002", "bisi": "SM/003"}


class ExamSlipsSetUp(RefusalAssertions, ChainSetUp):
    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )
        self.their_admin = grant_membership(
            User.objects.create_user("gbenga", PASSWORD, full_name="Gbenga Admin"), self.grace, Role.ADMIN
        )
        self.tayo = grant_membership(
            User.objects.create_user("tayo", PASSWORD, full_name="Tayo Ojo"), self.stmarys, Role.TEACHER
        )
        for handle, number in NUMBERS.items():
            Membership.objects.filter(pk=self.children[handle].pk).update(reference=number)
        # Tunde has no admission number; Bimpe, in JSS 1B, has one.
        Membership.objects.filter(pk=self.bimpe.pk).update(reference="SM/005")
        Membership.objects.filter(pk=self.grace_child.pk).update(reference="SM/001")
        for handle in list(self.children):
            self.children[handle].refresh_from_db()
        self.bimpe.refresh_from_db()
        self.grace_child.refresh_from_db()

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    # -- HTTP -----------------------------------------------------------------

    def as_(self, who):
        self.client.force_login(who.user if isinstance(who, Membership) else who)
        return self.client

    def overview(self, who, host=HOST):
        return self.as_(who).get(f"{BASE}slips/", HTTP_HOST=host)

    def class_slips(self, who, group_id, host=HOST):
        return self.as_(who).get(f"{BASE}slips/classes/{group_id}/", HTTP_HOST=host)

    def print_class(self, who, group_id, host=HOST):
        """The response, and the slips the PDF was rendered from (the raw PINs)."""
        captured = {}
        real = cbt_pdf.render_slips

        def keep(slips, address):
            captured["slips"], captured["address"] = slips, address
            return real(slips, address)

        with mock.patch("cbt.api.pdf.render_slips", side_effect=keep):
            response = self.as_(who).post(f"{BASE}slips/classes/{group_id}/print/", HTTP_HOST=host)
        connection.set_schema_to_public()
        return response, captured.get("slips"), captured.get("address")

    def print_student(self, who, group_id, student, host=HOST):
        captured = {}
        real = cbt_pdf.render_slips

        def keep(slips, address):
            captured["slips"] = slips
            return real(slips, address)

        with mock.patch("cbt.api.pdf.render_slips", side_effect=keep):
            response = self.as_(who).post(
                f"{BASE}slips/classes/{group_id}/students/{student.pk}/print/", HTTP_HOST=host
            )
        connection.set_schema_to_public()
        return response, captured.get("slips")

    def name(self, who, membership, note="", host=HOST):
        return self.as_(who).post(
            f"{BASE}officers/",
            data={"membership_id": membership.pk, "note": note},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def end(self, who, membership, host=HOST):
        return self.as_(who).post(
            f"{BASE}officers/{membership.pk}/end/", data={}, content_type="application/json", HTTP_HOST=host
        )

    # -- reading the tables ---------------------------------------------------

    def pins_of(self, school=None, **filters):
        with connected_to(school or self.stmarys):
            return list(ExamPin.objects.filter(**filters).order_by("id"))

    def prints(self, school=None):
        with connected_to(school or self.stmarys):
            return list(PinSlipPrint.objects.order_by("id"))

    def grants(self, school=None):
        with connected_to(school or self.stmarys):
            return list(ExamOfficerGrant.objects.order_by("id"))

    def check(self, number, pin, school=None, term_id=None):
        school = school or self.stmarys
        with connected_to(school):
            term = Term.objects.get(pk=term_id or (self.term_id if school == self.stmarys else self.grace_term_id))
            found = pins.check(school, term, number, pin)
        return found.pk if found else None

    def pin_for(self, slips, name):
        return next(s.pin for s in slips.slips if s.student_name == name)


class OnlyThePrincipalTheAdministratorAndAnExamOfficerPrintTests(ExamSlipsSetUp):
    def test_the_principal_prints_a_class(self):
        response, slips, address = self.print_class(self.head, self.jss1a_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(sorted(s.student_name for s in slips.slips), ["Ada Obi", "Bisi Ade", "Emeka Nwosu"])
        self.assertEqual(slips.without_a_number, ["Tunde Cole"])
        self.assertEqual(address, f"{HOST}/sit/")
        self.assertEqual(len(self.pins_of(cancelled_at__isnull=True)), 3)
        [row] = self.prints()
        self.assertEqual(
            (row.kind, row.class_group_name, row.count, row.cancelled_count, row.without_a_number, row.printed_by_id),
            ("class", "JSS 1A", 3, 0, 1, self.head.user.pk),
        )
        self.assertEqual(row.printed_by_name, "Ngozi Eze")

    def test_the_administrator_prints_a_class(self):
        response, slips, _ = self.print_class(self.admin, self.jss1b_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([s.student_name for s in slips.slips], ["Bimpe Ojo"])
        self.assertEqual(self.prints()[0].printed_by_id, self.admin.user.pk)

    def test_nobody_else_reads_or_prints_and_a_refusal_writes_nothing(self):
        student = self.children["ada"]
        for who in (self.teacher, self.tayo, self.vp, self.bursar, student):
            with self.subTest(role=who.role, who=who.user.username):
                self.assertEqual(self.overview(who).status_code, 403)
                self.assertEqual(self.class_slips(who, self.jss1a_id).status_code, 403)
                response, slips, _ = self.print_class(who, self.jss1a_id)
                self.assertEqual(response.status_code, 403)
                self.assertIsNone(slips)
                response, _ = self.print_student(who, self.jss1a_id, self.children["ada"])
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.pins_of(), [])
        self.assertEqual(self.prints(), [])

    def test_being_given_a_class_as_its_subject_teacher_gives_no_slips(self):
        """The assignments decide marking, not slips: a teacher of JSS 1A is refused its slips."""
        with connected_to(self.stmarys):
            SubjectTeacher.objects.create(
                term_id=self.term_id, class_group_id=self.jss1a_id, subject_id=self.maths_id,
                teacher_membership_id=self.teacher.pk, assigned_by_id=self.head.user.pk,
            )
        response, _, _ = self.print_class(self.teacher, self.jss1a_id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.pins_of(), [])

    def test_signed_out_is_told_to_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(f"{BASE}slips/", HTTP_HOST=HOST).status_code, 401)
        self.assertEqual(self.client.post(f"{BASE}slips/classes/{self.jss1a_id}/print/", HTTP_HOST=HOST).status_code, 401)

    def test_a_named_exam_officer_prints_any_class_and_stops_when_it_ends(self):
        self.assertEqual(self.name(self.head, self.teacher).status_code, 200)
        self.assertEqual(self.name(self.head, self.vp).status_code, 200)

        # Kemi teaches nothing in JSS 1B, and prints it.
        response, slips, _ = self.print_class(self.teacher, self.jss1b_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s.student_name for s in slips.slips], ["Bimpe Ojo"])
        self.assertEqual(self.overview(self.teacher).status_code, 200)
        response, _, _ = self.print_class(self.vp, self.jss1a_id)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(self.end(self.head, self.teacher).status_code, 200)
        response, _, _ = self.print_class(self.teacher, self.jss1b_id)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.overview(self.teacher).status_code, 403)
        self.assertEqual(len(self.prints()), 2)

    def test_an_exam_officer_whose_teaching_place_is_suspended_cannot_print(self):
        """Still signed in here as the bursar, so the refusal is the grant's, not the door's."""
        sola = User.objects.create_user("sola", PASSWORD, full_name="Sola Ige")
        teaching = grant_membership(sola, self.stmarys, Role.TEACHER)
        grant_membership(sola, self.stmarys, Role.BURSAR)
        self.name(self.head, teaching)
        response, _, _ = self.print_class(sola, self.jss1a_id)
        self.assertEqual(response.status_code, 200)

        Membership.objects.filter(pk=teaching.pk).update(status=MembershipStatus.SUSPENDED)
        response, _, _ = self.print_class(sola, self.jss1a_id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.overview(sola).status_code, 403)
        self.assertEqual(len(self.prints()), 1)

    def test_no_term_open_refuses_with_a_sentence(self):
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)
        response, slips, _ = self.print_class(self.head, self.jss1a_id)

        self.assertEqual(response.status_code, 422)
        self.assertIn("No term is open", response.json()["detail"])
        self.assertIsNone(slips)


class OnlyThePrincipalNamesExamOfficersTests(ExamSlipsSetUp):
    def test_the_principal_names_a_teacher_the_vice_principal_and_the_administrator(self):
        for who in (self.teacher, self.vp, self.admin):
            with self.subTest(role=who.role):
                response = self.name(self.head, who, note="Runs the lab")
                self.assertEqual(response.status_code, 200)
        body = self.overview(self.head).json()
        self.assertEqual(
            sorted(o["name"] for o in body["officers"]), ["Ade Admin", "Kemi Bello", "Vera Okoro"]
        )
        self.assertTrue(body["may_name"])

    def test_nobody_else_names_or_ends_one_and_nothing_is_written(self):
        self.name(self.head, self.teacher)
        before = len(self.grants())
        for who in (self.admin, self.vp, self.teacher, self.tayo, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.name(who, self.tayo).status_code, 403)
                self.assertEqual(self.end(who, self.teacher).status_code, 403)
        self.assertEqual(len(self.grants()), before)
        with connected_to(self.stmarys):
            self.assertEqual(access.officer_memberships([self.teacher.pk, self.tayo.pk]), {self.teacher.pk})

    def test_only_a_teacher_vice_principal_or_administrator_here_can_be_named(self):
        student = self.children["ada"]
        for who in (self.bursar, student, self.head, self.grace_teacher, self.their_admin):
            with self.subTest(who=who.user.username, school=who.school.slug):
                response = self.name(self.head, who)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.grants(), [])
        self.assertEqual(self.grants(self.grace), [])

    def test_naming_twice_or_ending_one_not_named_is_refused(self):
        self.assertEqual(self.name(self.head, self.teacher).status_code, 200)
        self.assertEqual(self.name(self.head, self.teacher).status_code, 422)
        self.assertEqual(self.end(self.head, self.tayo).status_code, 422)
        self.assertEqual(len(self.grants()), 1)

    def test_every_naming_and_ending_says_who_and_when(self):
        self.name(self.head, self.teacher, note="  Lab   two ")
        self.end(self.head, self.teacher)

        named, ended = self.grants()
        self.assertEqual(
            (named.kind, named.membership_id, named.membership_name, named.role, named.by_id, named.by_name, named.note),
            ("named", self.teacher.pk, "Kemi Bello", Role.TEACHER.value, self.head.user.pk, "Ngozi Eze", "Lab two"),
        )
        self.assertEqual((ended.kind, ended.by_id), ("ended", self.head.user.pk))
        self.assertLessEqual(named.at, ended.at)
        changes = self.overview(self.head).json()["officer_changes"]
        self.assertEqual([c["kind"] for c in changes], ["ended", "named"])

    def test_the_record_cannot_be_edited_or_deleted(self):
        self.name(self.head, self.teacher)
        with connected_to(self.stmarys):
            with transaction.atomic(), self.assertRefusedBy("cbt_examofficergrant is append-only"):
                ExamOfficerGrant.objects.update(kind="ended")
            with transaction.atomic(), self.assertRefusedBy("cbt_examofficergrant is append-only"):
                ExamOfficerGrant.objects.all().delete()

    def test_the_office_sees_who_the_officers_are_and_cannot_change_them(self):
        self.name(self.head, self.teacher)
        body = self.overview(self.admin).json()

        self.assertFalse(body["may_name"])
        self.assertEqual(body["candidates"], [])
        self.assertEqual([o["name"] for o in body["officers"]], ["Kemi Bello"])


class PrintingAgainCancelsTheOldPinsTests(ExamSlipsSetUp):
    def test_printing_a_class_again_cancels_every_old_pin_and_the_old_pin_then_fails(self):
        _, first, _ = self.print_class(self.head, self.jss1a_id)
        old = self.pin_for(first, "Ada Obi")
        ada = self.children["ada"].pk
        self.assertEqual(self.check("SM/001", old), ada)

        _, second, _ = self.print_class(self.admin, self.jss1a_id)
        new = self.pin_for(second, "Ada Obi")

        self.assertIsNone(self.check("SM/001", old))
        self.assertEqual(self.check("SM/001", new), ada)
        live = self.pins_of(cancelled_at__isnull=True)
        self.assertEqual(len(live), 3)
        cancelled = self.pins_of(cancelled_at__isnull=False)
        self.assertEqual(len(cancelled), 3)
        first_row, second_row = self.prints()
        self.assertEqual((second_row.count, second_row.cancelled_count), (3, 3))
        self.assertEqual({p.cancelled_by_print_id for p in cancelled}, {second_row.pk})
        self.assertEqual({p.issued_by_print_id for p in live}, {second_row.pk})

    def test_a_lost_slip_cancels_only_that_students_pin(self):
        _, first, _ = self.print_class(self.head, self.jss1a_id)
        response, one = self.print_student(self.head, self.jss1a_id, self.children["emeka"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual([s.student_name for s in one.slips], ["Emeka Nwosu"])
        self.assertIsNone(self.check("SM/002", self.pin_for(first, "Emeka Nwosu")))
        self.assertEqual(self.check("SM/002", one.slips[0].pin), self.children["emeka"].pk)
        self.assertEqual(self.check("SM/001", self.pin_for(first, "Ada Obi")), self.children["ada"].pk)
        row = self.prints()[-1]
        self.assertEqual((row.kind, row.student_membership_id, row.count, row.cancelled_count), ("student", self.children["emeka"].pk, 1, 1))

    def test_a_student_who_moved_class_loses_the_old_slip_when_the_new_class_is_printed(self):
        _, first, _ = self.print_class(self.head, self.jss1a_id)
        with connected_to(self.stmarys):
            academics.move_student(self.jss1b, Term.objects.get(pk=self.term_id), self.children["ada"])
        _, second, _ = self.print_class(self.head, self.jss1b_id)

        self.assertEqual(sorted(s.student_name for s in second.slips), ["Ada Obi", "Bimpe Ojo"])
        self.assertIsNone(self.check("SM/001", self.pin_for(first, "Ada Obi")))
        self.assertEqual(self.check("SM/001", self.pin_for(second, "Ada Obi")), self.children["ada"].pk)
        self.assertEqual(len(self.pins_of(student_membership_id=self.children["ada"].pk, cancelled_at__isnull=True)), 1)

    def test_at_most_one_live_pin_per_student_per_term(self):
        self.print_class(self.head, self.jss1a_id)
        with connected_to(self.stmarys):
            live = ExamPin.objects.filter(cancelled_at__isnull=True).first()
            with transaction.atomic(), self.assertRefusedBy("one_live_exam_pin_per_student_per_term"):
                ExamPin.objects.create(
                    student_membership_id=live.student_membership_id,
                    term_id=live.term_id,
                    class_group_id=live.class_group_id,
                    digest="0" * 64,
                    issued_by_print_id=live.issued_by_print_id,
                    issued_by_id=1,
                )

    def test_a_student_with_no_admission_number_gets_no_pin_and_no_lone_slip(self):
        self.print_class(self.head, self.jss1a_id)
        tunde = self.children["tunde"]

        self.assertEqual(self.pins_of(student_membership_id=tunde.pk), [])
        response, slips = self.print_student(self.head, self.jss1a_id, tunde)
        self.assertEqual(response.status_code, 422)
        self.assertIn("no admission number", response.json()["detail"])
        self.assertIsNone(slips)

    def test_a_student_not_in_the_class_cannot_be_printed_for_it(self):
        response, slips = self.print_student(self.head, self.jss1a_id, self.bimpe)

        self.assertEqual(response.status_code, 422)
        self.assertIsNone(slips)
        self.assertEqual(self.prints(), [])

    def test_a_pin_is_only_ever_cancelled_once_and_never_deleted_or_rewritten(self):
        self.print_class(self.head, self.jss1a_id)
        with connected_to(self.stmarys):
            pin = ExamPin.objects.first()
            with transaction.atomic(), self.assertRefusedBy("an_exam_pin_is_only_ever_cancelled"):
                ExamPin.objects.filter(pk=pin.pk).delete()
            with transaction.atomic(), self.assertRefusedBy("an_exam_pin_is_only_ever_cancelled"):
                ExamPin.objects.filter(pk=pin.pk).update(digest="f" * 64)
            print_row = PinSlipPrint.objects.first()
            ExamPin.objects.filter(pk=pin.pk).update(cancelled_at=print_row.at, cancelled_by_print=print_row)
            with transaction.atomic(), self.assertRefusedBy("an_exam_pin_is_only_ever_cancelled"):
                ExamPin.objects.filter(pk=pin.pk).update(cancelled_at=None, cancelled_by_print=None)

    def test_the_print_log_cannot_be_edited_or_deleted(self):
        self.print_class(self.head, self.jss1a_id)
        with connected_to(self.stmarys):
            with transaction.atomic(), self.assertRefusedBy("cbt_pinslipprint is append-only"):
                PinSlipPrint.objects.update(count=99)
            # Raw, because Django's own PROTECT would refuse first and the trigger is the claim.
            with self.assertRefusedBy("cbt_pinslipprint is append-only"), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM cbt_pinslipprint")

    def test_a_render_that_fails_mints_and_cancels_nothing(self):
        _, first, _ = self.print_class(self.head, self.jss1a_id)
        self.client.raise_request_exception = False
        with mock.patch("cbt.api.pdf.render_slips", side_effect=RuntimeError("no fonts")):
            response = self.as_(self.head).post(f"{BASE}slips/classes/{self.jss1a_id}/print/", HTTP_HOST=HOST)
        connection.set_schema_to_public()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.prints()), 1)
        self.assertEqual(self.check("SM/001", self.pin_for(first, "Ada Obi")), self.children["ada"].pk)


class OneAnswerForEveryFailureTests(ExamSlipsSetUp):
    def setUp(self):
        super().setUp()
        _, self.slips, _ = self.print_class(self.head, self.jss1a_id)
        _, self.b_slips, _ = self.print_class(self.head, self.jss1b_id)
        self.ada = self.pin_for(self.slips, "Ada Obi")

    def test_the_right_number_and_pin_however_spaced(self):
        for typed in (self.ada, pins.printed(self.ada), f" {self.ada[:4]}-{self.ada[4:]} "):
            with self.subTest(typed=typed):
                self.assertEqual(self.check(" sm/001 ", typed), self.children["ada"].pk)

    def test_every_failure_is_none(self):
        wrong = f"{(int(self.ada) + 1) % 10 ** 8:08d}"
        emeka = self.pin_for(self.slips, "Emeka Nwosu")
        for number, pin in (
            ("SM/001", wrong),
            ("SM/999", self.ada),
            ("SM/002", self.ada),  # Ada's PIN with Emeka's number
            ("SM/001", emeka),  # Emeka's PIN with Ada's number
            ("", self.ada),
            ("SM/001", ""),
            ("SM/001", self.ada[:7]),
            ("SM/001", self.ada + "0"),
        ):
            with self.subTest(number=number, pin=pin):
                self.assertIsNone(self.check(number, pin))

    def test_another_terms_pin_is_none(self):
        with connected_to(self.stmarys):
            self.assertIsNone(pins.check(self.stmarys, Term.objects.get(pk=self.second_term.pk), "SM/001", self.ada))

    def test_a_student_who_has_left_is_none(self):
        self.children["ada"].end()

        self.assertIsNone(self.check("SM/001", self.ada))

    def test_checking_writes_nothing(self):
        with connected_to(self.stmarys):
            term = Term.objects.get(pk=self.term_id)
            with CaptureQueriesContext(connection) as queries:
                pins.check(self.stmarys, term, "SM/001", "00000000")
                pins.check(self.stmarys, term, "SM/001", self.ada)
        writes = [q["sql"] for q in queries.captured_queries if re.match(r"\s*(INSERT|UPDATE|DELETE)", q["sql"], re.I)]
        self.assertEqual(writes, [])


class APinIsKeptOnlyAsAKeyedDigestTests(ExamSlipsSetUp):
    def test_no_pin_is_in_the_database_and_the_digest_is_not_a_plain_hash(self):
        _, slips, _ = self.print_class(self.head, self.jss1a_id)
        for slip in slips.slips:
            with self.subTest(student=slip.student_name):
                with connected_to(self.stmarys):
                    row = ExamPin.objects.get(
                        student_membership_id=Membership.objects.get(reference=slip.admission_number, school=self.stmarys).pk,
                        cancelled_at__isnull=True,
                    )
                    rows = [str(v) for row in ExamPin.objects.values_list() for v in row]
                    rows += [str(v) for row in PinSlipPrint.objects.values_list() for v in row]
                self.assertFalse([v for v in rows if slip.pin in v])
                self.assertNotEqual(row.digest, hashlib.sha256(slip.pin.encode()).hexdigest())
                self.assertEqual(len(row.digest), 64)

    def test_the_key_is_the_servers_and_without_it_no_pin_opens(self):
        _, slips, _ = self.print_class(self.head, self.jss1a_id)
        ada = self.pin_for(slips, "Ada Obi")

        self.assertEqual(self.check("SM/001", ada), self.children["ada"].pk)
        with override_settings(EXAM_PIN_KEY="another-servers-key"):
            self.assertIsNone(self.check("SM/001", ada))

    def test_the_digest_is_bound_to_the_school_the_student_and_the_term(self):
        base = pins.digest(1, 2, 3, "12345678")
        self.assertEqual(len({base, pins.digest(9, 2, 3, "12345678"), pins.digest(1, 9, 3, "12345678"), pins.digest(1, 2, 9, "12345678")}), 4)

    def test_the_pdf_is_sent_once_and_stored_nowhere(self):
        with mock.patch("django.core.files.storage.default_storage.save") as saved:
            response, _, _ = self.print_class(self.head, self.jss1a_id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertTrue(response["Content-Disposition"].startswith('attachment; filename="exam-slips-jss-1a'))
        saved.assert_not_called()
        for model in (ExamPin, PinSlipPrint, ExamOfficerGrant):
            with self.subTest(model=model.__name__):
                self.assertFalse(
                    [f.name for f in model._meta.get_fields() if f.get_internal_type() in ("FileField", "BinaryField", "TextField")]
                )

    def test_a_slip_says_where_to_go_and_carries_its_pin(self):
        _, slips, address = self.print_class(self.head, self.jss1a_id)
        html = cbt_pdf.slips_html(slips, address)

        self.assertIn(f"{HOST}/sit/", html)
        self.assertIn(pins.printed(self.pin_for(slips, "Ada Obi")), html)
        self.assertIn("Tunde Cole", html)  # named, with no slip
        for delimiter in ("{#", "#}", "{%", "{{", "}}"):
            self.assertNotIn(delimiter, html)


class OneSchoolIsNeverAnothersTests(ExamSlipsSetUp):
    def test_a_principal_at_one_school_cannot_print_or_name_at_the_other(self):
        response, slips, _ = self.print_class(self.head, self.grace_group_id, host=THEIR_HOST)
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(slips)
        self.assertEqual(self.overview(self.head, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.name(self.head, self.grace_teacher, host=THEIR_HOST).status_code, 403)
        self.assertEqual(self.pins_of(self.grace), [])
        self.assertEqual(self.grants(self.grace), [])

    def test_the_same_class_id_prints_only_this_schools_class(self):
        self.assertEqual(self.jss1a_id, self.grace_group_id)
        self.print_class(self.head, self.jss1a_id)

        self.assertEqual(len(self.pins_of(self.stmarys)), 3)
        self.assertEqual(self.pins_of(self.grace), [])
        self.assertEqual(self.prints(self.grace), [])

        _, theirs, _ = self.print_class(self.their_head, self.grace_group_id, host=THEIR_HOST)
        self.assertEqual([s.student_name for s in theirs.slips], ["Chidi Eze"])

    def test_one_schools_pin_opens_nothing_at_the_other_with_the_same_admission_number(self):
        _, ours, _ = self.print_class(self.head, self.jss1a_id)
        _, theirs, _ = self.print_class(self.their_head, self.grace_group_id, host=THEIR_HOST)
        ada, chidi = self.pin_for(ours, "Ada Obi"), self.pin_for(theirs, "Chidi Eze")

        self.assertIsNone(self.check("SM/001", ada, school=self.grace))
        self.assertIsNone(self.check("SM/001", chidi, school=self.stmarys))
        self.assertEqual(self.check("SM/001", chidi, school=self.grace), self.grace_child.pk)
        # Asked about one school while the connection is on the other: nothing, with
        # either school's PIN.
        with connected_to(self.grace):
            grace_term = Term.objects.get(pk=self.grace_term_id)
            self.assertIsNone(pins.check(self.stmarys, grace_term, "SM/001", ada))
            self.assertIsNone(pins.check(self.stmarys, grace_term, "SM/001", chidi))

    def test_a_principal_cannot_name_the_other_schools_staff_even_by_id(self):
        response = self.name(self.their_head, self.teacher, host=THEIR_HOST)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.grants(self.grace), [])
        self.assertEqual(self.grants(), [])

    def test_an_officer_at_one_school_is_nothing_at_the_other(self):
        tunji = User.objects.create_user("tunji", PASSWORD, full_name="Tunji Ola")
        here = grant_membership(tunji, self.stmarys, Role.TEACHER)
        grant_membership(tunji, self.grace, Role.TEACHER)
        self.name(self.head, here)

        response, _, _ = self.print_class(here, self.jss1a_id)
        self.assertEqual(response.status_code, 200)
        response, _, _ = self.print_class(here, self.grace_group_id, host=THEIR_HOST)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.pins_of(self.grace), [])

    def test_each_schools_page_lists_only_its_own(self):
        self.name(self.head, self.teacher)
        self.print_class(self.head, self.jss1a_id)

        body = self.overview(self.their_head, host=THEIR_HOST).json()
        self.assertEqual(body["officers"], [])
        self.assertEqual(body["prints"], [])
        self.assertEqual(body["officer_changes"], [])
        self.assertEqual([c["with_a_pin"] for c in body["classes"]], [0])


class TheAdministratorHasNoWayToBanksOrQuestionsTests(ExamSlipsSetUp):
    def test_the_administrator_never_reads_banks_even_as_an_exam_officer(self):
        with connected_to(self.stmarys):
            self.assertFalse(access.can_read_banks(self.admin.user, self.stmarys))
        self.name(self.head, self.admin)
        with connected_to(self.stmarys):
            self.assertTrue(access.is_exam_officer(self.admin.user, self.stmarys))
            self.assertFalse(access.can_read_banks(self.admin.user, self.stmarys))
            for who in (self.head, self.vp, self.teacher):
                with self.subTest(role=who.role):
                    self.assertTrue(access.can_read_banks(who.user, self.stmarys))

    def test_no_route_the_administrator_can_open_carries_a_bank_or_a_question(self):
        self.name(self.head, self.admin)
        self.print_class(self.head, self.jss1a_id)
        for path in (f"{BASE}slips/", f"{BASE}slips/classes/{self.jss1a_id}/"):
            with self.subTest(path=path):
                response = self.as_(self.admin).get(path, HTTP_HOST=HOST)
                self.assertEqual(response.status_code, 200)
                self.assertNotRegex(response.content.decode().lower(), r"question|bank|correct|answer")
        for path in (f"{BASE}banks/", f"{BASE}questions/", f"{BASE}tests/"):
            with self.subTest(path=path):
                self.assertEqual(self.as_(self.admin).get(path, HTTP_HOST=HOST).status_code, 404)

    def test_no_question_is_stored_or_seeded_by_cbt(self):
        """Step 2 has no question tables, and its migrations write no rows."""
        from django.apps import apps

        self.assertEqual(
            sorted(m.__name__ for m in apps.get_app_config("cbt").get_models()),
            ["ExamOfficerGrant", "ExamPin", "PinSlipPrint"],
        )
        from pathlib import Path

        for migration in (Path(__file__).resolve().parent.parent / "migrations").glob("0*.py"):
            with self.subTest(migration=migration.name):
                text = migration.read_text()
                self.assertNotRegex(text, r"(?i)\bINSERT\s+INTO|RunPython|bulk_create")
