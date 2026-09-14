One tenant schema is migrated per test database and every test's school is a
copy of it, instead of `CREATE SCHEMA` plus `migrate_schemas` once per test
method — ~1.65s, roughly 1,479 times a run, about 90% of the suite's wall clock
and none of it assertion work.

## Before / after

The number that matters is the whole suite on CI, so that is the headline. Both
rows are the same job on the same workflow, and both report the runner's own
`EXIT=`/`RESULT=` block rather than a badge.

| | commit | tests | Django's line | `EXIT` | `RESULT` | job wall |
| --- | --- | --- | --- | --- | --- | --- |
| **before** | `923b745` (main) | 1145 | `Ran 1145 tests in 1778.918s` | `EXIT=0` | `RESULT=OK` | **30m39s** |
| **after** | `a098a53` (this PR) | 1155 | `Ran 1155 tests in 826.171s` | `EXIT=0` | `RESULT=OK` | **14m55s** |

**2.15x on the runner's own clock — 1778.9s to 826.2s — and 15m44s off the
job.** The after row runs *ten more tests* than the before row: the ten in
`schools/tests/test_tenant_template.py`, which did not exist to run before.

It is not the 6.4x a single clone measures against a single migrate, and the
difference is worth stating rather than rounding away: schema building was about
90% of the suite's wall clock, not 100%, and 21 tests in the three
`TransactionTestCase` modules still migrate for real by design. What is left is
assertion work and those.

Baseline is run
[33654406471](https://github.com/adedejimakinde/luffy-school-saas/actions/runs/33654406471),
the post-merge run of #63 on the commit this branch is cut from; the after row is
[33706333045](https://github.com/adedejimakinde/luffy-school-saas/actions/runs/33706333045).

Locally, the same 120 tests on both sides — `schools.tests.test_tenant_isolation`,
`academics.tests.test_classes`, `results.tests.test_positions`,
`fees.tests.test_ledger`:

| | Django's line | exit | wall |
| --- | --- | --- | --- |
| **before** (`923b745`) | `Ran 120 tests in 399.163s` / `OK` | `EXIT=0` | 403s |
| **after** (this branch) | `Ran 120 tests in 151.562s` / `OK` | `EXIT=0` | 160s |

**2.6x on that slice, and the mechanism is visible in the logs: 189 schemas
migrated before, 10 after** — the template, plus the ones the exclusions below
still build on purpose. The slice is a gate, not the claim; the claim is the
CI row above.

`results/tests/test_card_api.py` alone, measured while the branch was being
written: **195.8s → 119.0s**.

The four modules that get the clone by *re-export* rather than by importing the
helper — `results.tests.test_cards`, `results.tests.test_revision`,
`schools.tests.test_cross_schema_fk`, `schools.tests.test_logging` — were run as
their own gate: `Ran 111 tests in 217.844s`, `OK`, `EXIT=0`, and **one schema
migrated in the entire run**. That one is the template.

## What holds the substitution up, and nothing else does

`schools/tests/test_tenant_template.py` — 10 tests. Two properties have to be
true for a copy to stand in for a migrated schema, and **neither would produce a
failure anywhere else in the suite if it stopped holding.**

**`SchemaFromACloneIsRolledBackTests` — four tests.** They guarantee that a
cloned schema is undone by the same per-test transaction rollback that undoes a
`CREATE SCHEMA`. `docs/tenancy.md` depends on tenant tests being `TestCase`
rather than `TransactionTestCase`; if a clone survived its test, every test
would leak a schema, and the first symptom would be some unrelated test failing
on a schema name that was supposed to be free — a long way from the cause.

The property is *between* tests, so it cannot be asserted inside one. Each of
the four checks the **previous** test's clone is gone before making its own.
That is why they look redundant: four tests that appear to do the same thing,
none of which asserts anything about its own subject.

**They are permanent regression tests, not prototype scaffolding.** Deleting
them as redundant is precisely how this breaks, and it would break silently —
the suite would go green for as long as the leak happened not to collide with a
name. If they ever fail, `make_school()` goes back to migrating.

**`AClonedSchemaIsTheSameSchemaTests`** compares a clone against a schema
migrated in the same test, on tables, columns, indexes, constraints, sequences,
functions and triggers — plus row counts for every table, the seeds read back
through the ORM, and a sequence that must not hand out an id a seeded row
already holds. It asserts the trigger and function counts are **non-zero**, so a
clone that copied none of them cannot pass by matching 0 against 0.

That guard is not hypothetical. The prototype's clone copied tables, indexes and
constraints, and checked itself by comparing index and constraint names — the
things it copied — so it reported success:

| | migrated | prototype clone |
| --- | --- | --- |
| triggers | 13 | **0** |
| functions | 13 | **0** |
| seeded traits / scale points / grade bands / settings | 11 / 5 / 9 / 1 | **0** |

Adopted as-is that would have removed every `append_only` guarantee from every
test's schema and started every school with no traits, no rating scale and no
grade bands — a green suite asserting less than it claimed.

## What still migrates, and why each one has to

Four exclusions. Each is a case where using the template would delete the thing
being tested or quietly break it, so none of them is an optimisation left on the
table:

1. **`RealSchemaCreationTests`** in `schools/tests/test_tenant_isolation.py` —
   its subject *is* the production path. It asserts that saving a `School`
   issues a real `CREATE SCHEMA`, that `migrate_schemas` puts the TENANT_APPS
   tables in it, that SHARED_APPS tables do not leak into it, and that you are
   left on `public` afterwards. Pointed at the template it would assert those
   things about a copy this branch made, and the code that really creates
   schemas would have no test at all. It calls `make_school_by_migrating()` and
   pays the ~1.65s deliberately. **Do not "optimise" this one.**
2. **The four `auto_create_schema = False` modules** — accounts
   `test_membership`, `test_transfers`, `test_transfer_concurrency`, schools
   `test_invitations`. Every model they touch is in the public schema; they
   never built a tenant schema and never paid the cost. Cloning would hand them
   a schema they deliberately do without.
3. **The three `TransactionTestCase` modules** — results
   `test_approval_concurrency`, `test_ratings_concurrency`,
   `test_release_roster_race`, 21 tests. Nothing they do is rolled back: they
   commit real schemas and drop them in teardown, and Django's flush between
   their tests would empty a cloned schema's seeded rows. Converting them is a
   question about their teardown, not about the clone function, and is not
   answered here.
4. **The template itself**, once per test database, by a real `migrate_schemas`.

## How it is wired

`schools/tests/runner.py`, as `settings.TEST_RUNNER`, builds the template in
`setup_databases()` — in the window **between** Django creating the test
database and Django cloning it for the `--parallel` workers. Each worker then
inherits the template through `CREATE DATABASE ... TEMPLATE ...` and **no worker
migrates anything**; built after that loop, all N workers would each migrate
their own. Django has no hook between those two statements, so the runner asks
for the database with `parallel` temporarily 0 and makes the worker clones
itself, with the call and the `..._1 … _N` names Django would have used.
Teardown is untouched.

There is deliberately **no lazy fallback**. A missing template rebuilt inside
the per-test transaction would be rolled back with it, once per test — slower
than the migration it replaces, and silent. It raises and says what to check.

`schools/tests/clone_tenant_schema.sql` carries rows (every table, not just
`django_migrations`), sequence positions, functions and triggers as well as
structure, and preserves index and constraint **names** — this repository
asserts constraint violations by name so a bare `IntegrityError` cannot pass for
the constraint under test. Two traps, both commented in the SQL:

- **`check_function_bodies`** compiles a PL/pgSQL body at CREATE time and
  resolves the tables it names. These bodies are unqualified, so the functions
  must be created with `search_path` pointing at the destination schema, or they
  fail with `relation "gradebook_score" does not exist`.
- **`LIKE ... INCLUDING IDENTITY` creates the identity sequence itself.**
  Pre-creating sequences before the tables gave 54 sequences against the
  source's 27 — a manual `x_id_seq` plus an identity `x_id_seq1`. Tables first.

## Also in here

`make_school()` was **14 copy-pasted definitions**. The ten that migrated now
import one shared `schools/tests/tenants.py`; the modules that re-export it
through `results.tests.test_positions` and `schools.tests.test_tenant_isolation`
pick up the clone with it. `results/tests/test_card_api.py` built two schools per
test across 30 tests through a `_school()` method rather than a module-level
copy, which is why the first pass missed it.

Five comments and docstrings that described a per-test migrate now describe what
actually happens, including the exclusions above — the last of them in
`tests.yml`'s `services:` block, fifty lines from where the change was visibly
happening. This is exactly the kind of claim nothing in the suite contradicts.
