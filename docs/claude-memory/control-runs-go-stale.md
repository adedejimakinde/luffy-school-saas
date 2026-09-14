---
name: control-runs-go-stale
description: A control run only speaks about the code it ran against; a review pass that edits that code invalidates every control taken before it, and controls must be run at module scope
metadata:
  type: feedback
---

Two rules about control runs, both learned the expensive way on PR #83.

**1. A control run is a statement about the code it was run against.** When a
review pass changes the code under test, every control measured before it is
stale — the PR body's controls described a tree that no longer existed. Re-run
both controls against the tree that actually merged, and post the corrected
output. Controls that disagree with the shipped code are worse than no controls,
because they read as evidence.

**2. Run the control over the whole module, not the narrow class slice.** The
19-test slice reported nine failures. The same control over all 69 tests
reported **ten** — the extra one was design test 7, a revision of a withheld card
served over `/pdf/`, and the narrow run never reached the class at all. The
narrow slice also left *"the other surface stays green"* **assumed** rather than
measured; only the wide run makes it an observation.

**Why:** a control exists to prove a test bites. Scoping it to the tests you
already expect to fail cannot discover the test you forgot, and re-using a
pre-review control silently attributes old evidence to new code.

**How to apply:** after `/code-review` changes anything, re-run every control at
module scope and post the output where the PR lives — a comment once the PR is
merged, since control outputs belong with the PR. Read the failure *values*, not
just the count: `202 != 403` said the bypass leaks the render state before it
ever serves a file, which is a different and worse bug than the one being tested
for.

See [[luffy-withholding-recovered]], [[luffy-open-work-state]],
[[pr-review-state-line]], [[code-review-target-by-pr-number]].
