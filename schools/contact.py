"""A school's own contact email — where a reply to its outgoing mail lands.

`docs/messaging.md` D17. One field on `School` (shared, not tenant-scoped —
`Outbound.reply_to` is filled in before the schema is chosen for some call
sites, e.g. an invitation, so the address has to be reachable from a plain
`School` row without entering its schema). Set from the same setup page and
by the same authority as the report card's colour (`results.look`): whoever
may set up the school's terms and classes, `academics.services.can_set_up()`.
"""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from academics.services import NotAllowedToSetUp, can_set_up


class NotAnEmailAddress(Exception):
    """What was typed does not look like an email address. The message is for the person."""


def set_contact_email_as(actor, school, address: str) -> str:
    """Set `school`'s own contact email. Blank clears it — a school may not
    have settled on one yet, and that is a valid state, not an error."""
    if not can_set_up(actor, school):
        raise NotAllowedToSetUp(
            f"{actor} may not set up {school}'s contact email. That is done by "
            f"a principal or an administrator of the school."
        )
    address = (address or "").strip()
    if address:
        try:
            validate_email(address)
        except ValidationError:
            raise NotAnEmailAddress(f"'{address}' does not look like an email address.")
    school.contact_email = address
    school.save(update_fields=["contact_email"])
    return school.contact_email


#: Room for a short paragraph; the public page is a card, not an essay.
ABOUT_MAX = 600
ADDRESS_MAX = 300
PHONE_MAX = 30
_PHONE_OK = frozenset("0123456789 +-()./")


class PublicDetailsRefused(Exception):
    """The about text, address or phone number cannot be used. The message is for the person."""


def set_public_details_as(actor, school, *, about, address, phone):
    """Set what `school`'s public page says. Blank clears a field.

    Text only, saved as typed and escaped where it is drawn; nothing here is
    markup. The same authority as the contact email: whoever may set the school up.
    """
    if not can_set_up(actor, school):
        raise NotAllowedToSetUp(
            f"{actor} may not set up {school}'s public page. That is done by "
            f"a principal or an administrator of the school."
        )
    about = "\n".join(line.rstrip() for line in (about or "").strip().splitlines())
    address = " ".join((address or "").split())
    phone = (phone or "").strip()
    if len(about) > ABOUT_MAX:
        raise PublicDetailsRefused(
            f"The about text is {len(about)} characters; keep it under {ABOUT_MAX}."
        )
    if len(address) > ADDRESS_MAX:
        raise PublicDetailsRefused(f"Keep the address under {ADDRESS_MAX} characters.")
    if len(phone) > PHONE_MAX or not set(phone) <= _PHONE_OK:
        raise PublicDetailsRefused("A phone number is digits, spaces and + - ( ) only.")
    school.about, school.address, school.phone = about, address, phone
    school.save(update_fields=["about", "address", "phone"])
    return school


__all__ = [
    "NotAnEmailAddress",
    "PublicDetailsRefused",
    "set_contact_email_as",
    "set_public_details_as",
]
