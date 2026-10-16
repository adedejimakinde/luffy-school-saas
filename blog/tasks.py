"""Sending a blog sign-in code: `messaging.codes`'s rules, for `blog.SignInCode`.

After the commit, off the request, sealed on the queue, and at most once (the
claim is `SignInCode.claimed_at`, taken with a conditional update). The words
are the platform's sign-in code message, and the provider is the one every
email code goes through. A publish that fails is logged and never fails the
page: the writer asks for another code.
"""

import logging

from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone

from messaging import kinds, providers
from messaging.kinds import Kind
from messaging.models import Outcome
from messaging.seal import open_sealed, seal

logger = logging.getLogger(__name__)


def deliver(code, raw_code):
    """Queue `raw_code` for its account's email once the minting transaction commits."""
    sealed = seal(raw_code)
    code_id = code.pk
    transaction.on_commit(lambda: _publish(code_id, sealed))


def _publish(code_id, sealed):
    try:
        send_sign_in_code.apply_async(args=[code_id, sealed], retry=False)
    except Exception:  # noqa: BLE001, see the module docstring
        logger.exception("Could not queue blog sign-in code %s", code_id)


@shared_task
def send_sign_in_code(code_id, sealed):
    from .models import SignInCode

    connection.set_schema_to_public()
    claimed = SignInCode.objects.filter(pk=code_id, claimed_at__isnull=True).update(
        claimed_at=timezone.now()
    )
    if not claimed:
        return None
    code = SignInCode.objects.select_related("user").get(pk=code_id)

    lifetime = int((code.expires_at - code.created_at).total_seconds())
    raw_code = open_sealed(sealed, ttl_seconds=lifetime)
    if raw_code is None or code.is_expired:
        return _record(code, Outcome.EXPIRED)

    params = {"code": raw_code, "minutes": max(1, round(lifetime / 60)), "school": ""}
    outbound = providers.Outbound(
        channel_type="email",
        address=code.user.email,
        kind=str(Kind.SIGN_IN_CODE),
        params=params,
        text=kinds.render(Kind.SIGN_IN_CODE, channel_type="email", **params),
        reference=f"blog-code-{code.pk}",
    )
    provider = providers.provider_for("email")
    try:
        provider.check_configured()
        provider.send(outbound)
    except providers.NotConfigured:
        logger.error("No email provider: blog code %s was not sent", code.pk)
        return _record(code, Outcome.NOT_CONFIGURED)
    except providers.Refused:
        return _record(code, Outcome.REFUSED)
    except providers.Unavailable:
        logger.exception("The email provider is unavailable: blog code %s", code.pk)
        return _record(code, Outcome.UNAVAILABLE)
    return _record(code, Outcome.ACCEPTED)


def _record(code, outcome):
    code.outcome = str(outcome)
    code.save(update_fields=["outcome"])
    return code.outcome
