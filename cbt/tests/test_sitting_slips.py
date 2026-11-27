"""Exam PIN slips from the sitting page: `docs/cbt.md`, "Exam PINs and slips".

The sitting page prints a whole class's slips and reissues one student's. Both go through
the routes the exam slips page uses, so what is proved here is what that page cannot:

- the sitting log says who may print (`may_print`) and the class's printable and held
  counts only to them, and the print routes refuse everybody else on the server;
- reissuing one student's slip gives them a **new** PIN and the old one then fails, and
  nobody else's PIN changes;
- printing a class that already holds live PINs is refused (409) until the caller says yes;
- one school can never print, or read the counts of, another school's slips.
"""

from unittest import mock

from django.db import connection

from cbt import officers, pins
from cbt import pdf as cbt_pdf
from cbt.models import ExamPin, PinSlipPrint
from cbt.tests import test_sitting
from results.tests.fixtures import HOST, THEIR_HOST
from schools.tests.tenants import connected_to


class SlipsFromTheSittingSetUp(test_sitting.SittingSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            # Kemi, a teacher, is named an exam officer; the vice principal is not.
            officers.name_as(self.head.user, self.stmarys, self.teacher.pk, "Runs the lab")

    def log(self, who, host=HOST, test_id=None):
        return self.get(who, f"tests/{test_id or self.test_id}/sitting/", host=host)

    def printing(self, who, group_id, student=None, host=HOST, replace=None):
        """The response and the slips the PDF was drawn from (the raw PINs)."""
        captured = {}
        real = cbt_pdf.render_slips

        def keep(slips, address):
            captured["slips"] = slips
            return real(slips, address)

        path = f"{test_sitting.STAFF}slips/classes/{group_id}/"
        path += f"students/{student}/print/" if student is not None else "print/"
        body = {} if replace is None else {"replace": replace}
        with mock.patch("cbt.api.pdf.render_slips", side_effect=keep):
            response = self.client_for(who).post(path, data=body, content_type="application/json", HTTP_HOST=host)
        connection.set_schema_to_public()
        return response, captured.get("slips")

    def client_for(self, who):
        self.client.force_login(who.user)
        return self.client

    def digests(self, school):
        with connected_to(school):
            return sorted(ExamPin.objects.filter(cancelled_at__isnull=True).values_list("student_membership_id", "digest"))

    def counts(self, school):
        with connected_to(school):
            return ExamPin.objects.count(), PinSlipPrint.objects.count()


class OnlyWhoCanPrintSlipsAreOfferedTheButtonsTests(SlipsFromTheSittingSetUp):
    def test_the_principal_the_administrator_and_a_named_exam_officer_may_print(self):
        for who in (self.head, self.admin, self.teacher):
            with self.subTest(who=who.user.username):
                body = self.log(who).json()
                self.assertIs(body["may_print"], True)
                classes = {c["name"]: c for c in body["classes"]}
                self.assertEqual(classes["JSS 1A"]["printable"], 4)
                self.assertEqual(classes["JSS 1A"]["with_a_pin"], 4)
                self.assertTrue(all(r["class_id"] for r in body["rows"]))

    def test_the_vice_principal_reads_the_log_and_is_not_offered_slips(self):
        body = self.log(self.vp).json()
        self.assertIs(body["may_print"], False)
        for c in body["classes"]:
            self.assertEqual((c["printable"], c["with_a_pin"]), (0, 0))

    def test_an_exam_officer_who_is_ended_stops_being_offered_them(self):
        with connected_to(self.stmarys):
            officers.end_as(self.head.user, self.stmarys, self.teacher.pk, "")
        self.assertIs(self.log(self.teacher).json()["may_print"], False)

    def test_the_routes_refuse_anybody_else_whatever_the_page_drew(self):
        before = self.counts(self.stmarys)
        for who in (self.vp, self.bursar_or_other()):
            with self.subTest(who=who.user.username):
                response, slips = self.printing(who, self.jss1a_id, replace=True)
                self.assertEqual(response.status_code, 403)
                response, slips = self.printing(who, self.jss1a_id, student=self.children["ada"].pk)
                self.assertEqual(response.status_code, 403)
                self.assertIsNone(slips)
        self.assertEqual(self.counts(self.stmarys), before)

    def bursar_or_other(self):
        from accounts.models import Role, User
        from accounts.services import grant_membership

        return grant_membership(User.objects.create_user("bola", "x" * 12, full_name="Bola Bursar"), self.stmarys, Role.BURSAR)


class ReissuingOneSlipGivesANewPinTests(SlipsFromTheSittingSetUp):
    def check(self, number, pin):
        with connected_to(self.stmarys):
            from cbt.models import Test

            term = Test.objects.get(pk=self.test_id).term
            return pins.check(self.stmarys, term, number, pin)

    def test_the_old_pin_is_refused_after_a_reissue_and_the_new_one_opens(self):
        old = self.pins["SM/001"]
        self.assertIsNotNone(self.check("SM/001", old))

        response, slips = self.printing(self.head, self.jss1a_id, student=self.children["ada"].pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([s.admission_number for s in slips.slips], ["SM/001"])
        new = slips.slips[0].pin
        self.assertNotEqual(new, old)
        self.assertIsNone(self.check("SM/001", old))
        self.assertEqual(self.check("SM/001", new).pk, self.children["ada"].pk)

    def test_nobody_elses_pin_changes(self):
        before = dict(self.digests(self.stmarys))
        self.printing(self.head, self.jss1a_id, student=self.children["ada"].pk)
        after = dict(self.digests(self.stmarys))

        self.assertEqual(len(after), len(before))
        changed = {sid for sid in before if before[sid] != after[sid]}
        self.assertEqual(changed, {self.children["ada"].pk})
        self.assertIsNotNone(self.check("SM/002", self.pins["SM/002"]))

    def test_an_exam_officer_can_reissue_and_it_is_logged_with_their_name(self):
        response, _ = self.printing(self.teacher, self.jss1a_id, student=self.children["emeka"].pk)
        self.assertEqual(response.status_code, 200)
        with connected_to(self.stmarys):
            row = PinSlipPrint.objects.order_by("-id").first()
            self.assertEqual((row.kind, row.student_name, row.count, row.cancelled_count), ("student", "Emeka Nwosu", 1, 1))
            self.assertEqual(row.printed_by_id, self.teacher.user.pk)

    def test_a_student_not_in_that_class_is_refused_and_nothing_changes(self):
        before = self.counts(self.stmarys)
        response, slips = self.printing(self.head, self.jss1a_id, student=self.bimpe.pk)
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(slips)
        self.assertEqual(self.counts(self.stmarys), before)


class PrintingTheWholeClassStillAsksTests(SlipsFromTheSittingSetUp):
    def test_a_class_that_holds_pins_is_refused_without_a_yes_and_nothing_changes(self):
        before, kept = self.counts(self.stmarys), self.digests(self.stmarys)
        response, slips = self.printing(self.head, self.jss1a_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Slips already handed out will stop working", response.json()["detail"])
        self.assertIsNone(slips)
        self.assertEqual(self.counts(self.stmarys), before)
        self.assertEqual(self.digests(self.stmarys), kept)

    def test_the_log_says_so_before_the_screen_asks(self):
        classes = {c["name"]: c for c in self.log(self.head).json()["classes"]}
        self.assertEqual(classes["JSS 1A"]["with_a_pin"], 4)

    def test_with_a_yes_everyone_gets_a_new_pin_and_the_old_ones_stop(self):
        response, slips = self.printing(self.head, self.jss1a_id, replace=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(slips.slips), 4)
        for s in slips.slips:
            self.assertNotEqual(s.pin, self.pins[s.admission_number])


class OneSchoolNeverPrintsAnothersSlipsTests(SlipsFromTheSittingSetUp):
    def test_a_principal_at_one_school_cannot_print_or_reissue_at_the_other(self):
        before = self.counts(self.grace)
        response, slips = self.printing(self.head, self.grace_group_id, host=THEIR_HOST, replace=True)
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(slips)
        response, slips = self.printing(self.head, self.grace_group_id, student=self.grace_child.pk, host=THEIR_HOST)
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(slips)
        self.assertEqual(self.counts(self.grace), before)

    def test_the_same_class_id_at_each_school_prints_only_that_schools_students(self):
        self.assertEqual(self.jss1a_id, self.grace_group_id)
        mine = self.counts(self.stmarys)
        response, slips = self.printing(self.their_head, self.grace_group_id, host=THEIR_HOST, replace=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s.student_name for s in slips.slips], ["Chidi Eze"])
        self.assertEqual(self.counts(self.stmarys), mine)

    def test_a_student_of_the_other_school_cannot_be_reissued_by_id_here(self):
        before = self.counts(self.stmarys), self.counts(self.grace)
        response, slips = self.printing(self.head, self.jss1a_id, student=self.grace_child.pk)
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(slips)
        self.assertEqual((self.counts(self.stmarys), self.counts(self.grace)), before)

    def test_the_sitting_log_of_one_school_is_never_read_at_the_other(self):
        self.assertEqual(self.log(self.head, host=THEIR_HOST).status_code, 403)
        # Grace's own principal asking for the same test id gets no line of St Mary's.
        theirs = self.log(self.their_head, host=THEIR_HOST)
        self.assertIn(theirs.status_code, (403, 404))
        self.assertNotIn("Ada", theirs.content.decode())
