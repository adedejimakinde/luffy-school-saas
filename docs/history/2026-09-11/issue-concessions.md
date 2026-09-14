Split out of #82 rather than fixed alongside it. The charge loop's savepoints are
gone; the discount loop's are not, and they are bounded by nothing but how many
concessions a school happens to have granted.

## The residual

`apply_to_class()`'s discount loop calls `services.discount()`, which is
`@transaction.atomic`, once per active concession for the class. **Those
savepoints are load-bearing** and must not simply be removed the way the charge
loop's were: the collision handler at the foot of the loop catches
`IntegrityError` and needs the failed entry rolled back to a savepoint so the
outer transaction stays usable. Without it, one concession collision kills the
whole run and forty-five children go unbilled — the exact outcome the skip
exists to prevent.

So the discount loop opens **one subtransaction per concession**, and the count
is the number of concessions, not a constant.

## The number

PostgreSQL caches **64** subtransaction ids per backend (`PGPROC_MAX_CACHED_SUBXIDS`).
Past that the backend overflows and every *other* backend's visibility check
against those xids falls back to `pg_subtrans`.

Measured on this hardware while the fix for #82 was being taken, holding the
billing transaction open and scanning from a concurrent backend:

| subtransactions | reader µs/scan | `Subtrans` blks_hit | blks_read |
|---|---|---|---|
| 30 | 7.31 | 3 | 0 |
| 135 | 39.45 | 8,100,003 | 0 |

A control writing the *same number of rows* in one statement — zero
subtransactions — came back at 12.29µs and 1 lookup, which is how the row count
was held fixed and the subxid effect isolated.

**So a class with more than 64 concessions reproduces #82 exactly**, through the
one loop #82's fix deliberately did not touch.

## Why it is filed rather than fixed

A class of 45 children cannot have more than 45 concessions, so today this is
under the limit **by margin, not by construction**. That is a real distinction
and not a reassuring one: nothing in the code says 64, nothing tests it, and the
margin is a property of class sizes rather than of this loop.

Scholarship-heavy schools are real but rare, and a school billing a class where
most children hold more than one concession is the shape that reaches it first.
It deserves the same measured treatment the charge loop got — a number, a
control, and a demonstration — rather than a guess bolted onto the #82 fix.

## What a fix has to preserve

Whatever replaces the per-concession savepoint must keep the property the
handler exists for: **a collision on one child's discount is a skip, not the end
of the run.** The narrowing in that handler is already complete for the path —
of the ten constraints on `FeeLedgerEntry` exactly one is reachable from a
concession discount — so the shape of the answer is probably to detect the
collision without needing rollback, not to catch it more cheaply.

## Not in scope

The `SET search_path` traffic measured alongside this (683 statements of 1,368
for a 45-child bill, 5 per entry, from django_tenants) is a separate and larger
question about the tenant backend, not about savepoints.
