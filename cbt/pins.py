"""Students' exam PINs and the slips that carry them. `docs/cbt.md`, "Exam PINs and slips".

A student will sign in to sit a test (step 4, `/sit/`) with the test code the teacher
reads out, their admission number and the eight-digit PIN from their exam slip. This
module mints the PINs, prints them, cancels them, and answers whether an admission
number and a PIN belong together (`check()`). Nothing in step 2 calls `check()` from a
route: the door, and the throttle in front of it, are step 4's.

## Printing

The principal, the administrator or an exam officer prints a class's slips as a PDF
(`print_class_as()`), or one student's for a lost slip (`print_student_as()`). Either
way, **every live PIN this term for the students printed for is cancelled in the same
transaction**, so a student has at most one live PIN per term, and the old slip stops
working the moment the new one exists. A class print reaches every student now placed
in the class this term, wherever their old slip was printed. One `PinSlipPrint` row
says who printed, when, how many slips and how many PINs it cancelled.

The PINs exist in the clear only in the request that mints them, on the PDF, which is
rendered in that request and stored nowhere (`api.py` sends it with `no-store`). The
mint and the render are one transaction, so a render that fails mints and cancels
nothing.

## Keyed digests

A PIN is kept as `digest()`: HMAC-SHA256 under `settings.EXAM_PIN_KEY`, a server secret
that is not in the database, over the PIN bound to this school, this student and this
term. Eight digits are 10^8 guesses; unkeyed, a copy of the table would give them all
up in seconds. Keyed, the copy alone is useless, and the same digits for two students
or at two schools are unrelated digests.

## One answer for every failure

`check()` answers with the student or `None`: an unknown admission number, a wrong PIN,
a cancelled PIN, another student's PIN, another term's, another school's, a student who
has left: all `None`, so whatever wraps it (step 4's throttle and its one sentence)
cannot tell them apart and neither can the person typing. It writes nothing.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from typing import List, Optional

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts.models import Membership, Role

from . import access
from .models import ExamPin, PinSlipPrint

#: Eight digits, not the result checker's twelve: a PIN only works behind a test code
#: that is live for one sitting (`docs/cbt.md`, "Student sign-in").
PIN_DIGITS = 8

_PIN_SEPARATORS = re.compile(r"[\s-]+")


class PinError(Exception):
    """A refusal from this module, carrying the sentence to show."""


class NotAllowedToPrint(PinError):
    """Not the principal, the administrator or an exam officer here."""


class PrintRefused(PinError):
    """Well formed, and the school's own state says no. The message is the reason."""


# -- the PIN -------------------------------------------------------------------------


def new_pin() -> str:
    """Eight random digits, leading zeros kept. `secrets`, never `random`."""
    return f"{secrets.randbelow(10 ** PIN_DIGITS):0{PIN_DIGITS}d}"


def printed(pin: str) -> str:
    """`12345678` as the slip prints it: `1234 5678`."""
    return " ".join(pin[i : i + 4] for i in range(0, len(pin), 4))


def digest(school_id: int, student_membership_id: int, term_id: int, pin: str) -> str:
    """The keyed digest a PIN is kept as. See the module docstring."""
    message = f"classnode.exam-pin:{school_id}:{student_membership_id}:{term_id}:{pin}"
    return hmac.new(settings.EXAM_PIN_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()


def _typed_pin(typed) -> Optional[str]:
    """The eight digits as typed, however they were spaced, or None."""
    digits = _PIN_SEPARATORS.sub("", typed or "")
    if len(digits) != PIN_DIGITS or not digits.isdigit():
        return None
    return digits


def _typed_number(typed) -> str:
    """An admission number as typed, trimmed, with runs of spaces made one."""
    return " ".join((typed or "").split())


# -- who is on a class ---------------------------------------------------------------


def current_term():
    return Term.objects.filter(is_current=True).first()


def _name_of(membership) -> str:
    return membership.display_name or membership.user.full_name or membership.user.username


def roster(school, group, term) -> list:
    """The students placed in `group` this term who can act at this school, by name.

    A student whose membership has ended or is suspended is left out: a slip they could
    not use is no slip.
    """
    ids = ClassPlacement.objects.student_ids(group, term)
    students = (
        Membership.objects.with_access()
        .filter(school=school, role=Role.STUDENT, pk__in=ids)
        .select_related("user")
    )
    return sorted(students, key=lambda m: (_name_of(m).casefold(), m.pk))


def live_pin_holders(term, student_ids) -> set:
    """Which of these students hold a live PIN this term."""
    return set(
        ExamPin.objects.filter(
            term=term, student_membership_id__in=list(student_ids), cancelled_at__isnull=True
        ).values_list("student_membership_id", flat=True)
    )


# -- printing ------------------------------------------------------------------------


@dataclass
class Slip:
    """One student's slip. `pin` is the raw PIN, printed once and kept nowhere."""

    student_name: str
    admission_number: str
    pin: str

    @property
    def printed_pin(self) -> str:
        return printed(self.pin)


@dataclass
class Slips:
    """What one press printed, and the students it could not print a slip for."""

    school_name: str
    class_group_name: str
    term_label: str
    session: str
    print_row: Optional[PinSlipPrint] = None
    slips: List[Slip] = field(default_factory=list)
    #: Students on the class with no admission number: they cannot sign in with a slip,
    #: so they are named instead.
    without_a_number: List[str] = field(default_factory=list)


def _require_printing_authority(actor, school):
    if not access.can_print(actor, school):
        raise NotAllowedToPrint(
            "Exam slips are printed by the principal, the administrator or an exam officer."
        )


def _name_of_user(user) -> str:
    return user.full_name or user.get_username()


def _issue(actor, school, group, term, students, *, kind, one=None) -> Slips:
    """Cancel these students' live PINs this term, mint one each, and write the print.

    Called with the class row locked, so two presses for one class cannot interleave.
    The partial unique index `one_live_exam_pin_per_student_per_term` is the backstop.
    """
    ids = [s.pk for s in students]
    live = list(
        ExamPin.objects.select_for_update()
        .filter(term=term, student_membership_id__in=ids, cancelled_at__isnull=True)
        .values_list("pk", flat=True)
    )
    numbered = [(s, _typed_number(s.reference)) for s in students]
    answer = Slips(
        school_name=school.name,
        class_group_name=group.name,
        term_label=TermName(term.name).label,
        session=term.session,
        without_a_number=[_name_of(s) for s, number in numbered if not number],
    )
    printing = [(s, number) for s, number in numbered if number]
    row = PinSlipPrint.objects.create(
        term=term,
        class_group=group,
        class_group_name=group.name,
        kind=kind,
        student_membership_id=one.pk if one is not None else None,
        student_name=_name_of(one) if one is not None else "",
        count=len(printing),
        cancelled_count=len(live),
        without_a_number=len(answer.without_a_number),
        printed_by_id=actor.pk,
        printed_by_name=_name_of_user(actor),
    )
    if live:
        ExamPin.objects.filter(pk__in=live).update(cancelled_at=timezone.now(), cancelled_by_print=row)
    pins = []
    for student, number in printing:
        pin = new_pin()
        pins.append(
            ExamPin(
                student_membership_id=student.pk,
                term=term,
                class_group=group,
                digest=digest(school.pk, student.pk, term.pk, pin),
                issued_by_print=row,
                issued_by_id=actor.pk,
            )
        )
        answer.slips.append(Slip(student_name=_name_of(student), admission_number=number, pin=pin))
    ExamPin.objects.bulk_create(pins)
    answer.print_row = row
    return answer


def _locked_group(group_id):
    group = ClassGroup.objects.select_for_update().filter(pk=group_id).first()
    if group is None:
        raise PrintRefused("There is no such class here.")
    return group


def _term_or_refuse():
    term = current_term()
    if term is None:
        raise PrintRefused("No term is open. The current term is set on the Setup page.")
    return term


@transaction.atomic
def print_class_as(actor, school, group_id) -> Slips:
    """A new slip for every student now in the class this term; every old PIN of theirs stops."""
    _require_printing_authority(actor, school)
    term = _term_or_refuse()
    group = _locked_group(group_id)
    students = roster(school, group, term)
    if not students:
        raise PrintRefused(f"Nobody is placed in {group.name} this term, so there is no slip to print.")
    return _issue(actor, school, group, term, students, kind=PinSlipPrint.Kind.CLASS)


@transaction.atomic
def print_student_as(actor, school, group_id, student_membership_id) -> Slips:
    """A new slip for one student of this class, for a lost one. Only their old PIN stops."""
    _require_printing_authority(actor, school)
    term = _term_or_refuse()
    group = _locked_group(group_id)
    student = next((s for s in roster(school, group, term) if s.pk == student_membership_id), None)
    if student is None:
        raise PrintRefused(f"That student is not in {group.name} this term.")
    if not _typed_number(student.reference):
        raise PrintRefused(
            f"{_name_of(student)} has no admission number, so a slip would not let them sign in. "
            "Add one on the Roll, then print the slip."
        )
    return _issue(actor, school, group, term, [student], kind=PinSlipPrint.Kind.STUDENT, one=student)


# -- checking ------------------------------------------------------------------------


def check(school, term, admission_number, pin) -> Optional[Membership]:
    """The student this admission number and PIN belong to this term, or None.

    For step 4's `/sit/`, which wraps it in a throttle and one sentence. Every failure is
    `None`, it writes nothing, and it reads only the schema the connection is on, which
    must be `school`'s: a PIN printed at one school opens nothing at another.
    """
    number = _typed_number(admission_number)
    digits = _typed_pin(pin)
    if not number or digits is None or term is None or school is None:
        return None
    if connection.schema_name != school.schema_name:
        return None
    students = {
        m.pk: m
        for m in Membership.objects.with_access().filter(
            school=school, role=Role.STUDENT, reference__iexact=number
        )
    }
    if not students:
        return None
    rows = ExamPin.objects.filter(
        term=term, student_membership_id__in=list(students), cancelled_at__isnull=True
    ).values_list("student_membership_id", "digest")
    opened = [
        sid for sid, kept in rows if hmac.compare_digest(kept, digest(school.pk, sid, term.pk, digits))
    ]
    if len(opened) != 1:
        return None
    return students[opened[0]]


__all__ = [
    "NotAllowedToPrint",
    "PIN_DIGITS",
    "PinError",
    "PrintRefused",
    "Slip",
    "Slips",
    "check",
    "current_term",
    "digest",
    "live_pin_holders",
    "new_pin",
    "print_class_as",
    "print_student_as",
    "printed",
    "roster",
]
