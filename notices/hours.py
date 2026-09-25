"""When a school's message may go: 07:00 to 20:00, Lagos time. D7, as decided in review.

A message asked for outside those hours is **held and sent at 07:00**, not
refused. `send_after()` is the one place that decides when that is, and the
budget counts a held message against the day it will go, not the day it was
asked for.

Codes are not here: a guardian asking for a code is asking now, and a code
lasts fifteen minutes.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

LAGOS = ZoneInfo("Africa/Lagos")


def _hours():
    opens, closes = getattr(settings, "NOTICE_HOURS", (7, 20))
    return time(opens), time(closes)


def send_after(now: datetime) -> datetime:
    """`now` if a message may go now, otherwise the next opening time."""
    opens, closes = _hours()
    local = now.astimezone(LAGOS)
    if opens <= local.time() < closes:
        return now
    day = local.date() if local.time() < opens else local.date() + timedelta(days=1)
    return datetime.combine(day, opens, tzinfo=LAGOS)


def day_of(moment: datetime):
    """The Lagos calendar day `moment` falls on, which is the day a budget counts."""
    return moment.astimezone(LAGOS).date()


def said(moment: datetime) -> str:
    """"07:00 tomorrow" style wording for a held batch, in Lagos time."""
    return moment.astimezone(LAGOS).strftime("%H:%M on %A %d %B")
