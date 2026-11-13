"""The ID card print, off the request. `idcards.printing` holds the rules.

One job for the class, as `results.tasks.build_class_cards` is: what is kept is
one file of every card, and it is made once. The job writes a heartbeat after
every sheet, so a second worker handed the same message after the broker's
visibility timeout finds it fresh and does nothing (`printing.claim`), and a job
whose worker died is taken over once its heartbeat is stale. Re-rendering a
class costs a minute; nothing is lost, because nothing here is a record: the
QR codes are the same on a second run (`cards.issue()` reuses the row).
"""

import logging

from celery import shared_task

from schools.tasks import TenantTask

logger = logging.getLogger(__name__)


class BuildIdCards(TenantTask):
    """A class's ID cards as one file, its failure on the row."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Say on the job that it failed, so the page stops showing progress.

        Wrapped by `TenantTask.__init_subclass__` to run inside the school's
        schema, and swallows its own exceptions: a failure handler that raises
        replaces the job's real error in the worker log with its own.
        """
        try:
            job_id = kwargs.get("job_id", args[1] if len(args) > 1 else None)
            if job_id is not None:
                from . import printing

                printing.record_failure(job_id, exc)
        except Exception:  # noqa: BLE001 — see the docstring
            logger.exception("Could not record a failed ID card print.")
        super().on_failure(exc, task_id, args, kwargs, einfo)


@shared_task(base=BuildIdCards)
def build_id_cards(schema_name, job_id):
    """Make one "Print ID cards" file. Returns how many cards are in it."""
    from . import printing

    job = printing.build(job_id)
    return job.card_count if job is not None else None


__all__ = ["BuildIdCards", "build_id_cards"]
