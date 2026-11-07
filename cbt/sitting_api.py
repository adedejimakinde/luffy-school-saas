"""HTTP for running a sitting, on the Tests page: `/api/cbt/tests/{id}/...`.

`docs/cbt.md`, step 4. The test code, opening and closing one class's sitting by hand,
extra time and retakes per student, and the sitting log. `cbt.sittings` holds every rule
and asks who is asking before it reads a row; so does every route here.

The sitting log is served to the administrator as to a teacher: there is **no answer, no
item, no option chosen and no score in it** for anybody in this step (`docs/cbt.md`, "The
administrator"). A test's code is shown **once**, in the answer to the request that set
it, and kept only as a digest.
"""

from typing import List, Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth

from . import sittings
from .banks import NotYours, Refused
from .models import SittingControl

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class EventOut(Schema):
    kind: str
    what: str
    said_by: str
    at: Optional[str] = None
    seat: str = ""
    detail: dict


class RowOut(Schema):
    student_id: int
    name: str
    admission_number: str
    class_name: str
    state: str
    number: int
    started_at: Optional[str] = None
    deadline: Optional[str] = None
    submitted_at: Optional[str] = None
    ended_by: str
    extra_minutes: int
    computers: int
    replaced: int
    disconnects: int
    left_page: int
    late_refused: int
    answers_received: int
    may_retake: bool
    events: List[EventOut]


class ClassOut(Schema):
    id: int
    name: str
    open: bool
    by_hand: bool
    said: str


class LogOut(Schema):
    test_id: int
    title: str
    state: str
    opens_at: str
    closes_at: str
    duration: int
    late_window: int
    code_set: bool
    #: The new code, in the answer to the request that set it, and never again.
    code: Optional[str] = None
    may_run: bool
    may_extend: bool
    may_retake: bool
    classes: List[ClassOut]
    rows: List[RowOut]
    code_changes: List[dict]
    controls: List[dict]


class ControlIn(Schema):
    reason: str = ""
    end_attempts: bool = False


class ExtraIn(Schema):
    minutes: int = 0
    reason: str = ""


class ReasonIn(Schema):
    reason: str = ""


_OUT = {200: LogOut, 403: MessageOut, 404: MessageOut, 422: MessageOut}


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No tests on this host.")
    return school


def _log_out(log, code=None) -> LogOut:
    t = log.test
    return LogOut(
        test_id=t.pk,
        title=t.title,
        state=t.state,
        opens_at=t.opens_at.isoformat(),
        closes_at=t.closes_at.isoformat(),
        duration=t.duration,
        late_window=t.late_window,
        code_set=log.code_set,
        code=code,
        may_run=log.may_run,
        may_extend=log.may_extend,
        may_retake=log.may_retake,
        classes=[ClassOut(**c) for c in log.classes],
        rows=[RowOut(**r.__dict__) for r in log.rows],
        code_changes=log.code_changes,
        controls=log.controls,
    )


def _answer(request, test_id, act):
    school = _school_of(request)
    try:
        code = act(school)
        log = sittings.sitting_log_as(request.user, school, test_id)
    except NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except sittings.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _log_out(log, code if isinstance(code, str) else None)


@router.get("/tests/{int:test_id}/sitting/", response=_OUT)
def sitting_log(request, test_id: int):
    """The sitting log: who started, dropped off and submitted, and when. No answers."""
    return _answer(request, test_id, lambda school: None)


@router.post("/tests/{int:test_id}/code/", response=_OUT)
def set_code(request, test_id: int):
    """A new test code, shown once in this answer. The old one stops opening anything."""
    return _answer(request, test_id, lambda school: sittings.set_code_as(request.user, school, test_id))


@router.post("/tests/{int:test_id}/classes/{int:class_group_id}/open/", response=_OUT)
def open_sitting(request, test_id: int, class_group_id: int, payload: ControlIn):
    return _answer(
        request, test_id,
        lambda school: sittings.control_as(
            request.user, school, test_id, class_group_id, SittingControl.Kind.OPENED, payload.reason
        ),
    )


@router.post("/tests/{int:test_id}/classes/{int:class_group_id}/close/", response=_OUT)
def close_sitting(request, test_id: int, class_group_id: int, payload: ControlIn):
    return _answer(
        request, test_id,
        lambda school: sittings.control_as(
            request.user, school, test_id, class_group_id, SittingControl.Kind.CLOSED, payload.reason,
            end_attempts=payload.end_attempts,
        ),
    )


@router.post("/tests/{int:test_id}/students/{int:student_id}/extra-time/", response=_OUT)
def extra_time(request, test_id: int, student_id: int, payload: ExtraIn):
    return _answer(
        request, test_id,
        lambda school: sittings.extend_as(request.user, school, test_id, student_id, payload.minutes, payload.reason),
    )


@router.post("/tests/{int:test_id}/students/{int:student_id}/retake/", response=_OUT)
def retake(request, test_id: int, student_id: int, payload: ReasonIn):
    return _answer(
        request, test_id, lambda school: sittings.retake_as(request.user, school, test_id, student_id, payload.reason)
    )


__all__ = ["router"]
