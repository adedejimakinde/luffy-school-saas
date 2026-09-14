---
name: luffy-subtransaction-measurement
description: "How the #82 subtransaction cost was actually measured, the numbers, and the two traps that made the first two attempts report nothing"
metadata: 
  node_type: memory
  type: project
  originSessionId: d07c2d64-4203-482c-a30e-3c51db52e69a
  modified: 2026-09-11T03:35:35.022Z
---

Taken 2026-09-11 for issue #82 (`apply_to_class()` opening ~135 subtransactions
per class). The user asked for the SLRU effect **shown, not inferred from the 64
limit**. Two attempts reported nothing before the third worked. Keep this —
re-deriving it cost most of a session.

## The numbers

`fees.schedules.apply_to_class()`, 3-line bill, statements counted with
`CaptureQueriesContext`:

| children | rows | subtransactions | statements | wall |
|---|---|---|---|---|
| 10 | 30 | 30 | 318 | 0.096s |
| 45 | 135 | **135** | **1,368** | 0.363s |

**Per entry: 1 SAVEPOINT + 1 RELEASE + 1 INSERT + 2 SELECT + 5 SET = 10
statements**, on 18 fixed. #82's own estimate of "~675 statements" was **half**
the real figure. The missing half is **683 `SET search_path`** from
django_tenants — 5 per entry — which no option in #82 addresses and which is a
separate question about the tenant backend.

Transaction held open, second connection scanning 20,000 times:

| case | subxids | reader us/scan | `Subtrans` blks_hit | blks_read |
|---|---|---|---|---|
| 45 children, via service | 135 | **39.45** | **8,100,003** | **0** |
| 45 children, one insert | 0 | 12.29 | 1 | **0** |
| 10 children, via service | 30 | 7.31 | 3 | **0** |
| 10 children, one insert | 0 | 7.52 | 4 | **0** |

`8,100,003` = 20,000 scans x 135 tuples x **3 lookups per tuple**.

**It is a step, not a slope.** At 30 subxids the service and its control are
identical within noise and the counter does not move. **The threshold is 64 / 3
lines = 22 children**, so every ordinary class was past it. The biller's *own*
cost is linear (4.23x wall for 4.5x children); the cliff is in **everybody
else**.

**`blks_read` is 0 everywhere, including the 8.1-million row.** This is
in-memory SLRU cache lookups, not disk I/O. PG15's Subtrans cache is a fixed 32
buffers (~65,536 xids) and nothing came near exhausting it. `blks_zeroed` of
4-10 is page initialisation as pg_subtrans extends — **not** pressure, and the
cumulative 1,859 on the cluster is the same thing. Keep those columns separate
or the report overstates the damage.

## Trap 1 — the effect is INVISIBLE on an idle cluster

The first run returned all zeros and it was not a bug in the harness.
`XidInMVCCSnapshot()` returns "in progress" **immediately** for any xid >= the
snapshot's `xmax`, so while nothing else is committing, the billing subxids sit
above every reader's `xmax` and **`pg_subtrans` is never consulted**.

Fix: a **committer thread** running `SELECT pg_current_xact_id()` in autocommit
alongside the reader, advancing `latestCompletedXid` past the subxids (8k-21k
commits over the run). In production that committer is other schools' ordinary
traffic.

**So the cost is zero on a quiet cluster and fully on when busy.** Anyone
benchmarking this fix against an idle database will measure no difference and
conclude it was unnecessary. This caveat is in PR #86's body as a block quote
for exactly that reason.

## Trap 2 — the row-count confound

A 45-child class leaves 135 tuples and a 10-child class leaves 30, so a reader
scanning each does 4.5x the visibility work for reasons with nothing to do with
subxids. **Every case needs a control that writes the same number of rows with
zero subtransactions** — a single `bulk_create()`. Without it the comparison is
meaningless. The first attempt's reader numbers were noise, and the 0-subxid
case came out *slower* than the 135-subxid one.

## Instrument notes (PostgreSQL 15.19 here)

- `stats_fetch_consistency = cache`, so **two reads of `pg_stat_slru` in one
  transaction return identical numbers**. Use a separate connection per read.
- SLRU counters are backend-local and flushed **at most once per second**.
  Reading straight after a fast loop reports zeros meaning "not yet flushed".
  Sleep ~1.2s before each read, and make the scan loop run for seconds.
- `pg_stat_reset_shared('slru')` **does not exist before PG16** — work in
  deltas on a quiet cluster.
- `pg_stat_get_backend_subxact` is not on this build. `pg_current_xact_id` and
  `pg_current_xact_id_if_assigned` are.
- Scan **server-side** in a `DO $$ ... LOOP ... END $$` block, not in a Python
  loop — round-trip time otherwise swamps the signal.
- `luffy_admin` is superuser.

## Harness shape

A temporary `fees/tests/test_measure_82.py`, run, then **deleted** (tree back to
clean). **`TransactionTestCase`, not `TestCase`** — under `TestCase` every write
sits in the test's own transaction, so `apply_to_class()`'s `@transaction.atomic`
becomes a savepoint rather than the top-level transaction it is in production,
**and a second connection cannot see the tenant schema at all**, schema creation
being uncommitted DDL.

Counting savepoints in a normal `TestCase` is still fine and is what the shipped
tests do: `CaptureQueriesContext` + `sql.strip().upper().startswith("SAVEPOINT")`
counts opens only, not `RELEASE`/`ROLLBACK TO`. In a `TestCase` the expected
count is **1 (apply_to_class's own) + one per concession**.

See [[luffy-open-work-state]], [[luffy-test-suite-runtime]],
[[control-runs-go-stale]], [[a-bound-needs-a-constraint]].
