"""Phone numbers set aside for fiction, which no real provider is handed.

The North American numbering plan keeps 555-0100 to 555-0199, in every area
code, for films, books and examples: they are never given to a subscriber.
Classnode's demo school (`schools.crestfield`) gives its made-up families those
numbers, because they pass `accounts.identifiers.normalize_phone()` and so can
be stored and shown like any other, and no Nigerian range is published as
reserved in the same way. (The UK's drama range, 07700 900xxx, would be the
other choice, and the phone-number library refuses it as not a number.)

`messaging.termii.TermiiProvider.send()` refuses one as `Refused`, the
address's fault, whatever school asked. The demo's own switch
(`schools.quiet`) stops its messages before they get here; this is the second
lock, for a path that one day forgets to ask.

Email needs no list here: the demo's addresses are at `example.com`, which
RFC 2606 reserves and whose null MX record (RFC 7505) refuses all mail.
"""

import re

_FICTIONAL_NANP = re.compile(r"^\+1\d{3}55501\d{2}$")


def is_fictional_phone(address: str) -> bool:
    """Whether `address`, in E.164, is a 555-01xx number."""
    return bool(_FICTIONAL_NANP.match((address or "").strip()))


__all__ = ["is_fictional_phone"]
