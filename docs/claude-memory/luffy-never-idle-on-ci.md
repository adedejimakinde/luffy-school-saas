---
name: luffy-never-idle-on-ci
description: Never wait or poll on CI with the Codespace running — overlap the next task in a worktree off main, or say there is nothing to overlap and stop
metadata:
  type: feedback
---

Set 2026-08-30. The Codespace bills core-hours by wall-clock, so **an idle
session waiting on CI is money for nothing.**

**Never poll or monitor CI in a loop.** No `gh pr checks --watch`, no sleep-and-
retry, no background wait job. Push, say it is pushed, and move on. A *single*
status check at a natural checkpoint is fine; a loop is not.

**Overlap instead of waiting.** While task N's CI runs, build task N+1 — from
**`main`, in a second worktree**, never branched off task N. This does not
weaken the no-stacking rule in [[luffy-phase-1-workflow]]: both branches are
still cut from `main` and each still merges to `main` on its own. Concretely:
task 7 is built off `main` in its own worktree while task 6's CI runs.

**When there is genuinely nothing to overlap, say so explicitly and stop.** Do
not invent filler work to look busy. The user then stops the Codespace and
merges from the browser — that is the intended path, not a failure.

**Why:** waiting is the single largest avoidable cost in this project. CI takes
~47–49 minutes (see [[luffy-test-suite-runtime]]), and burning that as idle
Codespace time on every task is the difference between the machine costing
something and costing nothing.

**An armed waiter is not permission to poll on top of it.** Reinforced
2026-09-04 after I did exactly that: I set background `until` waiters on two PR
gates — the right mechanism — and then checked `gh pr checks` roughly a dozen
times anyway while they ran. The user's words: "The waiters fire; that's what
they're for. If you have nothing to build while they run, say so and stop rather
than sitting on the gates."

So: arm one waiter per gate, then **either build something or stop.** Re-checking
a gate a waiter is already watching is the polling loop this memory forbids,
wearing a different shape.

**How to apply:** after any push, the next sentence is either "here is what I am
building meanwhile" or "there is nothing to overlap — stop the Codespace." Never
"waiting for CI."
