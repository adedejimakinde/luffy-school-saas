## The thing this issue reports on is being deleted

PR #65 puts one read of `ClassPlacement` per sheet-locked block in place — #60 —
and `services._say_if_the_roster_moved()` goes with it. Recording this here now
rather than after the merge, because the loss is the part worth arguing with
before it lands, not after.

It could not survive that change as anything but a no-op. It worked by reading
the roster a second time after everything was written and comparing it against
the frozen one; under one read per block it compares the snapshot against
itself, so its only possible output is "nothing moved". Keeping it with a
docstring admitting that would have shipped the no-op *and* the log line, and
asked every future reader to notice the docstring before trusting the output.

**So what is left of this issue is not "put the warning in front of a person".
There is no warning.**

What was actually lost is worth stating plainly, because it is more than a log
line: the platform has **no detector of a mid-release roster move** now. The old
one was already unreliable in both directions — it could not tell "the office
moved a child during the release" from "my own second read raced the first one",
and it could not see a move that landed after it ran — but unreliable is not
nothing, and nothing is what replaced it.

## What this issue is now

Two separate things, and they were tangled here from the start:

1. **Telling the principal what a release did.** Still wanted, still the
   substance of this issue, and now it needs a *source* as well as a channel.
   `release()` returns the sheet; the count or the ids would have to come back
   with it, which is the change #45 declined to make and the reason this stayed
   open.

2. **Detecting the move at all.** New, and only because #60 removed the old
   answer. The honest place for it is the release's own snapshot compared
   against the roster at some later, deliberate moment — not a second read
   inside the same block, which is the defect #60 exists to remove.

Worth noting that (2) has a cheaper shape available now that did not exist when
this was filed: the frozen roster is on the cards themselves, so "who is in this
class now, and who has a card for this release" is answerable at any time by
anybody, without a race and without a lock — a screen rather than a log line.

The dead end for the dropped child described above is unchanged, and task 8's
revision path is what opens it.
