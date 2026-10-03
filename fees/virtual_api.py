"""The accounts families pay into: making one, seeing one, and what could not be placed.

- `POST students/{id}/`: make (or return) a child's account. Bursar and
  administrator, as every write in `fees.api`; the principal is told they may
  not, everybody else gets the flat 404.
- `GET mine/`: **the caller's own children** and where to pay for each, for a
  parent's page. Never a roll: it is `results.card_api._children_of()`, the same
  family scope the card index uses, and it names nobody the caller does not
  stand for. It carries no balance and no ledger.
- `GET unmatched/`: payments Paystack confirmed that the books could not place,
  for the bursar. Read by whoever reads the books.

Paystack being down or unset is a 503 with one sentence and none of Paystack's
words, as `fees.bank_api`.
"""

import logging
from datetime import datetime
from typing import List, Optional

from ninja import Router, Schema

from accounts.session import session_auth

from django.http import Http404

from . import paystack, placing, virtual
from .api import (
    MessageOut,
    PayIntoOut,
    _balance_of,
    _refuse_non_writer,
    _require_reader,
    _school_of,
    _student_here,
)
from .authority import may_write
from .models import UnmatchedPayment

router = Router(auth=session_auth)
logger = logging.getLogger(__name__)

_DOWN = "Paystack is not available right now. Please try again in a little while."


class MadeOut(Schema):
    pay_into: PayIntoOut
    created: bool


class MyChildOut(Schema):
    student_membership_id: int
    student_name: str
    pay_into: Optional[PayIntoOut]


class MineOut(Schema):
    children: List[MyChildOut]


class PlacedOut(Schema):
    """Where an unmatched payment went, and who put it there."""

    student_membership_id: int
    student: str
    placed_by: str
    placed_at: datetime
    entry_id: int


class UnmatchedOut(Schema):
    payment_id: int
    reference: str
    amount_kobo: int
    account_number: str
    reason: str
    reason_label: str
    received_at: datetime
    #: None while it is still waiting for a person.
    placed: Optional[PlacedOut] = None


class UnmatchedListOut(Schema):
    payments: List[UnmatchedOut]
    #: Whether this login may place them (the bursar and administrator).
    may_place: bool = False


class PlaceIn(Schema):
    """What the person confirmed: the child, and the amount and reference as they read them."""

    student_membership_id: int
    amount_kobo: int
    reference: str


class PlacementOut(Schema):
    placed: PlacedOut
    created: bool
    balance_kobo: int


@router.post(
    "/students/{int:membership_id}/",
    response={200: MadeOut, 201: MadeOut, 403: MessageOut, 409: MessageOut, 422: MessageOut, 503: MessageOut},
)
def make(request, membership_id: int):
    """Make the child's account, or return the one they have (200)."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    child = _student_here(school, membership_id)
    try:
        account, created = virtual.ensure(school, request.user, child)
    except virtual.NoBank as exc:
        return 409, MessageOut(detail=str(exc))
    except virtual.VirtualAccountError as exc:
        return 422, MessageOut(detail=str(exc))
    except (paystack.PaystackUnavailable, paystack.PaystackNotConfigured) as exc:
        logger.warning("Paystack call failed: %s", type(exc).__name__)
        return 503, MessageOut(detail=_DOWN)
    line = virtual.pay_into(child.pk)
    return (201 if created else 200), MadeOut(pay_into=PayIntoOut(**line), created=created)


@router.get("/mine/", response=MineOut)
def mine(request):
    """Where to pay, for each of the caller's own children at this school."""
    from results.card_api import _children_of

    school = _school_of(request)
    children = _children_of(request.user, school)
    accounts = {
        a.student_membership_id: a
        for a in virtual.VirtualAccount.objects.filter(student_membership_id__in=[c.pk for c in children])
    }
    return MineOut(
        children=[
            MyChildOut(
                student_membership_id=c.pk,
                student_name=c.name,
                pay_into=(
                    PayIntoOut(
                        bank_name=accounts[c.pk].bank_name,
                        account_number=accounts[c.pk].account_number,
                        account_name=accounts[c.pk].account_name,
                    )
                    if c.pk in accounts
                    else None
                ),
            )
            for c in children
        ]
    )


@router.get("/unmatched/", response=UnmatchedListOut)
def unmatched(request):
    """Payments confirmed by Paystack that could not be placed, newest first."""
    school = _school_of(request)
    _require_reader(request.user, school)
    return UnmatchedListOut(
        payments=[
            UnmatchedOut(
                payment_id=p.pk,
                reference=p.reference,
                amount_kobo=p.amount_kobo,
                account_number=p.account_number,
                reason=p.reason,
                reason_label=p.get_reason_display(),
                received_at=p.received_at,
                placed=_placed_out(getattr(p, "placement", None)),
            )
            for p in UnmatchedPayment.objects.select_related("placement")
        ],
        may_place=may_write(request.user, school),
    )


def _placed_out(placement):
    if placement is None:
        return None
    return PlacedOut(
        student_membership_id=placement.student_membership_id,
        student=placement.student_name,
        placed_by=placement.placed_by_name,
        placed_at=placement.placed_at,
        entry_id=placement.entry_id,
    )


@router.post(
    "/unmatched/{int:payment_id}/placement/",
    response={200: PlacementOut, 201: PlacementOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def place(request, payment_id: int, payload: PlaceIn):
    """Put an unmatched payment on a child: the bursar's decision.

    201 when this places it; **200 when it had already been placed on this same
    child**, so a retried request is the placement that is there. The person
    confirms the amount and the reference, and the server posts *its own* amount.
    """
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    child = _student_here(school, payload.student_membership_id)
    try:
        placement, created = placing.place(
            request.user,
            payment_id=payment_id,
            child=child,
            amount_kobo=payload.amount_kobo,
            reference=payload.reference,
        )
    except placing.NotFound:
        raise Http404("No such payment.")
    except (placing.AlreadyPlaced, placing.NotWhatYouConfirmed, placing.AlreadyInTheLedger) as exc:
        return 409, MessageOut(detail=str(exc))
    except placing.NoCurrentTerm as exc:
        return 422, MessageOut(detail=str(exc))
    return (201 if created else 200), PlacementOut(
        placed=_placed_out(placement), created=created, balance_kobo=_balance_of(child.pk)
    )
