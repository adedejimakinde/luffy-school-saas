"""HTTP for the approval chain: see where every class stands, and take a step.

The chain has existed since the first results PR and has had **no HTTP surface
at all** — `submit`, `check`, `approve`, `release` and `send_back` were
reachable only from the ORM. This is the door, and `results/views.py`'s page is
what walks through it.

## The list is over class groups, not over sheets

A `ResultSheet` is created lazily: `open_sheet()` is `get_or_create`, so a
class nobody has looked at yet has no row. A list built from `ResultSheet`
would therefore show the classes somebody had already opened and silently omit
the ones nobody had — which is exactly backwards for a screen whose job is
"where does every class stand".

So the list is every active `ClassGroup` for the current term, with its sheet's
state where a sheet exists and `draft` where none does. Those two are the same
answer: `is_open_for_writing(None)` is true, and a term with no sheet is open
rather than closed.

## Nothing in the list costs a child

Three queries regardless of how many classes, and **not one of them touches a
student**: the groups, the sheets for this term, and the groups this login is
class teacher of. No roster, no marks, no counts.

That is deliberate. A list that counted "38 of 45 marked" per class would be a
per-child read per row on the one screen a principal refreshes while waiting,
and the number it produced would be a second implementation of something the
marking sheet already answers. Detail is loaded when a sheet is opened.

## Actions are computed here, and enforced in `services`

Each row carries the steps this login may take. That is a **convenience for
the screen, not the gate** — `services.submit()` and friends ask
`_require_authority()`, `_require_class_teacher_scope()` and
`_require_not_already_signed()` themselves, on the row read under the lock.
A page that hid a button would be a restriction anybody could bypass with a
POST, which is why the buttons are drawn from the same sets the service reads
rather than from a list written twice.

`may_submit` consults the class-teacher scope because `SUBMITTING_ROLES`
admits TEACHER and `_require_class_teacher_scope()` narrows it to their own
group — the hole issue #25 closed. An ADMIN is unaffected by that scope and so
is not asked about it.
"""

from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import ClassGroup, ClassTeacher, Term
from accounts.models import Role
from accounts.session import session_auth

from . import services
from .models import ResultSheet, SheetState

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class SignatoryOut(Schema):
    """Who took a step, and when. The audit as a sentence rather than a row."""

    from_state: str
    to_state: str
    actor_id: int
    at: str


class AlreadySignedOut(Schema):
    """The same-signatory refusal, carrying the step they already took.

    **A 409 with a body, in the shape `gradebook.api.ConflictOut` established.**
    `AlreadySignedThisCycle` carries the prior transition for exactly this
    reason and nothing exposed it: "you may not check this" is not a sentence
    somebody can act on, and "you submitted this sheet — ask somebody else to
    check it" is.

    `existing` is nullable because the unique index can refuse a concurrent
    pair where this guard saw nothing yet. The page then prints `detail` alone,
    which is still true.
    """

    detail: str
    existing: Optional[SignatoryOut] = None


class SheetRowOut(Schema):
    """One class group's standing, and what this login may do about it.

    `sheet_id` is null for a class nobody has opened. The page does not need it
    to act — the transition routes are keyed on the class group, and open the
    sheet themselves — but a null is the honest way to say "no row yet" rather
    than inventing one for a list.
    """

    class_group_id: int
    class_group: str
    sheet_id: Optional[int] = None
    state: str
    state_label: str
    may_submit: bool = False
    may_check: bool = False
    may_approve: bool = False
    may_release: bool = False
    may_send_back: bool = False


class ChainOut(Schema):
    term_id: Optional[int]
    term: Optional[str]
    rows: List[SheetRowOut]


class SendBackIn(Schema):
    """`reason` is required and must not be blank.

    Enforced in three places and that is not redundancy: the field is required
    here so a client learns before sending, `services.send_back()` refuses a
    blank one because it is callable without HTTP, and a check constraint
    refuses the row because neither of the first two is the database. A refusal
    that does not say what is wrong sends a teacher back to forty-five scores
    with no idea which to look at.
    """

    reason: str


def _school_of(request):
    """The school whose schema this request is already on.

    A 404 on the portal, matching every other tenant app: these tables do not
    exist there rather than existing and being empty.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No results on this host.")
    return school


#: One sentence for every refusal of authority on this router, so that "may you
#: act?" and "does that class exist?" cannot be told apart by their wording —
#: the gate `gradebook.api._MAY_NOT_MARK` sets, for the same oracle reason.
_MAY_NOT_ACT = (
    "Results are moved along by the class teacher, the vice principal "
    "(academic) and the principal of the school the class belongs to."
)


def _refuse_outsiders(request, school, roles):
    """The authority check, **before either lookup**.

    Takes `roles` rather than asking for them, because `roles_at()` is a query
    and every caller here needs the set anyway. Asking twice made the list cost
    three reads of one person's memberships — the middleware's, this one's and
    the view's — on the screen a principal refreshes while waiting.

    `OPENING_ROLES` is the union of everyone who can take any step, which is
    the same set `open_sheet()` admits — looking at where a class stands
    decides nothing. Asked first, because `get_object_or_404()` answers 404 for
    a row that is not there and lets the request reach a 403 for one that is:
    ask authority second and every route here becomes an existence oracle for
    class groups and terms, readable by any parent signed in at the school.
    """
    if not roles & services.OPENING_ROLES:
        return 403, MessageOut(detail=_MAY_NOT_ACT)
    return None


def _my_class_groups(request, school, term):
    """The group ids this login is class teacher of, this term. One query.

    `membership_id_at()` is access-scoped exactly as `roles_at()` is, so a
    suspended teacher has no membership here to be a class teacher with — the
    authority and the identity have to agree, and they only do if both ask the
    same question.
    """
    membership_id = request.user.membership_id_at(school, Role.TEACHER)
    if membership_id is None:
        return set()
    return set(
        ClassTeacher.objects.filter(
            term=term, teacher_membership_id=membership_id
        ).values_list("class_group_id", flat=True)
    )


def _actions(state, roles, group_id, mine):
    """Which steps this login may take on a sheet in this state.

    A mirror of what `services` enforces, and **only** a mirror: every one of
    these is asked again by the service on the locked row. Drawn from the same
    role sets so the two cannot drift by a role.
    """
    may_submit = (
        state == SheetState.DRAFT
        and bool(roles & services.SUBMITTING_ROLES)
        # A TEACHER is narrowed to their own group — issue #25's scope. An
        # ADMIN is not a teacher of anything, so the scope does not apply.
        and (Role.ADMIN.value in roles or group_id in mine)
    )
    return {
        "may_submit": may_submit,
        "may_check": state == SheetState.SUBMITTED and bool(roles & services.CHECKING_ROLES),
        "may_approve": state == SheetState.CHECKED and bool(roles & services.APPROVING_ROLES),
        "may_release": state == SheetState.APPROVED and bool(roles & services.RELEASING_ROLES),
        "may_send_back": state in {SheetState.SUBMITTED, SheetState.CHECKED, SheetState.APPROVED}
        and bool(roles & services.SENDING_BACK_ROLES),
    }


@router.get("/chain/", response={200: ChainOut, 403: MessageOut})
def chain(request):
    """Where every class stands this term, and what this login may do.

    Three queries, none of which touches a student — see the module docstring
    for why a "38 of 45 marked" column is deliberately absent.

    **Every class is listed, including the ones this login cannot act on.** A
    teacher seeing "JSS 3B — awaiting check" is reading her own school's
    progress, not somebody's results; the sheet carries no mark, no name and no
    number. Hiding those rows would make an empty list ambiguous — nothing to
    do, or nothing you may see — and a colleague asking "where is 3B?" would
    get "I cannot see it" from a system that simply declined to say.
    """
    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    refused = _refuse_outsiders(request, school, roles)
    if refused is not None:
        return refused

    term = Term.objects.filter(is_current=True).first()
    if term is None:
        return ChainOut(term_id=None, term=None, rows=[])

    mine = _my_class_groups(request, school, term)
    sheets = {
        s.class_group_id: s for s in ResultSheet.objects.filter(term=term)
    }

    rows = []
    for group in ClassGroup.objects.filter(is_active=True):
        sheet = sheets.get(group.pk)
        # No row is the same answer as a draft row: `open_sheet()` is
        # `get_or_create`, so a class nobody has looked at is simply unopened.
        state = sheet.state if sheet else SheetState.DRAFT
        rows.append(
            SheetRowOut(
                class_group_id=group.pk,
                class_group=group.name,
                sheet_id=sheet.pk if sheet else None,
                state=state,
                state_label=SheetState(state).label,
                **_actions(state, roles, group.pk, mine),
            )
        )
    return ChainOut(term_id=term.pk, term=str(term), rows=rows)


def _signatory(transition):
    if transition is None:
        return None
    return SignatoryOut(
        from_state=transition.from_state,
        to_state=transition.to_state,
        actor_id=transition.actor_id,
        at=transition.created_at.isoformat(),
    )


def _step(request, class_group_id, move, *, reason=None):
    """Open the sheet for this class and take one step on it.

    The sheet is opened rather than looked up, because a class nobody has
    opened is a class whose teacher may still submit it — and `open_sheet()` is
    `get_or_create`, so the second person to look is not an error.

    Every refusal the chain can raise is mapped to the status that says what
    kind of refusal it is: **403** for authority, **409** for the
    same-signatory rule (with the step they already took), **409** for a state
    that moved under them, and **422** for a send-back with nothing in it.
    """
    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    refused = _refuse_outsiders(request, school, roles)
    if refused is not None:
        return refused

    group = get_object_or_404(ClassGroup, pk=class_group_id)
    term = Term.objects.filter(is_current=True).first()
    if term is None:
        return 409, MessageOut(
            detail="No term is open, so there are no results to move along."
        )

    try:
        sheet = services.open_sheet(group, term, request.user)
        moved = move(sheet, request.user) if reason is None else move(
            sheet, request.user, reason
        )
    except services.AlreadySignedThisCycle as exc:
        return 409, AlreadySignedOut(
            detail=str(exc), existing=_signatory(getattr(exc, "existing", None))
        )
    except services.NotAllowedToActOnResults:
        # Deliberately not the exception's own text, which names the actor and
        # the school; that belongs in a log, not in a response body.
        return 403, MessageOut(detail=_MAY_NOT_ACT)
    except (services.WrongState, services.ReleaseIsFinal) as exc:
        return 409, MessageOut(detail=str(exc))
    except services.ResultsError as exc:
        # `send_back` with a blank reason lands here. 422: the request is well
        # formed and the caller is allowed, and what is missing is a sentence
        # they can type.
        return 422, MessageOut(detail=str(exc))

    # `_move()` returns the **transition**, not the sheet — the audit row is
    # what the chain's functions are about. `to_state` is where the sheet now
    # is, and reading it off the transition saves a re-read of the row the
    # service has only just written under its own lock.
    state = moved.to_state
    return 200, SheetRowOut(
        class_group_id=group.pk,
        class_group=group.name,
        sheet_id=moved.sheet_id,
        state=state,
        state_label=SheetState(state).label,
        **_actions(state, roles, group.pk, _my_class_groups(request, school, term)),
    )


_STEP_RESPONSES = {
    200: SheetRowOut,
    403: MessageOut,
    409: AlreadySignedOut,
    422: MessageOut,
}


@router.post("/chain/{int:class_group_id}/submit/", response=_STEP_RESPONSES)
def submit(request, class_group_id: int):
    """Teacher: these results are ready to be checked."""
    return _step(request, class_group_id, services.submit)


@router.post("/chain/{int:class_group_id}/check/", response=_STEP_RESPONSES)
def check(request, class_group_id: int):
    """Vice principal (academic): the academic check."""
    return _step(request, class_group_id, services.check)


@router.post("/chain/{int:class_group_id}/approve/", response=_STEP_RESPONSES)
def approve(request, class_group_id: int):
    """Principal: approved."""
    return _step(request, class_group_id, services.approve)


@router.post("/chain/{int:class_group_id}/release/", response=_STEP_RESPONSES)
def release(request, class_group_id: int):
    """Principal: publish to parents. The last thing that happens to this version.

    **In the request**, not on the queue. The freeze is one transaction over
    one class group, and the expensive half — rendering a PDF per child — is
    already asynchronous: `renders.mark_and_enqueue()` writes a PENDING marker
    and asks for the renders after the commit. Queuing the freeze as well would
    add a progress surface and a "did it work" state the chain does not have,
    to move work that is already bounded.
    """
    return _step(request, class_group_id, services.release)


@router.post("/chain/{int:class_group_id}/send-back/", response=_STEP_RESPONSES)
def send_back(request, class_group_id: int, payload: SendBackIn):
    """Refuse at whatever stage you sit, and say what is wrong."""
    return _step(request, class_group_id, services.send_back, reason=payload.reason)
