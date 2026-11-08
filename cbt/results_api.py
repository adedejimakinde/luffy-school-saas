"""HTTP for marking, key corrections, sending to CA and release: `/api/cbt/...`.

`docs/cbt.md`, step 5. `cbt.marking`, `cbt.ca` and `cbt.release` hold every rule and ask
who is asking before they read a row; so does every route here. Mounted under
`/api/cbt/` beside the banks, tests and sittings.

- `GET tests/{id}/results/`: screen 7, with the answers and the item analysis, for the
  test's teachers, the principal and the vice principal; **the administrator's is the
  released scores alone**, with no item, no option and no key.
- `POST tests/{id}/items/{item}/key/`, `POST tests/{id}/close/`.
- `GET tests/{id}/ca/?assessment=&existing=` (the preview, which writes nothing) and
  `POST tests/{id}/ca/` (the send).
- `POST tests/{id}/classes/{class}/release/`, `POST releases/{id}/restore/`.
- `GET scores/`: a parent's own children's released scores, and nothing else.
"""

from typing import Dict, Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth

from . import ca, marking, release
from .banks import NotYours, Refused
from .sittings import NotAllowed

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class KeyIn(Schema):
    new_index: int = -1
    reason: str = ""


class SendIn(Schema):
    assessment_id: int = 0
    existing: str = ""
    shown: Dict[str, dict] = {}
    confirm_replace: bool = False


class ReasonIn(Schema):
    reason: str = ""


_OUT = {200: dict, 403: MessageOut, 404: MessageOut, 422: MessageOut}


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No tests on this host.")
    return school


def _answer(act):
    try:
        return 200, act()
    except NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except Refused as exc:
        return 422, MessageOut(detail=str(exc))


def results_out(r: marking.Results) -> dict:
    t = r.test
    return {
        "test_id": t.pk,
        "title": t.title,
        "subject": r.subject,
        "state": t.state,
        "state_label": t.get_state_display(),
        "closes_at": t.closes_at.isoformat(),
        "released_only": r.released_only,
        "out_of": r.out_of,
        "classes": r.classes,
        "rows": [row.__dict__ for row in r.rows],
        "stats": r.stats,
        "distribution": r.distribution,
        "items": r.items,
        "corrections": r.corrections,
        "transfers": r.transfers,
        "may_correct": r.may_correct,
        "may_send": r.may_send,
        "may_close": r.may_close,
        "may_restore": r.may_restore,
        "sends_to_ca": r.sends_to_ca,
        "open_attempts": r.open_attempts,
    }


def _results(request, test_id):
    return results_out(marking.results_as(request.user, _school_of(request), test_id))


@router.get("/tests/{int:test_id}/results/", response=_OUT)
def results(request, test_id: int):
    """Screen 7: each student's score, the item analysis, the releases and the sends."""
    return _answer(lambda: _results(request, test_id))


@router.post("/tests/{int:test_id}/items/{int:item_id}/key/", response=_OUT)
def correct_key(request, test_id: int, item_id: int, payload: KeyIn):
    """A wrong key put right: every attempt is marked again. Answers with the results."""
    def act():
        row = marking.correct_key_as(request.user, _school_of(request), test_id, item_id, payload.new_index, payload.reason)
        return {**_results(request, test_id), "corrected": marking._correction_out(row)}

    return _answer(act)


@router.post("/tests/{int:test_id}/close/", response=_OUT)
def close_test(request, test_id: int):
    def act():
        marking.close_test_as(request.user, _school_of(request), test_id)
        return _results(request, test_id)

    return _answer(act)


def _column_out(a) -> dict:
    return {"id": a.pk, "name": a.name, "max_score": a.max_score}


def preview_out(p: ca.Preview) -> dict:
    return {
        "test_id": p.test.pk,
        "title": p.test.title,
        "assessment": _column_out(p.assessment),
        "columns": [_column_out(c) for c in p.columns],
        "existing": p.existing,
        "out_of": p.out_of,
        "lines": [line.__dict__ for line in p.lines],
        "counts": p.counts,
        "locked_classes": p.locked_classes,
        "replaces_by_hand": p.replaces_by_hand,
    }


@router.get("/tests/{int:test_id}/ca/", response=_OUT)
def ca_preview(request, test_id: int, assessment: int = 0, existing: str = "keep"):
    """The CA columns, and with one chosen, what a send would do. Writes nothing."""
    school = _school_of(request)

    def act():
        if not assessment:
            columns = ca.columns_as(request.user, school, test_id)
            return {"test_id": test_id, "columns": [_column_out(c) for c in columns], "assessment": None, "lines": []}
        return preview_out(ca.preview_as(request.user, school, test_id, assessment, existing))

    return _answer(act)


@router.post("/tests/{int:test_id}/ca/", response=_OUT)
def ca_send(request, test_id: int, payload: SendIn):
    """Send the previewed marks through the marking sheet's own rules. Answers with the lines."""
    school = _school_of(request)

    def act():
        transfer = ca.send_as(
            request.user, school, test_id, payload.assessment_id, payload.existing, payload.shown,
            confirm_replace=payload.confirm_replace,
        )
        lines = list(transfer.lines.all())
        return {
            "number": transfer.number,
            "assessment": transfer.assessment_name,
            "max_score": transfer.max_score,
            "existing": transfer.existing,
            "lines": [
                {"student_id": x.student_membership_id, "name": x.student_name, "class_name": x.class_group_name,
                 "test_score": x.test_score, "mark": x.mark, "outcome": x.outcome,
                 "outcome_label": x.get_outcome_display(), "previous": x.previous_value, "detail": x.detail}
                for x in lines
            ],
            "counts": {o: sum(1 for x in lines if x.outcome == o) for o, _ in ca.Outcome.choices},
        }

    return _answer(act)


@router.post("/tests/{int:test_id}/classes/{int:class_group_id}/release/", response=_OUT)
def release_class(request, test_id: int, class_group_id: int):
    def act():
        release.release_as(request.user, _school_of(request), test_id, class_group_id)
        return _results(request, test_id)

    return _answer(act)


@router.post("/releases/{int:release_id}/restore/", response=_OUT)
def restore(request, release_id: int, payload: ReasonIn):
    def act():
        row = release.restore_as(request.user, _school_of(request), release_id, payload.reason)
        return _results(request, row.release.test_id)

    return _answer(act)


@router.get("/scores/", response={200: dict})
def family_scores(request):
    """A parent's own children's released scores. Empty for anybody else."""
    school = _school_of(request)
    return {"children": release.family_scores_as(request.user, school)}


__all__ = ["router"]
