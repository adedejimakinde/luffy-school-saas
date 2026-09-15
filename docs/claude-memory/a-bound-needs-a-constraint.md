---
name: a-bound-needs-a-constraint
description: "A safety bound asserted in prose must be derived from a constraint in the schema, not from an intuition about the domain — and a stated premise must be verified before acting on it"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d07c2d64-4203-482c-a30e-3c51db52e69a
  modified: 2026-09-11T03:35:53.768Z
---

Two failures of the same shape, both on 2026-09-11, both caught rather than
shipped — one by the reviewer, one by me.

## 1. A bound needs a constraint behind it

PR #86 removed the charge loop's savepoints and left the discount loop's, and I
justified that in a code comment, the PR body, the commit message and issue #85
with: *"a class cannot have more concessions than children."*

**It is false.** `FeeConcession` has **no unique constraint** on
`student_membership_id`, and its own docstring says so on purpose: *"Several
concessions per child is allowed, deliberately. A bursary and a sibling discount
are two facts and two DISCOUNT entries."* The real bound is `children x
concessions_per_child`, so 45 children with two concessions each is 90
savepoints — back over the 64-subxid cache, reproducing the exact bug the PR was
written to remove.

I reasoned from what a class *is* instead of reading what the schema *permits*.
The number sounded safe, so it never got checked.

**Corrected 2026-09-11** in all four places — `fees/schedules.py`, the test
docstring, the PR #86 body and issue #85's body — plus a fifth of the same
shape found while doing it: `_charge()`'s docstring quoting the one-INSERT
**control's** `12.29us` as a measurement of `_charge()`, which was never timed.
Same failure: a sentence that sounds measured and is not.

**Why it matters more than a wrong comment:** the false bound had already
propagated into an issue body, which would have scoped the follow-up work
against a limit that cannot be exceeded. A wrong bound does not merely fail to
protect — it argues against the fix.

**How to apply:** before writing "cannot be more than N", find the constraint,
index or validator that makes it so and name it. If there isn't one, the
sentence is "is usually under N, bounded by nothing", and that is a different
claim with different consequences. Same discipline as this repo's rule that a
coverage claim in prose goes stale — see [[luffy-session-arithmetic]] for the
tests that passed against broken code for the same reason.

## 2. Verify a stated premise before acting on it

The user asked me to open a PR for "the six review fixes, on merged code and not
yet on main". They were **already on `main`** — the review had run against the
branch before the merge and the fixes went into the single reviewable commit.
Opening the PR would have produced an empty diff.

Checking took one pass over `results/withholding.py` (finding 1's
`why_not_a_student_here` at `:49`/`:293`, `WithholdingError` at `:84`, and so
on) plus a scan of every worktree for uncommitted work. I reported that instead
of building, and the user accepted the correction — along with a second one, that
the savepoint conversation is #82 and not #2.

**How to apply:** when an instruction rests on a factual premise about repo
state — what is committed, what is merged, what is uncommitted — verify it
first and report if it does not hold. Do not produce an empty or duplicate
artefact to satisfy the letter of the request. The same check stopped a
duplicate comment being posted to #83 earlier in the same session, where memory
said the work was done and the remote confirmed it.

See [[luffy-open-work-state]], [[luffy-subtransaction-measurement]],
[[control-runs-go-stale]], [[pr-review-state-line]].
