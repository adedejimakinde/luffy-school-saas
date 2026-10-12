"""A teacher's or a bursar's first things to do, on the dashboard.

Each role sees its own card and only its own: a teacher's is the register and
marks, a bursar's is fees and a payment. A teacher's card says nothing about
fees. The administrator has Start here instead, and a parent's welcome is on
the report card page (`results.card_api`, `first_days`).

## When a card goes

When that person has done what it asks, read from the data (a register they
took, a mark they recorded, a payment they recorded), or fourteen days after
their first sign-in (`User.first_signed_in_at`), whichever comes first. There
is no hide button and nothing stored about the card itself.

## What it costs

Nothing, for anybody past their first fourteen days or holding neither role.
Otherwise one statement.
"""

from datetime import timedelta
from typing import Optional

from django.db import connection
from django.utils import timezone

from accounts.models import Role

#: How long a first-days card is shown after somebody's first sign-in.
FIRST_DAYS = timedelta(days=14)

ROLES = (Role.TEACHER.value, Role.BURSAR.value)

_DONE_SQL = """
SELECT json_build_object(
    'register', EXISTS (SELECT 1 FROM attendance_register WHERE taken_by_id = %(user)s),
    'marks', EXISTS (SELECT 1 FROM gradebook_score WHERE recorded_by_id = %(user)s),
    'fees', EXISTS (
        SELECT 1 FROM fees_feescheduleline l
        JOIN fees_feeschedule s ON s.id = l.schedule_id
        JOIN academics_term t ON t.id = s.term_id AND t.is_current
    ),
    'payment', EXISTS (
        SELECT 1 FROM fees_feeledgerentry WHERE kind = 'payment' AND recorded_by_id = %(user)s
    )
)
"""


def in_first_days(user, now=None) -> bool:
    """Within fourteen days of this login's first sign-in."""
    first = getattr(user, "first_signed_in_at", None)
    if first is None:
        return True
    return (now or timezone.now()) < first + FIRST_DAYS


def _cards(roles, done) -> list:
    cards = []
    if Role.TEACHER.value in roles:
        cards.append({
            "role": "teacher",
            "title": "Two things a teacher does here",
            "actions": [
                {"key": "register", "icon": "i-register", "href": "/register/", "title": "Take a register",
                 "detail": "Open your class and tap each student present or absent.", "done": done["register"]},
                {"key": "marks", "icon": "i-marks", "href": "/marking/", "title": "Enter marks",
                 "detail": "Pick a class and a paper. Marks save on your phone, even offline.", "done": done["marks"]},
            ],
        })
    if Role.BURSAR.value in roles:
        cards.append({
            "role": "bursar",
            "title": "Two things a bursar does here",
            "actions": [
                {"key": "fees", "icon": "i-fees", "href": "/fees/", "title": "Set up fees",
                 "detail": "Add this term's fee items, such as school fees and PTA levy.", "done": done["fees"]},
                {"key": "payment", "icon": "i-bank", "href": "/fees/", "title": "Record a payment",
                 "detail": "A parent paid at the bank or in cash? Record it and they get a receipt.",
                 "done": done["payment"]},
            ],
        })
    return [card for card in cards if not all(a["done"] for a in card["actions"])]


def card_for(request, school, user, roles, now=None) -> Optional[list]:
    """The first-days cards for this login at this school, or None."""
    roles = set(roles)
    if not roles & set(ROLES) or not in_first_days(user, now):
        return None
    with connection.cursor() as cursor:
        cursor.execute(_DONE_SQL, {"user": user.pk})
        (done,) = cursor.fetchone()
    return _cards(roles, done) or None


__all__ = ["FIRST_DAYS", "ROLES", "card_for", "in_first_days"]
