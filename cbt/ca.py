"""Scores into CA: the preview, and the send. `docs/cbt.md`, "How scores reach CA".

1. The teacher picks a CA column: an `Assessment` of the test's subject and term, looked
   up in this school's schema only.
2. Each mark is `round_half_up(score / out_of x max_score)`, a whole number.
3. **The preview writes nothing.** It reads every affected `Score` and its version, and
   says for each student what the send would do: a new mark, keep the one they have,
   replace it (and which marks were typed by hand), no mark because they did not sit,
   or nothing because the class's results are locked.
4. **The send is a caller of `gradebook.services.set_score_as()`**, never a second write
   path, with the version the preview showed:
   - did not sit: no call, line `not_sat`. No zero, ever;
   - has a mark, keep: no call, line `kept`;
   - has a mark, replace: written over the version shown; a mark typed since raises
     `ScoreChangedMeanwhile` and the line says `changed_meanwhile`;
   - results submitted or released: the gradebook's own `MarksLocked`, line `locked`.

**A mark someone typed is never overwritten unseen.** The send carries what the preview
showed for each student (their mark and its version, or none); a replace that would
overwrite a mark not written by this test's own earlier send needs `confirm_replace`, and
the screen asks for it, naming them. If a test score has moved since the preview (a key
corrected, an attempt closed) the send is refused whole and the teacher previews again,
so **what is written is what was previewed**.

**A test sat without the exam PIN never reaches CA** (`Test.may_send_to_ca`), checked
here, by the service, whatever the screen sent.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from django.db import transaction
from django.db.models import Max

from academics.models import ClassPlacement
from academics.services import placement_of
from accounts.models import Membership, Role

from . import access, sitting
from .banks import NotYours, Refused, name_of
from .marking import _test, audience_of, keys_of, latest_attempts, answers_of, mark, round_half_up
from .models import CaTransfer, CaTransferLine, TestItem
from .sittings import NotAllowed, _role_word

Outcome = CaTransferLine.Outcome
NO_PIN = "This test was sat without the exam PIN, so its scores never go to a CA column."


def _subject_id(test):
    from .setting import subject_and_level

    return subject_and_level(test)[0]


def columns_of(test):
    """The CA columns a test's scores may go into: its subject's papers this term."""
    from gradebook.models import Assessment

    return list(Assessment.objects.filter(term_id=test.term_id, subject_id=_subject_id(test)).order_by("position", "name", "id"))


def _column(test, assessment_id):
    from gradebook.models import Assessment

    found = Assessment.objects.filter(pk=assessment_id, term_id=test.term_id, subject_id=_subject_id(test)).first()
    if found is None:
        raise Refused("Choose one of this subject's CA columns for the test's term.")
    return found


def lock_of(assessment, student_id, class_group_id) -> str:
    """Why the gradebook would refuse a mark for this student now, or "". Read only.

    The same two questions `gradebook.services` asks, in the same order: has a card for
    this child, this term, gone home; and is their class's sheet still open. The send
    asks the gradebook itself, under its lock; this is only what the preview says.
    """
    from results import services as results_services
    from results.models import ReleasedTraitRating

    if ReleasedTraitRating.objects.filter(sheet__term=assessment.term, student_membership_id=student_id).exists():
        return "released"
    placement = placement_of(student_id, assessment.term)
    if placement is None:
        return ""
    sheet = results_services.sheet_for(placement.class_group, assessment.term)
    if results_services.is_open_for_writing(sheet):
        return ""
    return sheet.state


@dataclass
class Line:
    student_id: int
    name: str
    class_name: str
    class_id: Optional[int]
    test_score: Optional[int]
    mark: Optional[int]
    #: The mark in the column now, its version, and whether this test's own send wrote it.
    current: Optional[int]
    version: Optional[int]
    by_hand: bool
    #: What the send would do: `new`, `replace`, `kept`, `not_sat`, `locked`, `same`.
    will: str
    locked_state: str = ""
    sitting_now: bool = False


@dataclass
class Preview:
    test: object
    assessment: object
    existing: str
    out_of: int
    lines: List[Line]
    columns: list
    counts: Dict[str, int] = field(default_factory=dict)
    locked_classes: List[dict] = field(default_factory=list)
    replaces_by_hand: int = 0


def _ours(test, assessment) -> Dict[int, int]:
    """`student id -> the mark this test's latest send wrote` into this column."""
    out = {}
    for sid, value in (
        CaTransferLine.objects.filter(transfer__test=test, transfer__assessment=assessment, outcome=Outcome.WRITTEN)
        .order_by("transfer__number", "id")
        .values_list("student_membership_id", "mark")
    ):
        out[sid] = value
    return out


def _preview(actor, school, test, assessment, existing) -> Preview:
    from gradebook.models import Score

    if existing not in (CaTransfer.Existing.KEEP, CaTransfer.Existing.REPLACE):
        raise Refused("Say whether a mark a student already has is kept or replaced.")
    audience = audience_of(test)
    scope = access.classes_of(actor, school, test, audience)
    items = list(TestItem.objects.filter(test=test).order_by("position"))
    out_of = sum(i.marks for i in items)
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
    scores = {s.student_membership_id: s for s in Score.objects.filter(assessment=assessment, student_membership_id__in=ids)}
    ours = _ours(test, assessment)
    lines = []
    for sid in ids:
        a = latest.get(sid)
        if a is not None and a.class_group_id not in scope:
            continue
        member = members.get(sid)
        class_id = a.class_group_id if a else placements.get(sid)
        current = scores.get(sid)
        line = Line(
            student_id=sid,
            name=a.student_name if a else sitting.name_of(member) if member else "A student who has left",
            class_name=a.class_group_name if a else audience.get(class_id, ""),
            class_id=class_id,
            test_score=None,
            mark=None,
            current=current.value if current else None,
            version=current.version if current else None,
            by_hand=bool(current) and ours.get(sid) != current.value,
            will=Outcome.NOT_SAT,
        )
        if a is not None and a.is_open:
            line.sitting_now = True
        elif a is not None:
            m = mark(items, keys, answers.get(a.pk, {}))
            line.test_score = m.score
            line.mark = round_half_up(m.score, out_of, assessment.max_score) if out_of else 0
            line.locked_state = lock_of(assessment, sid, class_id)
            if line.locked_state:
                line.will = Outcome.LOCKED
            elif current is None:
                line.will = "new"
            elif current.value == line.mark:
                line.will = "same"
            elif existing == CaTransfer.Existing.KEEP:
                line.will = Outcome.KEPT
            else:
                line.will = "replace"
        lines.append(line)
    lines.sort(key=lambda x: (x.class_name, x.name.casefold(), x.student_id))
    counts = {}
    for line in lines:
        counts[line.will] = counts.get(line.will, 0) + 1
    locked = {}
    for line in lines:
        if line.will == Outcome.LOCKED:
            locked.setdefault(line.class_name, {"class_name": line.class_name, "state": line.locked_state, "count": 0})
            locked[line.class_name]["count"] += 1
    return Preview(
        test=test, assessment=assessment, existing=existing, out_of=out_of, lines=lines, columns=columns_of(test),
        counts=counts, locked_classes=list(locked.values()),
        replaces_by_hand=sum(1 for x in lines if x.will == "replace" and x.by_hand),
    )


def _sendable(actor, school, test_id, *, lock=False):
    test = _test(
        actor, school, test_id, access.marks_test,
        "Scores are sent to CA by the test's teachers or the principal.", lock=lock,
    )
    if not test.may_send_to_ca:
        raise Refused(NO_PIN)
    return test


def columns_as(actor, school, test_id) -> list:
    return columns_of(_sendable(actor, school, test_id))


def preview_as(actor, school, test_id, assessment_id, existing) -> Preview:
    """What a send would do, for every student of this login's classes. Writes nothing."""
    with transaction.atomic():
        test = _sendable(actor, school, test_id)
        if test.state == test.State.PUBLISHED:
            sitting.settle_all(test)
    return _preview(actor, school, test, _column(test, assessment_id), existing)


def send_as(actor, school, test_id, assessment_id, existing, shown, *, confirm_replace=False) -> CaTransfer:
    """Send the scores the preview showed. `shown` is `{student id: {"score", "mark",
    "current", "version"}}` as the preview gave them."""
    from gradebook import services as gradebook

    shown = {int(k): v or {} for k, v in (shown or {}).items()}
    with transaction.atomic():
        test = _sendable(actor, school, test_id, lock=True)
        if test.state == test.State.PUBLISHED:
            sitting.settle_all(test)
        assessment = _column(test, assessment_id)
        preview = _preview(actor, school, test, assessment, existing)
        sent = [x for x in preview.lines if x.test_score is not None]
        if {x.student_id for x in sent} != {sid for sid, v in shown.items() if v.get("score") is not None} or any(
            shown[x.student_id].get("score") != x.test_score for x in sent
        ):
            raise Refused("The test's scores have changed since your preview. Look at the preview again, then send.")
        if preview.replaces_by_hand and existing == CaTransfer.Existing.REPLACE and not confirm_replace:
            raise Refused(
                f"{preview.replaces_by_hand} mark{' was' if preview.replaces_by_hand == 1 else 's were'} typed on the "
                "marking sheet. Confirm that the test marks replace them, or keep them."
            )
        number = (CaTransfer.objects.filter(test=test).aggregate(n=Max("number"))["n"] or 0) + 1
        transfer = CaTransfer.objects.create(
            test=test, assessment=assessment, assessment_name=assessment.name, max_score=assessment.max_score,
            out_of=preview.out_of, existing=existing, number=number, by_id=actor.pk, by_name=name_of(actor),
            role=_role_word(actor, school, test),
        )
        students = {
            m.pk: m
            for m in Membership.objects.filter(school=school, role=Role.STUDENT, pk__in=[x.student_id for x in sent])
            .select_related("school", "user")
        }
        rows = []
        for x in preview.lines:
            seen = shown.get(x.student_id, {})
            line = CaTransferLine(
                transfer=transfer, student_membership_id=x.student_id, student_name=x.name, class_group_name=x.class_name,
                test_score=x.test_score, mark=x.mark, previous_value=seen.get("current"),
                previous_version=seen.get("version"),
            )
            if x.test_score is None:
                line.outcome, line.mark = Outcome.NOT_SAT, None
                line.detail = "Still sitting it." if x.sitting_now else ""
                rows.append(line)
                continue
            had = seen.get("current") is not None
            if had and seen.get("current") == x.mark and x.current == x.mark:
                line.outcome, line.detail = Outcome.KEPT, "Already this mark."
            elif had and existing == CaTransfer.Existing.KEEP:
                line.outcome = Outcome.KEPT
            else:
                member = students.get(x.student_id)
                try:
                    gradebook.set_score_as(
                        actor, assessment, member, x.mark,
                        expected_version=seen.get("version") if had else None,
                    )
                    line.outcome = Outcome.WRITTEN
                except gradebook.MarksLocked as exc:
                    line.outcome, line.detail = Outcome.LOCKED, str(exc)[:300]
                except gradebook.ScoreChangedMeanwhile as exc:
                    line.outcome, line.detail = Outcome.CHANGED_MEANWHILE, str(exc)[:300]
                except gradebook.NotAssignedToMark as exc:
                    # A student who has moved to a class this sender does not teach: the
                    # gradebook's narrowing refuses, and the line says so.
                    line.outcome, line.detail = Outcome.LOCKED, str(exc)[:300]
                except gradebook.NotAllowedToMark as exc:
                    raise NotAllowed(str(exc))
            rows.append(line)
        CaTransferLine.objects.bulk_create(rows)
    return transfer


__all__ = ["NO_PIN", "Line", "Outcome", "Preview", "columns_as", "columns_of", "lock_of", "preview_as", "send_as"]
