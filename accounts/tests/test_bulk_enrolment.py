"""Admitting a class from a spreadsheet: all of it, or none of it.

Two schools in every test. `User` and `Membership` are **shared** tables, so
what keeps one school's import out of another's roll is a real authority check
rather than the tenant schema — and a handle or a contact already on the
platform belongs to somebody who may be at the other school.

The rule this module exists for is the all-or-nothing one, and the test that
holds it counts rows **before and after** a bad file rather than trusting the
report.
"""

from academics.models import ClassPlacement, Term
from accounts.models import Guardianship, Membership, Role, User
from accounts.tests.test_enrolment_api import EnrolmentSetUp
from results.tests.fixtures import HOST, THEIR_HOST
from schools.tests.tenants import connected_to

IMPORT = "/api/enrolment/roll/import/"

HEADER = "full_name,class_group,username,reference,guardian_name,guardian_contact"


def csv_of(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


class BulkImportTests(EnrolmentSetUp):
    def upload(self, user, text, host=HOST):
        self.client.force_login(user.user)
        return self.client.post(
            IMPORT, data={"csv": text}, content_type="application/json", HTTP_HOST=host
        )

    def counts(self):
        return (
            User.objects.count(),
            Membership.objects.filter(school=self.stmarys, role=Role.STUDENT).count(),
        )

    # -- the control, and it runs first --------------------------------------

    def test_a_good_file_admits_everybody_and_places_them(self):
        """Every refusal below would pass against an import that wrote nothing
        for anybody."""
        body = self.upload(
            self.admin,
            csv_of(
                "Chike Obi,JSS 1A,STM/2026/0100,0100,,",
                "Ngozi Abah,JSS 1B,STM/2026/0101,0101,,",
            ),
        ).json()

        self.assertEqual(body["problems"], [])
        self.assertEqual(body["admitted"], 2)
        chike = Membership.objects.get(user__username="STM/2026/0100")
        self.assertEqual(chike.school, self.stmarys)
        with connected_to(self.stmarys):
            self.assertEqual(
                ClassPlacement.objects.filter(
                    student_membership_id=chike.pk, class_group_id=self.jss1a_id
                ).count(),
                1,
            )

    # -- all or nothing --------------------------------------------------------

    def test_a_file_with_bad_rows_writes_nothing_at_all(self):
        """**The rule this module exists for.** Counted before and after rather
        than trusted from the report: an import that wrote the good rows and
        reported the bad ones would produce the same report."""
        before = self.counts()

        body = self.upload(
            self.admin,
            csv_of(
                "Chike Obi,JSS 1A,,,,",
                ",JSS 1A,,,,",
                "Ada Two,Nowhere,,,,",
            ),
        ).json()

        self.assertEqual(body["admitted"], 0)
        self.assertEqual(self.counts(), before, "a half-applied file was written")

    def test_every_bad_row_is_reported_with_its_line_number(self):
        """An office fixing a file one error per upload is the failure this
        design prevents. The header is line 1, so the first child is line 2."""
        body = self.upload(
            self.admin,
            csv_of(
                "Chike Obi,JSS 1A,,,,",
                ",JSS 1A,,,,",
                "Ada Two,Nowhere,,,,",
                "Bad Guardian,JSS 1A,,,Mama,not-a-contact",
            ),
        ).json()

        lines = sorted(p["line"] for p in body["problems"])
        self.assertEqual(lines, [3, 4, 5], "not every bad row was reported")
        columns = {p["line"]: p["column"] for p in body["problems"]}
        self.assertEqual(columns[3], "full_name")
        self.assertEqual(columns[4], "class_group")
        self.assertEqual(columns[5], "guardian_contact")

    # -- handles ---------------------------------------------------------------

    def test_a_blank_handle_is_generated_from_the_reference_and_reported(self):
        """A child cannot be handed a login nobody wrote down."""
        body = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,0100,,")
        ).json()

        self.assertEqual(body["generated"], {"2": "ST-MARYS/0100"})
        self.assertTrue(User.objects.filter(username="ST-MARYS/0100").exists())

    def test_a_blank_handle_and_no_reference_falls_back_to_a_sequence(self):
        body = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,,,", "Ngozi Abah,JSS 1B,,,,")
        ).json()

        self.assertEqual(
            sorted(body["generated"].values()), ["ST-MARYS/1", "ST-MARYS/2"]
        )

    def test_a_handle_already_on_the_platform_is_refused_without_naming_where(self):
        """It is unique across the platform, so naming the holder would tell
        this office which children exist at the other school."""
        User.objects.create_user("GRC/2026/0001", None, full_name="Their Child")

        body = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,GRC/2026/0001,,,")
        ).json()

        detail = body["problems"][0]["detail"]
        self.assertIn("already in use", detail)
        for leaked in ("Grace", "St Mary", "school"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, detail)

    def test_a_handle_duplicated_inside_the_file_is_caught(self):
        """Neither exists yet, so only the file itself can catch this."""
        body = self.upload(
            self.admin,
            csv_of("Chike Obi,JSS 1A,STM/1,,,", "Ngozi Abah,JSS 1B,STM/1,,,"),
        ).json()

        self.assertEqual([p["line"] for p in body["problems"]], [3])
        self.assertIn("twice in this file", body["problems"][0]["detail"])

    # -- references ------------------------------------------------------------

    def test_a_reference_already_used_at_this_school_is_refused(self):
        self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,0100,,"))

        body = self.upload(self.admin, csv_of("Ngozi Abah,JSS 1B,,0100,,")).json()

        self.assertEqual(body["admitted"], 0)
        self.assertIn("admission number", body["problems"][0]["detail"])

    def test_a_reference_duplicated_inside_the_file_is_caught(self):
        body = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,7,,", "Ngozi Abah,JSS 1B,,7,,")
        ).json()

        self.assertEqual([p["line"] for p in body["problems"]], [3])

    # -- the school scope ------------------------------------------------------

    def test_a_class_name_from_the_other_school_does_not_match_here(self):
        """Grace has a JSS 1A of its own; St Mary's has no 'JSS 9Z'. Matching
        by name has to be scoped to this school's groups or a file would enrol
        children into another school's classes by coincidence of naming."""
        with connected_to(self.grace):
            from academics.models import ClassGroup

            ClassGroup.objects.create(name="JSS 9Z", level=9)

        body = self.upload(self.admin, csv_of("Chike Obi,JSS 9Z,,,,")).json()

        self.assertEqual(body["admitted"], 0)
        self.assertIn("not a class this school teaches", body["problems"][0]["detail"])

    def test_an_inactive_group_is_not_a_class_to_join(self):
        with connected_to(self.stmarys):
            from academics.models import ClassGroup

            ClassGroup.objects.create(name="JSS 4A", level=4, is_active=False)

        body = self.upload(self.admin, csv_of("Chike Obi,JSS 4A,,,,")).json()

        self.assertEqual(body["admitted"], 0)

    def test_a_teacher_cannot_import(self):
        response = self.upload(self.teacher, csv_of("Chike Obi,JSS 1A,,,,"))

        self.assertEqual(response.status_code, 403)

    def test_an_administrator_at_one_school_cannot_import_at_the_other(self):
        response = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,,,"), host=THEIR_HOST
        )

        self.assertEqual(response.status_code, 403)

    # -- guardians -------------------------------------------------------------

    def test_siblings_sharing_a_contact_are_one_guardian_linked_to_each(self):
        """**Two rows, one parent.** The ordinary case in a school, and not a
        duplicate to refuse."""
        body = self.upload(
            self.admin,
            csv_of(
                "Chike Obi,JSS 1A,,,Mama Obi,08031234567",
                "Ada Obi Two,JSS 1B,,,Mama Obi,08031234567",
            ),
        ).json()

        self.assertEqual(body["admitted"], 2)
        guardians = User.objects.filter(phone="+2348031234567")
        self.assertEqual(guardians.count(), 1, "one parent became two accounts")
        self.assertEqual(Guardianship.objects.filter(guardian=guardians.first()).count(), 2)

    def test_the_same_parent_written_three_ways_is_still_one_guardian(self):
        """`0803...`, `803...` and `+234803...` are one number. Normalising
        happens **before** the matching, which is the whole reason it happens
        at all."""
        body = self.upload(
            self.admin,
            csv_of(
                "One Child,JSS 1A,,,Mama Obi,08031234567",
                "Two Child,JSS 1B,,,Mama Obi,8031234567",
                "Three Child,JSS 1A,,,Mama Obi,+2348031234567",
            ),
        ).json()

        self.assertEqual(body["admitted"], 3)
        self.assertEqual(User.objects.filter(phone="+2348031234567").count(), 1)
        self.assertEqual(
            Guardianship.objects.filter(guardian__phone="+2348031234567").count(), 3
        )

    def test_a_malformed_number_is_rejected_with_its_row(self):
        body = self.upload(
            self.admin,
            csv_of(
                "Chike Obi,JSS 1A,,,Mama,0803",
                "Ngozi Abah,JSS 1B,,,Mama,not a contact at all",
            ),
        ).json()

        self.assertEqual(sorted(p["line"] for p in body["problems"]), [2, 3])
        self.assertEqual(body["admitted"], 0)

    def test_a_guardian_name_without_a_contact_is_refused(self):
        body = self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,,Mama,")).json()

        self.assertEqual(body["problems"][0]["column"], "guardian_contact")

    def test_a_contact_without_a_name_is_refused(self):
        body = self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,,,08031234567")).json()

        self.assertEqual(body["problems"][0]["column"], "guardian_name")

    def test_the_report_says_the_guardian_links_are_not_live_yet(self):
        """D9: `link_guardian()` grants an INVITED membership until a contact
        channel is verified, so an import that said nothing would leave the
        office believing it had finished."""
        body = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,,Mama Obi,08031234567")
        ).json()

        self.assertEqual(body["guardians_pending"], 1)
        link = Guardianship.objects.get(guardian__phone="+2348031234567")
        parent = Membership.objects.get(
            user=link.guardian, school=self.stmarys, role=Role.PARENT
        )
        self.assertEqual(parent.status, "invited", "the link went live without a channel")

    # -- files that are not files ----------------------------------------------

    def test_a_file_missing_a_required_column_is_refused_as_a_file(self):
        response = self.upload(self.admin, "full_name\nChike Obi\n")

        self.assertEqual(response.status_code, 422)
        self.assertIn("class_group", response.json()["detail"])

    def test_the_header_may_be_in_any_order_and_any_case(self):
        """A positional format breaks silently the first time somebody reorders
        columns in a spreadsheet."""
        text = "Class_Group,FULL_NAME\nJSS 1A,Chike Obi\n"

        body = self.upload(self.admin, text).json()

        self.assertEqual(body["admitted"], 1)

    def test_no_current_term_refuses_the_whole_file(self):
        """Rather than admitting children unplaced: a bulk import that silently
        half-does its job is what the all-or-nothing rule exists to prevent."""
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=False)
        before = self.counts()

        response = self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,,,"))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.counts(), before)
