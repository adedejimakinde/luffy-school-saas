# Issue #56 — the brief checked against the code

Checked at `bd28cdf` (worktree `~/worktrees/card-render-enqueue`, still clean,
nothing written). Four things conflict or aren't covered; the rest holds.

## Holds as specified

`freeze_the_card()` runs inside `_move()`'s `transaction.atomic()`
(`results/services.py:542,594`) with `card_by_student` in hand at `:794` —
`on_commit` there fires after the release commits, and a `try/except` per card
keeps it off the principal's 500. The route can reuse `_school_of` /
`_the_child` / `_require_may_read` / `cards.card_for` verbatim; `card_payload()`
is already the single assembly. `render_card_pdf` upserts on the card, so a
duplicate job is safe. 202-with-a-body is expressible in the house style
(`response={200: …, 202: …}`, `gradebook/api.py:383`), and ninja returns a raw
`HttpResponse` as-is (`operation.py:360`), so a binary 200 and a JSON 202
coexist in one operation.

## Conflicts

### 1. The constraint refuses the PENDING row, and a test pins the refusal by name

`a_card_pdf_is_a_file_or_a_reason_and_not_both` requires content XOR error; a
PENDING row has neither. `test_a_row_that_is_neither_a_file_nor_a_reason_is_refused`
(`results/tests/test_pdf.py:520`) asserts that by name, docstring *"A job that
reported nothing at all. Silence is the failure mode here."* That test inverts:
the row it refuses becomes the row release writes. The model docstring's "a row
with neither is a job that reported nothing" is now false and gets rewritten,
not left standing.

My recommendation is an explicit `state` column (`PENDING`/`BUILT`/`FAILED`,
`TextChoices` like `SheetState`) rather than inferring the state from two empty
columns — inferring PENDING from "no content and no error" is detecting the
marker by absence, the same shape as the options you rejected. It also lets the
CHECK refuse `BUILT` with no bytes and `FAILED` with no reason, which matters
because `render_card_pdf`'s success upsert and `on_failure`'s
`_record_the_failure()` both have to start setting it.

### 2. `revise()` writes cards too, and the brief only names release

`results/revision.py:163` freezes a new card in its own atomic block, and it is
the only path that gives a late-placed child (#31) a card at all.
Marker-at-release-only means a corrected card never renders, never appears in
the marker, and arrives at the download route as *no row* — a fourth case, which
is exactly the "no file vs no attempt" ambiguity the design exists to kill. I'd
put the marker write plus `on_commit` enqueue in one helper called from both.

### 3. Every card already released has no row

Same fourth case, permanently, for real data in every tenant schema. Either the
migration backfills a PENDING row per existing `ReleasedCard` (per-schema
`INSERT … SELECT`; django-tenants runs it in each), and old cards then self-heal
through your GET-enqueues-on-PENDING path — or the route carries a second branch
for "no row" for ever. **Your call: backfill or not.**

### 4. The DISTINCT ON guards a path the enqueuer isn't on

A sheet is released once (`0003`, and `revise()` refuses a sheet that isn't
already RELEASED), so at release time every card is version 1 and
`card_by_student` is already one per child — 46 jobs can't arise there. The
DISTINCT ON bites on `cards.cards_on()`, i.e. any re-enqueue that starts from a
sheet. Enqueuing ids from `card_by_student` also avoids `cards_on()` prefetching
every line and cell of 45 cards to throw them away. So the invariant you named
holds, by construction rather than by that query — which means `cards_on()`
stays uncalled and its stale docstring gets corrected without gaining the caller
you expected.

## One decision your spec leaves open

GET-enqueues-on-PENDING has no debounce, and results week is the load case:
release enqueues, the row stays PENDING for the seconds until the worker writes
BUILT, and every parent refreshing in that window enqueues another render of the
same card. Idempotent, so safe — but it multiplies exactly the load the queue
exists to smooth. A `QUEUED` state fixes it and reintroduces a stuck state with
no recovery, which is the hole you just closed. Cheapest fix that keeps your
three states: enqueue only if a conditional `update()` on `built_at` (already
`auto_now`) touches the row — atomic, no new column.

## Before I cut the branch

PR #65's CI came back green (`33711760630`, success, `dd251da`), it is
mergeable, and it is still open awaiting your merge word. It rewrites the body
of `freeze_the_card()` — the exact function #56 edits — so #56 wants to be cut
from main after #65 lands rather than from `bd28cdf`. Say the word on #65 and
I'll verify ancestry, then start #56 from there.
