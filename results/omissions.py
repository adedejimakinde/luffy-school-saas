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
from .models import ReleaseCheck, ReleasedCard, ReleaseOmission, ResultSheet

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
        # Not "run it again": `record()` compares the class as it is when it
        # runs, and a later run would write down every child placed since as
        # left out by this release, in a table nothing can correct. The sheet
        # has no `ReleaseCheck`, and the principal's page says the check did
        # not finish (the review of #164).
        logger.exception(
            "Could not record who release of sheet %s left without a card. The "
            "release itself stands, and its sheet says the check did not finish.",
            sheet_id,
        )


@transaction.atomic
def record(sheet) -> list[ReleaseOmission]:
    """Write a row for each child on the class now who has no card on `sheet`.

    **For the check after the commit, not for running by hand later.** It
    compares the class as it is when it runs. Run straight after the release
    commits, a child on the class with no card was placed while the release
    ran; run days later, she may have arrived last week, and this would write
    her down — in a table nothing can correct — as left out by a release she
    was never near (the review of #164).

    A child with a card for this term from another class's release is not left
    out: she was moved in mid-release, and her card has gone home. Two runs at
    once are safe: a child already recorded is skipped, and a row the other run
    wrote first is let go rather than failing the batch it is in. The sheet's
    `ReleaseCheck` is written in the same transaction, found anything or not, so
    a release whose check never finished is one with no check row.

    Returns the rows it set out to write.
    """
    # The one copy of "the school's name for the child comes first".
    from .cards import _student_names, cards_by_student

    on_the_class = positions.roster_ids(sheet.class_group, sheet.term)
    carded = set(cards_by_student(sheet))
    missing = [student_id for student_id in on_the_class if student_id not in carded]
    if missing:
        carded_elsewhere = set(
            ReleasedCard.objects.filter(
                sheet__term=sheet.term, version=1, student_membership_id__in=missing
            ).values_list("student_membership_id", flat=True)
        )
        already = _already_recorded(sheet)
        missing = [
            student_id
            for student_id in missing
            if student_id not in carded_elsewhere and student_id not in already
        ]

    written = []
    if missing:
        names = _student_names(missing)
        references = _references(missing)
        written = ReleaseOmission.objects.bulk_create(
            [
                ReleaseOmission(
                    sheet=sheet,
                    student_membership_id=student_id,
                    student_name=names.get(student_id, ""),
                    student_reference=references.get(student_id, ""),
                )
                for student_id in missing
            ],
            ignore_conflicts=True,
        )
    ReleaseCheck.objects.get_or_create(sheet=sheet)
    return written


def _already_recorded(sheet) -> set[int]:
    return set(sheet.omissions.values_list("student_membership_id", flat=True))


def _references(membership_ids) -> dict[int, str]:
    from accounts.models import Membership

    return dict(
        Membership.objects.filter(pk__in=membership_ids).values_list("pk", "reference")
    )


def checked(sheet_ids) -> set[int]:
    """The sheets among `sheet_ids` whose check after release ran to its end."""
    return set(
        ReleaseCheck.objects.filter(sheet_id__in=list(sheet_ids)).values_list(
            "sheet_id", flat=True
        )
    )


def of_sheets(sheet_ids) -> dict[int, list[ReleaseOmission]]:
    """`sheet id -> its omissions`, in one query, for a page listing classes."""
    found = {}
    for row in ReleaseOmission.objects.filter(sheet_id__in=list(sheet_ids)):
        found.setdefault(row.sheet_id, []).append(row)
    return found
