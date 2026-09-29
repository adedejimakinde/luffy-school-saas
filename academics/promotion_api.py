"""HTTP for end-of-session promotion: one read that writes nothing, and one confirm.

`academics.promotion` holds every rule. This module is the door: who may open
it (a principal or an administrator, asked **before** any table is read, for the
oracle reason `academics.api._refuse_outsiders()` gives), and what each refusal
says. A 409 is the school's state disagreeing with the request (not the end of
the session, a class changed since the page was drawn); a 422 is a plan that is
not well formed.
"""

from typing import Dict, List, Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth

from . import promotion, services

router = Router(auth=session_auth)

_NOT_YOURS = (
    "Promoting children at the end of the session is done by a principal or an "
    "administrator of the school."
)


class MessageOut(Schema):
    detail: str


class ChildOut(Schema):
    membership_id: int
    name: str
    reference: str
    #: Always `promote` here: the default the page starts from.
    action: str = promotion.PROMOTE


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

    seen = promotion.review()
    return ReviewOut(
        term=str(seen.term) if seen.term else None,
        to_term=str(seen.to_term) if seen.to_term else None,
        problem=seen.problem,
        targets=[TargetOut(class_group_id=g.pk, name=g.name) for g in seen.targets],
        classes=[
            ClassOut(
                class_group_id=row.class_group.pk,
                name=row.class_group.name,
                destination_id=row.suggested_class.pk if row.suggested_class else None,
                graduate=row.suggested_graduate,
                children=[
                    ChildOut(membership_id=c.membership_id, name=c.name, reference=c.reference)
                    for c in row.children
                ],
            )
            for row in seen.classes
        ],
    )


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
            promotion.ReviewOutOfDate, promotion.AlreadyPlacedNext) as exc:
        return 409, MessageOut(detail=str(exc))
    except promotion.PromotionError as exc:
        return 422, MessageOut(detail=str(exc))
    return OutcomeOut(promoted=outcome.promoted, repeated=outcome.repeated, graduated=outcome.graduated, left=outcome.left)
