---
name: luffy-snapshot-read-once
description: "The one-read-per-locked-block rule on luffy-school-saas — what the ResultSheet lock does not cover, and the two reads that hide inside positions.py"
metadata:
  type: project
---

The `ResultSheet` row lock (`services._locked()`, `revision.revise()`) reaches
**that row and nothing else**. `ClassPlacement` is not locked, not joined to it,
and Postgres runs READ COMMITTED — so every statement inside the locked block
takes a fresh snapshot, and two reads of the roster are two answers.

**The rule, settled by the user on #60:** one `positions.class_results()` read
per locked block, passed down to everything that needs it. **Never a wider
lock** — it serialises the office against every release during the one week of
the year when both happen constantly, and it makes two reads *agree* rather than
removing the second one, leaving the next reader two reads and no reason to
trust either.

`ClassResults` therefore carries `placements`, `class_group` and `term`
alongside the numbers. Ids alone are not enough: `sessions._lines_for()` needs
each child's *placement* — which group she sat in — so passing the roster down
as a set of ids relabels the bug instead of closing it.

## The read that hides

`positions.overall_percentages(class_group, term)` **is**
`class_results(class_group, term).averages`. It looks like a lookup and it is a
whole second read. Anything inside a locked block that calls it is re-reading
the class one line below the read it was just handed.

Symptom when only the placements come from the snapshot and the averages do
not: a child removed mid-release keeps her placement but drops out of the fresh
averages, so her session line says `UNMARKED` where it used to say
`NOT_ENROLLED`. **A different sentence and the same lie** — it still contradicts
the card written beside it in the same transaction.

## The shape of the guard that goes with it

A guard must check **the same object the write will use**, not take a read of
its own. `revision._require_still_on_this_roster()` took its own read, passed,
and the freeze then read again and found an empty class — writing a blank
version 2 over a card that had marks, a total, an average and a position. Every
column individually legal, so no constraint objected; both versions append-only,
so neither could be withdrawn.

## A detector that compares a snapshot with itself is not a detector

`services._say_if_the_roster_moved()` was deleted rather than kept, because
under one read per block its only possible output is "nothing moved" — and its
log line reads as evidence somebody checked. The user's words: a guard that
guards nothing is worse than no guard. What that cost is recorded on #47: the
platform has **no detector of a mid-release roster move** now.

See [[luffy-open-work-state]], [[luffy-snapshot-architecture]],
[[luffy-release-marker-requirement]].
