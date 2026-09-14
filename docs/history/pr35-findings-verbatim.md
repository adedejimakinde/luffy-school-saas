# PR #35 review findings — verbatim copy of the live comment

Fetched from the GitHub API on 2026-08-26. Kept because the API was
rate-limited for ~9 minutes when this was first needed, and this is the
authoritative list the triage refers to.

_only1paulo, 2026-08-26T10:51:49Z_

## `/code-review` findings — 13, and this PR should NOT merge as it stands

Recording in full, with triage. Session context may be lost; this is the live copy.

### Blocking — must fix before merge

**1. `MarksLocked` escapes both HTTP endpoints as a 500.** `gradebook/api.py:426`
`save_score()` catches `NotAllowedToMark`, `ScoreChangedMeanwhile`,
`NotThisSchoolsStudent`, `InvalidScore` — not the new exception — and declares
only 200/403/409/422. Same at `clear_score()` line 485 (200/403/409). So the
entire refusal path this PR adds surfaces as an unhandled traceback instead of
the sentence it was written to say. No API test covers the locked case.

**2. The frozen artefact I said did not exist, does.** `gradebook/services.py:196`.
I justified the placement key with "nothing freezes marks until task 3" — but the
guarantee being enforced is *a card went home for this child*, and
`results_releasedtraitrating` JOIN `results_resultsheet` on `(term, student)`
answers exactly that, which is what `0011` already keys on. For a
ratings-enabled school the common case is closable **now**, with placement as
the fallback the way `0011` does it. My premise conflated "marks are frozen"
with "a card was released", and they are not the same claim. This is the most
serious finding.

**3. `clear_score()` is no longer idempotent.** `gradebook/services.py:464`. Its
docstring promises "a retried request should not fail because it succeeded the
first time"; the guard now runs before the delete, so a retried DELETE of an
already-cleared mark on a non-draft sheet raises instead of returning silently
— and via the API, as a 500 (see 1).

**4. The migration's own rationale names an escape hatch that does not exist.**
`0002`, line 17: it justifies trigger narrowness because the service "can be
told to stand down for one import". `set_score()` runs the guard before
dispatching on `ANY_VERSION`, so the documented bulk-import sentinel is refused
too. Either add the hatch or stop claiming it.

**5. Two factual errors I wrote into tests.**
- `test_release_guard.py:139` — docstring says `open_sheet()` "refuses a class
  that already has one". It is a `get_or_create` whose docstring says the
  opposite. The walk-forward structure is right; the stated reason is wrong.
- `test_release_guard.py:290` — `test_the_database_still_permits_a_draft_terms_marks`
  walks to `submitted`, not `draft`. The named control is not the control
  performed, and no test asserts the trigger permits a write against an actual
  `draft` sheet.

### Real, non-blocking — fix here or file

**6.** `gradebook/services.py:200` — the pre-sheet race is undocumented.
`locked_sheet_for()` returns `None` and locks nothing when no sheet exists, so
the "check and act in one transaction" claim does not hold for that case.
`results.ratings` documents the identical residue and files it as #30; this copy
asserts the lock closes the race with no qualification.

**7.** `gradebook/services.py:167` — the central lock claim has no test.
`results` has two concurrency modules pinning exactly this, including SQL-shape
assertions. Swapping `locked_sheet_for()` for its unlocked twin would pass all
15 new tests.

**8.** `gradebook/services.py:143` — third near-verbatim copy of
lookup → `is_open_for_writing` → released/reviewing branch. Only the two
sentences are local vocabulary. A shared `closed_because(sheet)` would leave
each app its wording. Same shape as the `sheet_for()` duplication a previous
review had to unwind.

**9.** `gradebook/services.py:200` — `placement.class_group` is a lazy FK
dereference; `placement_of()` has no `select_related`. Three queries per write,
one pure waste; ~450 avoidable round trips for a 45×10 term-end import.

**10.** `test_release_guard.py:46` — inherits `PositionSetUp`, which builds
**two** tenant schemas per test; the second school is never used. 15 tests × 2
schema builds added to an already ~28-minute suite.

**11.** `test_release_guard.py:39` — gradebook's suite now imports fixtures from
`results/tests/test_positions.py`, coupling two apps' test suites. Related to
the fixture gap in #36; a shared harness belongs in a helper module, not a
sibling app's test file.

**12.** `gradebook/services.py:197` — `_require_the_sheet_is_open()` returns a
value neither call site uses. Dead surface implying the sheet is handed on.

### Status

Branch `score-write-guard`, commit `a6697e9`, pushed. **Not merged.** `main` is
at `8eb98fb` (828 tests green) and is unaffected by any of this.
