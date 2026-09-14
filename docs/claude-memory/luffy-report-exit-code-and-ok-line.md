---
name: luffy-report-exit-code-and-ok-line
description: Never report a test suite green on one signal — capture and state BOTH the process exit code and the presence of the OK line
metadata:
  type: feedback
---

Set 2026-09-01, after I reported a run as inconclusive that had in fact **failed
loudly**, and told the user Django exits 0 on it. It does not.

**When reporting a suite as green, report the exit code AND that the `OK` line
was present. Not one or the other.** The user's words. Either alone is
insufficient:

- **the exit code without the `OK` line** misses a run that never started;
- **the `OK` line without the exit code** is what went wrong here.

## What actually happened, because the diagnosis matters

I ran suites as `(nohup python manage.py test … > log 2>&1 &)` and polled the log
for `^OK$|^FAILED`. **That subshell throws the exit status away.** The
"[exited with code 0]" I kept reading was the *polling loop's* exit code, not the
test run's.

A run whose test-database setup failed printed neither `OK` nor `FAILED`, so the
waiter spun for ever and I read the silence as "still running", then later as
"unverified". Django had already exited **2**, loudly, with the reason — verified
in `django/db/backends/base/creation.py`, `_create_test_db`, which ends that path
`self.log("Got an error recreating the test database: %s" % e); sys.exit(2)`.

So: **no repo-side "loud failure" is needed or wanted.** A `TEST_RUNNER` override
re-implementing `sys.exit(2)` would be a guard that guards nothing, which is the
shape this codebase spends its review effort removing. I proposed one and was
wrong; the user had asked for it on my own bad diagnosis. Correcting the premise
was the right move and they accepted it.

## The invocation to use instead

Wrap so the code lands in the log, and sweep stale backends between consecutive
runs (issue #61 — the previous run's Postgres backend outlives its process and
`DROP DATABASE` needs zero other sessions):

```bash
python manage.py test <targets> --noinput > run.log 2>&1
echo "EXIT=$?" >> run.log
```

Then wait on the log and report all three of `Ran N tests`, `OK`/`FAILED`, and
`EXIT=`. A working two-run script is at
`~/luffy-handover/run-tests-with-exit-code.sh`.

**How to apply:** never write "green" or "OK" about a suite without having both
numbers in front of you, and print both to the user. See
[[luffy-test-suite-runtime]] for the waiter-loop traps and
[[luffy-open-work-state]] for #61.
