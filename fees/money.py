"""Naira as a person types it, turned into kobo — or refused.

The ledger is whole kobo (`fees/models.py`), so the one place a naira amount
exists is the edge: what a bursar types into a form. This is that edge, and it
**refuses rather than guesses**:

- `15,000.50` is 1,500,050 kobo. Commas are allowed only where thousands
  separators go, because `1,50` is somebody's ₦1.50 typed with a comma and
  reading it as ₦150 would record a payment a hundred times too large.
- `12.345` is refused, not rounded. A third decimal place is a typo — of
  `12,345`, most likely — and rounding it to ₦12.35 would record a number
  nobody meant, on a receipt a parent keeps.
- Zero, a negative, and anything that is not a number are refused. The sign
  is the ledger's to apply, never the caller's.

Parsed through `Decimal`, never `float`: binary floating point cannot hold
0.1, and a float at this step would bring back the error the kobo column exists
to avoid.
"""

import re
from decimal import Decimal

from .models import KOBO_PER_NAIRA


class NotAnAmount(ValueError):
    """What was typed is not an amount of naira the books can take. The
    message is a sentence for the person who typed it."""


#: Digits, with commas only as thousands separators, and any number of decimal
#: places — so that a third one is *recognised* and refused with its own
#: sentence rather than falling through to "not a number".
_AMOUNT = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?$")

#: Fifteen digits of naira is more money than any school fee, and a bound that
#: keeps a pasted account number from becoming a payment.
_MAX_KOBO = 10**15


def kobo_from_naira(typed) -> int:
    text = str(typed or "").strip().replace(" ", "")
    if text.startswith("₦"):
        text = text[1:]
    if text.startswith("-"):
        raise NotAnAmount("Enter the amount as a positive number; the books apply the sign.")
    match = _AMOUNT.match(text)
    if not match:
        raise NotAnAmount("Enter an amount in naira, like 15,000 or 15000.50.")
    decimals = match.group(1) or ""
    if len(decimals) > 2:
        raise NotAnAmount(
            "Naira have two decimal places (kobo) at most. Check the amount — "
            "a third decimal place is usually a comma typed as a point."
        )
    naira = Decimal(text.replace(",", ""))
    kobo = int(naira * KOBO_PER_NAIRA)
    if kobo <= 0:
        raise NotAnAmount("The amount must be more than nothing.")
    if kobo >= _MAX_KOBO:
        raise NotAnAmount("That amount is too large to be a school fee. Check it.")
    return kobo


__all__ = ["NotAnAmount", "kobo_from_naira"]
