"""Who a release left without a card, written down by the release itself. Issue #47.

Two halves, in two kinds of test.

**The detector, against a real race.** A child placed into the class while its
release runs has to be another session's committed work, landing between two
statements of the releasing transaction, so these build on
`test_release_roster_race`'s machinery: `TransactionTestCase`, a real second
connection, and the placement timed inside `cards.freeze_for_release` rather
than raced for. Both schools release, and each has its own child landing
mid-release, so "each school writes down its own" is a statement about two
records rather than about one record and an empty table. The same machinery
proves the two things the review of #164 asked for: a check that fails stops
the release, and nothing writes down a child who arrived after it.

**What the principal is shown, over HTTP.** The chain fixture's two schools
and hosts, with the placement made inside the release's own transaction. The
check commits with the release, so an ordinary `TestCase` sees what the page
would; the race is proved above.
"""

import threading
from unittest import mock

from django.db import connection, connections, transaction
from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from results import cards, omissions, services
from results.models import (
    ReleaseCheck,
    ReleasedCard,
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
THIRD = TermName.THIRD.value
NOT_CHECKED = "Couldn't check who was left out of JSS 1A"


class ARosterThatWillNotRead:
    """Stands in for `positions` inside `omissions`, and only there.

    Its roster read is a real database error, raised inside the release's
    transaction, so the check fails the way a real one would: with the
    connection mid-transaction and the error in Postgres, not a Python
    exception thrown from nowhere.
    """

    @staticmethod
    def roster_ids(class_group, term):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM a_roster_that_is_not_there")


def the_check_fails():
    return mock.patch.object(omissions, "positions", ARosterThatWillNotRead)


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
                Term.objects.get(pk=terms[THIRD]),
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
                        Term.objects.get(pk=terms[THIRD]),
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

    def release(self, school, *, landing=None, sheet_id=None):
        """Release this school's third term; `landing` is placed mid-release.

        Approves first unless handed the `sheet_id` of one already approved,
        which is how a release that was stopped is released again.
        """
        if sheet_id is None:
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

    def checked(self, school):
        with connected_to(school):
            return list(ReleaseCheck.objects.values_list("sheet_id", flat=True))

    def release_over_http(self, *, landing=None):
        """St Mary's release, through the chain's own route and host.

        What the principal's page receives, with a real commit behind it.
        """
        from schools.models import Domain

        Domain.objects.create(tenant=self.school, domain="st-marys.testserver", is_primary=True)
        with connected_to(self.school):
            Term.objects.filter(pk=self.terms[THIRD]).update(is_current=True)
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
        self.assertIs(body["left_out_checked"], True)
        self.assertEqual([c["name"] for c in body["without_a_card"]], ["Bola Eze"])

    def test_a_release_that_left_nobody_out_answers_with_an_empty_list(self):
        """`[]`, which is "none" — distinct from the `null` others are sent."""
        body = self.release_over_http()

        self.assertEqual(body["state"], SheetState.RELEASED)
        self.assertIs(body["left_out_checked"], True)
        self.assertEqual(body["without_a_card"], [])

    def test_the_child_placed_mid_release_is_written_down(self):
        sheet_id = self.release(self.school, landing=self.bola)

        self.assertEqual(self.recorded(self.school), [(sheet_id, self.bola.pk, "Bola Eze")])

        with connected_to(self.school):
            row = ReleaseOmission.objects.get()
            released_at = ResultSheetTransition.objects.get(
                sheet_id=sheet_id, to_state=SheetState.RELEASED
            ).created_at
        # Noticed by the release's own check, after its transition row.
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

    def test_every_release_says_it_checked_whether_it_found_anyone_or_not(self):
        """The `ReleaseCheck` row, at a school with an omission and one without.

        It is what makes St Mary's empty list "nobody" rather than "not known".
        """
        ours = self.release(self.school)
        theirs = self.release(self.other_school, landing=self.emeka)

        self.assertEqual(self.checked(self.school), [ours])
        self.assertEqual(self.checked(self.other_school), [theirs])

    def test_a_check_that_fails_stops_the_release(self):
        """Nothing is released, nothing is written down, and the refusal says why.

        St Mary's check fails with Bola landing, so there was a child to record
        and it is not recorded either: the whole release rolled back. Grace
        releases in the same test, with nothing wrong, and writes down its own
        child, so the failure belongs to one release and not to the check.
        """
        sheet_id = self.approve(self.school)
        with the_check_fails(), self.assertLogs("results.omissions", "ERROR") as logged:
            with self.assertRaisesRegex(services.LeftOutNotChecked, NOT_CHECKED):
                self.release(self.school, landing=self.bola, sheet_id=sheet_id)
        theirs = self.release(self.other_school, landing=self.emeka)

        with connected_to(self.school):
            self.assertEqual(ResultSheet.objects.get(pk=sheet_id).state, SheetState.APPROVED)
            self.assertFalse(ReleasedCard.objects.filter(sheet_id=sheet_id).exists())
            self.assertFalse(
                ResultSheetTransition.objects.filter(
                    sheet_id=sheet_id, to_state=SheetState.RELEASED
                ).exists()
            )
        self.assertEqual(self.recorded(self.school), [])
        self.assertEqual(self.checked(self.school), [])
        self.assertIn(f"sheet {sheet_id}", logged.output[0])

        self.assertEqual(
            self.recorded(self.other_school), [(theirs, self.emeka.pk, "Emeka Nwosu")]
        )
        self.assertEqual(self.checked(self.other_school), [theirs])

    def test_releasing_again_gives_a_child_placed_since_a_card_and_no_record(self):
        """The recovery from a stopped release, at both schools.

        Both releases fail their check and roll back. Each school then places a
        child, after the release as far as anything could tell, and the
        principal releases again. That release reads the class for itself, so
        she is on it and gets a card, and nothing writes her down as left out.
        """
        stopped = {}
        for school in (self.school, self.other_school):
            stopped[school] = self.approve(school)
            with the_check_fails(), self.assertLogs("results.omissions", "ERROR"):
                with self.assertRaises(services.LeftOutNotChecked):
                    self.release(school, sheet_id=stopped[school])

        self.place_from_another_connection(self.school, self.bola)
        self.place_from_another_connection(self.other_school, self.emeka)

        for school in (self.school, self.other_school):
            self.release(school, sheet_id=stopped[school])

        for school, child in ((self.school, self.bola), (self.other_school, self.emeka)):
            with self.subTest(school=school.name):
                with connected_to(school):
                    sheet_id = stopped[school]
                    self.assertEqual(
                        ResultSheet.objects.get(pk=sheet_id).state, SheetState.RELEASED
                    )
                    self.assertTrue(
                        ReleasedCard.objects.filter(
                            sheet_id=sheet_id, student_membership_id=child.pk, version=1
                        ).exists(),
                        "the child placed since has no card",
                    )
                self.assertEqual(self.recorded(school), [])
                self.assertEqual(self.checked(school), [sheet_id])

    def test_a_child_placed_after_the_release_is_never_written_down(self):
        """At both schools, a placement that commits straight after the release.

        The placement is registered on the release's own commit, ahead of
        anything the release registers, so it lands once the release is durable
        and before anything that runs after the commit. A check that ran after
        the commit would find her there with no card and write her down as left
        out by a release she arrived after. The check inside the release cannot
        see her.
        """
        for school, child in ((self.school, self.bola), (self.other_school, self.emeka)):
            with self.subTest(school=school.name):
                sheet_id = self.approve(school)
                group_id, terms, (_, _, principal) = self._parts(school)
                with connected_to(school):
                    group = ClassGroup.objects.get(pk=group_id)
                    term = Term.objects.get(pk=terms[THIRD])

                    with transaction.atomic():
                        transaction.on_commit(
                            lambda group=group, term=term, child=child: (
                                academics.place_student(group, term, child)
                            )
                        )
                        services.release(ResultSheet.objects.get(pk=sheet_id), principal)

                    # She arrived: on the class, and with no card from it.
                    self.assertIn(child.pk, ClassPlacement.objects.student_ids(group, term))
                    self.assertFalse(
                        ReleasedCard.objects.filter(
                            sheet_id=sheet_id, student_membership_id=child.pk
                        ).exists()
                    )
                self.assertEqual(self.recorded(school), [])
                self.assertEqual(self.checked(school), [sheet_id])


class TheRecordIsAppendOnly(RefusalAssertions, ChainSetUp):
    def a_row(self):
        with connected_to(self.stmarys):
            sheet = services.open_sheet(self.jss1a, self.term, self.head.user)
            return ReleaseOmission.objects.create(
                sheet=sheet,
                student_membership_id=self.children["ada"].pk,
                student_name="Ada Obi",
            )

    def a_check(self):
        with connected_to(self.stmarys):
            sheet = services.open_sheet(self.jss1a, self.term, self.head.user)
            return ReleaseCheck.objects.create(sheet=sheet)

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

    def test_the_check_row_is_refused_an_edit_and_a_delete_by_the_table(self):
        """A check row that could be moved or removed would make "nobody" a guess."""
        check = self.a_check()
        with connected_to(self.stmarys):
            with self.assertRefusedBy(
                "results_releasecheck is append-only; UPDATE is not allowed"
            ), transaction.atomic():
                ReleaseCheck.objects.filter(pk=check.pk).update(checked_at=check.checked_at)
            with self.assertRefusedBy(
                "results_releasecheck is append-only; DELETE is not allowed"
            ), transaction.atomic():
                ReleaseCheck.objects.filter(pk=check.pk).delete()

            self.assertTrue(ReleaseCheck.objects.filter(pk=check.pk).exists())

    def test_the_check_row_model_refuses_before_the_table_has_to(self):
        check = self.a_check()
        with connected_to(self.stmarys):
            with self.assertRaises(ReleaseOmissionsAreAppendOnly):
                check.save()
            with self.assertRaises(ReleaseOmissionsAreAppendOnly):
                check.delete()


class TheTermsCardsCount(ChainSetUp):
    """A child moved in mid-release with a card from her old class is not left out.

    At each school one class is released first, and one of its children is then
    moved into the other class while that one releases. She has a card for the
    term, from the class she left, and it has gone home. A child placed from
    nowhere at the same moment has none, and is written down, so the check
    visibly ran and looked at both.
    """

    def setUp(self):
        super().setUp()
        self.zainab = enroll_student(
            User.objects.create_user("zainab", PASSWORD, full_name="Zainab Musa"),
            self.stmarys,
        )
        with connected_to(self.stmarys):
            academics.assign_class_teacher(self.jss1b, self.term, self.teacher, by=self.head)

        self.obi = enroll_student(
            User.objects.create_user("obi", PASSWORD, full_name="Obi Nnaji"), self.grace
        )
        self.ifeoma = enroll_student(
            User.objects.create_user("ifeoma", PASSWORD, full_name="Ifeoma Uche"),
            self.grace,
        )
        with connected_to(self.grace):
            self.grace_term = Term.objects.get(pk=self.grace_term_id)
            self.grace_1b = ClassGroup.objects.create(name="JSS 1B", level=1)
            academics.place_student(self.grace_1b, self.grace_term, self.obi)
            academics.assign_class_teacher(
                self.grace_1b, self.grace_term, self.grace_teacher, by=self.their_head
            )

    def release(self, school, group, term, staff, *, during=None):
        teacher, vp, head = staff
        real = cards.freeze_for_release

        def freeze_then(*args, **kwargs):
            card_by_student = real(*args, **kwargs)
            if during is not None:
                during()
            return card_by_student

        with connected_to(school):
            sheet = services.open_sheet(group, term, head.user)
            services.submit(sheet, teacher.user)
            services.check(sheet, vp.user)
            services.approve(sheet, head.user)
            with mock.patch.object(cards, "freeze_for_release", freeze_then):
                services.release(ResultSheet.objects.get(pk=sheet.pk), head.user)
            return sheet.pk

    def test_a_child_moved_in_with_a_card_this_term_is_not_left_out(self):
        ours = (self.teacher, self.vp, self.head)
        theirs = (self.grace_teacher, self.their_vp, self.their_head)

        self.release(self.stmarys, self.jss1b, self.term, ours)
        sheet_id = self.release(
            self.stmarys,
            self.jss1a,
            self.term,
            ours,
            during=lambda: (
                academics.move_student(self.jss1a, self.term, self.bimpe),
                academics.place_student(self.jss1a, self.term, self.zainab),
            ),
        )
        self.release(self.grace, self.grace_1b, self.grace_term, theirs)
        their_sheet_id = self.release(
            self.grace,
            self.grace_group,
            self.grace_term,
            theirs,
            during=lambda: (
                academics.move_student(self.grace_group, self.grace_term, self.obi),
                academics.place_student(self.grace_group, self.grace_term, self.ifeoma),
            ),
        )

        for school, sheet, moved, placed in (
            (self.stmarys, sheet_id, self.bimpe, self.zainab),
            (self.grace, their_sheet_id, self.obi, self.ifeoma),
        ):
            with self.subTest(school=school.name), connected_to(school):
                # Both are on the class now, and neither has a card from it.
                self.assertFalse(
                    ReleasedCard.objects.filter(
                        sheet_id=sheet,
                        student_membership_id__in=[moved.pk, placed.pk],
                    ).exists()
                )
                # She has one for the term, from the class she left.
                self.assertTrue(
                    ReleasedCard.objects.filter(
                        student_membership_id=moved.pk, version=1
                    ).exclude(sheet_id=sheet).exists()
                )
                self.assertEqual(
                    list(
                        ReleaseOmission.objects.filter(sheet_id=sheet).values_list(
                            "student_membership_id", flat=True
                        )
                    ),
                    [placed.pk],
                )


class ThePrincipalIsTold(ChainSetUp):
    """The list names the child, to the principal and to nobody else."""

    def setUp(self):
        super().setUp()
        self.zainab = enroll_student(
            User.objects.create_user("zainab", PASSWORD, full_name="Zainab Musa"),
            self.stmarys,
            reference="STM/99",
        )

    def step(self, who, step, host=HOST, group_id=None):
        self.client.force_login(who.user)
        return self.client.post(
            f"/api/results/chain/{group_id or self.jss1a_id}/{step}/",
            content_type="application/json",
            HTTP_HOST=host,
        )

    def listed(self, who, host=HOST):
        self.client.force_login(who.user)
        rows = self.client.get(CHAIN, HTTP_HOST=host).json()["rows"]
        return {row["class_group"] + f"#{row['class_group_id']}": row for row in rows}

    def approve_ours(self):
        self.step(self.teacher, "submit")
        self.step(self.vp, "check")
        self.step(self.head, "approve")

    def release_theirs(self):
        """Grace's JSS 1A, all the way, on Grace's host."""
        for who, step in (
            (self.grace_teacher, "submit"),
            (self.their_vp, "check"),
            (self.their_head, "approve"),
            (self.their_head, "release"),
        ):
            answer = self.step(who, step, host=THEIR_HOST, group_id=self.grace_group_id)
            self.assertEqual(answer.status_code, 200, answer.content)
        return answer.json()

    def release_with_zainab_landing(self):
        """Release JSS 1A, with Zainab placed after the cards are frozen.

        Inside the release's own transaction, so the check at its end finds her
        on the class and without a card. The race itself is
        `TheDetectorUnderARealRace`'s business.
        """
        self.approve_ours()

        real = cards.freeze_for_release

        def freeze_then_place(*args, **kwargs):
            card_by_student = real(*args, **kwargs)
            academics.place_student(self.jss1a, self.term, self.zainab)
            return card_by_student

        with mock.patch.object(cards, "freeze_for_release", freeze_then_place):
            return self.step(self.head, "release")

    def test_the_list_names_her_to_the_principal_and_to_nobody_else(self):
        answer = self.release_with_zainab_landing()
        self.assertEqual([c["name"] for c in answer.json()["without_a_card"]], ["Zainab Musa"])

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

    def test_a_release_that_could_not_check_is_not_released_and_says_so(self):
        """St Mary's check fails; Grace's does not. Then St Mary's tries again.

        The principal reads "couldn't check who was left out" and a class still
        waiting to be released, never a released class with nobody listed.
        """
        self.approve_ours()
        with the_check_fails(), self.assertLogs("results.omissions", "ERROR"):
            stopped = self.step(self.head, "release")

        self.assertEqual(stopped.status_code, 503, stopped.content)
        self.assertEqual(stopped.json()["code"], "left_out_not_checked")
        self.assertIn(NOT_CHECKED, stopped.json()["detail"])
        self.assertIn("has not been released", stopped.json()["detail"])

        row = self.listed(self.head)[f"JSS 1A#{self.jss1a_id}"]
        self.assertEqual(row["state"], SheetState.APPROVED)
        self.assertIs(row["may_release"], True)
        self.assertIsNone(row["without_a_card"])
        self.assertIsNone(row["left_out_checked"])

        theirs = self.release_theirs()
        self.assertIs(theirs["left_out_checked"], True)
        self.assertEqual(theirs["without_a_card"], [])

        again = self.step(self.head, "release")
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json()["state"], SheetState.RELEASED)
        self.assertIs(again.json()["left_out_checked"], True)
        self.assertEqual(again.json()["without_a_card"], [])

    def test_a_released_class_nobody_checked_is_not_known_rather_than_empty(self):
        """St Mary's released with no check behind it; Grace released as normal.

        However it came about, a released sheet with no `ReleaseCheck` must not
        read as "nobody was left out" — on the step's answer or on the list.
        """
        self.approve_ours()
        with mock.patch.object(omissions, "check"):
            answer = self.step(self.head, "release")
        self.assertEqual(answer.status_code, 200, answer.content)
        self.release_theirs()

        ours = self.listed(self.head)[f"JSS 1A#{self.jss1a_id}"]
        for body in (answer.json(), ours):
            with self.subTest(where="step" if body is not ours else "list"):
                self.assertEqual(body["state"], SheetState.RELEASED)
                self.assertIs(body["left_out_checked"], False)
                self.assertIsNone(body["without_a_card"])

        theirs = self.listed(self.their_head, host=THEIR_HOST)[
            f"JSS 1A#{self.grace_group_id}"
        ]
        self.assertIs(theirs["left_out_checked"], True)
        self.assertEqual(theirs["without_a_card"], [])

        # Somebody who may not release is told nothing either way.
        self.assertIsNone(self.listed(self.teacher)[f"JSS 1A#{self.jss1a_id}"]["left_out_checked"])
