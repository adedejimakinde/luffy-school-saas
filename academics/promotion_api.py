"""HTTP for end-of-session promotion: one read that writes nothing, and one confirm.

`academics.promotion` holds every rule. This module is the door: who may open
it (a principal or an administrator, asked **before** any table is read, for the
oracle reason `academics.api._refuse_outsiders()` gives), and what each refusal
says. A 409 is the school's state disagreeing with the request (not the end of
the session, a class changed since the page was drawn, a child the principal
has not decided about, a choice that is not what the principal decided); a 422
is a plan that is not well formed.

**And one route that decides** (audit finding G-04): `POST decisions/` records
what the principal decided for one child or many, with one reason. The
principal alone (`results.sessions.DECIDING_ROLES`); an administrator who may
open the page and press Confirm is refused here.
"""

from typing import Dict, List, Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth

from accounts.models import LIVE_STATUSES, Membership, Role, User

from . import promotion, services

router = Router(auth=session_auth)

_NOT_YOURS = (
    "Promoting children at the end of the session is done by a principal or an "
    "administrator of the school."
)


class MessageOut(Schema):
    detail: str


_NOT_THE_PRINCIPAL = (
    "Whether a child moves up, repeats, graduates or leaves is the principal's "
    "decision."
)


class DecisionOut(Schema):
    status: str
    label: str
    reason: str
    by: str
    at: str


class ChildOut(Schema):
    membership_id: int
    name: str
    reference: str
    #: What the plan will say for this child: the choice the principal's
    #: decision allows ("promote", "repeat" or "leave"). Null while undecided:
    #: nothing is assumed, and nothing can be confirmed until it is decided.
    action: Optional[str] = None
    #: The year's average on the released third-term card. Null when the year
    #: has not been frozen for this child (no released third-term card).
    average: Optional[str] = None
    #: What Classnode suggests from that average and the pass mark:
    #: "promoted", "repeated", or "" when there is nothing to go on.
    suggested: str = ""
    decision: Optional[DecisionOut] = None


class TargetOut(Schema):
    class_group_id: int
    name: str


class ClassOut(Schema):
    class_group_id: int
    name: str
    #: The class it moves up into by default; null when graduating is the
    #: default or when the office has to choose.
    destination_id: Optional[int] = None
    graduate: bool
    children: List[ChildOut]


class ReviewOut(Schema):
    term: Optional[str] = None
    to_term: Optional[str] = None
    #: Null when a promotion can be made; otherwise why not, for the person.
    problem: Optional[str] = None
    targets: List[TargetOut]
    classes: List[ClassOut]
    #: Whether this caller is the principal, who records the decisions.
    may_decide: bool = False
    #: The pass mark suggestions are made against.
    pass_mark: Optional[str] = None
    #: How many children have no decision yet. Confirm is refused above nought.
    undecided: int = 0
    #: The outcomes a decision may record, in the order the page offers them.
    outcomes: List[Dict[str, str]] = []


class ClassPlanIn(Schema):
    class_group_id: int
    #: Exactly one of these two: a class to move up into, or graduation.
    destination_id: Optional[int] = None
    graduate: bool = False
    #: Every child of the class, by membership id: "promote", "repeat" or "leave".
    children: Dict[str, str]


class PlanIn(Schema):
    classes: List[ClassPlanIn]


class OutcomeOut(Schema):
    promoted: int
    repeated: int
    graduated: int
    left: int


class DecisionsIn(Schema):
    #: Why, in the principal's words. Required, and kept on every row.
    reason: str = ""
    #: `{membership id: outcome}`: "promoted", "on_trial", "repeated",
    #: "graduated" or "withdrawn" (leaving).
    children: Dict[str, str]


class DecidedOut(Schema):
    decided: int


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No school on this host.")
    return school


@router.get("/", response={200: ReviewOut, 403: MessageOut})
def review(request):
    """Every class and every child, with the default choices. Writes nothing."""
    school = _school_of(request)
    if not services.can_place_students(request.user, school):
        return 403, MessageOut(detail=_NOT_YOURS)

    from results import sessions
    from results.models import PromotionStatus

    seen = promotion.review()
    deciders = _names(
        child.decision.decided_by_id
        for row in seen.classes
        for child in row.children
        if child.decision is not None
    )
    return ReviewOut(
        term=str(seen.term) if seen.term else None,
        to_term=str(seen.to_term) if seen.to_term else None,
        problem=seen.problem,
        may_decide=sessions.can_decide_promotions(request.user, school),
        pass_mark=_text(seen.pass_mark),
        undecided=seen.undecided,
        outcomes=[
            {"value": status.value, "label": _OUTCOME_LABEL.get(status.value, status.label)}
            for status in PromotionStatus
        ],
        targets=[TargetOut(class_group_id=g.pk, name=g.name) for g in seen.targets],
        classes=[
            ClassOut(
                class_group_id=row.class_group.pk,
                name=row.class_group.name,
                destination_id=row.suggested_class.pk if row.suggested_class else None,
                graduate=row.suggested_graduate,
                children=[
                    ChildOut(
                        membership_id=c.membership_id,
                        name=c.name,
                        reference=c.reference,
                        action=c.action,
                        average=_text(c.average),
                        suggested=c.suggested,
                        decision=_decision(c.decision, deciders),
                    )
                    for c in row.children
                ],
            )
            for row in seen.classes
        ],
    )


#: The page's words for each outcome. "Withdrawn" is the stored value's label
#: and what a card prints; on this page the choice reads as what is happening.
_OUTCOME_LABEL = {
    "promoted": "Promote",
    "on_trial": "Promote on trial",
    "repeated": "Repeat",
    "graduated": "Graduated",
    "withdrawn": "Leaving",
}


def _text(value) -> Optional[str]:
    return None if value is None else f"{value}"


def _names(user_ids) -> dict:
    """`{user id: name}` for the people who recorded these decisions."""
    ids = {pk for pk in user_ids if pk}
    return {
        user.pk: user.full_name or user.username
        for user in User.objects.filter(pk__in=ids)
    }


def _decision(decision, deciders) -> Optional[DecisionOut]:
    if decision is None:
        return None
    return DecisionOut(
        status=decision.status,
        label=decision.get_status_display(),
        reason=decision.note,
        by=deciders.get(decision.decided_by_id, ""),
        at=decision.decided_at.isoformat(),
    )


@router.post(
    "/decisions/",
    response={200: DecidedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def decide(request, payload: DecisionsIn):
    """Record the principal's decision for each child named, with one reason.

    Every one is recorded or none is. The children have to be on this term's
    class lists now, as the page showed them: a child who is not is a 409 and
    the page is drawn again. Deciding again writes a second row; both stand,
    and the later one holds (`results.PromotionDecision`).
    """
    school = _school_of(request)
    from results import sessions

    # Authority before any table is read, so a refusal says nothing about
    # which children exist. `decide_many_as()` asks it again where it writes.
    if not sessions.can_decide_promotions(request.user, school):
        return 403, MessageOut(detail=_NOT_THE_PRINCIPAL)

    seen = promotion.review()
    if seen.problem:
        return 409, MessageOut(detail=seen.problem)
    try:
        wanted = {int(key): status for key, status in payload.children.items()}
    except ValueError:
        return 422, MessageOut(detail="Each child is named by their number on the roll.")
    on_the_lists = {c.membership_id for row in seen.classes for c in row.children}
    if not set(wanted) <= on_the_lists:
        return 409, MessageOut(
            detail="The classes changed since this page was drawn. Look at it again; nothing was decided."
        )
    members = {
        m.pk: m
        for m in Membership.objects.filter(
            pk__in=list(wanted), school=school, role=Role.STUDENT, status__in=LIVE_STATUSES
        ).select_related("user", "school")
    }
    if set(members) != set(wanted):
        return 409, MessageOut(
            detail="The classes changed since this page was drawn. Look at it again; nothing was decided."
        )
    try:
        rows = sessions.decide_many_as(
            request.user,
            seen.term.session,
            {members[pk]: status for pk, status in wanted.items()},
            reason=payload.reason,
        )
    except sessions.NotAllowedToDecidePromotion:
        return 403, MessageOut(detail=_NOT_THE_PRINCIPAL)
    except sessions.SessionsError as exc:
        return 422, MessageOut(detail=str(exc))
    return DecidedOut(decided=len(rows))


@router.post(
    "/",
    response={200: OutcomeOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def confirm(request, payload: PlanIn):
    """Promote every class as the plan says, or change nothing at all."""
    school = _school_of(request)
    plan = [
        {
            "class_group_id": c.class_group_id,
            "destination_id": c.destination_id,
            "graduate": c.graduate,
            "children": c.children,
        }
        for c in payload.classes
    ]
    try:
        outcome = promotion.promote_as(request.user, school, plan)
    except services.NotAllowedToPlace:
        return 403, MessageOut(detail=_NOT_YOURS)
    except (promotion.NotEndOfSession, promotion.NoFirstTermNext,
            promotion.ReviewOutOfDate, promotion.AlreadyPlacedNext,
            promotion.NotDecided, promotion.AgainstTheDecision,
            services.ResultsInTheChain) as exc:
        return 409, MessageOut(detail=str(exc))
    except promotion.PromotionError as exc:
        return 422, MessageOut(detail=str(exc))
    return OutcomeOut(promoted=outcome.promoted, repeated=outcome.repeated, graduated=outcome.graduated, left=outcome.left)
