"""The proprietor's daily money summary: one email, once a day, per school.

Not shaped like a result notice, a reminder, a receipt or an alert — no
button, no `Notice` row, no guardian channel. This is a staff digest: whichever
staff the school has chosen (the settings screen, from its own live roster —
`notices.models.MoneySummaryRecipient`, nobody by default) get one email a day
summarising the money that moved on the day just ended, when
`NoticeSettings.daily_money_summary` is on. `manage.py send_daily_money_summary`
runs it, on the server's cron — `docs/background.md`'s "no `beat`, no
scheduler" argument, read again for a digest instead of a held message, the
way `release_held_notices` already reads it for M2.

**Sent once per day, per school**, recorded on `MoneySummarySent` — a plain
unique date rather than `Notice`'s claim-then-send machinery, because nobody
presses this twice by mistake: nobody presses it at all. A second run of the
same day's cron finds the row and sends nothing twice.

**Read from the ledger directly, not through `home.summary`.** That module
answers "what should a principal's home page show right now" for a signed-in
reader; this asks "what moved yesterday", for a day that has closed and an
audience that never opens the page. Same fold over `FeeLedgerEntry`
(`Coalesce(F("reverses__kind"), F("kind"))`, as `home.summary.fees()` uses),
a different filter (one day, by `recorded_at`) and a different reader.

**No queue, no quiet hours.** A small, staff-only audience and a message about
a day that has already closed is not urgent enough to hold and not frequent
enough to budget — sent straight through the provider, synchronously, from the
management command.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from messaging import kinds, providers

from . import hours
from .models import MoneySummarySent
from .services import offered

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DaysMoney:
    collected_kobo: int
    billed_kobo: int
    payments: int


def _bounds(day):
    """This school's Lagos day, as a `[start, end)` pair of instants."""
    start = datetime.combine(day, time(0), tzinfo=hours.LAGOS)
    return start, start + timedelta(days=1)


def money_on(day) -> DaysMoney:
    """What the ledger says happened on `day`. Same fold `home.summary.fees()` takes."""
    from fees.models import FeeEntryKind, FeeLedgerEntry

    start, end = _bounds(day)
    sums = dict.fromkeys(FeeEntryKind.values, 0)
    for row in (
        FeeLedgerEntry.objects.filter(recorded_at__gte=start, recorded_at__lt=end)
        .annotate(counts_as=Coalesce(F("reverses__kind"), F("kind")))
        .values("counts_as")
        .annotate(total=Sum("amount_kobo"))
    ):
        sums[row["counts_as"]] = row["total"] or 0
    payments = FeeLedgerEntry.objects.filter(
        kind=FeeEntryKind.PAYMENT, recorded_at__gte=start, recorded_at__lt=end
    ).count()
    return DaysMoney(
        collected_kobo=-(sums[FeeEntryKind.PAYMENT] + sums[FeeEntryKind.REFUND]),
        billed_kobo=sums[FeeEntryKind.CHARGE] + sums[FeeEntryKind.DISCOUNT],
        payments=payments,
    )


def recipient_emails(school) -> list[str]:
    """The chosen staff's own login emails, at most once each.

    **Nobody by default** — the settings screen adds rows to
    `MoneySummaryRecipient` one at a time, from this school's own live staff
    list. A membership picked and later ended, suspended or removed is skipped
    here rather than emailed: D4's "reachability is read again at send time"
    argument, for a staff address instead of a guardian channel.
    """
    from accounts.models import Membership

    from .models import MoneySummaryRecipient

    ids = MoneySummaryRecipient.objects.values_list("membership_id", flat=True)
    rows = (
        Membership.objects.for_school(school)
        .with_access()
        .filter(pk__in=list(ids))
        .exclude(user__email="")
        .exclude(user__email__isnull=True)
        .values_list("user__email", flat=True)
    )
    seen = set()
    emails = []
    for email in rows:
        if email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def summary_text(*, school_name, day, money: DaysMoney, channel_type) -> str:
    """The whole text: the school, the day, what was collected and billed."""
    word = "payment" if money.payments == 1 else "payments"
    return kinds.render(
        kinds.Kind.DAILY_MONEY_SUMMARY,
        channel_type=channel_type,
        school=school_name,
        date=day.strftime("%A %d %B %Y"),
        collected=kinds.naira(money.collected_kobo),
        billed=kinds.naira(money.billed_kobo),
        payments=money.payments,
        word=word,
    )


def send_summary(school, day) -> bool:
    """This school's digest for `day`, to every live administrator. Returns
    whether it was processed just now — `False` when the setting is off or
    `day` was already sent, either way with nothing sent twice.
    """
    if not offered().daily_money_summary:
        return False
    if MoneySummarySent.objects.filter(for_day=day).exists():
        return False

    money = money_on(day)
    provider = providers.provider_for("email")
    for address in recipient_emails(school):
        text = summary_text(school_name=school.name, day=day, money=money, channel_type="email")
        outbound = providers.Outbound(
            channel_type="email",
            address=address,
            kind=kinds.Kind.DAILY_MONEY_SUMMARY,
            text=text,
            reference=f"money-summary-{school.schema_name}-{day.isoformat()}",
        )
        try:
            provider.check_configured()
            provider.send(outbound)
        except providers.NotConfigured:
            logger.error("No email provider: %s's summary for %s was not sent", school, day)
        except providers.Refused:
            logger.error("Refused: %s's summary for %s to %s", school, day, address)
        except providers.Unavailable:
            logger.exception("Email provider unavailable: %s's summary for %s", school, day)

    # Recorded once regardless of how many emails above failed: this is a
    # "day processed" guard against the next cron tick, not a delivery
    # receipt — a provider outage should not mean every later tick retries a
    # digest whose day has already moved on, spamming the admins it did reach.
    MoneySummarySent.objects.create(
        for_day=day,
        collected_kobo=money.collected_kobo,
        billed_kobo=money.billed_kobo,
        payments=money.payments,
    )
    return True


def send_summaries(day=None, now=None) -> int:
    """Every school's digest for `day` (default: the Lagos day that just ended).

    Run by the server's cron, once daily, shortly after midnight. Returns how
    many schools were sent a digest just now. Safe to run more than once: a
    school already sent for `day` is skipped.
    """
    from django_tenants.utils import get_public_schema_name, tenant_context

    from schools.models import School

    now = now or timezone.now()
    day = day or (hours.day_of(now) - timedelta(days=1))
    sent = 0
    for school in School.objects.exclude(schema_name=get_public_schema_name()):
        with tenant_context(school):
            if send_summary(school, day):
                sent += 1
    return sent


__all__ = [
    "DaysMoney",
    "recipient_emails",
    "money_on",
    "send_summaries",
    "send_summary",
    "summary_text",
]
