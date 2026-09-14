# luffy-school-saas — session handover, 2026-08-26

Everything here was in the Claude Code session scratchpad, which is deleted
between sessions. None of it belongs in the repo (it is PR and issue text, not
project documentation), so it lives here instead.

**All code is in git and pushed.** Nothing in this folder is code.

| file | what it is | still needed? |
| --- | --- | --- |
| `task9-pr-body.md` | body for the task 9 PR | **done** — PR #37, merged as `015fd31` |
| `issue-pr35-nonblocking-findings.md` | the five non-blocking PR #35 findings | **done** — filed as issue #38 |
| `pr35-comment-POSTED.md` | verification comment for PR #35 | **done** — posted 2026-08-29, comment 5460808075 |
| `pr35-findings-verbatim.md` | the original 13 findings, verbatim | reference |
| `control-harness-pr35.sh` | the one-control-per-fix harness | reference / reusable |
| `control-results-pr35.txt` | what each control broke | reference |
| `commit-task9-message.txt` | commit `b1409a3`'s message | reference (also in git) |
| `commit-pr35-review-message.txt` | commit `f2d682b`'s message | reference (also in git) |

## Repo state

- `main` = **`a1884a1`**, pushed. Issue #27's mark guard plus its review fixes.
- `three-term-view` = **`b1409a3`**, pushed, **unmerged, no PR opened**.
  Task 9. Verified green: **906 tests**, full suite, ~39 minutes.

There is no `gh` CLI in this devcontainer, which is why the PR and the issues
are drafts rather than filed. `git push` over https works fine.

## One warning about the harness

`control-harness-pr35.sh` restores from **copies**, deliberately. Its first
version restored with `git checkout --`, which reverts to HEAD — so after the
first control it silently wiped every uncommitted fix, and the remaining three
"controls" ran against the original unfixed code and looked like convincing
controls. Commit before running anything that reverts files.

## Update, 2026-08-29

A pre-merge review of task 9 (handover step 2) found and fixed one bug:
`three-term-view` is now at **`b1e093b`**, pushed. A third-term release raised
an `IntegrityError` for the whole class when the school's weighting counted a
term at nothing (`0/0/100` and an unmarked third term). Fix, migration `0014`,
five new tests and three controls are in that commit; `task9-pr-body.md` has
the section to paste.

*(Superseded by the section below — both were done later the same day.)*

## Closed out, 2026-08-29

**Nothing in this folder is still waiting on anybody.** `gh` was installed, and
with it: PR #37 opened and merged (`main` = `015fd31`, ancestry verified by
`git merge-base --is-ancestor`, exit 0), the PR #35 verification comment posted
(comment 5460808075, with the `28236b8` → `f2d682b` correction), and the five
non-blocking findings filed as issue #38.

What remains here is **reference**: the verbatim findings, the control harness
and its results, and the two commit messages. Kept because the reasoning is the
best record of each finding, not because anything is outstanding.

## Session end, 2026-08-29 (usage limit)

`main` = **`90794bb`**. Merged this session: task 9 (PR #37, `015fd31`) and the
grading scale (PR #41).

**Task 3 is committed and pushed but unverified and unmerged** — branch
`report-card-snapshot`, commit `f582236`. Two things are outstanding and neither
is optional:

1. the **full suite has never been run** on it — only `test_cards` (33) and
   `test_sessions` (54);
2. **`/code-review high` was running when the session ended and its findings
   were lost.** Re-run it. The two previous PRs each returned six real findings.

Then PR → fold in findings → merge → `git merge-base --is-ancestor f582236
origin/main` → task 6.

After that, with no stops: task 6 (card page, snapshot-only, staff-only fields
excluded **at the serializer**), the Celery/Redis/WeasyPrint infra PR, task 7
(PDF; measure 45 cards, report the seconds, continue even if over 90s), task 8
(revision → new version, both kept, "Revised" on the card, principal + audited
platform-staff path).

Full detail is in the `luffy-open-work-state` and `luffy-snapshot-architecture`
memories, which are the durable copy — this folder is reference only.

### Where the interrupted review's transcript lives

`/code-review high` on `report-card-snapshot` was ~30 seconds in when the
session ended, so it has no findings — **re-run it, do not go looking**. If a
future interrupted agent *does* need recovering, its transcript is a `.jsonl`
under `/tmp/claude-1000/-workspace/<session-id>/tasks/<task-id>.output`, and
`/tmp` does not survive a container restart. The session transcript itself is at
`~/.claude/projects/-workspace/<session-id>.jsonl`, which does.
