# clone_schema, the runner half — measured

*2026-09-02. Untracked; delete when copied.*
Branch `clone-schema-prototype`, commit `7fb60c0`, rebased onto `16dd75c` and
pushed. **No PR** — nothing imports it, `make_school()` is untouched.

New file: `prototype_tests/test_clone_per_test.py`.

---

## The number

**A clone per test costs `0.274s`. Migrating one costs `1.764s` beside it.**

Five consecutive clones, reported individually because a mean would hide a
first-run cost, and a first-run cost is the whole question when the proposal is
"pay once, then copy":

| | 1 | 2 | 3 | 4 | 5 | mean |
| --- | --- | --- | --- | --- | --- | --- |
| **clone per test** | 0.335 | 0.292 | 0.253 | 0.257 | 0.234 | **0.274s** |
| **migrate per test** | 1.749 | 1.792 | 1.761 | 1.711 | 1.808 | **1.764s** |

- **6.4x faster** against the baseline measured in the same run on the same
  machine; **6.0x** against the `1.65s` figure in the `tests.yml` comment.
- Template built once for the run, by the ordinary path: **1.688s**.
- **Break-even after 1.1 tenants.** The suite builds ~1,479.

The clones drift *down* across the five (0.335 → 0.234), not up. There is no
warm-up penalty hiding in the mean.

The machine's own migrate baseline is **1.764s against the 1.65s** the CI
comment cites — same order, different machine. The comparison that counts is
the one measured beside it, which is why both were taken in a single run.

---

## What this run tested that the earlier one could not

The earlier driver measured a script against the **development** database,
outside any transaction. This measures the conditions the suite imposes: the
**test** database, inside the **per-test transaction**, with a rollback between
every clone.

**The rollback property is now tested, not asserted.** `docs/tenancy.md` depends
on tenant tests being `TestCase` and not `TransactionTestCase`, so a clone has
to survive being wrapped in a transaction that is then thrown away. The earlier
write-up called this "asserted, not tested" — it was the one thing that could
have made the whole idea impossible. Four tests now assert the previous test's
clone is **gone** before making the next one. All four pass: a clone is undone
by the same rollback that undoes a `CREATE SCHEMA`. Nothing leaks between tests.

**The structure check moved into the test database.** 98 index names and 190
constraint names preserved — the thing v1 got wrong, now confirmed on the
database that would actually be built this way, not just on the dev one.

```
Ran 11 tests in 12.261s
OK
EXIT=0
```

---

## What this does NOT decide

Whether the suite should use it. Routing `make_school()` through a template
changes what every tenant test runs against, and that is a design with a
decision behind it, not a number. **Not started, not authorised.**

Worth noting for whenever that decision is taken: 33 test files build schemas in
`setUp`, so the win is per *test method*, and the four `TransactionTestCase`
classes that build real schemas would keep doing so.
