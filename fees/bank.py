"""Connecting a school's bank account: the rules, apart from the HTTP.

Four facts, in the order the code checks them:

1. **The bank is one Paystack lists**, and the account number is ten digits.
2. **The name is Paystack's, confirmed by a person.** The person is shown what
   Paystack's resolve endpoint returned and confirms it; the server resolves
   *again* and compares before it writes, so a name that was typed, or that the
   bank has since changed, never becomes the record (`NameChanged`).
3. **One at a time per school**, by a lock on the school's row, held across the
   Paystack calls: two people pressing Connect together make one subaccount, not
   two.
4. **The platform holds nothing.** The subaccount takes no share for the
   platform, and the split gives it 100% and makes it bear Paystack's fees
   (`fees.paystack`). Changing bank re-points the same subaccount and adds a
   `SchoolBank` row; the old row stays.

If Paystack made the subaccount and the split then fails, the subaccount is an
orphan at Paystack (nothing points at it and no money can reach it) and the next
attempt makes another. Cheaper than a half-written row that says "connected".
"""

import re

from django.db import transaction

from schools.models import School

from . import paystack
from .models import SchoolBank


class BankError(Exception):
    """This connection was refused, with a sentence for the person. Nothing was written."""


class NameChanged(BankError):
    """What the person confirmed is not what the bank says now."""

    def __init__(self, resolved):
        super().__init__(
            "The bank now gives a different name for that account. Check the number "
            "and the bank, and confirm the name shown."
        )
        self.resolved = resolved


class AlreadyConnected(BankError):
    pass


_ACCOUNT_NUMBER = re.compile(r"^[0-9]{10}$")


def _same(a, b):
    return " ".join(str(a).split()).casefold() == " ".join(str(b).split()).casefold()


def current():
    """The school's current connection, or None. The latest row."""
    return SchoolBank.objects.order_by("-id").first()


def clean(bank_code, account_number):
    """`(bank, number)`: the Paystack-listed bank and the ten digits, or `BankError`."""
    number = "".join(str(account_number or "").split())
    if not _ACCOUNT_NUMBER.match(number):
        raise BankError("An account number is ten digits.")
    bank = next((b for b in paystack.list_banks() if b["code"] == str(bank_code)), None)
    if bank is None:
        raise BankError("Choose the bank from the list.")
    return bank, number


def resolve(*, bank_code, account_number):
    """The name the bank holds for the account, for the person to confirm."""
    bank, number = clean(bank_code, account_number)
    try:
        return paystack.resolve_account(account_number=number, bank_code=bank["code"])
    except paystack.PaystackRefused:
        raise BankError("The bank has no account with that number. Check the number and the bank.")


def connect(school, actor, *, bank_code, account_number, confirmed_name):
    """Connect (or change) the school's bank. Returns the new `SchoolBank`."""
    bank, number = clean(bank_code, account_number)
    with transaction.atomic():
        # The public-schema row, locked: the one thing every request for this
        # school shares. `.order_by()` because the model orders by default.
        School.objects.select_for_update().filter(pk=school.pk).order_by().first()
        try:
            resolved = paystack.resolve_account(account_number=number, bank_code=bank["code"])
        except paystack.PaystackRefused:
            raise BankError("The bank has no account with that number. Check the number and the bank.")
        if not _same(resolved, confirmed_name):
            raise NameChanged(resolved)

        latest = current()
        if latest and (latest.bank_code, latest.account_number) == (bank["code"], number):
            raise AlreadyConnected("That account is already connected.")
        try:
            if latest:
                code = paystack.update_subaccount(
                    latest.subaccount_code, bank_code=bank["code"], account_number=number
                )
                split = latest.split_code
            else:
                code = paystack.create_subaccount(
                    business_name=school.name, bank_code=bank["code"], account_number=number
                )
                split = paystack.create_split(name=school.name, subaccount_code=code)
        except paystack.PaystackRefused as exc:
            raise BankError(f"Paystack would not connect that account: {exc}")

        return SchoolBank.objects.create(
            bank_code=bank["code"],
            bank_name=bank["name"],
            account_number=number,
            account_name=resolved,
            subaccount_code=code,
            split_code=split,
            connected_by_id=actor.pk,
            connected_by_name=actor.get_full_name() or str(actor),
        )
