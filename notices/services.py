"""Telling families: the decision, the budget, and the switch. `docs/messaging.md` D7, D9.

**"Tell families" is its own step after release** (D9, agreed in review), for
the principal. `release()` stays one transaction that depends on nothing outside
the database; withholding can land after release and is read when each notice
goes; and the principal is told how many messages before any go.

**The whole batch or none of it.** The daily cap is checked against the batch
before anything is written (D7): a half-sent batch leaves the office asking
which families got it, and nothing on the page could say.

**Pressing it twice sends each notice once.** A notice is unique per card and
channel, and a second press finds the first's rows and writes nothing new.
Two principals pressing at once are serialised on the settings row, which is
also what serialises two batches racing for the same day's cap.
"""

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from messaging import kinds

from . import hours, recipients
from .models import Notice, NoticeKind, NoticeSettings


class NoticesError(Exception):
    """A school's notices could not be sent as asked. Carries a sentence."""


class NoticesOff(NoticesError):
    pass


class OverTheCap(NoticesError):
    pass


class NotReleased(NoticesError):
    pass


class NotAllowed(NoticesError):
    pass


def offered() -> NoticeSettings:
    """This school's switches. An unsaved default (both off) when there is no row."""
    return NoticeSettings.objects.filter(pk=1).first() or NoticeSettings(pk=1)


def set_offered_as(actor, *, result_notices=None, fee_reminders=None) -> NoticeSettings:
    """Turn a school's notices on or off. A principal or an administrator."""
    from accounts.models import Role
    from results.services import school_on_this_connection

    school = school_on_this_connection()
    if not set(actor.roles_at(school)) & {Role.PRINCIPAL.value, Role.ADMIN.value}:
        raise NotAllowed("Only the principal or an administrator decides what the school sends.")
    row, _ = NoticeSettings.objects.get_or_create(pk=1)
    if result_notices is not None:
        row.result_notices = bool(result_notices)
    if fee_reminders is not None:
        row.fee_reminders = bool(fee_reminders)
    row.save()
    return row


def daily_cap() -> int:
    return int(getattr(django_settings, "NOTICE_DAILY_SEGMENTS", 3000))


def _segments_on(day) -> int:
    """Segments already asked for on `day`, sent or held. A fold over the rows (rule 4)."""
    start, end = _bounds(day)
    return (
        Notice.objects.filter(send_after__gte=start, send_after__lt=end).aggregate(
            total=Sum("segments")
        )["total"]
        or 0
    )


def _bounds(day):
    from datetime import datetime, time, timedelta

    start = datetime.combine(day, time(0), tzinfo=hours.LAGOS)
    return start, start + timedelta(days=1)


def _require_room(batch_segments, send_after):
    day = hours.day_of(send_after)
    used = _segments_on(day)
    cap = daily_cap()
    if used + batch_segments > cap:
        left = max(0, cap - used)
        raise OverTheCap(
            f"This would send {batch_segments} message segments, and this school has "
            f"{left} left for {day:%A %d %B}. Nothing has been sent."
        )


# -- what a result notice says -----------------------------------------------


def term_words(card) -> str:
    return f"{card.get_term_name_display()} {card.session}"


def result_message(card, contact, *, held: bool):
    """`(message kind, text)` for a result notice about `card`, sent to `contact`.

    Nothing from the card but the names it froze: the school, the child and the
    term (rule 2). No mark, grade, average, position or remark (requirement 7).
    """
    params = {"school": card.school_name, "child": card.student_name, "term": term_words(card)}
    if held:
        from results import withholding

        kind = kinds.Kind.RESULT_HELD
        params["contact"] = withholding.settings().withholding_contact.strip()
    else:
        kind = kinds.Kind.RESULT_NOTICE
    return kind, kinds.render(kind, channel_type=contact.channel_type, **params)


# -- the step -----------------------------------------------------------------


def _require_releasing_authority(actor, school):
    from results.services import RELEASING_ROLES

    if not set(actor.roles_at(school)) & RELEASING_ROLES:
        raise NotAllowed("Only whoever may release the results may tell families.")


def _require_tellable(sheet, actor):
    """`(school, sheet read afresh)`, or the refusal the principal is given."""
    from results.models import ResultSheet
    from results.services import school_on_this_connection

    school = school_on_this_connection()
    _require_releasing_authority(actor, school)
    if not offered().result_notices:
        raise NoticesOff("This school does not send result notices.")
    sheet = ResultSheet.objects.get(pk=sheet.pk)
    if not sheet.is_released:
        raise NotReleased("These results have not been released, so there is nothing to tell families.")
    return school, sheet


def _batch(sheet, school, actor, now):
    """`(unsaved notices, unreachable guardians, send_after)`: what a press would write at `now`.

    One function for the preview and the press, so the number the principal is
    shown and the number sent are counted by the same code. Families already
    told are skipped here, which is what makes the second press write nothing.
    """
    from results.models import ReleasedCard
    from results.withholding import is_withheld

    send_after = hours.send_after(now)
    told = set(Notice.objects.filter(card__sheet=sheet).values_list("card_id", "contact_id"))
    rows, unreachable = [], 0
    for card in ReleasedCard.objects.filter(sheet=sheet, version=1).order_by("student_name"):
        reachable, missed = recipients.for_child(card.student_membership_id, school)
        unreachable += missed
        held = is_withheld(card.student_membership_id, card.term)
        for guardian, contact in reachable:
            if (card.pk, contact.pk) in told:
                continue
            _, text = result_message(card, contact, held=held)
            rows.append(
                Notice(
                    kind=NoticeKind.RESULT_NOTICE,
                    card=card,
                    student_membership_id=card.student_membership_id,
                    term_id=card.term_id,
                    guardian_user_id=guardian.pk,
                    contact_id=contact.pk,
                    channel_type=contact.channel_type,
                    address=contact.value,
                    segments=kinds.segments(text)[1] if contact.channel_type == "phone" else 1,
                    send_after=send_after,
                    created_by_id=actor.pk,
                )
            )
    return rows, unreachable, send_after


def _answer(rows, unreachable, send_after, now):
    return {
        "messages": len(rows),
        "segments": sum(row.segments for row in rows),
        "held_until": None if send_after <= now else send_after,
        "unreachable": unreachable,
    }


def preview_families(sheet, *, actor, now=None) -> dict:
    """What "Tell families" would send if pressed now, having written nothing. D9, D7.

    "The button says how many messages it will send before it sends them", and
    in quiet hours that they will go at 07:00. Refused as the press would be,
    over the cap included, so the principal reads a refusal before pressing
    rather than after. Nothing is locked: the press counts again under its lock,
    and says what it did, which can differ if somebody pressed in between.
    """
    school, sheet = _require_tellable(sheet, actor)
    now = now or timezone.now()
    rows, unreachable, send_after = _batch(sheet, school, actor, now)
    if rows:
        _require_room(sum(row.segments for row in rows), send_after)
    return _answer(rows, unreachable, send_after, now)


@transaction.atomic
def tell_families(sheet, *, actor, now=None) -> dict:
    """Write a result notice for each guardian of each child on a released sheet.

    Returns what the principal is told: how many messages and segments, when
    they go, and how many guardians had no usable channel. Queues the ones that
    may go now; the rest are held for `release_held()` at 07:00.
    """
    school, sheet = _require_tellable(sheet, actor)

    # One batch at a time per school: the unique key stops a second press
    # duplicating a notice, and this stops two batches both fitting a cap
    # that only has room for one.
    NoticeSettings.objects.select_for_update().get(pk=1)

    now = now or timezone.now()
    rows, unreachable, send_after = _batch(sheet, school, actor, now)
    if rows:
        _require_room(sum(row.segments for row in rows), send_after)
        written = Notice.objects.bulk_create(rows)
        if send_after <= now:
            from .tasks import queue

            ids = [row.pk for row in written]
            schema_name = school.schema_name
            transaction.on_commit(lambda: queue(schema_name, ids))
    return _answer(rows, unreachable, send_after, now)


def told_about(sheet) -> int:
    """How many result notices have been asked for about this sheet, for the chain page."""
    return Notice.objects.filter(card__sheet=sheet).count()
