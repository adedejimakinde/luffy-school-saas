"""Sending a notice, once, and releasing the held ones at 07:00. D5, D7.

`send_notice` is a `TenantTask`: a notice lives in its school's schema. It
claims the notice, with the text as it will go, before it calls the provider,
and a second run finds the claim and does nothing (D5). It asks D4 again first,
because a notice held overnight can outlive the guardian's standing at the school
or the channel's.

`release_held()` is what 07:00 runs: every school's notices whose time has come
and that nobody has claimed, queued. **It is a management command on the
server's cron, not `celery beat`**: the platform already has a scheduler,
`deploy/cron/classnode`, and `docs/background.md` argued against adding a second
process with its own failure modes. Running it twice is safe, because every send
is claimed.
"""

import logging

from celery import shared_task
from django.db import IntegrityError, transaction
from django.utils import timezone

from messaging import providers
from schools.tasks import TenantTask

from . import hours, recipients
from .models import Notice, NoticeClaim, NoticeKind, NoticeOutcome

logger = logging.getLogger(__name__)
Said = NoticeOutcome.Said


def queue(schema_name, notice_ids):
    """Publish one send per notice. Called after the commit; a broker failure is logged."""
    for notice_id in notice_ids:
        try:
            send_notice.apply_async(args=[schema_name, notice_id], retry=False)
        except Exception:  # noqa: BLE001 — the notices stay unclaimed; 07:00's sweep asks again
            logger.exception("Could not queue notice %s", notice_id)


@shared_task(base=TenantTask)
def send_notice(schema_name, notice_id):
    """Claim, then send. Idempotent: a second run finds the claim."""
    from results.services import school_on_this_connection
    from results.withholding import is_withheld

    notice = Notice.objects.select_related("card").filter(pk=notice_id).first()
    now = timezone.now()
    if notice is None or notice.send_after > now:
        return None
    if hours.send_after(now) > now:
        # D7 at the moment of sending, not only of asking: a job that reaches
        # a worker after 20:00, behind a slow queue, stays unclaimed, and the
        # 07:00 sweep sends it.
        return None
    school = school_on_this_connection()

    reachable = recipients.still_reachable(notice, school)
    if notice.kind == NoticeKind.RESULT_NOTICE:
        from accounts.models import GuardianContact

        from .services import result_message

        contact = GuardianContact.objects.filter(pk=notice.contact_id).first()
        held = is_withheld(notice.student_membership_id, notice.term)
        message_kind, text = (
            result_message(notice.card, contact, held=held) if contact else ("", "")
        )
    else:  # pragma: no cover — fee reminders are M3's
        return None

    claim = _claim(notice, message_kind, text if reachable else "")
    if claim is None:
        return None
    if not reachable:
        return _record(claim, Said.NO_LONGER_REACHABLE)

    outbound = providers.Outbound(
        channel_type=notice.channel_type,
        address=notice.address,
        kind=message_kind,
        params={},
        text=text,
        reference=f"notice-{schema_name}-{notice.pk}",
    )
    provider = providers.provider_for(notice.channel_type)
    try:
        provider.check_configured()
        accepted = provider.send(outbound)
    except providers.NotConfigured:
        logger.error("No %s provider: notice %s was not sent", notice.channel_type, notice.pk)
        return _record(claim, Said.NOT_CONFIGURED)
    except providers.Refused:
        return _record(claim, Said.REFUSED)
    except providers.Unavailable:
        logger.exception("The %s provider is unavailable: notice %s", notice.channel_type, notice.pk)
        return _record(claim, Said.UNAVAILABLE)
    return _record(claim, Said.ACCEPTED, provider_ref=accepted.provider_ref or "")


def _claim(notice, message_kind, text):
    try:
        with transaction.atomic():
            return NoticeClaim.objects.create(notice=notice, message_kind=message_kind, text=text)
    except IntegrityError:
        return None


def _record(claim, said, *, provider_ref=""):
    return NoticeOutcome.objects.create(claim=claim, said=said, provider_ref=provider_ref)


def release_held(now=None) -> int:
    """Queue every school's due, unclaimed notices. Returns how many were queued."""
    from django_tenants.utils import get_public_schema_name, tenant_context

    from schools.models import School

    now = now or timezone.now()
    queued = 0
    for school in School.objects.exclude(schema_name=get_public_schema_name()):
        with tenant_context(school):
            ids = list(
                Notice.objects.filter(send_after__lte=now, claim__isnull=True).values_list(
                    "pk", flat=True
                )
            )
        if ids:
            queue(school.schema_name, ids)
            queued += len(ids)
    return queued
