"""Finished attempts for the demo schools, sat through the services a school's students use.

`crestfield reset` and `seed_ui` (DEBUG only) call this so a demo's results, item analysis
and Send to CA show real numbers. Each student goes through `sitting.start()`,
`sitting.sync()` and `sitting.submit()`, so every answer, event and close is written as a
real sitting writes it; only the door is skipped (their PINs are not printed), with the
ticket the door would have handed them.
"""

import random
from datetime import timedelta

from django.utils import timezone

from . import sitting
from .models import TestItem


def sit_finished(school, test, students, *, rng=None, started=None, ability=None):
    """Each of `students` sits `test` and submits. A student's chance of a right answer is
    `ability(n)` for the n-th of them (default: from 0.9 down), and they leave the odd one
    blank. Times are `started` (default now) plus a minute a student; nothing is in the
    future. Returns the attempts."""
    rng = rng or random.Random(test.pk)
    items = list(TestItem.objects.filter(test=test).order_by("position"))
    begin = started or timezone.now() - timedelta(minutes=len(students) + test.duration)
    attempts = []
    for n, student in enumerate(students):
        chance = ability(n) if ability else max(0.3, 0.9 - 0.1 * n)
        at = begin + timedelta(minutes=n)
        ticket = sitting._ticket(school, test, student)
        begun = sitting.start(school, ticket, seat=f"Seat {n + 1}", now=at)
        answers = []
        for seq, item in enumerate(items, start=1):
            roll = rng.random()
            if roll > 0.96:
                continue
            if roll < chance:
                chosen = item.correct_index
            else:
                # The wrong one most choose: the option after the key, now and then another.
                wrong = [i for i in range(len(item.options)) if i != item.correct_index]
                chosen = wrong[0] if rng.random() < 0.6 else rng.choice(wrong)
            answers.append({"seq": seq, "item": item.pk, "chosen": chosen, "chosen_at": (at + timedelta(seconds=30 * seq)).isoformat()})
        done = at + timedelta(seconds=30 * len(items) + 20)
        sitting.submit(school, begun.token, answers=answers, now=done)
        begun.attempt.refresh_from_db()
        attempts.append(begun.attempt)
    return attempts


__all__ = ["sit_finished"]
