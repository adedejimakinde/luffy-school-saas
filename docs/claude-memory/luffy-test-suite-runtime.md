---
name: luffy-test-suite-runtime
description: "What the luffy-school-saas suite costs to run, before and after the clone-schema change, and where to run it"
metadata:
  type: project
---

## Run the suite through `scripts/run-tests.sh`, not `manage.py` directly

Landed in `main` by **PR #63**. It is what CI's "Run tests" step invokes, so
using it locally makes "green locally" and "green in CI" the *same* claim
rather than two that resemble each other. Arguments pass through to
`manage.py test`; with none it runs `--verbosity 2 --parallel` exactly as CI
does. `RUN_TESTS_LOG=<path>` chooses the log file.

It refuses two silences that have each cost this project real time: a pipe
eating the exit code (it reads `${PIPESTATUS[0]}`, since `tee` would otherwise
answer for `manage.py`), and **a run that exits 0 without ever printing `OK` or
`FAILED`** — which it reports as a failure. It prints `EXIT=` and `RESULT=`
every time, because either alone has been misread here.

Stop hand-rolling `python manage.py test … > log; echo EXIT=$?` runners. That
shape is what produced the original #61 misreading.

**LOCAL = only the app under test. The full suite runs in CI on push** (free
minutes). Env vars every local run needs:

```
export DJANGO_DEBUG=1
export INVITATION_ACCEPT_URL='http://localhost:3000/invitations/{token}/'
export EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

Postgres is reachable at host **`db`** (not localhost). `docker` is **not**
installed in the devcontainer; the database is a compose service already up.
`/usr/bin/time` is **not** installed either — time with bash `$SECONDS`.

## What it costs, after PR #64 (2026-09-03)

CI, full suite: **`Ran 1155 tests in 826.171s`**, job wall **14m55s**. Before
#64 it was `Ran 1145 tests in 1778.918s` and 30m39s. **2.15x.**

The `results` app alone, locally: **1454.876s** for 545 tests, against
`2852.528s` on the pre-#64 base. Migrated schemas across that run: **45**,
against 900-odd before.

Per-test cost is now a **clone** (~0.27s) rather than a `migrate_schemas`
(~1.65s), except in the three `TransactionTestCase` modules that still migrate
by design — 21 tests.

## CI wall-clock when several PRs are in flight (measured 2026-09-13)

The `14m55s` above is one run on an otherwise idle queue. **It is not the number
to plan a merge around.** From `gh run list --json createdAt,updatedAt`, which
spans queue *and* run — which is what "when can I merge" actually asks:

| run | concurrent with | created → updated |
|---|---|---|
| `f867234` (main) | nothing | **17m48s** |
| `c0129c2` | one other | **24m10s** |
| `220a81e` | one other | **23m52s** |

So: **~18 min alone, ~24 min with one other in flight**, and slower again with
four. Pushing a fix to one branch resets *that* branch's clock — a doc typo fix
on the PR that merges first can put it 20 minutes behind the three it precedes.

**Consequence for merge ordering:** decide the order *before* pushing the last
fixes, or the branch you want to merge first ends up the youngest run. Check
`createdAt` on the run, not just `status`, to know how long is actually left.

Do not poll — see [[luffy-never-idle-on-ci]]. Arm a `Monitor` that emits one
line per SHA as its `test` check-run reaches a terminal conclusion and exits
when all are terminal, then do other work. Poll the API at 60s, and emit on
**failure as well as success** — a monitor that greps only for `success` is
silent through a red run and silence reads as "still building".

## Running two test processes at once does not work

They collide on `test_luffy_db`. Serialise them in one script. Between runs,
kill stale backends or the next `DROP DATABASE` loses the race (issue #61):

```
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE datname LIKE 'test_%' AND pid <> pg_backend_pid();
```

## Watching a long run

Match on the script's own `^EXIT=` line, **not** on `ERROR` — tests deliberately
provoke Celery errors and log them, and a monitor grepping `ERROR` fires on a
passing run. Learned the hard way 2026-09-03.

`silence is normal`: a run prints nothing for minutes while it migrates.

See [[luffy-open-work-state]], [[luffy-never-idle-on-ci]].

**Locally there are only 2 CPUs**, so `--parallel` buys little — the full
`results` app is ~24 minutes either way (545 tests, `Ran 545 tests in 1454.876s`
at the last full measurement). `test_pdf` + `test_revision` + `test_card_api`
together are ~7.5 minutes (108 tests), which is the useful fast gate while
working on the card/PDF surface.

## `--parallel` hides *which* test failed (measured 2026-09-14)

A real failure under `--parallel` can surface as
`TypeError: cannot pickle 'traceback' object` from Django's
`runner.check_picklable`, with **no `OK`/`FAILED` line and no test name**.
`run-tests.sh` catches the silence correctly (`EXIT=1`, `RESULT=<none>`), but
the failing test is only findable by reading the `RemoteTraceback` block in the
log — search backwards from `cannot pickle` for the `AssertionError`.

Locally there are 2 CPUs, so `--parallel` buys nothing anyway. **Re-run the
suspect app serially** (pass app names as args — `run-tests.sh` only adds
`--parallel` when given none) to get a readable failure.

## A crashed run leaves `test_luffy_db*` and the next run hangs

Not the #61 race — a *different* symptom with the same cause. The next run
prompts `Type 'yes' if you would like to try deleting the test database…` and
**blocks forever** with no output, which looks exactly like a slow migration.

Fix: pass `--noinput`, which lets Django drop and recreate them itself. It also
cleans up the numbered `--parallel` clones (`test_luffy_db_1`, `_2`). Prefer it
over hand-rolled `DROP DATABASE`.

## `tests/test_refusals_are_constraints.py` is a full-suite-only gate

It walks **every** migration's SQL literals and requires the exact contiguous
string `USING ERRCODE = 'restrict_violation'` in each `RAISE` statement. So
wrapping after `USING` — legal plpgsql, and it reads better next to a
`MESSAGE`/`DETAIL`/`HINT` raise — fails it.

It lives in `tests/`, so **an app-scope run cannot see it**. Any change adding
a `RAISE EXCEPTION` to a migration needs `run-tests.sh <app> tests` at minimum.
Do not loosen the matcher to accept a line break.
