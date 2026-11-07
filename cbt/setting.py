"""Setting a test: write it, send it for approval, approve it. `docs/cbt.md`, step 3.

A teacher sets a test of a subject they teach, for classes they teach it to this term,
from that subject's bank at those classes' level. The principal may set any. The chain:

    draft  --send for approval-->  submitted  --approve (principal, vice principal)-->  published
           <--send back (principal or vice principal, with a reason) / withdraw (the teacher)--

**Sending for approval copies the paper.** The questions are drawn at random from the
bank's questions in use, and each is copied into a `TestItem`: text, options, answer,
marks, picture. From then on the test carries its own copy (operating rule 2): editing
or retiring a bank question never reaches it, and the approver approves exactly the
paper they reviewed. Sending it back discards the copy, and the next send draws again.

**Once a test leaves draft, what it is cannot change** (the database's
`a_set_test_keeps_its_paper` and `a_published_item_is_frozen`): only who sits it, and
every change to that is a `TestAudienceChange` naming who and when.

**Approving publishes it**, and only the principal or the vice principal approves or sends
back (`access.APPROVING_ROLES`, decided 7 November 2026). A test can be approved only
before it opens. Each move is a `TestStateChange` row.

Every function asks who is asking before it reads anything else, and answers "no such
test" and "not yours" alike (`NotAllowed`), so a test's id says nothing about another
teacher's test.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from django.db import transaction
from django.utils import timezone

from academics.models import ClassGroup

from . import access
from .banks import NotAllowed, NotYours, Refused, current_term, live_questions, name_of, plain
from .models import (
    DEFAULT_LATE_WINDOW,
    MAX_DURATION,
    MAX_LATE_WINDOW,
    MAX_TITLE,
    QuestionBank,
    Test,
    TestAudience,
    TestAudienceChange,
    TestItem,
    TestSection,
    TestStateChange,
)

State = Test.State

#: The most questions one class test draws.
MAX_QUESTIONS = 200

_NOT_YOURS = "There is no such test of yours here."


@dataclass
class TestDraft:
    """What the teacher filled in on Set a test."""

    title: str
    subject_id: int
    level: int
    class_group_ids: Sequence[int]
    question_count: int
    opens_at: datetime
    closes_at: datetime
    duration: int
    late_window: int = DEFAULT_LATE_WINDOW
    shuffle_questions: bool = True
    shuffle_options: bool = True
    can_go_back: bool = True
    grid: bool = True
    calculator: bool = False
    require_pin: bool = True
    extra: dict = field(default_factory=dict)


# -- who reaches a test ---------------------------------------------------------------------


def subject_and_level(test) -> tuple:
    section = test.sections.select_related("bank").first()
    return (section.bank.subject_id, section.bank.level) if section else (None, None)


def audience_ids(test) -> set:
    return set(TestAudience.objects.filter(test=test).values_list("class_group_id", flat=True))


def teaches_it(reach, test, subject_id=None, class_ids=None) -> bool:
    """Does this reach teach this test: its subject, to one of its classes, in its term?

    A draft with no class yet is its writer's alone.
    """
    if reach.writes_all:
        return True
    if subject_id is None:
        subject_id, _ = subject_and_level(test)
    class_ids = audience_ids(test) if class_ids is None else class_ids
    if not class_ids:
        return False
    return any(reach.teaches(subject_id, c) for c in class_ids)


def reads_questions(reach, test) -> bool:
    """May this login read this test's questions? Never the administrator's reach."""
    if reach.reads_all:
        return True
    return bool(reach.class_pairs) and teaches_it(reach, test)


def _test_for(actor, school, test_id, *, write=False, lock=False):
    """The test and this login's reach in its term, once this login is shown to reach it."""
    rows = Test.objects.all()
    if lock:
        rows = rows.select_for_update()
    # Who is asking first: a login that reaches no test is refused before a row is read.
    if not access.may_open_tests(actor, school):
        raise NotYours(_NOT_YOURS)
    test = rows.filter(pk=test_id).first()
    if test is None:
        raise NotYours(_NOT_YOURS)
    reach = access.reach(actor, school, test.term)
    if write:
        allowed = reach.writes_all or (reach.class_pairs and teaches_it(reach, test))
        if not allowed and test.state == State.DRAFT and test.created_by_id == actor.pk and reach.class_pairs:
            allowed = not audience_ids(test)
    else:
        allowed = reach.sees_test_summaries or reads_questions(reach, test) or (
            test.created_by_id == actor.pk and bool(reach.class_pairs) and not audience_ids(test)
        )
    if not allowed:
        raise NotYours(_NOT_YOURS)
    return test, reach


def test_as(actor, school, test_id):
    return _test_for(actor, school, test_id)


# -- checking what was typed ------------------------------------------------------------------


def _whole(value, what, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise Refused(f"{what} is a whole number.")
    if not low <= number <= high:
        raise Refused(f"{what} is {low} to {high}.")
    return number


def _checked(reach, draft: TestDraft, term) -> dict:
    if term is None:
        raise Refused("No term is open. The current term is set on the Setup page.")
    title = plain(draft.title, limit=MAX_TITLE, what="The title", lines=False)
    try:
        subject_id, level = int(draft.subject_id), int(draft.level)
    except (TypeError, ValueError):
        raise Refused("Choose the subject and class level the questions come from.")
    if not reach.writes_bank(subject_id, level):
        raise NotAllowed("You set tests only for the subjects and classes you teach this term.")
    bank = QuestionBank.objects.filter(subject_id=subject_id, level=level).first()
    if bank is None:
        raise Refused("That bank has no questions yet. Write some first.")
    try:
        ids = sorted({int(c) for c in draft.class_group_ids or []})
    except (TypeError, ValueError):
        ids = []
    if not ids:
        raise Refused("Choose at least one class to sit it.")
    groups = {g.pk: g for g in ClassGroup.objects.filter(pk__in=ids, is_active=True)}
    for class_id in ids:
        group = groups.get(class_id)
        if group is None or group.level != level:
            raise Refused("Each class must be one at the bank's level.")
        if not reach.teaches(subject_id, class_id):
            raise NotAllowed(f"{group.name}'s {bank.subject.name} is not yours to set.")
    count = _whole(draft.question_count, "The number of questions", 1, MAX_QUESTIONS)
    duration = _whole(draft.duration, "The time for each student, in minutes,", 1, MAX_DURATION)
    late = _whole(draft.late_window, "The late window, in minutes,", 0, MAX_LATE_WINDOW)
    opens, closes = draft.opens_at, draft.closes_at
    if not isinstance(opens, datetime) or not isinstance(closes, datetime):
        raise Refused("Say when the test opens and when it closes.")
    if timezone.is_naive(opens):
        opens = timezone.make_aware(opens)
    if timezone.is_naive(closes):
        closes = timezone.make_aware(closes)
    if closes <= opens:
        raise Refused("A test closes after it opens.")
    if duration > (closes - opens).total_seconds() / 60:
        raise Refused("The time for each student is longer than the test is open.")
    require_pin = bool(draft.require_pin)
    return {
        "bank": bank,
        "groups": [groups[c] for c in ids],
        "count": count,
        "fields": {
            "title": title,
            "term": term,
            "opens_at": opens,
            "closes_at": closes,
            "duration": duration,
            "late_window": late,
            "shuffle_questions": bool(draft.shuffle_questions),
            "shuffle_options": bool(draft.shuffle_options),
            "can_go_back": bool(draft.can_go_back),
            "grid": bool(draft.grid),
            "calculator": bool(draft.calculator),
            "require_pin": require_pin,
            # Option A of `docs/cbt.md`: no exam PIN, and then never to CA.
            "may_send_to_ca": require_pin,
        },
    }


# -- the audience -----------------------------------------------------------------------------


def _set_audience(actor, test, groups, *, log: bool):
    have = audience_ids(test)
    want = {g.pk: g for g in groups}
    added = [want[c] for c in sorted(set(want) - have)]
    removed = sorted(have - set(want))
    if removed:
        TestAudience.objects.filter(test=test, class_group_id__in=removed).delete()
    TestAudience.objects.bulk_create(TestAudience(test=test, class_group=g) for g in added)
    if log:
        names = dict(ClassGroup.objects.filter(pk__in=removed).values_list("pk", "name"))
        TestAudienceChange.objects.bulk_create(
            [
                TestAudienceChange(
                    test=test, class_group=g, class_group_name=g.name, kind=TestAudienceChange.Kind.ADDED,
                    test_state=test.state, by_id=actor.pk, by_name=name_of(actor),
                )
                for g in added
            ]
            + [
                TestAudienceChange(
                    test=test, class_group_id=c, class_group_name=names.get(c, ""), kind=TestAudienceChange.Kind.REMOVED,
                    test_state=test.state, by_id=actor.pk, by_name=name_of(actor),
                )
                for c in removed
            ]
        )
    return added, removed


# -- writing a draft ---------------------------------------------------------------------------


def create_as(actor, school, draft: TestDraft) -> Test:
    term = current_term()
    reach = access.reach(actor, school, term)
    if not reach.writes_any:
        raise NotAllowed("Tests are set by the subject's teachers and the principal.")
    checked = _checked(reach, draft, term)
    with transaction.atomic():
        test = Test.objects.create(created_by_id=actor.pk, created_by_name=name_of(actor), **checked["fields"])
        TestSection.objects.create(test=test, bank=checked["bank"], question_count=checked["count"])
        _set_audience(actor, test, checked["groups"], log=False)
    return test


def update_as(actor, school, test_id, draft: TestDraft) -> Test:
    """Change a draft. A test sent for approval is changed by sending it back first."""
    with transaction.atomic():
        test, _ = _test_for(actor, school, test_id, write=True, lock=True)
        if test.state != State.DRAFT:
            raise Refused("Only a draft can be changed. Withdraw it from approval first.")
        reach = access.reach(actor, school, test.term)
        checked = _checked(reach, draft, test.term)
        for name, value in checked["fields"].items():
            if name != "term":
                setattr(test, name, value)
        test.save()
        section = test.sections.first()
        section.bank = checked["bank"]
        section.question_count = checked["count"]
        section.save(update_fields=["bank", "question_count"])
        _set_audience(actor, test, checked["groups"], log=False)
    return test


def delete_as(actor, school, test_id) -> None:
    """Delete a draft that was never sent for approval. Anything else is kept."""
    with transaction.atomic():
        test, _ = _test_for(actor, school, test_id, write=True, lock=True)
        if test.state != State.DRAFT or TestStateChange.objects.filter(test=test).exists():
            raise Refused("This test has been sent for approval, so its record is kept.")
        TestAudience.objects.filter(test=test).delete()
        TestSection.objects.filter(test=test).delete()
        test.delete()


# -- the chain ---------------------------------------------------------------------------------


def _move(actor, test, to_state, note=""):
    TestStateChange.objects.create(
        test=test, from_state=test.state, to_state=to_state, by_id=actor.pk, by_name=name_of(actor), note=note
    )
    test.state = to_state
    test.save(update_fields=["state", "updated_at"])


def _when(at) -> str:
    return timezone.localtime(at).strftime("%-d %b %Y, %H:%M")


def draw(bank, count, *, rng=None):
    """`count` of the bank's questions in use, at random, in the order drawn."""
    rng = rng or random.SystemRandom()
    pool = list(live_questions(bank).prefetch_related("options").order_by("id"))
    if len(pool) < count:
        raise Refused(
            f"The bank has {len(pool)} question{'' if len(pool) == 1 else 's'} in use, and this test asks for {count}."
        )
    return rng.sample(pool, count)


def _copy(test, section, questions):
    TestItem.objects.bulk_create(
        TestItem(
            test=test,
            section=section,
            position=i,
            stem=q.stem,
            image_key=q.image_key,
            image_alt=q.image_alt,
            options=[o.text for o in sorted(q.options.all(), key=lambda o: o.position)],
            correct_index=q.correct_index,
            marks=q.marks,
            explanation=q.explanation,
            topic=q.topic,
            origin_question=q,
            origin_version=q.version,
        )
        for i, q in enumerate(questions)
    )


def submit_as(actor, school, test_id, *, rng=None) -> Test:
    """Send a draft for approval: draw its questions and copy them in."""
    with transaction.atomic():
        test, reach = _test_for(actor, school, test_id, write=True, lock=True)
        if test.state != State.DRAFT:
            raise Refused("This test has been sent for approval already.")
        if test.opens_at <= timezone.now():
            raise Refused(f"This test was to open at {_when(test.opens_at)}. Move it later, then send it.")
        section = test.sections.select_related("bank", "bank__subject").first()
        classes = audience_ids(test)
        if not classes:
            raise Refused("Choose at least one class to sit it.")
        if not reach.writes_all and not all(reach.teaches(section.bank.subject_id, c) for c in classes):
            raise NotAllowed("One of its classes is no longer yours for this subject.")
        questions = draw(section.bank, section.question_count, rng=rng)
        _copy(test, section, questions)
        _move(actor, test, State.SUBMITTED)
    return test


def withdraw_as(actor, school, test_id) -> Test:
    """Take a test back from approval, to change it. Its copied questions are discarded."""
    with transaction.atomic():
        test, _ = _test_for(actor, school, test_id, write=True, lock=True)
        if test.state != State.SUBMITTED:
            raise Refused("Only a test waiting for approval can be withdrawn.")
        _move(actor, test, State.DRAFT, note="Withdrawn")
        TestItem.objects.filter(test=test).delete()
    return test


def _require_approver(actor, school, test):
    if not access.reach(actor, school, test.term).approves:
        raise NotAllowed("A test is approved or sent back by the principal or the vice principal.")


def send_back_as(actor, school, test_id, note) -> Test:
    """The principal or the vice principal sends a test back to its teacher, saying why."""
    note = plain(note, limit=200, what="The reason", lines=False)
    with transaction.atomic():
        test, _ = _test_for(actor, school, test_id, lock=True)
        _require_approver(actor, school, test)
        if test.state != State.SUBMITTED:
            raise Refused("Only a test waiting for approval can be sent back.")
        _move(actor, test, State.DRAFT, note=note)
        TestItem.objects.filter(test=test).delete()
    return test


def approve_as(actor, school, test_id) -> Test:
    """The principal or the vice principal approves the paper they reviewed, which publishes it."""
    with transaction.atomic():
        test, _ = _test_for(actor, school, test_id, lock=True)
        _require_approver(actor, school, test)
        if test.state != State.SUBMITTED:
            raise Refused("Only a test waiting for approval can be approved.")
        if test.opens_at <= timezone.now():
            raise Refused(
                f"This test was to open at {_when(test.opens_at)}. Send it back so its teacher can move it."
            )
        expected = sum(test.sections.values_list("question_count", flat=True))
        if TestItem.objects.filter(test=test).count() != expected:
            raise Refused("This test's questions are not all here. Send it back to be sent again.")
        _move(actor, test, State.PUBLISHED)
    return test


def change_classes_as(actor, school, test_id, class_group_ids) -> tuple:
    """Who sits a test that has left draft. Every class added or removed is logged."""
    with transaction.atomic():
        test, reach = _test_for(actor, school, test_id, write=True, lock=True)
        if test.state not in (State.SUBMITTED, State.PUBLISHED):
            raise Refused("A draft's classes are changed by editing it; a closed test's are kept.")
        section = test.sections.select_related("bank", "bank__subject").first()
        try:
            ids = sorted({int(c) for c in class_group_ids or []})
        except (TypeError, ValueError):
            ids = []
        if not ids:
            raise Refused("A test keeps at least one class.")
        groups = {g.pk: g for g in ClassGroup.objects.filter(pk__in=ids, is_active=True)}
        have = audience_ids(test)
        for class_id in set(ids) ^ have:
            group = groups.get(class_id)
            if class_id in ids and (group is None or group.level != section.bank.level):
                raise Refused("Each class must be one at the bank's level.")
            if not reach.teaches(section.bank.subject_id, class_id):
                raise NotAllowed("You change only the classes you teach this subject to.")
        return _set_audience(actor, test, [groups[c] for c in ids], log=True)


__all__ = [
    "MAX_QUESTIONS",
    "TestDraft",
    "approve_as",
    "change_classes_as",
    "create_as",
    "delete_as",
    "draw",
    "reads_questions",
    "send_back_as",
    "submit_as",
    "teaches_it",
    "test_as",
    "update_as",
    "withdraw_as",
]
