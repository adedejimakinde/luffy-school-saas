"""Where a child came in their class, and in each subject.

Two numbers a Nigerian report card is judged on, and neither exists without a
class to be out of — which is what `academics.ClassPlacement` is for. Position
is reckoned over the **roster of the class for that term**, not over everybody
who happens to have a mark: a child who moved from JSS 1A to JSS 1B in January
is ranked among the children they were actually taught with.

## Dense ranking

Two children tied at 3rd means the next one is **4th, not 5th**. A tie does not
consume the position below it. Standard Nigerian practice, and the reason is
practical rather than mathematical: a school with a big tie at the top would
otherwise print "12th" on a card where eleven children are ahead of nobody.

    scores   88  74  74  61
    dense     1   2   2   3        <- what this module does
    standard  1   2   2   4        <- what it deliberately does not do

Hardcoded, and it may not stay that way — a school could reasonably want
standard competition ranking. `dense_positions()` is the one place it is
decided, so becoming a per-school setting is a change to one function rather
than to every caller.

## Ties are an equality test, so the number being compared has to be exact

Positions are decided by two children having *the same* score. That makes this
one of the few places where the difference between `Decimal` and `float`
changes an answer somebody reads: `float` equality on a computed percentage is
a coin toss on the last bit, and the visible symptom is two children printed
with identical percentages and different positions — which no teacher can
explain to a parent.

So percentages are `Decimal`, and **ranking compares the value as printed**,
quantised to two places before anything is sorted. Ranking on the unrounded
value and printing the rounded one is the same failure wearing a different hat:
75.004 and 74.996 both print as 75.00 and would be given different positions.

## "Not marked" is not zero

`gradebook` keeps that distinction in the table by having no row at all, and
this module has to keep it in the arithmetic. A child with no marks in a
subject has **no position** in it — `None`, not last. A child with no marks at
all has no overall position either.

Ranking them last would be a specific lie: it says the school assessed them and
they scored nothing. A child off sick for the term, or one who joined in week
ten, would be printed bottom of the class on a card that goes home.

## The overall average is the child's own, across their subjects

Settled for this phase, and worth stating because there are two defensible
readings and they disagree:

    Maths    10/10  = 100%
    English  40/80  =  50%

    mean of the subject percentages   = 75.0%   <- what this module does
    total scored over total available = 55.6%   (50/90)

The first is what "average across their subjects" means on a Nigerian report
card, and it is the one that does not let a subject with a large `max_score`
quietly outweigh the rest. The second is a weighted average pretending not to
be one.

It is **not** a class average. That is computed on demand and is staff-only,
for the reason `class_average()` gives.

## Who may see a position

Staff, and no one else — see `results.api`. Not a rendering preference: Nigerian
secondary schools do not print position on report cards, and parents and
students see the cumulative average only. The rule is enforced at the serializer
rather than the template, because omitting a field from a card while leaving it
in the JSON is the same leak with an extra step.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

from django.db.models import Sum

from academics.models import ClassPlacement
from gradebook.models import Score

#: Two decimal places, which is what a report card prints. Ranking compares the
#: quantised value, so what decides a tie is the number a parent can see.
PLACES = Decimal("0.01")

#: **Stated, not inherited.** `Decimal.quantize()` with no `rounding=` reads
#: `decimal.getcontext().rounding`, which defaults to `ROUND_HALF_EVEN` —
#: banker's rounding, where 74.505 goes down to 74.50 and 75.505 goes down to
#: 75.50. That is not what a Nigerian report card does, it is not explainable to
#: a parent at a grade boundary, and because `dense_positions()` ties on the
#: quantised value it would silently decide positions too.
#:
#: Worse, that context is thread-local and mutable: any library in the process
#: calling `decimal.setcontext()` would change every percentage and every
#: position on the platform with no code change here. A module whose thesis is
#: that this number is exact cannot leave its rounding to ambient state.
#:
#: The *divisions* below still run in the ambient context, at its 28 significant
#: digits, and that is left alone on purpose rather than overlooked. A division
#: that does not terminate cannot land exactly on a half at two places, and one
#: that does terminate is exact — so the digit the context decides, twenty-odd
#: places out, cannot move a percentage across a `PLACES` boundary or make two
#: children tie who otherwise would not. Only the quantise below can do that,
#: and it is stated.
ROUNDING = ROUND_HALF_UP

#: The percentage every score is expressed as before anything is compared.
FULL_MARKS = Decimal(100)


def _round(value: Decimal) -> Decimal:
    return value.quantize(PLACES, rounding=ROUNDING)


def _percentage(scored: int, available: int) -> Decimal | None:
    """A mark as a percentage, or `None` when there is nothing to divide by.

    `available` is zero exactly when the child has no marks, because it sums
    the `max_score` of the assessments they were *actually marked on* — the
    rule `ScoreQuerySet.total_for()` sets out. Returning `None` rather than
    `Decimal(0)` is what keeps "not marked" out of the ranking.
    """
    if not available:
        return None
    return _round(Decimal(scored) * FULL_MARKS / Decimal(available))


def roster_ids(class_group, term) -> list[int]:
    """Who sat in this class this term. The set a position is out of."""
    return ClassPlacement.objects.student_ids(class_group, term)


def _subject_totals(term, student_ids) -> dict[tuple[int, int], tuple[int, int]]:
    """`(student, subject) -> (scored, available)`, in one query.

    `.order_by()` is load-bearing and is not a leftover. `Score.Meta.ordering`
    is `["assessment", "student_membership_id"]`, and Django appends ordering
    columns to the GROUP BY of a `.values().annotate()` — so without clearing
    it the rows come back grouped by assessment as well, which is one row per
    mark and a "total" that is just the mark. `gradebook.api._totals_for_everyone`
    carries the same note, and it is the same bug both times.
    """
    if not student_ids:
        return {}
    grouped = (
        Score.objects.filter(
            assessment__term=term, student_membership_id__in=student_ids
        )
        .values("student_membership_id", "assessment__subject_id")
        .annotate(scored=Sum("value"), available=Sum("assessment__max_score"))
        .order_by()
    )
    return {
        (row["student_membership_id"], row["assessment__subject_id"]): (
            row["scored"] or 0,
            row["available"] or 0,
        )
        for row in grouped
    }


@dataclass(frozen=True)
class ClassResults:
    """Everything a broadsheet needs, derived from **one** read of the marks.

    This shape exists because of a bug rather than for tidiness. The first
    version asked the database separately for each number a row needs — the
    roster, then each subject's percentages, then each subject's positions,
    then the averages, then the class average — which is both slow and *wrong*.

    Slow: four queries per subject, each one re-aggregating the whole class's
    marks across every subject and throwing away all but one. Twelve subjects
    and forty-five children came to fifty-odd round trips for one page.

    Wrong, and this is the half that matters: the gradebook saves one mark per
    cell-blur, so a teacher marking while another reads the broadsheet is the
    ordinary case. Under READ COMMITTED each of those queries sees a different
    moment. A mark landing between the percentage read and the position read
    produces a row showing 88.00 in 1st place above a row showing 91.00 —
    exactly the "identical percentages, different positions" failure this
    module was written to prevent, arriving by a different route.

    Everything below is computed in Python from `_subject_totals()`, so every
    number on the page comes from the same instant.

    The roster is still a second query, and the residue is honest and small: a
    child placed between the two reads appears in `student_ids` with no marks
    and renders blank. Making even that atomic would need `REPEATABLE READ`,
    which cannot be set inside the transaction `TestCase` wraps every test in.
    """

    student_ids: list[int]
    #: Only subjects this class was actually marked in this term — see
    #: `class_results()` for why the full `Subject` table is the wrong list.
    subject_ids: list[int]
    percentages: dict[tuple[int, int], Decimal]
    subject_positions: dict[tuple[int, int], int]
    averages: dict[int, Decimal]
    positions: dict[int, int]
    class_average: Decimal | None

    def percentage(self, student_id, subject_id) -> Decimal | None:
        return self.percentages.get((student_id, subject_id))

    def subject_position(self, student_id, subject_id) -> int | None:
        return self.subject_positions.get((student_id, subject_id))


def class_results(class_group, term) -> ClassResults:
    """The whole broadsheet, from one roster read and one aggregate read.

    `subject_ids` is drawn from the marks rather than from `Subject.objects`,
    and the difference is visible on the page. The subject table is per school
    and keeps retired subjects on purpose — `Subject.is_active` says "a subject
    no longer taught, kept because old scores name it" — so listing all of them
    puts an all-blank Technical Drawing column on a class that has not been
    taught it for three sessions, alongside every subject the school teaches to
    other year groups. What a broadsheet should show is the subjects this class
    was marked in, which the aggregate already knows.
    """
    students = roster_ids(class_group, term)
    totals = _subject_totals(term, students)

    percentages: dict[tuple[int, int], Decimal] = {}
    per_student: dict[int, list[Decimal]] = {student: [] for student in students}
    subject_ids: list[int] = []

    for (student_id, subject_id), (scored, available) in totals.items():
        percentage = _percentage(scored, available)
        if percentage is None:
            continue
        percentages[(student_id, subject_id)] = percentage
        per_student[student_id].append(percentage)
        if subject_id not in subject_ids:
            subject_ids.append(subject_id)

    averages = {
        student_id: _round(sum(marks) / Decimal(len(marks)))
        for student_id, marks in per_student.items()
        if marks
    }

    subject_positions: dict[tuple[int, int], int] = {}
    for subject_id in subject_ids:
        in_subject = {
            student_id: value
            for (student_id, other), value in percentages.items()
            if other == subject_id
        }
        for student_id, position in dense_positions(in_subject).items():
            subject_positions[(student_id, subject_id)] = position

    return ClassResults(
        student_ids=students,
        subject_ids=sorted(subject_ids),
        percentages=percentages,
        subject_positions=subject_positions,
        averages=averages,
        positions=dense_positions(averages),
        class_average=(
            _round(sum(averages.values()) / Decimal(len(averages)))
            if averages
            else None
        ),
    )


def subject_percentages(class_group, term, subject_id) -> dict[int, Decimal]:
    """Every rostered child's percentage in one subject.

    Children with no mark in it are **absent from the mapping** rather than
    present with a zero or a `None`. A caller ranking this gets only the
    children who can be ranked, and a caller displaying it asks with `.get()`
    and renders a blank.

    A convenience over `class_results()` for a caller that wants one subject.
    Anything rendering a whole page should use `class_results()` directly, so
    that every number on it comes from one read.
    """
    results = class_results(class_group, term)
    return {
        student_id: value
        for (student_id, other), value in results.percentages.items()
        if other == subject_id
    }


def overall_percentages(class_group, term) -> dict[int, Decimal]:
    """Every rostered child's own average across the subjects they were marked in.

    Not a class average, and not a weighted one — see the module docstring for
    the worked example that separates the two readings. Children with no marks
    at all are absent from the mapping, for the reason `subject_percentages()`
    leaves them out of a single subject.

    **The denominator is that child's own marked-subject count**, which is what
    makes this the child's own average and is also its sharpest edge: a child
    marked only in Mathematics and scoring 100 averages 100.00 and outranks a
    child marked in ten subjects averaging 95. See the module docstring.
    """
    return class_results(class_group, term).averages


def dense_positions(values: Mapping[int, Decimal]) -> dict[int, int]:
    """Dense ranking, highest first: 1, 2, 2, 3.

    The single place the tie rule is decided. A school wanting standard
    competition ranking (1, 2, 2, 4) changes this function and nothing else.

    Ties are found by equality on the `Decimal` handed in, so a caller that
    quantises differently would get a different answer — which is why every
    value this module produces goes through `_round()`, and why `_round()` is
    the only place a rounding mode is named.
    """
    ordered = sorted(set(values.values()), reverse=True)
    position_of = {value: index + 1 for index, value in enumerate(ordered)}
    return {student: position_of[value] for student, value in values.items()}


def subject_positions(class_group, term, subject_id) -> dict[int, int]:
    """Position in one subject, out of the class roster for that term."""
    results = class_results(class_group, term)
    return {
        student_id: position
        for (student_id, other), position in results.subject_positions.items()
        if other == subject_id
    }


def class_positions(class_group, term) -> dict[int, int]:
    """Position in class, on the child's own average across their subjects."""
    return class_results(class_group, term).positions


def class_average(class_group, term) -> Decimal | None:
    """The class's average of its children's averages. **Staff only.**

    Computed here and deliberately **never stored**, on the reasoning settled
    for this phase: a stored copy is a fact about forty-five other children,
    and a later revision to any one of them would leave a released card
    carrying a number that disagrees with the rows it claims to summarise.
    Position is the opposite case and *is* frozen at release — it depends on
    everyone else's scores at that moment and cannot be recomputed later
    without changing.

    `None` when nobody in the class has a mark, which is the honest answer and
    the one a caller can render as a dash. Zero would claim the class sat
    exams and scored nothing.

    Delegates rather than re-deriving, and that is not tidiness. This function
    used to compute the mean itself and quantise it with a bare
    `.quantize(PLACES)` — inheriting `ROUND_HALF_EVEN` from the decimal context
    while `class_results()` rounded the same mean with `ROUNDING`. At a mean of
    74.505 the two disagreed: 74.50 here, 74.51 there. One number, computed two
    ways, printed differently depending on which caller asked. There is now one
    way to compute it.
    """
    return class_results(class_group, term).class_average


__all__ = [
    "ClassResults",
    "class_average",
    "class_positions",
    "class_results",
    "dense_positions",
    "overall_percentages",
    "roster_ids",
    "subject_percentages",
    "subject_positions",
]
