Folds **#46** and **#59**, which were two reports of one pattern. #43 was the third, and it is already fixed — its fix is the template.

## The pattern

> A read of `ClassPlacement` (directly, or through `positions.roster_ids()` / `positions.class_results()`) made **inside a block holding the `ResultSheet` lock**, asking a question something upstream in the same block has already answered.

The `ResultSheet` row lock reaches the `ResultSheet` row and nothing else. `ClassPlacement` is not locked, and Postgres runs READ COMMITTED, so every statement inside the transaction takes a fresh snapshot. Two reads of the roster inside one locked block can therefore return two different rosters, and the code between them has no way to know which one it is acting on.

**#43's fix is the template**: `cards.freeze_for_release()` performs the one read and *returns* the roster it found; `ratings`, `comments` and `sessions` take that map as an argument instead of asking again. Pass the answer down; do not re-derive it.

Filing this as the pattern rather than per instance, because three occurrences means a fourth — and the audit below found one nobody had reported.

## The audit

Every `roster_ids()` / `class_results()` / direct `ClassPlacement` read reachable from inside a `_locked()` block. There are exactly two such blocks in production code: `services._move()` (line 543) and `revision.revise()` (line 150).

| site | reached from | kind | status |
| --- | --- | --- | --- |
| `results/cards.py:217` — `freeze_for_release()` → `class_results()` | `_move()` | **authoritative** | correct; this is the single read #43 established |
| `results/cards.py:245` — `freeze_a_revision()` → `class_results()` | `revise()` | **authoritative** | correct; the revision path's equivalent |
| `results/sessions.py:386` — `_lines_for()` → `ClassPlacement.objects.filter()` | `_move()` **and** `revise()` | redundant | was #46 |
| `results/revision.py:216` — `_require_still_on_this_roster()` → `roster_ids()` | `revise()` | redundant | was #59 |
| `results/services.py:701` — `_say_if_the_roster_moved()` → `roster_ids()` | `_move()` | second read **by design** | see below — the fourth, unreported |

**So it is five call sites, not three.** Two are the authoritative read and must stay. Two are redundant re-reads. One is a deliberate second read whose answer is unstable for the same reason.

Because the `sessions` read happens on *both* paths, that is **four instances of the defect across the two code paths**, not three.

Reads that are *not* inside a locked block, and are fine: `comments.missing()`, `ratings.unrated()`, `api.py:199` (the broadsheet), and `positions.py`'s own internals.

## The fourth one, which nobody had filed

`services._say_if_the_roster_moved()` re-reads the roster to compare it against the frozen one, and reporting a change is its whole purpose — so unlike the other two this second read is not accidental.

It is still caught by the pattern. It compares the frozen roster against a **fresh** read, so it cannot distinguish "the office moved a child during the release" from "my own second read raced the first one", and it cannot see a move that lands after *it* runs. Its output is the log line issue #47 is about — so #47 is downstream of this, and a fix here changes what #47 has to say.

## What each one costs

- **`sessions._lines_for()` (was #46).** The card carries the child's third-term marks and the session line calls her `NOT_ENROLLED` for third term, renormalised over two — two rows written in one transaction that contradict each other. The module's own docstring says passing the roster down does not reach this one: it needs that term's *placements*, not just who is on the roster.
- **`revision._require_still_on_this_roster()` (was #59).** The guard reads the roster, `freeze_a_revision()` reads it again, and a placement moved between them writes a **blank version 2** — no marks, no totals, no position, no average — over a card that had all four. Every value is individually legal so no constraint objects, and both versions are append-only. Lowest probability, worst consequence.
- **`services._say_if_the_roster_moved()`.** A report that can be wrong in both directions.

## Shape of the fix

One read per locked block, threaded through everything that needs it — the #43 shape, extended:

- `class_results()` is already the single read on each path. What it returns has to reach `sessions` as well, and it has to carry **the placements**, not only the roster ids, or #46 is not closed.
- `_require_still_on_this_roster()` should check the `ClassResults` the freeze is about to use rather than asking the same question separately. That is a signature change to `freeze_a_revision()`.
- `_say_if_the_roster_moved()` should compare against that same snapshot, so that what it reports is "what this release saw", which is the only claim it can actually support.

The alternative for all four is a lock that covers `ClassPlacement` for the class and term. Wider, and it would serialise the office against every release — worth pricing before choosing, not assumed off the table.

## Closes

- #46 — the session line re-reads `ClassPlacement` for the term being released
- #59 — `revise()` reads the roster twice

Both are the same defect and are folded here. #47 is downstream of the fourth site.
