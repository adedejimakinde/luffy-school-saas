"""A bursar puts an unmatched payment on a child.

An unmatched payment is money Paystack confirmed that the books could not place
(`fees.webhook`). Placing it is a person's decision, and this is the only way it
happens. Four things hold it together:

- **It posts through `record_payment_once()` with the Paystack reference**, the
  same derived form key the webhook uses (`webhook.form_key_for()`), so the money
  is in the ledger at most once whichever of the two got there, and the second
  attempt is refused rather than posted. If the ledger already holds that key the
  money is already in somebody's account, and nothing is created.
- **Nothing the page says decides the money.** The person picks the child and
  *confirms* the amount and the reference; the server checks both against its own
  record of the payment and posts **its** amount. A stale page, or a payment that
  has changed under it, is refused with a sentence.
- **Once, at the database.** `UnmatchedPlacement` is one-to-one with the payment
  and with the entry it made. Placing the same payment on the same child again is
  the placement that is there (200); on another child, a refusal that says where
  it went. The payment row is locked, so two people pressing at once place it once.
- **It records who.** The entry's `recorded_by` is the person, and so is the
  placement row, frozen as a name; the entry's receipt goes out as any payment's does.

It posts to the school's **current term**: with none, it says so and posts nothing.
"""

from django.db import transaction

from academics.models import Term

from . import services, webhook
from .models import PaymentMethod, UnmatchedPayment, UnmatchedPlacement


class PlacementError(Exception):
    """This placement was refused, with a sentence for the person. Nothing was written."""


class NotFound(PlacementError):
    pass


class AlreadyPlaced(PlacementError):
    pass


class NotWhatYouConfirmed(PlacementError):
    pass


class AlreadyInTheLedger(PlacementError):
    pass


class NoCurrentTerm(PlacementError):
    pass


def place(actor, *, payment_id, child, amount_kobo, reference):
    """`(placement, created)`: put unmatched payment `payment_id` on `child`.

    `child` is a STUDENT membership of this school. `amount_kobo` and `reference`
    are what the person confirmed. `created` is False when this payment had
    already been placed on this same child (nothing more was done).
    """
    with transaction.atomic():
        payment = UnmatchedPayment.objects.select_for_update().filter(pk=payment_id).first()
        if payment is None:
            raise NotFound("There is no such payment.")

        earlier = UnmatchedPlacement.objects.filter(payment=payment).first()
        if earlier is not None:
            if earlier.student_membership_id == child.pk:
                return earlier, False
            raise AlreadyPlaced(
                f"This payment was already placed on {earlier.student_name} by {earlier.placed_by_name}."
            )

        if (
            isinstance(amount_kobo, bool)
            or amount_kobo != payment.amount_kobo
            or reference != payment.reference
        ):
            raise NotWhatYouConfirmed(
                "The amount or reference you confirmed is not what this payment says now. "
                "Reload the page and check it again."
            )

        term = Term.objects.filter(is_current=True).first()
        if term is None:
            raise NoCurrentTerm("The school has no current term to record this in. Open one first.")

        name = actor.get_full_name() or str(actor)
        try:
            entry, posted = services.record_payment_once(
                child,
                term,
                payment.amount_kobo,
                method=PaymentMethod.BANK_TRANSFER,
                form_key=webhook.form_key_for(payment.reference),
                reference=payment.reference,
                recorded_by=actor,
                narration=f"Paid online through Paystack, placed by {name}",
            )
        except services.FormAlreadyUsed:
            raise AlreadyInTheLedger("This payment is already in a child's account.")
        if not posted:
            raise AlreadyInTheLedger("This payment is already in a child's account.")

        placement = UnmatchedPlacement.objects.create(
            payment=payment,
            entry=entry,
            student_membership_id=child.pk,
            student_name=child.name,
            placed_by_id=actor.pk,
            placed_by_name=name,
        )
        return placement, True
