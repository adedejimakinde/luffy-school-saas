---
name: code-review-target-by-pr-number
description: /code-review forks inherit the session's working directory — target it by PR number, and re-check the tree afterwards
metadata:
  type: feedback
---

Set 2026-09-05, after PR #79 got two mis-aimed review passes in one session.

**Target `/code-review` by PR number, never by branch name.** The skill runs as a
fork that inherits the session's working directory, so `\/code-review high
<branch>` reviews `git diff main...HEAD` **of whatever branch the cwd is on** and
silently ignores the branch argument. On PR #79 that meant a pass launched with
`fee-schedule-billing` reviewed `/workspace`'s `phase-2-fee-design` diff — the
design document — and reported nine findings about the wrong artefact. It is the
same miss the user had already flagged once ("the last pass audited /workspace's
diff, so billing has had none"), reached again by a different route.
`/code-review high 79` reviewed the right tree.

**Check the working tree after the review returns.** The PR-number pass checked the
PR out *in `/workspace`*, leaving it detached at the PR head with the branch's own
commits invisible — a committed file appeared to have vanished. `git checkout
<branch>` restores it; nothing is lost, but a review that moves the tree it was
asked to describe will mislead the next command that runs there.

**A reviewer's caveats are load-bearing — read them before the findings.** This pass
reported it could not complete a test run because a broken test database was in the
way, which made it a reading pass rather than an executed one. That database came
from my own `manage.py test` run killed on a timeout; a killed run leaves
`test_luffy_db` behind and the next `--noinput` run can come back with a spray of
unrelated errors. Re-run clean before believing a regression — see
[[luffy-test-suite-runtime]].

**How to apply:** `\/code-review <effort> <PR number>`; afterwards, `git status` and
`git log --oneline -1` in every worktree the review could have touched, and state
the head per [[pr-review-state-line]].
