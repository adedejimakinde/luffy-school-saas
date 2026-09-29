"""Paystack's webhook: trusted only after it has been checked twice, recorded once.

What arrives is a claim. It becomes money in a child's account only after, in
this order:

1. **The signature.** `x-paystack-signature` is the HMAC-SHA512 of the raw body
   under `PAYSTACK_WEBHOOK_SECRET`, compared in constant time. Nothing is parsed,
   looked up or written before it passes: a forged or unsigned request is a 401
   and that is all it costs. No secret configured is also a refusal.
2. **Paystack itself.** `GET /transaction/verify/:reference` must say the same
   transaction succeeded, for the same reference, the same amount in kobo and NGN.
   Everything after this reads the **verified** record, never the webhook's own
   words. Paystack unreachable is a 503, so Paystack sends it again; a
   transaction that does not verify is a 200 that records nothing.
3. **The account.** The account number Paystack says was paid into is looked up
   in `schools.PaystackRoute` (which school), then in that school's
   `VirtualAccount` (which child), and Paystack's customer code must be the one
   that account was made for. Any step that does not match is **not guessed**:
   the money is listed as an `UnmatchedPayment` for the bursar (or an
   `UnroutedPayment` for the platform, when no school owns the number).
4. **Once per reference.** `record_payment_once()` with a form key derived from
   Paystack's reference, so the same webhook twice, or two racing, is one ledger
   entry: the unique index is the mechanism, not a read. An already-listed
   unmatched reference stays listed and is never recorded on a replay.

Amounts are integer kobo throughout; an amount that is not a positive integer is
ignored. Only `charge.success` is acted on.
"""

import hashlib
import hmac
import json
import logging
import uuid

from django.conf import settings
from django.db import transaction
from django_tenants.utils import schema_context

from accounts.models import Membership, Role
from academics.models import Term
from schools.models import PaystackRoute, UnroutedPayment

from . import paystack, services
from .models import PaymentMethod, UnmatchedPayment, UnmatchedReason, VirtualAccount

logger = logging.getLogger(__name__)

#: Form keys for Paystack references live in their own namespace, so the key for
#: one reference is the same on every delivery and never collides with a form's.
_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # NAMESPACE_URL


def form_key_for(reference):
    return uuid.uuid5(_NAMESPACE, f"paystack:{reference}")


def signature_ok(raw, header):
    secret = getattr(settings, "PAYSTACK_WEBHOOK_SECRET", "") or ""
    if not secret or not header:
        return False
    digest = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    return hmac.compare_digest(digest, header.strip().lower())


def _ignored(why):
    return 200, {"status": "ignored", "why": why}


def handle(raw, signature):
    """`(http_status, body)` for one delivery. See the module docstring."""
    if not signature_ok(raw, signature):
        return 401, {"detail": "Bad signature."}
    try:
        event = json.loads(raw)
    except ValueError:
        return 400, {"detail": "Not JSON."}
    if not isinstance(event, dict) or event.get("event") != "charge.success":
        return _ignored("not a charge.success")
    data = event.get("data")
    if not isinstance(data, dict):
        return _ignored("no data")
    reference, amount = data.get("reference"), data.get("amount")
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 64:
        return _ignored("no usable reference")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        return _ignored("amount is not a positive whole number of kobo")

    try:
        verified = paystack.verify_transaction(reference)
    except paystack.PaystackRefused:
        logger.warning("Paystack has no transaction %s", reference)
        return _ignored("Paystack does not know that transaction")
    except (paystack.PaystackUnavailable, paystack.PaystackNotConfigured) as exc:
        logger.warning("Could not verify %s: %s", reference, type(exc).__name__)
        return 503, {"detail": "Could not verify with Paystack; try again."}

    v_amount = verified.get("amount")
    if not (
        verified.get("status") == "success"
        and verified.get("reference") == reference
        and isinstance(v_amount, int)
        and not isinstance(v_amount, bool)
        and v_amount == amount
        and verified.get("currency") == "NGN"
    ):
        logger.warning("Paystack did not confirm %s as sent", reference)
        return _ignored("Paystack does not confirm it")

    authorization = verified.get("authorization") if isinstance(verified.get("authorization"), dict) else {}
    customer = verified.get("customer") if isinstance(verified.get("customer"), dict) else {}
    account_number = str(authorization.get("receiver_bank_account_number") or "")
    customer_code = str(customer.get("customer_code") or "")

    route = PaystackRoute.objects.select_related("school").filter(account_number=account_number).first()
    if route is None:
        UnroutedPayment.objects.get_or_create(
            reference=reference, defaults={"amount_kobo": v_amount, "account_number": account_number}
        )
        return 200, {"status": "unrouted"}

    with schema_context(route.school.schema_name):
        return 200, {"status": _record(route.school, reference, v_amount, account_number, customer_code)}


def _unmatched(reference, amount, account_number, customer_code, reason):
    UnmatchedPayment.objects.get_or_create(
        reference=reference,
        defaults={
            "amount_kobo": amount,
            "account_number": account_number,
            "customer_code": customer_code,
            "reason": reason,
        },
    )
    return "unmatched"


def _record(school, reference, amount, account_number, customer_code):
    """In the school's own schema: place the money on one child, or list it."""
    with transaction.atomic():
        if UnmatchedPayment.objects.filter(reference=reference).exists():
            return "unmatched"  # already listed: a person decides, not a replay
        account = VirtualAccount.objects.filter(account_number=account_number).first()
        if account is None:
            return _unmatched(reference, amount, account_number, customer_code, UnmatchedReason.NO_ACCOUNT)
        if customer_code != account.customer_code:
            return _unmatched(reference, amount, account_number, customer_code, UnmatchedReason.WRONG_CUSTOMER)
        child = Membership.objects.filter(
            pk=account.student_membership_id, school=school, role=Role.STUDENT
        ).first()
        if child is None:
            return _unmatched(reference, amount, account_number, customer_code, UnmatchedReason.NOT_A_STUDENT)
        term = Term.objects.filter(is_current=True).first()
        if term is None:
            return _unmatched(reference, amount, account_number, customer_code, UnmatchedReason.NO_CURRENT_TERM)
        try:
            _, posted = services.record_payment_once(
                child,
                term,
                amount,
                method=PaymentMethod.BANK_TRANSFER,
                form_key=form_key_for(reference),
                reference=reference,
                narration="Paid online through Paystack",
            )
        except services.FormAlreadyUsed:
            # The same reference, a different payment: Paystack's references are
            # unique, so this is not something to record either way.
            logger.error("Paystack reference %s was already recorded as a different payment", reference)
            return "conflict"
    return "recorded" if posted else "duplicate"
