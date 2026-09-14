Found while fixing #58.

`connected_to` is defined **fourteen times** in this repo, in fourteen test
modules, and called about 850 times:

```
academics/tests/test_classes.py          gradebook/tests/test_scores.py
academics/tests/test_term.py             results/tests/test_approval_chain.py
fees/tests/test_ledger.py                results/tests/test_approval_concurrency.py
results/tests/test_card_api.py           results/tests/test_class_teacher_scope.py
results/tests/test_comments.py           results/tests/test_positions.py
results/tests/test_ratings.py            results/tests/test_ratings_concurrency.py
results/tests/test_release_roster_race.py
schools/tests/test_tenant_isolation.py
```

Four more modules import one of them rather than defining a fifteenth
(`test_logging`, `test_background`, `test_pdf`, `test_session_expiry`,
`test_sessions`, `test_revision`, `test_cards`, `test_grades`).

## They are not the same helper

Thirteen are character-for-character identical:

```python
@contextlib.contextmanager
def connected_to(school):
    with schema_context(school.schema_name):
        yield
```

The fourteenth, in `schools/tests/test_tenant_isolation.py`, wraps
`tenant_context(school)` instead — after #58; before it, it hand-rolled
`set_tenant` / `set_schema_to_public` and did not nest at all.

`schema_context(name)` sets a `FakeTenant`, which carries a schema name and no
display name. `tenant_context(school)` sets the `School` itself.
`schools.logging.current_school()` reads `connection.tenant.name`, so under the
thirteen every log line reads `[st_marys]` and under the fourteenth it reads
`[St Mary's]`. `schools/tests/test_logging.py` asserts the second one and
imports the fourteenth.

So a module that swaps which `connected_to` it imports — the obvious tidy-up,
and the obvious first step of any deduplication — silently changes what its log
lines say. Only one module asserts on that, so almost nothing would fail.

## Why it is worth an issue rather than a paste

#58 was a divergent copy costing a lost test run and a diagnosis three frames
from the cause. Thirteen of these are one paste away from a fourteenth
divergence, and the name gives no hint that there is more than one.

## Options

- **One helper in `schools/tests/tenants.py`**, which is already the shared home
  for `make_school`. Delete the fourteen definitions, add an import to the ~22
  modules. Pick `tenant_context`, so `connection.tenant` is the `School`
  everywhere and log assertions mean the same thing in every module — that is a
  behaviour change for thirteen modules, invisible unless something reads
  `connection.tenant`, and it needs a full-suite run to say so with a straight
  face.
- **Same, but keep `schema_context`** for the thirteen and give the isolation
  module's variant a different name, so the difference is in the name rather
  than in the file it happens to live in.
- **Leave them and document it** — a comment on each saying which of the two it
  is. Cheapest, and does nothing about the fifteenth copy.

## While in there

`schools/tests/tenants.py` has the same shape #58 was about, still armed:
`build_template()` and `clone_template()` end in
`connection.set_schema_to_public()` (lines 95, 112, 120), and `make_school()`
calls `clone_template()`. Calling `make_school()` from inside a `connected_to`
block therefore leaves the block on public. Those three want public for the DDL
they run, which is a real reason — but restoring afterwards would keep the
reason and drop the footgun.

Not chosen here.
