"""HTTP for the school's calendar. One route, and it has no page.

`Term.school_days` is the denominator of every attendance figure a card prints,
and until this route it had constraints, documentation and **no writer** — no
admin, no form, no service function, reachable only from the ORM. So a school
could keep a perfect register all term and still send home a card with a blank
attendance line, because nothing could ever say how many days the term held.

**There is deliberately no screen**, and D12 in `docs/attendance.md` is the
argument: there are no staff pages anywhere in this project yet, and inventing
one here would drag the attendance slice into the staff-UI problem the register
screen already has to solve — the same problem, once, rather than twice in two
shapes. Nobody should read this route's existence as implying a page.
"""

from typing import Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from accounts.session import session_auth

from . import services
from .models import Term

router = Router(auth=session_auth)


class TermLengthIn(Schema):
    """How many teaching days the term held, as the school counts them.

    Nullable, and clearing is a real act rather than a mistake: a term whose
    length was entered wrongly and is not yet known again is better described by
    a blank than by a number somebody has stopped believing. A blank prints as
    "not recorded" on the card rather than as a zero.
    """

    school_days: Optional[int] = None


class TermOut(Schema):
    term_id: int
    term: str
    starts_on: str
    ends_on: str
    calendar_days: int
    school_days: Optional[int]


class MessageOut(Schema):
    detail: str


#: One sentence for every refusal, so that "you may not" and "there is no such
#: term" cannot be told apart by their wording. The gate
#: `gradebook.api._MAY_NOT_MARK` sets, for the reason it gives.
_MAY_NOT_SET = (
    "How many days a term taught is declared by a principal or an "
    "administrator of the school."
)


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No calendar on this host.")
    return school


@router.put(
    "/terms/{int:term_id}/length/",
    response={200: TermOut, 403: MessageOut, 422: MessageOut},
)
def set_term_length(request, term_id: int, payload: TermLengthIn):
    """Declare how many teaching days this term held.

    Authority **before** the lookup, for the reason
    `attendance.api._refuse_non_markers()` spells out: asking it second turns
    this route into an existence oracle for anybody signed in at the school, who
    could walk the id space and learn which terms are real by reading the status
    code.

    422 rather than 409 for a count the constraints refuse — more days than the
    term contains, or fewer than one. That is the request disagreeing with the
    calendar it names, not the school being in the wrong state.
    """
    school = _school_of(request)
    if not services.can_set_school_days(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_SET)

    term = get_object_or_404(Term, pk=term_id)
    try:
        term = services.set_school_days(term, payload.school_days, by=request.user)
    except Exception as exc:  # ValidationError from full_clean(), narrowed below
        from django.core.exceptions import ValidationError

        if not isinstance(exc, ValidationError):
            raise
        return 422, MessageOut(detail=_first_message(exc))

    return TermOut(
        term_id=term.pk,
        term=str(term),
        starts_on=term.starts_on.isoformat(),
        ends_on=term.ends_on.isoformat(),
        calendar_days=term.calendar_days,
        school_days=term.school_days,
    )


def _first_message(exc) -> str:
    """One sentence out of a `ValidationError`, whatever shape it arrived in.

    `full_clean()` raises with `message_dict` for field errors and
    `messages` for constraint ones, and a check constraint surfaces as the
    latter carrying the constraint's own name. Both are flattened here rather
    than at the call site, so the route has one answer shape.
    """
    messages = getattr(exc, "messages", None) or [str(exc)]
    return messages[0]


# ---------------------------------------------------------------------------
# Setting the school up: the calendar, and the groups children sit in.
#
# Both are tenant tables, so there is **no school slug in any path**: the
# connection has already been pointed at one schema by `TenantMainMiddleware`,
# and a slug would be a second opinion about which school this is, free to
# disagree with it. `gradebook/api.py` sets that rule out at length.
# ---------------------------------------------------------------------------

from datetime import date  # noqa: E402
from typing import List, Optional  # noqa: E402

from .models import ClassGroup, TermName  # noqa: E402

#: What a caller who may not shape the school is told. One sentence for every
#: refusal here, so "may you?" and "does that exist?" cannot be told apart by
#: their wording.
_MAY_NOT_SET_UP = (
    "The calendar and the class groups are set up by a principal or an "
    "administrator of the school."
)


class TermRowOut(Schema):
    term_id: int
    session: str
    name: str
    name_label: str
    starts_on: str
    ends_on: str
    school_days: Optional[int] = None
    is_current: bool


class ClassRowOut(Schema):
    class_group_id: int
    name: str
    level: int
    is_active: bool


class SetUpOut(Schema):
    """The school's shape: every term and every class group.

    **Nothing here costs a child a query.** A "45 enrolled" column per class
    would be a per-group read on the screen an administrator opens to add one
    more group, and the number it produced would be a second implementation of
    something the placement screens already answer.
    """

    terms: List[TermRowOut]
    classes: List[ClassRowOut]
    may_set_up: bool


class NewTermIn(Schema):
    session: str
    name: str
    starts_on: date
    ends_on: date
    next_term_starts_on: Optional[date] = None


class NewClassIn(Schema):
    name: str
    level: int = 0


def _term_row(term) -> TermRowOut:
    return TermRowOut(
        term_id=term.pk,
        session=term.session,
        name=term.name,
        name_label=TermName(term.name).label,
        starts_on=term.starts_on.isoformat(),
        ends_on=term.ends_on.isoformat(),
        school_days=term.school_days,
        is_current=term.is_current,
    )


def _class_row(group) -> ClassRowOut:
    return ClassRowOut(
        class_group_id=group.pk,
        name=group.name,
        level=group.level,
        is_active=group.is_active,
    )


def _refuse_outsiders(request, school):
    """Authority **before either read**, the oracle rule this app already keeps.

    Admitted on `SETUP_ROLES`, which is also who may write: there is nothing on
    this screen a person may look at and not change, so a wider viewing set
    would be a list of the school's shape shown to anybody signed in there.
    """
    if not services.can_set_up(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_SET_UP)
    return None


@router.get("/setup/", response={200: SetUpOut, 403: MessageOut})
def setup(request):
    """Every term and every class group, in the order each declares.

    Two queries, and neither touches a student.
    """
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused

    return SetUpOut(
        terms=[_term_row(t) for t in Term.objects.all()],
        classes=[_class_row(g) for g in ClassGroup.objects.all()],
        may_set_up=True,
    )


@router.post("/terms/", response={201: TermRowOut, 403: MessageOut, 422: MessageOut})
def create_term(request, payload: NewTermIn):
    """Open a term's record. **This does not make it current.**

    Two decisions, deliberately: a school opening next term's record while this
    one is still being taught is ordinary. `PUT /terms/{id}/current/` is the
    other one, said out loud.

    422 for a calendar that disagrees with itself — a term ending before it
    starts, a next term beginning before this one ends, a session and name
    already used. Those are `full_clean()` turning the model's constraints into
    sentences; the constraints still hold the rule.
    """
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused

    from django.core.exceptions import ValidationError

    try:
        term = services.create_term_as(
            request.user,
            payload.session,
            payload.name,
            payload.starts_on,
            payload.ends_on,
            school=school,
            next_term_starts_on=payload.next_term_starts_on,
        )
    except services.NotAllowedToSetUp:
        return 403, MessageOut(detail=_MAY_NOT_SET_UP)
    except ValidationError as exc:
        return 422, MessageOut(detail=_first_message(exc))

    return 201, _term_row(term)


@router.put(
    "/terms/{int:term_id}/current/",
    response={200: TermRowOut, 403: MessageOut, 422: MessageOut},
)
def set_current_term(request, term_id: int):
    """Say which term the school is teaching now.

    The previous one is cleared in the same transaction — `one_current_term` is
    a unique constraint on `is_current` where true, so setting a second without
    clearing the first is refused by the database. The service does both, so a
    school never has to know that and never gets half of it.
    """
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused

    term = get_object_or_404(Term, pk=term_id)
    try:
        term = services.set_current_term_as(request.user, term, school=school)
    except services.NotAllowedToSetUp:
        return 403, MessageOut(detail=_MAY_NOT_SET_UP)

    return 200, _term_row(term)


@router.post("/classes/", response={201: ClassRowOut, 403: MessageOut, 422: MessageOut})
def create_class_group(request, payload: NewClassIn):
    """Open a class group.

    `level` is the school's own ordering and is not derived from the name:
    "JSS 1A" sorts before "JSS 10A" as text, and no string rule survives a
    school running Nursery, Primary and Senior together.
    """
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused

    from django.core.exceptions import ValidationError

    try:
        group = services.create_class_group_as(
            request.user, payload.name, school=school, level=payload.level
        )
    except services.NotAllowedToSetUp:
        return 403, MessageOut(detail=_MAY_NOT_SET_UP)
    except ValidationError as exc:
        return 422, MessageOut(detail=_first_message(exc))

    return 201, _class_row(group)
