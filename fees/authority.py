"""Who may read a school's books, and who may write to them.

Decided 2026-09-24 (fees 1(a) and 2(a)): the **bursar and the administrator**
write — payments, discounts and reversals, each discount and reversal with its
reason — and the **principal and the vice principal (academic)** read. A
teacher, a parent and a student get the flat 404 every route here answers
with, so the books are not an existence oracle for anybody signed in at the
school.

Access-scoped through `roles_at()`, so an invited or suspended bursar holds no
authority. Platform staff are not admitted: a school's books are the school's
own, and `recorded_by_id` would name a platform operator on the row.
"""

from accounts.models import Role

WRITING_ROLES = frozenset({Role.BURSAR.value, Role.ADMIN.value})
READING_ROLES = WRITING_ROLES | {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value}


def may_read(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & READING_ROLES)


def may_write(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & WRITING_ROLES)


def receipt_number(school, entry_id) -> str:
    """Decided 2026-09-24 (fees 5): the ledger entry numbers the receipt — the
    school's code and the entry's id — rather than a counter of its own. A
    second counter would be a second sequence to keep in step with the first,
    and a gap in either would be a question nobody could answer."""
    return f"{school.slug.upper()}-{entry_id:06d}"


__all__ = ["READING_ROLES", "WRITING_ROLES", "may_read", "may_write", "receipt_number"]
