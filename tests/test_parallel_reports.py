"""A failure in a parallel worker reaches the report as itself, and only itself.

Issue #193. CI runs the suite with `--parallel auto`, and a worker sends each
result to the parent by pickling it. A traceback cannot be pickled unless
`tblib` is installed, and without it Django's `RemoteTestResult.check_picklable()`
prints "tracebacks cannot be pickled" and **re-raises inside the test run**.
That skips the failing test's cleanups and its class's cleanups, so whatever
they would have undone stays in force for every later test in that worker: an
`override_settings` (the fake message provider), a SimpleTestCase's database
guard. Those later tests then fail too, the parent's pool raises, and the run
ends with no OK or FAILED line.

That is what #193 looked like: `test_pdf` really failed on two commits, and
the report named a messaging test, an invitation test and a gradebook test
instead, which read as flaky. None of them was.
"""

import pickle
import sys
import unittest

from django.test import SimpleTestCase
from django.test import runner as django_runner


class AFailureCrossesToTheParentTests(SimpleTestCase):
    def test_tracebacks_can_be_pickled_here(self):
        self.assertIsNotNone(
            django_runner.tblib,
            "tblib is not installed: a failure in a parallel worker will abort "
            "the run and take other tests with it (issue #193)",
        )

    def test_a_failing_result_is_recorded_not_raised(self):
        """CONTROL: uninstall tblib and `addFailure` raises TypeError here."""

        # Defined here rather than at module level, so discovery never runs it.
        class Probe(unittest.TestCase):
            def test_fails(self):
                self.assertEqual(1, 2)

        probe = Probe("test_fails")
        try:
            probe.test_fails()
        except AssertionError:
            err = sys.exc_info()

        result = django_runner.RemoteTestResult()
        result.addFailure(probe, err)

        # What the worker sends to the parent, and the parent reads back.
        events = pickle.loads(pickle.dumps(result.events))
        self.assertEqual(events[-1][0], "addFailure")
        self.assertIn("1 != 2", str(events[-1][2][1]))
