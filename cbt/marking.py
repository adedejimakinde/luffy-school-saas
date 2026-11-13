"""Marking: a score per attempt, on read, and what a teacher does with it before release.

`docs/cbt.md`, "Release and CA" and screen 7. **No live score is stored.** A score is the
marks of the items whose counted answer (`cbt.sitting.counted_answers()`'s rule, read for a
whole test at once here) is the item's key, and the key is the item's own or the latest
`KeyCorrection`'s (`keys_of()`). So a key correction re-marks every attempt the moment its
row exists, and the row says whose scores moved.

The attempt that counts for a student is their **latest**: a retake replaces the first.
An attempt still open has no score yet.

Who may read and do what is `cbt.access` (`reads_results()`, `marks_test()`,
`reads_released_only()`), asked before any attempt is read; the administrator is served
the released scores alone, with no answer and no item.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from academics.models import ClassPlacement
from accounts.models import Membership, Role

from . import access, sitting
from .banks import NotYours, Refused, name_of, plain
from .models import (
    MAX_WHY,
    AnswerEvent,
    Attempt,
    AttemptEvent,
    CaTransfer,
    KeyCorrection,
    ReleasedTestScore,
    Test,
    TestAudience,
    TestItem,
    TestRelease,
    TestStateChange,
)
from .sittings import NotAllowed, _role_word

LETTERS = "ABCDE"
_NO_TEST = "There is no such test of yours here."
#: A test is marked once students can sit it: approved, or closed.
MARKED_STATES = (Test.State.PUBLISHED, Test.State.CLOSED)


# -- marking ------------------------------------------------------------------------------


def keys_of(test, items=None) -> Dict[int, int]:
    """`item id -> the index that is right`: the item's own, or its latest correction's."""
    items = items if items is not None else list(TestItem.objects.filter(test=test))
    keys = {i.pk: i.correct_index for i in items}
    for item_id, new in KeyCorrection.objects.filter(test=test).order_by("at", "id").values_list("item_id", "new_index"):
        keys[item_id] = new
    return keys


def answers_of(test) -> Dict[int, Dict[int, Optional[int]]]:
    """`attempt id -> {item id -> chosen}`: every attempt's counted answers, in two queries.

    The same rule as `sitting.counted_answers()`: the accepted rows nobody superseded and
    that lost to nobody.
    """
    beaten = AnswerEvent.objects.filter(attempt__test=test, supersedes__isnull=False).values("supersedes_id")
    rows = (
        AnswerEvent.objects.filter(attempt__test=test, accepted=True, superseded_by__isnull=True)
        .exclude(pk__in=beaten)
        .values_list("attempt_id", "item_id", "chosen")
    )
    out = defaultdict(dict)
    for attempt_id, item_id, chosen in rows:
        out[attempt_id][item_id] = chosen
    return out


@dataclass
class Mark:
    score: int
    out_of: int
    right: int
    answered: int


def mark(items, keys, answers) -> Mark:
    """One attempt's score: the marks of each item answered with its key."""
    score = right = answered = 0
    for item in items:
        chosen = answers.get(item.pk)
        if chosen is None:
            continue
        answered += 1
        if chosen == keys[item.pk]:
            right += 1
            score += item.marks
    return Mark(score, sum(i.marks for i in items), right, answered)


def latest_attempts(test) -> Dict[int, Attempt]:
    """`student id -> their latest attempt` at this test."""
    latest = {}
    for a in Attempt.objects.filter(test=test).order_by("student_membership_id", "number"):
        latest[a.student_membership_id] = a
    return latest


def scores_of(test, items=None, keys=None) -> Dict[int, Mark]:
    """`student id -> Mark` for every student whose latest attempt is closed."""
    items = items if items is not None else list(TestItem.objects.filter(test=test).order_by("position"))
    keys = keys if keys is not None else keys_of(test, items)
    answers = answers_of(test)
    return {
        sid: mark(items, keys, answers.get(a.pk, {}))
        for sid, a in latest_attempts(test).items()
        if not a.is_open
    }


def round_half_up(score: int, out_of: int, max_score: int) -> int:
    """`score / out_of x max_score`, to the nearest whole mark, halves up. Integers only."""
    return (2 * score * max_score + out_of) // (2 * out_of)


# -- the test, once this login is shown to reach it ------------------------------------------


def _test(actor, school, test_id, allowed, refusal, *, lock=False) -> Test:
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
    if test.state not in MARKED_STATES:
        raise Refused("A test is marked once it is approved and sat.")
    return test


def audience_of(test) -> Dict[int, str]:
    return {
        a.class_group_id: a.class_group.name
        for a in TestAudience.objects.filter(test=test).select_related("class_group")
    }


def live_releases(test) -> Dict[int, TestRelease]:
    """`class id -> its release that is not restored`, at most one each."""
    out = {}
    for r in TestRelease.objects.filter(test=test, restore__isnull=True).order_by("at", "id"):
        out[r.class_group_id] = r
    return out


def has_live_release(test) -> bool:
    return TestRelease.objects.filter(test=test, restore__isnull=True).exists()


# -- the results screen (screen 7) -----------------------------------------------------------


@dataclass
class Row:
    student_id: int
    name: str
    admission_number: str
    class_name: str
    state: str
    number: int = 0
    score: Optional[int] = None
    out_of: Optional[int] = None
    right: Optional[int] = None
    answered: Optional[int] = None
    started_at: Optional[str] = None
    submitted_at: Optional[str] = None
    disconnects: int = 0
    late_refused: int = 0
    released: bool = False


@dataclass
class Results:
    test: Test
    subject: str
    released_only: bool
    out_of: int
    classes: List[dict]
    rows: List[Row]
    stats: dict
    distribution: List[dict]
    items: List[dict]
    corrections: List[dict]
    transfers: List[dict]
    may_correct: bool = False
    may_send: bool = False
    may_close: bool = False
    may_restore: bool = False
    sends_to_ca: bool = True
    open_attempts: int = 0
    #: The classes that have still to finish the paper. While any is named, a release
    #: shows a class its scores and no answers (`release.classes_still_to_finish()`).
    answers_held_for: List[str] = field(default_factory=list)


def _iso(at):
    return at.isoformat() if at else None


def _stats(marks: List[Mark], out_of: int, placed: int) -> dict:
    if not marks:
        return {"sat": 0, "placed": placed, "average": None, "percent": None, "highest": None,
                "highest_count": 0, "lowest": None, "lowest_count": 0}
    scores = [m.score for m in marks]
    average = sum(scores) / len(scores)
    high, low = max(scores), min(scores)
    return {
        "sat": len(scores),
        "placed": placed,
        "average": round(average, 1),
        "percent": round(100 * average / out_of) if out_of else None,
        "highest": high,
        "highest_count": scores.count(high),
        "lowest": low,
        "lowest_count": scores.count(low),
    }


def _distribution(marks: List[Mark], out_of: int) -> List[dict]:
    counts = Counter(m.score for m in marks)
    return [{"score": s, "count": counts.get(s, 0)} for s in range(out_of + 1)]


def item_analysis(items, keys, answer_sets: List[dict], marks: List[Mark]) -> List[dict]:
    """Per question: how many chose each option, how many left it, the facility (percent
    right), the wrong option chosen most, and whether the strongest third mostly chose a
    wrong one (a key to check). Over the closed attempts given, in the paper's order."""
    n = len(answer_sets)
    ranked = sorted(range(n), key=lambda k: -marks[k].score)
    top = ranked[: max(1, n // 3)] if n >= 3 else []
    out = []
    for item in items:
        key = keys[item.pk]
        counts = Counter(a.get(item.pk) for a in answer_sets)
        chosen = [counts.get(i, 0) for i in range(len(item.options))]
        blank = n - sum(chosen)
        right = chosen[key] if key < len(chosen) else 0
        wrong = [(c, i) for i, c in enumerate(chosen) if i != key and c]
        # Most chosen; a tie goes to the earlier letter, so the answer is the same every read.
        most_wrong = max(wrong, key=lambda t: (t[0], -t[1]))[1] if wrong else None
        check = False
        if top:
            strong = Counter(answer_sets[k].get(item.pk) for k in top)
            favourite, times = max(((c, i) for i, c in strong.items() if i is not None), default=(0, None))[::-1]
            check = favourite is not None and favourite != key and times > strong.get(key, 0)
        out.append(
            {
                "item_id": item.pk,
                "number": item.position + 1,
                "stem": item.stem,
                "options": list(item.options),
                "key": key,
                "key_corrected": key != item.correct_index,
                "original_key": item.correct_index,
                "marks": item.marks,
                "chose": chosen,
                "percent": [round(100 * c / n) if n else 0 for c in chosen],
                "blank": blank,
                "right": right,
                "facility": round(100 * right / n) if n else None,
                "most_wrong": most_wrong,
                "check_key": check,
                "topic": item.topic,
            }
        )
    return out


def results_as(actor, school, test_id) -> Results:
    """The results of one test for this login: screen 7, or the office's released scores."""
    with transaction.atomic():
        test = _test(
            actor, school, test_id,
            lambda a, s, t: access.reads_results(a, s, t) or access.reads_released_only(a, s, t),
            "A test's results are read by its teachers, the principal and the vice principal; "
            "the administrator sees scores once they are released.",
        )
        if test.state == Test.State.PUBLISHED:
            sitting.settle_all(test, timezone.now())
    from .setting import subject_and_level

    subject_id, _ = subject_and_level(test)
    from gradebook.models import Subject

    subject = Subject.objects.filter(pk=subject_id).values_list("name", flat=True).first() or ""
    audience = audience_of(test)
    items = list(TestItem.objects.filter(test=test).order_by("position"))
    out_of = sum(i.marks for i in items)
    released = live_releases(test)
    if access.reads_released_only(actor, school, test) and not access.reads_results(actor, school, test):
        return _released_only(test, subject, audience, released, out_of)

    scope = access.classes_of(actor, school, test, audience)
    keys = keys_of(test, items)
    answers = answers_of(test)
    latest = latest_attempts(test)
    placements = dict(
        ClassPlacement.objects.filter(term_id=test.term_id, class_group_id__in=list(scope)).values_list(
            "student_membership_id", "class_group_id"
        )
    )
    ids = set(placements) | {sid for sid, a in latest.items() if a.class_group_id in scope}
    members = {
        m.pk: m for m in Membership.objects.filter(school=school, role=Role.STUDENT, pk__in=ids).select_related("user")
    }
    counts = defaultdict(Counter)
    for sid, kind, detail in AttemptEvent.objects.filter(test=test, kind__in=["disconnect", "late_refused"]).values_list(
        "student_membership_id", "kind", "detail"
    ):
        counts[sid][kind] += (detail or {}).get("count", 1) if kind == "late_refused" else 1
    rows, marks, answer_sets = [], [], []
    open_attempts = 0
    for sid in ids:
        a = latest.get(sid)
        member = members.get(sid)
        if a is not None and a.class_group_id not in scope:
            continue
        row = Row(
            student_id=sid,
            name=a.student_name if a else sitting.name_of(member) if member else "A student who has left",
            admission_number=a.admission_number if a else " ".join((member.reference or "").split()) if member else "",
            class_name=a.class_group_name if a else audience.get(placements.get(sid), ""),
            state="Did not sit" if a is None else "Sitting" if a.is_open else Attempt.EndedBy(a.ended_by).label,
            disconnects=counts[sid]["disconnect"],
            late_refused=counts[sid]["late_refused"],
        )
        if a is not None:
            row.number = a.number
            row.started_at = _iso(a.started_at)
            row.submitted_at = _iso(a.submitted_at)
            row.released = a.class_group_id in released
            if a.is_open:
                open_attempts += 1
            else:
                m = mark(items, keys, answers.get(a.pk, {}))
                row.score, row.out_of, row.right, row.answered = m.score, m.out_of, m.right, m.answered
                marks.append(m)
                answer_sets.append(answers.get(a.pk, {}))
        rows.append(row)
    rows.sort(key=lambda r: (r.class_name, r.name.casefold(), r.student_id))
    may_mark = access.marks_test(actor, school, test)
    classes = [_class_out(test, cid, name, released, may_mark, actor, school) for cid, name in audience.items() if cid in scope]
    return Results(
        test=test,
        subject=subject,
        released_only=False,
        out_of=out_of,
        classes=classes,
        rows=rows,
        stats=_stats(marks, out_of, len(ids)),
        distribution=_distribution(marks, out_of),
        items=item_analysis(items, keys, answer_sets, marks),
        corrections=[_correction_out(c) for c in KeyCorrection.objects.filter(test=test).select_related("item")],
        transfers=[_transfer_out(t) for t in CaTransfer.objects.filter(test=test).prefetch_related("lines")],
        may_correct=may_mark and not released,
        may_send=may_mark and test.may_send_to_ca,
        may_close=may_mark and test.state == Test.State.PUBLISHED,
        may_restore=access.restores(actor, school),
        sends_to_ca=test.may_send_to_ca,
        open_attempts=open_attempts,
        answers_held_for=_held_for(test),
    )


def _held_for(test) -> List[str]:
    from .release import classes_still_to_finish

    return classes_still_to_finish(test)


def _class_out(test, class_id, name, released, may_mark, actor, school) -> dict:
    from .release import why_not_releasable

    live = released.get(class_id)
    history = [
        {
            "release_id": r.pk,
            "at": _iso(r.at),
            "by": r.by_name,
            "count": r.count,
            "restored": bool(getattr(r, "restore", None)),
            "restored_at": _iso(r.restore.at) if getattr(r, "restore", None) else None,
            "restored_by": r.restore.by_name if getattr(r, "restore", None) else "",
            "reason": r.restore.reason if getattr(r, "restore", None) else "",
        }
        for r in TestRelease.objects.filter(test=test, class_group_id=class_id).select_related("restore").order_by("at", "id")
    ]
    why = "" if live else why_not_releasable(test, class_id)
    return {
        "id": class_id,
        "name": name,
        "released": live is not None,
        "release_id": live.pk if live else None,
        "released_at": _iso(live.at) if live else None,
        "released_by": live.by_name if live else "",
        "may_release": may_mark and live is None and not why,
        "why_not": why if may_mark and live is None else "",
        "history": history,
    }


def _correction_out(c) -> dict:
    return {
        "item_id": c.item_id,
        "number": c.item.position + 1,
        "old": LETTERS[c.old_index],
        "new": LETTERS[c.new_index],
        "reason": c.reason,
        "by": c.by_name,
        "at": _iso(c.at),
        "changes": c.changes,
        "out_of": c.out_of,
    }


def _transfer_out(t) -> dict:
    tally = Counter(line.outcome for line in t.lines.all())
    return {
        "number": t.number,
        "assessment": t.assessment_name,
        "max_score": t.max_score,
        "existing": t.existing,
        "by": t.by_name,
        "at": _iso(t.at),
        "counts": {o: tally.get(o, 0) for o, _ in t.lines.model.Outcome.choices},
    }


def _released_only(test, subject, audience, released, out_of) -> Results:
    """The administrator's: each released class's frozen scores, no answer and no item."""
    rows = []
    for r in ReleasedTestScore.objects.filter(release__in=list(released.values())).order_by(
        "class_group_name", "student_name", "id"
    ):
        rows.append(
            Row(
                student_id=r.student_membership_id, name=r.student_name, admission_number=r.admission_number,
                class_name=r.class_group_name, state="Released", number=r.attempt_number, score=r.score,
                out_of=r.out_of, released=True,
            )
        )
    classes = [
        {"id": cid, "name": name, "released": cid in released, "release_id": None,
         "released_at": _iso(released[cid].at) if cid in released else None,
         "released_by": released[cid].by_name if cid in released else "",
         "may_release": False, "why_not": "", "history": []}
        for cid, name in audience.items()
    ]
    marks = [Mark(r.score, r.out_of or out_of, 0, 0) for r in rows]
    return Results(
        test=test, subject=subject, released_only=True, out_of=out_of, classes=classes, rows=rows,
        stats=_stats(marks, out_of, len(rows)), distribution=[], items=[], corrections=[], transfers=[],
        sends_to_ca=test.may_send_to_ca, answers_held_for=_held_for(test),
    )


# -- a wrong key ---------------------------------------------------------------------------------


def correct_key_as(actor, school, test_id, item_id, new_index, reason) -> KeyCorrection:
    """Put a wrong key right, with a reason: every attempt is marked again, and the row says
    whose scores moved. Only before release (the database refuses it after too)."""
    reason = plain(reason, limit=MAX_WHY, what="The reason", lines=False)
    with transaction.atomic():
        test = _test(
            actor, school, test_id, access.marks_test,
            "A key is corrected by the test's teachers or the principal.", lock=True,
        )
        if has_live_release(test):
            raise Refused(
                "Scores of this test have been released, so its keys are fixed. The principal can "
                "restore the release, with a reason, if a key is wrong."
            )
        items = list(TestItem.objects.filter(test=test).order_by("position"))
        item = next((i for i in items if i.pk == item_id), None)
        if item is None:
            raise Refused("That question is not on this test.")
        try:
            new_index = int(new_index)
        except (TypeError, ValueError):
            raise Refused("Choose the option that is right.")
        if not 0 <= new_index < len(item.options):
            raise Refused("Choose one of the question's options.")
        if test.state == Test.State.PUBLISHED:
            sitting.settle_all(test, timezone.now())
        before_keys = keys_of(test, items)
        if before_keys[item.pk] == new_index:
            raise Refused(f"{LETTERS[new_index]} is already the key.")
        after_keys = {**before_keys, item.pk: new_index}
        answers = answers_of(test)
        changes = []
        for sid, a in latest_attempts(test).items():
            if a.is_open:
                continue
            got = answers.get(a.pk, {})
            before, after = mark(items, before_keys, got).score, mark(items, after_keys, got).score
            if before != after:
                changes.append({"student_id": sid, "name": a.student_name, "class_name": a.class_group_name,
                                "before": before, "after": after})
        changes.sort(key=lambda c: (c["class_name"], c["name"].casefold()))
        return KeyCorrection.objects.create(
            test=test, item=item, old_index=before_keys[item.pk], new_index=new_index, reason=reason,
            changes=changes, out_of=sum(i.marks for i in items), by_id=actor.pk, by_name=name_of(actor),
            role=_role_word(actor, school, test),
        )


# -- closing a test ------------------------------------------------------------------------------


def close_test_as(actor, school, test_id) -> Test:
    """Published to closed: nobody starts it again, by window or by hand. Its answers,
    scores and releases are kept. Refused while anybody is still sitting it."""
    with transaction.atomic():
        test = _test(actor, school, test_id, access.marks_test, "A test is closed by its teachers or the principal.", lock=True)
        if test.state != Test.State.PUBLISHED:
            raise Refused("This test is closed already.")
        sitting.settle_all(test, timezone.now())
        sitting_now = Attempt.objects.filter(test=test, submitted_at__isnull=True).count()
        if sitting_now:
            raise Refused(
                f"{sitting_now} student{' is' if sitting_now == 1 else 's are'} still sitting it. Wait for their time "
                "to end, or close their class's sitting and end the attempts in progress."
            )
        TestStateChange.objects.create(
            test=test, from_state=test.state, to_state=Test.State.CLOSED, by_id=actor.pk, by_name=name_of(actor),
        )
        test.state = Test.State.CLOSED
        test.save(update_fields=["state", "updated_at"])
    return test


__all__ = [
    "LETTERS",
    "Mark",
    "Results",
    "Row",
    "answers_of",
    "close_test_as",
    "correct_key_as",
    "item_analysis",
    "keys_of",
    "latest_attempts",
    "live_releases",
    "mark",
    "results_as",
    "round_half_up",
    "scores_of",
]
