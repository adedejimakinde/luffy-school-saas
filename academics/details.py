"""A child's details beyond a name: learner's ID, sex, date of birth and photo.

`StudentDetails` holds them, one row per child in the school's own schema. This
module is every write to that row and the one read that lists it.

## Who may

The office: a principal or an administrator, `PLACEMENT_ROLES` — the people who
already keep the roll on `/roll/`. A teacher sees a child's name and class and
does not edit what the office recorded about them.

## The photo is re-drawn, never kept as sent

As a crest is (`results.look`): the upload goes through the same checks
(`look.open_picture()`: size before opening, PNG or JPG only, pixel count from
the header before decoding) and is then cropped to a passport frame, centred a
little above the middle where a face is, and written out as a fresh JPEG of
`PHOTO_SIZE`. Nothing of the original file is stored: no metadata, no location,
nothing hidden after the image. The limit is larger than a crest's because a
photo comes off a phone camera.

## A learner's ID is unique at this school, when there is one

Compared without case, by the constraint `one_child_per_learner_id_per_school`
and by `learner_id_holder()` before it, so the office is told which child already holds
it rather than shown a database error.
"""

import io
from datetime import date
from typing import Iterable, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Membership, Role
from results import look

from .models import Sex, StudentDetails
from .services import can_place_students

#: The photo as stored and printed: a passport frame (35 by 45 mm), about
#: 200dpi at the size the card prints it.
PHOTO_SIZE = (280, 360)

#: A photo straight off a phone is a few megabytes.
MAX_PHOTO_BYTES = 5 * 1024 * 1024

#: A 48-megapixel phone sensor and some room; checked from the header.
MAX_PHOTO_PIXELS = 52_000_000

MAX_LEARNER_ID = StudentDetails._meta.get_field("learner_id").max_length

#: The earliest date of birth a row accepts, the constraint's own floor.
EARLIEST_BIRTH = date(1950, 1, 1)


class DetailsRefused(Exception):
    """What was sent cannot be recorded. The message is for the person."""


class NotAllowedToEditDetails(Exception):
    pass


MAY_NOT_EDIT = "A child's details are kept by a principal or an administrator of the school."


def can_edit_details(actor, school) -> bool:
    return can_place_students(actor, school)


def _require_authority(actor, school):
    if not can_edit_details(actor, school):
        raise NotAllowedToEditDetails(MAY_NOT_EDIT)


def _require_student_here(school, membership):
    if (
        membership.school_id != school.pk
        or membership.role != Role.STUDENT
    ):
        raise DetailsRefused("That is not a child on this school's roll.")


# -- reading the typed values -------------------------------------------------


_SEX_WORDS = {
    "f": Sex.FEMALE,
    "female": Sex.FEMALE,
    "girl": Sex.FEMALE,
    "m": Sex.MALE,
    "male": Sex.MALE,
    "boy": Sex.MALE,
}


def read_sex(value) -> str:
    """"F", "Female", "girl" and their capitals are `female`; blank is unsaid."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    sex = _SEX_WORDS.get(text)
    if sex is None:
        raise DetailsRefused(f"{value!r} is not a sex this can record. Write Female or Male.")
    return sex.value


def read_date_of_birth(value, *, today: Optional[date] = None) -> Optional[date]:
    """A date, or day/month/year as Nigerian offices write it, or ISO.

    `31/01/2014`, `31-01-2014`, `31.01.2014` and `2014-01-31` are all the same
    day. Month-first is never guessed: `02/03/2014` is the 2nd of March.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        parsed = None
        try:
            parsed = date.fromisoformat(text[:10]) if len(text) >= 10 and text[4] == "-" else None
        except ValueError:
            parsed = None
        if parsed is None:
            parts = text.replace("-", "/").replace(".", "/").split("/")
            try:
                day, month, year = (int(p) for p in parts)
                parsed = date(year, month, day) if year >= 1000 else None
            except ValueError:
                parsed = None
        if parsed is None:
            raise DetailsRefused(
                f"{value!r} is not a date this can read. Write it as day/month/year, like 31/01/2014."
            )
    today = today or timezone.localdate()
    if parsed > today:
        raise DetailsRefused("A date of birth cannot be in the future.")
    if parsed < EARLIEST_BIRTH:
        raise DetailsRefused(f"A date of birth before {EARLIEST_BIRTH.year} is not a child's.")
    return parsed


def read_learner_id(value) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > MAX_LEARNER_ID:
        raise DetailsRefused(f"A learner's ID is at most {MAX_LEARNER_ID} characters.")
    return text


def learner_id_holder(learner_id: str, *, besides: Optional[int] = None) -> Optional[int]:
    """The membership id of the child at this school who holds this ID, if any."""
    if not learner_id:
        return None
    holders = StudentDetails.objects.filter(learner_id__iexact=learner_id)
    if besides is not None:
        holders = holders.exclude(student_membership_id=besides)
    return holders.values_list("student_membership_id", flat=True).first()


def _taken(learner_id: str) -> DetailsRefused:
    return DetailsRefused(f"{learner_id!r} is already another child's learner's ID at this school.")


# -- writing ------------------------------------------------------------------


def _row_for(membership_id: int) -> StudentDetails:
    row, _ = StudentDetails.objects.select_for_update().get_or_create(
        student_membership_id=membership_id
    )
    return row


def record(membership_id: int, *, learner_id="", sex="", date_of_birth=None, by=None) -> StudentDetails:
    """Write the three typed fields for one child. No authority asked: callers ask.

    Used by `set_details_as()` and by the roll import, which has asked who is
    importing before it gets here. A learner's ID another child holds is
    refused, by `learner_id_holder()` first and by the constraint if two writes race.
    """
    learner_id = read_learner_id(learner_id)
    if learner_id_holder(learner_id, besides=membership_id) is not None:
        raise _taken(learner_id)
    try:
        with transaction.atomic():
            row = _row_for(membership_id)
            row.learner_id = learner_id
            row.sex = read_sex(sex)
            row.date_of_birth = read_date_of_birth(date_of_birth)
            row.updated_by_id = getattr(by, "pk", None)
            row.save(update_fields=["learner_id", "sex", "date_of_birth", "updated_by_id", "updated_at"])
    except IntegrityError:
        raise _taken(learner_id)
    return row


def set_details_as(actor, school, membership, *, learner_id="", sex="", date_of_birth=None):
    """The office records a child's learner's ID, sex and date of birth. Blank clears."""
    _require_authority(actor, school)
    _require_student_here(school, membership)
    return record(
        membership.pk, learner_id=learner_id, sex=sex, date_of_birth=date_of_birth, by=actor
    )


def redraw_photo(raw: bytes) -> bytes:
    """The upload, cropped to a passport frame and written as a new JPEG."""
    from PIL import Image, ImageOps

    source = look.open_picture(
        raw,
        noun="A photo",
        max_bytes=MAX_PHOTO_BYTES,
        max_pixels=MAX_PHOTO_PIXELS,
        size_hint=(PHOTO_SIZE[0] * 2, PHOTO_SIZE[1] * 2),
    )
    # On white rather than black wherever the upload was transparent.
    flat = Image.new("RGB", source.size, (255, 255, 255))
    flat.paste(source, mask=source.split()[3])
    framed = ImageOps.fit(flat, PHOTO_SIZE, Image.LANCZOS, centering=(0.5, 0.4))
    out = io.BytesIO()
    framed.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()


def set_photo_as(actor, school, membership, raw: bytes) -> StudentDetails:
    _require_authority(actor, school)
    _require_student_here(school, membership)
    photo = redraw_photo(raw)
    with transaction.atomic():
        row = _row_for(membership.pk)
        row.photo = photo
        row.updated_by_id = actor.pk
        row.save(update_fields=["photo", "updated_by_id", "updated_at"])
    return row


def clear_photo_as(actor, school, membership) -> StudentDetails:
    _require_authority(actor, school)
    _require_student_here(school, membership)
    with transaction.atomic():
        row = _row_for(membership.pk)
        row.photo = None
        row.updated_by_id = actor.pk
        row.save(update_fields=["photo", "updated_by_id", "updated_at"])
    return row


# -- reading ------------------------------------------------------------------


def details_for(membership_ids: Iterable[int]) -> dict:
    """`{membership id: StudentDetails}` for those that have a row. One query.

    The photo is deferred: a list of children never reads their pictures.
    `has_photo` is answered from the row's own query, not from the bytes.
    """
    from django.db.models import BooleanField, Case, Value, When

    rows = (
        StudentDetails.objects.filter(student_membership_id__in=list(membership_ids))
        .defer("photo")
        .annotate(
            has_photo=Case(
                When(photo__isnull=False, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
    )
    return {row.student_membership_id: row for row in rows}


def photo_of(membership_id: int) -> Optional[bytes]:
    photo = (
        StudentDetails.objects.filter(student_membership_id=membership_id)
        .values_list("photo", flat=True)
        .first()
    )
    return bytes(photo) if photo else None


def student_here(school, membership_id: int) -> Optional[Membership]:
    return (
        Membership.objects.filter(pk=membership_id, school=school, role=Role.STUDENT)
        .select_related("user")
        .first()
    )


__all__ = [
    "DetailsRefused",
    "MAX_PHOTO_BYTES",
    "MAY_NOT_EDIT",
    "NotAllowedToEditDetails",
    "PHOTO_SIZE",
    "can_edit_details",
    "clear_photo_as",
    "details_for",
    "learner_id_holder",
    "photo_of",
    "read_date_of_birth",
    "read_learner_id",
    "read_sex",
    "record",
    "redraw_photo",
    "set_details_as",
    "set_photo_as",
    "student_here",
]
