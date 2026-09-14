# The clone number, and where #63 stands

*2026-09-02*

Rebase is pushed and the clone number is measured. CI is still running on both;
a watcher will return when they finish, and I'll merge #63 then.

## The number

**A clone per test costs `0.274s`. Migrating one costs `1.764s` beside it.**

Five consecutive clones, reported individually — a mean would hide a first-run
cost, and a first-run cost is the whole question when the proposal is "pay once,
then copy":

| | 1 | 2 | 3 | 4 | 5 | mean |
| --- | --- | --- | --- | --- | --- | --- |
| **clone per test** | 0.335 | 0.292 | 0.253 | 0.257 | 0.234 | **0.274s** |
| **migrate per test** | 1.749 | 1.792 | 1.761 | 1.711 | 1.808 | **1.764s** |

- **6.4x** against the baseline measured in the same run on the same machine;
  **6.0x** against the `1.65s` in the `tests.yml` comment.
- Template built once for the run, by the ordinary path: **1.688s**.
- **Break-even after 1.1 tenants.** The suite builds ~1,479.

The clones drift *down* across the five, not up — no warm-up penalty hiding in
the mean. This machine's own migrate baseline is 1.764s against CI's cited
1.65s; same order, different machine, which is exactly why both figures were
taken in one run rather than compared across machines.

**Two things this run tested that the earlier one structurally could not.** The
old driver measured a script against the *development* database, outside any
transaction. This runs in the test database, inside the per-test transaction,
with a rollback between every clone.

The rollback property is now tested rather than asserted — it was the one thing
that could have killed the idea outright, since `docs/tenancy.md` depends on
tenant tests being `TestCase` and not `TransactionTestCase`. Four tests assert
the previous test's clone is **gone** before making the next. All four pass;
nothing leaks between tests. And the structural check moved into the test
database: 98 index names and 190 constraint names preserved.

```
Ran 11 tests in 12.261s
OK
EXIT=0
```

Committed as `7fb60c0` on `clone-schema-prototype`, rebased onto `16dd75c` and
pushed. **No PR** — nothing imports `prototype_tests/` and `make_school()` is
untouched. Whether the suite should actually use this is a design decision, not
a number, and I haven't started it.

## #63

Rebased onto `16dd75c` cleanly, force-pushed as `c5a2a0c`. Local gate on the app
touched: 4/4 `OK`, `EXIT=0`. CI re-running now (`33650339369`) — this is the run
that matters, since it's the first time the new runner drives a suite containing
task 7's tests.

Main's CI on `16dd75c` (`33649097683`) is still in progress. **I have not
confirmed it green yet**, and I won't merge #63 until I have both.
