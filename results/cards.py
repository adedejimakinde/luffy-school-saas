"""The report card snapshot: what one child's card said, at the moment it said it.

Task 3. Everything else in this app freezes one *section* of a card —
`ratings` the conduct, `comments` the remarks, `sessions` the year's last line.
This module freezes the card **itself**: the marks, the totals, the grades, the
position, and above all the row that records that a card went home at all.

## `ReleasedCard` is the artefact, and it is written unconditionally

One row per child on the roster at release, inside the release transaction,
whatever else is or is not true — no marks, no ratings, the conduct section
switched off school-wide, nothing decided. The model docstring has the history;
the short version is that a guard asking *has a card gone home for this child?*
used to have four places to look and a placement join to fall back on, and the
fallback gave the wrong answer for any child the office had moved.

**This is the one guarantee no constraint can hold.** No `CHECK` can say "a row
exists for every child on a roster this transaction has already moved past". It
is held here, and pinned by `test_a_school_with_everything_off_still_freezes_a_card`
plus the control that shows that test failing when the write is made
conditional. If that test is ever deleted, the guarantee is gone and nothing
will say so.

## Written first, before the sections

`services.release()` calls this ahead of `ratings`, `comments` and `sessions`,
because they now hang off the row this writes. That inverts the old "in the
order they print" note over there, which is now the order of the *sections*
under a parent that must exist first.

## Everything the card prints is copied

Not joined to. Every join out of a frozen row goes through something a school
may legitimately edit — its own name, the class's name, the child's name, a
subject's name, an assessment's name, the grading scale, the trait list — and
a released card does not change. `ReleasedTraitRating` made the argument for
trait names; this applies it to the rest of the page.

The two most easily missed are `student_name` and `school_name`, because both
come from `accounts`, which is a **shared** schema whose rows change for reasons
that have nothing to do with this school.

## The grade letter is copied, and must never be re-derived

`grades.grade_for()` is called **here**, at freeze time, and its answer is
stored. Nothing downstream may call it on a frozen percentage. A school
replacing its scale is an ordinary act, and re-deriving would silently rewrite
the letters on every card already in a parent's hand while the percentages
beside them stayed put — a card that said B2 quietly beginning to say B3.

The scale is read **once per release**, not once per child, which is what makes
a class's cards internally consistent with each other.

## What is not frozen

**The class average**, which is computed on demand — it is a statement about the
other forty-four children, and freezing it would leave forty-four unrevised
cards contradicting a revised one. **The promotion decision**, which is read
live from the append-only `PromotionDecision`. `ReleasedCard`'s docstring has
both arguments in full.
"""

from django.db.models import Prefetch

from . import grades, positions
from .models import (
    ReleasedAssessmentScore,
    ReleasedCard,
    ReleasedSubjectResult,
)
from .services import ResultsError


class CardsError(ResultsError):
    """A card could not be frozen or read as asked."""


def _student_names(membership_ids) -> dict[int, str]:
    """`membership_id -> the child's name`, in one query across the shared schema.

    A dictionary rather than a per-child lookup because release calls this for a
    whole roster, and because the name is copied — see the module docstring.
    Falls back to the empty string rather than raising: a membership whose user
    row has gone is a data problem that must not stop a release, and a card with
    a blank name is fixable while a refused release is a school unable to
    publish results.
    """
    from accounts.models import Membership

    return {
        row["pk"]: row["user__full_name"] or ""
        for row in Membership.objects.filter(pk__in=membership_ids).values(
            "pk", "user__full_name"
        )
    }


def _assessments_for(term, subject_ids):
    """Every assessment of these subjects, in the order the card prints them.

    Ordered by `(subject name, id)` and **not** by `Assessment.Meta.ordering`,
    which ends in `name` — alphabetical, so a card would print "Exam, First CA,
    Second CA". Schools create assessments in the order they are sat, so
    creation order is closer to right. It is still a guess: `Assessment` has no
    explicit print order, and the fix is a `position` field on it, filed rather
    than smuggled in here.
    """
    from gradebook.models import Assessment

    if not subject_ids:
        return []
    return list(
        Assessment.objects.filter(term=term, subject_id__in=subject_ids)
        .select_related("subject")
        .order_by("subject__name", "id")
    )


def _scores_for(assessments, student_ids) -> dict[tuple[int, int], int]:
    """`(student, assessment) -> value`, in one query. Absent means unmarked."""
    from gradebook.models import Score

    if not assessments or not student_ids:
        return {}
    return {
        (row["student_membership_id"], row["assessment_id"]): row["value"]
        for row in Score.objects.filter(
            assessment__in=assessments, student_membership_id__in=student_ids
        ).values("student_membership_id", "assessment_id", "value")
    }


def freeze_for_release(sheet) -> int:
    """Copy this class's cards as they read now. Returns the number written.

    Called by `results.services.release()` **first**, inside the transaction
    that writes the release row, so that the section freezes underneath it have
    a parent to hang off.

    Reads everything from `positions.class_results()` — one roster read and one
    aggregate read — so that every number on every card in the class comes from
    the same instant. Reading them per child would let a mark landing mid-freeze
    put one child's position above another's higher percentage, which is the
    failure `ClassResults` was extracted to prevent.
    """
    results = positions.class_results(sheet.class_group, sheet.term)
    roster = results.student_ids
    if not roster:
        return 0

    term = sheet.term
    school_name = _school_name()
    names = _student_names(roster)
    # Once per release, not once per child: a class's cards have to agree with
    # each other about what 72.00 is worth.
    bands = grades.scale()

    subjects = _subjects_in_print_order(results.subject_ids)
    assessments = _assessments_for(term, results.subject_ids)
    scores = _scores_for(assessments, roster)

    cards = [
        _card_for(sheet, term, school_name, names, results, student_id)
        for student_id in roster
    ]
    ReleasedCard.objects.bulk_create(cards)

    lines, cells = [], []
    for card in cards:
        student_id = card.student_membership_id
        for position, subject in enumerate(subjects, start=1):
            lines.append(
                _subject_line(card, subject, position, results, student_id, bands)
            )
        for position, assessment in enumerate(assessments, start=1):
            cells.append(_score_cell(card, assessment, position, scores, student_id))

    ReleasedSubjectResult.objects.bulk_create(lines)
    ReleasedAssessmentScore.objects.bulk_create(cells)
    return len(cards)


def _school_name() -> str:
    """The school this connection is on, by name, copied onto every card."""
    from .services import school_on_this_connection

    return str(school_on_this_connection())


def _subjects_in_print_order(subject_ids):
    """The subjects this class was marked in, ordered by name.

    Not by primary key, which is what `ClassResults.subject_ids` sorts by and is
    arbitrary to a school — the same complaint issue #24 makes about broadsheet
    row order. The order is frozen onto each line, so a school reordering its
    subject list later cannot reshuffle a card that has gone home.
    """
    from gradebook.models import Subject

    if not subject_ids:
        return []
    return list(Subject.objects.filter(pk__in=subject_ids).order_by("name", "pk"))


def _card_for(sheet, term, school_name, names, results, student_id) -> ReleasedCard:
    """One child's card row. **Never conditional** — see the module docstring."""
    scored = available = 0
    for subject_id in results.subject_ids:
        subject_scored, subject_available = results.scored_and_available(
            student_id, subject_id
        )
        scored += subject_scored
        available += subject_available

    return ReleasedCard(
        sheet=sheet,
        student_membership_id=student_id,
        term=term,
        version=1,
        session=term.session,
        term_name=term.name,
        class_group=sheet.class_group,
        class_group_name=str(sheet.class_group),
        school_name=school_name,
        student_name=names.get(student_id, ""),
        total_scored=scored,
        total_available=available,
        own_average=results.averages.get(student_id),
        position=results.positions.get(student_id),
        roster_size=len(results.student_ids),
        released_by_id=None,
    )


def _subject_line(card, subject, position, results, student_id, bands):
    scored, available = results.scored_and_available(student_id, subject.pk)
    percentage = results.percentage(student_id, subject.pk)
    band = grades.grade_for(percentage, bands=bands)

    return ReleasedSubjectResult(
        card=card,
        subject=subject,
        subject_name=subject.name,
        subject_code=subject.code,
        position=position,
        total_scored=scored,
        total_available=available,
        percentage=percentage,
        grade_letter=band.letter if band else "",
        grade_remark=band.remark if band else "",
        subject_position=results.subject_position(student_id, subject.pk),
    )


def _score_cell(card, assessment, position, scores, student_id):
    return ReleasedAssessmentScore(
        card=card,
        subject=assessment.subject,
        assessment=assessment,
        assessment_name=assessment.name,
        max_score=assessment.max_score,
        position=position,
        score=scores.get((student_id, assessment.pk)),
    )


# ---------------------------------------------------------------------------
# Reading a frozen card
# ---------------------------------------------------------------------------


def card_for(membership, term) -> ReleasedCard | None:
    """This child's card for that term, or `None` if none went home.

    **The earliest release, then its highest version**, and both halves matter.

    A child can collect more than one card for one term in two ways that
    compose. Two sheets: release JSS 1A, move the child to JSS 3B, release JSS
    3B — `ClassPlacement` allows one group per child per term, so "a child is on
    exactly one roster" is true at any instant and false over time. Two
    versions: a revision (task 8) writes a new row and both stand.

    The card is the **first** release, because a released card keeps saying what
    it said and a later release cannot reach backwards into one already in a
    parent's hand — the rule `0010`, `0011` and issue #27 all turn on. Within
    that release, the **latest** version is what holds, because that is what a
    revision means.

    Ordered explicitly on `(created_at, id)` and then on `version`, never left
    to `Meta.ordering`: `QuerySet.first()` adds an `ORDER BY` on the primary key
    when a queryset has none, so a test asserting merely that an ordering exists
    proves nothing — task 9 learned that twice. A "which card is this" that
    resolves arbitrarily between two rows is one that changes when nothing
    changed.
    """
    student_id = getattr(membership, "pk", membership)
    first = (
        ReleasedCard.objects.filter(
            term=term, student_membership_id=student_id, version=1
        )
        .order_by("created_at", "id")
        .first()
    )
    if first is None:
        return None
    return (
        ReleasedCard.objects.filter(
            sheet_id=first.sheet_id, student_membership_id=student_id
        )
        .order_by("-version", "-id")
        .first()
    )


def a_card_went_home(membership, term) -> bool:
    """The question every release guard asks, and the one row that answers it.

    Deliberately **not** "is there a frozen rating / remark / session line",
    which is what the guards had to ask before this table existed, and
    deliberately not a placement join, which answers a different question and
    gives the wrong answer for any child the office has moved. See
    `ReleasedCard`.

    Any version counts. A revision does not un-send the card that went home.
    """
    return ReleasedCard.objects.filter(
        term=term, student_membership_id=getattr(membership, "pk", membership)
    ).exists()


def cards_by_student(sheet) -> dict[int, ReleasedCard]:
    """`student_membership_id -> the card this release wrote`, for one sheet.

    How `ratings`, `comments` and `sessions` find the row to hang their frozen
    sections off. They run **after** `freeze_for_release()` inside the same
    transaction, so every child on the roster has one.

    Version 1 only. A revision (task 8) freezes its own sections against its own
    card, and reaching for "the latest version" here would attach a first
    release's conduct section to a second release's card.
    """
    return {
        card.student_membership_id: card
        for card in ReleasedCard.objects.filter(sheet=sheet, version=1)
    }


def card_lines(card):
    """One card's subject lines and score cells, fetched by `card_id`.

    Two queries, whatever the card's size. The row-per-cell shape is paid for
    here — see `ReleasedAssessmentScore` — and the read path is prefetch by card
    id from the start rather than a lookup per line, because task 7 renders
    forty-five of these into a PDF in one job.
    """
    lines = list(card.subject_results.all())
    cells = list(card.assessment_scores.all())
    by_subject = {}
    for cell in cells:
        by_subject.setdefault(cell.subject_id, []).append(cell)
    return [(line, by_subject.get(line.subject_id, [])) for line in lines]


def cards_on(sheet):
    """Every card that sheet's release wrote, with its lines, in few queries.

    `Prefetch` rather than a join per card: task 7's PDF job walks a whole class
    and a per-card query there is forty-five round trips inside a Celery task.
    """
    return list(
        ReleasedCard.objects.filter(sheet=sheet)
        .prefetch_related(
            Prefetch("subject_results"), Prefetch("assessment_scores")
        )
        .order_by("student_membership_id", "version")
    )


__all__ = [
    "CardsError",
    "a_card_went_home",
    "cards_by_student",
    "card_for",
    "card_lines",
    "cards_on",
    "freeze_for_release",
]
