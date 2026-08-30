"""The report card, as a family reads it. Snapshot only, and no staff field has a slot.

This module is separate from `results.api` on purpose, and the separation is
structural rather than tidy. `results.api` serves the broadsheet, whose whole
subject is `position` and `class_average`; this one serves a card to the child
it is about and to their parent. Issue #21 asks that the family-facing surfaces
be *built from their own schemas rather than by filtering the staff ones*, and
the way that requirement fails in practice is a family route importing a schema
somebody wrote for staff and trusting a filter to hold. There is nothing here to
import: every schema below is defined in this file and none of them has a field
for a staff-only number.

## Two rules, and both are about a field having nowhere to go

**Excluded at the serializer, not at the template.** A field omitted from a
printed page while the JSON still carries it has not been omitted — the browser
received it and anybody can read it. `ReleasedCard.position` says so on the
model itself. So the exclusions are enforced by the *shape of the response*:

| never here | where it lives | why |
| --- | --- | --- |
| `position`, `roster_size` | `ReleasedCard` | where the child came in the class |
| `subject_position` | `ReleasedSubjectResult` | where they came in that subject |
| `first/second/third_absence` | `ReleasedSessionResult` | *why* a term averaged nothing |
| `suggested` | `PromotionDecision` | what the arithmetic proposed |

**And the payload does not branch on who is asking.** A member of staff reading
this endpoint gets byte-for-byte what the parent gets, because the question it
answers is "what went home?" and there is exactly one answer to that. A role
branch here would be a second shape of this response that only staff ever
exercise in tests, which is how a leak survives review. Staff who want position
have the broadsheet, behind its own authority check.

Note that `position` is **not** a staff-only field everywhere it appears, and
this is the trap the module is most likely to fall into later.
`ReleasedSubjectResult.position` is *where the line prints*, smallest first, and
so are the `position` columns on the frozen assessment cells and trait ratings.
The rank in a subject is `subject_position`, a different column on the same
table. A future reader deleting every field called `position` from this module
would remove the print order and keep nothing dangerous; a future reader adding
`position` back "because the other tables have it" would publish a class rank.

## Snapshot only, and what that rules out

Every number below is read from the frozen tables through the card's own
`card_id`. In particular this module must **not** call
`ratings.card_sections()` or `comments.card_comments()`, which are the
draft-or-frozen readers used by the school's own screens: both fall back to live
configuration when a child has no frozen rows, which is correct for a draft card
and wrong here. A card that went home says what it said, including where what it
said was nothing.

`positions` is not imported at all. Nothing on this page is recomputed.

**The one live read, and the model sanctions it.** `PromotionDecision` is not
part of the snapshot and is deliberately not frozen — it is append-only and
already freezes its own inputs at decision time, so the hazard that drives
freezing everything else (a later configuration edit reaching backwards) cannot
apply to a table nothing edits. `ReleasedCard`'s docstring settles this. A
decision usually does not exist when the card is released, which is the other
half of why freezing it would be wrong: the card would permanently say
"undecided" about a year the school later decided.
"""

from decimal import Decimal
from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import Term, TermName
from accounts.models import Guardianship, Membership, Role
from accounts.session import session_auth

from . import cards
from .models import (
    CommentAuthor,
    PromotionDecision,
    ReleasedComment,
    ReleasedSessionResult,
    ReleasedTraitRating,
    TraitGroup,
)

router = Router(auth=session_auth)


#: Staff who may read any card at their own school.
#:
#: The same four as `results.api.POSITION_VIEWING_ROLES` and deliberately not
#: imported from it: that constant answers "who may see a position", this one
#: answers "who may see what went home to a family". They coincide today. Tying
#: them together would mean a later widening of one silently widened the other,
#: and these are not the same question — a bursar could reasonably be added
#: here one day and must never be added there.
CARD_VIEWING_ROLES = frozenset(
    {
        Role.TEACHER.value,
        Role.VICE_PRINCIPAL_ACADEMIC.value,
        Role.PRINCIPAL.value,
        Role.ADMIN.value,
    }
)


# -- what a family sees ------------------------------------------------------


class AssessmentCellOut(Schema):
    """One mark in one subject — "Test 1: 18 / 20", frozen as it was printed.

    `assessment_name` and `max_score` are the copied ones: an assessment renamed
    or re-weighted next term must not relabel a column on a card already in a
    parent's hand.
    """

    assessment_name: str
    max_score: int
    score: Optional[int]


class SubjectLineOut(Schema):
    """One subject's row on the card.

    No `subject_position`. That is the child's rank in the subject and it is
    staff-only for the same reason the class position is — see the module
    docstring, and note that this schema deliberately has no field it could be
    assigned to even by accident.

    `percentage` is a string rather than a float. It is `Decimal` everywhere
    behind this, and handing it to JSON as a float would round it at the last
    step, on the one number a parent is most likely to check with a calculator.
    """

    subject_name: str
    subject_code: str
    total_scored: int
    total_available: int
    percentage: Optional[str]
    grade_letter: str
    grade_remark: str
    assessments: List[AssessmentCellOut]


class TraitOut(Schema):
    """One line of the conduct section.

    `score` is `Optional` because a frozen section records the traits nobody
    rated as well as the ones somebody did — what was frozen is the *section*,
    and "nothing was recorded here" is a thing the card has to go on saying.
    """

    trait_name: str
    score: Optional[int]
    score_label: str


class SectionOut(Schema):
    """A conduct group — affective or psychomotor — and its lines."""

    group: str
    group_label: str
    traits: List[TraitOut]


class CommentOut(Schema):
    """A signed remark. Two signatories, fixed in code."""

    author: str
    author_label: str
    body: str


class SessionLineOut(Schema):
    """The three-term summary, third term only.

    **No `*_absence`.** Those columns say *why* a term contributed nothing —
    the child was not enrolled, or nobody entered marks, or the school never
    created the term — and `TermAbsence` states on the model that they are
    staff-only: a parent reading "no marks were entered" is being shown the
    school's filing rather than their child's year. A term that averaged
    nothing arrives here as a null average, which is what the card prints.

    The weights are absent for a narrower reason: they are the audit of how the
    year was averaged, they belong to the school's screen, and no Nigerian
    report card prints them.
    """

    session: str
    first_average: Optional[str]
    second_average: Optional[str]
    third_average: Optional[str]
    session_average: Optional[str]


class PromotionOut(Schema):
    """What the school *decided*, and never what the arithmetic suggested.

    `PromotionDecision` stores both, and the gap between them is the whole
    record: a child the numbers promote and the school holds back, or the
    reverse. `suggested` is the school's internal reasoning about a child and
    has no place on the card — it would tell a family that the system wanted a
    different answer from the one a person gave, which is a conversation for the
    school to have, not a field.

    There is no "undecided" value. A child nobody has decided about has no row,
    and this whole object is absent from the response.
    """

    status: str
    status_label: str


class ReportCardOut(Schema):
    """One child's card for one term, exactly as it was released.

    Every string here is a **copy** taken at release rather than a reach through
    a foreign key: `school_name`, `student_name`, `class_group_name`,
    `subject_name`. A school that renames itself, a child whose name is
    corrected, a class regrouped next session — none of them may relabel a card
    that has gone home.

    `own_average` is the child's own average across the subjects they were
    marked in. It is null where they were marked in nothing, which prints blank
    rather than as a zero that would claim they sat exams and scored none.

    Attendance is nullable until Phase 2 and prints blank meanwhile.

    `session` and `promotion` are third-term only and absent otherwise. A
    first-term card carrying a session average would be showing the first term's
    average wearing a session's name.
    """

    school_name: str
    student_name: str
    class_group_name: str
    academic_session: str
    term_name: str
    term_label: str
    version: int

    total_scored: int
    total_available: int
    own_average: Optional[str]

    days_present: Optional[int]
    days_absent: Optional[int]
    days_open: Optional[int]

    subjects: List[SubjectLineOut]
    sections: List[SectionOut]
    comments: List[CommentOut]
    session: Optional[SessionLineOut] = None
    promotion: Optional[PromotionOut] = None


# -- who may read one --------------------------------------------------------


def _school_of(request):
    """The school whose schema this request is already on.

    `None` is the portal host, where these tables do not exist — a 404 rather
    than a 403, the same answer `results.api` and `gradebook.api` give, and for
    the same reason: on the portal there is no such route because there is no
    such card.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No report cards on this host.")
    return school


def _the_child(school, student_membership_id: int) -> Membership:
    """The child this card is about, scoped to this school and to STUDENT.

    Both halves of that scoping are in the lookup rather than checked after,
    which is what stops a membership id belonging to another school — or to a
    teacher at this one — from resolving here at all.
    """
    return get_object_or_404(
        Membership,
        pk=student_membership_id,
        school=school,
        role=Role.STUDENT,
    )


def _may_read(actor, school, child: Membership) -> bool:
    """The child themselves, a guardian of theirs, or staff at this school.

    Three readers, and they are checked cheapest first. The guardian check is a
    query and is the reason this is a function rather than a role test: a parent
    holds a PARENT membership at the school, which says they are *a* parent
    there and nothing about *whose*. Guardianship is what links a login to one
    child, and without consulting it every parent at a school could read every
    child's card.
    """
    if not getattr(actor, "is_authenticated", False):
        return False

    # The child reading their own card. `Membership.user_id`, not the child's
    # membership id — a student's login is the thing being compared.
    if child.user_id == actor.pk:
        return True

    if set(actor.roles_at(school)) & CARD_VIEWING_ROLES:
        return True

    return Guardianship.objects.filter(guardian=actor, student=child).exists()


def _require_may_read(actor, school, child: Membership):
    """A flat 404 for every refusal, matching this API's disclosure convention.

    Not a 403. A 403 says "this card exists and you may not have it", which
    tells a stranger enumerating membership ids which children are enrolled at a
    school and in which term they were released — the existence oracle
    `gradebook.api`'s tests settled for this codebase. The refusal a caller who
    may not read this card gets is indistinguishable from the one they get for a
    child who does not exist.
    """
    if not _may_read(actor, school, child):
        raise Http404("No such report card.")


# -- reading the snapshot ----------------------------------------------------


def _as_text(value) -> Optional[str]:
    """`Decimal` to string, preserving `None`.

    Null is not the same as "0.00" on any number on this page: it is the
    difference between a child who was marked in nothing and one who scored
    nothing, and between a term that did not happen and a term that was failed.
    """
    return None if value is None else str(value)


def _subject_lines(card) -> List[SubjectLineOut]:
    """The subject table, in the order it was frozen to print in.

    `cards.card_lines()` returns `(line, cells)` pairs already grouped, in two
    queries whatever the card's size. `ReleasedSubjectResult.Meta.ordering`
    carries the frozen print order — `position`, which on this table means where
    the line prints and *not* a rank.
    """
    return [
        SubjectLineOut(
            subject_name=line.subject_name,
            subject_code=line.subject_code,
            total_scored=line.total_scored,
            total_available=line.total_available,
            percentage=_as_text(line.percentage),
            grade_letter=line.grade_letter,
            grade_remark=line.grade_remark,
            assessments=[
                AssessmentCellOut(
                    assessment_name=cell.assessment_name,
                    max_score=cell.max_score,
                    score=cell.score,
                )
                for cell in cells
            ],
        )
        for line, cells in cards.card_lines(card)
    ]


def _sections(card) -> List[SectionOut]:
    """The conduct section, grouped, read by `card_id` and nothing else.

    Deliberately **not** `ratings.card_sections()`. That reader falls back to
    live configuration for a child with no frozen rows, which is right for a
    draft card on the school's screen and wrong for a card that has gone home:
    it would print this term's trait list onto last term's card. Here, no frozen
    rows means no section, which is the truthful answer — a school that froze
    nothing published a card with no conduct section.

    Groups come out in `TraitGroup` declaration order rather than alphabetically,
    so affective precedes psychomotor as it does on the printed page.
    """
    rows = ReleasedTraitRating.objects.filter(card=card)

    by_group: dict[str, List[TraitOut]] = {}
    for row in rows:
        by_group.setdefault(row.group, []).append(
            TraitOut(
                trait_name=row.trait_name,
                score=row.score,
                score_label=row.score_label,
            )
        )

    return [
        SectionOut(
            group=group.value,
            group_label=group.label,
            traits=by_group[group.value],
        )
        for group in TraitGroup
        if group.value in by_group
    ]


def _comments(card) -> List[CommentOut]:
    """The signed remarks, in signatory order rather than write order.

    A card prints the class teacher above the principal whichever was typed
    first, so the order comes from `CommentAuthor` rather than from `created_at`.
    A remark that was never written has no row and prints as absent, which is
    what an unsigned card looks like.
    """
    by_author = {row.author: row for row in ReleasedComment.objects.filter(card=card)}
    return [
        CommentOut(
            author=author.value,
            author_label=author.label,
            body=by_author[author.value].body,
        )
        for author in CommentAuthor
        if author.value in by_author
    ]


def _session_line(card) -> Optional[SessionLineOut]:
    """The three-term summary, or `None` where none was frozen.

    Only third-term releases freeze one, so `None` here is the ordinary state of
    a first- or second-term card rather than a fault.
    """
    row = ReleasedSessionResult.objects.filter(card=card).first()
    if row is None:
        return None
    return SessionLineOut(
        session=row.session,
        first_average=_as_text(row.first_average),
        second_average=_as_text(row.second_average),
        third_average=_as_text(row.third_average),
        session_average=_as_text(row.session_average),
    )


def _promotion(card) -> Optional[PromotionOut]:
    """The recorded decision for this child's session, if a person has made one.

    Read live, which is the one thing on this page that is not from the
    snapshot — see the module docstring for why `ReleasedCard` sanctions it.

    Keyed on `(student, session)` and not on the card, because the decision is
    about the *year* rather than about the term whose release wrote this row.
    Absent where no row exists, because undecided is the absence of a row rather
    than a value.
    """
    if card.term_name != TermName.THIRD:
        return None
    decision = PromotionDecision.objects.filter(
        student_membership_id=card.student_membership_id, session=card.session
    ).first()
    if decision is None:
        return None
    return PromotionOut(
        status=decision.status,
        status_label=decision.get_status_display(),
    )


# -- the endpoint ------------------------------------------------------------


@router.get(
    "/cards/{int:student_membership_id}/{int:term_id}/",
    response=ReportCardOut,
    tags=["results"],
)
def report_card(request, student_membership_id: int, term_id: int):
    """One child's released card for one term.

    404 for every way this can fail to produce a card — no such child, no card
    released, or a caller with no claim on this one. They are one answer on
    purpose: see `_require_may_read()`.
    """
    school = _school_of(request)
    child = _the_child(school, student_membership_id)
    _require_may_read(request.user, school, child)

    term = get_object_or_404(Term, pk=term_id)
    card = cards.card_for(child, term)
    if card is None:
        raise Http404("No such report card.")

    return ReportCardOut(
        school_name=card.school_name,
        student_name=card.student_name,
        class_group_name=card.class_group_name,
        academic_session=card.session,
        term_name=card.term_name,
        term_label=TermName(card.term_name).label,
        version=card.version,
        total_scored=card.total_scored,
        total_available=card.total_available,
        own_average=_as_text(card.own_average),
        days_present=card.days_present,
        days_absent=card.days_absent,
        days_open=card.days_open,
        subjects=_subject_lines(card),
        sections=_sections(card),
        comments=_comments(card),
        session=_session_line(card),
        promotion=_promotion(card),
    )


__all__ = ["router", "CARD_VIEWING_ROLES"]
