> **POSTED — 2026-08-29T06:26:24Z.**
> https://github.com/adedejimakinde/luffy-school-saas/pull/35#issuecomment-5460808075
>
> Posted with `gh` as `only1paulo`, after confirming via the API that the PR
> carried only the original 13-findings review. PR #35 now has both comments.
>
> Two corrections were made to the text before posting, and the posted version
> is what went up rather than what is below the line here:
>
> - the headline hash `28236b8` → **`f2d682b`**. `28236b8` exists only in the
>   devcontainer's local clone (GitHub 422s it), was unreachable from every
>   branch, and was an earlier cut of the fix missing six lines of
>   `gradebook/services.py`.
> - "text for the follow-up issue is at the bottom" → "they are going into a
>   follow-up issue". That cross-reference was stale: the issue text is in
>   `issue-pr35-nonblocking-findings.md`, not in this file.
>
> A closing italic note was added recording that it went up after the merge.

## All five blocking findings fixed — `f2d682b`

Plus findings 6 and 12, which were one-line corrections inside docstrings the
blocking fixes were already rewriting. Findings 7, 8, 9, 10 and 11 are not
fixed here; text for the follow-up issue is at the bottom.

### The five

**1. `MarksLocked` escaped both endpoints as a 500.** Now a **423** on
`save_score()` and `clear_score()`, with the reasoning in `gradebook/api.py`:
409 in this API means "the row moved while you were typing" and a blur handler
answers it by reloading and retrying, which against a released term never
terminates; 403 is a refusal of *authority*, and the caller's authority has not
changed. `RatingsLocked` and `CommentsLocked` carry the same note so the same
refusal about the other two thirds of the card does not arrive as three codes —
neither has an HTTP surface yet (`results.api` is one read-only route), so the
rule is recorded where whoever adds one will read it. Four API tests.

**2. The frozen artefact — the one that mattered.** You were right, and the
premise was load-bearing: I conflated "the marks are frozen" with "a card was
released". `_require_this_card_has_not_gone_home()` now runs ahead of the
placement check in both write paths, keyed on `results_releasedtraitrating`
JOIN `results_resultsheet` the way `0011` does it, and migration `0002`'s
trigger gained the matching branch. Release JSS 1A, move the child to JSS 3B,
and the write is refused at both layers.

What is left is a **per-school** gap rather than a per-child one:
`freeze_for_release()` returns early when no group is enabled, so a
ratings-disabled school freezes nothing for anybody. That residue is #34's, and
it is the same one `ratings` carries. Two tests hold the line either side, and
the ratings-disabled one asserts its own precondition so it cannot start passing
for the wrong reason.

**3. `clear_score()` idempotency.** The guards now run *after* the check for a
row to delete. Nothing is written in that case, so a closed sheet has nothing to
protect. The existence check is deliberately unversioned: a row present at
another version is still a mark on a closed sheet, so it is `MarksLocked` rather
than `ScoreChangedMeanwhile` — which would send that caller round a loop
reloading something that cannot reopen. Three tests, including the retried
DELETE over HTTP.

**4. The escape hatch that did not exist.** Claim dropped rather than hatch
added. The trigger's narrowness stands on its own argument — `released` is
terminal, `submitted`/`checked` are a review-in-progress rule — and `0002` now
says so, and says explicitly that `ANY_VERSION` is not a stand-down. A bug-fix
PR is the wrong place to ship a bypass around the guard it is adding.

**5. The two factual errors.** The `open_sheet()` claim is corrected (it is a
`get_or_create`; the real reason to walk forward is that the states are a
sequence). The mis-named control is now two tests, one per state, and the
`submitted` one asserts both halves at once because the claim is about the
difference: the service refuses, the table does not.

**And a third the fix uncovered.** Asserting `sheet.state` failed: `walk_to()`
returned the instance it drove the steps with, and `submit()` and the rest
re-read under their own lock and update the row, not the caller's object — so
`state` read `draft` however far the chain had gone. It returns a re-read now.
Nothing had noticed because nothing had asked.

### Verification

29 tests in the module, all passing. **Four controls, one per fix**, each
reverting exactly that fix and nothing else:

| control | tests that stop passing |
| --- | --- |
| artefact guard removed (service) | the 3 moved-child tests |
| artefact branch removed (trigger) | `..._refused_by_the_database_too` |
| guards moved ahead of the idempotent exit | the 2 retried-clear tests |
| both API handlers removed | all 4 of the 423 tests |

No control produced a collateral failure, so each fix is pinned by tests that
detect its absence and nothing else's.

Worth recording, because it nearly cost the run: the first version of the
control harness restored with `git checkout --`, which reverts to HEAD — so
after the first control it silently wiped every uncommitted fix and the
remaining three "controls" ran against the original code. They looked like
convincing controls and proved nothing. It restores from copies now.
