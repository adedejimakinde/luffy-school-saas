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

## What may actually change between the two versions, which is less than it looks

**Names, and today nothing else.** The child's name, the school's name and the
class's name are copied at freeze from tables edited elsewhere — `accounts` is a
shared schema, and neither `School` nor `ClassGroup` is gated on a sheet's state
— so a misspelling corrected there reaches the new version. That is not a small
case: a misspelt child's name on a card that has gone home is the commonest
correction a school actually asks for, and the copy rule that protects a
released card from a later rename is exactly what makes it permanent until
somebody reissues.

**Marks, ratings and remarks cannot change at all**, and the first draft of this
module said two of the three could. `gradebook.services`, `results.ratings` and
`results.comments` all gate their writes on
`results.services.is_open_for_writing()`, which is false for anything past
`draft` — so once a term is released every input this function re-freezes from
is frozen upstream too, and a revision issued to fix a wrong mark, a wrong
rating or a wrong remark reproduces it exactly.

That is **#54**, and it is wider than the "marks" its title says. It is not this
module's to close: "may a released term be reopened, and by whom, and does that
reopening leave its own audit row" is precisely the sort of policy that must not
be invented in the least visible place on the platform. What *was* fixed here is
the six refusals across those three modules that told the reader "correcting one
is a revision rather than an edit" — true of the shape, false of the outcome,
and it sent people after a remedy that does not exist.

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

from academics.models import ClassPlacement, Term, TermName

from . import cards, comments, positions, ratings, renders, sessions
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

    ## The year's summary follows

    Reissuing a first- or second-term card whose average (or whose being there
    at all) differs from what the child's third-term card froze for that term
    reissues the third-term card as well, in the same transaction, with its own
    logged revision. `_update_the_years_summary()` has the rule.
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
        card = _reissue(student_id, term, actor, reason.strip(), by_platform_staff)
        _update_the_years_summary(card, actor, reason.strip(), by_platform_staff)
    return card


def _reissue(student_id, term, actor, reason, by_platform_staff):
    """One card, reissued at the next version. Inside the caller's transaction."""
    sheet = _the_released_sheet(student_id, term)
    locked = _locked(sheet)
    if locked.state != SheetState.RELEASED:
        raise NothingToRevise(
            f"{locked.class_group} for {locked.term} is "
            f"{locked.get_state_display().lower()}, not released. A revision "
            f"reissues a card that has gone home; there is nothing here that "
            f"has."
        )

    previous = cards.card_for(student_id, term)
    version = 1 if previous is None else previous.version + 1

    # One read of the class inside this lock, and everything below is
    # decided against it — the guard, the freeze and the session line.
    # Issue #60; `_require_still_on_this_roster()` says what two reads cost.
    results = positions.class_results(locked.class_group, locked.term)
    _require_still_on_this_roster(locked, results, student_id)

    # D7. `previous` is the card this revision supersedes, and its three
    # attendance numbers are copied onto the new version rather than
    # recomputed. A March revision fixing a comment typo must not silently
    # restate the attendance a parent read in December — every value
    # individually legal, nothing objecting, and a correction to one field
    # quietly rewriting another. That is issue #59's shape, about a
    # different column.
    #
    # `None` for a first version, which is the task 8 case of a child placed
    # into a term after it was released: she has no earlier card to carry
    # anything forward from.
    frozen = cards.freeze_a_revision(
        locked,
        results,
        student_id,
        version=version,
        supersedes=previous,
        by=actor,
    )
    # The conduct section is **carried** from the card this one supersedes,
    # not re-read from the school's settings: a trait renamed or a section
    # switched off since the first release must not reach a reissued card.
    # A child with no earlier card is frozen from the settings as they are.
    if previous is None:
        ratings.freeze_for_release(locked, frozen)
    else:
        ratings.carry_forward(frozen, previous)
    comments.freeze_for_release(locked, frozen)
    sessions.freeze_for_release(locked, frozen, results)

    card = frozen[student_id]
    CardRevision.objects.create(
        card=card,
        previous_card=previous,
        reason=reason,
        revised_by_id=actor.pk,
        by_platform_staff=by_platform_staff,
    )
    # A revision is a card, so it owes a file exactly as a release does —
    # and this path is the *only* way a child placed into a term after it
    # was released (issue #31) gets one at all. Marking only at release
    # would leave her card the one case with no marker and no render, which
    # is precisely the case issue #56 is about. `results.renders` holds the
    # ordering: the row inside this transaction, the queue after it.
    renders.mark_and_enqueue([card])

    return card


class TheYearsSummaryCannotFollow(RevisionError):
    """An earlier term's card cannot be reissued because the third-term card,
    whose year summary it would change, cannot be reissued with it."""


def _update_the_years_summary(card, actor, reason, by_platform_staff):
    """After a first- or second-term card is reissued: reissue the third-term
    card too, in this transaction, if its year summary no longer says what the
    cards say. Returns the new third-term card, or `None` when nothing changed.

    A third-term card freezes the year: each term's average and the session
    average (`ReleasedSessionResult`), read from the cards as they stood at its
    release (audit finding G-02). Reissuing an earlier term's card afterwards
    used to leave that summary quoting a card that had been superseded: the
    "first term" on the third-term card and the average on the first-term card
    in the same parent's hands disagreed, and so did the promotion suggestion.

    **Only when a figure moves.** The year's line is worked out again from the
    cards as they now stand and compared with the frozen one, term by term:
    the average, or the reason there is none. A reissue that corrects a name
    leaves them equal, and then the third-term card is not touched and does not
    grow a "Revised" mark over somebody's spelling.

    **How it is logged.** The third-term card's new version is an ordinary
    revision: its own `CardRevision` row, by the same person, at the same
    moment, with a reason that names the cause and quotes theirs.

    **Everything or nothing.** If the third-term card cannot be reissued (the
    child is no longer on that class's list for the term,
    `TheChildHasLeftThisClass`), neither is this one: the caller's transaction
    is rolled back and the refusal says both halves. A first-term card and a
    year summary that disagree is the state this exists to prevent, so it does
    not leave one behind on purpose.
    """
    if card.term_name == TermName.THIRD:
        # Its own reissue has just frozen the year again (`_reissue()`).
        return None
    third = Term.objects.filter(session=card.session, name=TermName.THIRD).first()
    if third is None:
        return None
    frozen = sessions.released_session_line(card.student_membership_id, card.session)
    if frozen is None:
        # No third-term card has frozen this child's year: nothing to update.
        return None

    now = sessions.session_line(card.student_membership_id, card.session)
    moved = [
        line.term_name
        for line in now.terms
        if line.term_name != TermName.THIRD
        and (
            getattr(frozen, f"{line.term_name}_average") != line.average
            or getattr(frozen, f"{line.term_name}_absence") != line.absence
        )
    ]
    if not moved:
        return None

    cause = (
        f"The year's summary was updated because the {TermName(card.term_name).label.lower()} "
        f"card was revised. That revision's reason: {reason}"
    )
    try:
        return _reissue(card.student_membership_id, third, actor, cause, by_platform_staff)
    except TheChildHasLeftThisClass as exc:
        raise TheYearsSummaryCannotFollow(
            f"Revising this card changes the year's summary on the child's third-term "
            f"card, and that card cannot be reissued: {exc} Nothing was changed."
        ) from exc


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


def _require_still_on_this_roster(sheet, results, student_id):
    """Refuse rather than write a blank card. See `TheChildHasLeftThisClass`.

    **Checked against the snapshot the freeze is about to use, not a read of its
    own — issue #59.** Being inside the lock was never enough: the lock is on
    the `ResultSheet` row and reaches no further, so this guard's read and
    `freeze_a_revision()`'s read were two statements under READ COMMITTED and
    two answers to one question. A placement moving between them passed the
    guard and then wrote a **blank version 2** — no marks, no totals, no
    position, no average — over a card that had all four. Every value
    individually legal, so no constraint objected, and both versions
    append-only, so neither could be taken back.

    Asking the same object the freeze will use makes the guard's answer and the
    freeze's answer the same answer by construction.
    """
    if student_id in results.placements:
        return
    raise TheChildHasLeftThisClass(
        f"This child's card was released with {sheet.class_group} for "
        f"{sheet.term}, and they are not on that class's roster for the term "
        f"any more. A revision re-freezes the card from that class's marks, and "
        f"there are none for them there now. It would issue a blank card over "
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
            f"no class group for it either, so there is no release to reissue "
            f"from. A child placed into a released term can be given a card, "
            f"but a child placed nowhere cannot."
        )

    sheet = ResultSheet.objects.filter(
        class_group=placement.class_group, term=term
    ).first()
    if sheet is None:
        raise NothingToRevise(
            f"{placement.class_group} for {term} has never been opened, so nothing "
            f"has been released for it and there is no card to reissue."
        )
    return sheet


__all__ = [
    "NothingToRevise",
    "RevisionError",
    "TheChildHasLeftThisClass",
    "TheYearsSummaryCannotFollow",
    "revise",
]
