"""A school that sends nothing: no email and no SMS, whatever anybody presses.

Classnode's sales demo (`School.sales_demo`, `schools.crestfield`) lives on the
production server beside real schools, and its families and staff are made up.
A salesperson clicking through it must be able to press every button without
a message reaching a real phone or inbox: "Tell families", "Invite", a parent's
"Send me a code", a receipt or an absence alert.

So every place this platform hands a message to a provider on a school's behalf
asks `is_quiet()` first, and a quiet school's message is not sent:

- staff invitations (`schools.invitations._deliver`), refused before anything is
  written, so no account or membership is left behind;
- family notices, receipts, absence alerts and reminders (`notices.tasks`),
  recorded as "switched off" and never handed to the provider; and their
  switches on the Notices page refuse to turn on (`notices.services`);
- the daily money summary (`notices.daily_summary`), not processed at all;
- a guardian's codes (`messaging.codes`): one asked for by a quiet school, or a
  sign-in code for a guardian whose only live links are at quiet schools.

**The addresses are made up too, as a second lock.** The demo's people carry
`example.com` addresses and North American 555-01xx numbers, both reserved
for fiction, and the real providers (`messaging.smtp`, `messaging.termii`)
refuse such an address whatever school asked (`messaging.reserved`). Either
lock alone would do today; each covers the day somebody adds a path to the
other.
"""

from django.db.models import Q

SWITCHED_OFF = (
    "Messages are switched off for this school. It is Classnode's demo school, "
    "so nothing it does sends an email or a text to anybody."
)


class SwitchedOff(Exception):
    """A quiet school asked for a message to be sent. The message is for the person."""

    def __init__(self, message=SWITCHED_OFF):
        super().__init__(message)


def is_quiet(school) -> bool:
    """Whether `school` sends nothing. A school row, or None (the platform's own)."""
    return bool(getattr(school, "sales_demo", False))


def refuse_if_quiet(school) -> None:
    if is_quiet(school):
        raise SwitchedOff()


def only_at_quiet_schools(user_id) -> bool:
    """Whether every live link this person holds is at a quiet school.

    For a guardian's sign-in code, which no school asked for: it goes to the
    channel the guardian holds, and is the demo's to stop only when the demo is
    all this person belongs to. A real parent whom somebody also typed into the
    demo still gets their own school's sign-in code.
    """
    from accounts.models import LIVE_STATUSES, Membership

    live = Membership.objects.filter(user_id=user_id, status__in=LIVE_STATUSES)
    return live.exists() and not live.filter(Q(school__sales_demo=False)).exists()


__all__ = ["SWITCHED_OFF", "SwitchedOff", "is_quiet", "only_at_quiet_schools", "refuse_if_quiet"]
