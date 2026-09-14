Closes #55.

## The promise

`results/api.py`'s `broadsheet()` said, in its own docstring:

> Read from live marks. There is no frozen snapshot yet — that is task 3 — and
> once there is, a *released* term must be served from it rather than from here,
> because a position recomputed after release can silently disagree with the
> card a parent is holding.

Task 3 shipped in #44. The switch was never made. `docs/positions.md` and
`docs/sessions.md` carried the same promise, so three places recorded a
condition — "once there is" — that had been true since #44 merged.

## What that cost, and why it is not a revision bug

The issue was originally framed as *a revision re-ranks only its own card*. That
is a consequence. The cause is that **marks lock at release and the roster does
not.**

- `gradebook`'s `0002` trigger refuses an INSERT, UPDATE or DELETE of a `Score`
  for a released term. A mark cannot move.
- Nothing refuses a `ClassPlacement`. A child placed into a released term (#31)
  or transferred out of one changes the live roster, and the broadsheet ranked
  whoever was on it *now* against marks frozen *then*.

So the two rankings were already disagreeing today, with no revision and without
#54. `test_a_placement_made_after_release_is_not_on_the_page` asserts both
halves — the trigger's refusal and the roster's movement — so the mechanism is
pinned by the suite rather than by this paragraph.

## The change

A released sheet is served from `cards.cards_on(sheet)`; anything else still
reads live marks, because a teacher who could not see their own marking on this
page would be reading a stale sheet all term.

**Every number on the released page comes from the rows on the released page.**

- `current_rank` is `dense_positions()` over the cards' frozen `own_average`
  values.
- `class_average` is `mean_percentage()` over those same values — still never
  stored, for the reason `positions.class_average()` already gives, and now
  provably the mean of the numbers displayed beside it.
- Columns come from the cards' own subject lines, in their frozen print order,
  so a subject retired since release still appears on a page released with it.

Nothing here writes.

### The ranks are derived, not read off the cards

This is the part worth reviewing. It would be natural to put
`ReleasedCard.position` on the page — it is right there, and it is the frozen
number. It is the wrong number for this page.

`position` records where a child came **at that card's own freeze**. A revision
re-freezes one card against the class as it reads at that later moment. Read
forty-five such numbers off forty-five cards and one page can show two children
at rank 1 — which `TheRevisedChildTests.test_the_page_never_repeats_a_rank`
demonstrates by asserting the frozen pair is literally `[1, 1]` while the page
says `[1, 2]`.

Both numbers are correct answers to different questions. The card answers *where
did she come when this card was made*; the page answers *where does she come
among the cards in this class*.

## Two things that need a word

**1. The response fields are renamed.** `position` → `current_rank`, and the
per-subject `position` → `current_subject_rank`. A new `from_snapshot: bool`
says which of the two questions the page answered.

The rename is the fix for the trap `results/card_api.py:34` already names:
`position` meant *rank in the class*, *rank in a subject* and *where the line
prints* in one codebase, and a broadsheet field called `position` holding a rank
was one paste away from being read as print order. Nothing in the repository
consumed the old names — there is no frontend, and `grep` finds no other reader
— so the cost is confined to any external caller, of which there are none before
release. Flagging it because it is a breaking API change, not a refactor.

**2. Row order differs between the two pages.** The live page is in roster order
(membership creation order); the released page comes back ordered by
`student_membership_id`, because `cards_on()`'s `DISTINCT ON` requires that
leading sort. Both are arbitrary to a school, which is [#24](https://github.com/adedejimakinde/luffy-school-saas/issues/24)
and still open. Choosing an order here would pre-empt it, so it is left alone
and stated instead.

## Not pre-committed

A mark-changing revision (#54) will still eventually need a class-wide re-freeze.
That decision belongs with #54, when there is something concrete to re-freeze.

## The self-review round

Reviewing this before opening it turned up one thing worth the paragraph, and it
was a *passing* control that found it.

The controls table in `docs/positions.md` breaks each claim in turn and re-runs.
Four of them failed loudly, as intended. The fifth — **take the columns from
`Subject.objects` instead of the cards' frozen subject lines** — came back `OK`,
28 tests, nothing broken. The subject half of a released page was carried
entirely by docstrings: the frozen column names, their print order and
`current_subject_rank` were claimed in prose and asserted by no test. That is
the same failure this endpoint's own docstring had already committed one
paragraph up, which is what makes it worth naming rather than quietly fixing.

`TheColumnsAreTheFrozenSubjectLinesTests` is that control's answer — a subject
renamed after release keeps the name it went home with, a subject the class was
never marked in is not a column, and the per-subject rank is derived from the
lines on the page. With them in place the same control fails, twice. A fourth
test in `TheRevisedChildTests` pins the per-subject half of the divergence:
the revised card's `subject_position` is `1` and the page says `2`.

The round also replaced a fourth inline copy of the sheet lookup with
`services.sheet_for()`, which carries the `.order_by()` that keeps
`ResultSheet.Meta.ordering` — two relations — from compiling a lookup of one
unique row into a three-table join. `ratings.sheet_for()` shipped without that
call once and was corrected on it, and its docstring asks not to be copied
again.

## Docs

- `docs/cards.md` gains the section the issue asked for: *"on the card"* names
  two artefacts — the `ReleasedCard` row, which carries `position`, and the page
  that goes home, which does not. Neither `position` nor the class average is
  ever shown to a parent; the exclusion is enforced at the serializer and
  confirmed at four surfaces.
- `docs/positions.md`'s "Read from live marks, for now" becomes "Live marks
  before release, the snapshot after", and records the rename.
- `docs/sessions.md`'s stale "once task 3 lands" bullet now says what is still
  read live in `_lines_for()` — the session's *other* two terms — and why that
  is safe for the one number it takes: `TermLine.average` is the child's own and
  marks lock at release, so it cannot move the way a rank can.

## Verification

`scripts/run-tests.sh results.tests.test_positions_api` — the script CI's "Run
tests" step invokes, so "green locally" and "green in CI" are the same claim:

```
Ran 32 tests in 100.759s

OK
EXIT=0
RESULT=OK
```

Twelve of those are new and belong to this change:
`AReleasedTermIsServedFromTheSnapshotTests` (6), `TheRevisedChildTests` (2 on
the class rank, 1 on the subject rank) and
`TheColumnsAreTheFrozenSubjectLinesTests` (3). Two tenants throughout —
`OneSchoolsStaffCannotReadAnothersTests` and
`TheSchemaComesFromTheHostNotThePathTests` ask the released path the same
cross-school questions the live one already answered.

### The controls

Each claim broken deliberately, then re-run. The table with the full reasoning
is in `docs/positions.md`; the summary:

| control | result |
| --- | --- |
| the released-term branch removed, so a released term keeps reading live marks | `FAILED (failures=10)` |
| `current_rank` read off `ReleasedCard.position` | `FAILED (failures=2)`, both in `TheRevisedChildTests` |
| `class_average` recomputed by `class_results()` from live marks | `FAILED (failures=1)` |
| the columns taken from `Subject.objects` | **`OK`** — then `FAILED (failures=2)` once the missing tests existed |
| `current_subject_rank` read off `ReleasedSubjectResult.subject_position` | `FAILED (failures=1)` |

The fourth row is the finding, and it is why the self-review section above
exists rather than being a formality.

The full suite is CI's job, not this machine's.
