"""The result checker: a family with no account reads the card with a PIN. D11.

`docs/messaging.md` D11. The child's admission number (`Membership.reference`)
and a twelve-digit PIN from a paper slip open that child's card for one term, on
the school's own host, with no session, no cookie and no account. Every check is
asked again from scratch.

Two halves, and this module is both:

- **Printing slips** (`print_slips()`): the principal or an administrator asks,
  after release, for a PDF of the class with one slip per child. The PINs are
  minted then, kept only as digests, and printed once.
- **Opening a card** (`open_card()`): the admission number and the PIN, checked
  behind the throttle, answer with the card `cards.card_for()` names, which the
  route then puts through the same gate every family reader meets.

## One refusal for every failure

An unknown admission number, a wrong PIN, a PIN that has been replaced, a PIN
whose session is over, and another child's PIN all end in `NotOpened`, with the
same sentence. A caller who could tell them apart could learn which admission
numbers exist at a school, and which children have a slip. Every one of them is
counted.

## Counted, never locked

Wrong answers are counted per admission number and per address, each at this
school, in `accounts.throttling`'s buckets (`SignInScope.CHECKER_*`). After too
many in the window the next attempt waits, and the wait ends by itself. An
admission number is written on a child's exercise books, so a lock that somebody
had to lift would let anybody who has seen one keep a family out; a wait does
not. While the wait lasts, **the PIN is not read at all**, the right one
included: a throttle that let a right answer through would let a guesser keep
guessing, since only the wrong answers would be refused.

The number is counted **as typed**, whether or not any child has it, so a wait
says only that this caller has been getting things wrong, and nothing about
whether the number is real. `accounts.guardian_signin` counts a channel the same
way, for the same reason.

## Why paper, and never a message

Nothing here sends anything, and nothing here imports anything that does. The
checker is for families with no verified channel, and sending a PIN to a number
nobody has proved would send a child's results to whoever holds it (D9).
"""

import hmac
import re
import secrets
from dataclasses import dataclass, field
from typing import List, Optional

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from academics.models import Term, TermName
from accounts import throttling
from accounts.models import Membership, Role, SignInScope
from schools.models import hash_token

from . import cards
from .models import CheckerPin, ReleasedCard, ResultSheet
from .services import school_on_this_connection

#: Who may print slips, which mints PINs: D11's "the principal or an admin".
PRINTING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})

#: Twelve digits, not six. A sign-in code lives fifteen minutes and dies after
#: five wrong guesses; a PIN lives all session and is used more than once, so it
#: cannot be capped per PIN without locking out the family holding it. The space
#: does that work instead: 10^12 against 10^6.
PIN_DIGITS = 12

#: The one refusal. Deliberately says nothing about which half was wrong.
NOT_OPENED = (
    "That admission number and PIN do not open a report card here. Check both "
    "against the slip and try again."
)

#: The wait, and it says that nothing has been locked, as sign-in's does.
WAIT = (
    "Too many wrong tries. Wait a few minutes and try again. Nothing has been "
    "locked."
)

_PIN_SEPARATORS = re.compile(r"[\s-]+")


class CheckerError(Exception):
    """A refusal from this module, carrying the sentence to show."""


class NotAllowed(CheckerError):
    """Only the principal or an administrator prints slips."""


class NotReleased(CheckerError):
    """Slips are printed for a released class only: there is no card to open yet."""


class NoSuchChild(CheckerError):
    """A lost slip was asked for with an admission number nobody in this class has."""


class NotOpened(CheckerError):
    """The one refusal. See the module docstring."""

    def __init__(self):
        super().__init__(NOT_OPENED)


class TooManyAttempts(CheckerError):
    """The wait. `retry_after` is whole seconds."""

    def __init__(self, retry_after: int):
        super().__init__(WAIT)
        self.retry_after = retry_after


# -- the PIN -----------------------------------------------------------------


def new_pin() -> str:
    """Twelve random digits, leading zeros kept. `secrets`, never `random`."""
    return f"{secrets.randbelow(10 ** PIN_DIGITS):0{PIN_DIGITS}d}"


def printed(pin: str) -> str:
    """`123456789012` as the slip prints it: `1234 5678 9012`."""
    return " ".join(pin[i : i + 4] for i in range(0, len(pin), 4))


def _typed_pin(typed) -> Optional[str]:
    """The twelve digits a family typed, however they spaced them, or None.

    Spaces and hyphens are dropped because the slip prints the PIN in groups
    and people copy what they see.
    """
    digits = _PIN_SEPARATORS.sub("", typed or "")
    if len(digits) != PIN_DIGITS or not digits.isdigit():
        return None
    return digits


def _typed_number(typed) -> str:
    """The admission number as typed, trimmed, with runs of spaces made one."""
    return " ".join((typed or "").split())


# -- printing slips ----------------------------------------------------------


@dataclass
class Slip:
    """One child's slip. `pin` is the raw PIN, printed once and kept nowhere."""

    student_name: str
    admission_number: str
    class_group_name: str
    term_label: str
    session: str
    pin: str

    @property
    def printed_pin(self) -> str:
        return printed(self.pin)


@dataclass
class Slips:
    """What one press printed, and the children it could not print a slip for."""

    school_name: str
    slips: List[Slip] = field(default_factory=list)
    #: Children on the class with no admission number: a slip they could not
    #: use would be worse than none, so they are named instead.
    without_a_number: List[str] = field(default_factory=list)


def _require_printing_authority(actor, school):
    if not set(actor.roles_at(school)) & PRINTING_ROLES:
        raise NotAllowed(
            "Result-checker slips are printed by the principal or an administrator."
        )


@transaction.atomic
def print_slips(sheet, *, actor, admission_number: Optional[str] = None) -> Slips:
    """Mint a PIN for each child on a released class who has none. D11.

    With `admission_number`, mint one for that child only, **whether or not
    they have one already**: that is the lost slip, and the new PIN stops the
    old one opening anything (`CheckerPin`, "The newest row is the live one").

    Without it, a child who already has a PIN for this term is skipped. A second
    press would otherwise replace every slip the first one printed, including
    the ones already in families' hands, and none of them would say so. The
    second press prints only the children the first could not: somebody given
    an admission number since, or a card released since.

    The sheet is locked, so two presses at once cannot both mint for one child
    and leave one of the two printed slips dead.
    """
    school = school_on_this_connection()
    _require_printing_authority(actor, school)
    sheet = ResultSheet.objects.select_for_update().select_related("term").get(pk=sheet.pk)
    if not sheet.is_released:
        raise NotReleased(
            "These results have not been released, so there is no card for a slip to open."
        )

    released = list(
        ReleasedCard.objects.filter(sheet=sheet, version=1).order_by(
            "student_name", "student_membership_id"
        )
    )
    references = dict(
        Membership.objects.filter(
            school=school, pk__in=[card.student_membership_id for card in released]
        ).values_list("pk", "reference")
    )
    term = sheet.term
    answer = Slips(school_name=released[0].school_name if released else school.name)

    if admission_number is not None:
        wanted = _typed_number(admission_number).casefold()
        chosen = [
            card for card in released
            if wanted and _typed_number(references.get(card.student_membership_id)).casefold() == wanted
        ]
        if len(chosen) != 1:
            raise NoSuchChild(
                "No child in this class has that admission number, so no slip was printed."
                if not chosen else
                "More than one child in this class has that admission number. "
                "Correct it on the roll, then print the slip."
            )
    else:
        has_one = set(
            CheckerPin.objects.filter(
                term=term, student_membership_id__in=[card.student_membership_id for card in released]
            ).values_list("student_membership_id", flat=True)
        )
        chosen = [card for card in released if card.student_membership_id not in has_one]

    for card in chosen:
        number = _typed_number(references.get(card.student_membership_id))
        if not number:
            answer.without_a_number.append(card.student_name)
            continue
        pin = new_pin()
        CheckerPin.objects.create(
            student_membership_id=card.student_membership_id,
            term=term,
            pin_hash=hash_token(pin),
            minted_by_id=actor.pk,
        )
        answer.slips.append(
            Slip(
                student_name=card.student_name,
                admission_number=number,
                class_group_name=card.class_group_name,
                term_label=TermName(card.term_name).label,
                session=card.session,
                pin=pin,
            )
        )
    return answer


def slips_printed(sheets) -> dict:
    """`sheet id -> children on it with a slip`, for the chain page. One query.

    Over the released cards and the PINs, never over a roster, so it costs the
    same however the class has moved since it was released.
    """
    sheets = list(sheets)
    if not sheets:
        return {}
    counts = dict(
        ReleasedCard.objects.filter(sheet__in=sheets, version=1)
        .filter(
            student_membership_id__in=CheckerPin.objects.filter(
                term_id__in={sheet.term_id for sheet in sheets}
            ).values("student_membership_id")
        )
        .values("sheet_id")
        .annotate(n=Count("student_membership_id", distinct=True))
        .values_list("sheet_id", "n")
    )
    return {sheet.pk: counts.get(sheet.pk, 0) for sheet in sheets}


# -- opening a card ----------------------------------------------------------


def _keys(school, number: str, address: str):
    """The two throttle keys, each carrying the school. See `SignInScope`."""
    return f"{school.pk}:{number.casefold()}", f"{school.pk}:{address}"


def _wait(number_key: str, address_key: str) -> Optional[int]:
    """The longer of the two waits, or None: `signin.wait_before_retrying()`'s rule."""
    waits = [
        wait
        for wait in (
            throttling.blocked_for(SignInScope.CHECKER_NUMBER, number_key),
            throttling.blocked_for(SignInScope.CHECKER_ADDRESS, address_key),
        )
        if wait is not None
    ]
    return max(waits) if waits else None


def open_card(school, *, admission_number, pin, address, today=None) -> ReleasedCard:
    """The card this admission number and PIN open, or `NotOpened`, or a wait.

    Asks nothing about withholding: that is the route's, through
    `card_api._require_servable()`, in the gate's order. A PIN is the claim, so
    it is checked first, and only somebody who has proved it learns that the
    card is being held.
    """
    number = _typed_number(admission_number)
    number_key, address_key = _keys(school, number, address)
    wait = _wait(number_key, address_key)
    if wait is not None:
        raise TooManyAttempts(wait)

    card = _card_opened_by(school, number, pin, today or timezone.localdate())
    if card is None:
        throttling.record_failure(SignInScope.CHECKER_NUMBER, number_key)
        throttling.record_failure(SignInScope.CHECKER_ADDRESS, address_key)
        raise NotOpened()

    # One right answer forgives the number's mistakes and not the address's,
    # for the reason `throttling.clear()` gives.
    throttling.clear(SignInScope.CHECKER_NUMBER, number_key)
    return card


def _card_opened_by(school, number: str, pin, today) -> Optional[ReleasedCard]:
    """Every failure is `None`, so the caller cannot answer them differently."""
    digits = _typed_pin(pin)
    if not number or digits is None:
        return None

    # `school=` cannot be seen from outside today: a control removing it left
    # every test green (#175). The PINs live in this school's schema and name
    # memberships by their platform-wide id, so another school's child has no
    # PIN here to match. It stays so that if either of those ever changes, an
    # admission number still means only this school's children.
    children = {
        child.pk: child
        for child in Membership.objects.filter(
            school=school, role=Role.STUDENT, reference__iexact=number
        )
    }
    if not children:
        return None

    # The newest PIN per child and term is the live one. Postgres's DISTINCT ON
    # keeps the first row of each pair in this order.
    newest = (
        CheckerPin.objects.filter(student_membership_id__in=list(children))
        .select_related("term")
        .order_by("student_membership_id", "term_id", "-id")
        .distinct("student_membership_id", "term_id")
    )
    digest = hash_token(digits)
    opened = [row for row in newest if hmac.compare_digest(row.pin_hash, digest)]
    if len(opened) != 1:
        return None
    row = opened[0]
    if session_is_over(row.term, today):
        return None
    return cards.card_for(children[row.student_membership_id], row.term)


def session_is_over(term, today) -> bool:
    """Has a later session begun? D11: a PIN "lasts until the end of the session".

    **Read as "until the next session starts".** A `Term` names its session as a
    string and nothing records when a session ends, and the nearest thing to it,
    the third term's last day, is days after a third-term card is released: a
    third-term slip would die in the week it went home. So a PIN stops opening
    anything on the first day of any term in a later session, which is the day a
    school has moved on. OPEN-M5 still asks whether a session is the right
    lifetime at all.
    """
    return Term.objects.filter(session__gt=term.session, starts_on__lte=today).exists()


__all__ = [
    "CheckerError",
    "NOT_OPENED",
    "NoSuchChild",
    "NotAllowed",
    "NotOpened",
    "NotReleased",
    "PIN_DIGITS",
    "PRINTING_ROLES",
    "Slip",
    "Slips",
    "TooManyAttempts",
    "WAIT",
    "new_pin",
    "open_card",
    "print_slips",
    "printed",
    "session_is_over",
    "slips_printed",
]
