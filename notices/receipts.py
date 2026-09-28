"""Payment receipts: written when the payment is, not pressed. `docs/messaging.md`.

Unlike a result notice or a fee reminder, nobody previews or presses this one.
`fees.services.record_payment()` calls `write_receipt()` itself, inside its own
transaction, the moment the entry exists — so a receipt and the money it is
about are one commit or neither.

**Email only.** A receipt reads like paperwork, not like the six-word text
`kinds.py` was built for, and it names its guardian's channel by `only={"email"}`
rather than taking the phone first the way D4's usual order does.

**No cap, and that is a deliberate departure from D7.** The daily segment
budget bounds the cost of a bursar's SMS campaign; a receipt is one email per
payment, and a school posting enough payments in a day to make that worth
bounding is not a school this line has met. Quiet hours still hold it: a
payment posted at nine at night is receipted at seven the next morning, same
as everything else `notices.hours` governs.

**No "balance changed" recheck.** A fee reminder states a balance that can
move before it sends; a receipt states a payment that already happened, and
that does not move. `notices.tasks.send_notice` sends it exactly as posted.
"""

from django.db import transaction
from django.utils import timezone

from messaging import kinds

from . import hours, recipients
from .models import Notice, NoticeKind
from .services import offered


def receipt_text(*, school_name, child_name, amount_kobo, receipt_number, method,
                  narration, effective_on, channel_type) -> str:
    """The whole text: the school, the receipt number, what was received, how, when."""
    by_method = f" by {method}" if method else ""
    return kinds.render(
        kinds.Kind.PAYMENT_RECEIPT,
        channel_type=channel_type,
        school=school_name,
        child=child_name,
        amount=kinds.naira(amount_kobo),
        receipt_number=receipt_number,
        by_method=by_method,
        date=effective_on.strftime("%d %B %Y"),
        narration=narration,
    )


def receipt_text_for(entry, *, school, channel_type) -> str:
    """`receipt_text()` from the ledger entry itself, as `notices.tasks` reads it."""
    from fees.authority import receipt_number

    return receipt_text(
        school_name=school.name,
        child_name=entry.student_name,
        amount_kobo=-entry.amount_kobo,
        receipt_number=receipt_number(school, entry.pk),
        method=entry.get_method_display() if entry.method else "",
        narration=entry.narration,
        effective_on=entry.effective_on,
        channel_type=channel_type,
    )


def _rows_for(entry, school, now):
    """What `write_receipt()` would insert at `now`, unsaved.

    Segments are always 1: every row here is `channel_type="email"` by
    construction (`only={"email"}` below), and email is never split the way an
    SMS is (`kinds.segments()`).
    """
    send_after = hours.send_after(now)
    reachable, _ = recipients.for_child(
        entry.student_membership_id, school, invoices_only=True, only={"email"}
    )
    return [
        Notice(
            kind=NoticeKind.PAYMENT_RECEIPT,
            source_entry=entry,
            student_membership_id=entry.student_membership_id,
            term_id=entry.term_id,
            guardian_user_id=guardian.pk,
            contact_id=contact.pk,
            channel_type=contact.channel_type,
            address=contact.value,
            segments=1,
            amount_kobo=-entry.amount_kobo,
            send_after=send_after,
            created_by_id=entry.recorded_by_id,
        )
        for guardian, contact in reachable
    ], send_after


@transaction.atomic
def write_receipt(entry, *, now=None):
    """Write a receipt notice for `entry`, to whoever receives this child's invoices.

    A no-op — returns `[]` — when this school has not turned receipts on, or
    when nobody who receives invoices has a live email. Called from inside
    `record_payment()`'s own transaction (`@transaction.atomic` nests as a
    savepoint), so the receipt and the payment are one commit or neither;
    queues the send for after that outer commit.
    """
    from results.services import school_on_this_connection

    if not offered().payment_receipts:
        return []
    school = school_on_this_connection()
    now = now or timezone.now()
    rows, send_after = _rows_for(entry, school, now)
    if not rows:
        return []
    written = Notice.objects.bulk_create(rows)
    if send_after <= now:
        from .tasks import queue

        ids = [row.pk for row in written]
        schema_name = school.schema_name
        transaction.on_commit(lambda: queue(schema_name, ids))
    return written


__all__ = ["receipt_text", "receipt_text_for", "write_receipt"]
