Closes #60. Closes #46. Closes #59.

One read of `ClassPlacement` per sheet-locked block, threaded through everything
that needs it. The `ResultSheet` row lock reaches that row and nothing else, and
Postgres runs READ COMMITTED, so two reads of the roster inside one locked block
are two answers and the code between them cannot know which one it acted on.

## The shape

`positions.ClassResults` now carries **the placement rows it was built from**,
along with the class group and term it was read for. `services.release()` and
`revision.revise()` each call `positions.class_results()` once, at the top of
their locked block, and pass that object down:

- `cards.freeze_for_release()` and `freeze_a_revision()` are handed the snapshot
  instead of reading it.
- `revision._require_still_on_this_roster()` checks the same object the freeze
  is about to use, so the guard's answer and the freeze's answer are the same
  answer by construction (#59).
- `sessions.freeze_for_release()` takes it and answers the term being released
  from it. That is what #43's fix could not reach: `_lines_for()` needs each
  child's *placement* — which group she sat in — and not merely her id, so the
  roster travelling down as a set of ids left it asking again.

The other two terms of the session are still read live, and correctly: no lock
covers them, no snapshot was taken of them, and they are history.

**Not a wider lock.** A lock over `ClassPlacement` for the class and term would
serialise the office against every release during the one week of the year when
both happen constantly — and, more to the point, it makes the two reads *agree*
rather than removing the second one, leaving the next reader two reads and no
reason to trust either.

## One thing the audit did not have

The issue counted five call sites. Closing #46 needed a sixth read removed, and
it is the one that would have made a fix look complete while leaving the bug
half-alive:

`sessions._lines_for()` calls `positions.overall_percentages()`, and that
function **is** `class_results(class_group, term).averages` — the same read
again, one line down from the placement read the fix had just closed. With only
the placements coming from the snapshot, a child removed mid-release keeps her
placement (from the snapshot) but drops out of the *fresh* averages, so the
line calls her `UNMARKED` instead of `NOT_ENROLLED`. Different sentence, same
lie, and it still contradicts the card written beside it in the same
transaction. The released term's averages therefore come off the snapshot too.

## `_say_if_the_roster_moved()` is deleted

Under one read per block it compares the frozen roster against the same snapshot
the freeze used, so its only possible output is "nothing moved". It is not a
weaker detector after this change; it is not a detector. Kept with a docstring
admitting that, it would ship a no-op *and* a log line that reads as evidence
somebody checked.

Deleted with it: its two tests, and `results/services.py`'s module logger, which
had no other caller.

**What that costs, stated plainly:** the platform's only detector of a
mid-release roster move goes with it. It was already unreliable in both
directions — it could not distinguish "the office moved a child during the
release" from "my own second read raced the first", and could not see a move
landing after it ran — but unreliable is not nothing. #47 was about putting its
output in front of a person; it no longer has an output. Commented there.

## The tests, and the control that makes them mean something

In `results/tests/test_release_roster_race.py`, which already owns the
two-connection machinery: a real second session committing real work between two
statements of the releasing transaction, timed deterministically by wrapping the
call the gap sits behind rather than raced for.

`TheChildWhoLeftMidReleaseTests` — Ada's placement is removed by the office
after her card is written:

- her card still carries her marks (she was on the class when it was read);
- her session line does **not** call her `NOT_ENROLLED` for the term the card is
  about;
- her year is not renormalised over the terms that are left.

`TheRevisionGuardAndTheFreezeAgreeTests` — the placement is removed between the
guard and the freeze, and version 2 is a real card rather than the blank one
that used to land on top of a card that had marks, a total, an average and a
position.

### The control run

The tests were run against **`923b745` — the code before this branch** — because
a regression test that passes on both sides proves nothing. Four of the six fail
there, and the two that pass are the two that should: the precondition that the
office really did remove the placement, and the card itself, which was written
before she left and is correct either way.

```
FAIL: test_the_session_line_does_not_call_her_not_enrolled
AssertionError: 'not_enrolled' != ''
 : the session line contradicts the card written beside it in the same transaction

FAIL: test_her_year_is_not_renormalised_over_the_terms_she_did_sit
AssertionError: unexpectedly None : third term carried no weight in her year,
 so it was dropped from the weighting rather than counted

FAIL: test_the_revision_is_a_real_card_and_not_a_blank_one
AssertionError: 0 != 80 : version 2 was written blank

FAIL: test_the_version_that_went_home_is_still_there_beside_it
AssertionError: Lists differ: [(1, 80), (2, 0)] != [(1, 80), (2, 80)]

Ran 6 tests in 38.964s
FAILED (failures=4)
EXIT=1
```

`[(1, 80), (2, 0)]` is the whole of #59 in one line: version 1 with her marks,
version 2 blank, on top of it, append-only, after a guard that said she was
still on the roster.

On this branch the same six pass, and the whole `results` app passes with them.

### The gate

The whole `results` app on this branch, rebased onto `bd28cdf`:

```
Ran 545 tests in 1454.876s
OK
EXIT=0
```

The same 545 tests took `2852.528s` on the pre-#64 base this branch was written
against, and migrated 900-odd schemas doing it against 45 here. That is #64
underneath, not this change — but it is the first independent run of it on
somebody else's branch, and it holds.

## Also

`docs/cards.md`'s "one roster read" section now describes one read of the class
belonging to the locked block, what #43 left behind, why the wider lock was
rejected, and what went away with the detector.
