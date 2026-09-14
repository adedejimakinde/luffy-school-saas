---
name: luffy-85-discount-subtransactions
description: "#85's numbers — the subxid cost is a hard STEP at 64, not a slope — plus the ON CONFLICT mechanics Django and Postgres actually permit"
metadata:
  node_type: memory
  type: project
---

Taken 2026-09-12 for issue #85 (the discount loop's savepoint per concession).
Shipped as PR #87. Keep the numbers and the mechanics — both cost real time.

## The cost is a STEP at 64, not a slope

Transaction held open, second backend scanning 20,000 times, **committer thread
running** (trap 1 from [[luffy-subtransaction-measurement]] — without it every row
reads zero), each arm paired against a control writing **the same number of rows**
in one statement (trap 2):

| rows | subxids | us/scan | `Subtrans` blks_hit | blks_read |
|---|---|---|---|---|
| 45 | **45** | 7.22 | **0** | 0 |
| 45 | 0 | 6.39 | 0 | 0 |
| 66 | **66** | **16.36** | **2,640,000** | 0 |
| 66 | 0 | 6.84 | 0 | 0 |
| 90 | **90** | 19.06 | 3,600,000 | 0 |
| 135 | **135** | 25.48 | 5,400,000 | 0 |

`blks_hit` = 20,000 scans x N rows x **2** lookups per tuple, exactly. (#82 saw 3
per tuple on its rows; the per-tuple constant varies, the mechanism does not.)

**45 subxids produce ZERO SLRU lookups and sit within noise of their control.**
Below 64 the cost is not small, it is nil. So a benchmark at 45 children, or on an
idle cluster, measures no difference and concludes the fix was unnecessary — two
separate ways to get a false negative.

`blks_read` is 0 throughout: in-memory SLRU, **not disk I/O**. `blks_zeroed` 17-19
is page initialisation. Keep them separate or the report overstates the damage.

## The transfer function, and the re-run finding

`savepoints = 1 + (concessions not already discounted this term)`, counted from
the query log. The `1` is `apply_to_class()`'s own atomic block, a savepoint only
under `TestCase` — **there is no `ATOMIC_REQUESTS` in `settings.py`**, so in
production that block is the top-level transaction and the subxid count equals
the concession count exactly.

**A re-run opens ZERO**, before and after the fix: the skip check `continue`s
before the service is reached and its skip-set is term-scoped. The exposure was
always the **first application of a bill in a term**, not a standing cost.

## Why a constraint could not have been the fix

The overflowing quantity is a **sum over the roster**, so no per-child constraint
bounds it: 2/child breaches 64 at 33 children, 1/child at 65. Bounding the real
quantity needs a constraint spanning `FeeConcession` x placements x term, across
tables, one of which (`Membership`) is in `public` while placements are tenant-
schema. Not expressible as a table constraint. See [[a-bound-needs-a-constraint]].

## ON CONFLICT mechanics — verified, not assumed

- **`ON CONFLICT ON CONSTRAINT <name>` does NOT work for a Django
  `UniqueConstraint` carrying a `condition`.** That is created as a *partial
  unique index*, not a table constraint; Postgres answers `constraint "..." for
  table "..." does not exist`. Use the **inference clause** instead — columns plus
  the same `WHERE` predicate — which does reach a partial index.
- **Django cannot emit it.** `on_conflict_suffix_sql` returns a bare
  `ON CONFLICT DO NOTHING` for `IGNORE` (read the source at
  `django/db/backends/postgresql/operations.py`), and `UPDATE` emits
  `ON CONFLICT(cols)` with no predicate. `bulk_create(ignore_conflicts=True)` is
  therefore **untargeted** and also does not set pks. Hand-write the INSERT.
- A **targeted** clause still raises another index's unique violation — proven by
  creating a second index in a test. A bare `DO NOTHING` swallows it silently.
- `DO NOTHING` covers unique/exclusion violations **only**. FK violations still
  raise.
- **...but Django's FKs are `DEFERRABLE INITIALLY DEFERRED`**, so an FK violation
  fires at **COMMIT**, not at the INSERT. A test asserting `IntegrityError` around
  the statement catches nothing and the error surfaces in `check_constraints()`
  during teardown, attributed to whatever ran next. Force it with
  `SET CONSTRAINTS ALL IMMEDIATE`.
- **`full_clean()` refuses a dangling FK first anyway** — `ForeignKey.validate()`
  looks the row up — so it arrives as `ValidationError`. Two code comments in
  `fees` claimed "the INSERT fails"; neither was the mechanism. Corrected in #87.
- Going around `Model.save()` means setting `_state.adding = False` and
  `_state.db` yourself, as `save_base()` does. Without it the returned object
  still claims to be unsaved and `FeeLedgerEntry`'s append-only guard — which
  reads `_state.adding` — stops firing on exactly the rows that path returns.
- **`ON CONFLICT DO NOTHING` does not retire a deadlock risk.** It still takes a
  row lock and waits, and a deadlock is not a conflict, so no skip is reachable
  for it. The `FeeConcession.Meta.ordering` total order is still what prevents it.

## A raw INSERT is a scoping claim

It uses a bare table name and leans on django_tenants' `search_path`, so it is
exactly the kind of write that lands in the wrong school. It needs a **2-tenant**
test like anything else that can be scoped wrong.

See [[luffy-no-pilot-data]], [[luffy-subtransaction-measurement]],
[[luffy-open-work-state]], [[control-runs-go-stale]].
