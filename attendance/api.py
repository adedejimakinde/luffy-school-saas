"""HTTP for a register: read one, take one, take one back.

Three endpoints, and their shape is decided by one interaction — the same way
`gradebook.api`'s was, and to the opposite conclusion.

**One request per register, not one per child.** A marking sheet saves on blur
because a teacher tabs through thirty cells over twenty minutes and losing the
tab must not lose the lot. A register is the other interaction entirely: one
screen, a few taps, one submit, thirty seconds. Forty-five conditional PUTs from
a phone in a corridor is not a register, and the unit of a write here is the
register because that is what actually happened — somebody stood in front of a
class and marked it once.

**The answer says what was written, not "ok".** `RegisterTaken` carries four
lists and the endpoint passes all four through. A child who appeared on the
roster after the screen loaded is unmarked and named; an absentee who has since
been moved out of the group is refused and named. Neither fails the request,
because a teacher in front of a class should not lose a register over one child
the office moved while they were marking — but a screen that was told only a
count could not say either sentence.

**The date is a path segment with no converter, and that is not an oversight.**
Django ships no `date` path converter, and registering one platform-wide to
serve three routes would be a URL-resolution change made for a corner of one
app. The segment is a plain string and the parameter is annotated `date`, so
django-ninja parses and validates it — a malformed one is a 422 naming the
field, which is a better answer than a 404 from a converter that simply failed
to match.

**The roster the screen drew is part of the submission.** `shown_ids` is what
makes the two reports above possible at all. A client that omits it is taken to
mean "whatever the roster is now", which is right for a caller with no screen
and wrong for a phone; the field is optional in the schema and the docstring on
`TakeRegisterIn` says which of the two you are.
"""

from datetime import date
from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import ClassGroup, Term
from accounts.models import Membership, Role
from accounts.session import session_auth

from . import services

router = Router(auth=session_auth)


# -- response and request shapes ---------------------------------------------


class RegisterRowOut(Schema):
    """One child on the register screen.

    `status` is nullable and null means **not marked**, which is a different
    answer from either value it could hold. It is how "this register exists and
    this child has no entry in it" reaches the screen, and it is the same
    distinction the tables keep by having no row rather than a third status.
    """

    student_membership_id: int
    student: str
    status: Optional[str]


class RegisterOut(Schema):
    """A register as it stands, or as it would stand if taken now.

    `taken` is false when no register exists for this slot yet, and the rows are
    then the roster with every `status` null. That is deliberately not the same
    payload as a register in which everybody happens to be unmarked — `taken`
    is what tells them apart, and a client that showed the rows without it would
    be unable to.
    """

    class_group_id: int
    class_group: str
    term_id: int
    term: str
    taken_on: date
    taken: bool
    rows: List[RegisterRowOut]


class TakeRegisterIn(Schema):
    """What one submit sends.

    `absent_ids` is what the teacher tapped; everyone else the screen showed is
    present. That default is the whole reason this fits in thirty seconds, and
    it is also why an empty list is a meaningful submission rather than an empty
    one: it says every child was there.

    `shown_ids` is the roster the screen drew. Omitting it means "whatever the
    roster is now" — correct for an import or a shell, wrong for a phone, which
    knows exactly which names it displayed. A client that omits it gets no
    `appeared` report, because without it there is nothing to compare against.
    """

    absent_ids: List[int] = []
    shown_ids: Optional[List[int]] = None


class RegisterTakenOut(Schema):
    """What the write did, in the four sentences it may need to say."""

    class_group_id: int
    taken_on: date
    present: List[int]
    absent: List[int]
    #: On the roster now, not on the screen then, and therefore not marked.
    appeared: List[int]
    #: Submitted as absent, not on the roster now. Nothing written for them.
    not_on_the_roster: List[int]


class MarkableClassOut(Schema):
    """One class group this school teaches, for the chooser to draw."""

    id: int
    name: str
    level: int


class WhereToMarkOut(Schema):
    """What the register screen needs before it can ask for a register.

    Both card routes taught this lesson once already: a screen keyed on ids
    nothing ever handed it is a screen openable only by typing integers into a
    URL. The register is keyed on `(class_group, term, date)` and until now the
    API named none of the three.

    `term` is **the school's own current term**, not one worked out from
    today's date. `Term.is_current` is a column the school sets, unique by
    constraint, and it is the same authority `school_days` comes from — a
    screen that inferred the term from the calendar would disagree with the
    school the first time a term ran late, and the register it wrote would be
    filed against the wrong one.

    `None` where no term is marked current. The screen then says so instead of
    guessing, because a register filed against a guessed term is worse than a
    register not taken: nothing about the row says it was a guess.

    **Every class the school teaches, not a subset.** Any teacher may take any
    class's register — `can_mark_attendance()` is school-wide and carries no
    reference to `ClassTeacher` — so a narrower list here would be a scope this
    platform does not enforce, shown as though it did. That gap is issue #125,
    which is also where the domain question behind it lives (the subject
    teacher covering an absent form teacher). Narrowing the screen while the
    route stays open would be the restriction-that-looks-enforced this codebase
    keeps finding.
    """

    term_id: Optional[int]
    term: Optional[str]
    classes: List[MarkableClassOut]


class MessageOut(Schema):
    detail: str


# -- the pieces every endpoint needs -----------------------------------------


def _school_of(request):
    """The school whose schema this request is already on.

    `None` is the portal host, where these tables do not exist at all rather
    than existing and being empty — the same answer `gradebook.api._school_of()`
    gives, and for the same reason. A 404, not a 403: on the portal there is no
    such route, because there is no such register.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No register on this host.")
    return school


#: One sentence for every refusal of authority, so that "you may not mark" and
#: "there is no such group" cannot be told apart by their wording. Deliberately
#: not `services.NotAllowedToMarkAttendance`'s text, which names the actor and
#: the school; that belongs in a log, not in a response body. The gate
#: `gradebook.api._MAY_NOT_MARK` sets, copied for the reason it gives.
_MAY_NOT_MARK = (
    "A register is taken by a teacher, a principal or an administrator of the "
    "school the class belongs to."
)


def _refuse_non_markers(request, school):
    """The authority check, **before** either lookup. A response, or None.

    Order is the whole point, and `gradebook.api._refuse_non_markers()` is where
    this codebase learned it: `get_object_or_404()` answers 404 for a row that is
    not there and lets the request go on to a 403 for one that is, so asking
    authority *second* turns every route here into an existence oracle for
    anybody signed in at the school — parents and students included. They could
    not take a register either way, but they could walk the id space and learn
    which class groups and which terms are real by reading the status code.
    """
    if not services.can_mark_attendance(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_MARK)
    return None


def _names_for(school, student_ids) -> dict[int, str]:
    """`membership_id -> the child's name`, for the roster being shown.

    One query for the class, not one per child. Scoped to this school and to
    STUDENT in the lookup itself, so a membership at another school is simply
    absent from the map rather than found and then filtered.

    **`Membership.name` is a property, not a column**, so it cannot be selected
    — the expression behind it is spelled out instead, exactly as
    `results.cards._student_names()` spells it. The school's own name for the
    child comes first, because `display_name` exists for schools that know a
    child by a different name than the one on their login, and the register is a
    screen where the teacher needs the name they use out loud.

    Falls back to the empty string rather than to the username: a username on a
    register is a hint the teacher cannot act on, and the roster still needs its
    row so the child can be marked.
    """
    return {
        row["pk"]: row["display_name"] or row["user__full_name"] or ""
        for row in Membership.objects.filter(
            school=school, role=Role.STUDENT.value, pk__in=list(student_ids)
        ).values("pk", "display_name", "user__full_name")
    }


def _rows_for(school, roster, marks) -> List[RegisterRowOut]:
    names = _names_for(school, roster)
    return [
        RegisterRowOut(
            student_membership_id=sid,
            student=names.get(sid, ""),
            status=marks.get(sid),
        )
        for sid in roster
    ]


# -- the endpoints -----------------------------------------------------------


@router.get("/where/", response={200: WhereToMarkOut, 403: MessageOut})
def where_to_mark(request):
    """The classes and the term a register can be taken for, for the screen.

    **The authority check is first, before either read**, for the reason
    `_refuse_non_markers()` gives: asking it second turns this into a directory
    of the school's class groups for anybody signed in there, parents and
    students included. They could not take a register either way; they could
    read the roll's shape off a 200.
    """
    school = _school_of(request)
    refusal = _refuse_non_markers(request, school)
    if refusal:
        return refusal

    term = Term.objects.filter(is_current=True).first()
    return WhereToMarkOut(
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        classes=[
            MarkableClassOut(id=group.pk, name=group.name, level=group.level)
            for group in ClassGroup.objects.filter(is_active=True)
        ],
    )


@router.get(
    "/classes/{int:class_group_id}/terms/{int:term_id}/{on}/",
    response={200: RegisterOut, 403: MessageOut},
)
def register(request, class_group_id: int, term_id: int, on: date):
    """The register for one group on one day — taken or not.

    A GET that answers for a register that does not exist yet is the point
    rather than a convenience: the screen the teacher opens is the roster with
    nothing marked, and making the client assemble that from a 404 plus a
    separate roster call would be two requests for one screen, on the connection
    this feature is least able to afford them.
    """
    school = _school_of(request)
    refusal = _refuse_non_markers(request, school)
    if refusal:
        return refusal

    group = get_object_or_404(ClassGroup, pk=class_group_id)
    term = get_object_or_404(Term, pk=term_id)
    roster = services.roster_ids(group, term)
    existing = services.register_for(group, on)
    marks = services.marks_in(existing) if existing else {}

    return RegisterOut(
        class_group_id=group.pk,
        class_group=str(group),
        term_id=term.pk,
        term=str(term),
        taken_on=on,
        taken=existing is not None,
        rows=_rows_for(school, roster, marks),
    )


@router.put(
    "/classes/{int:class_group_id}/terms/{int:term_id}/{on}/",
    response={200: RegisterTakenOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def take(
    request,
    class_group_id: int,
    term_id: int,
    on: date,
    payload: TakeRegisterIn,
):
    """Take or amend the register for one group on one day.

    PUT rather than POST because it is this slot being set to a state, and a
    teacher who submits twice — because the first answer was slow, or because
    they corrected one tap — has not taken two registers. There is exactly one
    register per group per day, by constraint, and this route is how it gets its
    contents.

    **409 for a group with nobody in it**, not 404 and not 422: the group and
    the term both exist and the request is well-formed, but the state of the
    school is wrong for it. A register for an empty group would record that
    somebody marked nothing, which is indistinguishable from the admin gap
    `days_open` measures.

    **422 for a date outside the term.** That is the request disagreeing with
    itself — this date and this term cannot both be right — and it is a rule no
    check constraint can hold, because a check constraint sees one row of one
    table. `services.DayOutsideTheTerm` is where it lives and why.
    """
    school = _school_of(request)
    refusal = _refuse_non_markers(request, school)
    if refusal:
        return refusal

    group = get_object_or_404(ClassGroup, pk=class_group_id)
    term = get_object_or_404(Term, pk=term_id)

    try:
        taken = services.take_register(
            group,
            term,
            on=on,
            absent_ids=payload.absent_ids,
            shown_ids=payload.shown_ids,
            by=request.user,
        )
    except services.NoRoster as exc:
        return 409, MessageOut(detail=str(exc))
    except services.DayOutsideTheTerm as exc:
        return 422, MessageOut(detail=str(exc))

    return RegisterTakenOut(
        class_group_id=group.pk,
        taken_on=on,
        present=taken.present,
        absent=taken.absent,
        appeared=taken.appeared,
        not_on_the_roster=taken.not_on_the_roster,
    )


@router.delete(
    "/classes/{int:class_group_id}/{on}/",
    response={204: None, 403: MessageOut, 404: MessageOut},
)
def discard(request, class_group_id: int, on: date):
    """Take back a register filed against the wrong day.

    Not how a wrong *mark* is fixed — that is a second PUT, which amends. This
    is for a register about a day that did not happen, where every mark in it is
    wrong for the same reason.
    """
    school = _school_of(request)
    refusal = _refuse_non_markers(request, school)
    if refusal:
        return refusal

    group = get_object_or_404(ClassGroup, pk=class_group_id)
    if not services.discard_register(group, on):
        return 404, MessageOut(detail="No register was taken for that slot.")
    return 204, None
