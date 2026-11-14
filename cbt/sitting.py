"""A student sits a test: the door, the attempt, its answers and its clock.

`docs/cbt.md`, "Student sign-in", "Sitting", "Offline" and "Power cuts and resuming". The
routes are `cbt.sit_views`, under `/sit/` on the school's own host. Staff's side (codes,
opening and closing sittings, extra time, retakes, the sitting log) is `cbt.sittings`.

## The door

`door()` takes the test code, the admission number and the exam PIN. **Every failure of
those three is one refusal** (`NotOpened`, one sentence): an unknown code, another
school's code, a test that is not approved, an unknown number, a wrong PIN, somebody
else's PIN, a student not in the test's classes. Only once the three are proved does the
door say anything else: that the sitting is not open to their class now, or that they
have sat it already.

**The PIN is asked of every test whose scores can go anywhere** (audit F-08,
`needs_pin()`): one that can send to CA or be released. A test with the PIN off is a
practice test: its scores never reach a CA column (`cbt.ca`) and are never released to a
student's or a parent's page (`cbt.release`), so knowing a classmate's admission number
opens nothing that is kept.

**Wrong tries wait on the device and the address, never on the student** (audit F-09).
Each failure is counted against the computer that made it (`device`: a random id the
`/sit/` page gives each browser in a cookie, `sit_views.DEVICE_COOKIE`) and against its
address, in `accounts.throttling`'s buckets, and while either wait lasts nothing is
checked from **that computer or that address**, the right answer included. Nothing is
counted against the admission number typed: a classmate who types someone else's number
ten times makes their own computer wait, and the student whose number it is signs in
from theirs as if nothing had happened. The device's bucket is
`SignInScope.SIT_NUMBER`'s row (named for the key it had before, and still holding
`SIT_MAX_FAILURES_PER_ADMISSION_NUMBER`, ten); the address's is `SIT_ADDRESS` (a hundred,
because a computer room shares one address). A correct sign-in clears neither, so it is
no reset button for whoever guesses.

A proved door answers "Is this you?" with the student's name, class and admission
number, and a **ticket**: signed, for this test and student, good for ten minutes. The
clock has not started. `start()` with the ticket starts it (or resumes an attempt in
progress); `not_me()` with it writes `not_me` and starts nothing.

## The attempt and the computer that holds it

`start()` writes the `Attempt` with the **server's** time and a deadline, and an
`AttemptSession` for this computer, whose token the route sets as a cookie scoped to
`/sit/`. Signing in again (a power cut, another seat) finds the open attempt, ends the
other computer's session (`replaced`) and continues: the deadline has not moved. Only one
session is open per attempt (the database's `one_computer_holds_an_attempt`).

The paper is `paper.for_device()` from the attempt's seed: the same order on every
computer, **no key and no explanation**, with the answers the school holds and the
deadline and the server's `now`, from which the device counts down on its own monotonic
clock.

## Answers

`sync()` takes a batch from the device's outbox. Each answer carries the device's
sequence number, the item, the original option index (or none, cleared) and when it was
chosen in the server's time as the device estimates it. `(session, client_seq)` makes a
resend harmless.

**Whether an answer is in time is the server's question, asked of the server's record**
(audit F-07), never of the device's clock. The server keeps, per computer, the sequence
of its contacts (`AttemptSession.last_seen_at`, moved on every sync, whether or not
that computer still holds the attempt). An answer is accepted only if:

- it arrives by `deadline + late_window` (the documented late window: 0 to 5 minutes);
  later than that the attempt is closed and the answer refused; and
- if it arrives after the deadline, it comes in **that computer's first contact since
  the deadline** (`in_first_contact_after_time()`). That is the answer a computer cut off
  through the deadline was holding when it came back. A computer the server has already
  heard from since the deadline had the deadline in hand: every answer it sends after
  that was chosen after time ran out, whatever its `chosen_at` says, and is refused
  (`after_time`). `TIE_SECONDS` of slack after the deadline let an answer chosen in the
  last second, while a heartbeat was crossing the deadline, still go with the submit;
- and the device does not itself say it was chosen after the deadline.

So the device's estimate of the time can only ever count against an answer, never for
it. A refused answer is kept, counts for nothing, and is logged (`late_refused`, with
each reason counted). The honest limit, as `docs/cbt.md` says: an answer chosen after the
deadline on a computer that was offline through it, and delivered by its first contact
inside the late window, cannot be told from one chosen just before; the window is the
most that buys.

Of two accepted answers to one item **the one chosen later counts**; within one computer
the later sequence number decides, and between two computers whose choices are within
`TIE_SECONDS` of each other, the later arrival. Nothing is ever updated: each row names
the row it replaced or lost to.

## The clock

The server closes an attempt at `deadline + late_window` whatever the device does:
`settle()` is asked on every read and write that touches it.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional

from django.conf import settings
from django.core import signing
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from academics.models import ClassGroup, ClassPlacement
from accounts import throttling
from accounts.models import Membership, Role, SignInScope

from . import paper, pins
from .models import (
    AnswerEvent,
    Attempt,
    AttemptEvent,
    AttemptSession,
    RetakeGrant,
    SittingControl,
    Test,
    TestAudience,
    TestItem,
    TimeExtension,
)

Kind = AttemptEvent.Kind

#: Six letters a teacher reads out. No I, L, O or U, which are read as 1, 0 and V.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 6

#: How long a proved door is good for before the student presses Start.
TICKET_SECONDS = 10 * 60
#: Two computers' choices closer than this are settled by which arrived later
#: (`docs/cbt.md`, "Honest limits": their clocks agree to a second or two).
TIE_SECONDS = 2
#: A heartbeat comes every 20 seconds; a gap longer than this is a disconnect.
GAP_SECONDS = 60
#: The most answers or events one sync carries.
MAX_BATCH = 500

#: The one refusal, for every failure of the code, the number and the PIN.
NOT_OPENED = (
    "That test code, admission number and PIN do not open a test here. "
    "Check all three against your slip and the code on the board, and try again."
)
WAIT = "Too many wrong tries. Wait a few minutes and try again. Nothing has been locked."
NOT_OPEN_NOW = "This test is not open to your class now. Ask your teacher when it opens."
ALREADY_SAT = "You have already sat this test. Ask your teacher if you should sit it again."
TICKET_OLD = "Signing in took too long. Type the test code, your admission number and PIN again."
NOT_FROM_A_PARENT = (
    "Tests are sat with the student's exam slip, not from a parent's sign-in. "
    "Sign out of the parent's account on this device first."
)


class SitError(Exception):
    """A refusal from this module, carrying the sentence to show."""


class NotOpened(SitError):
    def __init__(self):
        super().__init__(NOT_OPENED)


class TooManyAttempts(SitError):
    def __init__(self, retry_after: int):
        super().__init__(WAIT)
        self.retry_after = retry_after


class Closed(SitError):
    """Proved, and the school says no: not open now, or sat already."""


class Replaced(SitError):
    """This computer's session was ended because another signed in."""

    def __init__(self):
        super().__init__(
            "This test has been opened on another computer, so it has stopped here. "
            "Carry on there. Nothing you chose here is lost."
        )


class NoSession(SitError):
    """No `/sit/` cookie, or one that names no session here."""

    def __init__(self):
        super().__init__("You are not signed in to a test on this computer. Sign in with your slip.")


# -- codes and tokens ---------------------------------------------------------------


def typed_code(typed) -> str:
    """The code as a student types it: letters only, capitals, spaces and dashes dropped."""
    return "".join(ch for ch in (typed or "").upper() if ch.isalnum())


def code_digest(school_id: int, code: str) -> str:
    """The keyed digest a test code is kept as, bound to the school: one school's code is
    a different digest at another, so a code opens nothing there (`EXAM_PIN_KEY`)."""
    message = f"classnode.test-code:{school_id}:{typed_code(code)}"
    return hmac.new(settings.EXAM_PIN_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def token_digest(token: str) -> str:
    return hashlib.sha256(f"classnode.sit-session:{token}".encode()).hexdigest()


def _here(school) -> bool:
    return school is not None and connection.schema_name == school.schema_name


# -- the clock ----------------------------------------------------------------------


def extra_minutes(attempt) -> int:
    return (
        TimeExtension.objects.filter(
            test_id=attempt.test_id, student_membership_id=attempt.student_membership_id, number=attempt.number
        ).aggregate(n=Sum("minutes"))["n"]
        or 0
    )


def deadline_of(attempt, extra=None) -> datetime:
    """The attempt's deadline: its base, plus every minute of extra time given it."""
    return attempt.base_deadline + timedelta(minutes=extra_minutes(attempt) if extra is None else extra)


def closes_for_good_at(attempt, test=None, extra=None) -> datetime:
    """When the server closes it whatever the device does: deadline plus the late window."""
    test = test or attempt.test
    return deadline_of(attempt, extra) + timedelta(minutes=test.late_window)


def _end_sessions(attempt, why, at):
    AttemptSession.objects.filter(attempt=attempt, ended_at__isnull=True).update(ended_at=at, ended_by=why)


def close(attempt, ended_by, *, at=None, said_by=AttemptEvent.SaidBy.SERVER, detail=None):
    """Close an open attempt, once. The row must be locked by the caller."""
    at = at or timezone.now()
    kind = {Attempt.EndedBy.STUDENT: Kind.SUBMIT, Attempt.EndedBy.CLOCK: Kind.CLOCK_SUBMIT}.get(
        ended_by, Kind.TEACHER_SUBMIT
    )
    session_why = {
        Attempt.EndedBy.STUDENT: AttemptSession.EndedBy.SUBMIT,
        Attempt.EndedBy.CLOCK: AttemptSession.EndedBy.CLOCK,
    }.get(ended_by, AttemptSession.EndedBy.TEACHER)
    attempt.submitted_at = at
    attempt.ended_by = ended_by
    attempt.save(update_fields=["submitted_at", "ended_by"])
    _end_sessions(attempt, session_why, at)
    AttemptEvent.objects.create(
        test_id=attempt.test_id, student_membership_id=attempt.student_membership_id, attempt=attempt,
        kind=kind, said_by=said_by, at=at, detail=detail or {},
    )


def settle(attempt, test=None, now=None) -> bool:
    """Close the attempt if its time and late window are over. Locked by the caller. True if
    it is closed now."""
    if not attempt.is_open:
        return True
    now = now or timezone.now()
    ends = closes_for_good_at(attempt, test)
    if now >= ends:
        close(attempt, Attempt.EndedBy.CLOCK, at=ends)
        return True
    return False


def settle_all(test, now=None):
    """Close every attempt of this test whose time is over. For the sitting log's reads."""
    now = now or timezone.now()
    earliest = now - timedelta(minutes=test.late_window)
    for attempt in Attempt.objects.select_for_update().filter(
        test=test, submitted_at__isnull=True, base_deadline__lte=earliest
    ):
        settle(attempt, test, now)


# -- is a sitting open --------------------------------------------------------------


def sitting_open(test, class_group_id, now=None) -> bool:
    """May students of this class start now? A hand control, if any, decides; else the
    window. Only an approved test is ever open."""
    if test.state != Test.State.PUBLISHED:
        return False
    latest = (
        SittingControl.objects.filter(test=test, class_group_id=class_group_id).order_by("-id").first()
    )
    if latest is not None:
        return latest.kind == SittingControl.Kind.OPENED
    now = now or timezone.now()
    return test.opens_at <= now < test.closes_at


def class_of(test, student_id) -> Optional[ClassGroup]:
    """The class in the test's audience the student is placed in, in the test's term."""
    audience = TestAudience.objects.filter(test=test).values("class_group_id")
    placement = (
        ClassPlacement.objects.filter(term_id=test.term_id, student_membership_id=student_id, class_group_id__in=audience)
        .select_related("class_group")
        .first()
    )
    return placement.class_group if placement else None


# -- the door -----------------------------------------------------------------------


def _number(typed) -> str:
    return " ".join((typed or "").split())


#: The device's bucket. It is `SIT_NUMBER`'s row in `accounts.throttling` (and its limit,
#: `SIT_MAX_FAILURES_PER_ADMISSION_NUMBER`), which used to be keyed on the admission number
#: typed: audit F-09, a wait keyed on the number is a wait for the student whose number it
#: is. A device key never looks like a number (`_keys()`), so the two never share a row.
DEVICE_SCOPE = SignInScope.SIT_NUMBER
ADDRESS_SCOPE = SignInScope.SIT_ADDRESS


def _keys(school, device, address):
    """The device's and the address's keys, both bound to the school. A request with no
    device id (no cookie: not the page) shares one bucket per address."""
    device = device or f"none@{address}"
    return f"{school.pk}:device:{device}", f"{school.pk}:{address}"


def _wait(device_key, address_key) -> Optional[int]:
    waits = [
        w
        for w in (
            throttling.blocked_for(DEVICE_SCOPE, device_key),
            throttling.blocked_for(ADDRESS_SCOPE, address_key),
        )
        if w is not None
    ]
    return max(waits) if waits else None


def guarded(school, device, address):
    """The keys for one try at a door, or `TooManyAttempts` while this device or this
    address must wait. Never keyed on the number typed (audit F-09)."""
    device_key, address_key = _keys(school, device, address)
    wait = _wait(device_key, address_key)
    if wait is not None:
        raise TooManyAttempts(wait)
    return device_key, address_key


def count_a_wrong_try(device_key, address_key):
    throttling.record_failure(DEVICE_SCOPE, device_key)
    throttling.record_failure(ADDRESS_SCOPE, address_key)


def needs_pin(test) -> bool:
    """Does the door ask this test for the exam PIN? Yes for every test whose scores can
    go to CA or be released (audit F-08). Only a practice test, with the PIN off, opens on
    a number, and nothing it scores is kept anywhere a student or a parent reads."""
    return bool(test.require_pin or test.may_send_to_ca)


def is_practice(test) -> bool:
    """A test with the PIN off: its scores never go to CA or onto a released page."""
    return not needs_pin(test)


def name_of(membership) -> str:
    return membership.display_name or membership.user.full_name or membership.user.username


def _student_without_pin(school, number) -> Optional[Membership]:
    """Option A, a practice test only (`needs_pin()` false): the one student here with this
    number, or None."""
    found = list(
        Membership.objects.with_access()
        .filter(school=school, role=Role.STUDENT, reference__iexact=number)
        .select_related("user")[:2]
    )
    return found[0] if len(found) == 1 else None


def _proved(school, code, number, pin):
    """(test, student, class) for the three, or None for every failure alike."""
    code = typed_code(code)
    if len(code) != CODE_LENGTH or not number:
        return None
    test = Test.objects.filter(code_digest=code_digest(school.pk, code), state=Test.State.PUBLISHED).first()
    if test is None:
        return None
    if needs_pin(test):
        student = pins.check(school, test.term, number, pin)
    else:
        student = _student_without_pin(school, number)
    if student is None:
        return None
    group = class_of(test, student.pk)
    if group is None:
        return None
    return test, student, group


@dataclass
class Door:
    """A proved door: who, for which test, and the ticket that starts it."""

    ticket: str
    test: Test
    student: Membership
    class_group: ClassGroup
    resuming: bool
    minutes_left: Optional[int]


def _ticket(school, test, student):
    return signing.dumps({"sch": school.pk, "t": test.pk, "s": student.pk}, salt="cbt.sit.door", compress=True)


def _read_ticket(school, ticket):
    try:
        data = signing.loads(ticket or "", salt="cbt.sit.door", max_age=TICKET_SECONDS)
    except signing.BadSignature:
        raise Closed(TICKET_OLD)
    if data.get("sch") != school.pk:
        raise Closed(TICKET_OLD)
    return data


def _open_attempt(test, student_id):
    return Attempt.objects.filter(test=test, student_membership_id=student_id, submitted_at__isnull=True).first()


def _next_number(test, student_id) -> Optional[int]:
    """The attempt number this student may start, or None if they have sat it."""
    last = Attempt.objects.filter(test=test, student_membership_id=student_id).order_by("-number").first()
    if last is None:
        return 1
    if RetakeGrant.objects.filter(test=test, student_membership_id=student_id, number=last.number + 1).exists():
        return last.number + 1
    return None


def door(school, *, code, admission_number, pin, address, device="", now=None) -> Door:
    """The three, checked behind this device's and this address's throttle. See the module
    docstring."""
    if not _here(school):
        raise NotOpened()
    number = _number(admission_number)
    keys = guarded(school, device, address)
    proved = _proved(school, code, number, pin)
    if proved is None:
        count_a_wrong_try(*keys)
        raise NotOpened()
    test, student, group = proved
    now = now or timezone.now()
    with transaction.atomic():
        attempt = _open_attempt(test, student.pk)
        if attempt is not None:
            attempt = Attempt.objects.select_for_update().get(pk=attempt.pk)
            if settle(attempt, test, now):
                attempt = None
    if attempt is not None:
        left = max(0, int((deadline_of(attempt) - now).total_seconds() // 60))
        return Door(_ticket(school, test, student), test, student, group, True, left)
    if _next_number(test, student.pk) is None:
        raise Closed(ALREADY_SAT)
    if not sitting_open(test, group.pk, now):
        raise Closed(NOT_OPEN_NOW)
    return Door(_ticket(school, test, student), test, student, group, False, None)


def not_me(school, ticket):
    """"This is not me": written down, and nothing starts."""
    data = _read_ticket(school, ticket)
    test = Test.objects.filter(pk=data["t"]).first()
    if test is None:
        raise Closed(TICKET_OLD)
    AttemptEvent.objects.create(
        test=test, student_membership_id=data["s"], attempt=_open_attempt(test, data["s"]),
        kind=Kind.NOT_ME, said_by=AttemptEvent.SaidBy.SERVER, at=timezone.now(),
    )


# -- starting and resuming ------------------------------------------------------------


def _student(school, student_id) -> Optional[Membership]:
    return (
        Membership.objects.with_access()
        .filter(school=school, role=Role.STUDENT, pk=student_id)
        .select_related("user")
        .first()
    )


@dataclass
class Started:
    attempt: Attempt
    session: AttemptSession
    token: str
    resumed: bool


def start(school, ticket, *, seat="", sync_offset_ms=0, now=None) -> Started:
    """Start the attempt the ticket names, or resume the open one on this computer."""
    data = _read_ticket(school, ticket)
    with transaction.atomic():
        # One start at a time per test: two taps, or two computers at once, cannot both
        # make an attempt or both hold one.
        test = Test.objects.select_for_update().filter(pk=data["t"], state=Test.State.PUBLISHED).first()
        student = _student(school, data["s"])
        if test is None or student is None:
            raise Closed(TICKET_OLD)
        group = class_of(test, student.pk)
        if group is None:
            raise Closed(NOT_OPEN_NOW)
        now = now or timezone.now()
        attempt = Attempt.objects.select_for_update().filter(
            test=test, student_membership_id=student.pk, submitted_at__isnull=True
        ).first()
        if attempt is not None and settle(attempt, test, now):
            attempt = None
        resumed = attempt is not None
        if attempt is None:
            number = _next_number(test, student.pk)
            if number is None:
                raise Closed(ALREADY_SAT)
            if not sitting_open(test, group.pk, now):
                raise Closed(NOT_OPEN_NOW)
            planned = now + timedelta(minutes=test.duration)
            base = min(planned, test.closes_at) if now < test.closes_at else planned
            attempt = Attempt.objects.create(
                test=test, student_membership_id=student.pk, student_name=name_of(student),
                admission_number=_number(student.reference), class_group=group, class_group_name=group.name,
                number=number, seed=secrets.token_hex(8), started_at=now, base_deadline=base,
            )
        token = secrets.token_urlsafe(32)
        previous = AttemptSession.objects.filter(attempt=attempt, ended_at__isnull=True).first()
        if previous is not None:
            previous.ended_at = now
            previous.ended_by = AttemptSession.EndedBy.REPLACED
            previous.save(update_fields=["ended_at", "ended_by"])
        session = AttemptSession.objects.create(
            attempt=attempt, token_digest=token_digest(token), seat=(seat or "")[:80], signed_in_at=now,
            sync_offset_ms=max(-10**9, min(10**9, int(sync_offset_ms or 0))), last_seen_at=now,
        )
        common = dict(test=test, student_membership_id=student.pk, attempt=attempt, at=now)
        if previous is not None:
            AttemptEvent.objects.create(
                **common, session=session, kind=Kind.REPLACED,
                detail={"from_session": previous.pk, "from_seat": previous.seat, "to_session": session.pk, "to_seat": session.seat},
            )
        AttemptEvent.objects.create(
            **common, session=session, kind=Kind.RESUME if resumed else Kind.START,
            detail={"seat": session.seat, "number": attempt.number},
        )
    return Started(attempt, session, token, resumed)


# -- the session a cookie names --------------------------------------------------------


def session_for(school, token, *, lock=False):
    """The session this cookie's token names, and its attempt, or `NoSession`."""
    if not token or not _here(school):
        raise NoSession()
    rows = AttemptSession.objects.select_related("attempt", "attempt__test")
    session = rows.filter(token_digest=token_digest(token)).first()
    if session is None:
        raise NoSession()
    if lock:
        attempt = Attempt.objects.select_for_update().select_related("test").get(pk=session.attempt_id)
        session.attempt = attempt
    return session


def counted_answers(attempt) -> dict:
    """`item id -> chosen original index (or None, cleared)`: the answers that count.

    The accepted rows nobody superseded and that lost to nobody (see `AnswerEvent`).
    """
    rows = AnswerEvent.objects.filter(attempt=attempt, accepted=True, superseded_by__isnull=True).exclude(
        pk__in=AnswerEvent.objects.filter(attempt=attempt, supersedes__isnull=False).values("supersedes_id")
    )
    return {r.item_id: r.chosen for r in rows}


def _counted_row(attempt, item_id):
    return (
        AnswerEvent.objects.filter(attempt=attempt, item_id=item_id, accepted=True, superseded_by__isnull=True)
        .exclude(pk__in=AnswerEvent.objects.filter(attempt=attempt, supersedes__isnull=False).values("supersedes_id"))
        .first()
    )


def picture_url(key: str) -> str:
    return f"/sit/pictures/{key}/full.webp"


def paper_for(attempt) -> dict:
    """The paper this attempt's device is sent: `paper.for_device()` and nothing else."""
    items = list(TestItem.objects.filter(test_id=attempt.test_id))
    return paper.for_device(attempt.test, items, attempt.seed, image_url=picture_url)


def _iso(at) -> Optional[str]:
    return at.isoformat() if at else None


def state_of(session, now=None) -> dict:
    """What the device is told on every answer: the clock, and whether it still holds it."""
    attempt = session.attempt
    now = now or timezone.now()
    extra = extra_minutes(attempt)
    return {
        "now": _iso(now),
        "deadline": _iso(deadline_of(attempt, extra)),
        "late_window": attempt.test.late_window * 60,
        "extra_minutes": extra,
        "closed": not attempt.is_open,
        "submitted_at": _iso(attempt.submitted_at),
        "ended_by": attempt.ended_by,
        "replaced": session.ended_by == AttemptSession.EndedBy.REPLACED,
    }


def payload_for(session, *, student=None, now=None) -> dict:
    """Everything a device needs to show and resume the attempt. **No key.**"""
    attempt = session.attempt
    test = attempt.test
    answers = counted_answers(attempt)
    return {
        "attempt": {
            "id": attempt.pk,
            "number": attempt.number,
            "session": session.pk,
            "started_at": _iso(attempt.started_at),
        },
        "student": {
            "name": attempt.student_name,
            "admission_number": attempt.admission_number,
            "class_name": attempt.class_group_name,
        },
        "paper": paper_for(attempt),
        "answers": {str(k): v for k, v in answers.items()},
        **state_of(session, now),
        "test": {"id": test.pk, "title": test.title, "calculator": test.calculator},
    }


# -- answers ---------------------------------------------------------------------------


def _when(value, now) -> datetime:
    """A device's estimate of server time, as milliseconds since the epoch or ISO."""
    try:
        if isinstance(value, (int, float)):
            at = datetime.fromtimestamp(value / 1000, tz=dt_timezone.utc)
        else:
            at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if timezone.is_naive(at):
                at = timezone.make_aware(at, dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return now
    # A device cannot have chosen after the server received it.
    return min(at, now)


def _wins(new_session_id, new_seq, new_at, current) -> tuple:
    """(does the new answer win, was it settled as a tie)."""
    if current.session_id == new_session_id:
        return new_seq > current.client_seq, False
    if abs((new_at - current.chosen_at).total_seconds()) <= TIE_SECONDS:
        return True, True  # the later arrival, which is the new one
    return new_at > current.chosen_at, False


def in_first_contact_after_time(previous_contact, deadline) -> bool:
    """Is a contact the computer's first since the deadline, by the server's record?

    `previous_contact` is when the server last heard from this computer before this
    contact. If that was already past the deadline (and its `TIE_SECONDS` of slack), the
    computer has been told the time is up, and what it sends now was chosen after."""
    return previous_contact < deadline + timedelta(seconds=TIE_SECONDS)


def _record_answer(session, attempt, test, items, raw, now, deadline, previous_contact):
    """One answer from the outbox: (seq, refusal or '', whether it is new here)."""
    try:
        seq = int(raw.get("seq"))
        item_id = int(raw.get("item"))
    except (TypeError, ValueError, AttributeError):
        return None
    if seq < 0 or item_id not in items:
        return None
    existing = AnswerEvent.objects.filter(session=session, client_seq=seq).first()
    if existing is not None:
        return seq, existing.refusal, False
    chosen = raw.get("chosen")
    if chosen is not None:
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            return None
        if not 0 <= chosen < items[item_id]:
            return None
    chosen_at = _when(raw.get("chosen_at"), now)
    if not attempt.is_open:
        refusal = AnswerEvent.Refusal.AFTER_SUBMIT
    elif now > deadline + timedelta(minutes=test.late_window):
        refusal = AnswerEvent.Refusal.LATE
    elif now > deadline and not in_first_contact_after_time(previous_contact, deadline):
        # The server's record: this computer was heard from after time ran out, so this
        # answer was chosen after it, whatever the device says (audit F-07).
        refusal = AnswerEvent.Refusal.AFTER_TIME
    elif chosen_at > deadline:
        # The device's own word can only count against it.
        refusal = AnswerEvent.Refusal.AFTER_TIME
    else:
        refusal = AnswerEvent.Refusal.NONE
    fields = dict(
        attempt=attempt, session=session, item_id=item_id, chosen=chosen, client_seq=seq,
        chosen_at=chosen_at, received_at=now, accepted=refusal == "", refusal=refusal,
    )
    if refusal == "":
        current = _counted_row(attempt, item_id)
        if current is not None:
            won, tie = _wins(session.pk, seq, chosen_at, current)
            fields.update(tie=tie, **({"supersedes": current} if won else {"superseded_by": current}))
    AnswerEvent.objects.create(**fields)
    return seq, refusal, True


_DEVICE_KINDS = {"disconnect": Kind.DISCONNECT, "reconnect": Kind.RECONNECT, "left_page": Kind.LEFT_PAGE}


def _record_event(session, attempt, raw, now):
    try:
        seq = int(raw.get("seq"))
        kind = _DEVICE_KINDS[raw.get("kind")]
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    if AttemptEvent.objects.filter(session=session, said_by=AttemptEvent.SaidBy.DEVICE, detail__seq=seq).exists():
        return seq
    detail = {"seq": seq}
    if kind == Kind.LEFT_PAGE:
        try:
            detail["seconds"] = max(0, min(24 * 3600, int(raw.get("seconds") or 0)))
        except (TypeError, ValueError):
            pass
    if raw.get("until") is not None:
        detail["until"] = _when(raw.get("until"), now).isoformat()
    AttemptEvent.objects.create(
        test_id=attempt.test_id, student_membership_id=attempt.student_membership_id, attempt=attempt,
        session=session, kind=kind, said_by=AttemptEvent.SaidBy.DEVICE, at=_when(raw.get("at"), now), detail=detail,
    )
    return seq


def _heartbeat(session, attempt, now):
    """Note this contact. Answers when the server last heard from this computer before it.

    Every computer's contacts are kept in `last_seen_at`, a replaced one's too: the
    deadline rule asks it of whichever computer sends (audit F-07). A gap is logged only
    for the computer that holds the attempt."""
    previous = session.last_seen_at
    if session.is_open:
        gap = (now - previous).total_seconds()
        if gap > GAP_SECONDS:
            AttemptEvent.objects.create(
                test_id=attempt.test_id, student_membership_id=attempt.student_membership_id, attempt=attempt,
                session=session, kind=Kind.DISCONNECT, said_by=AttemptEvent.SaidBy.SERVER, at=previous,
                detail={"seconds": int(gap), "until": now.isoformat()},
            )
    if now > previous:
        AttemptSession.objects.filter(pk=session.pk).update(last_seen_at=now)
    return previous


def _sync_locked(session, answers, events, now):
    attempt = session.attempt
    test = attempt.test
    settle(attempt, test, now)
    previous_contact = _heartbeat(session, attempt, now)
    deadline = deadline_of(attempt)
    items = {i: len(o) for i, o in TestItem.objects.filter(test_id=test.pk).values_list("pk", "options")}
    acks, refused, why = [], [], {}
    for raw in sorted((answers or [])[:MAX_BATCH], key=lambda a: a.get("seq", 0) if isinstance(a, dict) else 0):
        if not isinstance(raw, dict):
            continue
        done = _record_answer(session, attempt, test, items, raw, now, deadline, previous_contact)
        if done is None:
            continue
        seq, refusal, new = done
        acks.append(seq)
        if refusal:
            refused.append({"seq": seq, "why": refusal})
            if new:
                why[refusal] = why.get(refusal, 0) + 1
    if why:
        AttemptEvent.objects.create(
            test_id=test.pk, student_membership_id=attempt.student_membership_id, attempt=attempt, session=session,
            kind=Kind.LATE_REFUSED, said_by=AttemptEvent.SaidBy.SERVER, at=now,
            detail={"count": sum(why.values()), "why": why, "deadline": deadline.isoformat(),
                    "last_contact": previous_contact.isoformat()},
        )
    event_acks = [s for s in (_record_event(session, attempt, e, now) for e in (events or [])[:MAX_BATCH] if isinstance(e, dict)) if s is not None]
    session.refresh_from_db(fields=["ended_at", "ended_by"])
    return {"acks": acks, "refused": refused, "event_acks": event_acks, **state_of(session, now)}


def sync(school, token, *, answers=(), events=(), now=None) -> dict:
    """A batch from the device's outbox, and the heartbeat. Answers from a replaced computer
    are taken like any other, by their time."""
    with transaction.atomic():
        session = session_for(school, token, lock=True)
        return _sync_locked(session, list(answers or []), list(events or []), now or timezone.now())


def submit(school, token, *, answers=(), events=(), by_clock=False, now=None) -> dict:
    """The outbox, then the close. A replaced computer cannot submit: the other holds it."""
    now = now or timezone.now()
    with transaction.atomic():
        session = session_for(school, token, lock=True)
        out = _sync_locked(session, list(answers or []), list(events or []), now)
        attempt = session.attempt
        if attempt.is_open:
            if session.ended_by == AttemptSession.EndedBy.REPLACED:
                raise Replaced()
            close(
                attempt, Attempt.EndedBy.CLOCK if by_clock else Attempt.EndedBy.STUDENT, at=now,
                said_by=AttemptEvent.SaidBy.DEVICE if by_clock else AttemptEvent.SaidBy.SERVER,
            )
        session.refresh_from_db(fields=["ended_at", "ended_by"])
        counted = counted_answers(attempt)
        out.update(state_of(session, now))
        out["received"] = sum(1 for v in counted.values() if v is not None)
        out["questions"] = TestItem.objects.filter(test_id=attempt.test_id).count()
        return out


__all__ = [
    "ALREADY_SAT",
    "CODE_ALPHABET",
    "CODE_LENGTH",
    "Closed",
    "Door",
    "NOT_OPENED",
    "NOT_OPEN_NOW",
    "NoSession",
    "NotOpened",
    "Replaced",
    "count_a_wrong_try",
    "guarded",
    "in_first_contact_after_time",
    "is_practice",
    "needs_pin",
    "SitError",
    "Started",
    "TooManyAttempts",
    "WAIT",
    "class_of",
    "close",
    "closes_for_good_at",
    "code_digest",
    "counted_answers",
    "deadline_of",
    "door",
    "extra_minutes",
    "new_code",
    "not_me",
    "paper_for",
    "payload_for",
    "session_for",
    "settle",
    "settle_all",
    "sitting_open",
    "start",
    "state_of",
    "submit",
    "sync",
    "typed_code",
]
