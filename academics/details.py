"""A child's details beyond a name: learner's ID, sex, date of birth and photo.

`StudentDetails` holds them, one row per child in the school's own schema. This
module is every write to that row and the one read that lists it.

## Who may

The office: a principal or an administrator, `PLACEMENT_ROLES` — the people who
already keep the roll on `/roll/`. A teacher sees a child's name and class and
does not edit what the office recorded about them.

## The photo is an upload like any other

It goes through the one upload service (`files.service`, slot
`student_photo:<membership id>`): checked by its own bytes in the request, then
drawn by the media worker into a master of 1200 px on its long side and a
passport frame (7:9, centred a little above the middle, where a face is) at the
size the card prints, as JPEG and WebP, plus a half-size WebP for a phone.
Nothing of the original file is kept: no metadata, no location. A new photo
replaces the old one only once it is ready.

Until `manage.py move_files_to_disk` has copied it, a child's photo may still be
the JPEG in `StudentDetails.photo`, written before the service existed; the
readers here fall back to it, and removing the photo clears both.

## A learner's ID is unique at this school, when there is one

Compared without case, by the constraint `one_child_per_learner_id_per_school`
and by `learner_id_holder()` before it, so the office is told which child already holds
it rather than shown a database error.
"""

from datetime import date
from typing import Iterable, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Membership, Role

from .models import Sex, StudentDetails
from .services import can_place_students

#: The photo as the card prints it: a passport frame (35 by 45 mm), about
#: 200dpi at the size the card prints it (`files.kinds`, "card").
PHOTO_SIZE = (280, 360)

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


def photo_slot(membership_id: int) -> str:
    return f"student_photo:{int(membership_id)}"


def set_photo_as(actor, school, membership, upload) -> StudentDetails:
    """Take a new photo. It is checked now and drawn by the media worker."""
    from files import service
    from files.kinds import Kind

    _require_authority(actor, school)
    _require_student_here(school, membership)
    try:
        stored = service.accept(Kind.STUDENT_PHOTO, upload, slot=photo_slot(membership.pk), by=actor)
    except service.UploadRefused as exc:
        raise DetailsRefused(str(exc))
    if stored.state == "failed":
        raise DetailsRefused(stored.error)
    with transaction.atomic():
        row = _row_for(membership.pk)
        row.updated_by_id = actor.pk
        row.save(update_fields=["updated_by_id", "updated_at"])
    return row


def clear_photo_as(actor, school, membership) -> StudentDetails:
    _require_authority(actor, school)
    _require_student_here(school, membership)
    from files import service

    with transaction.atomic():
        service.clear_slot(photo_slot(membership.pk))
        row = _row_for(membership.pk)
        row.photo = None
        row.updated_by_id = actor.pk
        row.save(update_fields=["photo", "updated_by_id", "updated_at"])
    return row


# -- reading ------------------------------------------------------------------


def details_for(membership_ids: Iterable[int]) -> dict:
    """`{membership id: StudentDetails}` for those that have a row. One query.

    The photo is deferred: a list of children never reads their pictures.
    `has_photo` is answered in the same query: a ready file in the child's
    slot, or (until it is moved to disk) bytes in the old column.
    """
    from django.db import connection
    from django.db.models import BooleanField, Case, CharField, Exists, OuterRef, Q, Value, When
    from django.db.models.functions import Cast, Concat

    from files.models import StoredFile

    ready_file = StoredFile.objects.filter(
        schema_name=connection.schema_name,
        state="ready",
        slot=Concat(Value("student_photo:"), Cast(OuterRef("student_membership_id"), CharField())),
    )
    rows = (
        StudentDetails.objects.filter(student_membership_id__in=list(membership_ids))
        .defer("photo")
        .annotate(has_file=Exists(ready_file))
        .annotate(
            has_photo=Case(
                When(Q(has_file=True) | Q(photo__isnull=False), then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
    )
    return {row.student_membership_id: row for row in rows}


def photo_file(membership_id: int):
    """The child's photo as the upload service keeps it, or None."""
    from files import service

    return service.current(photo_slot(membership_id))


def photo_status(membership_id: int) -> dict:
    """Ready, being drawn, or why the last one could not be used."""
    from files import service

    return service.status_of(photo_slot(membership_id))


def photo_of(membership_id: int) -> Optional[bytes]:
    """The passport frame the card prints, as JPEG bytes, or None."""
    from files import service

    stored = photo_file(membership_id)
    if stored is not None:
        try:
            return service.read(stored, "card.jpg")
        except FileNotFoundError:
            return None
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
    "MAY_NOT_EDIT",
    "NotAllowedToEditDetails",
    "PHOTO_SIZE",
    "can_edit_details",
    "clear_photo_as",
    "details_for",
    "learner_id_holder",
    "photo_file",
    "photo_of",
    "photo_slot",
    "photo_status",
    "read_date_of_birth",
    "read_learner_id",
    "read_sex",
    "record",
    "set_details_as",
    "set_photo_as",
    "student_here",
]
