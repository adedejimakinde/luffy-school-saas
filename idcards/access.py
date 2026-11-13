"""Who may print ID cards, asked on the server on every request.

The principal, the vice principal (academic) and the administrator, for any
class, and nobody else: a class teacher, a subject teacher, a bursar, a parent
and a student are refused. Asked of `actor.roles_at(school)`, which is this
school's roles only, so being a principal at another school gives nothing here
(`idcards.tests.test_access` breaks this to prove it).

There is one rule and it is here. The page's button, the menu's link and every
route ask it; none of them keeps a copy.
"""

from accounts.models import Role

PRINTING_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)

MAY_NOT_PRINT = (
    "Student ID cards are printed by the principal, the vice principal (academic) "
    "and the school's administrator."
)


def may_print(actor, school) -> bool:
    """May `actor` print ID cards at `school`?"""
    if school is None or not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & PRINTING_ROLES)


__all__ = ["MAY_NOT_PRINT", "PRINTING_ROLES", "may_print"]
