"""What the Ogun State report sheet says that the Standard card does not.

`docs/ogun-template.md` part 5. `card_api.card_payload()` calls `sheet_for()`
when the school prints the Ogun State card and serves the answer as
`ReportCardOut.ogun`; the page (`static/card/render.js`) and the PDF
(`results/report_card_ogun.html`) both draw from it, so the two cannot disagree.

Everything here comes from the frozen card, except what the Standard card
already reads live (the admission number, the next term's date, the promotion
decision) and the same kind of thing for this sheet: the child's learner's ID,
sex, date of birth and photo (`academics.StudentDetails`), the school's LGA and
code, and each subject's department. The PDF is rendered at release and
stored, so the file keeps what was on record then.

**No health record.** It is served to four readers only (`results.health`),
and this payload is served to every reader of the card, the result checker's
PIN holder among them. The page fetches it separately; the PDF has a variant
for those four (`ReleasedCardPdf.health_content`).

## The subject grid

One column per subject. Its rows: **Cont. Assess Scores (30)**, the sum of
every paper but the exam; **Exam Scores (70)**; **Weighted Average (100)**,
the subject's percentage. "The exam" is the paper named Exam (the Ogun preset's
name, `ogun.ASSESSMENTS`), so a school whose papers differ still gets its CA
and exam split, each out of what its papers add up to.

**The name decides the split and nothing else** (audit finding G-07). A subject
is whole when every one of its papers is marked, whatever they are called, and
a whole subject prints its Weighted Average, its term scores and its annual
score and is counted in the summary. A subject with no paper named exactly
"Exam" (a school that kept "Examination", "CA" and "Test") prints a dash in the
two rows the sheet cannot fill and its marks in the third.

A **senior** class (its name starts SS or SSS: "SSS 2A", "SS1 Gold") groups the
columns under department headings, in `gradebook.Department` order, with
subjects nobody placed under "Other". A junior class has one run of columns.

On a **third-term** card three more rows: the 1st, 2nd and 3rd term scores
(each out of 100, from this child's card for each term of the session) and the
**Weighted Annual Score**. A term with no score shows "-".

## One set of frozen figures (audit finding G-08)

- **Percentage** in the summary is the card's own frozen average
  (`ReleasedCard.own_average`): the figure the class position beside it is
  ranked on and the Standard card prints. It is not marks obtained over marks
  obtainable, which is a different number whenever subjects are out of
  different totals. Those two sums still print, as sums. (A card frozen before
  the whole-subjects rule, `whole_subjects_only` false, keeps the figure it
  was released with: its average counts part-marked subjects that the summary
  leaves out.)
- **Rounding** is `positions.round_percentage()`, half up, as everywhere else.
- **The annual score** of a subject is its term scores combined under the
  weighting frozen on this card's year summary (`ReleasedSessionResult`'s
  `*_weight_used`), over the terms the subject has a score for: the same terms,
  the same weights and the same rounding as the year's average on the card.
- **The 1st and 2nd term scores** are read off the child's cards for those
  terms *as they stood when this card was issued* (`cards.card_as_of()`), which
  is what the year summary was frozen from. A later revision of an earlier
  term's card reissues this one in the same transaction when it moves the
  year's figures (`results.revision`), and the new version reads the new card.

## The head

The school's crest, its name and its place, "(Abeokuta South LGA)
[B13003]", lead the card. A school that turns on the ministry's heading
(`ReportCardSettings.show_ministry`, off by default) gets the paper sheet's
order instead: the ministry's two lines, the sheet's title, then the school on
one line.

## The promotion line

Third term only, and **the principal's recorded decision and nothing else**
(`PromotionDecision`, audit finding G-06): "Promoted", "Promoted on trial",
"Not promoted, to repeat JSS 2A" (the class on this card), "Graduated",
"Withdrawn". No decision, no line. It is not worked out from where the child is
placed next session: a placement made by hand, a child who repeats in another
arm and a move in October each used to reword a card that had gone home.
The Standard card prints the same decision (`card_api._promotion()`).
"""

import base64
import re
from decimal import Decimal, localcontext
from typing import Optional

from academics.models import Sex, StudentDetails, Term, TermName
from gradebook.models import Department, Subject

from .models import (
    CardTemplate,
    PromotionDecision,
    PromotionStatus,
    ReleasedCard,
    ReleasedSessionResult,
    ReleasedSubjectResult,
    ReportCardSettings,
)
from .positions import CONTEXT, round_percentage

MINISTRY = ("OGUN STATE GOVERNMENT", "MINISTRY OF EDUCATION, SCIENCE AND TECHNOLOGY")

_SENIOR = re.compile(r"^\s*S\.?\s*S\.?\s*S?\.?\s*\d", re.IGNORECASE)


def is_ogun() -> bool:
    row = ReportCardSettings.objects.filter(pk=1).only("template").first()
    return bool(row and row.template == CardTemplate.OGUN)


def prints_ogun(card) -> bool:
    """Whether this card prints on the Ogun State sheet.

    The layout it was released under, once the card carries one
    (`ReleasedCard.template`); a card released before that follows the school's
    current template, as it always did.
    """
    if card.template:
        return card.template == CardTemplate.OGUN
    return is_ogun()


def is_senior(class_name: str) -> bool:
    """"SSS 2A", "SS1 Gold", "S.S.S. 3" are senior; "JSS 1A" is not."""
    return bool(_SENIOR.match(class_name or ""))


def _text(value) -> Optional[str]:
    if value is None:
        return None
    text = f"{value}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _is_exam(cell) -> bool:
    return cell.assessment_name.strip().lower() == "exam"


def _split(line, whole_only=False) -> dict:
    """CA and exam for one subject line, each with what it is out of.

    On a card frozen under the whole-subjects rule (`whole_only`), a half with a
    paper unmarked is a dash: a continuous assessment total over two of its three
    tests is not the child's CA score. An earlier card keeps its partial sum.

    **A subject with no paper named Exam has no split**: both halves are `None`
    with nothing they are out of, and the sheet prints a dash in each. Its marks
    are in the Weighted Average row (audit finding G-07).
    """
    exam = [c for c in line.assessments if _is_exam(c)]
    if not exam:
        return {"ca": None, "ca_max": None, "exam": None, "exam_max": None}
    rest = [c for c in line.assessments if c not in exam]

    def total(cells):
        if not cells:
            return None, None
        scores = [c.score for c in cells if c.score is not None]
        if whole_only and len(scores) < len(cells):
            return None, sum(c.max_score for c in cells)
        return (sum(scores) if scores else None), sum(c.max_score for c in cells)

    ca, ca_max = total(rest)
    exam_score, exam_max = total(exam)
    return {"ca": ca, "ca_max": ca_max, "exam": exam_score, "exam_max": exam_max}


def _is_complete(line) -> bool:
    """Every paper of this subject has a mark for this child.

    A paper with no mark is not nought (`gradebook.Score`: no row is "not
    marked"), and a subject still waiting on a paper has no total yet. The
    Standard card prints the percentage over what was marked, with the marks
    beside it; the Ogun sheet's Weighted Average (100) and its summary have no
    room for that denominator, so they wait until the subject is whole.

    **What the papers are called has nothing to do with it** (audit finding
    G-07). This used to ask for a paper named exactly "Exam" and at least one
    other, so a school that kept its own papers got a column of dashes for a
    subject every child had been marked in.
    """
    cells = line.assessments
    return bool(cells) and all(c.score is not None for c in cells) and line.is_complete


def _summary(card, subjects, whole) -> dict:
    """Marks obtainable and obtained over the whole subjects, and the percentage.

    The percentage is the card's own frozen average, the figure its position is
    ranked on (audit finding G-08), not the two sums divided.
    """
    done = [s for s in subjects if id(s) in whole]
    obtainable = sum(s["out_of"] for s in done)
    obtained = sum(s["total"] for s in done)
    if card.whole_subjects_only:
        percentage = (
            _text(round_percentage(card.own_average)) if card.own_average is not None else None
        )
    else:
        # A card frozen before the whole-subjects rule: its own average counts
        # part-marked subjects, which this summary leaves out, so the two sums
        # divided are what it has always printed here. A released card is not
        # reworded; the figure is kept exactly, rounding included.
        percentage = None
        if obtainable:
            share = Decimal(obtained) * 100 / Decimal(obtainable)
            percentage = _text(share.quantize(Decimal("0.01")))
    return {
        "obtainable": obtainable or None,
        "obtained": obtained if obtainable else None,
        "percentage": percentage,
        "left_out": len(subjects) - len(done),
    }


def _other_terms(card) -> dict:
    """`{"first": {subject_id: percentage}, "second": {...}}` from this child's
    cards for those terms, as they stood when this card was issued."""
    from . import cards

    found = {}
    for name in (TermName.FIRST, TermName.SECOND):
        term = Term.objects.filter(session=card.session, name=name).first()
        if term is None:
            continue
        other = cards.card_as_of(card.student_membership_id, term, card.created_at)
        if other is None:
            continue
        # A subject with a paper unmarked that term has no score for it.
        found[name.value] = dict(
            ReleasedSubjectResult.objects.filter(card=other, is_complete=True).values_list(
                "subject_id", "percentage"
            )
        )
    return found


def _weights_of(card) -> dict:
    """`{term name: weight}` as frozen on this card's year summary.

    Only the terms the year counted. A card with no frozen year (not a third
    term, or issued before the year was frozen at all) weighs its terms equally.
    """
    frozen = ReleasedSessionResult.objects.filter(card=card).order_by("-id").first()
    names = [name.value for name in (TermName.FIRST, TermName.SECOND, TermName.THIRD)]
    if frozen is None:
        return {name: Decimal(1) for name in names}
    return {
        name: weight
        for name in names
        if (weight := getattr(frozen, f"{name}_weight_used")) is not None
    }


def _annual(scores, weights) -> Optional[Decimal]:
    """One subject's year: its term scores under the card's frozen weighting.

    `scores` is `{term name: percentage or None}`. Over the terms that have a
    score and that the year counted, renormalised, exactly as the year's average
    is (`sessions._weigh()`), and rounded once, half up.
    """
    taken = {
        name: score
        for name, score in scores.items()
        if score is not None and name in weights
    }
    total = sum(weights[name] for name in taken)
    if not taken or total <= 0:
        return None
    with localcontext(CONTEXT):
        return round_percentage(
            sum(score * weights[name] for name, score in taken.items()) / total
        )


def _promotion_line(card) -> Optional[str]:
    """The principal's decision for this child's year, in the sheet's words."""
    if card.term_name != TermName.THIRD:
        return None
    decision = (
        PromotionDecision.objects.filter(
            student_membership_id=card.student_membership_id, session=card.session
        )
        .order_by("-decided_at", "-id")
        .first()
    )
    if decision is None:
        return None
    if decision.status == PromotionStatus.REPEATED:
        return f"Not promoted, to repeat {card.class_group_name}"
    return decision.get_status_display()


def _school_place(school) -> str:
    """"(Abeokuta South LGA) [B13003]", either part left out when unset."""
    parts = []
    if school.lga:
        lga = school.lga if school.lga.lower().endswith("lga") else f"{school.lga} LGA"
        parts.append(f"({lga})")
    if school.school_code:
        parts.append(f"[{school.school_code}]")
    return " ".join(parts)


def _school_line(school) -> str:
    place = _school_place(school)
    return f"{school.name} {place}" if place else school.name


def _shows_ministry() -> bool:
    row = ReportCardSettings.objects.filter(pk=1).only("show_ministry").first()
    return bool(row and row.show_ministry)


def sheet_for(card: ReleasedCard, payload, school) -> Optional[dict]:
    """The Ogun sheet's extra content for one card, or None for a Standard school."""
    if not prints_ogun(card):
        return None
    from . import look, ratings

    from academics.details import photo_of

    details = StudentDetails.objects.filter(student_membership_id=card.student_membership_id).defer("photo").first()
    photo = None
    jpeg = photo_of(card.student_membership_id)
    if jpeg:
        photo = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()

    lines = list(ReleasedSubjectResult.objects.filter(card=card).values_list("subject_id", "subject_name"))
    subject_of = {name: sid for sid, name in lines}
    departments = dict(
        Subject.objects.filter(pk__in=[sid for sid, _ in lines]).values_list("pk", "department")
    )
    third = card.term_name == TermName.THIRD
    others = _other_terms(card) if third else {}
    weights = _weights_of(card) if third else {}

    subjects = []
    whole = set()
    for line in payload.subjects:
        sid = subject_of.get(line.subject_name)
        split = _split(line, card.whole_subjects_only)
        complete = _is_complete(line)
        # A total over some of the papers must not look final: with a paper
        # still unmarked the weighted average is a dash, and the annual score
        # that would be built on it is too.
        percentage = Decimal(line.percentage) if line.percentage and complete else None
        row = {
            "name": line.subject_name,
            "department": departments.get(sid, "") or "",
            "ca": split["ca"],
            "ca_max": split["ca_max"],
            "exam": split["exam"],
            "exam_max": split["exam_max"],
            "weighted": _text(round_percentage(percentage)) if percentage is not None else None,
            #: The subject's marks and what they are out of, for the summary's
            #: two sums. Nought for a subject that is not whole; never printed.
            "total": sum(c.score for c in line.assessments) if complete else 0,
            "out_of": sum(c.max_score for c in line.assessments) if complete else 0,
        }
        if third:
            first = others.get("first", {}).get(sid)
            second = others.get("second", {}).get(sid)
            row.update(
                first=_text(first),
                second=_text(second),
                third=_text(percentage),
                annual=_text(
                    _annual({"first": first, "second": second, "third": percentage}, weights)
                ),
            )
        subjects.append(row)
        if complete:
            whole.add(id(row))

    senior = is_senior(card.class_group_name)
    if senior:
        groups = []
        for department in Department:
            inside = [s for s in subjects if s["department"] == department.value]
            if inside:
                groups.append({"label": department.label, "subjects": inside})
        rest = [s for s in subjects if s["department"] not in Department.values]
        if rest:
            groups.append({"label": "Other", "subjects": rest})
    else:
        groups = [{"label": "", "subjects": subjects}]

    traits = []
    for section in payload.sections:
        scored = [t.score for t in section.traits if t.score is not None]
        traits.append(
            {
                "label": section.group_label.split(" (")[0],
                "traits": [{"name": t.trait_name, "score": t.score} for t in section.traits],
                "total": sum(scored) if scored else None,
                "out_of": 5 * len(section.traits),
            }
        )

    present, absent = card.days_present, card.days_absent
    # Over the subjects that have the split; one with no paper named Exam has
    # neither half and says nothing about what the halves are out of.
    ca_outs = {s["ca_max"] for s in subjects if s["exam_max"] is not None}
    exam_outs = {s["exam_max"] for s in subjects if s["exam_max"] is not None}
    return {
        #: "(30)" and "(70)" on the row labels when every subject agrees.
        "ca_out_of": ca_outs.pop() if len(ca_outs) == 1 else None,
        "exam_out_of": exam_outs.pop() if len(exam_outs) == 1 else None,
        #: Empty unless the school prints the ministry's heading
        #: (`ReportCardSettings.show_ministry`, off by default); without it the
        #: card leads with the school's name and then its place.
        "ministry": list(MINISTRY) if _shows_ministry() else [],
        "title": (
            "SENIOR SECONDARY SCHOOL CONTINUOUS ASSESSMENT REPORT SHEET"
            if senior
            else "JUNIOR SECONDARY SCHOOL CONTINUOUS ASSESSMENT REPORT SHEET"
        ),
        "school_line": _school_line(school),
        "school_name": school.name,
        #: The crest the school's public page shows, small, for the page's head
        #: (the PDF draws the full one from `look.for_card()`). Null without one.
        "crest": look.for_site(school.name)["crest"],
        "school_place": _school_place(school),
        "learner_id": details.learner_id if details else "",
        "sex": Sex(details.sex).label if details and details.sex else "",
        "date_of_birth": details.date_of_birth.strftime("%d/%m/%Y") if details and details.date_of_birth else "",
        "photo": photo,
        "senior": senior,
        "third_term": third,
        "groups": groups,
        "promotion": _promotion_line(card),
        "times_opened": card.days_open,
        "times_present": present,
        "times_absent": absent,
        "traits": traits,
        #: The card's own key, as it was printed: relabelling a point of
        #: the scale later does not reword a card that has gone home.
        "key": ratings.scale_of_card(card),
        "summary": _summary(card, subjects, whole),
    }


__all__ = ["MINISTRY", "is_ogun", "is_senior", "prints_ogun", "sheet_for"]
