# clone-schema adoption — where it stands

*2026-09-03. Untracked in `/workspace`; delete it when you have copied it.*

Branch `clone-schema-adoption`, 4 commits on top of `main` (`923b745`), in
`~/worktrees/clone-schema-adoption`. **Not pushed, no PR yet.**

## Gated locally, green

| run | tests | result | wall |
| --- | --- | --- | --- |
| `test_tenant_isolation` + `test_classes` + `test_positions` + `test_ledger` | 120 | `OK`, `EXIT=0` | **151.6s** |
| `schools.tests.test_tenant_template` (the proof module) | 10 | `OK`, `EXIT=0` | **6.6s** |

The baseline for the same 120 tests — `main` at `923b745`, migrating one schema
per test — is still running. 75 schemas migrated so far against the adoption
run's 10 for the whole suite, which is the cost being removed, visible as it
happens.

## What the self-review found

`.github/workflows/tests.yml` still said:

> every `make_school()` issues a real `CREATE SCHEMA` followed by a real
> `migrate_schemas` run

That is false on this branch — `make_school()` copies a template now. It is
also exactly the class of claim the branch's own last commit was about ("say the
true thing in the four places that described a per-test migrate"), and it was
missed because it sits in the *services* block, arguing why CI needs a real
Postgres, rather than in the `--parallel` comment where the other four were.

Reworded to say what is actually true, and it makes the same argument more
strongly: the template is built by a real `migrate_schemas`, and the copy is
catalogue SQL — `pg_constraint`, `pg_get_triggerdef` — which nothing but
Postgres has. **Fixed, not yet committed.**

## What the branch does

- One tenant schema, `tenant_template`, migrated **once per test database**;
  every test's school is a copy of it. The migrate cost ~1.65s and the suite
  paid it ~1,479 times a run — about 90% of its wall clock.
- `schools/tests/runner.py` (as `settings.TEST_RUNNER`) builds it **between**
  Django creating the test database and Django cloning it for the `--parallel`
  workers, so each worker inherits it through `CREATE DATABASE ... TEMPLATE ...`
  and no worker migrates anything.
- `schools/tests/clone_tenant_schema.sql` copies rows, sequence positions,
  functions and triggers as well as structure, and preserves index and
  constraint **names**.
- `schools/tests/test_tenant_template.py` compares a clone against a freshly
  migrated schema on every kind of object, and four tests check that a clone is
  undone by the per-test rollback.

Still migrating on purpose: `RealSchemaCreationTests` (that path is its
subject), the four `auto_create_schema = False` modules (public schema only),
and the three `TransactionTestCase` modules (21 tests — nothing they do is
rolled back).

## What is left

1. Baseline number lands → fill the before/after in.
2. Commit the `tests.yml` fix.
3. Push, open the PR against `main`.
4. **Merging still waits on your word.**
