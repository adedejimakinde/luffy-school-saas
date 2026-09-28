"""Absence alerts: written when the register is, not pressed. `docs/messaging.md` D14.

The third kind with no button, and the same shape as `notices.receipts`:
`attendance.services.take_register()` calls `write_alerts()` itself, inside its
own transaction, with every child the submission says is absent.

**At most one alert per register per child, ever.** A register can be amended
— a child corrected from absent to present and back, on the same calendar day
— and re-alerting on every round trip would be noise for a fact that has not
changed: the child was, and still is, marked absent in this register. Dedup is
a "told" set read before writing, the same idiom `notices.services.tell_families()`
uses for a card, rather than a return value threaded up from `_write_marks()`:
simpler, and it also covers a plain resubmission for free.

**Every live guardian, not only those who receive invoices.** D10's
`invoices_only` gate is a fees question; an absence is not.

**Email only**, for the reason a receipt is (D13): this reads like a note home,
not the six-word text `kinds.py` was built for.

**No cap, and quiet hours still hold it** — both for D13's reasons, read here
for a register instead of a ledger entry.
"""

from django.db import transaction
from django.utils import timezone

from messaging import kinds

from . import hours, recipients
from .models import Notice, NoticeKind
from .reminders import child_name
from .services import offered


def alert_text(*, school_name, child, class_name, taken_on, channel_type) -> str:
    """The whole text: the school, the child, the class, the day."""
    return kinds.render(
        kinds.Kind.ABSENCE_ALERT,
        channel_type=channel_type,
        school=school_name,
        child=child,
        class_name=class_name,
        date=taken_on.strftime("%A %d %B %Y"),
    )


def alert_text_for(notice, *, school) -> str:
    """`alert_text()` from the register and the notice itself, as `notices.tasks` reads it."""
    register = notice.source_register
    return alert_text(
        school_name=school.name,
        child=child_name(notice.student_membership_id),
        class_name=str(register.class_group),
        taken_on=register.taken_on,
        channel_type=notice.channel_type,
    )


def _rows_for(register, student_ids, school, now):
    """What `write_alerts()` would insert at `now`, unsaved. Segments always 1 — see `receipts`.

    Skips a `(child, contact)` this register has already told — the fold
    `_batch()` in `notices.services` takes over `Notice`, read here instead of
    left to the unique constraint, so a resubmission asks the reachable
    guardians again (D4) without the database refusing the row it would write
    for the ones already told.
    """
    told = set(
        Notice.objects.filter(
            source_register=register, student_membership_id__in=student_ids
        ).values_list("student_membership_id", "contact_id")
    )
    send_after = hours.send_after(now)
    rows = []
    for student_id in student_ids:
        reachable, _ = recipients.for_child(student_id, school, only={"email"})
        for guardian, contact in reachable:
            if (student_id, contact.pk) in told:
                continue
            rows.append(
                Notice(
                    kind=NoticeKind.ABSENCE_ALERT,
                    source_register=register,
                    student_membership_id=student_id,
                    term_id=register.term_id,
                    guardian_user_id=guardian.pk,
                    contact_id=contact.pk,
                    channel_type=contact.channel_type,
                    address=contact.value,
                    segments=1,
                    send_after=send_after,
                    created_by_id=register.taken_by_id,
                )
            )
    return rows, send_after


@transaction.atomic
def write_alerts(register, student_ids, *, now=None):
    """Write an absence alert for each of `student_ids`, to every live guardian.

    `student_ids` is every child this submission says is absent — a no-op when
    this school has not turned alerts on, when nobody in `student_ids` has a
    reachable email, or when every one of them was already told about this
    same register. Called from inside `take_register()`'s own transaction, so
    the marks and their alerts are one commit or neither; queues the send for
    after that outer commit.
    """
    from results.services import school_on_this_connection

    if not student_ids or not offered().absence_alerts:
        return []
    school = school_on_this_connection()
    now = now or timezone.now()
    rows, send_after = _rows_for(register, student_ids, school, now)
    if not rows:
        return []
    written = Notice.objects.bulk_create(rows)
    if send_after <= now:
        from .tasks import queue

        ids = [row.pk for row in written]
        schema_name = school.schema_name
        transaction.on_commit(lambda: queue(schema_name, ids))
    return written


__all__ = ["alert_text", "alert_text_for", "write_alerts"]
