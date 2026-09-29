"""The school's bank connection: `GET`/`POST /api/fees/bank/` and its two helpers.

Read by whoever reads the books (`fees.authority.may_read`); **written only by
the bursar and an administrator** (`may_write`), the flat 404 to everybody who
may not read and a sentence (403) to a reader who may not write, as `fees.api`.
A reader who may not write sees the account number as its last four digits.

Paystack being down or unset is a 503 with one sentence and **nothing of its
reply**: what Paystack said, and any key, belong in the log and not on a page.
"""

import logging
from datetime import datetime
from typing import List, Optional

from ninja import Router, Schema

from accounts.session import session_auth

from . import bank, paystack
from .api import MessageOut, _refuse_non_writer, _require_reader, _school_of
from .authority import may_write

router = Router(auth=session_auth)
logger = logging.getLogger(__name__)

_DOWN = "Paystack is not available right now. Please try again in a little while."


class ConnectedOut(Schema):
    bank_name: str
    account_number: str
    account_name: str
    connected_by: str
    connected_at: datetime


class BankStateOut(Schema):
    connected: Optional[ConnectedOut]
    may_write: bool


class BankOut(Schema):
    name: str
    code: str


class BanksOut(Schema):
    banks: List[BankOut]


class AccountIn(Schema):
    bank_code: str
    account_number: str


class ConnectIn(AccountIn):
    #: The name the person was shown and confirmed. Compared with a fresh resolve.
    account_name: str


class ResolvedOut(Schema):
    account_name: str


def _shown(row, writer):
    if row is None:
        return None
    number = row.account_number if writer else "******" + row.account_number[-4:]
    return ConnectedOut(
        bank_name=row.bank_name,
        account_number=number,
        account_name=row.account_name,
        connected_by=row.connected_by_name,
        connected_at=row.connected_at,
    )


def _down(exc):
    logger.warning("Paystack call failed: %s", type(exc).__name__)
    return 503, MessageOut(detail=_DOWN)


@router.get("/", response=BankStateOut)
def state(request):
    school = _school_of(request)
    _require_reader(request.user, school)
    writer = may_write(request.user, school)
    return BankStateOut(connected=_shown(bank.current(), writer), may_write=writer)


@router.get("/banks/", response={200: BanksOut, 403: MessageOut, 503: MessageOut})
def banks(request):
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    try:
        return BanksOut(banks=[BankOut(**b) for b in paystack.list_banks()])
    except (paystack.PaystackUnavailable, paystack.PaystackNotConfigured, paystack.PaystackRefused) as exc:
        return _down(exc)


@router.post("/resolve/", response={200: ResolvedOut, 403: MessageOut, 422: MessageOut, 503: MessageOut})
def resolve(request, payload: AccountIn):
    """The name the bank holds for the account. Writes nothing."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    try:
        name = bank.resolve(bank_code=payload.bank_code, account_number=payload.account_number)
    except bank.BankError as exc:
        return 422, MessageOut(detail=str(exc))
    except (paystack.PaystackUnavailable, paystack.PaystackNotConfigured, paystack.PaystackRefused) as exc:
        return _down(exc)
    return ResolvedOut(account_name=name)


@router.post(
    "/",
    response={201: BankStateOut, 403: MessageOut, 409: MessageOut, 422: MessageOut, 503: MessageOut},
)
def connect(request, payload: ConnectIn):
    """Connect the school's bank account, once its name has been confirmed."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    try:
        row = bank.connect(
            school,
            request.user,
            bank_code=payload.bank_code,
            account_number=payload.account_number,
            confirmed_name=payload.account_name,
        )
    except (bank.NameChanged, bank.AlreadyConnected) as exc:
        return 409, MessageOut(detail=str(exc))
    except bank.BankError as exc:
        return 422, MessageOut(detail=str(exc))
    except (paystack.PaystackUnavailable, paystack.PaystackNotConfigured, paystack.PaystackRefused) as exc:
        return _down(exc)
    return 201, BankStateOut(connected=_shown(row, True), may_write=True)
