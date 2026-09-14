# Task 3: the card itself, and the row that says it went home

Branch `report-card-snapshot`, commit `f582236`, off `main` at `90794bb`.

**NOT READY TO OPEN.** Two gates first:
1. the full suite has never been run on this branch;
2. `/code-review high` needs running — the session that wrote this ended before
   its findings came back.

Paste the commit message of `f582236` for the body; it was written as PR prose.
`git log -1 --format=%B f582236` gets it. What follows is the summary table only.

## What lands

| | |
| --- | --- |
| `ReleasedCard` | the artefact — one row per child per release, **unconditional** |
| `ReleasedSubjectResult` | one per (card, subject): marks, percentage, **copied grade letter**, staff-only subject position |
| `ReleasedAssessmentScore` | one per (card, assessment): the CA/exam cells |
| `card` FK | added non-null to the three older frozen tables, backfilled |
| `results/cards.py` | the freeze and the read path |
| `0016`, `0017`, `0018` | schema, backfill-and-tighten, append-only triggers |
| `docs/cards.md` | the page |

`positions.ClassResults` gains `totals` and `scored_and_available()` — the raw
`(scored, available)` it already computed and discarded, kept because a card
prints "58/70" beside the percentage and re-reading would be a second read at a
second instant.

## Verification as it stands

33 tests in `results/tests/test_cards.py`; the 54 existing session tests pass
against the now-required `card` FK. Two controls on the unconditional write:

| control | what stops passing |
| --- | --- |
| freeze made conditional on the conduct section | 3 of 5 marker tests |
| only children with marks get a card | 3 of 5 marker tests |

## Closes

**#34** in substance — the per-child "a card went home" marker, unconditional.
**#31** and **#33** point at the same thing; check whether they close too.

## Filed, not fixed

**#42** — `Assessment` has no print order, so papers sort alphabetically. The
freeze uses creation order. Matters because the order is **frozen**: a wrong
guess is frozen too.
