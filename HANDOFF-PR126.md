# Handoff — PR #126 is open and **unfinished**

Written 2026-09-21 when a session ran out of budget mid-task. Delete this file
once #126 is merged.

## State

- `main` = **9c50c2d** (merge of #124, which closed issue #122).
- Branch `staff-landing-and-register-screen`, head **9290072**, 8 commits,
  pushed. Working tree clean.
- **Do not merge #126 yet.** See "What is left" below.

## What is left, in order

1. **Re-run the controls from scratch**: `scripts/controls-pr126.sh`.
   They were interrupted after BASELINE (green both) and control 1a's JS half.
   Every earlier control run is stale, because the code changed after them.
2. **Verify CI on the head SHA**, not the PR rollup.

   **Useful narrowing:** the full suite came back **green on `71d9ffc`**, which
   is the last commit that touches any code. Everything after it —  `9290072`
   and `ec44eb5` — changes only `docs/`, this file, and
   `scripts/controls-pr126.sh`: no Python, no JS, no templates, nothing the
   suite executes. So the code in this PR is CI-proven; what still needs
   confirming on the real head is only that those three additions did not
   upset anything (e.g. a test that walks `scripts/`).

   Confirm it on the head SHA anyway. "Nothing it changed is executed" is a
   reading, and the gate is the gate.
3. Merge gated on that SHA → ancestry both ways → fast-forward local `main` →
   delete the remote branch.
4. Delete this file and `PR-A-CONTROLS.md`.

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
