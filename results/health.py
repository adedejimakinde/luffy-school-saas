"""A child's physical development and health, per term. `HealthRecord`.

`docs/ogun-template.md` part 3. Sensitive children's health data, so this
module is the whole of who may read and write it, and nothing else in the
codebase serves it.

## Four readers

`may_see()` answers for one child and one term:

- **the class teacher** of the class the child sat in that term
  (`ClassPlacement` and `ClassTeacher`, both per term);
- **the principal** and **a school administrator** of the school;
- **the child's guardians** (`Guardianship`), for a term whose card has been
  released to them. Before release a family sees no part of a card, and this
  part is no different.

Nobody else: not another teacher, not the vice principal, not the bursar,
not the child's own login, and not a result-checker PIN. A refusal is a flat
404 at the route, so a stranger cannot learn which children have a record.

## One writer

The class teacher enters it, during the term. A record for a term whose card
has gone home is locked (`HealthLocked`, and the database trigger behind it).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from django.db import IntegrityError, transaction

from academics import services as academics
from accounts.models import Guardianship, Role

from .models import HealthLocked, HealthRecord, ReleasedCard

#: Office readers. Narrower than `card_api.CARD_VIEWING_ROLES` on purpose: a
#: teacher, a vice principal and a bursar read any card, and none of them reads
#: a child's health.
OFFICE_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})

MAX_ILLNESS = HealthRecord._meta.get_field("illness").max_length


class HealthRefused(Exception):
    """A value the record will not take. The message is for the person."""


class NotAllowedToRecordHealth(Exception):
    pass


def _is_class_teacher(actor, school, child, term) -> bool:
    placement = academics.placement_of(child.pk, term)
    if placement is None:
        return False
    mine = actor.membership_id_at(school, Role.TEACHER)
    return academics.is_class_teacher(mine, placement.class_group, term)


def is_released(child, term) -> bool:
    return ReleasedCard.objects.filter(student_membership_id=child.pk, term=term).exists()


def may_see(actor, school, child, term) -> bool:
    """See the module docstring. `child` is a STUDENT membership of `school`."""
    if not getattr(actor, "is_authenticated", False):
        return False
    if set(actor.roles_at(school)) & OFFICE_ROLES:
        return True
    if _is_class_teacher(actor, school, child, term):
        return True
    if Guardianship.objects.filter(guardian=actor, student=child).exists():
        return is_released(child, term)
    return False


def may_record(actor, school, child, term) -> bool:
    return getattr(actor, "is_authenticated", False) and _is_class_teacher(actor, school, child, term)


def record_for(child, term) -> Optional[HealthRecord]:
    return HealthRecord.objects.filter(student_membership_id=child.pk, term=term).first()


# -- reading what was typed ---------------------------------------------------


def _decimal(value, what, places, low, high, unit) -> Optional[Decimal]:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise HealthRefused(f"{what} is a number, in {unit}.")
    if not number.is_finite():
        raise HealthRefused(f"{what} is a number, in {unit}.")
    number = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if not (low <= number <= high):
        raise HealthRefused(f"{what} is in {unit}, between {low} and {high}.")
    return number


@dataclass
class Values:
    height_start_m: Optional[Decimal] = None
    height_end_m: Optional[Decimal] = None
    weight_start_kg: Optional[Decimal] = None
    weight_end_kg: Optional[Decimal] = None
    days_absent_ill: Optional[int] = None
    illness: str = ""


def read(*, height_start_m=None, height_end_m=None, weight_start_kg=None, weight_end_kg=None,
         days_absent_ill=None, illness="") -> Values:
    low_h, high_h = HealthRecord.HEIGHT_RANGE
    low_w, high_w = HealthRecord.WEIGHT_RANGE
    days = None
    if days_absent_ill is not None and str(days_absent_ill).strip() != "":
        try:
            days = int(str(days_absent_ill).strip())
        except ValueError:
            raise HealthRefused("Days absent through illness is a whole number.")
        if not 0 <= days <= HealthRecord.MAX_DAYS_ILL:
            raise HealthRefused(f"Days absent through illness is between 0 and {HealthRecord.MAX_DAYS_ILL}.")
    illness = " ".join(str(illness or "").split())
    if len(illness) > MAX_ILLNESS:
        raise HealthRefused(f"Say the illness in {MAX_ILLNESS} characters or fewer.")
    return Values(
        height_start_m=_decimal(height_start_m, "Height at the beginning of term", 2, low_h, high_h, "metres"),
        height_end_m=_decimal(height_end_m, "Height at the end of term", 2, low_h, high_h, "metres"),
        weight_start_kg=_decimal(weight_start_kg, "Weight at the beginning of term", 1, low_w, high_w, "kilograms"),
        weight_end_kg=_decimal(weight_end_kg, "Weight at the end of term", 1, low_w, high_w, "kilograms"),
        days_absent_ill=days,
        illness=illness,
    )


# -- writing ------------------------------------------------------------------


def record_as(actor, school, child, term, values: Values) -> HealthRecord:
    """The class teacher records a child's health for the term. Blank clears a box."""
    if not may_record(actor, school, child, term):
        raise NotAllowedToRecordHealth(
            "A child's health is recorded by the class teacher of the class they are in."
        )
    if is_released(child, term):
        raise HealthLocked(
            "This child's card for the term has been released, so its health record cannot change."
        )
    try:
        with transaction.atomic():
            row, _ = HealthRecord.objects.select_for_update().get_or_create(
                term=term, student_membership_id=child.pk
            )
            for name, value in values.__dict__.items():
                setattr(row, name, value)
            row.entered_by_id = actor.pk
            row.save()
    except IntegrityError as exc:
        # The trigger: a release committed between the check above and the
        # write. Its own sentence, not the database's.
        if "released" in str(exc):
            raise HealthLocked(
                "This child's card for the term has been released, so its health record cannot change."
            ) from None
        raise
    return row


__all__ = [
    "HealthLocked",
    "HealthRefused",
    "NotAllowedToRecordHealth",
    "OFFICE_ROLES",
    "Values",
    "may_record",
    "may_see",
    "is_released",
    "read",
    "record_as",
    "record_for",
]
