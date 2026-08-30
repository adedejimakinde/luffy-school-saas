"""Reissuing a card that has already gone home. Task 8.

A released card is append-only — `ReleasedCard.save()` refuses a second write —
so a correction is not an edit. It is a **new version**, at the next number, on
the same sheet, and the version already in a parent's hand goes on standing and
goes on saying what it said. `CardRevision` records who asked for the new one
and why.

## This does not move the sheet, and that is decided elsewhere

`services._move()` refuses every transition out of `released` with a sentence
that names this module: a released result "is corrected by issuing a revision,
which keeps this one standing, **not by moving it back**." So a revision does
not reopen the chain, does not start a new cycle, and does not touch
`ResultSheet.state`. What it does is re-freeze one child's card from the live
tables, exactly as `release()` froze it the first time and through the same
functions, so that a revised card and a first release can never be two different
kinds of thing.

## One child, not the class, and what that costs

`CardRevision.card` is a `OneToOne`: one act, one version, one child. A
correction to one child's marks does, however, move **everybody's** `position`,
and the forty-four cards around the revised one are not rewritten — so the
revised card's rank can disagree with theirs. That is a knowing trade rather
than an oversight: `position` and `roster_size` are staff-only, print on no
family's card (see `ReleasedCard`), and the alternative — reissuing forty-five
cards, and stamping "Revised" on forty-four families' cards over a change to
somebody else's child — is worse in the place it matters. Issue #55, rather
than a silent choice.

## What may actually change between the two versions

Everything a card copies rather than joins to: the child's name, the school's
name, the class's name, the conduct section, the remarks. **Not the marks** — a
released term refuses a score write for ever (`gradebook.api`'s 423), so today a
revision cannot carry a mark correction. That is a real gap, and it is #54;
it is not this module's to close, because the decision "may a released term's
marks be reopened, and by whom" is exactly the sort of policy that must not be
invented in the least visible place on the platform.

## Two ways in

A **principal**, which is release's own authority — release is the principal's
act, so revision is too (`services.RELEASING_ROLES` carries that argument, and
was narrowed to hold it up). And **platform staff**, explicitly, for the school
that is locked out of its own correction. The second is asked for by name rather
than fallen into, and is recorded as a different thing, because a school reading
its own audit must never be told its principal did something its principal did
not do.
"""

from django.db import transaction

from academics.models import ClassPlacement

from . import cards, comments, positions, ratings, sessions
from .models import CardRevision, ResultSheet, SheetState
# `_locked` and `_require_authority` are private to `services`, and are
# imported rather than reimplemented on purpose: the lock carries a load-bearing
# `.order_by()` that this codebase has been bitten without three times, and the
# authority check returns the school and the roles in one read. A second copy of
# either is a second thing to keep in step with the chain it guards.
from .services import (  # noqa: PLC2701
    NotAllowedToActOnResults,
    RELEASING_ROLES,
    ResultsError,
    _locked,
    _require_authority,
    school_on_this_connection,
)


class RevisionError(ResultsError):
    """A card could not be reissued as asked."""


class NothingToRevise(RevisionError):
    """There is no released card here, and no released sheet to make one from."""


class TheChildHasLeftThisClass(RevisionError):
    """The card's own class no longer has this child on its roster for the term.

    `ClassPlacement` allows one group per child per term, so a child moved from
    JSS 1A to JSS 1B after JSS 1A's release is on JSS 1A's roster no longer —
    and `positions.class_results()` for JSS 1A, which is what a revision
    re-freezes from, has nothing to say about her. Left unguarded this writes a
    **blank card at version 2**: no marks, no totals, no position, no average.
    Every one of those is a legitimate value on its own (a child marked in
    nothing has exactly that card), so no constraint refuses it and the parent's
    reader would simply show the newer, emptier card.
    """


def revise(membership, term, actor, reason, *, by_platform_staff=False):
    """Reissue this child's card for this term. Returns the new `ReleasedCard`.

    `reason` is required and may not be blank. A revision is the one act on this
    platform that changes what a family has already been told, and a revision
    with no stated reason is indistinguishable, six months later, from a
    mistake. `CardRevision`'s CHECK holds it; this refuses it in a sentence.

    ## The child with no card at all

    Where nothing has gone home — a child placed into the term **after** it was
    released, issue #31 — this is also the path that finally gives her one, at
    **version 1**, superseding nothing. `CardRevision.previous_card` is null
    there, and `ReleasedCard.is_revised` reads `version > 1` precisely so that
    her card does not print "Revised" over a correction that was never made.

    ## The lock

    The sheet row, taken the same way `release()` takes it. Two principals
    revising the same child at once would otherwise both read version 2 and both
    write it; the unique constraint would catch the pair, but as an
    `IntegrityError` naming a column rather than as a refusal naming the act.
    The card is re-read **inside** the lock for the same reason `_move()` re-reads
    the sheet: the caller's copy is a fact about an earlier moment.
    """
    if not (reason or "").strip():
        raise RevisionError(
            "A revision has to say why. This one changes a card that is already "
            "in somebody's hand, and a correction nobody wrote a reason for is "
            "indistinguishable from a mistake once the term is over."
        )

    _require_the_authority_to_revise(actor, by_platform_staff)
    student_id = getattr(membership, "pk", membership)

    with transaction.atomic():
        sheet = _the_released_sheet(student_id, term)
        locked = _locked(sheet)
        if locked.state != SheetState.RELEASED:
            raise NothingToRevise(
                f"{locked.class_group} — {locked.term} is "
                f"{locked.get_state_display().lower()}, not released. A revision "
                f"reissues a card that has gone home; there is nothing here that "
                f"has."
            )

        previous = cards.card_for(student_id, term)
        version = 1 if previous is None else previous.version + 1
        _require_still_on_this_roster(locked, student_id)

        frozen = cards.freeze_a_revision(
            locked, student_id, version=version, by=actor
        )
        ratings.freeze_for_release(locked, frozen)
        comments.freeze_for_release(locked, frozen)
        sessions.freeze_for_release(locked, frozen)

        card = frozen[student_id]
        CardRevision.objects.create(
            card=card,
            previous_card=previous,
            reason=reason.strip(),
            revised_by_id=actor.pk,
            by_platform_staff=by_platform_staff,
        )

    return card


def _require_the_authority_to_revise(actor, by_platform_staff):
    """Principal, or platform staff who said so. Returns the school.

    The two are **not** a union checked in one place. Asking "principal here or
    platform staff anywhere?" would let a platform staffer revise without the
    flag, and the row would then record a school's own principal-shaped act for
    something the school did not do — which is the one thing
    `CardRevision.by_platform_staff` exists to keep apart.

    So the flag chooses the check rather than widening it, and a principal who
    is *also* platform staff still has to say which hat they are wearing.
    """
    if not getattr(actor, "is_authenticated", False):
        raise NotAllowedToActOnResults("Signing in is required to revise a card.")

    if by_platform_staff:
        if not getattr(actor, "is_platform_staff", False):
            raise NotAllowedToActOnResults(
                f"{actor} is not platform staff, so this revision cannot be "
                f"recorded as one. A principal revising their own school's card "
                f"is the ordinary path and does not set that flag."
            )
        return school_on_this_connection()

    school, _roles = _require_authority(actor, RELEASING_ROLES, "revise")
    return school


def _require_still_on_this_roster(sheet, student_id):
    """Refuse rather than write a blank card. See `TheChildHasLeftThisClass`.

    Read inside the lock, because "who is on this roster" is precisely the
    question issue #43 showed two reads give two answers to.
    """
    if student_id in positions.roster_ids(sheet.class_group, sheet.term):
        return
    raise TheChildHasLeftThisClass(
        f"This child's card was released with {sheet.class_group} for "
        f"{sheet.term}, and they are not on that class's roster for the term "
        f"any more. A revision re-freezes the card from that class's marks, and "
        f"there are none for them there now — it would issue a blank card over "
        f"the one that went home. Whatever the office did to the placement has "
        f"to be undone, or looked at, first."
    )


def _the_released_sheet(student_id, term):
    """The sheet whose release this revision reissues from.

    Where a card exists, its own sheet — never a lookup through the child's
    *current* placement, which is a different question and gives the wrong
    answer for any child the office has moved since. `ReleasedCard.sheet` is the
    release that actually happened.

    Where none exists this is the #31 case, and the placement is all there is:
    the child sits in a group now, that group's sheet for this term was
    released, and she was not on the roster when it was. Refused if that sheet
    is missing, because a revision cannot invent a release.
    """
    existing = cards.card_for(student_id, term)
    if existing is not None:
        return existing.sheet

    placement = (
        ClassPlacement.objects.filter(student_membership_id=student_id, term=term)
        .select_related("class_group")
        .first()
    )
    if placement is None:
        raise NothingToRevise(
            f"No card has gone home for this child for {term}, and they are in "
            f"no class group for it either — so there is no release to reissue "
            f"from. A child placed into a released term can be given a card "
            f"(issue #31); a child placed nowhere cannot."
        )

    sheet = ResultSheet.objects.filter(
        class_group=placement.class_group, term=term
    ).first()
    if sheet is None:
        raise NothingToRevise(
            f"{placement.class_group} — {term} has never been opened, so nothing "
            f"has been released for it and there is no card to reissue."
        )
    return sheet


__all__ = [
    "NothingToRevise",
    "RevisionError",
    "TheChildHasLeftThisClass",
    "revise",
]
