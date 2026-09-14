# clone_schema prototype — measured

**2026-09-02.** Untracked; delete when copied. Branch `clone-schema-prototype`,
commit `32925ad`, pushed. **No PR opened** — it is a prototype, not a change to
how anything runs. Nothing imports it and no test calls it.

Files: `scripts/clone_schema.sql` (v1), `scripts/clone_schema_v2.sql` (v2),
`scripts/prototype_clone_schema.py` (the driver).

---

## The numbers, five consecutive of each

| | mean | range | vs baseline |
| --- | --- | --- | --- |
| **baseline** — `CREATE SCHEMA` + `migrate_schemas` | **1.968s** | 1.87–2.09s | — |
| **v1** — `LIKE INCLUDING ALL` | **0.382s** | 0.346–0.393s | **5.2x** |
| **v2** — index and constraint names preserved | **0.350s** | 0.308–0.391s | **5.6x** |

Template built once, by the ordinary path: **1.99s**. Break-even after ~1.2
tenants; the suite builds ~1,479.

Reported individually rather than averaged, because a mean would hide a
first-run cost — and a first-run cost is the whole question when the proposal is
"pay it once, then copy". **There isn't one.** The five clones sit inside
0.308–0.393s with no downward trend.

The baseline measures **1.97s here against the 1.65s** in the `tests.yml`
comment. Same order, different machine; the comparison that counts is against
the baseline measured beside it, not across machines.

---

## v1 is fast and wrong

`LIKE ... INCLUDING ALL` **does not copy index names.** Postgres regenerates
them from the table and columns, and does the same for the indexes behind
PRIMARY KEY and UNIQUE constraints:

```
migrated:  one_card_per_student_per_release
v1 clone:  results_releasedcard_sheet_id_student_membership_id_version_key
```

**66 of 96 indexes** and **23 of 184 constraints** differed.

That is not cosmetic in this repository:

- the results tests assert constraint violations **by name**, precisely so a
  bare `IntegrityError` cannot pass for the constraint under test;
- `NoIndexIsBuiltTwiceTests` reads index names out of `information_schema`.

A v1 test database would fail those — and worse, any test catching an
`IntegrityError` **without** checking the name would keep passing while
asserting something different from what it says.

## v2 replays them from the catalogue, and is faster for it

Excludes indexes and constraints from `LIKE`, then replays each with its own
name and definition. Faster than v1 because it builds each index **once**
instead of letting `INCLUDING ALL` build one and the constraint build another.

**Structure after v2: tables 28 same, columns 231 same, every index and
constraint name preserved.**

### The two objects that still differ, and why they do not count

Same artefact both times — an array cast re-rendered by the parser after a round
trip through SQL text:

```
migrated:  ANY ((ARRAY['payment'::varchar, 'discount'::varchar])::text[])
cloned:    ANY (ARRAY[('payment'::varchar)::text, ('discount'::varchar)::text])
```

Semantically identical; the cast distributes over the elements. The driver
compares **textually**, so it reports these as differences. They are not. A
semantic comparison would report zero.

---

## The one real gap, found by checking rather than assuming

A structure-only clone leaves **`django_migrations` empty**:

```
proto_t3 (migrated): django_migrations rows = 55
proto_c3 (cloned):   django_migrations rows = 0
```

The schema is structurally complete and yet reads as **never migrated**, so the
next `migrate_schemas` would try to apply all 55 again and fail on tables that
already exist. It is the one table whose *rows* are not data but bookkeeping.

v2 now copies them and moves the sequence with them. Verified:

```
proto_t4 (migrated): django_migrations rows = 55
proto_c4 (cloned):   django_migrations rows = 55
clone with the fix: 0.364s
```

---

## What this does NOT decide

Whether the suite should use it. That needs the test-runner half:

- a template schema built once per test database,
- `clone_schema` installed into it,
- `make_school()` routed through it.

That changes what every tenant test runs against. **The number says it is worth
designing; it does not say the design.** Not started — no authorisation asked
for or given.

Also untouched: the clone runs inside a test's transaction and rolls back like
`CREATE SCHEMA` does, so the `TestCase`-not-`TransactionTestCase` property in
`docs/tenancy.md` should survive — **asserted, not tested.**
