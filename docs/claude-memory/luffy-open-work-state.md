---
name: luffy-open-work-state
description: "READ FIRST: luffy-school-saas 2026-09-14 — main still 7ec7f7f; PRs #101 (parent-access doc) and #102 (#96 slice 2, Closes #96) OPEN and UNMERGED, user said no merge; #96 code-complete but the issue closes only on #102 merging"
metadata:
  node_type: memory
  type: project
---

## READ FIRST — two PRs open and unmerged (2026-09-14, latest)

### `main` is still `7ec7f7f`. **Nothing merged this session.** The user said explicitly: no merge, no `--auto`.

| PR | branch | head | state |
| --- | --- | --- | --- |
| **#101** | `parent-access-provenance` | `bd5b565` | `test=success` on the head sha |
| **#102** | `guardianship-membership-trigger` | `911811c` | see below — gate on the head sha, not the rollup |

**#96 is code-complete but NOT closed.** #102's body says `Closes #96`, so the
issue closes when #102 merges and not before. A comment recording the slice is
already on #96.

`/tmp/.../scratchpad/pa` is a **git worktree** on `parent-access-provenance`.
Remove it (`git worktree remove`) once #101 merges.

### #102 — `0009_a_guardianship_pins_the_membership_under_it`

`accounts_membership_guardianship_rules`, `BEFORE INSERT OR UPDATE ... FOR EACH
ROW` on **`accounts_membership`**. The first guard in this repo that sits on one
table to protect **another table's** invariant. Identifiers
`membership_role_is_pinned_by_a_guardianship` and
`membership_user_is_pinned_by_a_guardianship` — deliberately NOT `0008`'s two,
even though rule 1 is the same rule, so a test can say which side refused (#89).

Three things decided that should not be re-derived:

- **No DELETE branch.** `Guardianship.student` is `PROTECT` (ORM raises
  `ProtectedError`) and past the ORM the FK refuses as `IntegrityError` at
  COMMIT. Measured both. A DELETE branch would dress referential integrity as a
  guardianship rule.
- **INSERT as well as UPDATE**, beyond what #96 asked. FKs are `DEFERRABLE
  INITIALLY DEFERRED`, so a guardianship inserted *ahead of* its membership
  escapes `0008`'s `NOT FOUND` branch and commits with neither rule applied.
  Measured reachable. User approved keeping it.
- **Both rules, not just `role`.** Rule 2 reads `Membership.user_id`;
  `Membership.objects.update(user=...)` is the same bypass one column along.
  User approved keeping it.

**The guard is narrow TWICE OVER and that was the control finding.** Removing
the early return alone: green, 103 tests. Removing `NEW.role <> 'student'`
alone: green, 103. Removing **both**: 16 errors + 1 failure, release and
transfer down. My first docstring claimed the early return was load-bearing;
it is an optimisation. Corrected in the file — do not "restore" the old claim.

### The rule-5 exception has now run to completion

`GuardianshipRulesAreStillBypassableTests` **no longer exists.** Its last
known-limit test went red, was deleted, and its case moved to
`GuardianshipRulesHoldOnTheMembershipUnderneathTests` (11 tests, 2 schools).
The companion `test_the_ordinary_save_path_is_still_closed` moved with it, with
a new job: same breach from the guardianship side, refused by a different layer
under a different name. `docs/operating-rules.md` rule 5 now points at
`WhatARevisionCannotFixTests` as the live example and keeps the guardianship
history as the worked one.

### Measured this session

- Full suite locally: **`Ran 1418 tests in 2818.083s`, `OK`, `EXIT=0`** (2 CPUs,
  `--parallel --noinput`). That is ~47 min locally vs ~15 min in CI.
- `accounts` alone: 248, OK. `accounts tests`: 258, OK.
- `0009` applies, reverses cleanly (trigger AND function gone), re-applies.
- The three leftover `test_luffy_db*` databases are **gone** — `--noinput`
  cleaned them up. See [[luffy-test-suite-runtime]] for the hang they caused.

## Previously — #100 merged, #96 open for ONE path only (2026-09-13)

### `main` is `7ec7f7f`. **PR #100 merged** — tested head `b64e91d`, ancestry exit 0 on both.

`accounts/migrations/0008_guardianship_rules_are_a_trigger.py` adds
`accounts_guardianship_rules`, `BEFORE INSERT OR UPDATE ... FOR EACH ROW`,
carrying both `Guardianship.clean()` rules with `ERRCODE = 'restrict_violation'`.

**It is the FIRST trigger in a SHARED app and is NOT the tenant shape.** Every
other trigger lives in a tenant app and is created unqualified per school
schema. `accounts` is `SHARED_APPS`-only: this runs once against `public` and
one trigger guards every school's rows at once — same reason
`uniq_guardianship_guardian_student` is one index over all of them.

Two design points not to re-derive:
- **Messages open with stable rule identifiers** —
  `guardianship_student_must_be_a_student`,
  `guardianship_guardian_is_not_the_student`. A trigger has no constraint name
  for Postgres to report (#89), so those tokens are what tests match.
- **A missing membership row is deliberately NOT this trigger's refusal.** The
  `NOT FOUND` branch returns and lets the FK answer; without it a deferred-FK
  insert is refused here first and reported as a role violation.

### **#96 IS STILL OPEN — for the third path only.** Do not read it as done.

Closed by #100: `bulk_create()` and `QuerySet.update()`.
**Still open:** `Membership.objects.filter(...).update(role=...)` underneath a
live link. It writes nothing to `accounts_guardianship`, so no trigger on that
table can see it. Needs a guard on `accounts_membership` protecting an invariant
owned by `accounts_guardianship` — a shape this repo has NOWHERE. Its own PR and
its own review; #100 deliberately does not say `Closes #96`.

`GuardianshipRulesAreStillBypassableTests` now holds exactly two tests: the
third-path known-limit test, and `test_the_ordinary_save_path_is_still_closed`
as its companion.

### The rule-5 exception fired for the first time, and worked

The bypass tests for the two closed paths went red on the trigger landing.
Acted on as `docs/operating-rules.md` rule 5 prescribes: three deleted, cases
moved into the new `GuardianshipRulesHoldWhereSaveNeverRunsTests`, plus a fourth
whose bypass half no longer existed. #96 updated by comment.

### The control shape worth copying

Real `DROP TRIGGER` in a throwaway migration applied after `0008`, run at **app
scope**: `Ran 239 tests`, `FAILED (failures=6)`. Six of seven new tests red, the
other 232 `accounts` tests unmoved. **The seventh stays green by design** —
`test_legal_rows_still_write_through_both_paths_at_both_schools` asserts legal
rows still write, which holds with or without the trigger, and exists so a
trigger refusing *everything* could not satisfy the other six. Say that out
loud in the report, or "6 of 7" reads as a partial result.

## Previously (2026-09-13, the four-PR batch)

### `main` is `ed96611`. Merged in order `#95 → #99 → #98 → #97`.

| PR | tested head | merge commit | what |
| --- | --- | --- | --- |
| #95 | `9cb9af0` | `4cca176` | `docs/parent-access.md` + the survival-table corrections |
| #99 | `bfa7125` | `6b38588` | rule 5's known-limit exception in `docs/operating-rules.md` |
| #98 | `d584b96` | `0d5f5f7` | the three forward-looking #91 references → #96 |
| #97 | `8ea2359` | `ed96611` | two schools in both guardianship test classes |

Each gated on `test=success` at **its own head sha**, `gh pr merge --merge`, no
`--auto`, ancestry checked exit 0 on merge commit and tested head. For #97 both
`8ea2359` (the merge-in) and the original tip `38ccedd` were ancestry-checked.

### **#96 is the next real work** — and it is OPEN

The three paths that still write a `Guardianship` row `clean()` would refuse:
`bulk_create()`, `QuerySet.update()`, and **a role change on the `Membership`
underneath a live link**. That third one writes nothing to
`accounts_guardianship`, so the trigger cannot live on that table alone.

**The design note now in #96, which is the part worth not re-deriving:** that
trigger would be **a guard on one table protecting an invariant owned by
another** — refused row is a `Membership`, invariant belongs to `Guardianship`.
**No such trigger exists in the repo.** 14 distinct triggers, all
`BEFORE ... ON <the table whose rows it protects>`. The near miss that must not
be mistaken for precedent: the three `*_stop_at_release` triggers *read* another
table but still refuse their own row.

**`grep -rn "CREATE TRIGGER"` returns 15, not 14** — `0017`'s is a `for` loop
that drops and re-creates three of the eight frozen-table guards while adding
the card FK. Counting the grep is how that enumeration gets claimed complete
when it is not. I made exactly that error and corrected it.

### Two merge-mechanics facts learned here

- **`mergeable` reads `UNKNOWN` right after the PR ahead of you merges.** GitHub
  recomputes in the background; #98 took three queries to settle to
  `MERGEABLE`. Merging on the first `UNKNOWN` is merging on an unanswered
  question. Re-query in a small loop.
- **`gh run cancel` fails here: `HTTP 403: Resource not accessible by
  integration`.** `gh` is a `ghu_` GitHub App user-to-server token
  (`only1paulo`) with no `actions: write`. Superseded runs cannot be cancelled
  from this session by any route — the web UI is the only option. Do not offer
  a `!`-prefixed command as a workaround; it is the same token.

## Previously (2026-09-13, before the merges)

**The user's instruction was "No merge on any of them."** All four are pushed and
awaiting their word. CI was `in_progress` on all four heads when the session
reported; gate on `/commits/<sha>/check-runs`, not the rollup.

| PR | branch | head | what |
| --- | --- | --- | --- |
| **#95** | `parent-access-doc` | `28d7706` | the doc, plus `220a81e` (fact→A, A6 row, A2/A7 rows, 37→**33**) and `28d7706` (D3 into A7 holds, A8/A9/A10 rows) |
| **#97** | `guardianship-tests-two-tenants` | `38ccedd` | two schools in both guardianship test classes |
| **#98** | `guardianship-gap-retarget` | `d584b96` | the three forward-looking #91 references → #96 |
| **#99** | `bypass-tests-rule` | `bfa7125` | rule 5's known-limit exception in `docs/operating-rules.md` |

**#97 and #98 both touch `accounts/tests/test_membership.py`** — different hunks
(#98 the class docstring at 596–618, #97 `setUp` and the bodies below). `merge-tree`
showed zero conflict markers, but see the trap list: **a clean `merge-tree` is not a
clean merge.** Whichever lands second wants a re-run.

### #91 is CLOSED. **#96 is the live successor.**

#91 was the `save()`-path gap and PR #93 closed it. **#96** carries what #93
deliberately did not take — `bulk_create()`, `QuerySet.update()`, and **a role change
on the `Membership` underneath a live link**. That third path writes nothing to
`accounts_guardianship` at all, so a trigger on that table cannot see it; the trigger
has to be on `accounts_membership` too. That is what makes #96 bigger than it looks.

### The bypass-test exception, now measured

`GuardianshipRulesAreStillBypassableTests` asserts a gap **exists**. Deleting
`Guardianship.save()`'s `full_clean()` leaves all five bypass tests **green** and reds
only the companion `test_the_ordinary_save_path_is_still_closed` — 1 failure out of 6.
So the ordinary control method cannot reach them; they go red when **#96** closes,
not when a guard is removed. #99 puts this in rule 5.

### Doc facts worth not re-deriving

- **33 migration files**, not 37 — `academics` 4, `fees` 3, `gradebook` 3, `results` 23.
  The 37 counted the four `__init__.py` files.
- **`Guardianship.objects.count() == 1` answers the wrong question.**
  `accounts_guardianship` is one `public` table for every school, so that assertion
  means "the table holds one row", not "this pair was refused". Under two schools all
  three of those assertions fail `2 != 1` — they were *wrong*, not merely weak.
- `Guardianship.school` is a **property** (`self.student.school`), not a field.

## Previously (2026-09-13, mid-session)

### `main` is `f867234` — the merge of **PR #93** (`guardianship-clean-enforced`)

`Guardianship.clean()` now runs on every `save()` path from one copy;
`link_guardian()`'s duplicate copy of both rules is gone. `save()` passes
`validate_constraints=False` and that flag is **load-bearing** — it keeps a
duplicate pair travelling to `uniq_guardianship_guardian_student` so
`get_or_create()` meets an `IntegrityError` it can recover from.
`validate_unique` is inert here (uniqueness is a `Meta.constraints`
`UniqueConstraint`, which `validate_unique()` never inspects) and has been
dropped from the call.

### **PR #95** (`parent-access-doc`) — OPEN, green, waiting on the merge word

Head `220a81e`, `test: completed success` on the head sha. Two commits:
`c0129c2` (the doc verbatim) and `220a81e` (four self-consistency corrections —
`fact N` → `A N`, the A6 survival row, new A2/A7 rows, 37 → **33** migration
files). PR body updated to match and to carry the open question below.

**Open question left for the user on #95:** the A7 survival row puts D3 in
neither column. D4 is named as breaking; D3 (guardian auth = verified channel +
one-time code) holds unchanged if A7 is false. Not edited unilaterally.

**The migration count is 33, not 37** — `academics` 4, `fees` 3, `gradebook` 3,
`results` 23. The 37 counted the four `__init__.py` files. My own earlier report
made that error and the doc inherited it.

### Branch `guardianship-tests-two-tenants` — `38ccedd`, committed, **not pushed**

Two schools added to `TheRaceWindowIsStillTheDatabasesTests` and
`GuardianshipRulesAreStillBypassableTests`, per `docs/parent-access.md`'s own
correctness requirement (2+ tenants for isolation/identity tests). 95 tests
`OK` 64.9s. No PR opened yet — the user had not said to.

**Why it mattered:** `accounts_guardianship` is one `public` table for every
school, so `Guardianship.objects.count() == 1` was answering "the table holds
one row", not "this pair was refused". Under two schools all three of those
assertions fail `2 != 1` — they were wrong, not merely weak.

### The bypass-test exception to the control-run rule

`GuardianshipRulesAreStillBypassableTests` asserts that a gap **exists**
(`bulk_create()`, `QuerySet.update()`, and a role change underneath a live
link all reach past `clean()`). **Controlled and proven:** deleting
`Guardianship.save()`'s `full_clean()` leaves all five bypass tests green and
reds only the companion `test_the_ordinary_save_path_is_still_closed` — 1
failure out of 6. So the ordinary control method does not apply to them; they go
red when **#91** closes the gap, not when a guard is removed. Proposed wording
to put this in `docs/operating-rules.md` rule 5 was given to the user; the rules
doc is **not yet edited**.

### Issues filed off this work

**#91** — the `bulk_create`/`update` bypass of `Guardianship.clean()`; needs a
row-level trigger, the way the append-only tables are enforced. **#92** — the
tenant→shared FK policy is convention, not a constraint; wants a migration-time
or CI check.

## Previously (2026-09-13, earlier)

### `main` is `ae013f7`. **#85 and #84 are both closed.**

`ae013f7` = the merge of **PR #88** (`refusal-assertions`), closing **#84**
(`state=CLOSED reason=COMPLETED`). Gated on the head `c4e32a7` — `test=success`,
`total_count=1`, resolved by SHA — merged with `gh pr merge 88 --merge`, no
`--auto`. Ancestry exit 0 for the merge commit `ae013f7`, the tested head
`c4e32a7`, **and** the first commit `556db14`.

**The combined-status endpoint lies here.** `/commits/<sha>/status` reports
`state=pending statuses=0` for every commit in this repo — it uses the Checks
API, not legacy statuses, and GitHub renders an empty aggregate as `pending`.
Gate on `/commits/<sha>/check-runs`. Same on #87's shas.

### Previously (before #88 merged)

### `main` was `d28bfff`. **#85 and #84 were both done.**

`d28bfff` = the merge of **PR #87** (`discount-subtransactions`), which closed
**issue #85**. Note the numbering trap: **#85 is an ISSUE, not a PR** —
`gh pr view 85` returns "Could not resolve to a PullRequest". Merged with an
explicit `gh pr merge 87 --merge`, no `--auto`; `merge-base --is-ancestor`
exit 0 against both `main` and `origin/main` for `d28bfff`, and for both branch
commits `c6b218e` and `3614426`.

**Gate on the head, and check what the head actually is.** The instruction that
session named `c6b218e`, but the PR head was `3614426` sitting on top of it.
Both were green, so the merge stood — but checking only the named sha would
have gated on a commit that was not being merged.

### PR #88 — #84's sweep — MERGED as `ae013f7`

Two commits: `556db14` (the 13-site sweep) and `c4e32a7` (the `/code-review`
fixes). Local suite green at `c4e32a7`: `Ran 403 tests in 822.624s`, `OK`,
`EXIT=0`. **Gate on `c4e32a7`, not the rollup** — `556db14` carries its own
older green run.

`assertRefusedBy` now lives at `tests/refusals.py` as the `RefusalAssertions`
mixin. `tests/test_refusals_are_constraints.py` asserts the premise it rests on:
every migration `RAISE EXCEPTION` carries `USING ERRCODE = 'restrict_violation'`
(SQLSTATE 23001), which is the only reason pinning `IntegrityError` works.

**Two of #84's own prescriptions were wrong** and were not followed — verified
against the code, not the issue text:
- `test_a_teacher_may_not_withhold` should **not** assert `WithholdingError`.
  `services._require_authority()` raises `NotAllowedToActOnResults`, which is a
  `ResultsError` but not a `WithholdingError`; the issue's suggestion turns a
  weak green test red.
- The two append-only withholding tests **never reach a constraint** —
  `save()`/`delete()` raise in Python. They name
  `WithholdingDecisionsAreAppendOnly`. Chasing it found the trigger half that
  `TheDecisionRowIsAppendOnly`'s own docstring claimed and nothing asserted; two
  tests were added for it.

**The finding worth carrying forward:** `assertIn("released", ...)` was
satisfied by the *database* in two tests named
`test_the_model_refuses_before_the_database_has_to`, because the trigger's
message says "released" too. Deleting `ReleasedTraitRating.save()`'s guard
entirely left the old test green — `Ran 1 test … OK`. Ten trigger messages
likewise share the substring `append-only`, which is the whole argument in #89.

### Old state, kept for the #82/#86 reasoning

### `main` was `83bfa1d`. **Phase 2 is closed.**

`83bfa1d` = "Merge pull request #86 from adedejimakinde/charge-subtransactions".
CI green on the merged head **before** the merge (`test=success` on
`41ab8d7`, 22m), merged with an explicit `gh pr merge --merge` (no `--auto`),
and both shas ancestry-checked against `origin/main`: the merge commit
`83bfa1d` **and** the tested head `41ab8d7`. `autoMergeRequest` was `null`,
which is correct here because `--auto` was never armed — see
[[luffy-phase-1-workflow]] for why that same null is a red flag when it is.

**#82 is CLOSED** (auto-closed by the PR body's `Closes #82`).

### What #86 finally shipped

Option 1 for #82: an inner `fees.services._charge()` with no savepoint, called
only by `schedules.apply_to_class()`; public `charge()` keeps
`@transaction.atomic` and delegates. Plus **all four** `/code-review high 86`
findings acted on — the false bound, the misattributed `12.29us`, the moved term
check, and finding 4, which was the last commit:

**`_charge()` now checks its own precondition.**
`if not transaction.get_connection().in_atomic_block: raise NotInATransaction(...)`,
first statement in the function. `NotInATransaction` subclasses
`transaction.TransactionManagementError` and is **deliberately not a
`FeeLedgerError`** — under `FeeLedgerError` a caller catching ledger refusals and
carrying on would convert it into the partly-billed class #82 rejected as option
3, through exactly the handler `charge()`'s docstring sends that caller to.

Its tests are `ChargeNeedsATransactionTests` at the foot of
`fees/tests/test_schedules.py`, and they are a **`TransactionTestCase` because
they have to be**: under `TestCase` the test's own atomic block makes
`in_atomic_block` true, the guard is unreachable, and the refusal test would pass
against no guard at all. Two tests, because the refusal alone passes against
`def _charge(): raise` — the second is the same call inside `atomic()`, one
`atomic()` being the only difference between them. Asserted **by type**, which is
the #84 discipline applied on the way in.

`make_school()` (the template clone, 0.27s) works fine inside a
`TransactionTestCase` provided teardown drops the schema — `tenants.py`'s caveat
about seeded rows and the flush does not bite, because the flush runs after the
schema is already dropped. Proven, not reasoned: 2 tests in 2.438s.

### The runs behind `41ab8d7`

| target | result |
|---|---|
| `fees` | `Ran 108 tests in 169.399s`, `OK`, `EXIT=0` |
| `results.tests.test_withholding` | `Ran 69 tests in 247.175s`, `OK`, `EXIT=0` |
| `makemigrations --check` | `No changes detected` |

Control for the guard, at **module scope**, `raise` deleted and nothing else:
`Ran 66 tests in 119.759s`, `FAILED (failures=1)`, `EXIT=1` —
`AssertionError: NotInATransaction not raised`. **One failure out of 66** and the
in-transaction pair stayed green, which is what makes it a control.

`test_withholding` was **re-run** at the new head rather than carried over: the
PR body's old reason for not re-running it ("every commit since changes comments
only, `git diff -U0` shows no executable line") went stale the instant the guard
was pushed. The guard provably cannot reach it — `charge()` is atomic, so
`in_atomic_block` is true before `_charge()` — but that is an argument and the
run is evidence. Same defect class as the wrong bound, in the PR's own text.

## What remains

1. **#89** — the 92-site `assertRaises(IntegrityError)` remainder across 22
   files (82 bare, 10 `assertIn`-only). Scoped test-side-only like #84. Leads on
   the ten trigger messages sharing `append-only`.
2. **#90** — `test_the_constraint_still_holds_underneath_the_service` in
   `test_withholding.py` provokes an `IntegrityError` with no
   `transaction.atomic()`. **Latent, not live**: the `.update()` is the last
   statement, so the poisoned transaction is never used; a probe confirmed the
   next statement raises `TransactionManagementError`. **Not the same defect as
   #85** — #85 was savepoint *proliferation* in `fees` production code, #87
   touched zero `results/` files. `filter(pk=1)` there is **not** a defect:
   `ReportCardSettings` is a deliberate singleton (`withholding.py:163`,
   `ratings.py:206` both `get_or_create(pk=1)`).
3. **#74 — the takings report. Still deferred.**

## The three items that remained as of 2026-09-12

1. **#74 — the takings report. Deferred, and staying deferred.** Its four open
   questions are real; the three constraints holding meanwhile (no `reference`
   uniqueness, no allocation, no aggregate columns) are documented. Leave it
   until the user says otherwise.
2. **#84 — the `assertRaises(Exception)` sweep. Queued BEHIND #85.** Counts
   re-verified on `83bfa1d`: **15 grep hits, 2 are prose**
   (`test_schedules.py:1916`, `test_withholding.py:931`), so **13 real call
   sites** — matching the issue title. **3 bare** (capture nothing, assert
   nothing), all in `results/tests/test_withholding.py`: `:890`
   `test_updating_a_decision_is_refused`, `:898`
   `test_deleting_a_decision_is_refused`, `:1036` `test_a_teacher_may_not_withhold`
   — **that last is the priority**, an authority refusal a 500 satisfies. The
   other 10 assert on the message only. Two of those claim a *layer* their
   assertion cannot distinguish: `test_ratings.py:1389` and
   `test_comments.py:837`, both `test_the_model_refuses_before_the_database_has_to`.
   The fix already exists: `assertRefusedBy(name)` at
   `fees/tests/test_schedules.py:129`, **11 call sites** in that file. It should
   move somewhere shared.
3. **#85 — the concessions-not-children residual. NEXT UP, and it needs
   SCOPING, not building.** The discount loop still opens one savepoint per
   concession and **must** (its collision handler needs one to roll back to).
   Nothing bounds the count: uniqueness is keyed on
   `(student_membership_id, term, source_concession)` at `fees/models.py:566`,
   and `models.py:246` says outright that several concessions per child is
   deliberate, so there is no constraint on the child. 45 children x 2
   concessions = 90 savepoints, past 64 **on an ordinary bill**. Verified
   unchanged on `83bfa1d` at `fees/schedules.py:359` — #86 removed the *charge*
   loop's savepoints, not these. See [[a-bound-needs-a-constraint]].

### How #85 gets picked up — the user's instruction, 2026-09-12

**Scope it the way #82 was scoped: numbers first, options after.** Do not open
with a fix.

1. **Measure the real ceiling first.** Concessions per child is *not* bounded by
   roster size, so roster arithmetic does not give the answer. The number wanted
   is the actual **distribution of concessions per child across the pilot
   schools** — scholarship-heavy and scholarship-rare are different regimes and
   may well want different answers. Get that distribution before choosing.
2. **Then options.** #85 already rules that fixing it means **adding a
   constraint or restructuring the loop** — *not* asserting a limit the schema
   does not enforce. That ruling stands; the measurement decides between the two,
   it does not re-open the third.
3. **Prove it the way #82 was proven.** A control run showing **the collision at
   scale**, then the same run showing **it is gone**. Both at module scope — see
   [[control-runs-go-stale]] and [[luffy-subtransaction-measurement]], which also
   records the two traps that made #82's first two measurement attempts report
   nothing.

**#84 is queued behind #85.** Its fix location is settled and must not be
re-derived: `assertRefusedBy(name)` at `fees/tests/test_schedules.py:129`, 11
call sites in that file. The work is **moving it somewhere shared and applying it
across the 13 sites** — nothing to investigate.

## Rulings — do not re-open

- **Option 1 for #82**, and why not 2 or 3: option 2 (`bulk_create`) drops
  `full_clean()` and breaks the "every entry funnels through `_post()`"
  invariant; option 3 gives up all-or-nothing billing, and a partly billed class
  is worse for a bursar than a slow one.
- **The savepoint conversation is #82, not #2.** `#2` is a merged PR about
  phone/username normalisation.
- `_charge()`'s guard is **not** a `FeeLedgerError`, for the reason above.

## Still open

`#90 #89 #81 #80 #78 #75 #74 #53 #52 #50 #47 #40 #39 #38 #36 #33 #32 #31 #30
#28 #24 #23 #21 #20 #17 #16 #6`.

`/home/vscode/worktrees/placement-control` is dirty (one modified
`test_release_roster_race.py`, detached at `923b745`) and is **unrelated** — it
has sat there for several sessions.

## Traps this project keeps re-finding

- **Run tests with `DJANGO_DEBUG=1`** or `settings.py:36` refuses to start:
  `ImproperlyConfigured: DJANGO_SECRET_KEY is not set`. Nothing is tested and
  `RESULT=<none>`.
- `ReleasedCardPdf.card` is `PROTECT` and exists for **every** card after #66,
  so a raw `DELETE FROM results_releasedcard` in staging must clear
  `results_releasedcardpdf` first.
- A long run's log is only evidence about the code on disk when it **started**.
- **A killed session leaves `test_luffy_db` behind** -> interactive "destroy
  it?" prompt, `EOFError`, `RESULT=<none>`. Fix: `PGPASSWORD=changeme psql -h db
  -U luffy_admin -d luffy_db -c "DROP DATABASE test_luffy_db;"`.
- A binary 200 in django-ninja is `response={200: None, ...}`.
- A refusal of **state** over HTTP is a **423**, not 409 and not 403.
- **A clean `git merge-tree` is not a clean merge.**
- Usernames are **public-schema and globally unique** across schools in tests.
- `--parallel` hides real errors as `TypeError: cannot pickle 'traceback'
  object`. Re-run serially.

## Standing rules

2+ tenants wherever the claim *can* be scoped wrong (a connection-level flag
cannot — say so rather than staging a contrived second school); control runs
wherever a passing test proves nothing, **at module scope**; `/code-review`
every PR, **by PR number**; **merge on the user's word only**, gate keyed on the
**head sha**; ancestry check on the merge commit *and* the tested head; issues
for found-but-not-fixed; run the **neighbouring** test file too.

See [[luffy-subtransaction-measurement]], [[luffy-withholding-recovered]],
[[luffy-phase-1-workflow]], [[luffy-snapshot-architecture]],
[[luffy-session-arithmetic]], [[luffy-release-marker-requirement]],
[[phase-1-results-decisions]], [[luffy-never-idle-on-ci]],
[[luffy-test-suite-runtime]], [[luffy-snapshot-read-once]],
[[no-claude-attribution-on-github]], [[control-runs-go-stale]],
[[pr-review-state-line]], [[code-review-target-by-pr-number]],
[[a-bound-needs-a-constraint]].
