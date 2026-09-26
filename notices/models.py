"""What a school tells families, in its own schema. `docs/messaging.md` D6, D7, D9.

A tenant app, where `messaging` is shared: a code belongs to a guardian's
channel, which is the platform's, but a notice is a school telling a family
about its own child. It goes with the school when the school leaves, which is
the deletion path parent-access OPEN-9 says must work.

**Three rows, each written once.** The `Notice` is the decision: who, about
what, on which channel, and when it may go. The `NoticeClaim` is the send: a
worker writes it, with the text exactly as it went, before it calls the
provider, and its one-to-one with the notice is what makes a second run send
nothing (D5). The `NoticeOutcome` is what the provider said. A claim with no
outcome is "not known whether it arrived", and it is never resent.

**The text is on the claim, not the notice.** A notice asked for at nine in the
evening goes at seven the next morning (D7), and the withholding gate is read
when it goes, not when it was asked for (D9): a card withheld overnight must
not be announced as ready. What went out is what the claim says, frozen when it
went (rule 2).
"""

from django.db import models
from django.db.models import Q


class NoticesAreAppendOnly(Exception):
    """A notice, a claim or an outcome was edited or deleted."""


class _AppendOnly(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise NoticesAreAppendOnly(
                f"{type(self).__name__} {self.pk} has been recorded and cannot be changed."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NoticesAreAppendOnly(
            f"{type(self).__name__} {self.pk} cannot be deleted: it is the record of "
            f"what this school told a family."
        )


class NoticeSettings(models.Model):
    """Whether this school sends notices at all. One row, `pk=1`.

    **Both off by default**, for withholding's reason: a school that has never
    heard of this must see no trace of it, and must not start messaging families
    the day it ships. `services.set_offered_as()` turns them on.
    """

    result_notices = models.BooleanField(default=False)
    fee_reminders = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(pk=1), name="notice_settings_are_one_row"),
        ]


class NoticeKind(models.TextChoices):
    RESULT_NOTICE = "result_notice", "Result notice"
    FEE_REMINDER = "fee_reminder", "Fee reminder"


class Notice(_AppendOnly):
    """One message a school decided to send one guardian, on one channel.

    The recipient is bare ids into the shared tables (`accounts.User`,
    `accounts.GuardianContact`), as every per-child column in `results` is a bare
    id into `accounts.Membership`: a real foreign key from a school's schema into
    `public` cannot `PROTECT` anything (`docs/tenancy.md`). The address is
    copied, so the record says where it went even after the channel changes.
    """

    kind = models.CharField(max_length=16, choices=NoticeKind)
    #: The card a result notice is about. A real key: same schema.
    card = models.ForeignKey(
        "results.ReleasedCard", related_name="notices", on_delete=models.PROTECT,
        null=True, blank=True,
    )
    student_membership_id = models.PositiveBigIntegerField()
    term = models.ForeignKey("academics.Term", related_name="notices", on_delete=models.PROTECT)
    guardian_user_id = models.PositiveBigIntegerField()
    contact_id = models.PositiveBigIntegerField()
    channel_type = models.CharField(max_length=8)
    address = models.CharField(max_length=254)
    #: Segments as the notice read when it was asked for. What a budget counts
    #: (D7): the claim's text can differ by a sentence, and the cap is a limit
    #: on what a school asked for, checked before anything goes.
    segments = models.PositiveSmallIntegerField()
    #: A fee reminder's amount: the child's whole account as the ledger folded
    #: it when the bursar pressed send, and the number the message states.
    #: Null for a result notice. At send time the ledger is read again, and a
    #: balance that has moved sends nothing (`Said.BALANCE_CHANGED`).
    amount_kobo = models.BigIntegerField(null=True, blank=True)
    #: When it may go: now, or 07:00 Lagos time if it was asked for in quiet hours.
    send_after = models.DateTimeField()
    created_by_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["send_after"])]
        constraints = [
            # "Tell families" twice sends each notice once (requirement 13). A
            # reminder has no card, and NULLs never collide, so this binds result
            # notices only.
            models.UniqueConstraint(
                fields=["card", "contact_id"], name="a_card_is_announced_to_a_contact_once"
            ),
            # A result notice is about a card and states no amount; a reminder
            # states an amount owing and is about no card.
            models.CheckConstraint(
                condition=(
                    Q(kind="result_notice", card__isnull=False, amount_kobo__isnull=True)
                    | Q(kind="fee_reminder", card__isnull=True, amount_kobo__gt=0)
                ),
                name="a_notice_is_about_a_card_or_an_amount_owing",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} to {self.address}"


class NoticeClaim(_AppendOnly):
    """The send, claimed before the provider is called. One per notice: at most once."""

    notice = models.OneToOneField(Notice, related_name="claim", on_delete=models.PROTECT)
    #: The message kind that went, which for a result notice is the held variant
    #: when the card was withheld at the moment of sending.
    message_kind = models.CharField(max_length=32)
    text = models.TextField()
    claimed_at = models.DateTimeField(auto_now_add=True)


class NoticeOutcome(_AppendOnly):
    """What the provider said, or why nothing was sent."""

    class Said(models.TextChoices):
        ACCEPTED = "accepted", "Accepted by the provider"
        REFUSED = "refused", "Refused by the provider"
        UNAVAILABLE = "unavailable", "Provider unavailable"
        NOT_CONFIGURED = "not_configured", "No provider configured"
        #: The guardian or the channel stopped qualifying between the asking and
        #: the sending (D4 is read again at send time).
        NO_LONGER_REACHABLE = "no_longer_reachable", "No longer reachable"
        #: A fee reminder whose account moved between the asking and the
        #: sending. The number it would have stated is no longer true, so it
        #: went nowhere, and it does not count against the reminder interval.
        BALANCE_CHANGED = "balance_changed", "Balance changed before sending"

    claim = models.OneToOneField(NoticeClaim, related_name="outcome", on_delete=models.PROTECT)
    said = models.CharField(max_length=24, choices=Said)
    provider_ref = models.CharField(max_length=128, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
