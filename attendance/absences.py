"""The principal's list: children absent too often this term.

Decided 2026-09-24 (docs/attendance.md, OPEN-2):

- **Measured against days marked, not days declared.** A child is on the list
  when `absent / (present + absent)` is at least the school's threshold. A day
  with no register counts for nothing — A4 — so a school that missed Tuesday's
  register does not make thirty children look absent, and a declared
  `school_days` the school never set does not make every child look present.
- **Only past a floor of marked days**, so a child marked twice and absent once
  is not 50% absent.
- **The threshold is the school's** (`AbsenceSettings`, 10% and 10 days by
  default).
- **Principal, vice principal (academic) and administrator** see it — the whole
  school. A class teacher's own-class view waits on #125.

One read of the term's placements and one aggregate of its marks
(`summary.for_term()`), whatever the size of the school: nothing here is per
child. Compared in integers — `absent * 100 >= threshold * marked` — so a rate
on the boundary cannot be rounded either way.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from academics.models import ClassPlacement
from accounts.models import Membership, Role

from . import summary
from .models import AbsenceSettings, Register

#: Who may read the list. The whole school's attendance, by name.
VIEWING_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)

#: Who may change what "too often" means at this school.
EDITING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})


@dataclass(frozen=True)
class Flagged:
    student_membership_id: int
    student: str
    class_group: str
    absent: int
    marked: int

    @property
    def rate(self) -> Decimal:
        """Percent absent of days marked, to one place, for display only."""
        return (Decimal(self.absent * 100) / Decimal(self.marked)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )


def may_see(actor, school) -> bool:
    """Access-scoped like every authority question here: `roles_at()` counts
    only memberships that grant access, so an invited or suspended principal
    sees nothing. Platform staff are not admitted — a list of children by name
    is the school's own."""
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & VIEWING_ROLES)


def may_change_threshold(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & EDITING_ROLES)


def is_too_often(counts, settings) -> bool:
    if counts.marked < settings.min_marked_days:
        return False
    return counts.absent * 100 >= settings.threshold_percent * counts.marked


def flagged(school, term, settings=None) -> list[Flagged]:
    """Every child placed this term who is at or over the threshold, worst first."""
    settings = settings or AbsenceSettings.load()
    placements = list(
        ClassPlacement.objects.filter(term=term).select_related("class_group")
    )
    counts = summary.for_term(term, [p.student_membership_id for p in placements])
    over = [p for p in placements if is_too_often(counts[p.student_membership_id], settings)]

    # Names scoped to this school and to STUDENT in the lookup itself, as the
    # register's are: a placement row is a bare id into the shared table.
    names = {
        row["pk"]: row["display_name"] or row["user__full_name"] or ""
        for row in Membership.objects.filter(
            school=school,
            role=Role.STUDENT.value,
            pk__in=[p.student_membership_id for p in over],
        ).values("pk", "display_name", "user__full_name")
    }
    rows = [
        Flagged(
            student_membership_id=p.student_membership_id,
            student=names.get(p.student_membership_id, ""),
            class_group=str(p.class_group),
            absent=counts[p.student_membership_id].absent,
            marked=counts[p.student_membership_id].marked,
        )
        for p in over
    ]
    return sorted(rows, key=lambda r: (-r.rate, -r.absent, r.student))


def registers_taken(term) -> int:
    """How many registers this term has, so "nobody is on the list" and "nobody
    has taken a register" are two different sentences on the screen."""
    return Register.objects.for_term(term).count()


__all__ = [
    "EDITING_ROLES",
    "Flagged",
    "VIEWING_ROLES",
    "flagged",
    "is_too_often",
    "may_change_threshold",
    "may_see",
    "registers_taken",
]
