"""HTTP for a marking sheet: read it, save one mark, take one back.

Three endpoints, and their shape is decided by one interaction. A teacher
marking a class of thirty does not fill in a form and press Save at the bottom.
They tab through thirty cells, and each one has to save as it loses focus —
because the alternative is a teacher who spends twenty minutes marking, loses
the tab, and loses the lot. Every choice below follows from that:

**One mark per request.** Blur fires per cell, so the unit of a write is a
single student's mark on a single assessment, not a sheet. There is no bulk
save endpoint and a sheet is not a transaction: thirty independent writes is
what actually happened, and it is what should be recorded.

**Every write answers with the new version and the recomputed total.** Those
are the two things on the screen that a save invalidates. Returning them in the
response the client already has to wait for is what makes "refresh the total
before display" true by construction rather than by the client remembering to
ask again — and a client that never issues a second request cannot forget to.

**A conflict is a body, not a bare status.** `ScoreChangedMeanwhile` carries the
row as it now stands, so the 409 does too. "Somebody else changed this" is not
useful to a teacher; "Kemi entered 17 while you were typing" is, and the client
cannot say the second without being told what the mark now is.

**A closed sheet is a 423, and it is neither of the two codes it looks like.**
`MarksLocked` says the term has left `draft` — submitted, checked, approved or
released — so the mark cannot be written now and, for a released term, cannot
be written ever. It is not a **409**: in this API that code means "somebody
changed this while you were typing", and the client answers it by reloading the
cell and sending again. A blur handler doing that against a released sheet
retries for ever, because nothing it can reload will reopen the term. It is not
a **403** either: the caller's authority has not changed and is not the
problem — a teacher who could mark this child an hour ago still can, once the
sheet is sent back. What changed is the state of the resource, which is what
423 is for.

The same reasoning applies to `results.ratings.RatingsLocked` and
`results.comments.CommentsLocked`, which are the same refusal about the other
two thirds of the same card. Neither has an HTTP surface yet — `results.api`
exposes one read-only broadsheet route — and when they get one it is this code,
so that one refusal does not arrive as three.

**No school slug in any path**, unlike the `/api/schools/{slug}/...` invitation
routes. Those write shared tables, where the school is a row that has to be
named. The gradebook is a tenant app: its tables live in the school's own
schema, and `TenantMainMiddleware` has already chosen that schema from the
hostname before any code here runs. A slug in the path would be a *second*
opinion about which school this is, free to disagree with the connection — and
a disagreement means authorising against one school and writing into another's
schema. `services._require_student_of_this_school()` reads the connection for
exactly this reason; the routing does the same thing by having nothing to read.
"""

from typing import List, Optional

from django.db.models import Count, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import ClassGroup, ClassPlacement, Term
from accounts.models import Membership, Role
from accounts.session import session_auth
from results import services as results_services

from . import services
from .models import Assessment, Score

#: Auth on the router rather than on each operation, unlike the invitation
#: routes — those genuinely mix authenticated and anonymous halves, and spell it
#: out per endpoint because the anonymous ones are the surprising case. Nothing
#: here is ever anonymous, so the default belongs in one place where a fourth
#: endpoint added later inherits it instead of having to remember it.
router = Router(auth=session_auth)


# -- response and request shapes ---------------------------------------------


class TotalOut(Schema):
    """A running total, computed at the moment it was asked for.

    Three numbers rather than a percentage, because the percentage is a
    rendering decision and `available` can be zero. A client dividing by it
    knows to show a dash; a server that had already divided would have had to
    invent something.
    """

    scored: int
    available: int
    marked: int


class ScoreOut(Schema):
    """One cell, as it stands after whatever just happened to it.

    `value` and `version` are both nullable and are always null together: that
    pair is how "not marked" reaches the screen, and it is the same distinction
    `models.py` keeps in the table by having no row at all. A client that sees
    null sends `expected_version: null` back on the next save, which is what
    tells `set_score()` this must be an insert.
    """

    student_membership_id: int
    value: Optional[int]
    version: Optional[int]
    max_score: int
    total: TotalOut


class SheetRowOut(ScoreOut):
    student: str


class SheetOut(Schema):
    """One class group's rows for one assessment, and whether they can be written.

    **`locked` is a fact about the sheet, not about each row**, and that is a
    consequence of the class group being required rather than a simplification.
    `services._require_the_sheet_is_open()` resolves a child through
    `placement_of(student, term)`; `ClassPlacement` is unique per
    `(term, student_membership_id)` by constraint; and
    `results_services.locked_sheet_for()` answers per `(class_group, term)`. So
    every child in a scoped sheet resolves to the *same* `ResultSheet`, and a
    per-row flag would be N copies of one answer costing N queries.

    It exists at all because this screen saves on blur. Without it a teacher
    types a mark into a cell that cannot accept it, tabs away, and learns from
    the 423 — after typing. The number they just entered is the worst moment to
    discover the sheet shut.

    `locked` is `False` where no `ResultSheet` row exists yet, which is the
    ordinary case for a term nobody has submitted: `is_open_for_writing(None)`
    is what `locked_sheet_for()` returning `None` means, and a term with no
    sheet is open rather than closed.
    """

    assessment_id: int
    assessment: str
    subject: str
    term: str
    class_group_id: int
    class_group: str
    max_score: int
    locked: bool
    #: Why it is locked, for the sentence the screen shows. `None` when open.
    locked_reason: Optional[str] = None
    rows: List[SheetRowOut]


class MarkableAssessmentOut(Schema):
    id: int
    name: str
    subject: str
    max_score: int


class MarkableGroupOut(Schema):
    id: int
    name: str
    level: int


class WhereToMarkOut(Schema):
    """What the marking screen needs before it can ask for a sheet.

    The sheet is keyed on `(assessment, class_group)` and the API named neither
    — the same gap the card index closed for a family and
    `attendance.api.where_to_mark()` closed for the register. A screen keyed on
    ids nothing ever handed it is a screen openable only by typing integers
    into a URL.

    `term` is the school's own `Term.is_current`, never one inferred from
    today's date: a computed term disagrees with the school the first time a
    term runs late, and a mark filed against the wrong one carries nothing
    saying it was a guess.

    **Every subject and every class, not a subset.** `can_enter_marks()` is
    school-wide and carries no reference to a subject or a class group, so a
    narrower list would be a scope the platform does not enforce, drawn as
    though it did. That gap is issue #128, alongside #125 and #25; the reason a
    sheet cannot be scoped by subject even in principle is issue #127 —
    nothing models which students take which subject, so SSS electives cannot
    be expressed at all.
    """

    term_id: Optional[int]
    term: Optional[str]
    assessments: List[MarkableAssessmentOut]
    classes: List[MarkableGroupOut]


class SaveIn(Schema):
    """What a blur sends.

    `expected_version` is required in spirit and defaulted in fact, and the
    default is the safe one: `None` means "I was shown no mark", which
    `set_score()` reads as an insert. So a client that omits the field entirely
    gets a 409 the moment a row already exists, rather than an overwrite. There
    is deliberately no HTTP spelling of `services.ANY_VERSION` — that sentinel
    is for callers with no screen, and everything reaching this module has one.
    """

    value: int
    expected_version: Optional[int] = None


class ConflictOut(Schema):
    """A 409 that says what the mark now is, not merely that it moved.

    `current` is null when the row has been cleared since the client was shown
    it — a real outcome and a different one from "it now reads 17", which is
    why the field is nullable rather than the endpoint having two error shapes.
    """

    detail: str
    current: Optional[ScoreOut]


class MessageOut(Schema):
    detail: str


# -- the pieces every endpoint needs -----------------------------------------


def _school_of(request):
    """The school whose schema this request is already on.

    `None` is the portal host, where these tables do not exist at all rather
    than existing and being empty — `test_the_score_table_is_absent_from_public`
    pins that. So a 404, not a 403: on the portal there is no such route,
    because there is no such gradebook.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No gradebook on this host.")
    return school


def _student_here(school, student_membership_id) -> Membership:
    """The student's membership, or a flat 404.

    Scoped to this school and to STUDENT in the lookup itself, so a membership
    at another school is *not found* rather than found and then refused.

    That is a disclosure decision, not tidiness. `services` refuses the same
    thing with `NotThisSchoolsStudent`, whose message names the child and the
    school they actually attend — correct for a log and a test, and a
    cross-tenant leak if it were ever returned to an HTTP caller. Looking the
    row up narrowly means the refusal never reaches that far, on the same
    reasoning as the flat 404 the invitation routes answer a bad token with.
    """
    return get_object_or_404(
        Membership.objects.select_related("school", "user"),
        pk=student_membership_id,
        school=school,
        role=Role.STUDENT,
    )


def _running_total_scope(assessment):
    """Which marks the total on a sheet adds up.

    This subject, this term. Not the student's every mark ever, which spans
    subjects and sessions and is not a number anybody wants next to a
    Mathematics First CA; and not this assessment alone, which is already the
    cell. A teacher entering the Exam wants to see the CAs move with it.
    """
    return Score.objects.for_term(assessment.term_id).for_subject(
        assessment.subject_id
    )


def _total_for(assessment, student_membership_id) -> TotalOut:
    return TotalOut(
        **_running_total_scope(assessment).total_for(student_membership_id)
    )


def _totals_for_everyone(assessment) -> dict:
    """Every student's running total in one query rather than one each.

    `.order_by()` with no arguments is doing real work here and is not a
    leftover. `Score.Meta.ordering` is `["assessment", "student_membership_id"]`,
    and Django appends the ordering columns to the GROUP BY of a
    `.values().annotate()` — so without clearing it the rows come back grouped
    by student *and assessment*, which is one row per mark and a "total" that
    is just the mark itself.
    """
    grouped = (
        _running_total_scope(assessment)
        .values("student_membership_id")
        .annotate(
            scored=Sum("value"),
            available=Sum("assessment__max_score"),
            marked=Count("id"),
        )
        .order_by()
    )
    return {
        row["student_membership_id"]: TotalOut(
            scored=row["scored"] or 0,
            available=row["available"] or 0,
            marked=row["marked"] or 0,
        )
        for row in grouped
    }


def _cell(assessment, student_membership_id, score, total) -> dict:
    return {
        "student_membership_id": student_membership_id,
        "value": None if score is None else score.value,
        "version": None if score is None else score.version,
        "max_score": assessment.max_score,
        "total": total,
    }


#: What a caller who may not mark is told, on both write routes.
#:
#: One string, because it is now the answer to two different questions — "may
#: you mark?" and "does that assessment exist?" — and the whole point of the
#: gate below is that those two are indistinguishable from outside. Two copies
#: that drifted by a word would hand back exactly the difference the gate exists
#: to remove.
#:
#: Deliberately not `services.NotAllowedToMark`'s text, which names the actor and
#: the school; that belongs in a log, not in a response body.
_MAY_NOT_MARK = (
    "Marking is done by a teacher, a principal or an administrator of the "
    "school that set the assessment."
)


def _refuse_non_markers(request, school):
    """The authority check, before either lookup. Returns a response or None.

    Order is the whole point. `get_object_or_404()` answers 404 for a row that is
    not there and lets the request go on to a 403 for one that is — so asking
    authority *second* turns both write routes into an existence oracle for
    anybody signed in at the school, parents and students included. They could
    not write a mark either way, but they could walk the id space and learn which
    assessments and which student memberships are real by reading the status
    code. `marking_sheet()` has always gated first; these two now match it.

    Narrow on purpose: it closes on non-markers only. A teacher still gets a 404
    for an assessment that is not there, because for them that is a fact they are
    entitled to and the honest answer to their own typo.
    """
    if services.can_enter_marks(request.user, school):
        return None
    return 403, MessageOut(detail=_MAY_NOT_MARK)


def _is_our_write_arriving_twice(current, payload, actor) -> bool:
    """A retried blur, not a conflict.

    Blur fires more than once for one edit: tabbing out of a cell and then
    submitting, a browser retrying a request whose response was lost, a
    double-fired event. Each retry carries the version the teacher was *shown*,
    which the first attempt has already moved past — so a plain version check
    calls the retry a conflict and tells a teacher that somebody else is editing
    their sheet when nobody is. Cry wolf on that once and the warning stops
    being read, which costs exactly the protection the version exists to give.

    Swallowing it is only safe when the row already says precisely what this
    request asked for **and** this same person wrote it. A different value means
    the mark genuinely moved; another person's write means somebody else is in
    the sheet. Both are real, and both are still reported.
    """
    return (
        current is not None
        and current.value == payload.value
        and actor.pk is not None
        and current.updated_by_id == actor.pk
    )


# -- reading the sheet -------------------------------------------------------


@router.get("/where/", response={200: WhereToMarkOut, 403: MessageOut})
def where_to_mark(request):
    """The assessments and classes a sheet can be asked for, for the screen.

    **Authority first, before either read.** `_refuse_non_markers()` gives the
    reason at length: asking it second turns this into a directory of the
    school's subjects and class groups for anybody signed in there, parents and
    students included. They could not mark either way; they could read the
    shape of the school off a 200.
    """
    school = _school_of(request)
    refused = _refuse_non_markers(request, school)
    if refused is not None:
        return refused

    term = Term.objects.filter(is_current=True).first()
    assessments = (
        []
        if term is None
        else [
            MarkableAssessmentOut(
                id=a.pk, name=a.name, subject=a.subject.name, max_score=a.max_score
            )
            for a in Assessment.objects.filter(term=term).select_related("subject")
        ]
    )
    return WhereToMarkOut(
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        assessments=assessments,
        classes=[
            MarkableGroupOut(id=g.pk, name=g.name, level=g.level)
            for g in ClassGroup.objects.filter(is_active=True)
        ],
    )


@router.get(
    "/assessments/{int:assessment_id}/sheet/",
    response={200: SheetOut, 403: MessageOut, 422: MessageOut},
)
def marking_sheet(
    request, assessment_id: int, class_group_id: Optional[int] = None
):
    """One class group's rows for one assessment, marked or not.

    The unmarked students are the point. They have no `Score` row — that is the
    module's whole premise — so they cannot come from the score table, and a
    sheet built from it would show only the children already marked.

    **The roster is the class group's, and `class_group_id` is required.** It
    used to be `school_directory(school, role=STUDENT)` — *every* student in
    the school — which was invisible while there was no screen and is not a
    sheet anybody can mark from: an `Assessment` carries a term and a subject
    and **no class group**, so "First CA / Mathematics" listed Primary 1 beside
    JSS 3B.

    Required rather than optional, because a default of "everyone" is the
    behaviour being removed. A caller who omits it gets a 422 naming the field,
    which is a better answer than eight hundred rows.

    **It is typed `Optional` and required by hand, and that is about ordering
    rather than taste.** A required query parameter is validated by ninja
    *before* the view runs, which puts the 422 in front of both checks below:
    a caller on the portal would be told "this wants a `class_group_id`" where
    the honest answer is "there is no gradebook on this host", and — worse — a
    parent omitting the field would get a 422 instead of a 403, learning that
    the route is real and what shape it takes. That is precisely the existence
    oracle `_refuse_non_markers()` is written to close, arriving one layer
    above it. So the host answers first, then authority, then the field.

    This is a **view scope, not an authority narrowing**. `can_enter_marks()`
    is unchanged and still school-wide; who may mark is issue #128. Narrowing
    the list here while the write stays open would be a restriction that looked
    enforced and was not.

    Relationship-scoped through `ClassPlacement`, so a suspended student still
    appears: a teacher marks from the roll the office keeps, and silently
    dropping a child is how a mark goes missing with nobody noticing.

    Gated on `can_enter_marks()` — the same authority as writing, deliberately.
    `SchoolAccessMiddleware` has only established that the caller belongs to
    this school, and this school's parents and students belong to it too. A
    sheet is the whole class's marks side by side, which is the one thing a
    parent must not be handed.
    """
    school = _school_of(request)
    if not services.can_enter_marks(request.user, school):
        return 403, MessageOut(
            detail="A marking sheet is the whole class's marks. It is shown to "
            "the staff who enter them."
        )
    if class_group_id is None:
        return 422, MessageOut(
            detail="A marking sheet is one class group's. Name the group with "
            "`class_group_id`."
        )
    assessment = get_object_or_404(
        Assessment.objects.select_related("subject", "term"), pk=assessment_id
    )
    group = get_object_or_404(ClassGroup, pk=class_group_id)

    roster = ClassPlacement.objects.student_ids(group, assessment.term)
    students = {
        m.pk: m
        for m in Membership.objects.filter(pk__in=roster).select_related("user")
    }

    scores = {
        score.student_membership_id: score
        for score in Score.objects.filter(
            assessment=assessment, student_membership_id__in=roster
        )
    }
    totals = _totals_for_everyone(assessment)
    empty = TotalOut(scored=0, available=0, marked=0)

    rows = [
        SheetRowOut(
            student=students[sid].user.full_name or students[sid].user.username,
            **_cell(assessment, sid, scores.get(sid), totals.get(sid, empty)),
        )
        for sid in sorted(
            students,
            key=lambda sid: (
                students[sid].user.full_name or students[sid].user.username
            ),
        )
    ]

    # One read for the whole sheet — see `SheetOut.locked` for why this is a
    # sheet-level fact once the class group is required.
    sheet = results_services.locked_sheet_for(group, assessment.term)
    open_for_writing = results_services.is_open_for_writing(sheet)

    return SheetOut(
        assessment_id=assessment.pk,
        assessment=assessment.name,
        subject=assessment.subject.name,
        term=str(assessment.term),
        class_group_id=group.pk,
        class_group=group.name,
        max_score=assessment.max_score,
        locked=not open_for_writing,
        locked_reason=None
        if open_for_writing
        else (
            f"{group.name} — {assessment.term} is "
            f"{sheet.get_state_display().lower()}, so its marks cannot be "
            f"changed here."
        ),
        rows=rows,
    )


# -- saving one mark ---------------------------------------------------------


@router.put(
    "/assessments/{int:assessment_id}/scores/{int:student_membership_id}/",
    response={
        200: ScoreOut,
        403: MessageOut,
        409: ConflictOut,
        422: MessageOut,
        423: MessageOut,
    },
)
def save_score(
    request, assessment_id: int, student_membership_id: int, payload: SaveIn
):
    """Enter or change one mark. This is what a blur calls.

    PUT rather than POST because it is the cell being set to a value, and a
    teacher who tabs out of an unchanged cell should not create anything. The
    version check makes it conditional, not blind, so this is not the unsafe
    kind of idempotent.
    """
    school = _school_of(request)
    refused = _refuse_non_markers(request, school)
    if refused is not None:
        return refused
    assessment = get_object_or_404(Assessment, pk=assessment_id)
    student = _student_here(school, student_membership_id)

    try:
        score = services.set_score_as(
            request.user,
            assessment,
            student,
            payload.value,
            expected_version=payload.expected_version,
        )
    except services.NotAllowedToMark as exc:
        # Ahead of GradebookError, which is its base class: a refusal of
        # authority is a 403 and a refusal of state is not, and one handler
        # cannot tell them apart once the first has been caught.
        return 403, MessageOut(detail=str(exc))
    except services.ScoreChangedMeanwhile as exc:
        if _is_our_write_arriving_twice(exc.current, payload, request.user):
            return 200, ScoreOut(
                **_cell(
                    assessment,
                    student.pk,
                    exc.current,
                    _total_for(assessment, student.pk),
                )
            )
        return 409, ConflictOut(
            detail=str(exc),
            current=None
            if exc.current is None
            else ScoreOut(
                **_cell(
                    assessment,
                    student.pk,
                    exc.current,
                    _total_for(assessment, student.pk),
                )
            ),
        )
    except services.MarksLocked as exc:
        # 423, and see the module docstring for why not 409 or 403. Caught
        # after `ScoreChangedMeanwhile` only because the two cannot both be
        # raised — the state guard runs first and this is a sibling under
        # `GradebookError`, so the order between them is readability, not
        # dispatch.
        return 423, MessageOut(detail=str(exc))
    except services.NotThisSchoolsStudent:
        # Unreachable through `_student_here()`, which has already scoped the
        # lookup. Kept as a backstop, and answered with a bare 404 carrying
        # none of the exception's text — that message names the child and the
        # school they actually attend, which is another tenant's data.
        raise Http404("No such student here.")
    except services.InvalidScore as exc:
        # 422, matching `/accept/`: the request is well formed and the caller
        # is allowed: the number is the problem, and it is one they can retype.
        return 422, MessageOut(detail=str(exc))

    return 200, ScoreOut(
        **_cell(assessment, student.pk, score, _total_for(assessment, student.pk))
    )


@router.delete(
    "/assessments/{int:assessment_id}/scores/{int:student_membership_id}/",
    response={200: ScoreOut, 403: MessageOut, 409: ConflictOut, 423: MessageOut},
)
def clear_score(
    request, assessment_id: int, student_membership_id: int, expected_version: int
):
    """Take a mark back. The row goes; it is not set to zero.

    `expected_version` is a required query parameter with no default, mirroring
    `services.clear_score()`, where it is a keyword argument with no default for
    the same reason: "clear whatever is there" is precisely the destructive
    write the version exists to prevent, and it should not have a convenient
    spelling. A blur that finds an emptied cell has a version to send — it was
    shown one.

    200 with a body rather than 204, because the total this mark was part of has
    just changed and the row on the screen showing it is still there. A 204
    would be honest about the mark and leave the total stale, which is the bug
    this feature exists to fix.
    """
    school = _school_of(request)
    refused = _refuse_non_markers(request, school)
    if refused is not None:
        return refused
    assessment = get_object_or_404(Assessment, pk=assessment_id)
    student = _student_here(school, student_membership_id)

    try:
        services.clear_score_as(
            request.user,
            assessment,
            student,
            expected_version=expected_version,
        )
    except services.NotAllowedToMark as exc:
        return 403, MessageOut(detail=str(exc))
    except services.ScoreChangedMeanwhile as exc:
        return 409, ConflictOut(
            detail=str(exc),
            current=ScoreOut(
                **_cell(
                    assessment,
                    student.pk,
                    exc.current,
                    _total_for(assessment, student.pk),
                )
            ),
        )
    except services.MarksLocked as exc:
        # As in `save_score()`. Reachable only when there is a mark to take
        # back: clearing one that is already gone is a no-op at every state,
        # which is `services.clear_score()`'s idempotency promise and is why
        # the retried DELETE of an already-cleared mark still answers 200.
        return 423, MessageOut(detail=str(exc))
    except services.NotThisSchoolsStudent:
        raise Http404("No such student here.")

    return 200, ScoreOut(
        **_cell(assessment, student.pk, None, _total_for(assessment, student.pk))
    )
