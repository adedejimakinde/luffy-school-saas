#!/usr/bin/env python
"""Deal the suite into N shards of roughly equal wall-clock, one per CI job.

CI runs the suite as four jobs side by side (`.github/workflows/tests.yml`).
Each job asks this script which test modules are its own, and the answer has to
be the same in all four without them talking to each other, so it is computed
the same way in each: Django's own discovery, the same weights, the same greedy
deal.

**A module nobody runs is the failure that matters here**, because it would look
exactly like a module that passed. So the deal is checked before anything runs:
the shards must be disjoint, must cover every discovered module, and the tests
they load must add up to the tests the whole suite loads. And the count for this
shard goes to `scripts/run-tests.sh` as `EXPECT_TESTS`, which refuses a run that
did not execute exactly that many.

**Weights** are seconds of worker time per module, from `scripts/test-weights.json`.
A module missing from the file (a new one) is estimated from its test count at
the suite's average cost per test. Stale weights only unbalance the jobs; they
cannot drop a test. Rebuild the file from a CI run's logs with `weights`.

Usage:

    python scripts/shard_tests.py K N               # shard K's labels, one per line
    python scripts/shard_tests.py K N --github-env  # SHARD_LABELS=... EXPECT_TESTS=...
    python scripts/shard_tests.py weights LOG...    # refresh test-weights.json
"""

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = REPO_ROOT / "scripts" / "test-weights.json"


def partition(weights, n):
    """Longest job first, each to the lightest shard so far. Deterministic.

    Ties break by name, so every job computes the same deal from the same input,
    and between equally light shards by how few modules each has, so a run of
    zero weights still reaches every shard.
    """
    if n < 1 or n > len(weights):
        raise ValueError(f"cannot deal {len(weights)} modules into {n} shards")
    shards = [[0.0, i, []] for i in range(n)]
    for module in sorted(weights, key=lambda m: (-weights[m], m)):
        lightest = min(shards, key=lambda s: (s[0], len(s[2]), s[1]))
        lightest[0] += weights[module]
        lightest[2].append(module)
    return [sorted(s[2]) for s in shards]


def estimate(counts, known):
    """Seconds per module: the file's figure, or the count at the average rate."""
    measured = {m: known[m] for m in counts if m in known}
    measured_tests = sum(counts[m] for m in measured)
    rate = sum(measured.values()) / measured_tests if measured_tests else 1.0
    return {m: measured.get(m, counts[m] * rate) for m in counts}


def _setup_django():
    sys.path.insert(0, str(REPO_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    import django

    django.setup()


def _count_by_module(runner, labels):
    from django.test.utils import iter_test_cases

    counts = {}
    for test in iter_test_cases(runner.build_suite(labels)):
        module = type(test).__module__
        counts[module] = counts.get(module, 0) + 1
    return counts


def deal(n, weights_file=WEIGHTS):
    """Every shard's labels and test count, checked. Raises SystemExit if not whole."""
    from django.conf import settings
    from django.test.utils import get_runner

    runner = get_runner(settings)(verbosity=0, parallel=0)
    counts = _count_by_module(runner, [])
    known = json.loads(Path(weights_file).read_text()) if Path(weights_file).exists() else {}
    shards = partition(estimate(counts, known), n)

    dealt = [m for shard in shards for m in shard]
    if len(dealt) != len(set(dealt)) or set(dealt) != set(counts):
        raise SystemExit("shard_tests: the shards do not cover the suite exactly once")
    if any(not shard for shard in shards):
        raise SystemExit("shard_tests: an empty shard would run the whole suite")

    loaded = [sum(_count_by_module(runner, shard).values()) for shard in shards]
    if sum(loaded) != sum(counts.values()):
        raise SystemExit(
            f"shard_tests: the shards load {sum(loaded)} tests and the suite "
            f"loads {sum(counts.values())}"
        )
    return list(zip(shards, loaded))


def refresh_weights(logs, weights_file=WEIGHTS):
    """Replace each module's seconds with what the logs measured.

    Reads the `class-seconds <module.Class> <secs>` lines the test runner prints
    from its workers under `LUFFY_CLASS_SECONDS` (`schools/tests/runner.py`).
    A module the logs did not measure keeps its old figure.
    """
    line = re.compile(r"class-seconds (\S+)\.[^.\s]+ ([0-9.]+)")
    measured = {}
    for log in logs:
        for match in line.finditer(Path(log).read_text(errors="replace")):
            module, seconds = match.group(1), float(match.group(2))
            measured[module] = measured.get(module, 0.0) + seconds
    if not measured:
        raise SystemExit("shard_tests: no class-seconds lines in those logs")
    path = Path(weights_file)
    weights = json.loads(path.read_text()) if path.exists() else {}
    weights.update({m: round(s, 1) for m, s in measured.items()})
    path.write_text(json.dumps(dict(sorted(weights.items())), indent=1) + "\n")
    return measured


def main(argv):
    if argv[:1] == ["weights"] and len(argv) > 1:
        measured = refresh_weights(argv[1:])
        print(f"{len(measured)} modules measured, {sum(measured.values()):.0f}s")
        return 0
    if len(argv) not in (2, 3) or not all(a.isdigit() for a in argv[:2]):
        print(__doc__, file=sys.stderr)
        return 2
    k, n = int(argv[0]), int(argv[1])
    if not 1 <= k <= n:
        raise SystemExit(f"shard_tests: shard {k} of {n} does not exist")

    _setup_django()
    labels, expected = deal(n)[k - 1]
    print(f"shard {k}/{n}: {len(labels)} modules, {expected} tests", file=sys.stderr)
    if argv[2:] == ["--github-env"]:
        print(f"SHARD_LABELS={' '.join(labels)}")
        print(f"EXPECT_TESTS={expected}")
    elif argv[2:]:
        print(__doc__, file=sys.stderr)
        return 2
    else:
        print("\n".join(labels))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
