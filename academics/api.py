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
