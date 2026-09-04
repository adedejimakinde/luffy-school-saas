#!/usr/bin/env bash
#
# Run the suite so that a run which did not pass cannot look like one that did.
#
# Issue #61. The cost of that bug was never the lost minutes — it was that a run
# which never executed a test was indistinguishable from one that passed. This
# script exists to make the three ways that happens loud, and it is the same
# argument `docs/background.md` already makes about skips: a broker nothing can
# reach would have gone green, because `manage.py test` does not fail on skips,
# and silence handed back as success is the failure with no other symptom.
#
# ## 1. A pipe throws the exit code away
#
# `python manage.py test ... 2>&1 | tail -25` reports **tail's** exit code,
# which is 0 whatever the tests did. That has now cost this project twice: a
# test run that had failed loudly was read as still running, and a `git checkout`
# that failed was followed by a `&&` that ran anyway, rebasing the wrong branch.
# Neither was a subtle bug. Both were invisible for exactly the same reason.
#
# `set -o pipefail` is the fix for the shell in general, and it is set below.
# It is not sufficient here, though, because this script deliberately pipes the
# run through `tee` to keep the output on screen *and* on disk: pipefail makes
# `$?` the rightmost non-zero status, and what we want is specifically the
# status of `manage.py`. `${PIPESTATUS[0]}` is the only thing that answers that,
# so the run is wrapped in `set +e` and the real code read back by index.
#
# ## 2. A run exits 0 without ever saying `OK`
#
# Django prints exactly one result line — `OK`, `OK (skipped=…)` or
# `FAILED (…)`. A zero exit with no such line means the runner returned success
# without completing a suite, and there is no reading of that which is good
# news. This script refuses it: **exit 0 and no result line is a failure here**,
# reported as one.
#
# ## 3. #61 itself, which is what taught us the other two
#
# The test database survives a run by a few hundred milliseconds — the process
# is gone, its Postgres backend is not — so the next run's `DROP DATABASE`
# loses a race. Django does exit non-zero for this (`_create_test_db` calls
# `sys.exit(2)`; an earlier reading of this as a silent exit-0 was wrong, and
# was itself a pipe eating the code). But the message is four lines up from the
# end and reads like a configuration problem, so this script names it and prints
# the recovery instead of leaving it to be rediscovered.
#
# This script does not terminate the stale backend itself, and still should not:
# that is a real change to how the suite behaves, and it belongs to the runner
# rather than to a wrapper whose job is to report accurately. It now happens
# one level down — `schools/tests/runner.py` clears those backends before
# asking for the test database — so in the ordinary case the diagnosis below
# no longer gets a chance to fire. It is kept because the runner only clears
# what it can name: a backend held by something outside this project, or on a
# database Django is not about to create, still lands here.
#
# ## Usage
#
#   scripts/run-tests.sh                       # everything, as CI runs it
#   scripts/run-tests.sh results.tests.test_pdf
#   scripts/run-tests.sh --parallel 4 accounts
#
# Arguments are passed through to `manage.py test` untouched. With none, it runs
# what CI runs, so "green locally" and "green in CI" mean the same thing.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

log="${RUN_TESTS_LOG:-$(mktemp -t luffy-tests-XXXXXX.log)}"

if [ "$#" -eq 0 ]; then
  # The same invocation as .github/workflows/tests.yml's "Run tests" step.
  set -- --verbosity 2 --parallel
fi

echo "==> python manage.py test $*"
echo

# `set +e` so a failing run reaches the diagnosis below instead of exiting here,
# and `${PIPESTATUS[0]}` so the code read is manage.py's rather than tee's.
set +e
python manage.py test "$@" 2>&1 | tee "$log"
status="${PIPESTATUS[0]}"
set -e

# Django's one result line. `|| true` because grep exits 1 on no match, which is
# the case this whole script is about and must not end it early.
result_line="$(grep -E '^(OK|FAILED)' "$log" | tail -1 || true)"

echo
echo "-----------------------------------------------------------------------"
# Both, every time. Either alone has been misread here before.
echo "EXIT=${status}"
echo "RESULT=${result_line:-<none — the runner printed no OK or FAILED line>}"
echo "LOG=${log}"
echo "-----------------------------------------------------------------------"

if grep -q "error recreating the test database" "$log" 2>/dev/null; then
  echo
  echo "This is issue #61: the previous run's Postgres backend outlived its"
  echo "process, so DROP DATABASE lost a race it does not retry. Recover with:"
  echo
  echo "  SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
  echo "  WHERE datname LIKE 'test_%' AND pid <> pg_backend_pid();"
  echo
  echo "Then run this again. Nothing was tested, so nothing about the code is"
  echo "known either way."
fi >&2

if [ "${status}" -ne 0 ]; then
  exit "${status}"
fi

if [ -z "${result_line}" ]; then
  echo
  echo "FAILED LOUDLY: the runner exited 0 without printing OK or FAILED." >&2
  echo "A suite that reports success without completing has not told you"      >&2
  echo "anything about the code. Treating this as a pass is the mistake this"  >&2
  echo "script exists to prevent — see issue #61 and the header above."        >&2
  exit 1
fi

echo "==> ${result_line}"
