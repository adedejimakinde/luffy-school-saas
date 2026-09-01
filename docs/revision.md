# Reissuing a card that has gone home

Task 8. Code: `results/revision.py`, `CardRevision` and `ReleasedCard.is_revised`
in `results/models.py`, `cards.freeze_a_revision()`, migration
`0019_a_card_can_be_reissued`, tests in `results/tests/test_revision.py`.

## A correction is a new version, not an edit

`ReleasedCard.save()` refuses a second write, so there is no such thing as
changing a released card. A correction writes a **new row** at the next version
on the same sheet; the version already in a parent's hand goes on standing and
goes on saying what it said. `cards.card_for()` has ordered on version since
task 3 and now has a second row to order.

**A revision does not move the sheet.** `services._move()` refuses every
transition out of `released` with a sentence that names this: a released result
"is corrected by issuing a revision, which keeps this one standing, not by moving
it back." So there is no reopening, no new cycle, and no second trip through
submit → check → approve. The revision re-freezes one child's card through the
same functions the release used, so a revised card and a first release can never
be two different kinds of thing.

## The three keys that refused a second version

`version` has been on `ReleasedCard` since `0016`, added on the reasoning that a
revision would then need nothing from the content tables. That was wrong, and
task 8 found out by trying it: `ReleasedTraitRating`, `ReleasedComment` and
`ReleasedSessionResult` were unique on `(sheet, student_membership_id, …)` —
keys written before `card` existed at all — so a second version's conduct
section, remarks and session line collided with the first version's. They are
keyed on the card now.

Nothing is weakened by the swap. `one_card_per_student_per_release` already makes
a card unique per `(sheet, student_membership_id, version)`, so "one row per
trait per card" still implies one per student per trait per release. It only
stops being blind to which version. And no data moves: every existing row is
version 1, where the old key and the new one select exactly the same rows.

`ReleasedSubjectResult` and `ReleasedAssessmentScore` were already keyed on the
card and needed no change.

## One child, and what that costs

`CardRevision.card` is a `OneToOne`: one act, one version, one child. A
correction to one child's marks does move **everybody's** `position`, and the
forty-four cards around the revised one are not rewritten — so the revised
card's rank can disagree with theirs.

That is a knowing trade. `position` and `roster_size` are staff-only and print
on no family's card, so the disagreement is between two staff screens; the
alternative is reissuing forty-five cards and stamping "Revised" on forty-four
families' cards over a change to somebody else's child. It has an issue rather
than being a silent choice — it is #55.

The card is still **ranked against the whole class**: `freeze_a_revision()`
reads `positions.class_results()` for the class and narrows only the write. A
revision that read one child would rank every revised card first out of one,
which would look right.

## What can actually differ between the two versions

**Names, and today nothing else.** The child's name, the school's name and the
class's name are copied at freeze from tables edited elsewhere — `accounts` is a
shared schema, and neither `School` nor `ClassGroup` is gated on a sheet's state
— so a correction there reaches the new version. A misspelt name on a card that
has gone home is the commonest correction a school asks for, and the copy rule
that stops a later rename rewriting a released card is exactly what makes the
misspelling permanent until somebody reissues.

**Marks, ratings and remarks cannot change at all.** `gradebook.services`,
`results.ratings` and `results.comments` all gate their writes on
`is_open_for_writing()`, which is false for anything past `draft`. So once a
term is released, every input a revision re-freezes from is frozen upstream too,
and a revision issued to fix a wrong mark, rating or remark reproduces it
exactly.

That is **#54**, and it is wider than the "marks" in its title. It is
deliberately not closed here: "may a released term be reopened, and by whom" is
a policy decision, and the least visible place on the platform is the wrong
place to invent one.

### The six messages that promised otherwise

`MarksLocked`, `RatingsLocked` and `CommentsLocked` each refused a write in two
places with the sentence "correcting one is a revision rather than an edit."
True of the shape and false of the outcome: there was no revision that could
carry the correction, so the message sent a teacher after a remedy that does not
exist. All six now say the write is refused, that a released card is corrected
by reissuing it, that reissuing cannot yet reach the value in question, and who
to raise it with. They go back when #54 lands.

## "Revised" is said by the version, not by the audit row

`ReleasedCard.is_revised` is `version > 1`. It is **not** "a `CardRevision` row
points at this card", although the same act writes both.

They disagree on one real case, and it is the case this path exists to open. A
child placed into a term *after* it was released — issue #31 — gets her first
card from the revision path, at version 1, with a `CardRevision` recording who
issued it and why. Keying on the audit row would stamp "Revised" across the only
card she has ever been given. Keying on the version says what is true.

`is_revised` is on the family payload as well as the staff one, unlike
`position`: a parent holding two cards for one term has to be able to tell which
supersedes which, and being told that in the office rather than on the page is
how the wrong card gets believed. The *reason* is not on the payload —
`CardRevision` is the school's audit, and "why was this corrected" is a
conversation rather than a field on a page a child carries home.

## Who may

**The principal**, which is release's own authority: release is the principal's
act, so revision is too. `RELEASING_ROLES` was narrowed to `{principal}` in an
earlier PR specifically so this sentence would not be resting on a premise the
chain had stopped honouring.

**Platform staff, by saying so.** A school locked out of its own correction has
no other recourse. The flag is not a widening of the role check — it *chooses* a
different check, so a platform staffer cannot revise without it and a principal
cannot set it. `CardRevision.by_platform_staff` then records which it was,
because a school reading its own audit must never be told its principal did
something its principal did not do.

## The audit row

`CardRevision` is append-only in the same shape as `ReleasedCard` and
`ResultSheetTransition`: `save()` on an existing row and `delete()` both raise.
`reason` is required by a CHECK as well as by the service, for the argument
`ResultSheetTransition` makes one step earlier in the chain and which holds
harder here — by this point the wrong number is not on a screen in the office,
it is on paper in somebody's hand, and a revision with no stated reason is
indistinguishable six months later from a mistake.
