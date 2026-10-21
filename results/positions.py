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

## A subject with a paper unmarked has no total, and its child is not ranked

`gradebook` keeps "not marked" apart from nought by having no row, and a
subject has as many papers as it has `Assessment`s for the term. A child is
**whole in a subject** when every one of those papers has a mark for them. A
paper still unmarked is the teacher's work not yet done, not a child who sat
the paper and scored nothing, so:

- the subject has **no total on the card a family reads**, and is left out of
  the card's summary (marks obtained, percentage) and its average. The marks that
  are in stay on the staff broadsheet, marked incomplete;
- the child is **ranked in a subject** only where they are whole in it, and
  **ranked in the class** only when they are whole in every subject the class
  was marked in. Ranking a child on the papers marked so far puts them above or
  below children who have been marked on more, which is the one number a parent
  would take to the school.

Everyone ranked is ranked as before: dense, on the average as printed. "Out of
N" is the number ranked, not the roster, and **the class average is the mean of
those children's averages** (labelled "Class average (ranked students)"): it
counts the children the ranking beside it counts. A child who is not ranked has no
position, and is not last. `ClassResults.averages` is untouched, and so is
everything built on it (the year's last line): the new fields below are
additions.

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
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Mapping

from django.db.models import Count, OuterRef, Subquery, Sum

from academics.models import ClassGroup, ClassPlacement, Term
from gradebook.models import Assessment, Score

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
#: `CONTEXT` below closes the rest of that hole.
ROUNDING = ROUND_HALF_UP

#: The percentage every score is expressed as before anything is compared.
FULL_MARKS = Decimal(100)

#: **The whole calculation runs in this, not in whatever the caller left set.**
#:
#: Pinning `ROUNDING` alone was not enough, and the gap is worth spelling out
#: because the first version of this module claimed to have closed it. A context
#: carries a *precision* as well as a rounding mode, and `prec` is thread-local
#: and mutable in exactly the same way. Two things follow from a small one:
#:
#: - `Decimal.quantize()` raises `InvalidOperation` when the quantised
#:   coefficient needs more digits than `prec`. At `prec=3`, quantising 74.505
#:   to two places wants four digits and raises — so a library calling
#:   `decimal.setcontext()` anywhere in the process turns every broadsheet on
#:   the platform into a 500, not a wrong number;
#: - the divisions lose their significant digits first. At `prec=3`,
#:   `6101 * 100 / 10000` comes back 61.0 rather than 61.01, and the printed
#:   percentage is wrong before any rounding decision is reached.
#:
#: 28 digits is CPython's own default, so this pins the arithmetic to what it
#: already does rather than changing any number — what it removes is the
#: possibility of somebody else changing it. `round_percentage()` still names `ROUNDING`
#: explicitly, which is belt and braces and costs nothing.
CONTEXT = Context(prec=28, rounding=ROUNDING)


def round_percentage(value: Decimal) -> Decimal:
    """Quantise to the two places every percentage here is compared at.

    **Public, and the single place any percentage in this app is rounded.**
    `results.sessions` combines these numbers into a session average and has to
    round the result the same way; a second `quantize()` over there would be a
    second rounding policy, which is exactly the divergence that
    `mean_percentage()` below was extracted to end. The module docstring's
    argument — that this number is exact, and cannot outsource its last step to
    thread-local ambient state — is not an argument about *this* module, it is
    an argument about the number.
    """
    with localcontext(CONTEXT):
        return value.quantize(PLACES, rounding=ROUNDING)


def mean_percentage(values) -> Decimal:
    """The mean of some already-quantised percentages, quantised again.

    One function because two callers used to do this inline and one of them
    rounded differently — see `class_average()`.

    **Public**, for the same reason `round_percentage()` is: a released term's
    broadsheet averages the *frozen* cards rather than live marks (issue #55),
    and computing that mean anywhere else would be a second rounding policy —
    which is the exact divergence this function was extracted to end.
    """
    with localcontext(CONTEXT):
        return round_percentage(sum(values) / Decimal(len(values)))


def _percentage(scored: int, available: int) -> Decimal | None:
    """A mark as a percentage, or `None` when there is nothing to divide by.

    `available` is zero exactly when the child has no marks, because it sums
    the `max_score` of the assessments they were *actually marked on* — the
    rule `ScoreQuerySet.total_for()` sets out. Returning `None` rather than
    `Decimal(0)` is what keeps "not marked" out of the ranking.
    """
    if not available:
        return None
    with localcontext(CONTEXT):
        return round_percentage(Decimal(scored) * FULL_MARKS / Decimal(available))


def roster_ids(class_group, term) -> list[int]:
    """Who sat in this class this term. The set a position is out of.

    For a caller inside a `ResultSheet`-locked block this is the wrong function:
    the lock reaches the sheet row and not `ClassPlacement`, so a second call
    here is a second answer. Those callers take `class_results()` once and read
    `student_ids` and `placements` off it — issues #43 and #60.

    The one exception wants the second answer: `omissions.record()`, at the end
    of a release, where the difference from the first read is the children
    placed while the release ran, and nothing frozen depends on it (#47).
    """
    return ClassPlacement.objects.student_ids(class_group, term)


def roster(class_group, term) -> dict[int, ClassPlacement]:
    """The roster as the placement rows themselves, keyed by membership id.

    `class_group` is selected in the same query because the one caller that
    needs the rows — `sessions._lines_for()` — asks each placement which group
    the child sat in, and a lazy load there would be one query per child.

    Insertion order is the queryset's order, which `ClassPlacement.Meta` makes
    `student_membership_id` within a group, so `list(roster(...))` is
    `roster_ids(...)`.
    """
    return {
        placement.student_membership_id: placement
        for placement in ClassPlacement.objects.roster(class_group, term)
        .select_related("class_group")
    }


def _subject_totals(term, student_ids) -> dict[tuple[int, int], tuple[int, int, int, int]]:
    """`(student, subject) -> (scored, available, papers marked, papers there are)`, in one query.

    The last two are what "whole" is made of: a child is whole in a subject when
    they have a mark for every paper the subject has this term. The count of
    papers is a subquery of the same statement and not a second read, so a paper
    added while this runs cannot make the two disagree, and the page is still two
    reads (the roster, then the marks).

    `.order_by()` is load-bearing and is not a leftover. `Score.Meta.ordering`
    is `["assessment", "student_membership_id"]`, and Django appends ordering
    columns to the GROUP BY of a `.values().annotate()` — so without clearing
    it the rows come back grouped by assessment as well, which is one row per
    mark and a "total" that is just the mark. `gradebook.api._totals_for_everyone`
    carries the same note, and it is the same bug both times.
    """
    if not student_ids:
        return {}
    papers = (
        Assessment.objects.filter(term=term, subject_id=OuterRef("assessment__subject_id"))
        .order_by()
        .values("subject_id")
        .annotate(n=Count("pk"))
        .values("n")
    )
    grouped = (
        Score.objects.filter(
            assessment__term=term, student_membership_id__in=student_ids
        )
        .values("student_membership_id", "assessment__subject_id")
        .annotate(
            scored=Sum("value"),
            available=Sum("assessment__max_score"),
            marked=Count("pk"),
            papers=Subquery(papers),
        )
        .order_by()
    )
    return {
        (row["student_membership_id"], row["assessment__subject_id"]): (
            row["scored"] or 0,
            row["available"] or 0,
            row["marked"],
            row["papers"],
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
    #: The placement rows `student_ids` came from, keyed by membership id, and
    #: the class group and term they were read for.
    #:
    #: They travel with the numbers because of issue #60. A caller holding the
    #: `ResultSheet` lock has asked "who sat here this term" exactly once, and
    #: anything downstream that asks again gets a *different* answer under READ
    #: COMMITTED — the lock is on the sheet row and not on `ClassPlacement`.
    #: `sessions._lines_for()` needed the placements and not merely the ids
    #: (it asks each one which group the child sat in), so carrying only the
    #: ids would have relabelled #46 rather than closed it.
    placements: dict[int, ClassPlacement]
    class_group: ClassGroup
    term: Term
    #: Only subjects this class was actually marked in this term — see
    #: `class_results()` for why the full `Subject` table is the wrong list.
    subject_ids: list[int]
    #: `(student, subject) -> (scored, available)`, the marks themselves before
    #: any percentage was taken of them. Kept rather than discarded because a
    #: report card prints "58/70" beside the percentage, and `results.cards`
    #: freezes both — re-reading the scores to recover the numerator would be a
    #: second read at a second instant, which is the whole failure this dataclass
    #: exists to prevent.
    #:
    #: `available` is the total this child was actually assessed on, not the
    #: subject's full mark scheme: a child who missed a CA has a smaller
    #: denominator, and their percentage is over what they sat. See
    #: `_subject_totals()`.
    totals: dict[tuple[int, int], tuple[int, int]]
    #: Over what was marked, whole subject or not: the staff's figure, and what
    #: the broadsheet shows beside "incomplete".
    percentages: dict[tuple[int, int], Decimal]
    #: Only where the child is whole in the subject (`whole`).
    subject_positions: dict[tuple[int, int], int]
    #: The child's average over **every subject they have a mark in**, partial
    #: ones included. Unchanged, and what the year's last line and the class
    #: average are built on. It is not the figure a family reads: that is
    #: `card_averages`.
    averages: dict[int, Decimal]
    #: Only the children whole in every subject, dense on `averages`. Everyone
    #: else is absent, which is "not ranked", not last.
    positions: dict[int, int]
    #: The mean of the ranked children's averages, so of the same children
    #: `positions` ranks. Null when nobody is ranked.
    class_average: Decimal | None
    #: `(student, subject)` pairs where every paper of the subject has a mark.
    whole: frozenset[tuple[int, int]]
    #: The children whole in every subject the class was marked in — the ones
    #: `positions` ranks. Empty when the class was marked in nothing.
    whole_students: frozenset[int]
    #: What the card a family reads is built from: totals and average over the
    #: whole subjects only. For a child whole in everything these are the same
    #: numbers as `totals` and `averages`.
    card_totals: dict[int, tuple[int, int]]
    card_averages: dict[int, Decimal]

    def scored_and_available(self, student_id, subject_id) -> tuple[int, int]:
        """`(0, 0)` for a subject this child has no mark in, which prints blank."""
        return self.totals.get((student_id, subject_id), (0, 0))

    def percentage(self, student_id, subject_id) -> Decimal | None:
        return self.percentages.get((student_id, subject_id))

    def subject_position(self, student_id, subject_id) -> int | None:
        return self.subject_positions.get((student_id, subject_id))

    def is_whole(self, student_id, subject_id) -> bool:
        """Every paper of this subject has a mark for this child."""
        return (student_id, subject_id) in self.whole

    def card_total(self, student_id) -> tuple[int, int]:
        """`(scored, available)` over the child's whole subjects; `(0, 0)` with none."""
        return self.card_totals.get(student_id, (0, 0))


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
    placements = roster(class_group, term)
    students = list(placements)
    counted = _subject_totals(term, students)
    totals = {key: (scored, available) for key, (scored, available, _, _) in counted.items()}

    percentages: dict[tuple[int, int], Decimal] = {}
    per_student: dict[int, list[Decimal]] = {student: [] for student in students}
    subject_ids: list[int] = []
    whole: set[tuple[int, int]] = set()

    for (student_id, subject_id), (scored, available, marked, papers) in counted.items():
        percentage = _percentage(scored, available)
        if percentage is None:
            continue
        percentages[(student_id, subject_id)] = percentage
        per_student[student_id].append(percentage)
        if subject_id not in subject_ids:
            subject_ids.append(subject_id)
        if marked >= papers:
            whole.add((student_id, subject_id))

    averages = {
        student_id: mean_percentage(marks)
        for student_id, marks in per_student.items()
        if marks
    }

    # Whole in every subject the class was marked in: a subject the child has
    # no mark in at all counts against them, because from the teacher's side it
    # is a paper not yet entered. `subject_ids` is a list of the subjects with a
    # percentage for somebody, so this is the class's own subject list.
    whole_students = frozenset(
        student_id
        for student_id in students
        if subject_ids and all((student_id, subject_id) in whole for subject_id in subject_ids)
    )

    subject_positions: dict[tuple[int, int], int] = {}
    for subject_id in subject_ids:
        in_subject = {
            student_id: value
            for (student_id, other), value in percentages.items()
            if other == subject_id and (student_id, other) in whole
        }
        for student_id, position in dense_positions(in_subject).items():
            subject_positions[(student_id, subject_id)] = position

    card_totals: dict[int, tuple[int, int]] = {}
    card_marks: dict[int, list[Decimal]] = {}
    for (student_id, subject_id) in whole:
        scored, available = totals[(student_id, subject_id)]
        so_far = card_totals.get(student_id, (0, 0))
        card_totals[student_id] = (so_far[0] + scored, so_far[1] + available)
        if (student_id, subject_id) in percentages:
            card_marks.setdefault(student_id, []).append(percentages[(student_id, subject_id)])
    card_averages = {student: mean_percentage(marks) for student, marks in card_marks.items()}

    return ClassResults(
        student_ids=students,
        placements=placements,
        class_group=class_group,
        term=term,
        subject_ids=sorted(subject_ids),
        totals=totals,
        percentages=percentages,
        subject_positions=subject_positions,
        averages=averages,
        positions=dense_positions(
            {student: averages[student] for student in whole_students if student in averages}
        ),
        # Over the children who are ranked and nobody else: a class average that
        # counted a child's average over the papers marked so far would move when
        # the rest were marked, and say less than the ranking beside it.
        class_average=(
            mean_percentage([averages[s] for s in whole_students if s in averages])
            if any(s in averages for s in whole_students)
            else None
        ),
        whole=frozenset(whole),
        whole_students=whole_students,
        card_totals=card_totals,
        card_averages=card_averages,
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
    value this module produces goes through `round_percentage()`, and why it is
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
    "mean_percentage",
    "overall_percentages",
    "round_percentage",
    "roster_ids",
    "subject_percentages",
    "subject_positions",
]
