Closes #42.

> **Note on the issue itself:** #42 was closed on 2026-09-02, two seconds after
> #62 merged, with no commit and no closing keyword — a manual close alongside
> that merge, and my mistake. #62's own body said "the issue is unchanged". It is
> reopened, with the evidence, in [a comment on the issue](https://github.com/adedejimakinde/luffy-school-saas/issues/42).

## The bug

`Assessment` had no field saying where it printed. `Meta.ordering` ended in
`name` — alphabetical, so a term's papers sorted "Exam, First CA, Second CA",
which is neither the order they were sat nor the order a Nigerian report card
prints. `cards._assessments_for()` worked around it by sorting on
`(subject name, id)` — creation order — and said in its own docstring that this
was a guess.

It was `must-fix-before-release` because the order is frozen onto each card at
release: **a wrong order cannot be corrected on cards already in a parent's
hand.**

## The change

`Assessment.position` — explicit, smallest first, deliberately **not** unique per
`(term, subject)`. The same shape and the same argument as
`results.Trait.position`: a unique constraint there makes the ordinary edit,
swapping two papers round, impossible without a temporary value or a deferred
constraint. `Meta.ordering` gains it ahead of `name` and ends in `id`, so the
order is total. The freeze orders by `(subject name, position, id)`.

## The backfill writes the order down rather than improving it

`gradebook.0003` numbers existing papers by creation order, in tens.

Cards already released were frozen under creation order. A backfill that
reshuffled would make cards released tomorrow disagree with cards sent home last
term — same child, same term, different columns — and nothing could reconcile
them.

**A name heuristic was considered and rejected.** "First CA" first, "Exam" last
is right only for the names it recognises, and silently reorders everything else:
"Test 1", "CA1", "Mid-Term", a label in a language it does not read. That is the
ordinary contents of the column, not an edge case, and the failure is invisible
until a parent compares two cards.

Tens rather than ones, so a paper can be inserted between two others without
renumbering. Schools set the order they want from here on; the migration only
stops the old one being lost in the move.

## Verification

| Run | Result |
| --- | --- |
| `makemigrations --check --dry-run` | `No changes detected`, exit 0 |
| Seven tests, two schools | `Ran 7 tests in 26.146s`, `OK`, `EXIT=0` |
| **Control A** — backfill made a no-op | `FAILED (failures=4)`, `EXIT=1` |
| **Control B** — backfill numbers alphabetically | `FAILED (failures=6)`, `EXIT=1` |

**A and B are a matched pair.** Both break the numbering, so both fail the four
tests asserting it. B additionally *reshuffles*, and that is the only difference
between them — so the two tests only B fails are exactly the reshuffle
detectors: `test_the_printed_order_is_byte_identical_across_the_backfill` and
`test_a_card_frozen_after_the_backfill_agrees_with_one_frozen_before`.

The backfill is run as Django runs it: the migration's own function, imported
rather than copied, called with the **historical registry** — models rebuilt from
migration state. Handing it `django.apps` would test different code, and
different in the direction that hides bugs.

Papers are created "First CA", "Second CA", "Exam" — an order alphabetical
sorting cannot reproduce. In the base setup's first term the two happen to
coincide, so these go in a term of their own;
`test_the_order_is_the_one_sat_and_not_the_alphabetical_one` guards that premise
out loud.

`test_the_staging_is_real` guards the case that hid `0017`'s deploy-stopper: an
empty table makes the backfill a silent no-op and every other assertion vacuous.

## A test that nearly proved nothing

Worth recording. The frozen-card test first read a released card's rows, ran the
backfill, and read them again. It passed — and would have passed against *any*
backfill, because the migration writes to `Assessment` and never to a released
card, so those rows could not have differed. Control B left it green, which is
how it was caught.

It now releases, backfills, then **reissues**, and compares version 2's columns
against version 1's — two versions of one child's card for one term, which is
the disagreement this whole decision exists to prevent.
`ReleasedAssessmentScore.position` is an ordinal from `enumerate()`, not a copy
of `Assessment.position`, so it follows the ordering: a reshuffling backfill puts
different names against the same numbers and the comparison fails.

## Stale prose this would have left behind

`results/models.py`'s `ReleasedAssessmentScore` docstring, `docs/cards.md`'s
"Known gap" section and `docs/report-card-pdf.md` all described the missing
field as a live gap and pointed here. All three now describe what the code does.

## Overlap with #68 and #69

Cut from `main` at `54ec826`; `origin/main` (`9572a93`, with #68 merged) is
merged in here, and CI runs against that merge rather than the older base. File
sets are disjoint from both #68 and #69 — checked rather than assumed, after the
#66/#68 merge showed a clean `git merge-tree` is not the same claim.
