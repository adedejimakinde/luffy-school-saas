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

A **senior** class (its name starts SS or SSS: "SSS 2A", "SS1 Gold") groups the
columns under department headings, in `gradebook.Department` order, with
subjects nobody placed under "Other". A junior class has one run of columns.

On a **third-term** card three more rows: the 1st, 2nd and 3rd term scores
(each out of 100, from this child's card for each term of the session) and the
**Weighted Annual Score**, their average over the terms taken. A term with no
score shows "-".

## The head

The school's crest, its name and its place, "(Abeokuta South LGA)
[B13003]", lead the card. A school that turns on the ministry's heading
(`ReportCardSettings.show_ministry`, off by default) gets the paper sheet's
order instead: the ministry's two lines, the sheet's title, then the school on
one line.

## The promotion line

Third term only, from the end-of-session promotion (`academics.promotion`),
which places each child in next session's first term: placed in the same class
is "Not promoted, to repeat JSS 2A"; in another, "Promoted to JSS 3A". Where no
placement exists yet, the school's recorded decision (`PromotionDecision`) is
used if there is one, without a class. Otherwise no line.
"""

import base64
import re
from decimal import Decimal
from typing import Optional

from academics.models import ClassPlacement, Sex, StudentDetails, Term, TermName
from gradebook.models import Department, Subject

from .models import (
    CardTemplate,
    PromotionDecision,
    PromotionStatus,
    ReleasedCard,
    ReleasedSubjectResult,
    ReportCardSettings,
)

MINISTRY = ("OGUN STATE GOVERNMENT", "MINISTRY OF EDUCATION, SCIENCE AND TECHNOLOGY")

_SENIOR = re.compile(r"^\s*S\.?\s*S\.?\s*S?\.?\s*\d", re.IGNORECASE)


def is_ogun() -> bool:
    row = ReportCardSettings.objects.filter(pk=1).only("template").first()
    return bool(row and row.template == CardTemplate.OGUN)


def is_senior(class_name: str) -> bool:
    """"SSS 2A", "SS1 Gold", "S.S.S. 3" are senior; "JSS 1A" is not."""
    return bool(_SENIOR.match(class_name or ""))


def _text(value) -> Optional[str]:
    if value is None:
        return None
    text = f"{value}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _split(line) -> dict:
    """CA and exam for one subject line, each with what it is out of."""
    exam = [c for c in line.assessments if c.assessment_name.strip().lower() == "exam"]
    rest = [c for c in line.assessments if c not in exam]

    def total(cells):
        scores = [c.score for c in cells if c.score is not None]
        return (sum(scores) if scores else None), sum(c.max_score for c in cells)

    ca, ca_max = total(rest)
    exam_score, exam_max = total(exam)
    return {"ca": ca, "ca_max": ca_max, "exam": exam_score, "exam_max": exam_max}


def _other_terms(card) -> dict:
    """`{"first": {subject_id: percentage}, "second": {...}}` from this child's cards."""
    from . import cards

    found = {}
    for name in (TermName.FIRST, TermName.SECOND):
        term = Term.objects.filter(session=card.session, name=name).first()
        if term is None:
            continue
        other = cards.card_for(card.student_membership_id, term)
        if other is None:
            continue
        found[name.value] = dict(
            ReleasedSubjectResult.objects.filter(card=other).values_list("subject_id", "percentage")
        )
    return found


def _annual(scores) -> Optional[Decimal]:
    taken = [s for s in scores if s is not None]
    if not taken:
        return None
    return (sum(taken) / len(taken)).quantize(Decimal("0.01"))


def _promotion_line(card) -> Optional[str]:
    if card.term_name != TermName.THIRD:
        return None
    from academics.promotion import next_session

    following = Term.objects.filter(session=next_session(card.session), name=TermName.FIRST).first()
    placement = (
        ClassPlacement.objects.select_related("class_group")
        .filter(term=following, student_membership_id=card.student_membership_id)
        .first()
        if following
        else None
    )
    if placement is not None:
        if placement.class_group_id == card.class_group_id:
            return f"Not promoted, to repeat {card.class_group_name}"
        return f"Promoted to {placement.class_group.name}"
    decision = PromotionDecision.objects.filter(
        student_membership_id=card.student_membership_id, session=card.session
    ).first()
    if decision is None:
        return None
    if decision.status == PromotionStatus.REPEATED:
        return f"Not promoted, to repeat {card.class_group_name}"
    if decision.status in (PromotionStatus.PROMOTED, PromotionStatus.ON_TRIAL):
        return decision.get_status_display()
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
    if not is_ogun():
        return None
    from . import look, ratings

    details = StudentDetails.objects.filter(student_membership_id=card.student_membership_id).first()
    photo = None
    if details is not None and details.photo:
        photo = "data:image/jpeg;base64," + base64.b64encode(bytes(details.photo)).decode()

    lines = list(ReleasedSubjectResult.objects.filter(card=card).values_list("subject_id", "subject_name"))
    subject_of = {name: sid for sid, name in lines}
    departments = dict(
        Subject.objects.filter(pk__in=[sid for sid, _ in lines]).values_list("pk", "department")
    )
    third = card.term_name == TermName.THIRD
    others = _other_terms(card) if third else {}

    subjects = []
    for line in payload.subjects:
        sid = subject_of.get(line.subject_name)
        split = _split(line)
        percentage = Decimal(line.percentage) if line.percentage else None
        row = {
            "name": line.subject_name,
            "department": departments.get(sid, "") or "",
            "ca": split["ca"],
            "ca_max": split["ca_max"],
            "exam": split["exam"],
            "exam_max": split["exam_max"],
            "weighted": _text(percentage.quantize(Decimal("0.01"))) if percentage is not None else None,
        }
        if third:
            first = others.get("first", {}).get(sid)
            second = others.get("second", {}).get(sid)
            terms = [first, second, percentage]
            row.update(
                first=_text(first),
                second=_text(second),
                third=_text(percentage),
                annual=_text(_annual(terms)),
            )
        subjects.append(row)

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
    ca_outs = {s["ca_max"] for s in subjects}
    exam_outs = {s["exam_max"] for s in subjects}
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
        "key": [{"value": p.value, "label": p.label} for p in ratings.scale()],
    }


__all__ = ["MINISTRY", "is_ogun", "is_senior", "sheet_for"]
