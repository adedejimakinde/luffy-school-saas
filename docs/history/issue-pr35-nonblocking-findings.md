# PR #35 review: the non-blocking findings, filed rather than fixed

`/code-review` on `score-write-guard` returned 13 findings. Five were blocking
and are fixed on the branch. Two more (6 and 12) were one-line corrections
inside docstrings the blocking fixes were already rewriting, so they went with
them. These five are the remainder — real, and deliberately not done in a
bug-fix PR.

## 7. The lock claim in `gradebook/services._require_the_sheet_is_open()` has no test

The function takes `results.services.locked_sheet_for()` — a `SELECT ... FOR
UPDATE` — and the docstring rests the whole check-then-act argument on it.
Swapping it for the unlocked `sheet_for()` twin passes every test in
`gradebook/tests/test_release_guard.py`.

`results` pins exactly this in two concurrency modules, including assertions on
the captured SQL shape (`test_approval_concurrency.LockScopeTests`). The
gradebook half should be pinned the same way, and the same module is where the
`Meta.ordering` join hazard would be caught if `locked_sheet_for()` ever
regressed.

## 8. Third near-verbatim copy of the closed-sheet branch

`gradebook/services.py`, `results/ratings.py` and `results/comments.py` each
hold the same shape: look the sheet up, ask `is_open_for_writing()`, branch on
`RELEASED` versus everything else. Only the two refusal *sentences* are local
vocabulary, and those are local on purpose — a teacher reads them.

A shared `closed_because(sheet)` in `results.services` returning the state,
leaving each app to phrase its own refusal, would remove the third copy without
touching the wording. Same shape as the `sheet_for()` duplication an earlier
review had to unwind, and worth doing before a fourth writer appears.

## 9. `placement.class_group` is a lazy dereference on the write path

`academics.services.placement_of()` has no `select_related`, so
`_require_the_sheet_is_open()` costs three queries per write where two would do
— the third fetches a `ClassGroup` only to render it into a refusal that is
usually never raised. Around 450 avoidable round trips for a 45-child, 10-
assessment term-end import.

`placement_of()` is shared, so the fix is either a `select_related("class_group")`
there (paid by every caller, most of which want the group anyway) or a
`.only()`-style variant here. Worth measuring before choosing.

## 10. `test_release_guard.py` builds a second tenant schema it never uses

It inherits `PositionSetUp`, which creates St Mary's *and* Grace Academy. The
release-guard tests touch only St Mary's. Per-test tenant schema creation is
most of this suite's runtime — around 25 tests now paying for a schema nothing
reads, on a suite already near 30 minutes.

Note the tension with the project rule to test with 2+ tenants: the right fix is
a fixture whose second school is *used* by a cross-tenant test, not one that is
built and ignored.

## 11. Gradebook's tests import fixtures from `results/tests/test_positions.py`

`PASSWORD`, `PositionSetUp` and `connected_to` are imported across app
boundaries, so a change to a `results` test module can now break the gradebook
suite. A shared harness belongs in a helper module both import — not in a
sibling app's test file.

Closely related to #36: the reason the gradebook suite reached for `results`'
fixtures at all is that its own build a school with no `ClassGroup` and no
`ClassPlacement`, which is what let a placement-keyed guard go silently
untested. Fixing #36 and this together is probably one piece of work.
