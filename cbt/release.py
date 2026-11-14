"""Release and restore, and the two pages that read what was released.

`docs/cbt.md`, "Release and CA". **A release is final, like a results release**: it
freezes each student's score, and their corrections, as `ReleasedTestScore` rows in the
same transaction, and those rows, never the live marks, are all a student's or a
parent's page reads (operating rule 1: the guard keys off the released artefact, not off
where the child sits today). **Undoing it is a restore with a reason, by the principal
alone**: the frozen rows stay, the page stops showing them, and a later release is a new
row with scores frozen afresh (after a key correction, if one was needed).

A class is released when nobody in it is still sitting the test and its sitting is not
open, by a teacher of the test for a class they teach it to, or by the principal.

## A practice test is never released (audit F-08)

A test with the exam PIN off opened on an admission number alone, which is on every class
list, so whoever sat it may not be who the score names. Its scores are the teacher's to
read on the results screen and nobody else's: `release_as()` refuses it, and
`live_scores()`, which every student's and parent's page reads, never carries a score of
one, whatever rows exist.

## The two pages

## Answers wait for every class (audit G-03)

A test is one paper and may be set for several classes, and scores are released a class at
a time. A release shows that class **its scores only** while any other class has still to
finish the paper: the corrections (what was right, and why) are frozen with the score as
before, and the student's page does not hand them out until `classes_still_to_finish()`
is empty. It is asked on every read, never stored, so a sitting opened again by hand, or
a retake still running, holds the answers again for everybody.

- **A student** has no account to sign in with (`docs/cbt.md`, "Student sign-in"), so
  their page is a door, like `/sit/`: the test code, their admission number and their
  exam PIN, **always the PIN**, behind the same throttle (this browser and its address,
  never the number typed: audit F-09) and with the same one refusal for every failure of
  the three. Proved, it shows their own released score for that test with their
  corrections (their numbering and letters), and their other released scores; before
  release it says so and shows nothing.
- **A parent**, signed in, sees each of their own children's released scores: no
  question, no answer, no other child, no class average.
"""

from dataclasses import dataclass
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from accounts.models import Membership, Role

from . import access, paper, pins, sitting
from .banks import NotYours, Refused, name_of, plain
from .marking import LETTERS, MARKED_STATES, _test, answers_of, keys_of, latest_attempts, mark
from .models import (
    MAX_WHY,
    Attempt,
    ReleasedTestScore,
    SittingControl,
    Test,
    TestAudience,
    TestItem,
    TestRelease,
    TestReleaseRestore,
)
from .sittings import NotAllowed, _role_word

NOT_RELEASED = "Your score for this test has not been released yet. Your teacher releases it."
#: Why a practice test (the exam PIN off) is never released (audit F-08).
PRACTICE_NOT_RELEASED = (
    "This is a practice test, sat without the exam PIN, so its scores are never released to "
    "students or parents: anybody with the class list could have sat as anybody."
)
#: Said on a student's page in place of the corrections while another class still sits.
ANSWERS_HELD = (
    "Your answers and the right ones will show here once every class has finished this test."
)


# -- has every class finished the paper ----------------------------------------------------------


def classes_still_to_finish(test, now=None) -> List[str]:
    """The names of the classes that have not finished sitting this test, sorted.

    While this is not empty, no student of any class is shown a right answer (audit
    G-03): the paper is the same for every class, so one class's corrections are the
    next class's answer key.

    A class has **finished** when nobody in it has an attempt still running and nobody
    in it can start one:

    - the test is closed for good (`Test.State.CLOSED`); or
    - its window has closed (`closes_at` has passed) and the class's sitting has not
      been opened again by hand; or
    - its sitting was closed by hand after somebody in the class sat it.

    A sitting closed by hand **before anybody in the class sat**, with the window still
    running, has not finished: that is a class waiting its turn, and it can be opened
    again. A sitting opened by hand has not finished whatever the window says, which
    also covers a retake, since a retake can only start while the sitting is open.

    An attempt still running holds the answers whichever class it belongs to, until its
    own time and late window are over (the moment the server would close it).

    Reads only; nothing is settled or written here.
    """
    now = now or timezone.now()
    still = set()
    for attempt in Attempt.objects.filter(test=test, submitted_at__isnull=True):
        if sitting.closes_for_good_at(attempt, test) > now:
            still.add(attempt.class_group_name)
    if test.state == Test.State.PUBLISHED:
        latest = {}
        for control in SittingControl.objects.filter(test=test).order_by("id"):
            latest[control.class_group_id] = control.kind
        sat = set(
            Attempt.objects.filter(test=test, submitted_at__isnull=False).values_list("class_group_id", flat=True)
        )
        window_over = now >= test.closes_at
        for audience in TestAudience.objects.filter(test=test).select_related("class_group"):
            kind = latest.get(audience.class_group_id)
            if kind == SittingControl.Kind.OPENED:
                finished = False
            elif window_over:
                finished = True
            else:
                finished = kind == SittingControl.Kind.CLOSED and audience.class_group_id in sat
            if not finished:
                still.add(audience.class_group.name)
    return sorted(still)


def answers_held(test, now=None) -> bool:
    """Are this test's right answers still held back from every student?"""
    return bool(classes_still_to_finish(test, now))


# -- release -------------------------------------------------------------------------------------


def why_not_releasable(test, class_group_id) -> str:
    """Why this class's scores cannot be released now, or "" if they can."""
    if sitting.is_practice(test):
        return PRACTICE_NOT_RELEASED
    open_now = Attempt.objects.filter(test=test, class_group_id=class_group_id, submitted_at__isnull=True).count()
    if open_now:
        return f"{open_now} student{' is' if open_now == 1 else 's are'} still sitting it."
    if test.state == Test.State.PUBLISHED and sitting.sitting_open(test, class_group_id):
        return "Its sitting is still open. Close it, or wait until the test closes."
    if not Attempt.objects.filter(test=test, class_group_id=class_group_id, submitted_at__isnull=False).exists():
        return "Nobody in this class has sat it yet."
    return ""


def corrections_for(test, items, keys, attempt, answers) -> List[dict]:
    """The student's own paper as they saw it, with what they chose and what was right."""
    by_position = sorted(items, key=lambda i: i.position)
    out = []
    order = paper.order_for(attempt.seed, len(by_position), test.shuffle_questions)
    for number, at in enumerate(order, start=1):
        item = by_position[at]
        shown = paper.option_order_for(attempt.seed, item.pk, len(item.options), test.shuffle_options)
        letter = {index: LETTERS[place] for place, index in enumerate(shown)}
        chosen = answers.get(item.pk)
        key = keys[item.pk]
        out.append(
            {
                "number": number,
                "stem": item.stem,
                "image_alt": item.image_alt if item.image_key else "",
                "options": [{"letter": letter[i], "text": item.options[i]} for i in shown],
                "chosen": letter.get(chosen) if chosen is not None else None,
                "chosen_text": item.options[chosen] if chosen is not None else "",
                "right_letter": letter[key],
                "right_text": item.options[key],
                "right": chosen == key,
                "marks": item.marks,
                "explanation": item.explanation,
            }
        )
    return out


def release_as(actor, school, test_id, class_group_id) -> TestRelease:
    """Release one class's scores: freeze them, with each student's corrections.

    The corrections are frozen here whether or not they may be shown yet; whether a
    student's page hands them out is `answers_held()`'s question, asked on each read."""
    from gradebook.models import Subject

    from .setting import subject_and_level

    with transaction.atomic():
        test = _test(
            actor, school, test_id, access.marks_test,
            "Scores are released by the test's teachers or the principal.", lock=True,
        )
        audience = set(TestAudience.objects.filter(test=test).values_list("class_group_id", flat=True))
        if class_group_id not in audience:
            raise Refused("That class does not sit this test.")
        if class_group_id not in access.classes_of(actor, school, test, audience):
            raise NotAllowed("You release scores only for the classes you teach this subject to.")
        if test.state == Test.State.PUBLISHED:
            sitting.settle_all(test, timezone.now())
        if sitting.is_practice(test):
            raise Refused(PRACTICE_NOT_RELEASED)
        if TestRelease.objects.filter(test=test, class_group_id=class_group_id, restore__isnull=True).exists():
            raise Refused("This class's scores are released already.")
        why = why_not_releasable(test, class_group_id)
        if why:
            raise Refused(why)
        items = list(TestItem.objects.filter(test=test).order_by("position"))
        keys = keys_of(test, items)
        answers = answers_of(test)
        subject_id, _ = subject_and_level(test)
        subject = Subject.objects.get(pk=subject_id).name
        closed = [
            a for a in latest_attempts(test).values() if not a.is_open and a.class_group_id == class_group_id
        ]
        group = closed[0].class_group if closed else None
        release = TestRelease.objects.create(
            test=test, class_group_id=class_group_id,
            class_group_name=group.name if group else "", count=len(closed),
            by_id=actor.pk, by_name=name_of(actor), role=_role_word(actor, school, test),
        )
        rows = []
        for a in closed:
            got = answers.get(a.pk, {})
            m = mark(items, keys, got)
            rows.append(
                ReleasedTestScore(
                    release=release, test=test, student_membership_id=a.student_membership_id,
                    student_name=a.student_name, admission_number=a.admission_number,
                    class_group_name=a.class_group_name, test_title=test.title, subject_name=subject,
                    attempt_number=a.number, score=m.score, out_of=m.out_of, right=m.right, questions=len(items),
                    corrections=corrections_for(test, items, keys, a, got),
                    released_by_name=release.by_name, released_at=release.at,
                )
            )
        ReleasedTestScore.objects.bulk_create(rows)
    return release


def restore_as(actor, school, release_id, reason) -> TestReleaseRestore:
    """Undo a release, with a reason: the principal alone. Its scores stop showing; they
    are not deleted, and a CA mark already sent is not touched."""
    reason = plain(reason, limit=MAX_WHY, what="The reason", lines=False)
    if not access.may_open_tests(actor, school):
        raise NotYours("There is no such release here.")
    if not access.restores(actor, school):
        raise NotAllowed("A release is restored by the principal, with a reason.")
    with transaction.atomic():
        release = TestRelease.objects.select_for_update().filter(pk=release_id).first()
        if release is None:
            raise NotYours("There is no such release here.")
        if TestReleaseRestore.objects.filter(release=release).exists():
            raise Refused("This release has been restored already.")
        return TestReleaseRestore.objects.create(release=release, reason=reason, by_id=actor.pk, by_name=name_of(actor))


# -- what a student and a parent see ------------------------------------------------------------


def live_scores():
    """Released scores whose release has not been restored, of tests that asked for the exam
    PIN. A practice test's never show (audit F-08), even if a row was written for one."""
    return ReleasedTestScore.objects.filter(release__restore__isnull=True).exclude(
        test__require_pin=False, test__may_send_to_ca=False
    )


def _summary(r) -> dict:
    return {
        "test_title": r.test_title,
        "subject": r.subject_name,
        "score": r.score,
        "out_of": r.out_of,
        "percent": round(100 * r.score / r.out_of) if r.out_of else None,
        "released_at": r.released_at.isoformat(),
        "released_by": r.released_by_name,
    }


@dataclass
class StudentScores:
    name: str
    class_name: str
    this: dict
    earlier: List[dict]


def _proved_for_scores(school, code, number, pin):
    """(test, student) for the three, or None for every failure alike: as the door's, and
    the student must have sat the test."""
    code = sitting.typed_code(code)
    if len(code) != sitting.CODE_LENGTH or not number:
        return None
    test = Test.objects.filter(
        code_digest=sitting.code_digest(school.pk, code), state__in=MARKED_STATES
    ).select_related("term").first()
    if test is None:
        return None
    # Always the PIN: a practice test has nothing released to open (audit F-08).
    student = pins.check(school, test.term, number, pin)
    if student is None:
        return None
    if not Attempt.objects.filter(test=test, student_membership_id=student.pk).exists():
        return None
    return test, student


def student_scores(school, *, code, admission_number, pin, address, device="", now=None) -> StudentScores:
    """A student's own released scores, behind the door's three and its throttle.

    The corrections are left out, and `answers_held` says so, while any class has still
    to finish the paper (`classes_still_to_finish()`): the score shows, the answers wait."""
    if not sitting._here(school):
        raise sitting.NotOpened()
    number = sitting._number(admission_number)
    keys = sitting.guarded(school, device, address)
    proved = _proved_for_scores(school, code, number, pin)
    if proved is None:
        sitting.count_a_wrong_try(*keys)
        raise sitting.NotOpened()
    test, student = proved
    mine = list(live_scores().filter(student_membership_id=student.pk).order_by("-released_at", "-id"))
    this = next((r for r in mine if r.test_id == test.pk), None)
    if this is None:
        raise sitting.Closed(NOT_RELEASED)
    seen, earlier = {test.pk}, []
    for r in mine:
        if r.test_id not in seen:
            seen.add(r.test_id)
            earlier.append(_summary(r))
    held = answers_held(test, now)
    return StudentScores(
        name=this.student_name,
        class_name=this.class_group_name,
        this={
            **_summary(this),
            "right": this.right,
            "questions": this.questions,
            # Never the frozen list while it is held: an empty one, so that nothing
            # downstream can show what this left in.
            "corrections": [] if held else this.corrections,
            "answers_held": held,
            "answers_held_why": ANSWERS_HELD if held else "",
        },
        earlier=earlier,
    )


def family_scores_as(actor, school) -> List[dict]:
    """Each child this login stands for here, with their released scores. Nothing else."""
    if not getattr(actor, "is_authenticated", False) or not sitting._here(school):
        return []
    roles = set(actor.roles_at(school))
    children = Membership.objects.none()
    if Role.PARENT.value in roles:
        children = Membership.objects.filter(school=school, role=Role.STUDENT, guardianships__guardian=actor)
    if Role.STUDENT.value in roles:
        children = children | Membership.objects.filter(school=school, role=Role.STUDENT, user=actor)
    out = []
    for child in children.distinct().select_related("user").order_by("user__full_name", "pk"):
        released = list(live_scores().filter(student_membership_id=child.pk).order_by("-released_at", "-id"))
        seen, scores = set(), []
        for r in released:
            if r.test_id not in seen:
                seen.add(r.test_id)
                scores.append(_summary(r))
        sat = set(
            Attempt.objects.filter(student_membership_id=child.pk, submitted_at__isnull=False)
            # A practice test's scores never come, so it is not "waiting".
            .exclude(test__require_pin=False, test__may_send_to_ca=False)
            .values_list("test_id", flat=True)
        )
        out.append(
            {
                "student_id": child.pk,
                "name": sitting.name_of(child),
                "class_name": released[0].class_group_name if released else "",
                "scores": scores,
                "waiting": len(sat - seen),
            }
        )
    return out


__all__ = [
    "ANSWERS_HELD",
    "NOT_RELEASED",
    "PRACTICE_NOT_RELEASED",
    "StudentScores",
    "answers_held",
    "classes_still_to_finish",
    "corrections_for",
    "family_scores_as",
    "live_scores",
    "release_as",
    "restore_as",
    "student_scores",
    "why_not_releasable",
]
