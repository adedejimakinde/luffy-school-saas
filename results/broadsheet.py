"""The master broadsheet: one class, one term, every child and every subject.

`docs/broadsheet.md`. This module is the numbers and nothing else: it builds one
`Sheet`, and the page (`broadsheet_api`), the PDF and the Excel file
(`broadsheet_files`) all draw that one thing, so they cannot disagree.

**It computes nothing the report cards do not.** A broadsheet that worked a
total or a position out for itself would be a second answer to "what did Ada
get", and the day it differed from her card is the day a parent holds one up
against the other. So:

- **Released**: every figure is read off the frozen cards that went home
  (`class_print.released_cards()`, the rule a family's own page uses): the
  card's total, average and position, the subject lines' percentages and
  letters, and each paper's mark.
- **Not released**: the same figures from `positions.class_results()`, which is
  what `cards.freeze_for_release()` itself freezes, through the same helpers
  (`cards._assessments_for`, `cards._scores_for`, `grades.grade_for`). The
  test that holds this releases the class and compares every cell with the
  card it wrote.

## The columns

Per subject, in the order the cards print them:

| template | columns |
| --- | --- |
| Standard | **CA**, **Exam**, **%** |
| Ogun State | each continuous-assessment paper (1st Test, 2nd Test, Assignment...), then **CA**, **Exam**, **%** |

CA is the sum of every paper but the one named Exam, and Exam is that paper
(`ogun_card._split`, the Ogun sheet's own rule). **%** is the subject's
percentage, which is what the card ranks, grades and averages. Then **Total**
(marks obtained over the subjects that are whole, as the card says), **Average**,
**Position** when the school prints one, a count of each grade letter, and the
promotion status.

## A paper not marked is "-"

Never a zero. `gradebook` keeps "not marked" apart from nought by having no
`Score` row, and this keeps it apart in every cell: a missing paper is `None`;
a CA with a paper missing is `None` (a total over two of three tests is not the
child's CA); a subject with a paper missing has no `%`, no letter and no
place in the subject's footer or the child's average, which is exactly what the
card does with it (`positions`, "A subject with a paper unmarked"). A child with
no whole subject has no total, no average and no position. Nothing is ranked on
a subject the child did not sit, because ranks are `positions`' and `positions`
ranks only whole subjects.

## Position, and the tie rule

`ReportCardSettings.show_position` is the school's setting. When it is off the
sheet has **no position column and no position in any payload**, and the rows
are put in name order, because rows in rank order would print the position
without printing it. When it is on, the position is the card's own, and rows are
in rank order with the unranked last. Ties are `positions.dense_positions()`'s
(1, 2, 2, 3): the one place the school's tie rule is decided, so the sheet and
the card cannot break a tie two ways.

## Who

`may_see()` is `class_print.may_print()`: the principal, the vice principal
(academic) and the administrator for any class; a class teacher for their own
class that term; nobody else. They are the same people on purpose: the sheet
carries every child's marks, positions and promotion, the same material as the
class's cards.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

from django.db.models import prefetch_related_objects

from . import class_print, grades, ogun_card, positions

#: Who may see a class's broadsheet: who may print its cards.
may_see = class_print.may_print
may_see_any = class_print.may_print_any

MAY_NOT_SEE = (
    "A class's broadsheet is read by its class teacher, the vice principal "
    "(academic), the principal and the school's administrator."
)

#: The words in the three footer rows, in order.
FOOTER = ("Highest", "Lowest", "Class average")

PAPER, CA, EXAM, PERCENT = "paper", "ca", "exam", "pct"


@dataclass(frozen=True)
class Column:
    """One column of subject marks."""

    subject_id: int
    subject: str
    key: str
    label: str
    #: What it is out of (a paper's `max_score`, the CA's or the exam's total),
    #: or 100 for the percentage. None where there is no such paper.
    out_of: Optional[int] = None


@dataclass
class Row:
    student_id: int
    name: str
    #: One entry per `Sheet.columns`: an int, a `Decimal`, or None for "-".
    values: list
    total: Optional[int]
    average: Optional[Decimal]
    #: None when the school hides positions, and for a child who is not ranked.
    position: Optional[int]
    #: `letter -> subjects the child earned it in`, over whole subjects.
    grades: dict
    #: How many subjects have a grade at all, so a child with none shows "-"
    #: and not a row of zeros that reads as "no A, no B, no C".
    graded: int
    promotion: Optional[str]


@dataclass
class Sheet:
    class_group: str
    class_group_id: int
    term: str
    term_id: int
    school: str
    #: True when the class is not released: every figure is live, and the PDF
    #: is stamped "PREVIEW, NOT RELEASED".
    preview: bool
    ogun: bool
    show_position: bool
    columns: list
    letters: list
    rows: list
    #: `[(label, values aligned to columns)]`: highest, lowest, class average.
    footer: list = field(default_factory=list)
    #: How many children are ranked, when the school prints positions.
    ranked: int = 0

    def subjects(self):
        """`[(subject name, how many columns it spans)]`, in column order."""
        out = []
        for column in self.columns:
            if out and out[-1][2] == column.subject_id:
                out[-1][1] += 1
            else:
                out.append([column.subject, 1, column.subject_id])
        return [(name, span) for name, span, _ in out]


def text(value) -> str:
    """How a figure prints: "-" for none, whole numbers as they are, else two places."""
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


# -- building ------------------------------------------------------------------


def build(class_group, term) -> Sheet:
    """The class's sheet for `term`, released or live. Writes nothing."""
    from .look import settings as card_settings

    sheet = class_print.sheet_of(class_group, term)
    released = class_print.is_released(sheet)
    show_position = card_settings().show_position
    if released:
        return _from_the_cards(class_group, term, sheet, show_position)
    return _from_the_marks(class_group, term, show_position)


def _is_exam(name) -> bool:
    return (name or "").strip().lower() == "exam"


def _columns(subject, papers, ogun):
    """One subject's columns. `papers` is `[(name, out_of)]` in print order."""
    sid, name = subject
    cols = []
    if ogun:
        cols += [Column(sid, name, PAPER, paper, out_of) for paper, out_of in papers if not _is_exam(paper)]
    ca_max = sum(out_of for paper, out_of in papers if not _is_exam(paper))
    exam_max = sum(out_of for paper, out_of in papers if _is_exam(paper))
    cols += [
        Column(sid, name, CA, "CA", ca_max or None),
        Column(sid, name, EXAM, "Exam", exam_max or None),
        Column(sid, name, PERCENT, "%", 100),
    ]
    return cols


def _subject_values(ogun, papers, scores, percentage, whole_only):
    """The values for one child in one subject, aligned to `_columns()`.

    `scores` is the child's mark for each paper, None where not marked.
    CA and Exam are `ogun_card._split()`'s, the sheet's own rule, including
    that a CA over a missing paper is a dash.
    """
    cells = [
        SimpleNamespace(assessment_name=name, max_score=out_of, score=score)
        for (name, out_of), score in zip(papers, scores)
    ]
    split = ogun_card._split(SimpleNamespace(assessments=cells), whole_only=whole_only)
    values = []
    if ogun:
        values += [score for (name, _), score in zip(papers, scores) if not _is_exam(name)]
    values += [split["ca"], split["exam"], percentage]
    return values


def _finish(class_group, term, rows, columns, letters, preview, ogun, show_position):
    """Order the rows, work out the footer, and wrap it all up."""
    if show_position:
        rows.sort(
            key=lambda r: (r.position is None, r.position or 0, r.name.casefold(), r.student_id),
        )
    else:
        rows.sort(key=lambda r: (r.name.casefold(), r.student_id))
        for row in rows:
            row.position = None
    from .cards import _school_name

    return Sheet(
        class_group=str(class_group),
        class_group_id=class_group.pk,
        term=str(term),
        term_id=term.pk,
        school=_school_name(),
        preview=preview,
        ogun=ogun,
        show_position=show_position,
        columns=columns,
        letters=letters,
        rows=rows,
        footer=_footer(columns, rows),
        ranked=sum(1 for r in rows if r.position is not None) if show_position else 0,
    )


def _footer(columns, rows):
    """Highest, lowest and class average of each column, over the figures shown.

    A "-" is not in the sum: the average is over the children who have a figure,
    never over the roster with zeros in the gaps.
    """
    out = [[] for _ in FOOTER]
    for index, _ in enumerate(columns):
        shown = [r.values[index] for r in rows if r.values[index] is not None]
        if shown:
            out[0].append(max(shown))
            out[1].append(min(shown))
            out[2].append(positions.mean_percentage([Decimal(v) for v in shown]))
        else:
            for line in out:
                line.append(None)
    return list(zip(FOOTER, out))


def _promotion(card_like):
    return ogun_card._promotion_line(card_like)


def _letters(bands, used):
    """The scale's letters, highest band first, then any a card used that the scale no longer has."""
    letters = []
    for band in bands:
        if band.letter not in letters:
            letters.append(band.letter)
    letters += sorted(letter for letter in used if letter and letter not in letters)
    return letters


def _from_the_marks(class_group, term, show_position):
    """An unreleased class: live marks, through the helpers a release freezes with."""
    from . import cards

    results = positions.class_results(class_group, term)
    ids = results.student_ids
    names = cards._student_names(ids)
    subjects = cards._subjects_in_print_order(results.subject_ids)
    assessments = cards._assessments_for(term, results.subject_ids)
    scores = cards._scores_for(assessments, ids)
    bands = grades.scale()
    ogun = ogun_card.is_ogun()

    papers_of = {}
    for assessment in assessments:
        papers_of.setdefault(assessment.subject_id, []).append(assessment)

    columns, spans = [], {}
    for subject in subjects:
        papers = [(a.name, a.max_score) for a in papers_of.get(subject.pk, [])]
        cols = _columns((subject.pk, subject.name), papers, ogun)
        spans[subject.pk] = (papers, len(cols))
        columns += cols

    used = set()
    rows = []
    for student_id in ids:
        values, graded, counts = [], 0, {}
        for subject in subjects:
            papers, _ = spans[subject.pk]
            whole = results.is_whole(student_id, subject.pk)
            percentage = results.percentage(student_id, subject.pk) if whole else None
            marks = [scores.get((student_id, a.pk)) for a in papers_of.get(subject.pk, [])]
            values += _subject_values(ogun, papers, marks, percentage, whole_only=True)
            band = grades.grade_for(percentage, bands=bands) if whole else None
            if band is not None:
                counts[band.letter] = counts.get(band.letter, 0) + 1
                graded += 1
                used.add(band.letter)
        scored, available = results.card_total(student_id)
        rows.append(
            Row(
                student_id=student_id,
                name=names.get(student_id, ""),
                values=values,
                total=scored if available else None,
                average=results.card_averages.get(student_id),
                position=results.positions.get(student_id),
                grades=counts,
                graded=graded,
                promotion=_promotion(
                    SimpleNamespace(
                        term_name=term.name,
                        session=term.session,
                        class_group_id=class_group.pk,
                        class_group_name=str(class_group),
                        student_membership_id=student_id,
                    )
                ),
            )
        )
    return _finish(class_group, term, rows, columns, _letters(bands, used), True, ogun, show_position)


def _from_the_cards(class_group, term, sheet, show_position):
    """A released class: each figure is the one on the card that went home."""
    chosen = class_print.released_cards(sheet)
    prefetch_related_objects(chosen, "subject_results", "assessment_scores")
    ogun = bool(chosen) and ogun_card.prints_ogun(chosen[0])

    # The columns, in the order the cards froze them. A subject retired since
    # release still has its column, because the cards still have its line.
    order = {}  # subject_id -> (print position, name)
    papers_of = {}  # subject_id -> [(name, out_of)] from the first card that has it
    for card in chosen:
        for line in card.subject_results.all():
            order.setdefault(line.subject_id, (line.position, line.subject_name))
        by_subject = {}
        for cell in sorted(card.assessment_scores.all(), key=lambda c: (c.position, c.pk)):
            by_subject.setdefault(cell.subject_id, []).append(cell)
        for subject_id, cells in by_subject.items():
            papers_of.setdefault(subject_id, [(c.assessment_name, c.max_score) for c in cells])
    ordered = sorted(order.items(), key=lambda item: (item[1][0], item[1][1]))

    columns = []
    for subject_id, (_, name) in ordered:
        columns += _columns((subject_id, name), papers_of.get(subject_id, []), ogun)

    used = {line.grade_letter for card in chosen for line in card.subject_results.all() if line.grade_letter}
    rows = []
    for card in chosen:
        lines = {line.subject_id: line for line in card.subject_results.all()}
        cells = {}
        for cell in sorted(card.assessment_scores.all(), key=lambda c: (c.position, c.pk)):
            cells.setdefault(cell.subject_id, []).append(cell)
        values, graded, counts = [], 0, {}
        for subject_id, (_, name) in ordered:
            papers = papers_of.get(subject_id, [])
            line = lines.get(subject_id)
            mine = cells.get(subject_id, [])
            marks = [mine[i].score if i < len(mine) else None for i in range(len(papers))]
            whole = line is not None and (line.is_complete or not card.whole_subjects_only)
            percentage = line.percentage if whole else None
            values += _subject_values(ogun, papers, marks, percentage, whole_only=card.whole_subjects_only)
            if line is not None and line.is_complete and line.grade_letter:
                counts[line.grade_letter] = counts.get(line.grade_letter, 0) + 1
                graded += 1
        rows.append(
            Row(
                student_id=card.student_membership_id,
                name=card.student_name,
                values=values,
                total=card.total_scored if card.total_available else None,
                average=card.own_average,
                position=card.position,
                grades=counts,
                graded=graded,
                promotion=_promotion(card),
            )
        )
    return _finish(class_group, term, rows, columns, _letters(grades.scale(), used), False, ogun, show_position)


__all__ = [
    "FOOTER",
    "MAY_NOT_SEE",
    "Column",
    "Row",
    "Sheet",
    "build",
    "may_see",
    "may_see_any",
    "text",
]
