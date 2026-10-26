"""Writing to, and reading, a school's setup log (`audit.models.Change`).

`record()` is called by the service that made the change, **inside its
transaction**, so a change that rolls back takes its log row with it and a
change that commits cannot lose one. It writes in the school's own schema
whichever connection it was called on.
"""

from django.db import connection
from django_tenants.utils import schema_context

from .models import Change


def name_of(user) -> str:
    return (getattr(user, "full_name", "") or getattr(user, "username", "") or "Somebody").strip()


def _write(school, row: Change) -> Change:
    if connection.schema_name == school.schema_name:
        row.save()
        return row
    with schema_context(school.schema_name):
        row.save()
    return row


def record(actor, school, *, action, kind, summary, item=None, item_name="", before=None, after=None) -> Change:
    """Write down one change to `school`'s setup, by `actor`, now.

    `item` is the row changed, when there is one; its id and its name as it
    is now are copied unless `item_name` says otherwise.
    """
    roles = sorted(actor.roles_at(school)) if hasattr(actor, "roles_at") else []
    return _write(school, Change(
        by_id=actor.pk,
        by_name=name_of(actor)[:255],
        by_roles=",".join(roles)[:100],
        action=action,
        kind=kind,
        item_id=getattr(item, "pk", None),
        item_name=(item_name or (str(item) if item is not None else ""))[:255],
        summary=summary[:500],
        before=before,
        after=after,
    ))


def recent(limit=10):
    """The latest changes, newest first, on the connection's own schema."""
    return list(Change.objects.order_by("-at", "-id")[:limit])


__all__ = ["name_of", "recent", "record"]
