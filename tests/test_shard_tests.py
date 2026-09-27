"""`scripts/shard_tests.py`: the deal that splits the suite across CI's jobs.

The property that matters is that every test runs somewhere, exactly once. A
test dealt to no job would look exactly like a test that passed, so the real
deal is checked against the real discovery here, not only against made-up
weights.
"""

import importlib.util
import json
import random
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "shard_tests", REPO_ROOT / "scripts" / "shard_tests.py"
)
shard_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shard_tests)


class ThePartitionTests(SimpleTestCase):
    weights = {"a": 50.0, "b": 40.0, "c": 30.0, "d": 20.0, "e": 10.0, "f": 10.0}

    def test_every_module_is_dealt_once(self):
        shards = shard_tests.partition(self.weights, 3)

        dealt = [m for shard in shards for m in shard]
        self.assertCountEqual(dealt, self.weights)

    def test_the_heaviest_go_to_the_lightest_shard(self):
        shards = shard_tests.partition(self.weights, 3)

        self.assertEqual(
            sorted(sum(self.weights[m] for m in s) for s in shards), [50, 50, 60]
        )

    def test_the_same_weights_in_any_order_deal_the_same(self):
        """Four jobs compute this independently; they must agree."""
        expected = shard_tests.partition(self.weights, 3)
        items = list(self.weights.items())
        for seed in range(5):
            random.Random(seed).shuffle(items)
            self.assertEqual(shard_tests.partition(dict(items), 3), expected)

    def test_zero_weights_still_reach_every_shard(self):
        shards = shard_tests.partition({m: 0.0 for m in "abcdefgh"}, 4)

        self.assertEqual([len(s) for s in shards], [2, 2, 2, 2])

    def test_more_shards_than_modules_is_refused(self):
        with self.assertRaises(ValueError):
            shard_tests.partition({"a": 1.0}, 2)


class TheEstimateTests(SimpleTestCase):
    def test_a_module_missing_from_the_file_is_costed_by_its_count(self):
        weights = shard_tests.estimate(
            {"old_a": 2, "old_b": 4, "new": 3}, {"old_a": 10.0, "old_b": 20.0}
        )

        # 30 seconds over 6 measured tests is 5 a test; the new module has 3.
        self.assertEqual(weights, {"old_a": 10.0, "old_b": 20.0, "new": 15.0})

    def test_a_module_the_suite_no_longer_has_is_ignored(self):
        weights = shard_tests.estimate({"a": 1}, {"a": 4.0, "deleted": 99.0})

        self.assertEqual(weights, {"a": 4.0})


class TheRealDealTests(SimpleTestCase):
    """Against Django's own discovery of this repository, as CI runs it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.conf import settings
        from django.test.utils import get_runner

        runner = get_runner(settings)(verbosity=0, parallel=0)
        cls.discovered = shard_tests._count_by_module(runner, [])
        cls.dealt = shard_tests.deal(4)

    def test_four_shards_cover_every_discovered_module_once(self):
        modules = [m for labels, _ in self.dealt for m in labels]

        self.assertEqual(len(modules), len(set(modules)))
        self.assertEqual(set(modules), set(self.discovered))

    def test_the_shards_counts_add_up_to_the_suite(self):
        self.assertEqual(
            sum(count for _, count in self.dealt), sum(self.discovered.values())
        )

    def test_this_module_is_dealt(self):
        """The deal includes the test that checks the deal."""
        modules = {m for labels, _ in self.dealt for m in labels}

        self.assertIn(__name__, modules)

    def test_an_empty_shard_is_refused(self):
        """Handed no labels, `manage.py test` would run the whole suite."""
        real = shard_tests.partition

        def one_empty(weights, n):
            shards = real(weights, n)
            return [shards[0] + shards[-1], *shards[1:-1], []]

        with mock.patch.object(shard_tests, "partition", one_empty):
            with self.assertRaisesRegex(SystemExit, "empty shard"):
                shard_tests.deal(4)

    def test_a_module_dealt_twice_is_refused(self):
        real = shard_tests.partition

        def duplicated(weights, n):
            shards = real(weights, n)
            return [shards[0] + shards[1][:1], *shards[1:]]

        with mock.patch.object(shard_tests, "partition", duplicated):
            with self.assertRaisesRegex(SystemExit, "exactly once"):
                shard_tests.deal(4)


class RefreshingTheWeightsTests(SimpleTestCase):
    def test_class_seconds_lines_become_module_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "shard.log"
            log.write_text(
                "tests 1/4\tRun tests\t2026-09-27T01:00:00.1Z "
                "class-seconds results.tests.test_pdf.AClassTests 12.5\n"
                "test_x (a.b.C.test_x) ... ok\n"
                "class-seconds results.tests.test_pdf.AnotherTests 7.5\n"
                "test_y (a.b.C.test_y) ... class-seconds accounts.tests.test_x.T 3.0\n"
            )
            weights = Path(tmp) / "weights.json"
            weights.write_text(json.dumps({"kept.tests.test_old": 9.0}))

            shard_tests.refresh_weights([log], weights_file=weights)

            self.assertEqual(
                json.loads(weights.read_text()),
                {
                    "accounts.tests.test_x": 3.0,
                    "kept.tests.test_old": 9.0,
                    "results.tests.test_pdf": 20.0,
                },
            )

    def test_a_log_with_no_timings_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "shard.log"
            log.write_text("Ran 5 tests in 1.0s\nOK\n")

            with self.assertRaises(SystemExit):
                shard_tests.refresh_weights([log], weights_file=Path(tmp) / "w.json")
