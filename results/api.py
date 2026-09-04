"""The broadsheet: a class's marks, averages and positions, for staff.

One endpoint, and its whole design is the audience. **Position is staff-only**,
and that is a rule about who may see the number rather than about where it is
printed:

> Nigerian secondary schools do not print position on report cards. Parents and
> students see the cumulative average only. Schools use position internally, so
> it is computed and (at release) frozen — but it must not reach a parent or a
> student, in a card *or in a payload*.

Enforced here at the **router**, which is the earliest place it can be. A field
omitted from a template while the JSON still carries it is the same leak with an
extra step, and the way that happens is a family-facing view reusing a schema
that was written for staff. There is no schema in this module a family-facing
route could reuse: `PositionOut` and `BroadsheetOut` are only ever produced
behind `_require_position_authority()`.

The parent- and student-facing surfaces — the report card (task 6) and the
unauthenticated result checker — do not exist yet, and when they do they must be
built from their own schemas rather than by filtering these. That is
[issue #21](https://github.com/adedejimakinde/luffy-school-saas/issues/21).

**No school slug in the path**, for the reason `gradebook.api` sets out at
length: these are tenant tables, `TenantMainMiddleware` has already chosen the
schema from the hostname, and a slug would be a second opinion free to disagree
with the connection.
"""

from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import ClassGroup, Term
from accounts.models import Membership, Role
from accounts.session import session_auth
from gradebook.models import Subject

from . import cards as released_cards
from . import positions
from .models import ResultSheet, SheetState

router = Router(auth=session_auth)


#: Who may see a position or a class average.
#:
#: Teachers, the academic vice principal (this codebase's HOD-shaped role),
#: principals and school administrators — the four the decision names. The
#: load-bearing half is who is absent: a **parent** and a **student** are the
#: subjects of this number, not its audience, and a **bursar** keeps the books.
#:
#: Wider than `results.services.APPROVING_ROLES` and narrower than "staff",
#: deliberately. It is a reading right over the whole class, so it is not the
#: same question as who may move the sheet along the chain.
POSITION_VIEWING_ROLES = frozenset(
    {
        Role.TEACHER.value,
        Role.VICE_PRINCIPAL_ACADEMIC.value,
        Role.PRINCIPAL.value,
        Role.ADMIN.value,
    }
)


class SubjectPlacingOut(Schema):
    """One child in one subject. `current_subject_rank` is the staff-only half.

    **Not called `position`, deliberately.** That word already names two
    different things in this codebase and this schema used to add a third:
    `ReleasedSubjectResult.position` is *where the line prints*, smallest first,
    while the rank in a subject is `ReleasedSubjectResult.subject_position`.
    A field here called `position` holding a rank was one paste away from being
    read as print order. Issue #55.
    """

    subject_id: int
    subject: str
    percentage: Optional[str]
    #: The child's rank in this subject **among the rows on this page**.
    #: For a released term that is the frozen subject lines; it is **not** a
    #: copy of `ReleasedSubjectResult.subject_position`, which records what was
    #: true at that card's own freeze.
    current_subject_rank: Optional[int]


class PlacingOut(Schema):
    """One child's row on the broadsheet.

    `average` and `current_rank` are `Optional` together and are null together:
    that pair is how "this child has no marks" reaches the screen, rather than a
    zero that would claim they sat exams and scored nothing. `gradebook.ScoreOut`
    keeps the same distinction for the same reason.

    ## `current_rank` is not `ReleasedCard.position`

    It is the child's rank **among the rows on this page, as this page is
    computed now**. For a released term the rows are the frozen cards, so the
    rank is derived from their `own_average` values.

    `ReleasedCard.position` is a different number and stays a different number:
    it records where the child came **at that card's own freeze**, which for a
    revised card is a later moment than the rest of the class. That field is the
    audit record and is why it is frozen at all; this one is what the page says
    today. They agree for every card released together and can disagree for a
    revised one — `TheRevisedChildTests` asserts exactly that, with both values
    written out. Issue #55.

    Percentages are strings, not floats. They are `Decimal` all the way through
    `positions` because ties are decided by equality, and handing them to JSON
    as floats would undo that at the last step for anybody who compares them.
    """

    student_membership_id: int
    student: str
    average: Optional[str]
    current_rank: Optional[int]
    subjects: List[SubjectPlacingOut]


class BroadsheetOut(Schema):
    class_group: str
    term: str
    #: Computed on demand and never stored — see `positions.class_average()`.
    #: Staff-only, like `current_rank`, and for the same reason. For a released
    #: term it is the mean of the frozen cards' `own_average` values, so it and
    #: the ranks on this page come from the same rows.
    class_average: Optional[str]
    #: Whether these rows are the frozen cards rather than live marks. A reader
    #: comparing two broadsheets needs to know which question each answered.
    from_snapshot: bool = False
    rows: List[PlacingOut]


def _school_of(request):
    """The school whose schema this request is already on.

    `None` is the portal host, where these tables do not exist at all — so a
    404 rather than a 403, the answer `gradebook.api._school_of()` gives and for
    the same reason: on the portal there is no such route, because there is no
    such broadsheet.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No results on this host.")
    return school


def _require_position_authority(actor, school):
    """A flat 404, not a 403, and that is the disclosure decision.

    `gradebook.api`'s `ExistenceOracleTests` settled this for the codebase: a
    caller who may not read this must not be able to tell a class that exists
    from one that does not by which refusal comes back. A parent probing class
    ids would otherwise map the school's whole class list.

    Asked before the class or term is looked up, so the refusal cannot depend on
    whether they exist.

    The unauthenticated branch is belt and braces: the router's `session_auth`
    answers first, with a 401, and never reaches this. It stays because the
    result checker this module will grow is `auth=None` by definition, and the
    day somebody adds it is the day this function stops being unreachable. A 401
    is no oracle either — it comes back whether or not the class exists.
    """
    if not getattr(actor, "is_authenticated", False):
        raise Http404("No such broadsheet.")
    if not set(actor.roles_at(school)) & POSITION_VIEWING_ROLES:
        raise Http404("No such broadsheet.")


def _named(school, student_ids) -> dict:
    """`membership id -> the child's name`, in one query.

    **Scoped to this school and to STUDENT in the lookup itself**, on the
    reasoning `gradebook.api._student_here()` sets out: a membership at another
    school is *not found* rather than found and then trusted.

    That matters more here than it looks, because of what the roster is made of.
    `ClassPlacement.student_membership_id` is a bare integer into the shared
    `public` membership table — no foreign key and no database integrity, the
    policy `docs/tenancy.md` settles — and it is checked against
    `why_not_a_student_here()` only at write time, by `academics.services`. A
    placement row that reached the table another way (a bad import, a script, a
    hand-edited row) would otherwise put another school's child's real name on
    this sheet, which is the one thing tenancy is supposed to make impossible.

    Narrowed, such a row simply has no name and renders `"—"`, the same blank an
    unmarked child gets.
    """
    return {
        membership.pk: membership.user.full_name or membership.user.username
        for membership in Membership.objects.select_related("user").filter(
            pk__in=student_ids, school=school, role=Role.STUDENT
        )
    }


def _as_text(value) -> Optional[str]:
    return None if value is None else str(value)


@router.get(
    "/classes/{class_group_id}/broadsheet/",
    response=BroadsheetOut,
    tags=["results"],
)
def broadsheet(request, class_group_id: int, term_id: int):
    """A class's term: every child's subject percentages, averages and ranks.

    **A released term is served from the snapshot; an unreleased one from live
    marks.** This docstring used to promise the first half as future work —
    "there is no frozen snapshot yet — that is task 3" — and task 3 shipped in
    #44 without the switch being made. The promise stood unkept long enough that
    the live and frozen rankings drifted apart in production shape: marks lock
    at release, but the *roster* does not, so a child placed into a released
    term (#31) made this page rank forty-six children while all forty-five
    frozen cards still said forty-five. Issue #55.

    Nothing here writes. The cards are read exactly as they were frozen, and
    every number this page derives is derived from the rows it is showing.
    """
    school = _school_of(request)
    _require_position_authority(request.user, school)

    class_group = get_object_or_404(ClassGroup, pk=class_group_id)
    term = get_object_or_404(Term, pk=term_id)

    sheet = ResultSheet.objects.filter(class_group=class_group, term=term).first()
    if sheet is not None and sheet.state == SheetState.RELEASED:
        return _from_the_snapshot(class_group, term, sheet)

    # One read of the marks for the whole page. Asking per row or per subject
    # would put every number on this response at a different instant — and the
    # gradebook saves a mark per cell-blur, so a teacher marking while a HOD
    # reads this is the ordinary case, not a race worth discounting. The
    # visible symptom is the one this module exists to prevent: 88.00 printed
    # above 91.00 because the percentage and the position were read either side
    # of an incoming mark. See `positions.ClassResults`.
    results = positions.class_results(class_group, term)
    names = _named(school, results.student_ids)

    # Only the subjects this class was actually marked in, which is what
    # `results.subject_ids` holds. `Subject.objects.all()` is the wrong list:
    # the table is per school and keeps retired subjects on purpose, so it puts
    # an all-blank column on the sheet for every subject the school teaches to
    # anybody. Ordered by `Subject.Meta.ordering`, so columns stay alphabetical
    # rather than falling into primary-key order.
    subjects = list(Subject.objects.filter(pk__in=results.subject_ids))

    rows = []
    for student_id in results.student_ids:
        rows.append(
            PlacingOut(
                student_membership_id=student_id,
                student=names.get(student_id, "—"),
                average=_as_text(results.averages.get(student_id)),
                current_rank=results.positions.get(student_id),
                subjects=[
                    SubjectPlacingOut(
                        subject_id=subject.pk,
                        subject=subject.name,
                        percentage=_as_text(
                            results.percentage(student_id, subject.pk)
                        ),
                        current_subject_rank=results.subject_position(
                            student_id, subject.pk
                        ),
                    )
                    for subject in subjects
                ],
            )
        )

    return BroadsheetOut(
        class_group=str(class_group),
        term=str(term),
        class_average=_as_text(results.class_average),
        rows=rows,
    )


def _from_the_snapshot(class_group, term, sheet):
    """The broadsheet as the released cards say it, deriving nothing from marks.

    Issue #55. Three rules hold this together, and they are the same rule:
    **every number on this page comes from the rows on this page.**

    1. The rows are `cards.cards_on(sheet)` — one card per child, the highest
       version, which is the `DISTINCT ON` that function was kept for. It said
       it had no caller and existed because "the rule any future batch reader
       needs" should not be rewritten from memory. This is that reader.
    2. `current_rank` is `dense_positions()` over the cards' frozen
       `own_average` values. **Not** a copy of `ReleasedCard.position`: those
       are per-card facts from possibly different freezes — `revision.revise()`
       reads the whole class inside its lock and freezes that card against the
       class as it then stands — so reading them off forty-five cards can put
       two children at the same rank on one page.
       `TheRevisedChildTests.test_the_page_never_repeats_a_rank` asserts exactly
       that: the frozen pair is `[1, 1]` where this derivation says `[1, 2]`.
    3. `class_average` is `mean_percentage()` over those same averages, still
       never stored, and now provably the mean of the numbers displayed beside
       it.

    A child with no card is absent from this page, which is the honest answer:
    she was not in what went home. The revision path is what gives her one
    (issue #31), and she appears here once it has.
    """
    released = released_cards.cards_on(sheet)

    averages = {
        card.student_membership_id: card.own_average
        for card in released
        if card.own_average is not None
    }
    ranks = positions.dense_positions(averages)

    # Columns in the order the cards froze them — `ReleasedSubjectResult.position`
    # is *print order*, not a rank. Taken from the cards rather than from
    # `Subject.objects` for the reason the live path gives, and because a subject
    # retired since release must still appear on a page that was released with it.
    columns = {}  # subject_id -> (print position, frozen name)
    for card in released:
        for line in card.subject_results.all():
            columns.setdefault(line.subject_id, (line.position, line.subject_name))
    ordered_subjects = sorted(
        columns.items(), key=lambda item: (item[1][0], item[1][1])
    )

    # One dense ranking per subject, over the frozen percentages on this page.
    per_subject = {}  # subject_id -> {student_id: frozen percentage}
    for card in released:
        for line in card.subject_results.all():
            if line.percentage is not None:
                per_subject.setdefault(line.subject_id, {})[
                    card.student_membership_id
                ] = line.percentage
    subject_ranks = {
        subject_id: positions.dense_positions(values)
        for subject_id, values in per_subject.items()
    }

    rows = []
    for card in released:
        student_id = card.student_membership_id
        lines = {line.subject_id: line for line in card.subject_results.all()}
        rows.append(
            PlacingOut(
                # The frozen name, not a live lookup: this page has to keep
                # saying what the card said, including whose card it was.
                student_membership_id=student_id,
                student=card.student_name,
                average=_as_text(card.own_average),
                current_rank=ranks.get(student_id),
                subjects=[
                    SubjectPlacingOut(
                        subject_id=subject_id,
                        subject=name,
                        percentage=_as_text(
                            lines[subject_id].percentage
                            if subject_id in lines
                            else None
                        ),
                        current_subject_rank=subject_ranks.get(subject_id, {}).get(
                            student_id
                        ),
                    )
                    for subject_id, (_, name) in ordered_subjects
                ],
            )
        )

    return BroadsheetOut(
        class_group=str(class_group),
        term=str(term),
        class_average=(
            _as_text(positions.mean_percentage(averages.values()))
            if averages
            else None
        ),
        rows=rows,
        from_snapshot=True,
    )


__all__ = ["POSITION_VIEWING_ROLES", "router"]
