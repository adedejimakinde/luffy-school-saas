"""Who a release left without a card, written down after it commits. Issue #47.

`release()` freezes a card for every child on the one read of the class its
locked block takes (#43, #60). A child the office places into the class while
that block runs is not on the read and gets no card, which is the truthful
outcome and #31's dead end. What was missing was any record of her:
`docs/operating-rules.md` rule 8 says a decision that produces an absence needs
one, and the release's freeze row was the exception it named.

## A second read of the roster, on purpose, and after the commit

This module is the one place a release reads `ClassPlacement` twice, and the
second read is the detector. That is not the defect #60 removed. That defect
was a second read *inside* the locked block, deciding what got frozen. This one
runs in an `on_commit` callback, after everything is frozen and durable, and
decides nothing that goes home: its only output is a row saying who is in the
class now and has no card on this sheet.

The frozen side of the comparison is the cards themselves (version 1 on the
sheet, which is what the release wrote), not the snapshot the freeze used.
Compared with that snapshot, the answer would be "nothing moved" for every
state of the database, which is why the last detector was deleted instead of
being rewritten that way (`docs/cards.md`, "The detector that went with it").

**What it cannot see:** a placement that lands after its own read. She is in the
class with no card as well, and nothing here says so.

## It must not be able to fail a release

The callback runs after the commit, so an exception in it would reach the
principal as a 500 for results that have already gone home. It is caught and
logged at ERROR, the way `results.renders` treats the enqueue. The log line
names the school through `schools.logging.SchoolContextFilter`, because the
callback runs on the school's connection.

## The schema is captured, not read in the callback

For `renders`' reason: the schema name is read while the release is still on
the school's connection and handed to the callback, which enters it
explicitly. A callback that trusted whatever `search_path` it found would be
guessing at the one point that looks safe.
"""

import logging

from django.db import connection, transaction
from django_tenants.utils import schema_context

from . import positions
from .models import ReleasedCard, ReleaseOmission, ResultSheet

logger = logging.getLogger(__name__)


def notice_after_commit(sheet):
    """Ask, once the release commits, who is on the class and has no card.

    Called from inside `release()`'s locked block. It registers the check and
    returns; the check itself runs after the commit.
    """
    schema_name = connection.schema_name
    sheet_id = sheet.pk
    transaction.on_commit(lambda: _notice(schema_name, sheet_id))


def _notice(schema_name, sheet_id):
    """The `on_commit` body: record, and never raise."""
    try:
        with schema_context(schema_name):
            record(ResultSheet.objects.get(pk=sheet_id))
    except Exception:  # noqa: BLE001 — the release is durable; say so and stop
        logger.exception(
            "Could not record who release of sheet %s left without a card. The "
            "release itself stands; the check can be run again with "
            "results.omissions.record().",
            sheet_id,
        )


@transaction.atomic
def record(sheet) -> list[ReleaseOmission]:
    """Write a row for each child on the class now who has no card on `sheet`.

    Safe to call again for the same sheet: a child already recorded is skipped,
    and `a_release_omits_a_child_once` refuses a second row if two calls race.
    Returns the rows it wrote.
    """
    # The one copy of "the school's name for the child comes first".
    from .cards import _student_names

    on_the_class = positions.roster_ids(sheet.class_group, sheet.term)
    carded = set(
        ReleasedCard.objects.filter(sheet=sheet, version=1).values_list(
            "student_membership_id", flat=True
        )
    )
    already = set(sheet.omissions.values_list("student_membership_id", flat=True))
    missing = [
        student_id
        for student_id in on_the_class
        if student_id not in carded and student_id not in already
    ]
    if not missing:
        return []

    names = _student_names(missing)
    references = _references(missing)
    return ReleaseOmission.objects.bulk_create(
        [
            ReleaseOmission(
                sheet=sheet,
                student_membership_id=student_id,
                student_name=names.get(student_id, ""),
                student_reference=references.get(student_id, ""),
            )
            for student_id in missing
        ]
    )


def _references(membership_ids) -> dict[int, str]:
    from accounts.models import Membership

    return dict(
        Membership.objects.filter(pk__in=membership_ids).values_list("pk", "reference")
    )


def of_sheets(sheet_ids) -> dict[int, list[ReleaseOmission]]:
    """`sheet id -> its omissions`, in one query, for a page listing classes."""
    found = {}
    for row in ReleaseOmission.objects.filter(sheet_id__in=list(sheet_ids)):
        found.setdefault(row.sheet_id, []).append(row)
    return found
