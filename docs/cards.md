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

### One read of the class, and it belongs to the locked block

`services.release()` calls `positions.class_results()` **once**, at the top of
the block holding the sheet lock, and hands the result to everything below it.
`cards.freeze_for_release()` returns `student_id -> card`, and **that map is the
roster** for `ratings` and `comments`; `sessions` additionally takes the
`ClassResults` itself, because it needs each child's *placement* for the term
being released and not merely their id. `renders.mark_and_enqueue()` takes the
same map's values — the cards it writes a `PENDING` marker for are exactly the
cards this release froze, which is what makes "every released card owes a file"
a claim about one transaction rather than about a query run afterwards.

That is issue #43 and it is not tidiness. The lock `services._move()` holds is on
the **`ResultSheet` row** and reaches no further: `ClassPlacement` is not locked,
not joined to it, and not covered by anything else. Under READ COMMITTED every
statement in the release takes a fresh snapshot, so the office placing a child
into the class mid-release made the second roster read return somebody the first
had never seen. `card_by_student.get()` gave `None`, and the whole class's
release died on

    IntegrityError: null value in column "card_id" ... violates not-null constraint

— a column named, a cause not, on the screen of a principal who pressed release.

Four reads became one, so the question "who is on this release?" now has a single
answer and everything frozen agrees with it. A child placed while the release
runs is simply **not on it** — no card and therefore no sections, which is the
truthful outcome and avoids the empty-card shape #31 complains about.

**#43 left one read behind, and #60 removed it.** Passing the roster down as a
set of ids answered *who*, and `sessions._lines_for()` needed *where*: which
group each child sat in for the term being released. So it went back to
`ClassPlacement` inside the same locked block, and a placement deleted or moved
between the card freeze and the session freeze wrote two rows in one transaction
that contradicted each other — the card carrying her third-term marks while the
session line called her `NOT_ENROLLED` for third term and renormalised her year
over two. `ClassResults` therefore carries the placement rows it was built from,
and the same object answers both questions.

The alternative was a lock covering `ClassPlacement` for the class and term. It
was rejected on two grounds, the second the stronger: it serialises the office
against every release during the one week of the year when both happen
constantly, and it makes two reads *agree* rather than removing the second one —
leaving the next reader two reads and no reason to trust either.

Gone with it: `services._say_if_the_roster_moved()`, which logged the children a
release finished without by reading the roster once more at the end and
comparing. Against a single snapshot it can only ever report "nothing moved", so
it was a guard that guarded nothing whose log line read as evidence somebody had
checked. Deleting it takes away the platform's only detector of a mid-release
move, unreliable as that was — it could not tell "the office moved a child"
from "my own second read raced the first" — and it is what issue #47 was
reporting on.

`cards.the_card_for()` and `TheRosterMovedDuringRelease` are the belt to that
braces: nothing on the release path can now reach for a child the cards never
saw, so the exception exists for the paths that do not go through `release()`,
and for the fourth section somebody adds next year reaching for
`positions.roster_ids()` out of habit. It says what happened and that nothing was
saved, rather than naming a column.

`results/tests/test_release_roster_race.py` proves it with a real second
connection committing a real placement, timed deterministically rather than
raced for — a test that raced for luck would pass most runs, which is worse than
not having it.

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

## "On the card" does two jobs, and that is what took three rounds to pin down

**Neither `position` nor the class average is ever shown to a parent.** Both are
staff-only. Say that first, because everything below is a refinement of it.

The confusion is the phrase *on the card*, which names two different artefacts:

| "the card" | what it is | carries `position`? |
| --- | --- | --- |
| the `ReleasedCard` **row** | the frozen artefact, the audit record | **yes** |
| the **page that goes home** | `ReportCardOut`, and the PDF built from it | **no** |

So "`position` is on the card" is true of the row and false of the page, and
read as the second it says the opposite of what is meant.

**`position` is frozen for staff and audit recoverability, not for printing.**
It cannot be recomputed later without changing — the roster and the marks it
ranked against have both moved on — so if the rank as at release is ever to be
answerable, it has to be written down at release. That is the whole reason the
column exists. It is not evidence that anybody outside the school sees it.

The parent-facing exclusion is enforced at the serializer and confirmed at four
surfaces: `ReportCardOut` has no slot for `position`, `roster_size` or
`subject_position`; the PDF is built from `card_payload()`, the same object the
page is served from, so the omission is structural rather than repeated in a
template; the template carries no position field; and the broadsheet — the one
place a rank is shown at all — is behind `_require_position_authority`.

**The broadsheet does not display the frozen field.** For a released term it
derives `current_rank` from the cards' `own_average` values, deliberately named
so that it cannot be mistaken for `ReleasedCard.position`. See issue #55: the
frozen positions on forty-five cards need not come from one freeze, so reading
them off the rows could put two children at the same rank on one page.

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

The cost is paid on the read path, where it is cheap — `cards.card_lines()`
fetches by `card_id` in a bounded number of queries.

That paragraph twice named a batch that does not exist. It said "task 7 renders
forty-five of these in one Celery job", written before the job existed; then "in
a batch", after [report-card-pdf.md](report-card-pdf.md) settled that it is
**one job per card** — `acks_late` means a worker killed on the forty-fourth
card hands the message back, and `visibility_timeout` is 300 seconds, so a
per-class job risks redelivery alongside itself.

`cards.cards_on()` is the sibling reader built for that batch, and issue #56's
enqueuer did not want it either: it takes ids straight off the release's
`card_by_student` rather than prefetching every line and cell of forty-five
cards to throw them away. So it has **no caller**, which its own docstring now
says. It is kept for the `DISTINCT ON (student_membership_id) … ORDER BY version
DESC` rule, which any future batch reader needs and which is easy to get wrong:
without it a forty-five child class with one revision reads as forty-six, and
the superseded version goes home beside the one that replaced it.

## Migrating a database that already has results

`0017` gives `ReleasedTraitRating`, `ReleasedComment` and `ReleasedSessionResult`
a non-null `card` FK and backfills it, inventing a card for any historical
`(sheet, student)` pair that has a frozen section — a frozen rating *is* the
record that a card went home, so the row is not fabricated, it is that fact
written where it now belongs. Those cards carry the sections and nothing else:
the marks behind them were never frozen, and reconstructing a past card from
today's live scores is the exact thing this snapshot exists to prevent.

**Filling that column in means writing to three append-only tables.** Each has
carried a `BEFORE UPDATE OR DELETE` trigger that raises unconditionally since
`0007`, `0009` and `0013`, so the backfill drops the three triggers, writes, and
recreates them. That is safe in a way it does not look: Postgres DDL is
transactional and a migration is one transaction, so no session ever observes
the guards missing, and the write only ever touches `card_id` — no card changes
what it says. The functions are never dropped, only the triggers, so those three
migrations remain the single definition of what a guard says.

**An empty database cannot exercise any of this.** With nothing released there
are no pairs to link and the backfill returns before it writes, so a green test
suite and a clean fresh install say nothing about it. The coverage that counts
releases a term and then walks it back to the pre-`0016` shape before running the
migration's own `backfill()` against it — `TheBackfillMeetsTheAppendOnlyGuardsTests`
for a database whose cards exist and only need linking, and
`TheBackfillInventsTheMissingCardsTests` for the case any school that has
released anything actually has: frozen sections and no cards at all.

**A migration's models carry fields, not methods, and that is the third bug this
found.** `apps.get_model()` inside a `RunPython` hands back a model rebuilt from
migration state, so `ClassGroup.__str__` is not on it and `str(class_group)`
returns `ClassGroup object (3)` where the live model returns `JSS 1A`.
`cards._card_for()` is right to use `str()`; the backfill beside it was not, and
the difference is invisible to any test that hands the backfill
`django.apps.apps` — it agrees with the code for a reason production does not
share. The tests build the registry from `0017`'s own declared `dependencies`
instead, which is the one Django passes. The same slip is what left `school_name`
empty on every invented card.

The rule that falls out of it: **inside a migration, read attributes, never call
methods** — including `__str__` through `str()`, `f""` or `format()`.

## Assessment column order

`Assessment.position` says where a paper prints — smallest first, explicit,
never alphabetical. Issue #42, now closed. The freeze orders by
`(subject name, position, id)`.

Before it, `Meta.ordering` ended in `name` and a card would have printed "Exam,
First CA, Second CA", so the freeze sorted by `(subject name, assessment id)` —
creation order — as the closer guess.

`gradebook.0003` numbered existing papers by that same creation order rather
than trying to improve on it. The order is frozen onto every released card, and
a frozen order cannot be corrected on cards already issued: a backfill that
reshuffled would leave newly released cards disagreeing with cards already in
parents' hands, for the same child and the same term. A name heuristic was
considered and rejected for exactly that — it is right only for the names it
recognises and silently reorders "Test 1", "CA1", "Mid-Term" and anything not
in English.
