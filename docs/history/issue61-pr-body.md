Closes #61.

## What was actually left

Most of #61 is already in `main`. PR #63 landed the loud-failure guard and the
pipefail work — `scripts/run-tests.sh` reads `${PIPESTATUS[0]}`, refuses a run
that exits 0 without printing `OK` or `FAILED`, and the workflow names `bash` as
its shell so a future piped step gets `-eo pipefail` rather than silently
reporting the wrong half of the pipe.

The issue's own comment retitled it after Django was read properly:
`_create_test_db` calls `sys.exit(2)` on this and names the cause. The original
"exits 0 and silent" report was a hand-rolled waiter discarding the status, not
Django. **So this is a convenience, not a correctness fix**, and it seems worth
saying so rather than dressing it up.

What is left is the race itself. A run started shortly after one finished finds
`test_luffy_db` still there and still occupied — the previous process has
returned, its Postgres backend has not, and `DROP DATABASE` needs zero other
sessions. It costs a startup and a diagnosis, and it has cost that twice,
because the message sits four lines from the end of a long log and reads like a
configuration problem.

## The change

`TenantTemplateRunner.setup_databases()` clears those backends before asking for
the test database, on a connection to the real one — the connection doing the
terminating must not be among the connections terminated.

**What it will not touch.** The names are computed, never loosely matched: the
test database Django is about to ask for, and its `_1 … _N` worker clones.
`luffy_db` cannot match either, because every candidate carries Django's `test_`
prefix. `_` and `%` are `LIKE` wildcards and these names are full of the former,
so the name is escaped before the clone pattern is built from it.

**`--keepdb` skips it** — it drops nothing, so it has nothing to lose.

**It says what it did.** A terminated backend is reported at verbosity 1 and up.
Killing connections quietly would be the same class of fault this harness exists
to refuse.

## Verification

Five tests against three scratch databases, never the suite's own.

| Run | Result |
| --- | --- |
| Five tests, escaping in place | `Ran 5 tests in 8.666s`, `OK`, `EXIT=0` |
| **Control** — name escaping removed | `FAILED (failures=1)`, `EXIT=1`, `decoy='luffyXprobeX61_1'` |

And the whole path, against a real leftover — #61 as reported rather than as
unit-tested. A connection held open on an existing `test_luffy_db`, then a run:

| Run | Result |
| --- | --- |
| **Control** — clearing disabled | `Got an error recreating the test database: database "test_luffy_db" is being accessed by other users`, `EXIT=2`, `RESULT=<none — the runner printed no OK or FAILED line>` |
| Clearing enabled | `Terminated a leftover backend still attached to 'test_luffy_db' (issue #61).`, `Ran 6 tests in 1.275s`, `OK`, `EXIT=0` |

That control's `RESULT=<none>` is #63's guard doing its job on the way past: a
run that never started, refused rather than counted as green.

## Two drafts that proved nothing, and what they cost

Worth recording, because both looked like passing tests.

**The first decoy was carrying less than it claimed.** With only
`luffy_probe_61x`, removing the escaping from the *name* left all five tests
passing — the still-escaped suffix kept that name out on its own. The control is
what exposed it. `luffyXprobeX61_1` puts letters exactly where the name has
underscores, so it is matched only when those underscores have become wildcards,
and with it the control fails as it should.

**The first end-to-end control set up no database at all.** Its payload was a
`SimpleTestCase` module, and Django creates no database for tests that declare
they need none — so there was no drop to lose and both arms passed. The payload
is a `TestCase` module for that reason.

## One comment that would have gone stale

`scripts/run-tests.sh`'s header said the script deliberately does not terminate
for you, and pointed at #61 for the decision. The decision is now made, one
level down. The header says where it happens, and why the diagnosis it prints is
kept anyway: the runner only clears what it can name, so a backend held by
something outside this project still lands there.
