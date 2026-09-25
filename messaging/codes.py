"""Sending the codes `accounts.guardian_contacts` mints. `docs/messaging.md` D5, D6, D8.

**After the commit.** A door mints a code inside its transaction and calls
`deliver_code()`, which registers the send on commit, for `results.renders`'s
reason: a worker is another connection, and a message published before the
commit can be picked up before the code row exists.

**Off the request.** The provider is never called on the request that asked for
the code. A provider call takes hundreds of milliseconds and happens only for a
number on a guardian record, so on the request it would make response time say
which numbers are guardians: the oracle `accounts/guardian_signin.py` is built to
refuse. The send is queued, and the request answers without waiting.

**Sealed on the queue** (`seal.py`), and **at most once** (`CodeDelivery`): the
task claims the code before it calls the provider, and a second run finds the
claim and does nothing.

**The publish cannot fail the door.** It runs after the commit, so an exception
here would reach a guardian or an admin as a 500 for a code that exists. It is
caught and logged, and the code row stays: a guardian asks again, an admin sends
again.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from . import kinds, providers
from .models import CodeDelivery, CodeDeliveryOutcome, Outcome
from .seal import open_sealed, seal

logger = logging.getLogger(__name__)


def deliver_code(code, raw_code, kind):
    """Queue `raw_code` for sending once the minting transaction commits.

    Called by each door in `accounts.guardian_contacts`, inside its transaction,
    with the `(code, raw_code)` `_mint_code()` returned.
    """
    sealed = seal(raw_code)
    code_id = code.pk
    transaction.on_commit(lambda: _publish(code_id, str(kind), sealed))


def _publish(code_id, kind, sealed):
    try:
        send_code.apply_async(args=[code_id, kind, sealed], retry=False)
    except Exception:  # noqa: BLE001 — see the module docstring
        logger.exception("Could not queue the delivery of code %s", code_id)


@shared_task
def send_code(code_id, kind, sealed):
    """Claim the code, send it, and write down what the provider said.

    A platform task, not a `TenantTask`: every row it touches is shared. It
    still says so to the connection, because a worker reuses its connection
    between jobs and the last one may have left it on a school's schema.
    """
    from accounts.models import GuardianContactCode

    connection.set_schema_to_public()
    code = (
        GuardianContactCode.objects.select_related("contact", "requested_by_school")
        .filter(pk=code_id)
        .first()
    )
    if code is None:
        return None

    delivery = _claim(code, kind)
    if delivery is None:
        return None

    lifetime = int((code.expires_at - code.created_at).total_seconds())
    raw_code = open_sealed(sealed, ttl_seconds=lifetime)
    if raw_code is None or code.is_expired:
        return _record(delivery, Outcome.EXPIRED)

    contact = code.contact
    school = code.requested_by_school
    minutes = max(1, round(lifetime / 60))
    params = {"code": raw_code, "minutes": minutes, "school": school.name if school else ""}
    outbound = providers.Outbound(
        channel_type=contact.channel_type,
        address=contact.value,
        kind=kind,
        params=params,
        text=kinds.render(kind, channel_type=contact.channel_type, **params),
        reference=f"code-{code.pk}",
    )
    provider = providers.provider_for(contact.channel_type)
    try:
        provider.check_configured()
        accepted = provider.send(outbound)
    except providers.NotConfigured:
        logger.error("No %s provider: code %s was not sent", contact.channel_type, code.pk)
        return _record(delivery, Outcome.NOT_CONFIGURED)
    except providers.Refused:
        return _record(delivery, Outcome.REFUSED)
    except providers.Unavailable:
        logger.exception("The %s provider is unavailable: code %s", contact.channel_type, code.pk)
        return _record(delivery, Outcome.UNAVAILABLE)
    return _record(delivery, Outcome.ACCEPTED, provider_ref=accepted.provider_ref or "")


def _claim(code, kind):
    """The claim row, or None if this code has been claimed already (at most once)."""
    try:
        with transaction.atomic():
            return CodeDelivery.objects.create(
                code=code, kind=kind, channel_type=code.contact.channel_type
            )
    except IntegrityError:
        return None


def _record(delivery, outcome, *, provider_ref=""):
    return CodeDeliveryOutcome.objects.create(
        delivery=delivery, outcome=outcome, provider_ref=provider_ref
    )


# -- what a school's office is shown ----------------------------------------

#: What each outcome is called on the guardians panel, and a claim with none.
SAID = {
    Outcome.ACCEPTED: "sent",
    Outcome.REFUSED: "could not be delivered to this contact",
    Outcome.UNAVAILABLE: "not sent: messages are not going out just now",
    Outcome.NOT_CONFIGURED: "not sent: this platform cannot send messages yet",
    Outcome.EXPIRED: "not sent in time",
}
NOT_KNOWN = "not known whether it arrived"
QUEUED = "waiting to be sent"


def last_message(contact, school_id):
    """What happened to the last code **this school** sent to `contact`, or "".

    In the office's words: `QUEUED` for a code no worker has claimed yet,
    `NOT_KNOWN` for a claim with no outcome (D5: a worker died between the two),
    and otherwise the outcome. A code sent more than a day ago is old news and
    says nothing.

    **Only this school's codes.** A guardian's own sign-in codes, and another
    school's sends, are not this school's to read: the first is when a parent
    signs in, the second is who else they are a parent at (#135).
    """
    from accounts.models import GuardianContactCode

    code = (
        GuardianContactCode.objects.filter(
            contact=contact,
            requested_by_school_id=school_id,
            created_at__gte=timezone.now() - timedelta(days=1),
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if code is None:
        return ""
    delivery = CodeDelivery.objects.filter(code=code).first()
    if delivery is None:
        return QUEUED
    outcome = CodeDeliveryOutcome.objects.filter(delivery=delivery).first()
    if outcome is None:
        return NOT_KNOWN
    return SAID[outcome.outcome]
