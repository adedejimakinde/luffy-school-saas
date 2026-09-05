# PR #79 — independent pass on the two questions

Branch `fee-schedule-billing`, **head `08b40cf`**, base `main` (`c236a18`).
Worktree clean; `08b40cf` is what PR #79 points at, merge-base `c236a18`, `MERGEABLE`/`CLEAN`.

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
