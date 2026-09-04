"""Rendering a card off the request. Task 7.

A class of forty-five is enough rendering that no principal should be watching a
browser tab while it happens, so the render moves to a worker. The queue and its
two traps are `schools.tasks` and `docs/background.md`; this module is the first
real job on it.

## One card per job, which reverses what `docs/cards.md` expected

That file says a release renders "forty-five of these in one Celery job",
written before there was a job. Per card instead, for two reasons that both come
out of the queue's own settings: `acks_late` with
`task_reject_on_worker_lost` hands a killed worker's message to another worker,
and a per-class job would re-render forty-four finished cards to reach the one
that was lost; and `visibility_timeout` is 300 seconds, so a per-class job has
to finish inside it or be redelivered *alongside itself*. Per card, redelivery
costs one render and the timeout is never close.

## The job is idempotent, which is what lets it be redelivered

`settings.py` states the rule: with `acks_late` and
`task_reject_on_worker_lost`, a worker killed mid-render hands the message back
and some other worker runs it again — so a task that is not safe to run twice
has to say so. This one is safe, and not by luck. It renders a **frozen**
snapshot: every number comes from rows that refuse a second write, so two runs a
week apart produce the same card. The write is an upsert keyed on the card, so
the second run replaces the first's row rather than adding to it — and since
issue #56 that row usually exists before the job starts, `PENDING`, written by
`results.renders` inside the release. This job moves it to `BUILT` or, through
`on_failure`, to `FAILED`. It never writes `PENDING`: that word means "released
and not yet rendered", and a job that has run is past it either way.

## The failure handler is why `TenantTask` wraps handlers at all

`RenderACard.on_failure` records that a card did not render, in the school's own
`results_releasedcardpdf`. That handler is called by Celery's tracer *outside*
the body — outside the `with tenant_context(...)` block `__call__` opens — so
before `schools.tasks` wrapped the handlers a subclass brings, this write went
to `public` and raised a `ProgrammingError` naming a missing relation. The
failure of the failure handler is a bad place to find out.
"""

import logging

from celery import shared_task
from django.db import transaction

from schools.tasks import TenantTask

logger = logging.getLogger(__name__)


class RenderACard(TenantTask):
    """A card render, with its failure recorded where the school can read it."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Write the reason there is no file. Runs inside the school's schema.

        Wrapped by `TenantTask.__init_subclass__`, not by anything written here
        — see the module docstring. **This body is the first line that runs**,
        before any `super()` call, which is exactly the placement a base-class
        override could not have protected.

        Swallows its own exceptions. A failure handler that raises replaces the
        job's real error with its own in the worker log, and the real one is the
        one somebody needs.
        """
        try:
            card_id = _card_id_from(args, kwargs)
            if card_id is not None:
                _record_the_failure(card_id, exc)
        except Exception:  # noqa: BLE001 — see the docstring
            logger.exception("Could not record a failed card render.")
        super().on_failure(exc, task_id, args, kwargs, einfo)


@shared_task(base=RenderACard)
def render_card_pdf(schema_name, card_id):
    """Render one released card and store the file. Returns its size in bytes.

    The schema name is first and is passed through to the body as well as
    consumed by the base, so an operator watching a queue can see which school a
    job belongs to — `schools.tasks` makes that argument in full.

    Returns a size rather than the bytes: there is no result backend
    (`settings.py` says why it is off), so nothing reads a return value except
    the worker's own log, where "48213" is a useful line and a PDF is not.
    """
    from .models import PdfState, ReleasedCard, ReleasedCardPdf
    from . import pdf

    card = ReleasedCard.objects.get(pk=card_id)
    content = pdf.render(card)

    with transaction.atomic():
        # `update_or_create` rather than `create`, and the row it updates is
        # now the normal case rather than the redelivery case: `renders`
        # writes a `PENDING` marker for every card at release, so this job
        # almost always finds one waiting and moves it to `BUILT`. Every field
        # is written explicitly — a `state` left behind by a partial update is
        # a row claiming to owe a file it is holding, which the check
        # constraint refuses outright.
        ReleasedCardPdf.objects.update_or_create(
            card=card,
            defaults={
                "content": content,
                "byte_size": len(content),
                "error": "",
                "state": PdfState.BUILT,
            },
        )
    return len(content)


def _card_id_from(args, kwargs):
    """The card this job was for, however the caller passed it."""
    if "card_id" in kwargs:
        return kwargs["card_id"]
    if len(args) > 1:
        return args[1]
    return None


def _record_the_failure(card_id, exc):
    """One row saying this card has no file, and why.

    `update_or_create` rather than `create`: a card that rendered last week and
    fails today must end up saying it has no file now, not carrying a stale
    success beside a fresh failure. The constraint on the model refuses a row
    that claims both.

    The row it meets is usually the `PENDING` marker `results.renders` wrote at
    release, and moving that to `FAILED` is what takes the card out of the
    download route's enqueue path: a `FAILED` card is not asked for again by
    anybody reloading a page, because what it needs is a person reading `error`.
    """
    from .models import PdfState, ReleasedCardPdf

    with transaction.atomic():
        ReleasedCardPdf.objects.update_or_create(
            card_id=card_id,
            defaults={
                "content": None,
                "byte_size": None,
                "state": PdfState.FAILED,
                # No `or "unknown error"` fallback. The f-string always
                # carries at least "<TypeName>: ", so a fallback for an empty
                # `error` could never fire — it would read as protection
                # against tripping the file-or-a-reason constraint while
                # protecting nothing.
                "error": f"{type(exc).__name__}: {exc}"[:2000],
            },
        )


__all__ = ["render_card_pdf", "RenderACard"]
