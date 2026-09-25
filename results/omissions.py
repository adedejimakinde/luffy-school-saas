"""Who a release left without a card, written down by the release itself. Issue #47.

`release()` freezes a card for every child on the one read of the class its
locked block takes (#43, #60). A child the office places into the class while
that block runs is not on the read and gets no card, which is the truthful
outcome and #31's dead end. What was missing was any record of her:
`docs/operating-rules.md` rule 8 says a decision that produces an absence needs
one, and the release's freeze row was the exception it named.

## The last step of the release, and it can stop the release

`check()` is called at the end of `release()`'s locked block, after every card
and every section is written. It reads the class again and writes a
`ReleaseOmission` for each child on it with no card, and a `ReleaseCheck` saying
the check finished, found anyone or not. All of it commits with the release or
not at all.

**If it fails, the release does not happen.** The principal is told that who was
left out could not be checked, and that the class has not been released. Nothing
has gone home, so releasing it again is the whole of the recovery: that release
takes its own read of the class, and a child placed since is on it and gets a
card (the review of #164).

It used to run after the commit instead, where a failure could only be logged
beside a release that stood, and the principal's page could not tell "nobody was
left out" from "nobody knows". A check after the commit also sees placements
that committed after the release did, and would write those children down as
left out by a release they were never near. Inside the transaction it cannot:
nothing committed after the release is visible to a read taken before it.

## A second read of the roster, on purpose

This is the one place a release reads `ClassPlacement` twice, and the second
read is the detector. That is not the defect #60 removed. That defect was a
second read deciding what got frozen, so two reads gave two answers to one
question and the card and its sections disagreed. This read comes after every
frozen row is written and nothing frozen hangs off it. It asks a different
question, "who is on the class now that the first read did not see?", and the
difference between the two reads is the answer. It is the shape of the detector
#60 deleted, which `docs/cards.md` records as having had no false positives.

The frozen side of the comparison is the cards the freeze just wrote, handed in
by `release()`. It is not the snapshot the freeze used, because compared with
that the answer would be "nothing moved" for every state of the database, which
is why the last detector was deleted instead of being rewritten that way
(`docs/cards.md`, "The detector that went with it").

**What it cannot see:** a placement that commits after its own read, or one into
the class after the release. She is in the class with no card as well, and
nothing here says so. That is issue #165.
"""

import logging

from django.db import transaction

from . import positions
from .models import ReleaseCheck, ReleasedCard, ReleaseOmission

logger = logging.getLogger(__name__)


def check(sheet, card_by_student):
    """Write down who the release is leaving without a card, or stop the release.

    Called last inside `release()`'s locked block, with the cards the freeze
    wrote. Any failure is logged with its traceback and re-raised as
    `LeftOutNotChecked`, which rolls the whole release back.
    """
    from .services import LeftOutNotChecked

    # Read before anything can fail. A refusal that queried after a database
    # error could come back as "current transaction is aborted" instead of the
    # sentence the principal needs.
    class_name = str(sheet.class_group)
    try:
        return record(sheet, card_by_student)
    except Exception as exc:
        logger.exception(
            "Could not check who release of sheet %s would leave without a card. "
            "The release is refused and nothing was released.",
            sheet.pk,
        )
        raise LeftOutNotChecked(
            f"Couldn't check who was left out of {class_name}, so it has not "
            f"been released and no card has gone home. Try releasing it again."
        ) from exc


@transaction.atomic
def record(sheet, card_by_student) -> list[ReleaseOmission]:
    """Write a row for each child on the class now who has no card on `sheet`.

    `card_by_student` is what `cards.freeze_for_release()` returned: the cards
    this release wrote. Called from `check()`, inside the release, and from
    nowhere else. Run later, it would compare the class as it is then, and
    write down every child placed since as left out by a release she was never
    near.

    A child with a first-release card for this term from another class is not
    left out: she was moved in mid-release, and her card has gone home.

    The sheet's `ReleaseCheck` is written in the same transaction, found anyone
    or not, so a released sheet with no check row is one nobody checked.

    Returns the rows it wrote.
    """
    # The one copy of "the school's name for the child comes first".
    from .cards import _student_names

    on_the_class = positions.roster_ids(sheet.class_group, sheet.term)
    missing = [
        student_id for student_id in on_the_class if student_id not in card_by_student
    ]
    if missing:
        carded_elsewhere = set(
            ReleasedCard.objects.filter(
                term=sheet.term, version=1, student_membership_id__in=missing
            ).values_list("student_membership_id", flat=True)
        )
        missing = [
            student_id for student_id in missing if student_id not in carded_elsewhere
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
            ]
        )
    ReleaseCheck.objects.create(sheet=sheet)
    return written


def _references(membership_ids) -> dict[int, str]:
    from accounts.models import Membership

    return dict(
        Membership.objects.filter(pk__in=membership_ids).values_list("pk", "reference")
    )


def checked(sheet_ids) -> set[int]:
    """The sheets among `sheet_ids` whose release checked who it left out."""
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
