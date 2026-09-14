Task 8. A card that has gone home cannot be edited — `ReleasedCard` is
append-only — so a correction is a **new version** on the same sheet, and the
version in a parent's hand goes on standing.

## The mechanism was already decided, in a message

`services._move()` refuses every transition out of `released` with a sentence
naming this work: a released result "is corrected by issuing a revision, which
keeps this one standing, not by moving it back." So a revision does not reopen
the chain, start a new cycle or touch `ResultSheet.state`. It re-freezes one
child's card through the same functions the release used, so a revised card and
a first release are never two different kinds of thing.

## Three unique keys said a second version could not exist

`ReleasedTraitRating`, `ReleasedComment` and `ReleasedSessionResult` were unique
on `(sheet, student_membership_id, …)` — keys written before `card` existed — so
a second version's conduct section, remarks and session line collided with the
first version's. Re-keyed onto `card` in `0019`. Nothing weakens, because a card
is already unique per `(sheet, student, version)`, and no data moves, because
every existing row is version 1 where the two keys select the same rows.

## A child moved out of the class would have been reissued a blank card

`ClassPlacement` is one group per child per term, so a child moved after release
is off the roster the release was computed from and `class_results()` has nothing
to say about her. Every value it produces is individually legal — a child marked
in nothing has exactly that card — so no constraint objects, and the family's
reader shows the newer, emptier one. Refused now, with a control proving she is
genuinely off the roster.

## `is_revised` is `version > 1`, not "a `CardRevision` points here"

They disagree on the case this path exists to open: a child placed into a term
after it was released (#31) gets her first card from the revision path, at
version 1, with an audit row. Keying on the audit would stamp "Revised" across
the only card she has ever been given. The marker is on the **family** payload
as well as the staff one, unlike `position` — a parent holding two cards has to
know which supersedes which — while the reason and the reviser are on neither.

Authority is the principal's, which is release's own. Platform staff have a
second door they must ask for by name, and the flag chooses a different check
rather than widening one, so a staffer cannot revise without it and a principal
cannot set it.

## What the review then found, in the second commit

**The module said the conduct section and the remarks could change between two
versions. They cannot.** `gradebook.services`, `results.ratings` and
`results.comments` all gate their writes on `is_open_for_writing()`, false for
anything past `draft` — so every table a revision re-freezes from is frozen
upstream too. What can actually differ is the set of fields copied from tables
*not* gated on sheet state: the child's name, the school's name, the class's
name. A misspelt name on a card that has gone home is the commonest correction a
school asks for, so that is not nothing — but it is much less than the first
draft claimed.

**Six refusals sent a teacher after a remedy that does not exist.**
`MarksLocked` ×2, `RatingsLocked` ×2 and `CommentsLocked` ×2 all ended
"correcting one is a revision rather than an edit". All six now say the write is
refused, that a released card is corrected by reissuing it, that reissuing
cannot yet reach the value in question, and who to raise it with. The old
sentence survives in a comment above each, so whoever closes #54 finds the six
places that have to change back. See #53.

**`NoIndexIsBuiltTwiceTests` was scoped by a tuple**, so it only ever asked
about two tables. Widened to all five frozen tables, which found the same
redundant foreign-key index on `ReleasedSubjectResult` and
`ReleasedAssessmentScore`, carried since `0016`. `0020` drops all five. Both
reads such an index would serve are `WHERE card_id = …`, which the unique
constraint's leading column answers. That closes the `results` half of **#32**.

## Found and not fixed

- **#54** — a released term refuses *every* input a revision re-freezes from, so
  a revision can only fix a name. Updated from "marks" to the full set.
- **#55** — a revision re-ranks only its own card, so one class can hold two
  disagreeing rankings.
- **#53** — the messages half is fixed here; the mechanism half is #54.

## Tests

38 tests in `results/tests/test_revision.py`, two schools throughout, and Grace
releases and revises with its own people rather than being built and asked
nothing. The section comparisons assert a non-zero count: a school with the
conduct section off freezes nothing for either version, so `0 == 0` held with the
whole re-freeze deleted, which is how the first version of those tests passed.
