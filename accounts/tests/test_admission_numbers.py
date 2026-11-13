"""An admission number names one child per school. Audit finding G-14.

Compared without case and without surrounding spaces, ended children included,
blank never a number. Held by the database (`an_admission_number_names_one_child_per_school`)
and refused in a sentence on every door that writes one: admitting a child, the
edit, the roll import, and a transfer carrying a number in.

Two schools throughout: `Membership` is a shared table, so "per school" is a
`school_id` doing real work, and Grace may hold the very number St Mary's gives.
"""

from django.db import IntegrityError, connection, transaction

from accounts import admission_numbers
from accounts.models import Membership, Role, User
from accounts.services import (
    AdmissionNumberTaken,
    enroll_student,
    release_student,
    set_admission_number,
    transfer_student,
)
from accounts.tests.test_bulk_enrolment import IMPORT, csv_of
from accounts.tests.test_enrolment_api import ROLL, EnrolmentSetUp
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST


class AdmissionNumberSetUp(EnrolmentSetUp):
    def setUp(self):
        super().setUp()
        self.ada = self.children["ada"]
        set_admission_number(self.ada, "JSS/014")

    def edit(self, user, membership_id, reference, host=HOST):
        self.client.force_login(user.user)
        return self.client.put(
            f"{ROLL}{membership_id}/admission-number/",
            data={"reference": reference},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def upload(self, user, text, host=HOST):
        self.client.force_login(user.user)
        return self.client.post(IMPORT, data={"csv": text}, content_type="application/json", HTTP_HOST=host)


class TheDoorsRefuseInASentenceTests(AdmissionNumberSetUp):
    def test_admitting_a_second_child_with_the_same_number_is_refused(self):
        """The finding's reproduction: two POSTs, one number. Both answered 201.

        Two layers refuse it, and each has its own test: the service's check
        (`test_the_service_refuses_without_the_index`) and the index with its
        translation (`test_two_admissions_that_both_passed_the_check_meet_the_index`)."""
        response = self.admit(self.admin, username="STM/9", reference="JSS/014")

        self.assertEqual(response.status_code, 409)
        self.assertIn("already the admission number of Ada Obi", response.json()["detail"])
        self.assertFalse(User.objects.filter(username="STM/9").exists(), "the refused admission left a login behind")

    def test_the_service_refuses_without_the_index(self):
        """The check in `enroll_student()` on its own, the index dropped for the test.

        CONTROL G14-1: `enroll_student()` without `require_free()` makes this
        red: 201, a second child on JSS/014."""
        with connection.cursor() as cursor:
            cursor.execute(f'DROP INDEX IF EXISTS "{admission_numbers.CONSTRAINT}"')

        response = self.admit(self.admin, username="STM/9", reference="jss/014")

        self.assertEqual(response.status_code, 409)
        self.assertIn("already the admission number of Ada Obi", response.json()["detail"])

    def test_the_number_is_compared_without_case_or_spaces(self):
        """The doors match "jss/014" and "JSS/014" as one, so the roll must."""
        for typed in ("jss/014", " JSS/014 "):
            with self.subTest(typed=typed):
                response = self.admit(self.admin, username=f"STM/{len(typed)}", reference=typed)
                self.assertEqual(response.status_code, 409)

    def test_a_leavers_number_is_not_given_to_the_next_child(self):
        release_student(self.ada)

        response = self.admit(self.admin, username="STM/9", reference="JSS/014")

        self.assertEqual(response.status_code, 409)
        self.assertIn("who has left this school", response.json()["detail"])

    def test_editing_a_number_to_another_childs_is_refused(self):
        emeka = self.children["emeka"]

        response = self.edit(self.admin, emeka.pk, "jss/014")

        self.assertEqual(response.status_code, 409)
        self.assertIn("Ada Obi", response.json()["detail"])
        emeka.refresh_from_db()
        self.assertEqual(emeka.reference, "")

    def test_editing_a_number_saves_it_trimmed(self):
        response = self.edit(self.admin, self.children["emeka"].pk, "  JSS/015 ")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reference"], "JSS/015")

    def test_a_child_keeps_their_own_number_in_another_case(self):
        response = self.edit(self.admin, self.ada.pk, "jss/014")
        self.assertEqual(response.status_code, 200)

    def test_the_import_refuses_a_number_held_in_another_case(self):
        """It compared as typed before G-14, so "jss/014" passed beside "JSS/014".

        CONTROL G14-2: `bulk.check()` comparing `reference` as typed makes this
        red: the row is admitted."""
        body = self.upload(self.admin, csv_of("Ngozi Abah,JSS 1B,,jss/014,,")).json()

        self.assertEqual(body["admitted"], 0)
        self.assertEqual([p["column"] for p in body["problems"]], ["reference"])

    def test_the_import_refuses_a_number_twice_in_one_file_in_two_cases(self):
        body = self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,ab1,,", "Ngozi Abah,JSS 1B,,AB1,,")).json()

        self.assertEqual([p["line"] for p in body["problems"]], [3])
        self.assertIn("twice in this file", body["problems"][0]["detail"])

    def test_a_transfer_carrying_a_number_the_receiving_school_uses_is_refused(self):
        """`transfer_student()` carried the sending school's number across unchecked.
        Refused before anything is ended, so the child stays where they were.

        CONTROL G14-3: `transfer_student()` without its `require_free()` makes
        this red at the index instead: an IntegrityError, not the sentence."""
        chidi = self.grace_child
        set_admission_number(chidi, "JSS/014")

        with self.assertRaises(AdmissionNumberTaken):
            transfer_student(chidi, self.stmarys)

        chidi.refresh_from_db()
        self.assertTrue(chidi.is_live, "a refused transfer ended the enrolment it was moving")

    def test_only_an_administrator_edits_a_number(self):
        response = self.edit(self.head, self.children["emeka"].pk, "JSS/099")
        self.assertEqual(response.status_code, 403)


class PerSchoolTests(AdmissionNumberSetUp):
    def test_the_other_school_may_use_the_same_number(self):
        """A per-school rule: Grace's JSS/014 is no obstacle at St Mary's."""
        set_admission_number(self.grace_child, "JSS/014")
        self.assertEqual(self.grace_child.reference, "JSS/014")

    def test_the_edit_cannot_reach_the_other_schools_child(self):
        response = self.edit(self.admin, self.grace_child.pk, "X1")
        self.assertEqual(response.status_code, 404)
        self.grace_child.refresh_from_db()
        self.assertEqual(self.grace_child.reference, "")

    def test_the_refusal_names_nobody_at_the_other_school(self):
        """The sentence names the holder, so it must only ever find one here."""
        set_admission_number(self.grace_child, "GR/1")
        response = self.admit(self.admin, username="STM/9", reference="GR/1")
        self.assertEqual(response.status_code, 201)

    def test_staff_numbers_are_not_admission_numbers(self):
        """The index is on student rows: a staff number may be anything."""
        Membership.objects.filter(pk=self.teacher.pk).update(reference="JSS/014")
        self.assertEqual(self.admit(self.admin, username="STM/9", reference="X2").status_code, 201)

    def test_blank_is_no_number(self):
        for n in range(2):
            self.assertEqual(self.admit(self.admin, username=f"STM/B{n}", reference="").status_code, 201)


class TheDatabaseHoldsItTests(AdmissionNumberSetUp):
    def violate(self, **change):
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            Membership.objects.filter(pk=self.children["emeka"].pk).update(**change)
        return caught.exception

    def test_an_update_that_walks_past_the_service_is_refused_by_name(self):
        """Rule 5: assert on the constraint's name.

        CONTROL G14-4: the migration's `AddConstraint` removed (and the model's)
        makes this red: the update succeeds."""
        exc = self.violate(reference="jss/014")
        self.assertEqual(exc.__cause__.diag.constraint_name, admission_numbers.CONSTRAINT)

    def test_two_admissions_that_both_passed_the_check_meet_the_index(self):
        """The race the check cannot close: simulated by skipping the check,
        and the loser still gets the sentence and a usable connection.

        CONTROL G14-5: `grant_membership()` without `_raise_if_the_number_clashed()`
        makes this red: a raw IntegrityError."""
        from unittest import mock

        with mock.patch.object(admission_numbers, "require_free"):
            with self.assertRaises(AdmissionNumberTaken) as caught:
                enroll_student(
                    User.objects.create_user("late", PASSWORD, full_name="Late Comer"),
                    self.stmarys,
                    reference="JSS/014",
                )
        self.assertIn("Ada Obi", str(caught.exception))
        self.assertTrue(User.objects.filter(username="late").exists(), "the connection was left unusable")


class TheMigrationReportsExistingDuplicatesTests(AdmissionNumberSetUp):
    """The migration stops with every shared number listed, instead of Postgres
    naming the first pair or a silent rewrite."""

    def test_every_clash_is_listed_with_its_school_and_children(self):
        from importlib import import_module

        migration = import_module("accounts.migrations.0021_an_admission_number_names_one_child_per_school")
        emeka, bisi = self.children["emeka"], self.children["bisi"]
        with transaction.atomic():
            with connection.cursor() as cursor:
                # The index is how Django builds an expression constraint; it
                # is dropped inside this transaction and comes back on rollback.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(f'DROP INDEX "{admission_numbers.CONSTRAINT}"')
            Membership.objects.filter(pk=emeka.pk).update(reference="jss/014 ")
            Membership.objects.filter(pk=bisi.pk).update(reference="A1")
            Membership.objects.filter(pk=self.children["tunde"].pk).update(reference="a1")

            class Editor:
                connection = connection

            with self.assertRaises(RuntimeError) as caught:
                migration.stop_on_shared_numbers(None, Editor())
            transaction.set_rollback(True)

        report = str(caught.exception)
        for expected in ("St Mary's", "'jss/014'", "'a1'", "Ada Obi", "Emeka Nwosu", "Bisi Ade", "Tunde Cole",
                         f"membership {emeka.pk}", "admission_number_clashes"):
            with self.subTest(expected=expected):
                self.assertIn(expected, report)
        self.assertNotIn("Grace", report)

    def test_with_no_clash_it_passes(self):
        from importlib import import_module

        migration = import_module("accounts.migrations.0021_an_admission_number_names_one_child_per_school")

        class Editor:
            connection = connection

        migration.stop_on_shared_numbers(None, Editor())

    def test_the_command_lists_nothing_when_nothing_is_shared(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("admission_number_clashes", stdout=out)
        self.assertIn("No admission number is shared", out.getvalue())
