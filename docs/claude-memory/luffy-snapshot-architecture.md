---
name: luffy-snapshot-architecture
description: How the luffy report card snapshot is shaped — ReleasedCard as the artefact, what is copied, what is not, and the premise trap the whole design turns on
metadata:
  type: project
---

Task 3, on branch `report-card-snapshot` (`f582236`). `docs/cards.md` carries
the full argument in the repo; this is what a future session needs *before*
reading it, plus the parts that are decisions rather than code.

## `ReleasedCard` is the artefact, and the write is unconditional

One row per child on the roster at release, whatever else is true — no marks, no
ratings, both conduct groups off, nothing decided. Content tables
(`ReleasedSubjectResult`, `ReleasedAssessmentScore`) hang off it, and the three
older frozen tables (`ReleasedTraitRating`, `ReleasedComment`,
`ReleasedSessionResult`) gained a **non-null `card` FK**, backfilled by `0017`.

**One answer to "did a card go home", not four.** Four answers is the condition
that produced the issue #27 bug.

**No constraint can hold the unconditional-ness** — no `CHECK` can say "a row
exists for every child on a roster this transaction has already moved past". It
lives in `cards.freeze_for_release()`, is pinned by
`TheUnconditionalMarkerTests`, and has two controls behind it. **If those tests
are ever deleted for looking redundant, the guarantee is gone silently.**

## The premise trap — the thing to re-read before touching a release guard

> **"The marks are not frozen" and "no artefact records the release" are
> different claims, and the first does not imply the second.**

Issue #27's first draft reasoned from the first to the second, concluded there
was no artefact, and keyed the guard on `ClassPlacement` — which holds one group
per child per term, so a mid-term move *rewrites* it and destroys the record of
where the child sat at release. Released remarks became rewritable for any moved
child. `ReleasedTraitRating` had been answering the question all along.

The failure was in the **survey, not the logic**: a claim about the system
arriving disguised as a claim about the task in hand. Before concluding a guard
cannot be keyed properly, check *what release actually writes*.

**Its next form:** "a snapshot row exists, therefore a card went home" is true;
"content exists, therefore a card went home" is **not**. Guards key on
`ReleasedCard`, never on the presence of content.

## Copied, not joined — and the two that get missed

Every join out of a frozen row goes through something a school edits on an
ordinary Tuesday. Copied: subject name and code, assessment name and max score,
class group name, term name, session, **school name**, **student name**, grade
letter and remark.

The last two of those are the easily-missed ones: both come from `accounts`, a
**shared** schema whose rows change for reasons unconnected to this school.

**The grade letter especially.** `grades.grade_for()` is called at freeze time
and stored; nothing downstream may call it on a frozen percentage, or a school
replacing its scale rewrites every card in every parent's hand while the
percentages beside them stay put. The load-bearing test asserts reading a card
issues **no query against `results_gradeband`** — a values-only test passes
against a renderer that re-derives and happens to agree.

The scale is read **once per release**, not once per child, so a class's cards
agree with each other.

## Not frozen, deliberately

- **`class_average`** — computed on demand. Position is a statement about *this*
  child and is fixed at release; the class average is a statistic about the
  other forty-four, and freezing it leaves every unrevised card contradicting a
  revised one. The user reversed their own instruction to freeze it. A test
  asserts the column does not exist so it cannot be quietly reintroduced.
- **The promotion decision** — read live from the append-only
  `PromotionDecision`; it usually does not exist at release.

## Which row is *the* card

Earliest `(created_at, id)` among `version=1` rows for the term, then the
**highest version** of that sheet. Two sheets can hold a card for one child and
one term (release JSS 1A, move the child, release JSS 3B); versions come from
task 8. **Ordered explicitly, never by `Meta.ordering`** — `QuerySet.first()`
adds an `ORDER BY` on the pk when a queryset has none, so asserting merely that
an ordering exists proves nothing. Task 9 learned that twice.

## Ordering inside the release transaction

`cards.freeze_for_release()` runs **first** in `services.release()` — structural,
not tidy: the section freezes hang off the row it writes.

## Row volume, and why not JSON

~1,350 score cells per class release (45 children × 10 subjects × 3
assessments). Deliberate: one table means a card is exactly "these rows, in this
order", which can be asserted against; a JSON blob is a second shape that can
disagree with the columns beside it. The cost is paid on the read path, where
`cards.card_lines()` and `cards.cards_on()` fetch by `card_id` — task 7 renders
45 of these in one job, so **prefetch-by-card-id from the start**.

## A test hazard that has now bitten twice

**Every queryset must be evaluated inside its `connected_to()` block.** A lazy
`.first()` or `.all()` escaping the block runs against the public schema, where
tenant tables do not exist. It reads perfectly by eye both times. Materialise
inside, assert outside.
