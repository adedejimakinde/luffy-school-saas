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
`services.clear_score_as()` and `api.marking_sheet()`).

**And it stays that way.** The rule is "once the term has had one", not "while it has
one": taking the last row away leaves marking restricted, and a teacher holding nothing
marks nothing. Only the principal's switch opens the term to every teacher again
(`set_open_as()`), and only it restricts it again; both are written to the log. Where
a term stands is read from that log (`marking_in()`), never from a column.

**A new term starts with the last one's assignments** (`carry_forward()`), copied by
the system as the term is made current, so it is restricted from its first day if the
last one was. If the last term had none, nothing is copied and nothing changes.

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
from django.utils import timezone

from accounts.models import Membership, Role
from accounts.staff import why_not_a_teacher_here

from .models import SubjectTeacher, SubjectTeacherCarry, SubjectTeacherChange

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


#: Where a term's marking stands (`marking_in()`).
NOT_YET = "not-yet"
RESTRICTED = "restricted"
OPEN = "open"

_Kind = SubjectTeacherChange.Kind


def marking_in(term) -> str:
    """`NOT_YET`, `RESTRICTED` or `OPEN`: a fold over the term's log.

    The principal's last switch, if there is one. Otherwise `RESTRICTED` once the term
    has had any assignment, and `NOT_YET` before: the term marks as it always did. A
    removal is not a switch, so taking the last row away changes nothing here.
    """
    if term is None:
        return NOT_YET
    changes = SubjectTeacherChange.objects.filter(term=term)
    switch = (
        changes.filter(kind__in=SubjectTeacherChange.SWITCH)
        .order_by("-id")
        .values_list("kind", flat=True)
        .first()
    )
    if switch is not None:
        return OPEN if switch == _Kind.OPENED else RESTRICTED
    if changes.filter(kind=_Kind.ADDED).exists() or SubjectTeacher.objects.filter(term=term).exists():
        return RESTRICTED
    return NOT_YET


def in_force(term) -> bool:
    """Is marking in this term restricted to the teachers given each pair?"""
    return marking_in(term) == RESTRICTED


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


def _current_term():
    from academics.models import Term

    return Term.objects.filter(is_current=True).first()


def prompt_for(roles) -> bool:
    """Should Home ask this login to say who teaches what?

    The principal's, while the current term has never had an assignment. Nothing is
    read for anybody else.
    """
    if not set(roles) & ASSIGNING_ROLES:
        return False
    term = _current_term()
    return term is not None and marking_in(term) == NOT_YET


def carried_for(roles):
    """The current term's carry-forward, while the principal has not looked at it.

    For Home's "Assignments copied from last term". `None` for anybody else, and once
    the principal has opened `/subject-teachers/` in this term or dismissed the card.
    """
    if not set(roles) & ASSIGNING_ROLES:
        return None
    term = _current_term()
    if term is None:
        return None
    return (
        SubjectTeacherCarry.objects.filter(term=term, seen_at__isnull=True)
        .select_related("from_term")
        .first()
    )


def seen_as(actor, school, term) -> bool:
    """The principal has looked at this term's carry-forward. True if one was waiting."""
    if term is None or not can_assign(actor, school):
        return False
    return bool(
        SubjectTeacherCarry.objects.filter(term=term, seen_at__isnull=True).update(
            seen_at=timezone.now(), seen_by_id=actor.pk
        )
    )


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


def set_open_as(actor, school, term, open_to_all: bool) -> bool:
    """The principal's switch: open this term's marking to every teacher, or not.

    Only for a term that has had an assignment: before that it is open already, and
    restricting it would leave every teacher with nothing. Saying what it already is
    writes nothing and answers False; a change writes an `OPENED` or a `RESTRICTED`
    row, naming who, and answers True.
    """
    _require_assigning_authority(actor, school)
    if term is None:
        raise AssignmentRefused("No term is open. Set the current term on the Setup page first.")
    with transaction.atomic():
        # One switch at a time, so two taps cannot both find it the other way.
        type(term).objects.select_for_update().filter(pk=term.pk).first()
        now = marking_in(term)
        if now == NOT_YET:
            raise AssignmentRefused(
                "Nobody has been given a subject this term, so marking is already open to every teacher."
            )
        if (now == OPEN) == bool(open_to_all):
            return False
        SubjectTeacherChange.objects.create(
            term=term,
            kind=_Kind.OPENED if open_to_all else _Kind.RESTRICTED,
            by_id=actor.pk,
            by_name=_name_of_user(actor),
        )
    return True


# -- the new term -------------------------------------------------------------------


def _why_not_copied(row, teacher) -> str:
    if teacher is None or why_not_a_teacher_here(teacher, subject="a subject teacher", holder="gradebook"):
        return "no longer a teacher here"
    if not row.subject.is_active:
        return "the subject is no longer taught"
    if not row.class_group.is_active:
        return "the class is closed"
    return ""


def carry_forward(school, previous, term):
    """Copy `previous`'s assignments into `term`, which has just been made current.

    Called by `academics.api.set_current_term()` in the transaction that makes `term`
    current, with the term that was current until then. Copies only going forward
    (`term` starts after `previous`) and only into a term that has never had an
    assignment of its own, so switching back and forth copies nothing twice. Returns
    the `SubjectTeacherCarry`, or `None` when there was nothing to copy: if `previous`
    had no assignments, nothing at all is written and the new term marks as today.

    Each row is copied only if it could be given today (`assign_as()`'s rules): a
    teacher who has left this school or no longer has teacher access, a subject no
    longer taught and a closed class are left out, each written down as `SKIPPED`
    with why. A teacher is looked up among **this** school's memberships, so a row
    that named anybody else is never copied. If the principal had opened `previous` to
    every teacher, `term` is opened too, so a new term never quietly narrows marking
    the principal had opened. Every row names `previous` and nobody: the system did it.
    """
    if previous is None or term is None or previous.pk == term.pk:
        return None
    if previous.starts_on >= term.starts_on or marking_in(term) != NOT_YET:
        return None
    rows = list(
        SubjectTeacher.objects.filter(term=previous).select_related("class_group", "subject")
    )
    if not rows:
        return None
    # This school's memberships only, whatever the rows say; the names of any, so that
    # a teacher who has left is still named in the line that says so.
    members = Membership.objects.filter(
        pk__in={r.teacher_membership_id for r in rows}, school=school
    ).select_related("user", "school")
    names = {m.pk: _name_of_membership(m) for m in members}
    teachers = {m.pk: m for m in members.with_access().filter(role=Role.TEACHER)}
    from_name = str(previous)
    copied = skipped = 0
    for row in rows:
        teacher = teachers.get(row.teacher_membership_id)
        why = _why_not_copied(row, teacher)
        if not why:
            SubjectTeacher.objects.create(
                term=term,
                class_group_id=row.class_group_id,
                subject_id=row.subject_id,
                teacher_membership_id=row.teacher_membership_id,
            )
            copied += 1
        else:
            skipped += 1
        SubjectTeacherChange.objects.create(
            term=term,
            kind=_Kind.SKIPPED if why else _Kind.ADDED,
            class_group_id=row.class_group_id,
            subject_id=row.subject_id,
            teacher_membership_id=row.teacher_membership_id,
            class_group_name=row.class_group.name,
            subject_name=row.subject.name,
            teacher_name=names.get(row.teacher_membership_id, ""),
            from_term=previous,
            from_term_name=from_name,
            reason=why,
        )
    if copied and marking_in(previous) == OPEN:
        SubjectTeacherChange.objects.create(
            term=term, kind=_Kind.OPENED, from_term=previous, from_term_name=from_name
        )
    return SubjectTeacherCarry.objects.create(
        term=term, from_term=previous, copied=copied, skipped=skipped
    )


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
    "NOT_YET",
    "NotAllowedToAssign",
    "OPEN",
    "RESTRICTED",
    "UNNARROWED_ROLES",
    "VIEWING_ROLES",
    "assign_as",
    "can_assign",
    "can_view",
    "carried_for",
    "carry_forward",
    "in_force",
    "marking_in",
    "may_mark",
    "narrowed",
    "pairs_of",
    "prompt_for",
    "seen_as",
    "set_open_as",
    "unassign_as",
]
