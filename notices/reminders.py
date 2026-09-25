"""Fee reminders: the bursar's act, to whoever receives invoices. `docs/messaging.md` D10.

**Who.** Each child placed in the chosen class, or anywhere in the school, in the
chosen term, whose whole account is owing by the ledger's own fold. Each guardian
of that child whose link says `receives_invoices` and who is live here, on one
channel (D4). One message per child per guardian: a family with three children
gets three (OPEN-M9). The term only chooses the children.

**What.** The amount is the whole account, worded as the account (decided
2026-09-25), and it is frozen on the row when the bursar presses send: the
number she saw in the preview.

**At send time the ledger is read again** (decided 2026-09-25). A balance that
has moved is a number that stopped being true, so the reminder goes nowhere and
its outcome says `balance_changed`. It does not count against the interval, and
the bursar's page lists it (`not_sent()`) so she can send again.

**At most one reminder per child per interval**, seven days by default
(`NOTICE_REMINDER_INTERVAL_DAYS`). A fold over the reminder rows, taken under the
settings-row lock that serialises every batch at a school, `tell_families()`'s
included. **Nothing in the schema bounds it**: the window moves with the clock,
and whether a row counts is known only once it has been sent.

The cap and the hours are the result notices' (D7): one budget per school per
Lagos day, and nothing school-originated goes between 20:00 and 07:00.
"""

from datetime import timedelta

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from messaging import kinds

from . import hours, recipients
from .models import Notice, NoticeKind, NoticeOutcome, NoticeSettings
from .services import NotAllowed, NoticesOff, OverTheCap, _require_room, offered  # noqa: F401

BALANCE_CHANGED = NoticeOutcome.Said.BALANCE_CHANGED


def interval() -> timedelta:
    return timedelta(days=int(getattr(django_settings, "NOTICE_REMINDER_INTERVAL_DAYS", 7)))


def _require_reminding(actor):
    """The school, or the refusal: the bursar's act, at a school that sends reminders."""
    from fees.authority import may_write
    from results.services import school_on_this_connection

    school = school_on_this_connection()
    if not may_write(actor, school):
        raise NotAllowed("Only the bursar or an administrator sends fee reminders.")
    if not offered().fee_reminders:
        raise NoticesOff("This school does not send fee reminders.")
    return school


# -- reading the ledger and the roll -------------------------------------------


def balances(ids) -> dict:
    """`membership id -> whole-account balance in kobo`, every term, one query.

    The fold `FeeLedgerQuerySet.balance()` takes for one child, grouped: a plain
    sum of the signed column, so a reversal needs no clause of its own.
    """
    from fees.models import FeeLedgerEntry

    return dict(
        FeeLedgerEntry.objects.filter(student_membership_id__in=list(ids))
        .values("student_membership_id")
        .annotate(total=Sum("amount_kobo"))
        .values_list("student_membership_id", "total")
    )


def balance_of(student_membership_id) -> int:
    from fees.models import FeeLedgerEntry

    return FeeLedgerEntry.objects.for_student(student_membership_id).balance()


def _named(ids, school):
    """`[{id, name, reference}]` for this school's students among `ids`, by name."""
    from accounts.models import Membership, Role

    rows = Membership.objects.filter(
        pk__in=list(ids), school=school, role=Role.STUDENT.value
    ).values("pk", "display_name", "user__full_name", "reference")
    named = [
        {
            "id": row["pk"],
            "name": row["display_name"] or row["user__full_name"] or "",
            "reference": row["reference"],
        }
        for row in rows
    ]
    return sorted(named, key=lambda c: (c["name"].lower(), c["id"]))


def _placed(term, class_group, only):
    """The children placed in `class_group` (or any class) in `term`, narrowed to `only`."""
    from academics.models import ClassPlacement

    placements = ClassPlacement.objects.filter(term=term)
    if class_group is not None:
        placements = placements.filter(class_group=class_group)
    ids = set(placements.values_list("student_membership_id", flat=True))
    if only is not None:
        ids &= {int(i) for i in only}
    return ids


def _counted_since(ids, since, *, inclusive=False):
    """Children with a reminder that counts, going after `since` (or at it, if `inclusive`).

    Held ones count: they are asked for. One whose balance changed does not: it
    went nowhere, by decision, so it must not stand in the way of the next.
    """
    return set(
        Notice.objects.filter(
            kind=NoticeKind.FEE_REMINDER,
            student_membership_id__in=list(ids),
            **({"send_after__gte": since} if inclusive else {"send_after__gt": since}),
        )
        .exclude(claim__outcome__said=BALANCE_CHANGED)
        .values_list("student_membership_id", flat=True)
    )


# -- what a reminder says ------------------------------------------------------


def reminder_text(*, school_name, child_name, amount_kobo, channel_type) -> str:
    """The whole text: the school, the child, the account's amount, who to call."""
    from results import withholding

    contact = withholding.settings().withholding_contact.strip()
    ask = f"Please contact the school: {contact}" if contact else "Please contact the school."
    return kinds.render(
        kinds.Kind.FEE_REMINDER,
        channel_type=channel_type,
        school=school_name,
        child=child_name,
        amount=kinds.naira(amount_kobo),
        ask=ask,
    )


def child_name(student_membership_id) -> str:
    from accounts.models import Membership

    row = (
        Membership.objects.filter(pk=student_membership_id)
        .values("display_name", "user__full_name")
        .first()
    )
    return (row["display_name"] or row["user__full_name"] or "") if row else ""


# -- the batch -----------------------------------------------------------------


def _batch(term, school, actor, now, class_group, only):
    """What a press would write at `now`, unsaved, and what the bursar is shown.

    One function for the preview and the press, so the number read in the
    preview is counted by the code that writes.
    """
    send_after = hours.send_after(now)
    children = _named(_placed(term, class_group, only), school)
    owed = balances(c["id"] for c in children)
    owing = [c for c in children if owed.get(c["id"], 0) > 0]
    recent = _counted_since((c["id"] for c in owing), send_after - interval())

    rows, unreachable, reminded, skipped = [], 0, [], []
    for child in owing:
        amount = owed[child["id"]]
        entry = {
            "student_membership_id": child["id"],
            "student": child["name"],
            "reference": child["reference"],
            "amount_kobo": amount,
        }
        if child["id"] in recent:
            skipped.append(entry)
            continue
        reachable, missed = recipients.for_child(child["id"], school, invoices_only=True)
        unreachable += missed
        for guardian, contact in reachable:
            text = reminder_text(
                school_name=school.name, child_name=child["name"], amount_kobo=amount,
                channel_type=contact.channel_type,
            )
            rows.append(
                Notice(
                    kind=NoticeKind.FEE_REMINDER,
                    student_membership_id=child["id"],
                    term_id=term.pk,
                    guardian_user_id=guardian.pk,
                    contact_id=contact.pk,
                    channel_type=contact.channel_type,
                    address=contact.value,
                    segments=kinds.segments(text)[1] if contact.channel_type == "phone" else 1,
                    amount_kobo=amount,
                    send_after=send_after,
                    created_by_id=actor.pk,
                )
            )
        entry["guardians"] = [guardian.full_name for guardian, _ in reachable]
        entry["unreachable"] = missed
        reminded.append(entry)
    return rows, unreachable, send_after, reminded, skipped


def _answer(rows, unreachable, send_after, now, reminded, skipped):
    return {
        "messages": len(rows),
        "segments": sum(row.segments for row in rows),
        "held_until": None if send_after <= now else send_after,
        "unreachable": unreachable,
        "children": reminded,
        "recently_reminded": skipped,
    }


def preview_reminders(term, *, actor, class_group=None, only=None, now=None) -> dict:
    """What "Remind families" would send if pressed now, having written nothing.

    D10: "see a preview: which children, which guardians, how many messages and
    segments. Then send." Refused as the press would be, over the cap included.
    """
    school = _require_reminding(actor)
    now = now or timezone.now()
    rows, unreachable, send_after, reminded, skipped = _batch(
        term, school, actor, now, class_group, only
    )
    if rows:
        _require_room(sum(row.segments for row in rows), send_after)
    return _answer(rows, unreachable, send_after, now, reminded, skipped)


@transaction.atomic
def send_reminders(term, *, actor, class_group=None, only=None, now=None) -> dict:
    """Write a reminder for each guardian who receives invoices, of each child who owes.

    Queues the ones that may go now; the rest are held for the 07:00 sweep.
    """
    school = _require_reminding(actor)
    # The lock `tell_families()` takes: one batch at a time per school, so two
    # presses cannot both pass the interval's fold, and two batches of any kind
    # cannot both fit a cap with room for one.
    NoticeSettings.objects.select_for_update().get(pk=1)

    now = now or timezone.now()
    rows, unreachable, send_after, reminded, skipped = _batch(
        term, school, actor, now, class_group, only
    )
    if rows:
        _require_room(sum(row.segments for row in rows), send_after)
        written = Notice.objects.bulk_create(rows)
        if send_after <= now:
            from .tasks import queue

            ids = [row.pk for row in written]
            schema_name = school.schema_name
            transaction.on_commit(lambda: queue(schema_name, ids))
    return _answer(rows, unreachable, send_after, now, reminded, skipped)


# -- the ones that went nowhere ------------------------------------------------


def not_sent() -> list:
    """Children whose last reminder went nowhere because their balance moved.

    For the bursar's page (decided 2026-09-25), so she can send again. A child
    leaves the list once a later reminder counts for them. One entry per child:
    the latest such reminder, the amount it would have stated, and the account
    as it stands now.
    """
    from results.services import school_on_this_connection

    latest = {}
    for notice in Notice.objects.filter(
        kind=NoticeKind.FEE_REMINDER, claim__outcome__said=BALANCE_CHANGED
    ).order_by("send_after", "pk"):
        latest[notice.student_membership_id] = notice
    if not latest:
        return []

    # At the same moment counts too: the other guardian's copy of that batch
    # went, so the child was reminded then, and the interval stands.
    superseded = set()
    for child_id, notice in latest.items():
        if _counted_since([child_id], notice.send_after, inclusive=True):
            superseded.add(child_id)
    waiting = {i: n for i, n in latest.items() if i not in superseded}
    if not waiting:
        return []

    now_owed = balances(waiting)
    school = school_on_this_connection()
    return [
        {
            "student_membership_id": child["id"],
            "student": child["name"],
            "reference": child["reference"],
            "term_id": waiting[child["id"]].term_id,
            "stated_kobo": waiting[child["id"]].amount_kobo,
            "asked_for": waiting[child["id"]].send_after,
            "balance_kobo": now_owed.get(child["id"], 0),
        }
        for child in _named(waiting, school)
    ]
