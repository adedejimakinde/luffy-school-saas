"""A write sent twice, with the first answer lost, lands once. At two schools.

`docs/offline.md` correctness requirement 1, and D3. Every test here is shaped
the same way: a write with a key lands, something happens that a second copy of
it must not undo, and then the second copy arrives. Each is one a replay judged
afresh gets wrong:

- a mark: the teacher has since entered a *different* mark on another device,
  so `_is_our_write_arriving_twice()` no longer recognises the replay and calls
  it a conflict with themselves;
- a register: the office has since corrected it, and a register applied again
  puts every corrected absence back.

**Two schools, and the second is not decoration.** The receipt is a row in a
school's own schema. With it anywhere else, a key that landed at St Mary's would
be found by Grace's request and Grace's teacher told her write was somebody
else's. `test_a_key_is_one_schools_fact` is the one that says so, and moving
`sync` from `TENANT_APPS` to `SHARED_APPS` is its control.
"""

import json
import uuid

from django.db import connection

from academics.models import ClassGroup
from accounts.models import Membership, Role, User
from accounts.services import grant_membership
from attendance.models import AttendanceMark, AttendanceStatus
from attendance.tests.fixtures import A_SCHOOL_DAY
from gradebook.models import Score
from gradebook.tests.fixtures import PASSWORD, MarkingSetUp
from schools.models import Domain
from schools.tests.tenants import connected_to
from sync.models import SyncReceipt
from tests.refusals import RefusalAssertions

HOST = "st-marys.testserver"
GRACE_HOST = "grace.testserver"

#: A replay's whole answer: that it landed, and nothing about the cell (#161).
ALREADY_SAVED = {"detail": "Already saved.", "already_saved": True}


class ReplaySetUp(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=GRACE_HOST, is_primary=True)
        self.ada = self.children["ada"]
        self.emeka = self.children["emeka"]

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def as_(self, membership):
        self.client.force_login(membership.user)

    def save(self, student, value, *, key=None, expected_version=None,
             assessment_id=None, host=HOST):
        body = {"value": value, "expected_version": expected_version}
        if key is not None:
            body["key"] = str(key)
        return self.client.put(
            f"/api/gradebook/assessments/{assessment_id or self.first_ca_id}"
            f"/scores/{student}/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=host,
        )

    def take(self, absent_ids, *, key=None, group=None, term=None, host=HOST):
        body = {"absent_ids": absent_ids}
        if key is not None:
            body["key"] = str(key)
        return self.client.put(
            f"/api/attendance/classes/{group or self.jss1a_id}"
            f"/terms/{term or self.term_id}/{A_SCHOOL_DAY}/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=host,
        )

    def value_of(self, school, assessment_id, student):
        with connected_to(school):
            return Score.objects.get(
                assessment_id=assessment_id, student_membership_id=student
            ).value

    def receipts_at(self, school):
        with connected_to(school):
            return SyncReceipt.objects.count()


class AMarkReplayedAfterALaterOneTests(ReplaySetUp):
    """17 queued last night, 18 entered this morning, the 17 arriving after it."""

    def the_story(self, *, host, school, teacher, student, assessment_id):
        self.as_(teacher)
        key = uuid.uuid4()

        first = self.save(student, 17, key=key, assessment_id=assessment_id, host=host)
        self.assertEqual(first.status_code, 200)

        # On another device, shown the 17, the teacher changes it to 18.
        later = self.save(
            student, 18, expected_version=first.json()["version"],
            assessment_id=assessment_id, host=host,
        )
        self.assertEqual(later.status_code, 200)

        replayed = self.save(
            student, 17, key=key, assessment_id=assessment_id, host=host
        )
        return first, replayed

    def test_the_replay_is_told_it_is_already_saved_and_nothing_else(self):
        """Not the first arrival's answer: that was 17 at a version the 18 has
        since moved past, and a device drawing it would show the teacher their
        own mark as it no longer is (#161)."""
        for host, school, teacher, student, assessment_id in (
            (HOST, self.stmarys, self.teacher, self.ada.pk, self.first_ca_id),
            (GRACE_HOST, self.grace, self.grace_teacher, self.grace_child.pk,
             self.grace_ca_id),
        ):
            with self.subTest(school=school.name):
                first, replayed = self.the_story(
                    host=host, school=school, teacher=teacher, student=student,
                    assessment_id=assessment_id,
                )
                self.assertEqual(replayed.status_code, 200, replayed.content)
                self.assertEqual(replayed.json(), ALREADY_SAVED)
                # Not the key's doing: the replay carries the version it was
                # queued with, and that alone keeps it off the 18. Asserted so
                # that answering from a receipt is never mistaken for writing.
                self.assertEqual(self.value_of(school, assessment_id, student), 18)

    def test_without_a_key_the_same_replay_is_a_conflict(self):
        """What the key is for, pinned so the difference cannot quietly close.

        The keyless path is unchanged on purpose, and this is the case
        `_is_our_write_arriving_twice()` cannot see: the value moved, so the
        inference says somebody else moved it.
        """
        self.as_(self.teacher)
        first = self.save(self.ada.pk, 17)
        self.save(self.ada.pk, 18, expected_version=first.json()["version"])

        self.assertEqual(self.save(self.ada.pk, 17).status_code, 409)


class ARegisterReplayedAfterTheOfficeCorrectedItTests(ReplaySetUp):
    """Ada marked absent at 8am, marked present by the office at 10am."""

    def setUp(self):
        super().setUp()
        self.grace_office = grant_membership(
            User.objects.create_user("bola", PASSWORD, full_name="Bola Ade"),
            self.grace,
            Role.PRINCIPAL,
        )

    def the_story(self, *, host, teacher, office, child, group, term):
        key = uuid.uuid4()
        self.as_(teacher)
        first = self.take([child], key=key, group=group, term=term, host=host)
        self.assertEqual(first.status_code, 200, first.content)

        self.as_(office)
        corrected = self.take([], group=group, term=term, host=host)
        self.assertEqual(corrected.status_code, 200, corrected.content)

        self.as_(teacher)
        replayed = self.take([child], key=key, group=group, term=term, host=host)
        return first, replayed

    def cases(self):
        return (
            (HOST, self.stmarys, self.teacher, self.head, self.ada.pk,
             self.jss1a_id, self.term_id),
            (GRACE_HOST, self.grace, self.grace_teacher, self.grace_office,
             self.grace_child.pk, self.grace_group_id, self.grace_term_id),
        )

    def test_the_correction_stands(self):
        for host, school, teacher, office, child, group, term in self.cases():
            with self.subTest(school=school.name):
                self.the_story(
                    host=host, teacher=teacher, office=office, child=child,
                    group=group, term=term,
                )
                with connected_to(school):
                    mark = AttendanceMark.objects.get(
                        register__class_group_id=group,
                        register__taken_on=A_SCHOOL_DAY,
                        student_membership_id=child,
                    )
                self.assertEqual(mark.status, AttendanceStatus.PRESENT)

    def test_the_replay_is_told_it_is_already_saved_and_nothing_else(self):
        """Not the 8am absences: the office has corrected them since (#161)."""
        for host, school, teacher, office, child, group, term in self.cases():
            with self.subTest(school=school.name):
                first, replayed = self.the_story(
                    host=host, teacher=teacher, office=office, child=child,
                    group=group, term=term,
                )
                self.assertEqual(replayed.status_code, 200, replayed.content)
                self.assertEqual(replayed.json(), ALREADY_SAVED)


class AWriteThatLandedIsNotRefusedOnItsResendTests(ReplaySetUp):
    """#161: the receipt is asked before authority, for this person's own write.

    The case: a write lands, its answer is lost, and before the device sends it
    again the teacher's role changes. Asked authority first, the resend is a 403
    — final to the outbox, and shown as "not saved" about a mark that was
    saved. Asked the receipt first, it is told the truth.
    """

    def setUp(self):
        super().setUp()
        self.grace_head = grant_membership(
            User.objects.create_user("grace-head", PASSWORD, full_name="Bola Ade"),
            self.grace,
            Role.PRINCIPAL,
        )
        self.grace_bursar = grant_membership(
            User.objects.create_user("grace-bursar", PASSWORD, full_name="Femi Ade"),
            self.grace,
            Role.BURSAR,
        )

    def no_longer_marks(self, membership):
        Membership.objects.filter(pk=membership.pk).update(role=Role.BURSAR)

    def mark_cases(self):
        return (
            (HOST, self.stmarys, self.teacher, self.ada.pk, self.first_ca_id,
             self.head, self.bursar),
            (GRACE_HOST, self.grace, self.grace_teacher, self.grace_child.pk,
             self.grace_ca_id, self.grace_head, self.grace_bursar),
        )

    def test_a_mark_resent_after_the_teacher_can_no_longer_mark_is_already_saved(self):
        for host, school, teacher, student, assessment_id, _, _ in self.mark_cases():
            with self.subTest(school=school.name):
                key = uuid.uuid4()
                self.as_(teacher)
                first = self.save(student, 17, key=key, assessment_id=assessment_id, host=host)
                self.assertEqual(first.status_code, 200, first.content)

                self.no_longer_marks(teacher)
                resent = self.save(student, 17, key=key, assessment_id=assessment_id, host=host)

                self.assertEqual(resent.status_code, 200, resent.content)
                self.assertEqual(resent.json(), ALREADY_SAVED)
                # The authority really is gone: anything but the resend is refused.
                self.assertEqual(
                    self.save(student, 16, assessment_id=assessment_id, host=host,
                              expected_version=first.json()["version"]).status_code,
                    403,
                )
                self.assertEqual(self.value_of(school, assessment_id, student), 17)

    def test_a_register_resent_after_the_teacher_can_no_longer_take_it_is_already_saved(self):
        for host, school, teacher, child, group, term in (
            (HOST, self.stmarys, self.teacher, self.ada.pk, self.jss1a_id, self.term_id),
            (GRACE_HOST, self.grace, self.grace_teacher, self.grace_child.pk,
             self.grace_group_id, self.grace_term_id),
        ):
            with self.subTest(school=school.name):
                key = uuid.uuid4()
                self.as_(teacher)
                first = self.take([child], key=key, group=group, term=term, host=host)
                self.assertEqual(first.status_code, 200, first.content)

                self.no_longer_marks(teacher)
                resent = self.take([child], key=key, group=group, term=term, host=host)

                self.assertEqual(resent.status_code, 200, resent.content)
                self.assertEqual(resent.json(), ALREADY_SAVED)
                self.assertEqual(
                    self.take([], group=group, term=term, host=host).status_code, 403
                )

    def test_somebody_elses_key_is_not_answered_before_authority(self):
        """The same request, the same key, another person: not their replay.

        A bursar sending it is refused as a bursar is — not told a teacher's
        write is saved. A principal, who may mark, meets the key's own rule.
        """
        for host, school, teacher, student, assessment_id, head, bursar in self.mark_cases():
            with self.subTest(school=school.name):
                key = uuid.uuid4()
                self.as_(teacher)
                self.save(student, 17, key=key, assessment_id=assessment_id, host=host)

                self.as_(bursar)
                self.assertEqual(
                    self.save(student, 17, key=key, assessment_id=assessment_id,
                              host=host).status_code,
                    403,
                )
                self.as_(head)
                self.assertEqual(
                    self.save(student, 17, key=key, assessment_id=assessment_id,
                              host=host).status_code,
                    422,
                )

    def test_a_different_write_under_the_key_is_not_answered_before_authority(self):
        for host, school, teacher, student, assessment_id, _, _ in self.mark_cases():
            with self.subTest(school=school.name):
                key = uuid.uuid4()
                self.as_(teacher)
                self.save(student, 17, key=key, assessment_id=assessment_id, host=host)

                self.no_longer_marks(teacher)
                self.assertEqual(
                    self.save(student, 16, key=key, assessment_id=assessment_id,
                              host=host).status_code,
                    403,
                )


class AKeyIsOneWriteTests(ReplaySetUp):
    def test_a_key_used_for_a_different_mark_is_refused_and_writes_nothing(self):
        self.as_(self.teacher)
        key = uuid.uuid4()
        self.assertEqual(self.save(self.ada.pk, 17, key=key).status_code, 200)

        reused = self.save(self.emeka.pk, 12, key=key)

        self.assertEqual(reused.status_code, 422)
        self.assertIn("already used for a different write", reused.json()["detail"])
        with connected_to(self.stmarys):
            self.assertFalse(
                Score.objects.filter(student_membership_id=self.emeka.pk).exists()
            )

    def test_a_key_used_for_a_different_value_is_refused(self):
        self.as_(self.teacher)
        key = uuid.uuid4()
        self.save(self.ada.pk, 17, key=key)

        self.assertEqual(self.save(self.ada.pk, 16, key=key).status_code, 422)
        self.assertEqual(self.value_of(self.stmarys, self.first_ca_id, self.ada.pk), 17)

    def test_somebody_elses_key_is_not_their_replay(self):
        """The same request, sent by a different person, is not a replay.

        Answering it from the receipt would tell the principal their write
        landed when the teacher's did.
        """
        key = uuid.uuid4()
        self.as_(self.teacher)
        self.save(self.ada.pk, 17, key=key)

        self.as_(self.head)
        self.assertEqual(self.save(self.ada.pk, 17, key=key).status_code, 422)

    def test_a_key_used_for_a_different_register_is_refused(self):
        self.as_(self.teacher)
        key = uuid.uuid4()
        self.take([self.ada.pk], key=key)

        reused = self.take([self.emeka.pk], key=key)

        self.assertEqual(reused.status_code, 422)
        with connected_to(self.stmarys):
            self.assertEqual(
                AttendanceMark.objects.get(student_membership_id=self.emeka.pk).status,
                AttendanceStatus.PRESENT,
            )


class ARefusalLeavesNoReceiptTests(ReplaySetUp):
    """A refused write is judged again, because what refused it may have gone."""

    def test_a_refused_mark_leaves_no_receipt(self):
        self.as_(self.teacher)
        refused = self.save(self.ada.pk, 25, key=uuid.uuid4())

        self.assertEqual(refused.status_code, 422)
        self.assertEqual(self.receipts_at(self.stmarys), 0)

    def test_a_conflict_sent_again_after_the_teacher_reloads_is_judged_again(self):
        """A 409 is not the write's answer for ever.

        The same key, with the same body, after the conflicting mark is cleared:
        the first attempt's refusal left nothing behind, so this one lands.
        """
        self.as_(self.head)
        theirs = self.save(self.ada.pk, 15)

        self.as_(self.teacher)
        key = uuid.uuid4()
        self.assertEqual(self.save(self.ada.pk, 17, key=key).status_code, 409)

        self.as_(self.head)
        self.client.delete(
            f"/api/gradebook/assessments/{self.first_ca_id}/scores/{self.ada.pk}/"
            f"?expected_version={theirs.json()['version']}",
            HTTP_HOST=HOST,
        )

        self.as_(self.teacher)
        self.assertEqual(self.save(self.ada.pk, 17, key=key).status_code, 200)
        self.assertEqual(self.value_of(self.stmarys, self.first_ca_id, self.ada.pk), 17)

    def test_a_refused_register_leaves_no_receipt(self):
        self.as_(self.teacher)
        with connected_to(self.stmarys):
            empty = ClassGroup.objects.create(name="JSS 2A", level=2)

        refused = self.take([], key=uuid.uuid4(), group=empty.pk)

        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.receipts_at(self.stmarys), 0)


class AKeyIsOneSchoolsFactTests(ReplaySetUp):
    def test_a_key_is_one_schools_fact(self):
        """The same key at two schools is two writes, and neither sees the other.

        A device should never send one key to two hosts (requirement 6), so this
        is not about a device doing so. It is about where the receipt lives: in
        a table every school shares, Grace's request would find St Mary's
        receipt, and her teacher would be refused for a write she never made.
        """
        key = uuid.uuid4()
        self.as_(self.teacher)
        self.assertEqual(self.save(self.ada.pk, 17, key=key).status_code, 200)

        self.as_(self.grace_teacher)
        at_grace = self.save(
            self.grace_child.pk, 17, key=key, assessment_id=self.grace_ca_id,
            host=GRACE_HOST,
        )

        self.assertEqual(at_grace.status_code, 200, at_grace.content)
        self.assertEqual(
            self.value_of(self.grace, self.grace_ca_id, self.grace_child.pk), 17
        )
        self.assertEqual(self.receipts_at(self.stmarys), 1)
        self.assertEqual(self.receipts_at(self.grace), 1)


class TheIndexIsTheMechanismTests(RefusalAssertions, ReplaySetUp):
    def test_a_second_receipt_for_one_key_is_refused_by_the_database(self):
        key = uuid.uuid4()
        with connected_to(self.stmarys):
            SyncReceipt.objects.create(
                key=key, made_by_id=1, write="PUT /a/", request={}
            )
            with self.assertRefusedBy("a_queued_write_lands_once"):
                SyncReceipt.objects.create(
                    key=key, made_by_id=1, write="PUT /a/", request={}
                )
