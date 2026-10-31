"""The media queue's jobs: one upload each, on the `media` queue.

`settings.CELERY_TASK_ROUTES` sends everything here to the `media` queue, which
the `media` worker serves with one process at low priority (deploy/compose.yml):
a gallery of photos or a video never holds up a report card's PDF.

The body is `files.service.process`, which is idempotent: a redelivered job
finds its row no longer `pending` and does nothing. A failure inside it is
written on the row as a sentence for the person who uploaded, so the task
itself has nothing to retry.

The time limits sit under the broker's five-minute visibility timeout
(`settings.CELERY_BROKER_TRANSPORT_OPTIONS`): a job still running when that
expires would be handed to a second worker.
"""

from celery import shared_task
from django_tenants.utils import schema_context

from schools.tasks import TenantTask

LIMITS = {"soft_time_limit": 200, "time_limit": 240}


@shared_task(base=TenantTask, **LIMITS)
def process_upload(schema_name, key):
    """One school's upload. The schema comes first, as every school's job's does."""
    from . import service

    stored = service.process(schema_name, key)
    return stored.state if stored is not None else "superseded"


@shared_task(**LIMITS)
def process_platform_upload(key):
    """Classnode's own: the blog's pictures, kept in `public`."""
    from . import service

    with schema_context("public"):
        stored = service.process("public", key)
    return stored.state if stored is not None else "superseded"


__all__ = ["process_platform_upload", "process_upload"]
