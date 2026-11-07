"""Running a sitting: the test code, opening and closing by hand, extra time, retakes and
the sitting log. `docs/cbt.md`, "The administrator", "Extra time" and "Integrity".

Who may do which is `cbt.access` (`runs_sitting()`, `gives_extra_time()`,
`grants_retake()`, `reads_sitting_log()`), asked here before any row of the test's sitting
is read, and asked again by the routes. Each act writes a row that cannot be edited
(migration 0003), with who did it, as which role, when, and the reason where one is owed.

**The sitting log has no answer in it.** Per student: their class and admission number,
the attempt, when it started and closed, the deadline and any extra time, and the events
(computers, disconnects, leaving the page, late answers refused), but never an item, an
option chosen or a score. The administrator reads exactly this; a teacher's screen with
the answers is step 5's (screen 7).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from academics.models import ClassGroup, ClassPlacement
from accounts.models import Membership, Role

from . import access, sitting
from .banks import NotYours, Refused, name_of, plain
from .models import (
    MAX_EXTRA_MINUTES,
    MAX_REASON,
    Attempt,
    AttemptEvent,
    AttemptSession,
    RetakeGrant,
    SittingControl,
    Test,
    TestAudience,
    TestCodeChange,
    TimeExtension,
)


class NotAllowed(Exception):
    """Not this login's to do. The message says whose it is."""


_NO_TEST = "There is no such test of yours here."


def _role_word(actor, school, test) -> str:
    roles = set(actor.roles_at(school))
    if Role.PRINCIPAL.value in roles:
        return "principal"
    if Role.ADMIN.value in roles:
        return "administrator"
    if access.teaches_test(actor, school, test):
        return "teacher"
    if access.is_exam_officer(actor, school):
        return "exam officer"
    if Role.VICE_PRINCIPAL_ACADEMIC.value in roles:
        return "vice principal"
    return "staff"


def _test(actor, school, test_id, allowed, refusal, *, lock=False) -> Test:
    """The test, once `allowed(actor, school, test)` says yes. 'No such test' and 'not
    yours' read alike to anybody who may not open the Tests page."""
    if not access.may_open_tests(actor, school):
        raise NotYours(_NO_TEST)
    rows = Test.objects.select_related("term")
    if lock:
        rows = rows.select_for_update()
    test = rows.filter(pk=test_id).first()
    if test is None:
        raise NotYours(_NO_TEST)
    if not allowed(actor, school, test):
        raise NotAllowed(refusal)
    return test


def _reason(text) -> str:
    return plain(text, limit=MAX_REASON, what="The reason", lines=False)


# -- the test code -------------------------------------------------------------------


def set_code_as(actor, school, test_id, *, code=None) -> str:
    """A new test code for an approved test, shown once: the digest replaces the old one.

    `code` is for the demo seeds only; no route passes it. A student already sitting is
    not signed out; one who must sign in again needs the new code.
    """
    with transaction.atomic():
        test = _test(
            actor, school, test_id, access.runs_sitting,
            "A test's code is set by its teachers, the principal or the administrator.", lock=True,
        )
        if test.state != Test.State.PUBLISHED:
            raise Refused("A test code is set once the test is approved.")
        taken = set(
            Test.objects.exclude(pk=test.pk).exclude(code_digest="").values_list("code_digest", flat=True)
        )
        for _ in range(20):
            chosen = sitting.typed_code(code) if code else sitting.new_code()
            digest = sitting.code_digest(school.pk, chosen)
            if digest not in taken:
                break
            if code:
                raise Refused("That code is another test's.")
        else:  # pragma: no cover - 22^6 codes
            raise Refused("No free code was found. Try again.")
        kind = "changed" if test.code_digest else "set"
        test.code_digest = digest
        test.save(update_fields=["code_digest", "updated_at"])
        TestCodeChange.objects.create(
            test=test, kind=kind, by_id=actor.pk, by_name=name_of(actor), role=_role_word(actor, school, test)
        )
    return chosen


# -- opening and closing by hand ------------------------------------------------------------


def control_as(actor, school, test_id, class_group_id, kind, reason, *, end_attempts=False) -> SittingControl:
    """Open or close one class's sitting by hand, with a reason. Closing with
    `end_attempts` ends every attempt of that class in progress now, each logged."""
    reason = _reason(reason)
    if kind not in (SittingControl.Kind.OPENED, SittingControl.Kind.CLOSED):
        raise Refused("A sitting is opened or closed.")
    with transaction.atomic():
        test = _test(
            actor, school, test_id, access.runs_sitting,
            "A sitting is opened and closed by the test's teachers, the principal or the administrator.", lock=True,
        )
        if test.state != Test.State.PUBLISHED:
            raise Refused("Only an approved test is sat.")
        if not TestAudience.objects.filter(test=test, class_group_id=class_group_id).exists():
            raise Refused("That class does not sit this test.")
        group = ClassGroup.objects.get(pk=class_group_id)
        row = SittingControl.objects.create(
            test=test, class_group=group, class_group_name=group.name, kind=kind,
            end_attempts=bool(end_attempts) and kind == SittingControl.Kind.CLOSED, reason=reason,
            by_id=actor.pk, by_name=name_of(actor), role=_role_word(actor, school, test),
        )
        if row.end_attempts:
            now = timezone.now()
            for attempt in Attempt.objects.select_for_update().filter(
                test=test, class_group=group, submitted_at__isnull=True
            ):
                if not sitting.settle(attempt, test, now):
                    sitting.close(
                        attempt, Attempt.EndedBy.TEACHER, at=now, detail={"by": row.by_name, "reason": reason}
                    )
    return row


# -- extra time and retakes ------------------------------------------------------------------


def _student_of(school, test, student_id):
    student = Membership.objects.filter(school=school, role=Role.STUDENT, pk=student_id).select_related("user").first()
    if student is None:
        raise Refused("That student does not sit this test.")
    placed = ClassPlacement.objects.filter(
        term_id=test.term_id, student_membership_id=student.pk,
        class_group_id__in=TestAudience.objects.filter(test=test).values("class_group_id"),
    ).exists()
    if not placed and not Attempt.objects.filter(test=test, student_membership_id=student.pk).exists():
        raise Refused("That student does not sit this test.")
    return student


def extend_as(actor, school, test_id, student_id, minutes, reason) -> TimeExtension:
    """Extra minutes for one student, before they start or while they sit."""
    reason = _reason(reason)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise Refused("Extra time is a whole number of minutes.")
    if not 1 <= minutes <= MAX_EXTRA_MINUTES:
        raise Refused(f"Extra time is 1 to {MAX_EXTRA_MINUTES} minutes.")
    with transaction.atomic():
        test = _test(
            actor, school, test_id, access.gives_extra_time,
            "Extra time is given by the test's teachers, an exam officer or the administrator.", lock=True,
        )
        if test.state != Test.State.PUBLISHED:
            raise Refused("Extra time is given on an approved test.")
        student = _student_of(school, test, student_id)
        latest = (
            Attempt.objects.select_for_update()
            .filter(test=test, student_membership_id=student.pk)
            .order_by("-number")
            .first()
        )
        now = timezone.now()
        if latest is not None and sitting.settle(latest, test, now):
            nxt = sitting._next_number(test, student.pk)
            if nxt is None or nxt == latest.number:
                raise Refused(
                    f"{latest.student_name}'s attempt is closed, so extra time cannot reach it. Allow a retake instead."
                )
            number, attempt = nxt, None
        else:
            number, attempt = (latest.number, latest) if latest is not None else (1, None)
        row = TimeExtension.objects.create(
            test=test, student_membership_id=student.pk, student_name=sitting.name_of(student), number=number,
            attempt=attempt, minutes=minutes, reason=reason, by_id=actor.pk, by_name=name_of(actor),
            role=_role_word(actor, school, test),
        )
        AttemptEvent.objects.create(
            test=test, student_membership_id=student.pk, attempt=attempt, kind=AttemptEvent.Kind.EXTRA_TIME,
            at=now, detail={"minutes": minutes, "reason": reason, "by": row.by_name, "role": row.role, "number": number},
        )
    return row


def retake_as(actor, school, test_id, student_id, reason) -> RetakeGrant:
    """Allow one student to sit again, once their attempt is closed."""
    reason = _reason(reason)
    with transaction.atomic():
        test = _test(
            actor, school, test_id, access.grants_retake,
            "A retake is allowed by the test's teachers or an exam officer.", lock=True,
        )
        if test.state != Test.State.PUBLISHED:
            raise Refused("A retake is of an approved test.")
        student = _student_of(school, test, student_id)
        latest = (
            Attempt.objects.select_for_update()
            .filter(test=test, student_membership_id=student.pk)
            .order_by("-number")
            .first()
        )
        if latest is None:
            raise Refused("They have not sat it yet, so there is nothing to retake.")
        if not sitting.settle(latest, test):
            raise Refused(f"{latest.student_name} is still sitting it. Give extra time instead, if it is time they need.")
        number = latest.number + 1
        if RetakeGrant.objects.filter(test=test, student_membership_id=student.pk, number=number).exists():
            raise Refused(f"{latest.student_name} may already sit it again.")
        row = RetakeGrant.objects.create(
            test=test, student_membership_id=student.pk, student_name=latest.student_name, number=number,
            reason=reason, by_id=actor.pk, by_name=name_of(actor), role=_role_word(actor, school, test),
        )
        AttemptEvent.objects.create(
            test=test, student_membership_id=student.pk, attempt=latest, kind=AttemptEvent.Kind.RETAKE,
            at=timezone.now(), detail={"reason": reason, "by": row.by_name, "role": row.role, "number": number},
        )
    return row


# -- the sitting log --------------------------------------------------------------------------


@dataclass
class Row:
    """One student's line of the sitting log. No answer, item, option or score."""

    student_id: int
    name: str
    admission_number: str
    class_name: str
    state: str
    number: int = 0
    started_at: Optional[str] = None
    deadline: Optional[str] = None
    submitted_at: Optional[str] = None
    ended_by: str = ""
    extra_minutes: int = 0
    computers: int = 0
    replaced: int = 0
    disconnects: int = 0
    left_page: int = 0
    late_refused: int = 0
    answers_received: int = 0
    may_retake: bool = False
    events: List[dict] = field(default_factory=list)


@dataclass
class Log:
    test: Test
    classes: List[dict]
    rows: List[Row]
    may_run: bool
    may_extend: bool
    may_retake: bool
    code_set: bool
    code_changes: List[dict]
    controls: List[dict]


def _iso(at):
    return at.isoformat() if at else None


def sitting_log_as(actor, school, test_id) -> Log:
    """The sitting log for this test, and what this login may do with it."""
    with transaction.atomic():
        test = _test(
            actor, school, test_id, access.reads_sitting_log,
            "The sitting log is read by the test's teachers, the principal, the vice principal, "
            "an exam officer and the administrator.",
        )
        now = timezone.now()
        if test.state == Test.State.PUBLISHED:
            sitting.settle_all(test, now)
    audience = list(TestAudience.objects.filter(test=test).select_related("class_group"))
    group_names = {a.class_group_id: a.class_group.name for a in audience}
    classes = []
    for a in audience:
        latest = SittingControl.objects.filter(test=test, class_group_id=a.class_group_id).order_by("-id").first()
        classes.append(
            {
                "id": a.class_group_id,
                "name": a.class_group.name,
                "open": sitting.sitting_open(test, a.class_group_id, now),
                "by_hand": latest is not None,
                "said": (
                    f"{latest.get_kind_display()} by hand by {latest.by_name}, {timezone.localtime(latest.at):%-d %b %H:%M}: {latest.reason}"
                    if latest
                    else "As planned"
                ),
            }
        )
    placements = dict(
        ClassPlacement.objects.filter(term_id=test.term_id, class_group_id__in=list(group_names)).values_list(
            "student_membership_id", "class_group_id"
        )
    )
    attempts = list(Attempt.objects.filter(test=test).order_by("student_membership_id", "number"))
    latest_attempt = {}
    for a in attempts:
        latest_attempt[a.student_membership_id] = a
    ids = set(placements) | set(latest_attempt)
    students = {
        m.pk: m
        for m in Membership.objects.filter(school=school, role=Role.STUDENT, pk__in=ids).select_related("user")
    }
    extras = defaultdict(int)
    for sid, number, minutes in TimeExtension.objects.filter(test=test).values_list(
        "student_membership_id", "number", "minutes"
    ):
        extras[(sid, number)] += minutes
    events = defaultdict(list)
    for e in AttemptEvent.objects.filter(test=test).select_related("session").order_by("at", "id"):
        events[e.student_membership_id].append(e)
    computers = Counter(
        AttemptSession.objects.filter(attempt__test=test).values_list("attempt_id", flat=True)
    )
    received = Counter()
    if attempts:
        for a in attempts:
            received[a.pk] = sum(1 for v in sitting.counted_answers(a).values() if v is not None)
    may_retake = access.grants_retake(actor, school, test)
    rows = []
    for sid in ids:
        member = students.get(sid)
        attempt = latest_attempt.get(sid)
        name = attempt.student_name if attempt else sitting.name_of(member) if member else "A student who has left"
        number_typed = attempt.admission_number if attempt else " ".join((member.reference or "").split()) if member else ""
        class_name = attempt.class_group_name if attempt else group_names.get(placements.get(sid), "")
        if attempt is None:
            state = "Not started"
        elif attempt.is_open:
            state = "Sitting"
        else:
            state = Attempt.EndedBy(attempt.ended_by).label
        mine = [e for e in events[sid] if attempt is None or e.attempt_id in (None, attempt.pk) or e.kind in ("extra_time", "retake")]
        row = Row(
            student_id=sid, name=name, admission_number=number_typed, class_name=class_name, state=state,
        )
        if attempt is not None:
            extra = extras[(sid, attempt.number)]
            counts = Counter(e.kind for e in events[sid] if e.attempt_id == attempt.pk)
            row.number = attempt.number
            row.started_at = _iso(attempt.started_at)
            row.deadline = _iso(sitting.deadline_of(attempt, extra))
            row.submitted_at = _iso(attempt.submitted_at)
            row.ended_by = attempt.ended_by
            row.extra_minutes = extra
            row.computers = computers[attempt.pk]
            row.replaced = counts["replaced"]
            row.disconnects = counts["disconnect"]
            row.left_page = counts["left_page"]
            row.late_refused = sum((e.detail or {}).get("count", 1) for e in events[sid] if e.attempt_id == attempt.pk and e.kind == "late_refused")
            row.answers_received = received[attempt.pk]
            row.may_retake = may_retake and not attempt.is_open and not RetakeGrant.objects.filter(
                test=test, student_membership_id=sid, number=attempt.number + 1
            ).exists()
        else:
            row.extra_minutes = extras[(sid, 1)]
        row.events = [_event_out(e) for e in mine]
        rows.append(row)
    rows.sort(key=lambda r: (r.class_name, r.name.casefold(), r.student_id))
    return Log(
        test=test,
        classes=classes,
        rows=rows,
        may_run=access.runs_sitting(actor, school, test),
        may_extend=access.gives_extra_time(actor, school, test),
        may_retake=may_retake,
        code_set=bool(test.code_digest),
        code_changes=[
            {"what": f"Code {c.kind}", "by": c.by_name, "role": c.role, "at": _iso(c.at)}
            for c in TestCodeChange.objects.filter(test=test).order_by("at", "id")
        ],
        controls=[
            {"class_name": c.class_group_name, "kind": c.kind, "reason": c.reason, "by": c.by_name, "role": c.role,
             "end_attempts": c.end_attempts, "at": _iso(c.at)}
            for c in SittingControl.objects.filter(test=test).order_by("at", "id")
        ],
    )


#: What the log may say of an event's detail: never an item, an option or a score.
_SAFE_DETAIL = ("seat", "from_seat", "to_seat", "seconds", "until", "count", "minutes", "reason", "by", "role", "number")


def _event_out(e) -> dict:
    detail = {k: v for k, v in (e.detail or {}).items() if k in _SAFE_DETAIL}
    return {
        "kind": e.kind,
        "what": AttemptEvent.Kind(e.kind).label,
        "said_by": e.said_by,
        "at": _iso(e.at),
        "seat": e.session.seat if e.session_id else "",
        "detail": detail,
    }


__all__ = ["Log", "NotAllowed", "Row", "control_as", "extend_as", "retake_as", "set_code_as", "sitting_log_as"]
