"""The seam: how a message leaves this platform. `docs/messaging.md` D1.

A provider is anything with `send(outbound)` and, optionally,
`check_configured()`. Not an ABC, for `schools.delivery.Channel`'s reason: a
test double should be able to be a plain object with a `send`.

**One provider per contact channel type, not per technology.**
`settings.MESSAGING_PROVIDERS` maps `email` and `phone` to a dotted path each.
Whether a phone message goes by SMS, by WhatsApp, or by one with the other as a
fallback is the phone provider's business, so choosing between them
(parent-access OPEN-5) is one class written later, and nothing that sends a
message changes.

**The provider is handed the kind and its parameters as well as our text.** SMS
and email send the text `kinds.render()` made. A WhatsApp provider sends a
pre-approved template by name with parameters, which no text of ours can be, so
it maps `outbound.kind` to its template and ignores `outbound.text`.

**Two failures, not one**, for `schools.delivery`'s reason. `Refused` is about
the address: the number is not a subscriber, the mailbox does not exist. A
school can do something about that by checking the number with the family.
`Unavailable` is about the provider, and is nobody's business but the
operator's. Both are recorded, and they are shown to different people.
"""

from dataclasses import dataclass, field

from django.conf import settings
from django.utils.module_loading import import_string


class NotConfigured(Exception):
    """This deploy has no provider for this channel type, so nothing can be sent."""


class Refused(Exception):
    """The provider will not deliver to this address. Permanent."""


class Unavailable(Exception):
    """The provider could not be reached, or failed. Transient, and not the address's fault."""


@dataclass(frozen=True)
class Outbound:
    """One message, as a provider is handed it."""

    channel_type: str
    address: str
    kind: str
    #: The kind's parameters, for a provider that sends templates by name. A
    #: code kind carries the code here too, which is why an `Outbound` is never
    #: written anywhere by this platform's own code.
    params: dict = field(default_factory=dict)
    text: str = ""
    #: Our reference for the message, which a delivery report comes back with.
    reference: str = ""


@dataclass(frozen=True)
class Accepted:
    """The provider took the message. Not that it arrived: that is a report, later."""

    provider_ref: str = ""


class Provider:
    """The contract, spelled out. Nothing has to inherit from it."""

    def check_configured(self):
        """Raise `NotConfigured` if this provider cannot send anything in this deploy."""
        return None

    def send(self, outbound: Outbound) -> Accepted:  # pragma: no cover
        raise NotImplementedError


class NoProvider:
    """What a channel type with no provider configured gets: a refusal, never a silence."""

    def __init__(self, channel_type):
        self.channel_type = channel_type

    def check_configured(self):
        raise NotConfigured(
            f"No {self.channel_type} provider is configured for this deploy, so "
            f"nothing can be sent to a {self.channel_type} channel."
        )

    def send(self, outbound):
        self.check_configured()


def provider_for(channel_type):
    """The provider for `channel_type` (`email` or `phone`), read from settings per call.

    Per call rather than cached, so `override_settings` is honoured, which is how
    the test suite switches the fake on (D2).
    """
    path = (getattr(settings, "MESSAGING_PROVIDERS", None) or {}).get(channel_type)
    if not path:
        return NoProvider(channel_type)
    return import_string(path)()
