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
from accounts.models import GuardianAccount, Guardianship, Membership, Role, User
from accounts.services import link_guardian
from accounts.tests.test_enrolment_api import EnrolmentSetUp
from results.tests.fixtures import HOST, THEIR_HOST
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

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

    def test_a_handle_in_use_in_another_case_is_reported_on_its_row(self):
        """The platform compares handles case-insensitively (`User.save()` asks
        `matching_identifier()`), so this file has to as well.

        **Status first.** A check narrower than the platform's lets the row
        through, and `User.save()` then refuses it at write time as a
        whole-file 422 with no line number — nothing written, and nothing the
        office can find either.
        """
        User.objects.create_user("GRC/2026/0001", None, full_name="Their Child")

        response = self.upload(self.admin, csv_of("Chike Obi,JSS 1A,grc/2026/0001,,,"))

        self.assertEqual(response.status_code, 200, "a per-row report became a whole-file refusal")
        body = response.json()
        self.assertEqual([p["line"] for p in body["problems"]], [2])
        self.assertIn("already in use", body["problems"][0]["detail"])

    def test_a_generated_handle_steps_around_one_given_later_in_the_file(self):
        """Line 2's reference would make `ST-MARYS/0100`, and line 3 asks for
        exactly that handle by name. Generating in file order without knowing
        what the rest of the file claims hands line 2 the handle and refuses
        the whole file at line 3 — for a file with nothing wrong in it."""
        response = self.upload(
            self.admin,
            csv_of("Chike Obi,JSS 1A,,0100,,", "Ngozi Abah,JSS 1B,ST-MARYS/0100,,,"),
        )

        self.assertEqual(response.status_code, 200, "a good file was refused whole")
        body = response.json()
        self.assertEqual(body["admitted"], 2)
        self.assertEqual(
            Membership.objects.get(user__username="ST-MARYS/0100").user.full_name,
            "Ngozi Abah",
        )
        self.assertNotEqual(body["generated"]["2"], "ST-MARYS/0100")

    def test_a_generated_handle_steps_around_one_in_use_in_another_case(self):
        """A school that once typed its handles in lower case must not be
        dead-ended: a generated handle is one the office cannot correct, so a
        collision on it has to be avoided here rather than refused at save."""
        User.objects.create_user("st-marys/1", None, full_name="Typed By Hand")

        response = self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,,,"))

        self.assertEqual(response.status_code, 200, "a generated handle collided at save")
        self.assertEqual(response.json()["generated"], {"2": "ST-MARYS/2"})

    def test_a_handle_duplicated_inside_the_file_is_caught(self):
        """Neither exists yet, so only the file itself can catch this.

        **Status first**, and that is the assertion doing the work. Without the
        in-file check the duplicate is still refused — by the database, at
        write time, as a whole-file 422 — and the difference between that and a
        200 carrying a line number *is* what this check buys. Reading the body
        first turned that regression into `KeyError: 'problems'`.
        """
        response = self.upload(
            self.admin,
            csv_of("Chike Obi,JSS 1A,STM/1,,,", "Ngozi Abah,JSS 1B,STM/1,,,"),
        )

        self.assertEqual(response.status_code, 200, "a per-row report became a whole-file refusal")
        body = response.json()
        self.assertEqual([p["line"] for p in body["problems"]], [3])
        self.assertIn("twice in this file", body["problems"][0]["detail"])

    # -- references ------------------------------------------------------------

    def test_a_reference_already_used_at_this_school_is_refused(self):
        self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,0100,,"))

        body = self.upload(self.admin, csv_of("Ngozi Abah,JSS 1B,,0100,,")).json()

        self.assertEqual(body["admitted"], 0)
        self.assertIn("admission number", body["problems"][0]["detail"])

    def test_a_reference_in_use_at_the_other_school_is_no_obstacle_here(self):
        """**`Membership` is shared**, so "unique within this school" is a
        `school=` filter doing real work rather than the tenant schema doing it
        for free. Without it Grace's admission numbers would refuse St Mary's
        children — and tell St Mary's which numbers Grace has issued."""
        Membership.objects.filter(school=self.grace, role=Role.STUDENT).update(
            reference="0100"
        )

        response = self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,0100,,"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["problems"], [])
        self.assertEqual(body["admitted"], 1)

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

    def test_a_principal_is_refused_before_the_file_is_read(self):
        """**Added because controls found the first two versions blind.**

        A teacher fails both authorities, so removing either check still
        refused her. A principal is the one who can tell them apart —
        `PLACEMENT_ROLES` admits her and `MEMBERSHIP_GRANTING_ROLES` does not.

        But a *clean* file cannot tell either: without the route's check,
        `admit_student_as()` refuses her at write time anyway. What only the
        route's check provides is refusing **before `check()` reads anything**,
        so the file here is one `check()` would fault — on a handle that exists
        at the other school. Without the gate she gets a 200 and a report that
        says which handles are taken on the platform.
        """
        User.objects.create_user("GRC/2026/0001", None, full_name="Their Child")
        before = self.counts()

        response = self.upload(self.head, csv_of("Chike Obi,JSS 1A,GRC/2026/0001,,,"))

        self.assertEqual(response.status_code, 403, "the file was judged for somebody who may not import")
        body = response.json()
        self.assertNotIn("problems", body)
        self.assertIn("admitted by an administrator", body["detail"])
        self.assertEqual(self.counts(), before)

    def test_an_administrator_at_one_school_cannot_import_at_the_other(self):
        response = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,,,"), host=THEIR_HOST
        )

        self.assertEqual(response.status_code, 403)

    # -- guardians -------------------------------------------------------------

    def test_siblings_sharing_a_contact_are_one_guardian_linked_to_each(self):
        """**Two rows, one parent.** The ordinary case in a school, and not a
        duplicate to refuse."""
        response = self.upload(
            self.admin,
            csv_of(
                "Chike Obi,JSS 1A,,,Mama Obi,08031234567",
                "Ada Obi Two,JSS 1B,,,Mama Obi,08031234567",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["admitted"], 2)
        guardians = User.objects.filter(phone="+2348031234567")
        self.assertEqual(guardians.count(), 1, "one parent became two accounts")
        self.assertEqual(Guardianship.objects.filter(guardian=guardians.first()).count(), 2)

    def test_the_same_parent_written_three_ways_is_still_one_guardian(self):
        """`0803...`, `803...` and `+234803...` are one number. Normalising
        happens **before** the matching, which is the whole reason it happens
        at all."""
        response = self.upload(
            self.admin,
            csv_of(
                "One Child,JSS 1A,,,Mama Obi,08031234567",
                "Two Child,JSS 1B,,,Mama Obi,8031234567",
                "Three Child,JSS 1A,,,Mama Obi,+2348031234567",
            ),
        )

        self.assertEqual(response.status_code, 200, "three spellings of one number were refused")
        self.assertEqual(response.json()["admitted"], 3)
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

    def test_the_report_says_each_guardian_link_is_not_live_yet(self):
        """D9: `link_guardian()` grants an INVITED membership until a contact
        channel is verified, so an import that said nothing would leave the
        office believing it had finished. **Per line**, so they know which
        parents to chase.

        The link is found through the child rather than the guardian's phone,
        so that a control breaking how contacts are stored cannot turn this
        into a `DoesNotExist` about something else."""
        response = self.upload(
            self.admin,
            csv_of(
                "Chike Obi,JSS 1A,STM/1,,Mama Obi,08031234567",
                "Ngozi Abah,JSS 1B,STM/2,,Papa Abah,papa@example.com",
            ),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["guardian_links"],
            [
                {"line": 2, "guardian_contact": "+2348031234567", "status": "pending verification"},
                {"line": 3, "guardian_contact": "papa@example.com", "status": "pending verification"},
            ],
        )
        self.assertEqual(body["guardians_pending"], 2)
        link = Guardianship.objects.get(student__user__username="STM/1")
        parent = Membership.objects.get(
            user=link.guardian, school=self.stmarys, role=Role.PARENT
        )
        self.assertEqual(parent.status, "invited", "the link went live without a channel")

    def test_a_guardian_verified_elsewhere_is_pending_here_like_anybody_new(self):
        """**Reversed by #135.** This used to say "live": `link_guardian()`
        granted ACTIVE at once to a guardian verified anywhere. Now a link goes
        live only when the guardian answers *this* school, so a parent verified
        at Grace is pending at St Mary's — and the report cannot tell St Mary's
        which numbers belong to verified parents elsewhere.

        CONTROL 4: `link_guardian()` granting ACTIVE makes this go red.
        """
        parent = User.objects.create_user(
            "mama.obi", None, full_name="Mama Obi", phone="08031234567"
        )
        with_a_child_at_grace = Membership.objects.filter(
            school=self.grace, role=Role.STUDENT
        ).first()
        link_guardian(parent, with_a_child_at_grace)
        give_verified_channel(parent, "08031234567")
        self.assertTrue(parent.has_access_to(self.grace), "the fixture is not live at Grace")

        response = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,,Mama Obi,0803 123 4567")
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["guardian_links"],
            [{"line": 2, "guardian_contact": "+2348031234567", "status": "pending verification"}],
        )
        self.assertEqual(body["guardians_pending"], 1)
        self.assertEqual(
            Guardianship.objects.get(student__user__username="ST-MARYS/1").guardian,
            parent,
            "an existing parent was duplicated rather than linked",
        )
        self.assertFalse(parent.has_access_to(self.stmarys))

    def test_a_guardian_already_live_at_this_school_is_reported_live(self):
        """The one case a new link is live: this school has already had its
        answer from this guardian, for another child, and `grant_membership()`
        never takes that back. Liveness is per school, not per child.

        The control for the test above, and the reason it needs one: a report
        that printed "pending verification" whatever happened would pass it.
        """
        parent = User.objects.create_user(
            "mama.obi", None, full_name="Mama Obi", phone="08031234567"
        )
        link_guardian(
            parent, Membership.objects.filter(school=self.stmarys, role=Role.STUDENT).first()
        )
        give_verified_channel(parent, "08031234567")

        body = self.upload(
            self.admin, csv_of("Chike Obi,JSS 1A,,,Mama Obi,08031234567")
        ).json()

        self.assertEqual(
            body["guardian_links"],
            [{"line": 2, "guardian_contact": "+2348031234567", "status": "live"}],
        )
        self.assertEqual(body["guardians_pending"], 0)

    def test_an_imported_guardian_has_a_channel_to_verify(self):
        """D10: one guardian record, one verification story, whichever door.
        The import used to make the `User` and record no channel, so there was
        nothing for anybody to verify.

        CONTROL 7: the import creating its own guardian rather than going
        through `link_by_contact_as()` makes this go red.
        """
        self.upload(self.admin, csv_of("Chike Obi,JSS 1A,,,Mama Obi,0803 123 4567"))

        guardian = Guardianship.objects.get(student__user__username="ST-MARYS/1").guardian
        contact = GuardianAccount.objects.get(user=guardian).live_contact()
        self.assertIsNotNone(contact, "an imported guardian has no channel")
        self.assertEqual(contact.value, "+2348031234567")
        self.assertIsNone(contact.verified_at)

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
