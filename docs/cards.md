# The report card snapshot

What one child's card said, at the moment it said it. Task 3.

Code: `results/cards.py`, `results.models.ReleasedCard`,
`ReleasedSubjectResult`, `ReleasedAssessmentScore`, migrations `0016`–`0018`.

Everything else in this app freezes one *section* of a card — [conduct](ratings.md),
[remarks](comments.md), the [session line](sessions.md). This freezes the card
itself, and above all the row that records that a card went home at all.

## `ReleasedCard` is the artefact

One row per child on the roster at release, written **unconditionally**: no
marks, no ratings, the conduct section switched off school-wide, nothing
decided. A card went home for that child, and this row is what says so.

### Why that matters, from the failure that produced it

A guard asking *has a card gone home for this child?* used to have four places
to look and a placement join to fall back on. The fallback answers a different
question. `academics.ClassPlacement` holds one group per child per term, so a
mid-term move **rewrites** the row — the record of where the child sat at
release is destroyed, not superseded.

    release JSS 1A          the card goes home
    move the child to 3B    the placement row is rewritten
    guard asks "released?"  looks at JSS 3B's untouched draft -> permits the write

The child who stayed put was protected and the child who moved was not, on the
same term, by the same guard. `0010` and `0011` fixed that one table at a time
by keying on the frozen rows. What was left was a **per-school** hole: a school
with the conduct section off froze nothing for anybody, so nothing recorded its
releases at all. Issues #31, #33 and #34 each arrived here from a different
direction.

### The premise trap, stated once

The rule is *a guard on a released artefact keys off the artefact, not the
child's current placement*. The trap sits above the rule:

> **"The marks are not frozen" and "no artefact records the release" are
> different claims, and the first does not imply the second.**

Issue #27's first draft reasoned from the first to the second and keyed on
placement. `ReleasedTraitRating` had been answering the question all along.
Before concluding that a guard cannot be keyed properly, check **what release
actually writes** — not what the guard in front of you happens to be about.

The form it takes from here: *"a snapshot row exists, therefore a card went
home"* is true, but *"content exists, therefore a card went home"* is not.
Guards key on `ReleasedCard`, never on the presence of content.

### No constraint holds it

No `CHECK` can say "a row exists for every child on a roster this transaction
has already moved past". It is held by `cards.freeze_for_release()` and pinned
by `TheUnconditionalMarkerTests`, with a control run behind it. **Delete those
tests and the guarantee is gone with nothing to say so.**

## Everything the card prints is copied

Not joined to. Every join out of a frozen row goes through something a school
may legitimately edit next term.

| edit the school makes | what would have changed on a released card |
| --- | --- |
| renames a subject | a line it never printed |
| renames an assessment | a column header it never printed |
| renames the class | a heading it never printed |
| replaces the grading scale | every letter on the page |
| corrects a child's name | the name a parent is holding |

`student_name` and `school_name` are the two most easily missed: both come from
`accounts`, a **shared** schema whose rows change for reasons that have nothing
to do with this school.

### The grade letter especially

`grades.grade_for()` is called at **freeze time** and its answer stored.
**Nothing downstream may call it on a frozen percentage.** Re-deriving would
rewrite letters on cards already in parents' hands while the percentages beside
them stayed put — a card that said B2 quietly beginning to say B3.

Two tests hold that: one replaces the scale after release and asserts the
letters did not move, and one asserts that reading a card issues no query
against `results_gradeband` at all. The second is the one that matters — a
renderer that re-derived and happened to agree would pass the first.

The scale is read **once per release**, not once per child, so a class's cards
agree with each other.

## What is *not* frozen

**The class average**, computed on demand:

| | a statement about |
| --- | --- |
| `position` | *this* child — fixed at release, unrecomputable later without changing |
| class average | the other forty-four children |

Freeze the class average and one child's revision leaves forty-four unrevised
cards asserting a number that disagrees with the revised one — the
school's-screen-versus-card disagreement this phase exists to kill. Both are
staff-only and neither prints on a parent card, so nothing is lost by computing
it.

**The promotion decision**, read live from the append-only `PromotionDecision`.
It usually does not exist at release, and the hazard that drives freezing
everything else — a later configuration edit reaching backwards — cannot apply
to a table nothing edits.

## Staff-only, at the serializer

`position`, `roster_size`, `subject_position`. Excluded at the **serializer**,
not merely the template: a field omitted from the page but sitting in the JSON
has not been omitted. They live in their own columns so the exclusion is a field
list rather than a computation. Task 6 enforces it.

## Which row is *the* card

More than one can exist for one `(child, term)`, in two ways that compose:

    two sheets, one term     release JSS 1A, move the child, release JSS 3B
    two versions, one sheet  a revision (task 8)

The card is the **earliest** `(created_at, id)` among `version=1` rows, then the
**highest version** of that sheet. Ordered explicitly, never left to
`Meta.ordering`: `QuerySet.first()` adds an `ORDER BY` on the primary key when a
queryset has none, so asserting merely that an ordering exists proves nothing —
task 9 learned that twice.

## Rows, not JSON

A class of forty-five with ten subjects and three assessments writes about 1,350
score cells per release. Deliberate: one table means a released card is exactly
"these rows, in this order", which can be looked at, indexed and asserted
against. A JSON blob is a second shape that can disagree with the columns beside
it and nothing would notice.

The cost is paid on the read path, where it is cheap — `cards.card_lines()` and
`cards.cards_on()` fetch by `card_id` in a bounded number of queries, because
task 7 renders forty-five of these in one Celery job.

## Known gap: assessment column order

`Assessment` has no explicit print order and its `Meta.ordering` ends in `name`,
which is alphabetical — a card would print "Exam, First CA, Second CA". The
freeze orders by `(subject name, assessment id)` instead, on the grounds that
schools create assessments in the order they are sat. That is closer to right
and still a guess. The fix is a `position` field on `Assessment`, filed rather
than smuggled into this PR.
