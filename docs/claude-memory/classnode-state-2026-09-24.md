---
name: classnode-state-2026-09-24
description: READ FIRST — Classnode state late 2026-09-24 (session 3): #144 merged; T1 timetable and B2 billing built and under controls; demo seed PR #145 open (not to merge without a word); demo served on ports 8002/8001
metadata:
  type: project
  modified: 2026-09-24T17:27:49.996Z
---

## State ~19:20Z 2026-09-24 (session 3)

`main` = `6a7962e` (#144–#147 merged). Repo: adedejimakinde/luffy-school-saas. `gh` at `~/bin/gh` (PATH). #75 closed by #147.

| item | state |
|---|---|
| **#145 demo seed** | MERGED `206191e` (user's word), gated on 8141373; ancestry 0 |
| **#146 T1 timetable** | MERGED `68fb9cd`, gated on 9441453; ancestry 0 |
| **#147 B2 billing** | MERGED `6a7962e`, gated on 56ed7dc test+image; ancestry 0 for 6a7962e/56ed7dc/b42eb15/324b6fd. Controls B2-1..12 in PR body |
| **#148 seed: timetable + bills + revoked concession** | OPEN, head `ca72b81` (branch `demo-seed-more`, worktree `~/worktrees/demo-seed-more`). 3 tests OK EXIT=0 on main+it; 2 controls red. **Needs the user's merge word** (seed PRs are not under the standing rule) |
| **Demo** | dev DB `luffy_db` rebuilt from main 6a7962e + seeded from ca72b81 at ~19:16Z. Served from `/workspace` (main, `--noreload`): portal https://sturdy-guide-p7wwr6jv65wg29wvp-8002.app.github.dev/sign-in/ (PID 79335), Sunrise https://…-8001.app.github.dev/ (PID 79336). Password `demo-pass-2026`; `sunrise.admin/.principal/.vp/.teacher/.bursar/.english/.science/.parent`. Restart: kill PIDs, `bash ~/luffy-handover/demo/serve-demo.sh`. Re-seed = drop/create luffy_db, `migrate_schemas --shared`, `PORTAL_HOST=<8002 host> setup_portal`, `seed_demo --domain-suffix localhost`, set Sunrise primary Domain to the 8001 host |

### B2 reading of the user's rule (flag it in the PR and report)
"Applying a schedule must not double-charge a child already charged for that term" read as: skip a child with an UNREVERSED CHARGE in the term from ANOTHER bill's line (mid-term move), besides the existing same-bill skip. This overturned docs/fees.md's old deliberate "charged by both bills" rule. Term row lock `FOR NO KEY UPDATE` serialises bills in a term. Revert = billed-elsewhere skip + term lock in fees/schedules.py.

### Running tests in parallel safely
A second test run is safe on a DIFFERENT database name: `POSTGRES_DB=luffy_b2check` → test DB `test_luffy_b2check`; the runner's backend sweep only matches its own name. The named DB must exist (create it via psycopg2 on `postgres`). Drop scratch DBs when done. Still never two runs on `test_luffy_db`. **And never from the same worktree as a control run** — the controls mutate files, so a parallel baseline can import a mutated module; use a detached worktree at the commit (`git worktree add --detach <path> <sha>`). Caught myself on 2026-09-24 before reading a result.

### Merging (the standing rule)
`FULL=$(git rev-parse origin/<branch>)` = `gh pr view N --json headRefOid`; `/commits/$FULL/check-runs` total_count ≥ 1, all completed, test AND image success; `gh pr merge N --merge --match-head-commit $FULL`; then `git merge-base --is-ancestor` for merge commit and head. Never type a sha from memory.

### Fresh-Codespace setup
gh tarball to `~/bin`; `git config --local user.name "Adedeji Makinde"`, `user.email 153077464+adedeji-makinde@users.noreply.github.com`; `rerere.enabled true`. Tests: `DJANGO_DEBUG=1 INVITATION_ACCEPT_URL=… EMAIL_BACKEND=…console… scripts/run-tests.sh <labels> --noinput`, serially per DB, stdout to a file to keep EXIT=/RESULT=.

See [[no-claude-attribution-on-github]], [[luffy-never-idle-on-ci]], [[luffy-phase-1-workflow]].

### Where things live (persistent)
`~/luffy-handover/demo/`: serve-demo.sh, demo_settings.py (the forwarded-host settings wrapper), e2e.sh (sign in on the portal through the forwarded URL, then open school paths), gate.sh (CI gate on a SHA), and the control runners. `/tmp` is wiped when the Codespace restarts, and so are the running demo servers, so restart them with `bash ~/luffy-handover/demo/serve-demo.sh`. The dev DB persists in the `db` service.

### Next session
1. #148 is waiting on the user's merge word. When it comes, gate on `ca72b81` (or the current head) and merge.
2. Nothing else is open from this batch. T2 is #142.
