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

from . import paystack, virtual
from .api import MessageOut, PayIntoOut, _refuse_non_writer, _require_reader, _school_of, _student_here
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


class UnmatchedOut(Schema):
    reference: str
    amount_kobo: int
    account_number: str
    reason: str
    reason_label: str
    received_at: datetime


class UnmatchedListOut(Schema):
    payments: List[UnmatchedOut]


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
                reference=p.reference,
                amount_kobo=p.amount_kobo,
                account_number=p.account_number,
                reason=p.reason,
                reason_label=p.get_reason_display(),
                received_at=p.received_at,
            )
            for p in UnmatchedPayment.objects.all()
        ]
    )
