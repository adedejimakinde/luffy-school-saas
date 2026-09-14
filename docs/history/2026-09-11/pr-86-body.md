Closes #82.

`services.charge()` is `@transaction.atomic`, so `apply_to_class()` opened a
savepoint per entry: a 45-child three-line bill opened **135 subtransactions**
inside its one transaction, against the **64** subtransaction ids PostgreSQL
caches per backend. Past 64 the backend overflows and every *other* backend's
visibility check against those xids falls back to `pg_subtrans`, for as long as
the transaction stays open.

This is **option 1** of the three the issue set out: an inner `_charge()` with
no savepoint, called only by `apply_to_class()`, while the public `charge()`
keeps its decorator.

## Why option 1 and not the other two

**Option 2 (`bulk_create()`) buys speed by dropping `full_clean()`**, which
stops `Model.clean()`'s cross-row rules and the FK probes being asked and breaks
the "every entry funnels through `_post()`" invariant — the same funnel #83's
finding 1 was about. Weakening that in the money path is the wrong trade.

**Option 3 gives up all-or-nothing billing**; a partially billed class is worse
for a bursar than a slow one.

Two functions rather than one with the decorator removed, because `charge()`'s
own docstring has warned since the schedule work that *"the second caller is the
one that will not know"*. That caller must find the safe function under the
obvious name.

**The savepoint bought the charge loop nothing**, and that is structural rather
than a judgement: the loop catches nothing, so an `IntegrityError` rolled back
to its savepoint and then propagated out of `apply_to_class()`'s own atomic
block, aborting everything the savepoint was protecting.

## Measured before the fix was written

A 45-child three-line class. Statements counted with `CaptureQueriesContext`;
the transaction held open while a second connection scanned 20,000 times.

| children | rows | subtransactions | statements | wall |
|---|---|---|---|---|
| 10 | 30 | 30 | 318 | 0.096s |
| 45 | 135 | **135** | 1,368 | 0.363s |

Per entry: 1 SAVEPOINT + 1 RELEASE + 1 INSERT + 2 SELECT + 5 SET = **10 statements**.

| case | subxids | reader µs/scan | `Subtrans` blks_hit | blks_read |
|---|---|---|---|---|
| 45 children, via the service | 135 | **39.45** | **8,100,003** | **0** |
| 45 children, one insert | 0 | 12.29 | 1 | **0** |
| 10 children, via the service | 30 | 7.31 | 3 | **0** |
| 10 children, one insert | 0 | 7.52 | 4 | **0** |

The one-insert rows are the control: **the same number of tuples to check, zero
subtransactions**, so the row count is held fixed and the subxid effect is
isolated. `8,100,003` = 20,000 scans × 135 tuples × 3 lookups per tuple.

**It is a step, not a slope.** At 30 subtransactions the service and its control
are identical within noise and the counter does not move; at 135 it is 3.2× and
8.1 million lookups. The threshold is 64 ÷ 3 lines = **22 children**, so every
ordinary class was past it. A 45-child class is the median Nigerian secondary
class.

### Cache lookups, not disk

**`blks_read` is 0 in every row above, including the 8.1-million one.** All of it
was served from the in-memory Subtrans SLRU cache; there is no disk I/O anywhere
in these numbers. PostgreSQL 15's Subtrans cache is a fixed 32 buffers
(~65,536 xids) and nothing here comes near exhausting it. Worth stating because
it bounds the damage honestly: bad enough to triple every concurrent reader, not
bad enough to cause I/O storms.

### The caveat that matters, for whoever benchmarks this next

> **The cost is zero on an idle cluster.** My first run showed all zeros, and
> the reason is real: `XidInMVCCSnapshot()` returns "in progress" immediately
> for any xid ≥ the snapshot's `xmax`, so while nothing else commits, the
> billing subxids sit above every reader's `xmax` and `pg_subtrans` is never
> consulted. I had to run a committer alongside (8k–21k commits) to advance
> `latestCompletedXid` before the effect appeared. In production that committer
> is other schools' ordinary traffic — so this is **off when the cluster is
> quiet and fully on when it is busy**, which is the honest form of #82's "paid
> cluster-wide" claim.

A benchmark run against a quiet database will show this fix changing nothing,
and conclude it was unnecessary. It is not: it is measuring the one condition
under which the bug does not appear.

## The control run

`SubtransactionCountTests` counts savepoints rather than timing anything,
because the count is the mechanism and a timing here would be a flake.

Reverting the one word — `services._charge` back to `services.charge` — with the
tests in place:

```
Ran 4 tests in 8.386s
FAILED (failures=3)

FAIL: test_billing_a_class_opens_one_savepoint_not_one_per_charge
AssertionError: 5 != 1 : one savepoint for apply_to_class()'s own atomic block
and no more; a savepoint per charge is issue #82

FAIL: test_the_count_does_not_grow_with_the_class
AssertionError: 7 != 1 : the savepoint count must be flat in the size of the
class; that is the whole of #82, since 64 is the limit and a class is not

FAIL: test_a_discount_still_opens_one_because_its_handler_needs_one
AssertionError: 7 != 3 : one for the run and one per concession; if this ever
reads 1 the collision handler has lost the savepoint it rolls back to
```

**`5` and `7` are the subxid count growing with the class** — two children then
three, one savepoint per charge on top of the run's own. After the fix all three
read the run's savepoint plus one per concession and nothing more:

```
Ran 4 tests in 8.565s
OK
EXIT=0
```

`test_charge_still_leaves_an_enclosing_transaction_usable` **stayed GREEN
throughout**, and correctly: the control does not touch `charge()`, and that
test asserts the guarantee the decorator still buys. That is the control's own
control — had it moved, the control would have been proving something else.

## Deliberately not fixed here

**The discount loop still opens one savepoint per concession, and must** — its
collision handler needs one to roll back to, and removing it reintroduces the
bug where one collision leaves forty-five children unbilled. That leaves this
function under 64 **by margin rather than by construction**, since a class
cannot have more concessions than children. Filed as **#85** with the numbers in
it, to be measured rather than guessed at.

**The 683 `SET search_path` statements** of the 1,368 — five per entry, from
django_tenants — are untouched, and are a separate and larger question about the
tenant backend. Note that #82's own estimate of ~675 statements was **half** the
real figure; that is where the other half went.

## Runs

| target | result |
|---|---|
| `fees` | `Ran 106 tests in 182.126s`, `OK`, `EXIT=0` |
| `results.tests.test_withholding` | `Ran 69 tests in 281.169s`, `OK`, `EXIT=0` |
| `makemigrations --check` | `No changes detected` |

`test_withholding` because it is the neighbour: it charges children into arrears
through `fees.services.charge()`, which is the function this PR splits.
