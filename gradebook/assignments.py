"""Who teaches which subject to which class, and what that does to marking.

The principal says who teaches what, per term (`SubjectTeacher`). The vice principal
and the administrator can read it; only the principal changes it. Every change writes
a `SubjectTeacherChange` in the same transaction, naming who and when.

## What it does to marking

**Nothing, until the term has an assignment.** Until then any teacher marks any paper,
exactly as before, and the principal's Home says so (`home/views.py`). From the first
row in a term, a teacher marks only the pairs they hold that term: their marking page
lists those (`gradebook.api.where_to_mark()`), and the sheet and both writes refuse the
rest on the server (`may_mark()`, asked by `services.set_score_as()`,
`services.clear_score_as()` and `api.marking_sheet()`). Remove every row and the term
is back where it started: the rule is "while the term has one", not "once it ever had".

**The principal, the vice principal and the administrator are never narrowed**
(`UNNARROWED_ROLES`). The administrator and the principal mark as before; the vice
principal has no marking role of their own (`services.MARK_ENTERING_ROLES`), so this
matters only to one who also teaches, who keeps marking everything.

The term is the paper's own (`Assessment.term`), never today's, so a paper from an
earlier term is judged by that term's assignments.

**Released results are untouched.** Nothing here reads or writes a released row, and a
mark on a released card is refused by `services._require_this_card_has_not_gone_home()`
whoever is assigned.
"""

from django.db import IntegrityError, transaction

from accounts.models import Membership, Role
from accounts.staff import why_not_a_teacher_here

from .models import SubjectTeacher, SubjectTeacherChange

#: Who changes the assignments: the principal alone (decided 23 October 2026).
ASSIGNING_ROLES = frozenset({Role.PRINCIPAL.value})

#: Who reads them. The administrator and the vice principal see them and cannot change
#: them.
VIEWING_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)

#: Whose marking assignments never narrow.
UNNARROWED_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)


class AssignmentError(Exception):
    """An assignment could not be changed as asked."""


class NotAllowedToAssign(AssignmentError):
    """The caller is not the principal of this school."""


class AssignmentRefused(AssignmentError):
    """Well formed, and the school's own rules say no. The message is the reason."""


def _roles(actor, school) -> set:
    if not getattr(actor, "is_authenticated", False):
        return set()
    return set(actor.roles_at(school))


def can_view(actor, school) -> bool:
    return bool(_roles(actor, school) & VIEWING_ROLES)


def can_assign(actor, school) -> bool:
    return bool(_roles(actor, school) & ASSIGNING_ROLES)


def _require_assigning_authority(actor, school):
    if not can_assign(actor, school):
        raise NotAllowedToAssign(
            f"{actor} may not change who teaches what at {school}. That is the principal's."
        )


# -- the narrowing ------------------------------------------------------------------


def in_force(term) -> bool:
    """Has this term any assignment? Until it has, marking is not narrowed."""
    return term is not None and SubjectTeacher.objects.filter(term=term).exists()


def _teacher_ids(actor, school) -> list:
    """The actor's TEACHER memberships here that can act now (usually one)."""
    return list(
        Membership.objects.with_access()
        .filter(user=actor, school=school, role=Role.TEACHER)
        .values_list("pk", flat=True)
    )


def narrowed(actor, school, term) -> bool:
    """Is this actor's marking narrowed to their own pairs in `term`?"""
    if _roles(actor, school) & UNNARROWED_ROLES:
        return False
    return in_force(term)


def pairs_of(actor, school, term) -> set:
    """`{(subject_id, class_group_id)}` this actor holds in `term`."""
    if term is None:
        return set()
    return set(
        SubjectTeacher.objects.filter(
            term=term, teacher_membership_id__in=_teacher_ids(actor, school)
        ).values_list("subject_id", "class_group_id")
    )


def may_mark(actor, school, term, subject_id, class_group_id) -> bool:
    """May this actor mark this subject in this class, in this term?

    Only the narrowing. Whether they may mark at all is
    `services.can_enter_marks()`, asked first by every caller. A child with no class
    in the term has no `class_group_id` (`None`), and a narrowed teacher may not mark
    them: nothing assigns a teacher to a child who is in no class.
    """
    if not narrowed(actor, school, term):
        return True
    if class_group_id is None:
        return False
    return (subject_id, class_group_id) in pairs_of(actor, school, term)


def prompt_for(roles) -> bool:
    """Should Home ask this login to say who teaches what?

    The principal's, while the current term has no assignment. Nothing is read for
    anybody else.
    """
    if not set(roles) & ASSIGNING_ROLES:
        return False
    from academics.models import Term

    term = Term.objects.filter(is_current=True).first()
    return term is not None and not in_force(term)


# -- the principal's writes ---------------------------------------------------------


def _name_of_user(user) -> str:
    return user.full_name or user.get_username()


def _name_of_membership(membership) -> str:
    return membership.display_name or membership.user.full_name or membership.user.username


def assign_as(actor, school, term, class_group, subject, membership):
    """Say that `membership` teaches `subject` to `class_group` in `term`."""
    _require_assigning_authority(actor, school)
    if term is None:
        raise AssignmentRefused("No term is open. Set the current term on the Setup page first.")
    if why_not_a_teacher_here(membership, subject="a subject teacher", holder="gradebook") or (
        membership.school_id != school.pk
    ):
        raise AssignmentRefused("That is not one of this school's teachers.")
    if not subject.is_active:
        raise AssignmentRefused(f"{subject.name} is no longer taught, so nobody can be given it.")
    if not class_group.is_active:
        raise AssignmentRefused(f"{class_group.name} is closed, so nobody can be given it.")
    teacher_name = _name_of_membership(membership)
    try:
        with transaction.atomic():
            row = SubjectTeacher.objects.create(
                term=term,
                class_group=class_group,
                subject=subject,
                teacher_membership_id=membership.pk,
                assigned_by_id=actor.pk,
            )
            SubjectTeacherChange.objects.create(
                term=term,
                kind=SubjectTeacherChange.Kind.ADDED,
                class_group_id=class_group.pk,
                subject_id=subject.pk,
                teacher_membership_id=membership.pk,
                class_group_name=class_group.name,
                subject_name=subject.name,
                teacher_name=teacher_name,
                by_id=actor.pk,
                by_name=_name_of_user(actor),
            )
    except IntegrityError as exc:
        raise AssignmentRefused(
            f"{teacher_name} already teaches {subject.name} to {class_group.name}."
        ) from exc
    return row


def unassign_as(actor, school, row_id) -> bool:
    """Take one assignment away. False if it was already gone."""
    _require_assigning_authority(actor, school)
    with transaction.atomic():
        row = (
            SubjectTeacher.objects.select_for_update(of=("self",))
            .select_related("class_group", "subject")
            .filter(pk=row_id)
            .first()
        )
        if row is None:
            return False
        teacher = Membership.objects.select_related("user").filter(pk=row.teacher_membership_id).first()
        SubjectTeacherChange.objects.create(
            term_id=row.term_id,
            kind=SubjectTeacherChange.Kind.REMOVED,
            class_group_id=row.class_group_id,
            subject_id=row.subject_id,
            teacher_membership_id=row.teacher_membership_id,
            class_group_name=row.class_group.name,
            subject_name=row.subject.name,
            teacher_name=_name_of_membership(teacher) if teacher else "",
            by_id=actor.pk,
            by_name=_name_of_user(actor),
        )
        row.delete()
    return True


__all__ = [
    "ASSIGNING_ROLES",
    "AssignmentError",
    "AssignmentRefused",
    "NotAllowedToAssign",
    "UNNARROWED_ROLES",
    "VIEWING_ROLES",
    "assign_as",
    "can_assign",
    "can_view",
    "in_force",
    "may_mark",
    "narrowed",
    "pairs_of",
    "prompt_for",
    "unassign_as",
]
