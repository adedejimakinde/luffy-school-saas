"""The only provider built. It records, and sends nothing. `docs/messaging.md` D2.

Tests assert on `FakeMessage`. In development `/dev/outbox/` shows what it was
given, codes included, which is how a developer signs in as a guardian without
a phone. `messaging.E001` is why that is safe: a deploy with `DEBUG` off cannot
be pointed at this class.

**It fails on purpose, for a few reserved addresses**, so every failure path can
be tested without a network:

| address | answer |
| --- | --- |
| a phone ending `0000`, or an email whose local part is `refused` | `Refused` |
| a phone ending `0001`, or an email whose local part is `unavailable` | `Unavailable` |

Everything else is `Accepted`, with a reference of its own.
"""

import uuid

from .models import FakeMessage, Outcome
from .providers import Accepted, Refused, Unavailable


def _answer_for(channel_type, address):
    if channel_type == "phone":
        if address.endswith("0000"):
            return Outcome.REFUSED
        if address.endswith("0001"):
            return Outcome.UNAVAILABLE
    else:
        local = address.partition("@")[0]
        if local == "refused":
            return Outcome.REFUSED
        if local == "unavailable":
            return Outcome.UNAVAILABLE
    return Outcome.ACCEPTED


class FakeProvider:
    """Writes what it is handed to `FakeMessage`, then answers as the table above says."""

    def check_configured(self):
        return None

    def send(self, outbound):
        from .kinds import subject

        answer = _answer_for(outbound.channel_type, outbound.address)
        FakeMessage.objects.create(
            channel_type=outbound.channel_type,
            address=outbound.address,
            kind=outbound.kind,
            subject=subject(outbound.kind) if outbound.channel_type == "email" else "",
            text=outbound.text,
            reference=outbound.reference,
            outcome=answer,
        )
        if answer == Outcome.REFUSED:
            raise Refused(f"The fake provider refuses {outbound.address}.")
        if answer == Outcome.UNAVAILABLE:
            raise Unavailable("The fake provider is pretending to be down.")
        return Accepted(provider_ref=f"fake-{uuid.uuid4().hex[:12]}")
