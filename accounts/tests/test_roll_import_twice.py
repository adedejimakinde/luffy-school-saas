"""A roll file sent twice never doubles the roll. Audit finding G-15.

`accounts.bulk` matches each row to a child already on the roll before it
admits anybody: by admission number, else username, else name (`_match()` has
the rules). A matched row fills only what the roll has nothing for and is
`updated`, or has nothing to fill and is `skipped`; an unmatched row is `new`;
a row that could be two children is refused with a sentence. The preview says
which, writing nothing.

Two schools throughout: `Membership` is shared, so a name or a number at Grace
must never match a row at St Mary's.
"""

import threading
import time

from django.db import connection, connections, transaction
from django.test import TransactionTestCase

from academics import services as academics
from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts import bulk
from accounts.models import Guardianship, Membership, MembershipStatus, Role, User
from accounts.services import enroll_student, grant_membership, release_student, set_admission_number
from accounts.tests.test_bulk_enrolment import IMPORT, csv_of
from accounts.tests.test_enrolment_api import EnrolmentSetUp
from accounts.tests.test_roll_import import CHECK, RollImportSetUp, workbook
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST
from schools.models import School
from schools.tests.tenants import connected_to


class TwiceSetUp(EnrolmentSetUp):
    def upload(self, text, user=None, host=HOST):
        self.client.force_login((user or self.admin).user)
        response = self.client.post(IMPORT, data={"csv": text}, content_type="application/json", HTTP_HOST=host)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def roll(self, school=None):
        return Membership.objects.filter(school=school or self.stmarys, role=Role.STUDENT).count()

    def placed_in(self, membership):
        with connected_to(self.stmarys):
            row = ClassPlacement.objects.filter(term_id=self.term_id, student_membership_id=membership.pk).first()
            return row.class_group.name if row else None


class TheSameFileTwiceTests(TwiceSetUp):
    def test_without_admission_numbers_the_second_time_admits_nobody(self):
        """The finding's reproduction: names and classes only, sent twice.

        CONTROL G15-1: `_match()` without its name rule (rule 3) makes this red:
        the second upload admits two more children."""
        text = csv_of("Chike Obi,JSS 1A,,,,", "Ngozi Abah,JSS 1B,,,,")
        first = self.upload(text)
        before = self.roll()

        second = self.upload(text)

        self.assertEqual((first["admitted"], first["skipped"]), (2, 0))
        self.assertEqual((second["admitted"], second["updated"], second["skipped"]), (0, 0, 2))
        self.assertEqual(self.roll(), before)
        self.assertEqual(second["generated"], {})

    def test_with_admission_numbers_the_second_time_admits_nobody(self):
        """CONTROL G15-2: `_match()` without its number rule (rule 1) makes this
        red: every row is refused as "already an admission number"."""
        text = csv_of("Chike Obi,JSS 1A,,0100,,", "Ngozi Abah,JSS 1B,,0101,,")
        self.upload(text)
        before = self.roll()

        second = self.upload(text)

        self.assertEqual(second["problems"], [])
        self.assertEqual((second["admitted"], second["skipped"]), (0, 2))
        self.assertEqual(self.roll(), before)

    def test_with_usernames_the_second_time_admits_nobody(self):
        """CONTROL G15-3: `_match()` without its username rule (rule 2) makes
        this red: every row is refused as "already in use"."""
        text = csv_of("Chike Obi,JSS 1A,STM/100,,,", "Ngozi Abah,JSS 1B,STM/101,,,")
        self.upload(text)

        second = self.upload(text)

        self.assertEqual(second["problems"], [])
        self.assertEqual(second["skipped"], 2)

    def test_numbers_added_to_a_file_already_sent_fill_them_in(self):
        """First without numbers, then the office's corrected copy with them: the
        same two children, now numbered. Not two more."""
        self.upload(csv_of("Chike Obi,JSS 1A,,,,", "Ngozi Abah,JSS 1B,,,,"))
        before = self.roll()

        second = self.upload(csv_of("Chike Obi,JSS 1A,,0100,,", "Ngozi Abah,JSS 1B,,0101,,"))

        self.assertEqual((second["admitted"], second["updated"]), (0, 2))
        self.assertEqual(self.roll(), before)
        self.assertEqual(Membership.objects.get(school=self.stmarys, user__full_name="Chike Obi").reference, "0100")

    def test_a_name_matches_without_case_or_extra_spaces(self):
        self.upload(csv_of("Chike Obi,JSS 1A,,,,"))
        second = self.upload(csv_of("  chike   OBI ,JSS 1A,,,,"))
        self.assertEqual(second["skipped"], 1)

    def test_a_guardian_added_the_second_time_is_linked_once(self):
        self.upload(csv_of("Chike Obi,JSS 1A,,,,"))

        second = self.upload(csv_of("Chike Obi,JSS 1A,,,Mrs Obi,08031234567"))
        third = self.upload(csv_of("Chike Obi,JSS 1A,,,Mrs Obi,0803 123 4567"))

        chike = Membership.objects.get(school=self.stmarys, user__full_name="Chike Obi")
        self.assertEqual((second["updated"], third["skipped"]), (1, 1))
        self.assertEqual(Guardianship.objects.filter(student=chike).count(), 1)


class TheImportNeverChangesWhatTheRollSaysTests(TwiceSetUp):
    def test_a_child_already_in_a_class_is_not_moved_by_the_file(self):
        """Ada is in JSS 1A; the file says JSS 1B. Kept, and said. The import
        adds; moving is the roll's act."""
        ada = self.children["ada"]
        set_admission_number(ada, "A1")

        body = self.upload(csv_of("Ada Obi,JSS 1B,,A1,,"))

        self.assertEqual((body["skipped"], body["problems"]), (1, []))
        self.assertEqual(self.placed_in(ada), "JSS 1A")

    def test_a_child_with_no_class_this_term_is_placed(self):
        kola = enroll_student(User.objects.create_user("kola", PASSWORD, full_name="Kola Ade"), self.stmarys)

        body = self.upload(csv_of("Kola Ade,JSS 1B,,,,"))

        self.assertEqual((body["admitted"], body["updated"]), (0, 1))
        self.assertEqual(self.placed_in(kola), "JSS 1B")

    def test_a_different_number_on_the_roll_is_kept(self):
        """Ada holds A1; a row naming her with no number on the roll yet... is her,
        and a row with a different number is a different child."""
        set_admission_number(self.children["ada"], "A1")

        body = self.upload(csv_of("Ada Obi,JSS 1A,,A2,,"))

        self.assertEqual(body["admitted"], 1, "a row with a number of its own is a new child")


class ARowThatCouldBeTwoChildrenIsRefusedTests(TwiceSetUp):
    def test_the_same_name_in_another_class_is_refused_with_what_to_add(self):
        """Ada Obi is in JSS 1A. A row "Ada Obi, JSS 1B" with no number could be
        her or another child, so the file is refused, and says what to add."""
        before = self.roll()

        body = self.upload(csv_of("Ada Obi,JSS 1B,,,,"))

        self.assertEqual(body["admitted"], 0)
        self.assertIn("already on the roll, in JSS 1A", body["problems"][0]["detail"])
        self.assertIn("admission number", body["problems"][0]["detail"])
        self.assertEqual(self.roll(), before)

    def test_a_name_two_children_share_is_refused(self):
        enroll_student(User.objects.create_user("ada2", PASSWORD, full_name="Ada Obi"), self.stmarys)

        body = self.upload(csv_of("Ada Obi,JSS 1A,,,,"))

        self.assertIn("2 children called Ada Obi", body["problems"][0]["detail"])

    def test_one_new_child_twice_in_one_file_is_refused(self):
        body = self.upload(csv_of("Chike Obi,JSS 1A,,,,", "chike obi,JSS 1A,,,,"))

        self.assertEqual([p["line"] for p in body["problems"]], [3])
        self.assertIn("twice in this file", body["problems"][0]["detail"])

    def test_two_rows_for_one_child_already_on_the_roll_are_refused(self):
        set_admission_number(self.children["ada"], "A1")
        body = self.upload(csv_of("Ada Obi,JSS 1A,,A1,,", "Ada Obi,JSS 1A,,,,"))
        self.assertEqual([p["line"] for p in body["problems"]], [3])

    def test_a_leavers_number_is_refused(self):
        ada = self.children["ada"]
        set_admission_number(ada, "A1")
        release_student(ada)

        body = self.upload(csv_of("Ada Obi,JSS 1A,,A1,,"))

        self.assertIn("who has left this school", body["problems"][0]["detail"])

    def test_a_number_held_by_a_child_of_another_name_is_refused(self):
        set_admission_number(self.children["ada"], "A1")
        body = self.upload(csv_of("Chike Obi,JSS 1A,,A1,,"))
        self.assertIn("Ada Obi's, and this row names Chike Obi", body["problems"][0]["detail"])


class EachSchoolMatchesItsOwnRollTests(TwiceSetUp):
    def test_a_child_of_the_same_name_at_the_other_school_is_not_matched(self):
        """Grace's child is Chidi Eze. A St Mary's row "Chidi Eze" is a new
        child here, admitted; Grace's roll and Chidi are untouched.

        CONTROL G15-4: `_Roll` reading students without `school=` makes this
        red: the row matches Grace's Chidi and is skipped."""
        theirs = self.roll(self.grace)

        body = self.upload(csv_of("Chidi Eze,JSS 1A,,,,"))

        self.assertEqual(body["admitted"], 1)
        self.assertEqual(self.roll(self.grace), theirs)

    def test_the_other_schools_number_is_not_a_match_here(self):
        set_admission_number(self.grace_child, "G1")
        body = self.upload(csv_of("Chidi Eze,JSS 1A,,G1,,"))
        self.assertEqual(body["admitted"], 1)


class ThePreviewSaysWhatWillHappenTests(RollImportSetUp):
    def test_each_row_says_new_updated_or_skipped_and_nothing_is_written(self):
        set_admission_number(self.children["ada"], "A1")
        kola = enroll_student(User.objects.create_user("kola", PASSWORD, full_name="Kola Ade"), self.stmarys)
        before = self.counts()

        body = self.post(CHECK, self.admin, workbook(
            ["Ada Obi", "JSS 1A", "A1"],
            ["Kola Ade", "JSS 1B", "K1"],
            ["Chike Obi", "JSS 1A", ""],
        )).json()

        self.assertEqual(self.counts(), before)
        self.assertTrue(body["admissible"])
        self.assertEqual((body["new"], body["updated"], body["skipped"]), (1, 1, 1))
        rows = {r["full_name"]: r for r in body["rows"]}
        self.assertEqual(rows["Ada Obi"]["outcome"], "skipped")
        self.assertEqual(rows["Ada Obi"]["matched"], "Ada Obi")
        self.assertEqual(rows["Kola Ade"]["outcome"], "updated")
        self.assertEqual(rows["Kola Ade"]["fills"], ["admission number K1", "class JSS 1B this term"])
        self.assertEqual(rows["Chike Obi"]["outcome"], "new")
        self.assertIsNotNone(kola)

    def test_a_kept_difference_is_shown_as_a_note(self):
        set_admission_number(self.children["ada"], "A1")
        body = self.post(CHECK, self.admin, workbook(["Ada Obi", "JSS 1B", "A1"])).json()
        self.assertIn("Kept in JSS 1A; move them on the roll.", body["rows"][0]["notes"])


# -- a double press, on two connections ---------------------------------------

SESSION = "2025/2026"


class ADoublePressTests(TransactionTestCase):
    """The same file pressed twice at once: two connections, one school.

    **The interleaving is arranged, not hoped for**, as `test_membership_concurrency`
    arranges it: the first import runs inside a transaction held open, and the
    second is not let go until `pg_stat_activity` shows its backend waiting on a
    lock. Then the first commits. A run in which the second never waited fails
    as "not arranged" rather than passing.

    CONTROL G15-5: `admit()` without `_lock_the_roll()` makes this red: the
    second import does not wait on the roll; it meets the first's uncommitted
    handles at the username index, and fails with an IntegrityError once the
    first commits, instead of reporting every row skipped.
    """

    def setUp(self):
        self.school = self._school("St Mary's", "st-marys", "st_marys")
        self.other = self._school("Grace Academy", "grace", "grace")
        self.admin = User.objects.create_user("amaka", PASSWORD, full_name="Amaka Obi")
        grant_membership(self.admin, self.school, Role.ADMIN)
        for school in (self.school, self.other):
            with connected_to(school):
                Term.objects.create(
                    session=SESSION, name=TermName.FIRST, is_current=True,
                    starts_on="2025-09-15", ends_on="2025-12-12",
                )
                ClassGroup.objects.create(name="JSS 1A", level=1)

    def _school(self, name, slug, schema):
        school = School(name=name, slug=slug, schema_name=schema)
        school.save()
        return school

    def tearDown(self):
        connection.set_schema_to_public()
        with connection.cursor() as cursor:
            for school in (self.school, self.other):
                cursor.execute(f'DROP SCHEMA IF EXISTS "{school.schema_name}" CASCADE')
        super().tearDown()

    def test_the_second_press_waits_and_admits_nobody(self):
        text = csv_of("Chike Obi,JSS 1A,,,,", "Ngozi Abah,JSS 1A,,,,")
        first_in = threading.Event()
        let_first_commit = threading.Event()
        results, failures, pids = {}, [], {}

        def first():
            try:
                with connected_to(self.school), transaction.atomic():
                    term = Term.objects.get(is_current=True)
                    results["first"] = bulk.admit(self.admin, self.school, term, text)
                    first_in.set()
                    let_first_commit.wait(20)
            except Exception as exc:  # noqa: BLE001 — reported, never swallowed
                failures.append(("first", exc))
                first_in.set()
            finally:
                connections.close_all()

        def second():
            try:
                with connected_to(self.school):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        pids["second"] = cursor.fetchone()[0]
                    term = Term.objects.get(is_current=True)
                    results["second"] = bulk.admit(self.admin, self.school, term, text)
            except Exception as exc:  # noqa: BLE001
                failures.append(("second", exc))
            finally:
                connections.close_all()

        a = threading.Thread(target=first)
        a.start()
        self.assertTrue(first_in.wait(30), "the first import never finished writing")
        b = threading.Thread(target=second)
        b.start()

        waited = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not waited:
            if "second" in pids:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pids["second"]]
                    )
                    row = cursor.fetchone()
                    waited = bool(row and row[0] == "Lock")
            if not waited:
                time.sleep(0.05)
        let_first_commit.set()
        a.join(30)
        b.join(30)

        self.assertTrue(waited, "not arranged: the second import never waited on the first")
        self.assertEqual(failures, [])
        self.assertEqual(results["first"].count(bulk.NEW), 2)
        self.assertEqual(
            (results["second"].count(bulk.NEW), results["second"].count(bulk.SKIPPED)), (0, 2)
        )
        self.assertEqual(Membership.objects.filter(school=self.school, role=Role.STUDENT).count(), 2)
        self.assertEqual(Membership.objects.filter(school=self.other, role=Role.STUDENT).count(), 0)
