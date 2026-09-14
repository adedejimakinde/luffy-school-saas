Closes #58.

`schools/tests/test_tenant_isolation.connected_to()` ended in
`set_schema_to_public()` unconditionally:

```python
connection.set_tenant(school)
try:
    yield
finally:
    connection.set_schema_to_public()
```

At the outermost level that is invisible — the schema it found *was* public, so
forcing public and restoring public are the same thing. One level in it is a
trap. The inner block's exit drops the **outer** block onto public, and every
read after it in the outer block looks for tenant tables in the shared schema.

## What it costs is the diagnosis, not the failure

The failure never mentions a schema. It arrives as

```
django.db.utils.ProgrammingError: relation "results_releasedsubjectresult" does not exist
```

from whichever line touched the object next — inside a payload builder, a
serialiser, a `refresh_from_db` three frames from either `with` — and the helper
that produced the object works perfectly when called on its own. Task 7 lost a
test run to it. `results/tests/test_pdf.py` has carried a workaround for it
since.

## The change

```python
with tenant_context(school):
    yield
```

**`tenant_context` and not `schema_context`**, though the two are otherwise the
same save-and-restore. `tenant_context` hands `connection.tenant` the real
`School`; `schema_context` sets a `FakeTenant`, which knows a schema name and no
display name. `schools.logging.current_school()` reads that attribute, and
`schools/tests/test_logging.py` — which imports this helper — asserts on
`[St Mary's]`, not `[st_marys]`. The other thirteen `connected_to` definitions
in this repo *do* wrap `schema_context`, which is why that is worth stating
rather than assuming. **Issue #67** covers the duplication itself, including the
fact that swapping a module between the two silently changes what its logs say.

`schools/tasks.py` already banks on this nesting in production code — "Wrapping
again is harmless — `tenant_context` nests" — so the semantics are not new to
the codebase, only to this helper.

## The old guarantee is kept, not traded away

The original was written the way it was for a reason: a test left connected to a
schema that is about to be dropped fails somewhere else entirely. Restoring what
was current still lands the **outermost** block back on public, so that cannot
happen. And nothing in the repo nests today — not textually and not through a
helper — so every one of the ~850 existing call sites restores the public schema
it was already given. `test_the_outermost_block_still_lands_on_public` is the
assertion for that, and it is the one test of the seven that passes against the
old helper too.

## Tests

`ConnectedToNestsTests`, seven tests over two schools:

| | |
| --- | --- |
| `test_leaving_an_inner_block_returns_to_the_outer_school` | the mechanism |
| `test_the_outer_block_can_still_read_its_own_rows` | the same thing a caller would notice |
| `test_an_object_fetched_in_an_inner_block_is_read_in_the_outer_one` | the shape that actually bit: a lazy read after somebody else's block |
| `test_three_levels_unwind_one_at_a_time` | restores the *previous* schema, not "the outer school" |
| `test_an_exception_inside_an_inner_block_still_restores_the_outer_one` | the unwinding path |
| `test_the_outermost_block_still_lands_on_public` | the old guarantee, kept |
| `test_the_connection_carries_the_school_itself_not_a_stand_in` | why `tenant_context` |

## `test_pdf` drops its workaround

`TheRenderedPageTests` kept a context-free `_card()` purely so that `html()`
could repeat the lookup instead of calling it, with a docstring explaining why.
Now `card()` opens a block of its own and `html()` calls it from inside its own
— the ordinary way to write it, and the shape that used to die.

That is also this PR's second control: run against the old helper, the new
`test_pdf` shape fails five tests with the missing-relation error verbatim.

## Verification

| Run | Result |
| --- | --- |
| `ConnectedToNestsTests` against the **old** helper | `Ran 7 tests`, `FAILED (failures=4, errors=2)`, `EXIT=1` |
| `ConnectedToNestsTests` against this one | `Ran 7 tests in 4.206s`, `OK`, `EXIT=0` |
| `schools` + `results.tests.test_pdf` | `Ran 238 tests in 220.234s`, `OK`, `EXIT=0` |
| `TheRenderedPageTests`'s new shape against the **old** helper | `Ran 6 tests`, `FAILED (errors=5)`, `EXIT=1` |

Two of the six control failures are `ProgrammingError: relation "academics_term"
does not exist` raised from `refresh_from_db` — the diagnosis this issue is
about, reproduced on purpose.

## Overlap with #66

Both branches are cut from `main` at `ff36dda` and both touch
`results/tests/test_pdf.py`, in different regions. `git merge-tree` reports a
clean merge either way round. Nothing here reads or writes `ReleasedCardPdf`.
