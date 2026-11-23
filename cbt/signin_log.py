"""The staff attempt log: a sign-in at the exam door that did not get through, and why.

`docs/cbt.md`, "The staff attempt log". The student is told one sentence for the three
that did not prove (`sitting.NOT_OPENED`) and never which of them was wrong; the door's
answers are the same bytes as before this module existed. Staff are told the real
reason here, per student, on the sitting page (`sittings.sitting_log_as`). Nothing in
this module is read by `/sit/`.

## What is kept, and what never is

A `SignInRefusal` row names the test, the student, their admission number, the reason,
the time, six characters of a keyed hash of the browser's own id (`device_tag`) and, for
a lockout, when it ends. **Never kept: the PIN typed, the test code typed, an address.**

## Who it can be written against

Only a typed admission number that names exactly one student here. A number nobody has
writes nothing, so a stranger's typing leaves no row, and the table cannot be filled by
guessing numbers. Which test it is written against:

- the test the code typed opens, if it opens one (any state: a closed test's code says
  "not open", not "wrong code"); else
- **wrong code**, and **locked**: the approved tests that are open now to the class the
  student is placed in. A student with no open test writes nothing, because no sitting
  was waiting on them.

## The reason is the door's own first failing check

In the door's order: code, PIN, class, then (the door proved) already sat, then not
open. A PIN that is a live slip's of another term is told from a wrong one
(`other_term_slip`), because it is the one a slip printed after the term moved on looks
like. A locked device is not checked at all (the right answer waits too), so a lockout is
written against the student the number names and the tests open to them, with when it
ends, once per student, test and computer while a wait lasts.

## Bounded

Wrong tries are already counted per device and per address and then refused
(`sitting.guarded()`), so the rows written for them are bounded by that throttle. The two
that are not counted, a proved door that finds the test not open and one that finds it
sat, are written once per student, test, reason and computer in `REPEAT_SECONDS`.
"""

import hashlib
import hmac
from datetime import timedelta
from typing import List, Optional

from django.conf import settings

from academics.models import ClassPlacement
from accounts.models import Membership, Role

from . import pins, sitting
from .models import SignInRefusal, Test

Reason = SignInRefusal.Reason

#: A proved door that finds the sitting closed, pressed again and again before it opens, is
#: one line in this long, not one a press.
REPEAT_SECONDS = 120


def device_tag(device) -> str:
    """Six characters that say "the same computer again" and nothing else. Keyed, so the
    browser's own id cannot be got back, or looked for, from what staff read."""
    message = f"classnode.sit-device-tag:{device or 'none'}"
    return hmac.new(settings.EXAM_PIN_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()[:6]


def one_student(school, number) -> Optional[Membership]:
    """The one student here with this admission number, or None for none or for several."""
    number = " ".join((number or "").split())
    if not number:
        return None
    found = list(
        Membership.objects.with_access()
        .filter(school=school, role=Role.STUDENT, reference__iexact=number)
        .select_related("user")[:2]
    )
    return found[0] if len(found) == 1 else None


def open_tests_for(student, now) -> List[Test]:
    """The approved tests whose class sitting this student's class is open now."""
    placed = list(
        ClassPlacement.objects.filter(student_membership_id=student.pk).values_list("class_group_id", "term_id")
    )
    if not placed:
        return []
    tests = (
        Test.objects.filter(
            state=Test.State.PUBLISHED,
            term_id__in={t for _, t in placed},
            audience__class_group_id__in={g for g, _ in placed},
        )
        .distinct()
        .select_related("term")
        .order_by("id")
    )
    out = []
    for test in tests:
        group = sitting.class_of(test, student.pk)
        if group is not None and sitting.sitting_open(test, group.pk, now):
            out.append(test)
    return out


def _write(test, student, reason, *, device, now, until=None):
    return SignInRefusal.objects.create(
        test=test, student_membership_id=student.pk, student_name=sitting.name_of(student),
        admission_number=" ".join((student.reference or "").split()), reason=reason, until=until,
        device_tag=device_tag(device), at=now,
    )


def note_failed_try(school, *, code, number, pin, device, now):
    """A try that did not prove: write the first check that failed, if it can be written
    against a student and a test. Returns the rows written. Reads, writes nothing else, and
    changes nothing the student is told."""
    student = one_student(school, number)
    if student is None:
        return []
    typed = sitting.typed_code(code)
    test = None
    if len(typed) == sitting.CODE_LENGTH:
        test = Test.objects.filter(code_digest=sitting.code_digest(school.pk, typed)).select_related("term").first()
    if test is None:
        return [_write(t, student, Reason.WRONG_CODE, device=device, now=now) for t in open_tests_for(student, now)]
    if test.state != Test.State.PUBLISHED:
        return [_write(test, student, Reason.NOT_OPEN, device=device, now=now)]
    if sitting.needs_pin(test) and pins.check(school, test.term, number, pin) is None:
        other = pins.is_a_live_slip_of_another_term(school, test.term, student.pk, pin)
        return [_write(test, student, Reason.OTHER_TERM_SLIP if other else Reason.WRONG_PIN, device=device, now=now)]
    if sitting.class_of(test, student.pk) is None:
        return [_write(test, student, Reason.NOT_IN_CLASS, device=device, now=now)]
    return []


def note_closed(school, test, student, reason, *, device, now):
    """A proved door that finds the test not open to their class, or sat already."""
    again = SignInRefusal.objects.filter(
        test=test, student_membership_id=student.pk, reason=reason, device_tag=device_tag(device),
        at__gt=now - timedelta(seconds=REPEAT_SECONDS),
    ).exists()
    if again:
        return []
    return [_write(test, student, reason, device=device, now=now)]


def note_locked(school, *, number, retry_after, device, now):
    """A try made while this device or its address must wait. Nothing was checked, so it is
    written against the student the number names and the tests open to them, once for the
    wait."""
    student = one_student(school, number)
    if student is None:
        return []
    until = now + timedelta(seconds=int(retry_after))
    tag = device_tag(device)
    rows = []
    for test in open_tests_for(student, now):
        waiting = SignInRefusal.objects.filter(
            test=test, student_membership_id=student.pk, reason=Reason.LOCKED, device_tag=tag, until__gt=now
        ).exists()
        if not waiting:
            rows.append(_write(test, student, Reason.LOCKED, device=device, now=now, until=until))
    return rows


def out(row) -> dict:
    """One row as the sitting page reads it. No PIN, no code, no address, no device id."""
    return {
        "at": row.at.isoformat(),
        "reason": row.reason,
        "what": SignInRefusal.Reason(row.reason).label,
        "until": row.until.isoformat() if row.until else None,
        "device": row.device_tag,
    }


__all__ = ["REPEAT_SECONDS", "Reason", "device_tag", "note_closed", "note_failed_try", "note_locked", "one_student", "open_tests_for", "out"]
