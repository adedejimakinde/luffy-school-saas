Closes #67.

`connected_to` was defined **fourteen times** across fourteen test modules and
called about 850 times. Thirteen were character-for-character identical, wrapping
`schema_context(school.schema_name)`; the fourteenth, in
`schools/tests/test_tenant_isolation.py`, wrapped `tenant_context(school)`.
Nothing in the name said which one a module had imported.

There is now one, in `schools/tests/tenants.py` — already the shared home for
`make_school` — and it wraps `tenant_context`.

## Why `tenant_context` and not the thirteen

`tenant_context` restores the schema it found on the way out. `schema_context`
does not, and that is **#58**: an inner block's exit drops the *outer* block onto
public, and the next lazy read in the outer block goes looking for tenant tables
in the shared schema. It surfaces as `relation "…" does not exist` from a line
frames away from either `with`, and it has cost a lost run and a diagnosis twice.

Standardising on the thirteen would have kept that bug and merely centralised
it — one helper nobody suspects, instead of thirteen.

## ⚠️ Visible behaviour change: every log line inside a block

**Stating this plainly rather than burying it, because it is a behaviour change
and not a refactor artefact.**

`tenant_context(school)` puts the real `School` on `connection.tenant`.
`schema_context(name)` sets a `FakeTenant`, which knows a schema name and no
display name. `schools.logging.current_school()` reads that.

| | before | after |
| --- | --- | --- |
| the thirteen modules | `[st_marys]` | `[St Mary's]` |
| the fourteenth | `[St Mary's]` | `[St Mary's]` |

So thirteen modules change what their log output says. **Exactly one test
asserts on it** — `schools/tests/test_logging.py`, which already imported the
fourteenth and already expected `[St Mary's]`.

That asymmetry is the point: almost nothing would have failed if this were the
wrong call, which is why the issue asked for a full-suite run rather than an
argument, and why it is in the PR body rather than a footnote.

## `make_school()` no longer drops its caller onto public

The other half of #67, and the same bug as #58 three lines from the helper that
fixes it. `build_template()` and `clone_template()` both ended in
`set_schema_to_public()`, and `make_school()` calls `clone_template()` — so a
`make_school()` inside a `connected_to` block left that block on public, and the
block's next read failed exactly the way #58 failed.

Both genuinely need public for the DDL they run. What they did not need was to
*end* there. `_on_public()` keeps the reason and drops the footgun: go to public,
then put the connection back where it was.

`MakeSchoolInsideABlockTests` pins it, in four tests:

- the schema name is still the block's after `make_school()` returns;
- a real query after it still lands on the block's schema — the symptom rather
  than the mechanism, and the shape that actually bit;
- the outermost block still lands on public, which is the guarantee restoring was
  written to keep;
- called from public it still ends on public, which every `setUp` here depends on.

**Nothing else pinned this.** Every existing caller builds its schools in `setUp`,
before opening any block — which is how it survived a fix to `connected_to` that
was otherwise about precisely this.

## Scope

24 files: one helper added, fourteen definitions deleted, twenty-three modules
repointed, and the imports those deletions orphaned removed. Pre-existing unused
imports in the same files (`School`, `ReleasedCard`, `Term`, `TestCase`,
`ReportCardSettings`) are deliberately left alone — they are not this PR's.

## Verification

Full-suite CI is the gate here, for the reason in the log-lines section above.

| Run | Result |
| --- | --- |
| `schools` (209 tests, incl. `test_logging` — the log-line canary) | `Ran 209 tests in 103.429s`, `OK`, `EXIT=0` |
| **Control** — `_on_public` put back to ending on public (pre-#67) | `FAILED (failures=1, errors=1)`, `EXIT=1` |

The control reproduces #58's signature exactly:

```
AssertionError: 'public' != 'st_marys'
psycopg2.errors.UndefinedTable: relation "academics_term" does not exist
```

The second is the one worth looking at. It is an **error, not a failure** — the
query raised rather than returning something wrong, from a line that never
mentions a schema, which is the whole reason this class of bug is expensive.

The control discriminates cleanly: exactly the two tests asserting the *new*
behaviour fail, and the two asserting the *preserved* guarantees — outermost
block still lands on public, called-from-public still ends on public — pass
under both, because the old code got those right too.
