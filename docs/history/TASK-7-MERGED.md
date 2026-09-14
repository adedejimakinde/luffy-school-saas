# Task 7 is merged — where luffy-school-saas stands

*2026-09-02*

## What I did

**PR #62 (task 7, the report card as a PDF) is on `main`.** CI was green
(`test` pass, 31m23s) and the branch had already been through two rounds of
`/code-review high`, so it met the standing merge word exactly. Merged as a
merge commit; `main` moved `2e9ddd7` → **`16dd75c`**.

Ancestry check, per the rule that a "merged" badge is not the same claim as
reachability:

```
git merge-base --is-ancestor bf5d956 origin/main  →  yes
```

**All of Phase 1's numbered tasks are now on `main`.**

CI on `main` for `16dd75c` is running (run `33649097683`). I'm not sitting on
it — you'll want to glance at it before anything builds on top.

### The four commits that landed

| commit | what |
| --- | --- |
| `07a9aa7` | Task 7: the card as a file, and the three absences a page must not confuse |
| `8b0f297` | Act on the review: a badge that could never print, and marks without their totals |
| `ad85fe7` | Rebase onto task 8: a migration renumbered, and a rule that now has one name |
| `bf5d956` | Act on the review: fifteen lines of developer prose printed on the card |

## What's open, and what I did not do

**PR #63 `loud-test-failures` — green, clean, and I left it alone.** The merge
word covered task 8 and task 7; both are in, so it's spent. #63 isn't
authorised and I didn't treat it as if it were.

Its state, so the decision is cheap:

- One commit, `0477cb9`. `MERGEABLE` / `CLEAN`.
- Five commits behind `main` but **conflict-free** — it touches only
  `.github/workflows/tests.yml`, `scripts/run-tests.sh`, `tests/__init__.py`,
  `tests/test_loud_failures.py`. Zero overlap with task 7's files.
- Its own CI passed in 25m48s.

One thing worth weighing before you give a word on it: **that green run was on a
base without task 7's 32 `test_pdf` tests.** The new runner has never actually
driven the current full suite. Rebasing it onto `16dd75c` and letting CI re-run
would turn "the wrapper works" into "the wrapper works on the suite we now
have" — cheap insurance for a change whose entire purpose is that a run can't
lie about its own result.

## After that

The remaining work is all issues, none of it authorised:

- **#56** `must-fix-before-pilot` — nothing enqueues the render, no route serves
  the file, no rebuild path. The missing enqueuer must keep task 8's
  `DISTINCT ON (student_membership_id) … version DESC`, or a 45-child class
  enqueues 46 jobs and sends a superseded card home.
- **#60** `must-fix-before-release` — one `ClassPlacement` read per sheet-locked
  block; you already settled the fix shape (pass the snapshot down, don't widen
  the lock).
- **#54** — you asked for options explicitly and not a pick. Four are written up
  as a comment there. Still yours.
- **#58**, **#61**, **#42** — smaller, unscheduled.

Say the word on #63 (rebase-then-merge, or merge as-is), or point me at an
issue.
