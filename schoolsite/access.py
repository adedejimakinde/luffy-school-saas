"""Who may do what to a school's website. `docs/school-sites.md` §2.4.

| | edit the draft, mark it ready | publish, roll back | theme, its options, delegation | read the log |
| --- | --- | --- | --- | --- |
| Principal | yes | yes | yes | yes |
| Administrator, delegated | yes | **no** | no | yes |
| Administrator, not delegated | no | no | no | yes |
| Anybody else | no | no | no | no |

Only the principal publishes (decided 24 October 2026: large schools guard their
brand). Every answer reads the roles the login holds **at this school**
(`User.roles_at()`, which leaves out an invited or suspended membership) and this
school's own delegation log, read afresh each time, so a role or a delegation at
one school is nothing at another, and a delegation ended is ended on the next
request. And every answer is no unless the connection is on this school's own
schema: the draft and the log read are the connection's.
"""

from django.db import connection

from accounts.models import Role

from .models import SiteDelegationEvent

PRINCIPAL = Role.PRINCIPAL.value
ADMIN = Role.ADMIN.value
#: Who may open the editor at all: the principal, and the administrator, who
#: reads the log and edits only while delegated. The menu's link is theirs.
READING_ROLES = frozenset({PRINCIPAL, ADMIN})


def _roles(actor, school) -> set:
    if not getattr(actor, "is_authenticated", False):
        return set()
    return set(actor.roles_at(school))


def here(school) -> bool:
    """Is the connection on this school's schema? Everything read and written is the connection's."""
    return school is not None and connection.schema_name == school.schema_name


def delegated(school) -> bool:
    """Has this school's principal let the administrator edit drafts, and not stopped? The latest row decides."""
    if not here(school):
        return False
    latest = SiteDelegationEvent.objects.order_by("-id").values_list("on", flat=True).first()
    return bool(latest)


def can_edit(actor, school) -> bool:
    """May this login change the draft and mark it ready? The principal, or a delegated administrator."""
    if not here(school):
        return False
    roles = _roles(actor, school)
    if PRINCIPAL in roles:
        return True
    return ADMIN in roles and delegated(school)


def can_publish(actor, school) -> bool:
    """May this login publish or roll back? The principal alone."""
    return here(school) and PRINCIPAL in _roles(actor, school)


def can_set_theme(actor, school) -> bool:
    """May this login change the theme, its options or the delegation? The principal alone."""
    return can_publish(actor, school)


def can_read_log(actor, school) -> bool:
    """May this login read the publish log? The principal and the administrator, delegated or not."""
    return here(school) and bool(_roles(actor, school) & READING_ROLES)


def role_of(actor, school) -> str:
    """The role a log row names this login by: the principal's if they hold it."""
    roles = _roles(actor, school)
    return PRINCIPAL if PRINCIPAL in roles else ADMIN if ADMIN in roles else ""


__all__ = [
    "READING_ROLES",
    "can_edit",
    "can_publish",
    "can_read_log",
    "can_set_theme",
    "delegated",
    "here",
    "role_of",
]
