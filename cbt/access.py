"""Who may do what in CBT, as far as Phase 2 step 2 goes. `docs/cbt.md`, "Who sees what".

One module so that every route and every service asks the same question, and the menu
reads the same role sets (`menu.py`). Each answer reads the roles the login holds **at
this school** (`User.roles_at()`) and, for an exam officer, this school's own
`ExamOfficerGrant` rows, so a role or a grant at one school is nothing at another.

| | exam slips | exam officers | banks and questions |
| --- | --- | --- | --- |
| Principal | prints, any class | names and ends | reads (step 3) |
| Administrator | prints, any class | sees who they are | **never**, named officer or not |
| Exam officer (a teacher, the vice principal or the administrator, named) | prints, any class | sees who they are | nothing beyond their own as a teacher |
| Vice principal, not named | no | no | reads (step 3) |
| Teacher, not named | no, whatever they are assigned | no | their own subjects and levels (step 3) |

A teacher's subject-teacher assignments (`gradebook.assignments`) give no slip rights:
slips are not a teacher's job in `docs/cbt.md`, and an exam officer prints for any class
in the school (decided 24 October 2026). Step 3 is where a teacher's assignments start
to decide what they see.
"""

from django.db import connection
from django.db.models import QuerySet

from accounts.models import Membership, Role

from .models import ExamOfficerGrant

#: Who prints exam slips by their role alone. An exam officer prints them too.
PRINTING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})

#: Who names and ends exam officers: the principal alone.
NAMING_ROLES = frozenset({Role.PRINCIPAL.value})

#: Whom the principal may name: a teacher, the vice principal or the administrator.
OFFICER_ROLES = frozenset(
    {Role.TEACHER.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)

#: Who will read question banks (step 3), each within their own reach there: the
#: principal and the vice principal all, a teacher their own. **Never the
#: administrator**, who runs sittings and not their content (decided 20 October 2026),
#: and being named exam officer does not change that.
BANK_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.TEACHER.value}
)


def _roles(actor, school) -> set:
    if not getattr(actor, "is_authenticated", False):
        return set()
    return set(actor.roles_at(school))


def _here(school) -> bool:
    """Is the connection on this school's schema? The grants read are the connection's."""
    return school is not None and connection.schema_name == school.schema_name


def officer_memberships(membership_ids) -> set:
    """Which of these memberships' latest grant, in this schema, names them an exam officer.

    `membership_ids` is a list or a query of ids. One statement either way: Postgres's
    DISTINCT ON keeps each membership's newest row, and a query is a subquery.
    """
    if isinstance(membership_ids, QuerySet):
        ids = membership_ids
    else:
        ids = list(membership_ids)
        if not ids:
            return set()
    latest = (
        ExamOfficerGrant.objects.filter(membership_id__in=ids)
        .order_by("membership_id", "-id")
        .distinct("membership_id")
        .values_list("membership_id", "kind")
    )
    return {mid for mid, kind in latest if kind == ExamOfficerGrant.Kind.NAMED}


def _officer_ids_of(actor, school):
    """The actor's memberships here that a grant could name and that can act now, as a query."""
    return (
        Membership.objects.with_access()
        .filter(user=actor, school=school, role__in=OFFICER_ROLES)
        .values("pk")
    )


def is_exam_officer(actor, school) -> bool:
    """Has the principal named one of this login's memberships here, and not ended it?

    A membership that is suspended or ended is no officer while it is so: `with_access()`
    leaves it out, as `roles_at()` does.
    """
    if not getattr(actor, "is_authenticated", False) or not _here(school):
        return False
    return bool(officer_memberships(_officer_ids_of(actor, school)))


def can_print(actor, school) -> bool:
    """May this login print exam slips here? The principal, the administrator, an exam officer."""
    if _roles(actor, school) & PRINTING_ROLES:
        return True
    return is_exam_officer(actor, school)


def can_name(actor, school) -> bool:
    """May this login name and end exam officers here? The principal alone."""
    return bool(_roles(actor, school) & NAMING_ROLES)


def can_read_banks(actor, school) -> bool:
    """Will this login read any question bank here? Never a login holding the administrator role.

    Asked from step 3, where the banks are; stated here so that step 2's own pages, and
    the test that the administrator has no way to banks or questions, read the rule from
    the one place it will live. Being named exam officer adds nothing.
    """
    roles = _roles(actor, school)
    if Role.ADMIN.value in roles:
        return False
    return bool(roles & BANK_ROLES)


def menu_keys(roles, actor, school) -> frozenset:
    """Links a login holds by a permission rather than a role: the exam slips page for an
    exam officer whose roles alone would not show it (`menu.py`).

    Asks the database only for a login that could be named and does not already print
    by role, so the principal, the administrator, a bursar and a parent cost nothing.
    """
    roles = set(roles)
    if not roles & OFFICER_ROLES or roles & PRINTING_ROLES:
        return frozenset()
    return frozenset({"exam-slips"}) if is_exam_officer(actor, school) else frozenset()


__all__ = [
    "BANK_ROLES",
    "NAMING_ROLES",
    "OFFICER_ROLES",
    "PRINTING_ROLES",
    "can_name",
    "can_print",
    "can_read_banks",
    "is_exam_officer",
    "menu_keys",
    "officer_memberships",
]
