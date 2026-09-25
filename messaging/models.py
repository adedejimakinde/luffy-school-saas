"""What was sent, and the fake provider's outbox. `docs/messaging.md` D2, D5, D6.

Shared tables, in `public`: a code belongs to a guardian's channel, and a
guardian is the platform's rather than a school's (parent-access D5). The
notices a school sends are its own, and live in its schema (M2).
"""

from django.db import models

from .kinds import Kind


class DeliveriesAreAppendOnly(Exception):
    """A delivery claim or outcome was edited or deleted."""


class _AppendOnly(models.Model):
    """`save()` refuses an update and `delete()` refuses outright; a trigger does the rest."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise DeliveriesAreAppendOnly(
                f"{type(self).__name__} {self.pk} has been recorded and cannot be changed."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DeliveriesAreAppendOnly(
            f"{type(self).__name__} {self.pk} cannot be deleted: it is the record "
            f"of whether a message went out."
        )


class CodeDelivery(_AppendOnly):
    """The claim: this code is being sent, once. Written before the provider is called.

    **At most once, and the unique key is how.** A Celery task can run twice
    (`acks_late` and reject-on-worker-lost, `docs/background.md`), and a send is
    not idempotent: a second SMS costs money and reaches a parent twice. So the
    task writes this row first. A second run meets the one-to-one and does
    nothing. A worker that dies after the claim leaves a claim with no
    `CodeDeliveryOutcome`, which is shown as "not known" and never resent: the
    guardian asks for another code.

    **No body.** The text of a code message carries the code, and a code is
    never at rest (D6). `GuardianContactCode` is already the send log; this row
    and its outcome are what happened to one entry in it.
    """

    code = models.OneToOneField(
        "accounts.GuardianContactCode", related_name="delivery", on_delete=models.PROTECT
    )
    kind = models.CharField(max_length=32, choices=Kind)
    channel_type = models.CharField(max_length=8)
    claimed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_kind_display()} for code {self.code_id}"


class Outcome(models.TextChoices):
    ACCEPTED = "accepted", "Accepted by the provider"
    REFUSED = "refused", "Refused by the provider"
    UNAVAILABLE = "unavailable", "Provider unavailable"
    NOT_CONFIGURED = "not_configured", "No provider configured"
    #: The sealed code expired on the queue before a worker reached it.
    EXPIRED = "expired", "Expired before it could be sent"


class CodeDeliveryOutcome(_AppendOnly):
    """What the provider said about one claimed code. At most one per claim.

    Its own row rather than a column on the claim, because the claim is
    append-only: it is written before the provider is called and cannot be
    amended after. The absence of this row is itself an answer, "not known".
    """

    delivery = models.OneToOneField(
        CodeDelivery, related_name="outcome", on_delete=models.PROTECT
    )
    outcome = models.CharField(max_length=16, choices=Outcome)
    provider_ref = models.CharField(max_length=128, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_outcome_display()} ({self.delivery_id})"


class FakeMessage(models.Model):
    """What `FakeProvider` was given. **Development and tests only**, and it holds codes.

    `messaging.E001` refuses a deploy with `DEBUG` off whose settings point at
    the fake, because this table would then hold every guardian's sign-in code
    in the clear and `/dev/outbox/` would show them.
    """

    channel_type = models.CharField(max_length=8)
    address = models.CharField(max_length=254)
    kind = models.CharField(max_length=32)
    subject = models.CharField(max_length=128, blank=True)
    text = models.TextField()
    reference = models.CharField(max_length=128, blank=True)
    outcome = models.CharField(max_length=16, choices=Outcome)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.kind} to {self.address}"
