"""Exam officers: the principal names them and ends them. `docs/cbt.md`, "Exam officers".

Each act writes one `ExamOfficerGrant` row naming who did it and when, in a table a
trigger keeps append-only; the latest row for a membership is where it stands
(`access.officer_memberships()`), so the log is the state and nothing else records it
(operating rule 4).

Only a teacher, the vice principal or the administrator of **this** school can be
named, and only while they can act here. Two taps at once cannot both name, or both
end: each locks the membership's row first, then reads where it stands.
"""

from django.db import transaction

from accounts.models import Membership

from . import access
from .models import ExamOfficerGrant


class OfficerError(Exception):
    """An exam officer could not be named or ended as asked."""


class NotAllowedToName(OfficerError):
    """The caller is not the principal of this school."""


class OfficerRefused(OfficerError):
    """Well formed, and the school's own rules say no. The message is the reason."""


#: Longer than the column is refused, not cut: a note is what the principal wrote.
MAX_NOTE = ExamOfficerGrant._meta.get_field("note").max_length


def _name_of_user(user) -> str:
    return user.full_name or user.get_username()


def _name_of(membership) -> str:
    return membership.display_name or membership.user.full_name or membership.user.username


def _require_naming_authority(actor, school):
    if not access.can_name(actor, school):
        raise NotAllowedToName(f"{actor} may not name exam officers at {school}. That is the principal's.")


def _locked(school, membership_id):
    """This school's membership, row-locked, or None. Another school's is simply not found."""
    return (
        Membership.objects.select_for_update(of=("self",))
        .select_related("user", "school")
        .filter(pk=membership_id, school=school)
        .first()
    )


def _note(note) -> str:
    note = " ".join((note or "").split())
    if len(note) > MAX_NOTE:
        raise OfficerRefused(f"A note can be at most {MAX_NOTE} characters.")
    return note


def name_as(actor, school, membership_id, note="") -> ExamOfficerGrant:
    """Name this membership an exam officer here. The principal's."""
    _require_naming_authority(actor, school)
    note = _note(note)
    with transaction.atomic():
        membership = _locked(school, membership_id)
        if (
            membership is None
            or membership.school.schema_name != school.schema_name
            or not membership.grants_access
            or membership.role not in access.OFFICER_ROLES
        ):
            raise OfficerRefused(
                "Only a teacher, the vice principal or the administrator of this school can be named exam officer."
            )
        if access.officer_memberships([membership.pk]):
            raise OfficerRefused(f"{_name_of(membership)} is already an exam officer.")
        return ExamOfficerGrant.objects.create(
            membership_id=membership.pk,
            kind=ExamOfficerGrant.Kind.NAMED,
            membership_name=_name_of(membership),
            role=membership.role,
            by_id=actor.pk,
            by_name=_name_of_user(actor),
            note=note,
        )


def end_as(actor, school, membership_id, note="") -> ExamOfficerGrant:
    """End this membership's time as an exam officer here. The principal's.

    Works for somebody who has since left, so that a grant is never stranded.
    """
    _require_naming_authority(actor, school)
    note = _note(note)
    with transaction.atomic():
        membership = _locked(school, membership_id)
        if membership is None or not access.officer_memberships([membership.pk]):
            raise OfficerRefused("That person is not an exam officer here.")
        return ExamOfficerGrant.objects.create(
            membership_id=membership.pk,
            kind=ExamOfficerGrant.Kind.ENDED,
            membership_name=_name_of(membership),
            role=membership.role,
            by_id=actor.pk,
            by_name=_name_of_user(actor),
            note=note,
        )


__all__ = ["MAX_NOTE", "NotAllowedToName", "OfficerError", "OfficerRefused", "end_as", "name_as"]
