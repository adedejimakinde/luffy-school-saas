# PR #79 — independent pass on the two questions

Branch `fee-schedule-billing`, head `426b4b1`, base `main` (`c236a18`).
Re-verified locally before starting: `Ran 87 tests in 121.854s`, `OK`, `EXIT=0` in `fees`.

> **Status:** this is my own read, done while `/code-review` runs against the branch.
> The reviewer's findings are still pending and will be appended below when they land.
> Nothing merged, nothing changed.

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
