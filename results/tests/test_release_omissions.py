"""Who a release left without a card, written down after it commits. Issue #47.

Two halves, in two kinds of test.

**The detector, against a real race.** A child placed into the class while its
release runs has to be another session's committed work, landing between two
statements of the releasing transaction, so these build on
`test_release_roster_race`'s machinery: `TransactionTestCase`, a real second
connection, and the placement timed inside `cards.freeze_for_release` rather
than raced for. Both schools release, and each has its own child landing
mid-release, so "each school writes down its own" is a statement about two
records rather than about one record and an empty table.

**What the principal is shown, over HTTP.** The chain fixture's two schools
and hosts, with the placement made inside the release's own transaction and
the commit callbacks run by `captureOnCommitCallbacks`. That is enough for the
surface; the race is proved above.
"""

import threading
from unittest import mock

from django.db import connection, connections, transaction
from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from results import cards, omissions, services
from results.models import (
    ReleaseOmission,
    ReleaseOmissionsAreAppendOnly,
    ResultSheet,
    ResultSheetTransition,
    SheetState,
)
from results.tests.fixtures import HOST, PASSWORD, THEIR_HOST, ChainSetUp
from results.tests.test_release_roster_race import ReleaseUnderARosterChangeSetUp
from schools.tests.tenants import connected_to
from tests.refusals import RefusalAssertions

CHAIN = "/api/results/chain/"


class TheDetectorUnderARealRace(ReleaseUnderARosterChangeSetUp):
    """St Mary's and Grace both release their third term; each can be raced."""

    def setUp(self):
        super().setUp()
        # Grace needs a vice principal to get as far as release, and a child of
        # its own to land mid-release.
        self.their_vp = self._staff(
            "obinna", "Obinna Okafor", self.other_school, Role.VICE_PRINCIPAL_ACADEMIC
        )
        self.emeka = self._student("emeka", "Emeka Nwosu", self.other_school)

    # -- a release at either school, with or without a child landing ---------

    def _parts(self, school):
        if school == self.school:
            return self.group_id, self.terms, (self.teacher, self.vp, self.principal)
        return (
            self.their_group_id,
            self.their_terms,
            (self.their_teacher, self.their_vp, self.their_principal),
        )

    def approve(self, school):
        group_id, terms, (teacher, vp, principal) = self._parts(school)
        with connected_to(school):
            sheet = services.open_sheet(
                ClassGroup.objects.get(pk=group_id),
                Term.objects.get(pk=terms[TermName.THIRD.value]),
                principal,
            )
            services.submit(sheet, teacher)
            services.check(sheet, vp)
            services.approve(sheet, principal)
            return sheet.pk

    def place_from_another_connection(self, school, child):
        group_id, terms, _ = self._parts(school)
        failed = []

        def run():
            try:
                with connected_to(school):
                    academics.place_student(
                        ClassGroup.objects.get(pk=group_id),
                        Term.objects.get(pk=terms[TermName.THIRD.value]),
                        child,
                    )
            except Exception as exc:  # noqa: BLE001 — reported, never swallowed
                failed.append(exc)
            finally:
                connections.close_all()

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(15)
        self.assertFalse(thread.is_alive(), "the placing thread never finished")
        self.assertEqual(failed, [], f"the placing thread failed: {failed}")

    def release(self, school, *, landing=None):
        """Release this school's third term; `landing` is placed mid-release."""
        sheet_id = self.approve(school)
        _, _, (_, _, principal) = self._parts(school)
        real = cards.freeze_for_release
        landed = []

        def freeze_then_let_the_office_in(*args, **kwargs):
            card_by_student = real(*args, **kwargs)
            if landing is not None:
                self.place_from_another_connection(school, landing)
                landed.append(True)
            return card_by_student

        with connected_to(school):
            with mock.patch.object(
                cards, "freeze_for_release", freeze_then_let_the_office_in
            ):
                services.release(ResultSheet.objects.get(pk=sheet_id), principal)
        if landing is not None:
            self.assertEqual(landed, [True], "the placement never landed mid-release")
        return sheet_id

    def recorded(self, school):
        with connected_to(school):
            return list(
                ReleaseOmission.objects.values_list(
                    "sheet_id", "student_membership_id", "student_name"
                )
            )

    def release_over_http(self, *, landing=None):
        """St Mary's release, through the chain's own route and host.

        What the principal's page receives. The check registered inside the
        release has to have run before this answer is built, and only a real
        commit shows whether it has.
        """
        from schools.models import Domain

        Domain.objects.create(tenant=self.school, domain="st-marys.testserver", is_primary=True)
        with connected_to(self.school):
            Term.objects.filter(pk=self.terms[TermName.THIRD.value]).update(is_current=True)
        self.approve(self.school)

        real = cards.freeze_for_release

        def freeze_then_let_the_office_in(*args, **kwargs):
            card_by_student = real(*args, **kwargs)
            if landing is not None:
                self.place_from_another_connection(self.school, landing)
            return card_by_student

        self.client.force_login(self.principal)
        with mock.patch.object(cards, "freeze_for_release", freeze_then_let_the_office_in):
            answer = self.client.post(
                f"/api/results/chain/{self.group_id}/release/",
                content_type="application/json",
                HTTP_HOST="st-marys.testserver",
            )
        connection.set_schema_to_public()
        self.assertEqual(answer.status_code, 200, answer.content)
        return answer.json()

    # -- the claims -----------------------------------------------------------

    def test_the_release_step_answers_with_her_name(self):
        body = self.release_over_http(landing=self.bola)

        self.assertEqual(body["state"], SheetState.RELEASED)
        self.assertEqual([c["name"] for c in body["without_a_card"]], ["Bola Eze"])

    def test_a_release_that_left_nobody_out_answers_with_an_empty_list(self):
        """`[]`, which is "none" — distinct from the `null` others are sent."""
        body = self.release_over_http()

        self.assertEqual(body["state"], SheetState.RELEASED)
        self.assertEqual(body["without_a_card"], [])

    def test_the_child_placed_mid_release_is_written_down(self):
        sheet_id = self.release(self.school, landing=self.bola)

        self.assertEqual(self.recorded(self.school), [(sheet_id, self.bola.pk, "Bola Eze")])

        with connected_to(self.school):
            row = ReleaseOmission.objects.get()
            released_at = ResultSheetTransition.objects.get(
                sheet_id=sheet_id, to_state=SheetState.RELEASED
            ).created_at
        # Noticed after the release, by the check that runs once it commits.
        self.assertGreaterEqual(row.noticed_at, released_at)

    def test_each_school_writes_down_its_own(self):
        """Two releases, two children landing, two records — and no crossing.

        `ReleaseOmission` is a tenant table, so the rows are in two schemas; the
        claim is that each check read its own school's roster and wrote to its
        own school's table, which a check on the wrong connection would not.
        """
        ours = self.release(self.school, landing=self.bola)
        theirs = self.release(self.other_school, landing=self.emeka)

        self.assertEqual(self.recorded(self.school), [(ours, self.bola.pk, "Bola Eze")])
        self.assertEqual(
            self.recorded(self.other_school), [(theirs, self.emeka.pk, "Emeka Nwosu")]
        )

    def test_an_undisturbed_release_writes_nothing(self):
        """The control for the one above: nothing moved, nothing is recorded.

        Grace releases in the same test with Emeka landing, so "nothing" here is
        St Mary's answer and not a detector that never ran.
        """
        self.release(self.school)
        self.release(self.other_school, landing=self.emeka)

        self.assertEqual(self.recorded(self.school), [])
        self.assertEqual(len(self.recorded(self.other_school)), 1)

    def test_a_failing_check_does_not_fail_the_release(self):
        """The release is durable by the time the check runs; a 500 would lie."""
        with mock.patch.object(omissions, "record", side_effect=RuntimeError("boom")):
            with self.assertLogs("results.omissions", level="ERROR") as logged:
                sheet_id = self.release(self.school, landing=self.bola)

        with connected_to(self.school):
            self.assertEqual(ResultSheet.objects.get(pk=sheet_id).state, SheetState.RELEASED)
        self.assertIn(f"sheet {sheet_id}", logged.output[0])

    def test_the_check_enters_the_school_it_was_given(self):
        """Not whatever schema the connection happens to be on when it runs.

        Called from `public`, as a callback on a pooled connection could be.
        Bola is placed after an ordinary release, so she is on the class with no
        card, which is the state the check exists to find.
        """
        sheet_id = self.release(self.school)
        self.place_from_another_connection(self.school, self.bola)

        connection.set_schema_to_public()
        omissions._notice(self.school.schema_name, sheet_id)

        self.assertEqual(self.recorded(self.school), [(sheet_id, self.bola.pk, "Bola Eze")])


class TheRecordIsAppendOnly(RefusalAssertions, ChainSetUp):
    def a_row(self):
        with connected_to(self.stmarys):
            sheet = services.open_sheet(self.jss1a, self.term, self.head.user)
            return ReleaseOmission.objects.create(
                sheet=sheet,
                student_membership_id=self.children["ada"].pk,
                student_name="Ada Obi",
            )

    def test_the_table_refuses_an_edit_and_a_delete(self):
        row = self.a_row()
        with connected_to(self.stmarys):
            with self.assertRefusedBy(
                "results_releaseomission is append-only; UPDATE is not allowed"
            ), transaction.atomic():
                ReleaseOmission.objects.filter(pk=row.pk).update(student_name="Someone")
            with self.assertRefusedBy(
                "results_releaseomission is append-only; DELETE is not allowed"
            ), transaction.atomic():
                ReleaseOmission.objects.filter(pk=row.pk).delete()

            self.assertEqual(ReleaseOmission.objects.get(pk=row.pk).student_name, "Ada Obi")

    def test_the_model_refuses_before_the_table_has_to(self):
        row = self.a_row()
        with connected_to(self.stmarys):
            row.student_name = "Someone"
            with self.assertRaises(ReleaseOmissionsAreAppendOnly):
                row.save()
            with self.assertRaises(ReleaseOmissionsAreAppendOnly):
                row.delete()

    def test_one_release_omits_a_child_once(self):
        row = self.a_row()
        with connected_to(self.stmarys):
            with self.assertRefusedBy("a_release_omits_a_child_once"), transaction.atomic():
                ReleaseOmission.objects.create(
                    sheet_id=row.sheet_id, student_membership_id=row.student_membership_id
                )

    def test_recording_twice_writes_once(self):
        """`record()` may be run again by hand; the second run adds nothing."""
        with connected_to(self.stmarys):
            sheet = services.open_sheet(self.jss1a, self.term, self.head.user)
            first = omissions.record(sheet)
            again = omissions.record(sheet)

            # No card was ever frozen, so everyone on the class counts.
            self.assertEqual(len(first), len(self.children))
            self.assertEqual(again, [])
            self.assertEqual(ReleaseOmission.objects.count(), len(self.children))


class ThePrincipalIsTold(ChainSetUp):
    """The list names the child, to the principal and to nobody else.

    The release step's own answer is asserted in `TheDetectorUnderARealRace`,
    not here. Its point is that the check has already run when the step
    answers, which is true only with a real commit: in a `TestCase`,
    `captureOnCommitCallbacks` runs the callbacks after the response is built,
    so a response test here would pass whatever the release left out.
    """

    def setUp(self):
        super().setUp()
        self.zainab = enroll_student(
            User.objects.create_user("zainab", PASSWORD, full_name="Zainab Musa"),
            self.stmarys,
            reference="STM/99",
        )

    def step(self, who, step, host=HOST):
        self.client.force_login(who.user)
        return self.client.post(
            f"/api/results/chain/{self.jss1a_id}/{step}/",
            content_type="application/json",
            HTTP_HOST=host,
        )

    def listed(self, who, host=HOST):
        self.client.force_login(who.user)
        rows = self.client.get(CHAIN, HTTP_HOST=host).json()["rows"]
        return {row["class_group"] + f"#{row['class_group_id']}": row for row in rows}

    def release_with_zainab_landing(self):
        """Release JSS 1A, with Zainab placed after the cards are frozen.

        Inside the release's own transaction, so the check after the commit —
        run by `captureOnCommitCallbacks` when the block ends — finds her on the
        class and without a card. The race itself is
        `TheDetectorUnderARealRace`'s business.
        """
        self.step(self.teacher, "submit")
        self.step(self.vp, "check")
        self.step(self.head, "approve")

        real = cards.freeze_for_release

        def freeze_then_place(*args, **kwargs):
            card_by_student = real(*args, **kwargs)
            academics.place_student(self.jss1a, self.term, self.zainab)
            return card_by_student

        with mock.patch.object(cards, "freeze_for_release", freeze_then_place):
            with self.captureOnCommitCallbacks(execute=True):
                return self.step(self.head, "release")

    def test_the_list_names_her_to_the_principal_and_to_nobody_else(self):
        self.release_with_zainab_landing()

        principal = self.listed(self.head)[f"JSS 1A#{self.jss1a_id}"]
        self.assertEqual(
            [c["name"] for c in principal["without_a_card"]], ["Zainab Musa"]
        )
        # A class that is not released carries `null` even for the principal.
        self.assertIsNone(self.listed(self.head)[f"JSS 1B#{self.jss1b_id}"]["without_a_card"])

        # Everybody else who can see the list: `null`, not a name and not `[]`.
        for who in (self.teacher, self.vp):
            with self.subTest(who=who.user.username):
                self.assertIsNone(
                    self.listed(who)[f"JSS 1A#{self.jss1a_id}"]["without_a_card"]
                )

    def test_the_other_school_hears_nothing_of_it(self):
        """Grace's principal, on Grace's host, after St Mary's released with a gap."""
        self.release_with_zainab_landing()

        for row in self.listed(self.their_head, host=THEIR_HOST).values():
            self.assertIsNone(row["without_a_card"])
        with connected_to(self.grace):
            self.assertEqual(ReleaseOmission.objects.count(), 0)
