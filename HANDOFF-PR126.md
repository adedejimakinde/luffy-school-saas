# Handoff — PR #126 is open and **unfinished**

Written 2026-09-21 when a session ran out of budget mid-task. Delete this file
once #126 is merged.

## State

- `main` = **9c50c2d** (merge of #124, which closed issue #122).
- Branch `staff-landing-and-register-screen`, head **9290072**, 8 commits,
  pushed. Working tree clean.
- **Do not merge #126 yet.** See "What is left" below.

## What is left

**Only the merge.** Everything else is done:

- **Controls: all six run, all six reddened**, serially. Baseline green either
  side; tree restored clean; a confirmation run afterwards came back
  `EXIT=0 RESULT=OK` (98 tests) and `JS 104/0`. The table is in
  `docs/sign-in-page.md`.
- **CI: green on the head SHA `5b145c9`**, and on every earlier SHA that
  touches code (`71d9ffc`, `073da51`, `3902faf`).

So the remaining sequence is: merge gated on the head SHA → ancestry both ways →
fast-forward local `main` → delete the remote branch → delete this file and
`scripts/controls-pr126.sh` (both exist only in case this PR was handed over
mid-flight) and `PR-A-CONTROLS.md`.

It was **not** merged in the session that built it, because the instruction for
this PR was to report when it was pushed with CI and controls done. The merge
is somebody's call, not an implied next step.

## Two rules the controls in this repo now depend on

**Never `--parallel` for a control run.** A failure carrying a
`TransactionManagementError` cannot be pickled back to the parent
(`TypeError: cannot pickle 'traceback' object`); the pool dies and the run
reports `EXIT=1` with **`RESULT=<none>`** — no `OK`, no `FAILED`. That is a
**crash, not a red**, and must never be written into a controls table as though
the control had worked. Controls provoke in-transaction failures by design, so
they hit this far more often than ordinary runs.

**Commit before running controls.** The restore step is `git checkout -- …`,
which destroys uncommitted work in those paths. New, untracked test files are
the trap: they do not show in `git diff`. Check `git status --short` first.

Local runs also need `DJANGO_DEBUG=1` and `--noinput`.

## The controls, and why 1 is split

| # | break | expect red in |
|---|---|---|
| 1a | the payload claims every school is markable | `accounts.tests.test_login` payload tests |
| 1b | `landed()` draws the register link regardless of the boolean | **`tests/js/staff_signin.test.js`** |
| 2 | booleans answered per-login, not per-school | the two-school payload tests |
| 3 | `NoMembershipHere.a_password_fixes_it` → True | `test_staff_sign_in_page` |
| 4 | `schools()` → `LIVE_STATUSES` | the suspended-teacher test |
| 5 | `_refuse_non_markers()` refuses nobody | `attendance.tests.test_api` |
| 6 | the code door stops narrowing the payload | the code-session tests |

**1a and 1b are separate on purpose.** The landing is a JS renderer fed a
payload; it never calls `can_mark_attendance()`. So breaking the server-side
predicate can never redden the landing test — only 1b proves the link is keyed
on the boolean. This was an explicit review instruction.

## A bug a control already found (fixed in 71d9ffc)

`_schools_of()` re-implements `can_mark_attendance()` as a `Membership` query
rather than calling it. They agree on `MARKING_ROLES` but **not on the
narrowing**: `roles_at()` filters to PARENT on a code-opened credential, and
that flag is set only on a school's host — while both sign-in routes answer on
the portal. So `guardian_session()` told a guardian-who-also-teaches
`may_take_a_register: true` on a credential `can_mark_attendance()` refuses the
moment she uses it.

Fixed with `_schools_of(user, *, parent_scoped=False)`, the code door passing
`True`. `has_children_here` is deliberately untouched — her own children are
what the code is *for*.

## Decisions already taken (do not relitigate)

- **Both booleans shipped**, because the prerequisite was proved first:
  `results.tests.test_card_api.AStaffParentOnAPasswordSessionIsServedHerOwnChild`
  shows `/cards/` serves a password-opened staff session holding a Guardianship.
- **`vp_academic`, no HOD role.** There is no head-of-department role in this
  codebase and its absence is deliberate — the approval chain is per
  `(class, term)` and carries no subject.
- **Class-teacher scoping is issue #125, filed not fixed**, and recorded as
  **A5** in `docs/attendance.md` under *Domain assumptions* — **not A4**, which
  was already taken by a settled assumption.
- **No auto-redirect** from the staff landing. One school is one row; capability
  is the union of roles.
