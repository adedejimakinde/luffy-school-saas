---
name: classnode-state-2026-09-24
description: READ FIRST — Classnode state at end of 2026-09-24 session: #140/#141 merged, #144 (B1 fees) open awaiting CI+merge, B2 and T1 decisions, timetable WIP branch, fresh-Codespace setup
metadata:
  type: project
  modified: 2026-09-24T13:56:01.941Z
---

## State at ~14:00Z 2026-09-24 (session ended on usage limit, mid-work)

`main` = `1f35c05` (merge of #141). Repo: adedejimakinde/luffy-school-saas.

| item | state |
|---|---|
| #140 hosting H3 | MERGED `42689d4`, gated on head `48bc82c` (test+image green before merge), ancestry 0 |
| #141 absence view | MERGED `1f35c05`, gated on head `db8113d` (test 13:19Z, image 13:21Z), ancestry 0 for 1f35c05/db8113d/36c82d4/1a42422. Controls 5–8 posted as a comment; control 8 first stayed GREEN (may_see access-scoping unasserted) → test added in `36c82d4`, then red |
| #143 issue | filed: receipt "Received by" read live from User.full_name (rule 2); ReceiptOut docstring names it |
| **#144 B1 fees** | **OPEN, head `3587ae7`** (main merged in). CI `test` was in_progress (started 13:33:58Z). Local: 386 tests OK serial; JS 278 pass. Controls 1,1b,2–8 all red on target, table in PR body. **Next: gate on test+image success on the FULL head sha, then merge** |
| B2 billing screens | not started; must be cut from main AFTER #144 merges (no stacking) |
| T1 timetable | branch `timetable` `7b4b361` WIP, pushed, cut from 1f35c05 |

### Merging #144 (the standing rule)
`FULL=$(git rev-parse origin/fees-ledger)`; confirm equals `gh pr view 144 --json headRefOid`; all `/commits/$FULL/check-runs` conclusions success (test AND image; image `needs: test`); `gh pr merge 144 --merge --match-head-commit $FULL`; then `git merge-base --is-ancestor` for the merge commit and `3587ae7`, `df9e998`, `0404815`, `3750c8f`. **Never type a full sha from memory** — I did, and --match-head-commit refused it (good).

### B2 decisions (user, 2026-09-24)
- Same authority as B1: bursar+admin write, principal+VP academic read, others flat 404.
- **Fix #75 in B2**: revoking a concession needs a required reason and an append-only audit row (who, when, why); never edit or delete the concession row. Control: revoke without a reason is refused.
- Applying a schedule to a class must not double-charge a child already charged for that term — test + control.

### T1 decisions (user, 2026-09-24) and WIP
One bell schedule per school; subject+teacher per slot; double period = two slots; free = no slot; clash refused unless same subject (EXCLUDE constraint must allow same-subject combined lesson — test both); timetable per term with copy-last-term; all teachers read; admin + VP academic edit. T2 stays in #142 (after first-term results).
Done on `timetable`: app `timetable` (TENANT_APPS), models `Period` (tsrange EXCLUDE `periods_do_not_overlap`, `[)`), `TimetableSlot` (`one_lesson_per_class_per_slot`, `a_weekday_is_a_school_day`, EXCLUDE `a_teacher_teaches_one_subject_at_a_time` with subject `<>`), migration 0001 (`CREATE EXTENSION btree_gist WITH SCHEMA public` — must be public, see its docstring), services, API, router. **Clone fix**: `schools/tests/clone_tenant_schema.sql` did not copy contype 'x'; clone comparison test red before, green after.
Remaining: RUN `timetable/tests/test_timetable.py` (written, never run); page (views, template, static/timetable/*, urls, tests/test_pages PAGES, landing flag `may_see_timetable`?); JS tests; docs/timetable.md; controls 1–7 named in test docstrings (+ clone control: drop 'x' → clone test red); PR.

### Fresh-Codespace setup (all of this was lost last time)
- `gh` is not installed: download release tarball to `~/bin` (cli/cli latest linux_amd64). Auth comes from GITHUB_TOKEN (account only1ifeoluwa).
- `git config --local user.name "Adedeji Makinde"`; `user.email 153077464+adedeji-makinde@users.noreply.github.com` (global config had the wrong identity).
- `git config rerere.enabled true`.
- Tests: `DJANGO_DEBUG=1 scripts/run-tests.sh <labels> --noinput`, **serially** — `--parallel` crashed twice with `cannot pickle 'traceback'` and hid a real TypeError. Never two test runs at once (shared test_luffy_db).
- Control runner pattern: replace exact text (assert count), run labels, `git checkout -- file`, assert clean tree, grep `^Ran|^OK|^FAILED` and `RESULT=`. Run at module scope over every module that can reach the code.

See [[no-claude-attribution-on-github]], [[luffy-never-idle-on-ci]], [[luffy-phase-1-workflow]].
