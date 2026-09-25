"""The closed list of things this platform says to a family, and the words. D3.

**No free text.** A text box would make the platform a bulk sender for whatever
a school typed, with no template a WhatsApp provider could have approved and
nobody having read what it gives away on a shared handset (`docs/messaging.md`
M2). So every message is one of these kinds, and its wording is here, in code.

**Each kind was read for what it gives away on a lock screen.** The code kinds
carry the code and the school's name, and no child's name: a school can type a
number wrong, and the stranger who holds it learns nothing about anybody's
child. None of them says anything a person holding the phone could not safely
read.

**Counted in segments.** An SMS is 160 characters of the GSM 03.38 alphabet, or
153 a segment once it is split. One character outside that alphabet makes the
whole message UCS-2, at 70 characters (67 split), and a message costs by the
segment. `₦` is outside it, and so are many diacritics in the names a school
holds. `segments()` is what a budget counts (D7).
"""

import math

from django.conf import settings
from django.db import models


class Kind(models.TextChoices):
    """What a message is. The value is what a provider maps to a template."""

    CHANNEL_CHECK = "channel_check", "Channel check"
    SIGN_IN_CODE = "sign_in_code", "Sign-in code"
    REACTIVATION = "reactivation", "Reactivation"
    SCHOOL_ANSWER = "school_answer", "School answer"
    RESULT_NOTICE = "result_notice", "Result notice"
    #: A result notice for a card the school is withholding. Its own kind, so a
    #: WhatsApp provider can hold a template for each.
    RESULT_HELD = "result_held", "Result notice, card held"


#: The kinds that carry a one-time code. Their text is never stored anywhere
#: (D6), and `codes.py` is the only thing that sends them.
CODE_KINDS = frozenset(
    {Kind.CHANNEL_CHECK, Kind.SIGN_IN_CODE, Kind.REACTIVATION, Kind.SCHOOL_ANSWER}
)

#: The choices a code delivery's `kind` may take: the code kinds and nothing
#: else, so that a new kind of notice is not a migration on the code table.
CODE_KIND_CHOICES = [(kind.value, kind.label) for kind in Kind if kind in CODE_KINDS]

_NEVER_ASKED = "Nobody from the school will ask you for it."

_TEXT = {
    Kind.CHANNEL_CHECK: (
        "{school} has added this {what} to a parent record on Classnode. "
        "Your code is {code}. It lasts {minutes} minutes.{where} " + _NEVER_ASKED
    ),
    Kind.SIGN_IN_CODE: (
        "Your Classnode sign-in code is {code}. It lasts {minutes} minutes. "
        + _NEVER_ASKED
    ),
    Kind.REACTIVATION: (
        "{school} has asked Classnode to open this {what} again for a parent "
        "record. Your code is {code}. It lasts {minutes} minutes.{where} "
        + _NEVER_ASKED
    ),
    Kind.SCHOOL_ANSWER: (
        "{school} has added you as a parent on Classnode. To accept, your code is "
        "{code}. It lasts {minutes} minutes.{where} " + _NEVER_ASKED
    ),
}

# **No results in a result notice** (D9, requirement 7): the school, the child as
# the card names them, the term, and where to read it. Nothing from the card.
_TEXT[Kind.RESULT_NOTICE] = (
    "{school}: {child}'s {term} report card is ready. Sign in {where_to_read} to read it."
)
# A held card says the school is holding it and who to call, and not why: the
# gate says a card is held, and a lock screen is more public than a signed-in
# page (docs/withholding.md, "What the 403 carries").
_TEXT[Kind.RESULT_HELD] = (
    "{school} is holding {child}'s {term} report card. Please contact the school: {contact}"
)

_SUBJECT = {
    Kind.CHANNEL_CHECK: "Your Classnode code",
    Kind.SIGN_IN_CODE: "Your Classnode sign-in code",
    Kind.REACTIVATION: "Your Classnode code",
    Kind.SCHOOL_ANSWER: "Your Classnode code",
    Kind.RESULT_NOTICE: "A report card is ready",
    Kind.RESULT_HELD: "About a report card",
}


def _where():
    """Where a code a school sent is typed. The portal, when a deploy names one."""
    host = getattr(settings, "PORTAL_HOST", None)
    return f" Enter it at {host}." if host else ""


def _where_to_read():
    host = getattr(settings, "PORTAL_HOST", None)
    return f"at {host}" if host else "on Classnode"


def render(kind, *, channel_type, **params) -> str:
    """The text of one message of `kind`. Raises `KeyError` for a parameter it lacks."""
    what = "number" if channel_type == "phone" else "address"
    return _TEXT[Kind(kind)].format(
        what=what, where=_where(), where_to_read=_where_to_read(), **params
    )


def subject(kind) -> str:
    """An email's subject line. A phone message has none."""
    return _SUBJECT[Kind(kind)]


# -- what a message costs ----------------------------------------------------

#: GSM 03.38's basic alphabet: one septet each.
_GSM_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
#: Its extension table: two septets each, an escape and the character.
_GSM_EXTENDED = frozenset("^{}\\[~]|€\f")


def segments(text: str) -> tuple[str, int]:
    """`(encoding, segments)` for `text` as one SMS.

    `"gsm7"` when every character is in the GSM alphabet, counting an extension
    character as two; otherwise `"ucs2"`, counting UTF-16 code units, so a
    character outside the Basic Multilingual Plane counts as the two it is on
    the wire.
    """
    if all(ch in _GSM_BASIC or ch in _GSM_EXTENDED for ch in text):
        length = sum(2 if ch in _GSM_EXTENDED else 1 for ch in text)
        single, split = 160, 153
        encoding = "gsm7"
    else:
        length = len(text.encode("utf-16-le")) // 2
        single, split = 70, 67
        encoding = "ucs2"
    if length <= single:
        return encoding, 1
    return encoding, math.ceil(length / split)
