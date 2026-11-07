#!/usr/bin/env bash
# Run the screens suite (`npm run screens`), retrying a failed test once.
#
# A test that fails and then passes on its own retry is reported as
# "FLAKY: <test name>" in the log and the job summary, and does not fail the
# job. A test that fails twice fails it. A failure outside any test (a setup
# hook, a crash) has no test to retry and fails the job straight away.
set -uo pipefail

dir="$(cd "$(dirname "$0")" && pwd)"
tmp="${RUNNER_TEMP:-$(mktemp -d)}"
first="$tmp/screens-1.xml"
second="$tmp/screens-2.xml"
files=(tests/ui/*.test.js)
reporters=(--test-reporter=spec --test-reporter-destination=stdout
           --test-reporter=junit)
# --test-force-exit: the retry names the failed tests, and a file none of them
# is in has no test to run, but its top-level `before` still launches Chromium
# and its `after` never runs, so the open browser kept `node` alive for ever:
# the retry waited on a process that never exited. Every run ends when its
# tests have. A single test that never settles is tests/ui/timed.js's to fail.
runner=(node --test --test-force-exit)

if "${runner[@]}" "${reporters[@]}" --test-reporter-destination="$first" "${files[@]}"; then
  exit 0
fi

mapfile -t failed < <(node "$dir/failed-tests.mjs" "$first")
failed=("${failed[@]//$'\r'/}")
if [ "${#failed[@]}" -eq 0 ] || [ -z "${failed[0]}" ]; then
  echo "::error::The screens suite failed outside any single test; nothing to retry."
  exit 1
fi

echo "Retrying ${#failed[@]} failed test(s) once:"
patterns=()
for name in "${failed[@]}"; do
  echo "  - $name"
  # Escape regex metacharacters: --test-name-pattern takes a regular expression.
  patterns+=("--test-name-pattern=$(printf '%s' "$name" | sed -e 's/[][\\.^$*+?(){}|\/]/\\&/g')")
done

if "${runner[@]}" "${reporters[@]}" --test-reporter-destination="$second" "${patterns[@]}" "${files[@]}"; then
  rc=0
else
  rc=1
fi

mapfile -t still < <(node "$dir/failed-tests.mjs" "$second")
for name in "${failed[@]}"; do
  if ! printf '%s\n' "${still[@]}" | grep -qxF -- "$name"; then
    echo "FLAKY: $name"
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
      echo "FLAKY: $name" >> "$GITHUB_STEP_SUMMARY"
    fi
  fi
done

if [ "$rc" -ne 0 ]; then
  echo "::error::A screens test failed twice."
  exit 1
fi
