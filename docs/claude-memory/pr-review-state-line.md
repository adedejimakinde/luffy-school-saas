---
name: pr-review-state-line
description: Before asking the user to review a PR, state in one line that the worktree is clean and name the branch head being reviewed
metadata:
  type: feedback
---

Set 2026-09-05, after PR #79. **Before I ask the user to review a PR, I confirm the
worktree is clean and that the branch head is what they are reviewing — stated
explicitly, one line, every time.** Not implied, not assumed from a diff I ran earlier.

**Why:** on PR #79 the `fee-schedule-billing` worktree carried *uncommitted* work that
included a **billing behaviour change** — `apply_to_class()` skipping children whose
membership had ended, which silently redefined `AppliedSummary.students` from "on the
roster" to "billed". It was outside the PR description the user reviewed, so it got the
least scrutiny of anything in the PR while changing the money path. The user's framing:
this is the process finding, not a footnote.

The failure is not "I forgot to commit". It is that the artefact the user reviewed and
the code that actually exists were different things, and nothing in my report said so —
the same shape as the merged-badge-vs-reachability trap in [[luffy-phase-1-workflow]]
and the artefact-not-placement rule in [[luffy-release-marker-requirement]].

**How to apply:** `git status --short` in the worktree and `git log --oneline -1` before
the review request. If anything is uncommitted, commit it or name it in the request —
never let behaviour changes ride along outside the description. Say the head SHA out
loud so a later reader can tell whether the review still applies; when work lands after
a review, the review's SHA is stale and must be re-stated.
