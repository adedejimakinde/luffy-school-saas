# PR #79 — independent pass on the two questions

Branch `fee-schedule-billing`, base `main` (`c236a18`). Worktree clean.

| commit | what it is |
|---|---|
| `426b4b1` | what §1 and §2 below were written against |
| `08b40cf` | what `/code-review` reviewed |
| `7b82d4e` | the `is_live` proof — tests only |
| `60eabf1` | the fixes for findings 1, 3, 4 and 5 |
| *this commit* | this document; the branch tip |

Stated as a list rather than as one SHA because this document has now spanned five of
them, and a single "head" line was wrong twice already — see the correction below.

> **Header corrected 2026-09-05.** This document was first published against head
> `426b4b1` and said so. Two commits landed after it — `405aa54` and `08b40cf` — so that
> header described a commit that was no longer the branch head, which is the same failure
> the document itself reports in §5: the artefact under review and the code that existed
> were different things, and nothing said so. Read §1 and §2 as written against `426b4b1`;
> everything from *Acted on* down is `08b40cf`.
>
> **Baselines.** `426b4b1`: `Ran 87 tests in 121.854s`, `OK`, `EXIT=0` in `fees`.
> `08b40cf`: 93 tests, `OK`, `EXIT=0`.

> **Status:** §1 and §2 are my own read. A `/code-review` pass was believed to be running
> alongside them; when checked on 2026-09-05 **no review was in flight** — no reachable
> agents, empty task slot, zero comments on PR #79 — so one was started against `08b40cf`
> and its findings are appended below. Nothing merged.

---

## 1. Concession-vs-schedule lock scope — the narrowing is complete

Checked by enumeration rather than by re-reading the argument.

Ten constraints exist on `FeeLedgerEntry`. Exactly one is reachable from a concession
discount, and each of the others is excluded for a stateable reason:

- amount is `-_magnitude(concession.amount_kobo)`, and `a_concession_reduces_something`
  forces the source `> 0`, so the posted amount is always strictly negative
  → `a_ledger_entry_moves_money` and `a_payment_or_discount_reduces_what_is_owed` satisfied
- `kind=DISCOUNT` → satisfies `a_concession_only_produces_discounts`; excluded from
  `a_charge_or_refund_increases_what_is_owed` and `a_schedule_line_only_produces_charges`
- `reverses=None` → satisfies `only_a_reversal_names_what_it_undoes`; excluded from the
  partial index `an_entry_is_reversed_at_most_once`
- `source_line=None` → excluded from `a_schedule_line_charges_a_child_once`; satisfies
  `an_entry_has_one_source`

What is left is `a_concession_discounts_a_child_once_per_term` — the one the handler names.
Everything else that can raise `IntegrityError` on that INSERT is a foreign-key violation,
which carries a different `constraint_name` and is re-raised.

**So: complete, not merely the case that was found.**

Two supporting facts verified rather than assumed:

- **The savepoint reasoning holds.** `services.discount` is `@transaction.atomic`
  (`fees/services.py:187`), so the failure rolls back to a nested savepoint and the outer
  transaction survives. `test_a_discount_another_bill_posted_is_a_skip_not_a_dead_run`
  proves it against a **real** database collision — it inserts the row, then calls the real
  `discount()` — asserting `charges_posted == 4`. It is not a mocked exception.
- **The comment's "eleven constraints" is ten.** The eleventh refusal mechanism on that
  table is the `fees_ledger_append_only` trigger from migration `0002`, which is a trigger
  and not a constraint, and fires `BEFORE UPDATE OR DELETE` only — unreachable from an
  INSERT. If it ever did fire it raises `ERRCODE = 'restrict_violation'` with no
  `constraint_name`, so the predicate re-raises it, which is right.

### The gap the narrowing structurally cannot cover

It reaches the same worst outcome named in the brief.

Two runs of two *different* schedules in one term, overlapping on a mid-move child, both
insert the same `(child, term, concession)` row. If they ever process shared concessions in
**different orders**, Postgres deadlocks — and a deadlock arrives as `OperationalError`
(SQLSTATE `40P01`), not `IntegrityError`. The handler never sees it, the loser's transaction
dies, and forty-five children go unbilled.

Today that is unreachable, but by accident. The concessions queryset carries no
`.order_by()` and inherits `FeeConcession.Meta.ordering = ["student_membership_id", "id"]`
— a global total order, so every run walks shared concessions in the same relative order.
Compiled SQL confirms it:

```
ORDER BY "fees_feeconcession"."student_membership_id" ASC, "fees_feeconcession"."id" ASC
```

`apply_to_class()` explicitly sorts `student_ids`, and explicitly writes `.order_by("pk")` on
`memberships` with a paragraph about why. The one queryset whose ordering actually carries a
concurrency guarantee is the only one that says nothing — one `Meta` edit or one stray
`.order_by()` away from a deadlock the handler cannot catch.

**Proposed fix:** an explicit `.order_by("student_membership_id", "id")` on the concessions
queryset, with a comment naming the deadlock it prevents.

---

## 2. Unbacked claims — six, one of them the same shape as the re-post escape hatch

| Claim | Where | Status |
|---|---|---|
| **"Non-unique, and it must stay non-unique"** (`reference`) | `fees/models.py:415` | No test. Explicitly anticipates a future reader adding a unique index — and nothing would fail if they did |
| `UnknownStudent` — refused, nothing posted | `fees/schedules.py` | Never triggered. Only touched by `issubclass` at `fees/tests/test_schedules.py:755`. Reachable: `ClassPlacement.student_membership_id` is a bare `PositiveBigIntegerField`, so a public-schema `Membership` can be deleted out from under a tenant placement |
| `AppliedSummary.discounted_kobo` | `fees/schedules.py` | Asserted nowhere. `charged_kobo` is, at `test_schedules.py:154` |
| `a_concession_reduces_something` | `fees/models.py:294` | Untested, while its exact twin `a_schedule_line_charges_something` is tested at `test_schedules.py:786` |
| Predicate's "different constraint name" branch | `fees/schedules.py` | The one test (`test_schedules.py:704`) raises a bare `IntegrityError` with no `__cause__`, so only the "no diagnostics" branch is covered. The real-diag-different-name path is never exercised |
| "editing changes only what a **future** application would post" | `docs/fees.md` | The freeze half is tested twice (`test_the_charge_freezes_the_line_description_rather_than_joining_to_it`, `test_the_charge_freezes_the_amount_too_not_only_the_wording`); the future-application half is not |

The first is the strongest — same genre as the re-post claim, and it is the first one in the
money path.

Also checked: `docs/fees.md` links [#74](https://github.com/adedejimakinde/luffy-school-saas/issues/74)
and [#75](https://github.com/adedejimakinde/luffy-school-saas/issues/75); both exist and are OPEN.

---

## Agreed scope

- **#78 disclosed rather than fixed is the right call.** `reverse_entry()`'s joined lock
  belongs with the pattern audit, not in a billing PR.

## Order of operations

1. Report findings (this document) — **done**
2. Append `/code-review`'s findings when they land
3. Fix
4. Merge on your word
5. `git merge-base --is-ancestor <sha> origin/main`

---

# Acted on — branch head `08b40cf`

`fees`: **93 tests, OK, EXIT=0** (baseline was 87). Two commits, both pushed.

## 1. The ordering gap — closed and pinned

`.order_by("student_membership_id", "id")` is now explicit on the concessions
queryset, with a comment naming the deadlock: SQLSTATE `40P01`, arriving as
`OperationalError`, invisible to the `IntegrityError` handler, costing the whole
class its billing.

Pinned by `test_the_concession_read_is_ordered_so_two_bills_cannot_deadlock`,
which asserts against **compiled SQL** in two halves:

1. the emitted read carries
   `ORDER BY "fees_feeconcession"."student_membership_id" ASC, "fees_feeconcession"."id" ASC`;
2. **it still carries it with `FeeConcession.Meta.ordering` emptied** — which is
   the half that matters, because half 1 passes just as happily against the
   inherited ordering that was the problem.

Verified load-bearing by mutation, not by inspection: deleting the explicit
`.order_by()` turns half 2 red on its own with the intended message. The
filter matches `"fees_feeconcession"."amount_kobo"` rather than the table name,
because `full_clean()` → `ForeignKey.validate()` probes the same table with
`SELECT 1 AS "a" … LIMIT 1` once per concession; that was found by the first run
failing 3 != 1, not assumed.

## 2. Three claims backed

| claim | test | note |
|---|---|---|
| `reference` "must stay non-unique" | `test_two_children_can_share_one_teller_reference` | through `record_payment()`, not row inserts — the claim is about the money path. Asserts **both children's balances**, since one child paid twice would satisfy a row count |
| `a_concession_reduces_something` | `test_a_concession_reduces_something` | both directions (`0` and negative): `_magnitude()` takes an absolute value, so a negative concession would post exactly like a positive one |
| predicate's different-constraint-name branch | `test_a_real_violation_of_another_constraint_is_raised_not_swallowed` | a **real** violation of `one_fee_schedule_per_class_per_term`, re-raised from inside a savepoint. Asserts the forced `pgcode`/`constraint_name` pair, so it cannot drift back onto the already-covered no-diagnostics arm |

## 3. Eleven → ten

Counted, not recalled: `FeeLedgerEntry._meta.constraints` is exactly 10, and the
names match the enumeration in this document. The comment now says why the
eleventh refusal is not one — `fees_ledger_append_only` is a **trigger**, fires
`BEFORE UPDATE OR DELETE`, unreachable from an INSERT, and raises
`restrict_violation` with no `constraint_name` if it ever did.

## 4. Filed

- **#80** — the three gaps, as agreed: `UnknownStudent` never raised in a test,
  `discounted_kobo` asserted nowhere while `charged_kobo` is, and the
  future-application half of the editing rule.
- **#81** — *not in the original six.* The predicate docstring claimed
  consolidating its four copies "is filed"; it was not. Now filed and the comment
  names the issue. The issue records the real finding: four copies, two
  definitions, `accounts/throttling.py` still checking the name without the
  SQLSTATE.

## 5. Found in the working tree, not in the six

The branch carried **uncommitted** work: a behaviour change skipping children
whose membership has ended, `AppliedSummary.students_skipped`, `select_related`
on the memberships read, ordering hygiene on the two skip-set reads,
`FeeLedgerEntry` added to the `Meta.ordering` guard, the predicate tightened to
check `pgcode`, and three stale "Test N of the design" docstring numbers removed.

Two problems with it, both fixed rather than shipped:

- **The leaver rule had no test at all** — a billing behaviour change on the money
  path, exactly the shape this PR exists to close. Now two tests (the skip and
  the count, and that `__str__` reports it), both verified load-bearing by
  removing the `is_live` filter and watching them fail.
- **It was in no document.** `docs/fees.md` states every other billing rule and
  said nothing about this one. Written up, including that `students` now means
  "billed" rather than "on the roster" — a silent change to an existing field's
  meaning.


---

# The `/code-review` pass — appended 2026-09-05

Findings below are the second pass, against `08b40cf`. Branch head is now
**`7b82d4e`** (pushed): the delta from the reviewed commit is three tests and no
production code — see *The `is_live` read* below.

## The first pass reviewed the wrong branch

Recorded rather than quietly re-run, because it is §5's failure reached twice in one
PR by two different routes. `/code-review` was launched with `fee-schedule-billing`
as an argument, but the fork inherits the session's working directory and
`/workspace` is on `phase-2-fee-design`. Its own scope line: `git diff main...HEAD`
= "two files, docs only — `docs/fee-schedule-and-withholding.md`,
`docs/operating-rules.md`". It reviewed the design document. The billing code still
had no pass — the exact gap this review existed to close.

Relaunched as `/code-review high 79`. A PR number cannot be ambiguous about which
tree it means; a branch name passed to a fork with its own cwd evidently can.

That pass is not wasted — nine substantive findings against
`docs/fee-schedule-and-withholding.md`, already on `main` via #76. They belong to
their own issue and are deliberately not mixed in here.

**Two caveats, both mine.** The reviewer reported: *"I could not complete a local
test run (the test DB was left in a broken state by an interrupted `--noinput` run,
and dropping it is blocked)."* That database was mine, from a run I killed on a
two-minute timeout while building the `is_live` proof — so this is a reading pass,
not an executed one. And the second pass checked the PR out **in `/workspace`**,
leaving it on a detached `08b40cf` with the branch's own commit invisible until
restored. A review that moves the tree it was asked to describe is the same class
of problem as §5, now on the reviewing side.

## Findings — five

| # | where | sev | the claim |
|---|---|---|---|
| 1 | `fees/services.py:270` | **med** | `reverse_entry()`'s `select_for_update().select_related("term")` takes `FOR UPDATE` on the joined `academics_term` row. Every insert in `apply_to_class()` takes `FOR KEY SHARE` on that same row and holds it to commit; the two conflict. Bursar A bills 45 children (135 inserts, one transaction); bursar B clicks undo on an unrelated payment in the same term and blocks for the whole run — reversed, it stalls the billing run on its first insert. #78 scoped this as *waste*; the new long transaction turns it into *contention*. Dropping `select_related("term")` from the locked queryset fixes it — the term is re-read a line later anyway |
| 2 | `fees/schedules.py:299` | low/med | the charge loop calls `services.charge()`, which is `@transaction.atomic`, so each entry opens a savepoint inside the class-wide transaction — ~135 subtransactions and ~675 statements for a 45-child three-line bill, while holding the schedule lock. Past 64 subxids Postgres overflows the per-backend subtransaction cache into `pg_subtrans` SLRU lookups, degrading visibility checks **cluster-wide** for the life of the transaction. The savepoints are load-bearing for the discount loop; for charges they are not |
| 3 | `fees/services.py:141` | low | `charge()` takes `source_line` publicly but never checks `source_line.schedule.term_id == term.pk`. `a_schedule_line_charges_a_child_once` is keyed on `(student, source_line)` with no term, and the docstring's justification holds only if no caller mismatches them. A hand-posted correction naming the right line with the wrong term makes the real run report that child's tuition as *skipped* — **silent under-billing no constraint can catch** |
| 4 | `fees/services.py:187` | low | the same shape on the other column: `discount()` never checks `source_concession.student_membership_id == membership.pk`, so a discount can post on Ada's account attributed to Chidi's concession, and "everything this concession did" then returns two children. The child half is guarded by `_require_student_of_this_school()`; this is the matching guard the new columns lack |
| 5 | `fees/services.py:302` | low | `narration or f"Reversal of: {locked.narration}"` prepends 13 characters to a `max_length=255` column. Newly reachable, because `apply_to_class()` copies `FeeScheduleLine.description` (also 255) verbatim. A 243+ character line produces a charge that **cannot be reversed**, and it fails as `ValidationError` — not a `FeeLedgerError`, so `except FeeLedgerError` will not catch it |

Checked and cleared: the `an_entry_has_one_source` REVERSAL-only claim; §1's
concession `order_by` deadlock argument; `_is_the_concession_colliding()` against
psycopg2's real surface; migration `0003` against the models; that nothing outside
`fees` switches exhaustively on `kind`.

## Does any finding touch the ended-membership skip?

**No — seven places, seven noes.** Checked one at a time against the surface the
skip actually occupies, rather than against a general impression of the review.

| # | place | any finding? |
|---|---|---|
| 1 | `fees/schedules.py:240-242` — the `is_live` filter, `students_skipped`, `student_ids = billable_ids` | **no** |
| 2 | `fees/schedules.py:373` — `students=len(student_ids)`, the meaning change | **no** |
| 3 | `fees/schedules.py:132` — the field and its comment | **no** |
| 4 | `fees/schedules.py:145` — the `"no longer enrolled"` string | **no** |
| 5 | `fees/schedules.py:210-215` — the memberships read the filter depends on | **no** |
| 6 | `docs/fees.md:220` — the written rule | **no** |
| 7 | `fees/tests/test_schedules.py:960-1015` — the two tests | **no** |

**What that "no" means, and what it does not.** It does not mean the skip was
examined and cleared. The reviewer's only contact with that surface is one line in
its cleared list — *"`Membership.objects` has no default filtering, so the
`UnknownStudent` guard does not misfire on ended memberships"* — which concerns the
read at place 5 and answers a different question. With no test run completed, the
behaviour change that arrived last and changed billing is still the least-scrutinised
thing in this PR *after* the review, which is what was suspected before it ran.

Two adjacencies, named rather than hidden, neither a finding against the skip.
Finding 2 concerns the loop the skip feeds — the subxid count is
`len(billable_ids) x lines`, so the skip moves that number without being the defect.
Finding 3 reaches the **same outcome class** by a different mechanism: a child
silently not billed, no error, no row. That the review found one such path
independently is the argument for taking the other one seriously.

## The `is_live` read — proven rather than argued

The open question was whether a partially-loaded membership could make `is_live`
answer differently, since it is a Python property read in memory over a dict the
same commit changed the fetch strategy for. Half that premise was wrong, and the
half that held is worse than it looked.

**`select_related` is not the guard.** Removing `.select_related("user", "school")`
from the production read leaves all eight leaver and refusal tests **green**.
`is_live` returns `self.status in LIVE_STATUSES` and reads nothing else, so the join
costs queries in `snapshot_student()`, not correctness here.

**A loaded `status` is the guard.** Deferred, `.status` becomes a lazy refetch of a
row the function already read, issued later and inside the schedule lock — two reads
that can disagree, with the decision taken on the later one. That is the
second-read-per-locked-block shape, on the money path.

Three tests, `fees/tests/test_schedules.py::LeaverReadTests`:

| test | pins |
|---|---|
| `test_the_object_is_live_reads_has_its_status_loaded` | spies on the property and asserts `get_deferred_fields()` is empty **on the instance `is_live` actually read**, and that it was consulted for both children — so it cannot pass by not looking |
| `test_deciding_the_skip_costs_no_second_read_of_the_membership` | exactly one `accounts_membership` SELECT: one read, so there is no later read to disagree with it |
| `test_a_deferred_status_would_drop_an_enrolled_child_from_billing` | the control. A membership ends **mid-billing**; same mutation both ways. Loaded → billed, `students_skipped == 0`. Deferred → skipped, `students_skipped == 1`, the exam fee never posts, no error raised |

Verified load-bearing by mutation, not by inspection. Adding `.defer("status")` to
the production read turns all three red:

```
AssertionError: 1 != 2 : the enrolled child was billed
AssertionError: 3 != 1 : the memberships are read once and decided from that read;
  3 reads means status can be fetched again later:
  SELECT ... FROM "accounts_membership" WHERE "id" IN (5, 6)
  SELECT "id", "status" FROM "accounts_membership" WHERE "id" = 5 LIMIT 21
  SELECT "id", "status" FROM "accounts_membership" WHERE "id" = 6 LIMIT 21
AssertionError: membership 9 reached is_live with fields unloaded: ['status']
```

What raises the stakes: **nothing downstream would catch a wrong answer.**
`why_not_a_student_here()` checks `role` and `school.schema_name` and never
`status`, so this filter is the entire guard — between a leaver and a charge, and
between an enrolled child and never being invoiced at all.

`fees`: **96 tests, OK, EXIT=0** (93 at `08b40cf`).

> One retraction from getting there: an intermediate run showed 13 errors across
> `test_ledger`. That was a test database left behind by a run I killed on a
> timeout, not a regression — clean `08b40cf` is 93/OK, and the same tree re-run is
> 96/OK. It is also the database the reviewer could not work around, so it cost
> this pass its test run.

## Order of operations

1. Report findings — **done**, both this document's own pass and the review
2. Fix — **done** for 1, 3, 4 and 5; 2 filed as #82, `must-fix-before-pilot`
3. Merge on your word — *pending*
4. `git merge-base --is-ancestor <sha> origin/main`

---

# Acted on the review — 1, 3, 4 and 5 fixed; 2 filed

Finding 2 is deliberately not fixed: it is a design decision about how charges post,
not a patch, and it is now **[#82](https://github.com/adedejimakinde/luffy-school-saas/issues/82)**,
labelled `must-fix-before-pilot`. The issue carries the whole analysis — 135
subtransactions past Postgres's 64-subxid cache, why the savepoints are load-bearing
for the discount loop and not for the charge loop, and three options with what each
one costs.

Every fix below is verified load-bearing by mutation: the production change is
reverted, the test is run, and it goes red on its own.

## 1 — the reversal lock stops joining the term

`reverse_entry()`'s locked read drops `.select_related("term")`, and the reversal is
built with `term_id=locked.term_id` rather than `term=locked.term`, so the join is
not replaced by a lazy read. The comment now names the contention rather than the
waste: `FOR KEY SHARE` from every insert in a billing run versus `FOR UPDATE` from
one undo, and which one stalls behind the other.

`test_the_reversal_lock_does_not_join_the_term` asserts against **compiled SQL** —
exactly one `FOR UPDATE` statement, and `academics_term` absent from it. The join is
invisible in the Python, so the Python is not where it can be checked.

*Mutation:* restore `.select_related("term")` → red.

## 3 — a charge naming another term's line is refused

New `NotThisTermsLine(FeeLedgerError)`. `charge()` compares
`source_line.schedule.term_id` against `term.pk` when a `source_line` is passed.

**Free in the hot path, and asserted to be.** `apply_to_class()` reads its lines
through `locked.lines.all()`, and a reverse manager primes each line's `schedule`
from the instance it came from — so the guard compares two integers already in
memory. `test_the_line_guard_costs_no_query_per_charge` pins that at one
`fees_feeschedule` read per run, because a guard paid 135 times inside the schedule
lock would have been its own finding.

The test asserts the *consequence*, not just the exception: after the refusal the
child's slot in `a_schedule_line_charges_a_child_once` is still free and the real run
bills them. A refusal that consumed the slot would be the same bug wearing an
exception.

*Mutation:* remove the guard → red.

## 4 — a discount naming another child's concession is refused

New `NotThisStudentsConcession(FeeLedgerError)`. `discount()` compares
`source_concession.student_membership_id` against `membership.pk`.

`_require_student_of_this_school()` already guards the child half of every entry this
carefully; this is the same guard for the source half. The test asserts both that the
discount is refused and that **nothing posted against the concession** — the damage
was never a balance, it was "everything this concession did" answering with two
children.

*Mutation:* remove the guard → red.

## 5 — a long line description no longer produces an unreversible charge

`_inherited_narration()` builds `"Reversal of: X"` and trims it to the column's own
`max_length`, read from the field so the two cannot drift, marking the cut with an
ellipsis.

The test uses the **shortest description that overflows** — 243 characters, asserted
to be exactly that — rather than a round number that would keep passing if the
threshold moved.

*Mutation:* restore the raw f-string → red, and red as an **error**, not a failure:
`ValidationError` escapes uncaught. That is the finding restated by the test — the
old failure was not merely a save that failed, it was one that `except FeeLedgerError`
could not catch.

## The `is_live` correction, in the code

`fees/schedules.py` now says the guard is that **`status` is loaded**, at the read
where someone hardening this would edit, and says in as many words that
`select_related` is not it — remove the join and every leaver test stays green;
add `.only()` or `.defer("status")` and a child enrolled at read time is silently
dropped. The control test that proves it is permanent:
`test_a_deferred_status_would_drop_an_enrolled_child_from_billing`.
