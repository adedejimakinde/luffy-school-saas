"""Who asks for a card to be rendered, and what says one is still owed. Issue #56.

Task 7 built three things — a renderer (`results.pdf`), a job to run it off the
request (`results.tasks`) and a table to keep the file in (`ReleasedCardPdf`) —
and nothing called any of them. This module is the way in. `results.card_api`
is the way out.

## The marker is the artefact, and it is written before anything is rendered

`mark_and_enqueue()` writes a `PENDING` row for every card in the same
transaction that freezes the card, and only then, after the commit, asks for the
render. So a school's database says "this card owes a file" from the moment the
card exists, and *not having a file* stops being the same observation as *not
having been asked for*.

That ordering is the point. The enqueue can fail — a Redis that is down, a
worker that never comes back, a message lost between the two — and every one of
those failures now leaves a row saying which cards were affected, queryable by
anybody, instead of a silence that looks exactly like a term nobody has released
yet. `ReleasedCard` made the same argument about placements: the artefact is the
row, not the thing you can infer from other rows going missing.

## `transaction.on_commit`, and why a bare `.delay()` is a bug rather than a style

A worker is a different process on a different connection. A message published
before the release commits can be picked up immediately, and under READ
COMMITTED that worker sees no card — so it raises `DoesNotExist`, `on_failure`
writes a `FAILED` row saying the card does not exist, and the card is fine three
milliseconds later. The failure is indistinguishable from a real one and it is
permanent, because nothing retries a `FAILED` card.

## And the enqueue must not be able to fail the release

`on_commit` callbacks run *after* the commit, so an exception raised in one
reaches the caller with the release already durable: the principal gets a 500
for cards that have gone home. Every publish is therefore caught per card and
logged. `schools.logging.SchoolContextFilter` reads the connection, and the
callback runs on the school's connection, so the log line names the school
without this module passing it.

`retry=False` on the publish is part of the same argument. Celery's default is
to retry a publish three times with a sleep between, which on a dead broker
holds the request open for seconds per card — forty-five of them — to arrive at
the same place. Failing fast is right here precisely *because* the `PENDING` row
survives: the next GET on that card asks again.

## The schema name is read here, not in the callback

`connection.schema_name` is captured while the release is still on the school's
connection. By the time an `on_commit` callback runs, a pooled connection can be
anywhere — and the whole reason `schools.tasks.TenantTask` takes the schema as
its first argument is that a job may not guess. Reading it inside the callback
would reintroduce the guess at the one point that looks safe.
"""

import logging
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from .models import PdfState, ReleasedCardPdf
from .tasks import render_card_pdf

logger = logging.getLogger(__name__)

#: How long a card that has been queued is left alone before a download asks for
#: it again.
#:
#: The window exists because `PENDING` means both "queued a moment ago" and
#: "queued never" — `PdfState` says why there is no fourth state to tell them
#: apart — and the download route enqueues on `PENDING`. Without a window,
#: results week (every parent of a class at once, on the day the cards are
#: released) turns one release into a job per refresh per card, all of them
#: rendering the same forty-five cards the release already asked for.
#:
#: A minute is longer than a render, which task 7 measured at a few hundred
#: milliseconds a card, and short enough that a parent who reloads after reading
#: "still being prepared" is the thing that recovers a lost job.
RE_ENQUEUE_AFTER = timedelta(seconds=60)


def mark_and_enqueue(cards):
    """Write the `PENDING` marker for these cards, then queue a render for each.

    Called from inside the transaction that froze them — `services.release()`
    for a class, `revision.revise()` for one child — and it must stay inside it.
    The marker is part of the release: a release that commits without one has
    the hole this module exists to close, and the row and the card have to land
    or not land together.

    Takes cards rather than ids because the caller has them (a freeze returns
    them), and passes **ids** to the queue because the worker re-reads the card
    in its own transaction, which is what makes the job idempotent under
    `acks_late`. Handing a worker a prefetched card would also mean serialising
    one through JSON, which the broker's `task_serializer` will not do.

    One `INSERT` for the class rather than forty-five. No `update_or_create`
    here: these cards were frozen moments ago in this transaction, so a marker
    for one cannot already exist, and a get-or-create would be forty-five extra
    round trips to prove it.
    """
    cards = list(cards)
    if not cards:
        return []

    schema_name = connection.schema_name
    asked_at = timezone.now()
    ReleasedCardPdf.objects.bulk_create(
        [
            ReleasedCardPdf(
                card=card, state=PdfState.PENDING, last_enqueued_at=asked_at
            )
            for card in cards
        ]
    )

    card_ids = [card.pk for card in cards]
    transaction.on_commit(lambda: _enqueue_each(schema_name, card_ids))
    return card_ids


def marker_for(card):
    """The row saying where this card's file has got to, written if it is missing.

    Every path that makes a card writes its marker inside the same transaction —
    `services.release()` for a class, `revision.revise()` for one child — and
    migration `0022` gave one to every card released before those paths existed.
    So a card with no marker is not a state this design has. It is a fourth
    writer of `ReleasedCard` that did not read this module, or a row deleted by
    hand.

    Writing one here rather than raising keeps that bug off the family's screen:
    the card downloads one render later instead of not at all. `get_or_create`
    is what makes the repair safe when two parents ask at once — `card` is a
    `OneToOne`, so the second insert is an `IntegrityError` from Postgres, which
    `get_or_create` catches and turns back into a read.

    **The warning is not decoration and must not be tidied away.** A silent
    self-heal is the same shape as the hole issue #56 was filed about: the
    platform quietly covering for a missing row instead of leaving a line saying
    which card had none and when.
    """
    marker, written = ReleasedCardPdf.objects.get_or_create(card=card)
    if written:
        logger.warning(
            "Released card %s had no ReleasedCardPdf row and has been given one, "
            "PENDING. Something wrote a card without its marker.",
            card.pk,
        )
    return marker


def enqueue_if_pending(marker) -> bool:
    """Ask for this card again, unless it was asked for recently. Returns whether it did.

    The recovery path for a card whose release-time enqueue never reached the
    broker, driven by the person who actually wants the file. Only `PENDING`
    reaches the queue: a `BUILT` card has its file, and a `FAILED` one needs a
    person to read the reason — a download that re-queued it would be a retry
    loop driven by a parent hitting reload against a template that cannot
    render, which is the thing `RenderACard.on_failure` writes a row to stop.

    **The debounce is the conditional `UPDATE`, not the `if` above it.** Two
    requests arriving together both read `PENDING`, both find `last_enqueued_at`
    old enough, and both would enqueue. Postgres re-evaluates a `WHERE` clause
    against the newer row version when it unblocks, so exactly one of two
    concurrent `UPDATE`s here matches and the other reports zero rows — the
    check and the claim are one statement, and one job is queued. Doing it in
    Python around a read would be the same race with more code.

    **`on_commit` here is not the same promise it is in `mark_and_enqueue()`.**
    The caller is a GET, and this project sets no `ATOMIC_REQUESTS`, so the
    `UPDATE` above has already committed on its own and Django runs the callback
    at once rather than at some later commit. The ordering the release path
    needs — claim durable before job published — is what autocommit gives here
    for free, and the `on_commit` is what keeps it true if this is ever called
    from inside a transaction.
    """
    if marker.state != PdfState.PENDING:
        return False

    asked_at = timezone.now()
    claimed = (
        ReleasedCardPdf.objects.filter(pk=marker.pk, state=PdfState.PENDING)
        .filter(
            Q(last_enqueued_at__isnull=True)
            | Q(last_enqueued_at__lte=asked_at - RE_ENQUEUE_AFTER)
        )
        .update(last_enqueued_at=asked_at)
    )
    if not claimed:
        return False

    schema_name = connection.schema_name
    card_id = marker.card_id
    transaction.on_commit(lambda: _enqueue(schema_name, card_id))
    return True


def _enqueue_each(schema_name, card_ids):
    """One publish per card. One failing does not stop the rest being asked for."""
    for card_id in card_ids:
        _enqueue(schema_name, card_id)


def _enqueue(schema_name, card_id):
    """Publish one render job, and swallow whatever the broker does about it.

    The exception is logged rather than raised for the reason the module
    docstring gives: this runs after the commit, and the cards have gone home
    whatever Redis is doing. What makes the swallow defensible is that the
    `PENDING` row is still there afterwards, so the work is recorded as owed
    rather than lost.

    It deliberately does **not** clear `last_enqueued_at` on the way out. A card
    whose publish failed is left alone for `RE_ENQUEUE_AFTER` before a download
    asks for it again, which is a minute's delay on a path that only runs when
    the broker is down — against a write issued from a post-commit callback, on
    a connection that by then may be on any schema at all. A minute is the
    cheaper of the two.
    """
    try:
        render_card_pdf.apply_async(args=[schema_name, card_id], retry=False)
    except Exception:  # noqa: BLE001 — see the docstring
        logger.exception(
            "Could not queue a render for released card %s. The card is "
            "released and its file is still owed; the marker row records that.",
            card_id,
        )


__all__ = [
    "RE_ENQUEUE_AFTER",
    "mark_and_enqueue",
    "marker_for",
    "enqueue_if_pending",
]
