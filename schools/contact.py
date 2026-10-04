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


#: The twenty local government areas of Ogun State, as the setup page offers
#: them. An offer, not a rule: a school elsewhere types its own.
OGUN_LGAS = (
    "Abeokuta North",
    "Abeokuta South",
    "Ado-Odo/Ota",
    "Ewekoro",
    "Ifo",
    "Ijebu East",
    "Ijebu North",
    "Ijebu North East",
    "Ijebu Ode",
    "Ikenne",
    "Imeko Afon",
    "Ipokia",
    "Obafemi Owode",
    "Odeda",
    "Odogbolu",
    "Ogun Waterside",
    "Remo North",
    "Sagamu",
    "Yewa North",
    "Yewa South",
)

LGA_MAX = 60


def set_lga_as(actor, school, lga: str) -> str:
    """Set the local government area the school sits in. Blank clears it.

    Printed on the Ogun State report card beside the school's name. Free text,
    trimmed, because a school outside Ogun has its own list.
    """
    if not can_set_up(actor, school):
        raise NotAllowedToSetUp(
            f"{actor} may not set up {school}'s local government area. That is done by "
            f"a principal or an administrator of the school."
        )
    lga = " ".join((lga or "").split())
    if len(lga) > LGA_MAX:
        raise PublicDetailsRefused(f"Keep the local government area under {LGA_MAX} characters.")
    school.lga = lga
    school.save(update_fields=["lga"])
    return school.lga


SCHOOL_CODE_MAX = 20


def set_school_code_as(actor, school, code: str) -> str:
    """The school's code with the state, printed "[B13003]". Blank clears it."""
    if not can_set_up(actor, school):
        raise NotAllowedToSetUp(
            f"{actor} may not set up {school}'s code. That is done by a principal or an administrator of the school."
        )
    code = "".join((code or "").split())
    if len(code) > SCHOOL_CODE_MAX:
        raise PublicDetailsRefused(f"Keep the school code under {SCHOOL_CODE_MAX} characters.")
    if code and not all(ch.isalnum() or ch in "-/" for ch in code):
        raise PublicDetailsRefused("A school code is letters and digits, like B13003.")
    school.school_code = code
    school.save(update_fields=["school_code"])
    return school.school_code


__all__ = [
    "LGA_MAX",
    "SCHOOL_CODE_MAX",
    "set_school_code_as",
    "NotAnEmailAddress",
    "OGUN_LGAS",
    "PublicDetailsRefused",
    "set_lga_as",
    "set_contact_email_as",
    "set_public_details_as",
]
