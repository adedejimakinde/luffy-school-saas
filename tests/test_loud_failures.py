"""A run that did not pass must not be able to look like one that did.

Issue #61. `scripts/run-tests.sh` exists because three different silences have
been read as success in this project, and the script's own header argues each.
These tests are what stop the guards being removed by someone who cannot
reproduce the bug they were written for — which is the ordinary fate of a guard
whose failure mode is that nothing happens.

The runner is stubbed with a `python` earlier on `PATH` than the real one, so
each case is a chosen exit code and a chosen output. That is the only way to
produce "exited 0 and never said OK" on demand: it is not a state the real
suite can be asked for, which is exactly why it went unnoticed.

**The control is case 1 against case 3.** Both stubs exit 0. They differ by one
line of output — `OK` — and nothing else. If the script passed both, the guard
would be decoration; if it failed both, it would be broken in a way that looks
like working. It has to separate them, and that is the assertion.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run-tests.sh"


@unittest.skipUnless(SCRIPT.exists(), f"{SCRIPT} is missing")
class ARunThatDidNotPassCannotLookLikeOneTests(SimpleTestCase):
    """Four ways a run ends, and what the script must report for each."""

    def run_with_stub(self, stub_body):
        """Run the script with `python` stubbed to `stub_body`. Returns the result.

        `capture_output` rather than a pipe in the shell, deliberately: piping
        in the harness that tests a pipefail bug would be its own joke, and
        `subprocess` reports the real return code without any of that.
        """
        shim_dir = tempfile.mkdtemp()
        shim = Path(shim_dir) / "python"
        shim.write_text("#!/bin/sh\n" + stub_body + "\n")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

        env = dict(os.environ)
        env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
        env["RUN_TESTS_LOG"] = str(Path(shim_dir) / "run.log")

        return subprocess.run(
            [str(SCRIPT)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_a_passing_run_passes(self):
        """The control for the case below. Same exit code, one more line."""
        result = self.run_with_stub('echo "Ran 5 tests in 1.0s"; echo "OK"; exit 0')

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("EXIT=0", result.stdout)
        self.assertIn("RESULT=OK", result.stdout)

    def test_exit_zero_with_no_result_line_is_a_failure(self):
        """**The guard.** Django prints exactly one `OK` or `FAILED` line.

        A zero exit without one means the runner returned success without
        completing a suite, and there is no reading of that which is good news.
        Compare with the test above: the stub differs only in that it does not
        print `OK`, and the script must turn that difference into a failure.
        """
        result = self.run_with_stub(
            'echo "Found 5 test(s)."; '
            "echo \"Creating test database for alias 'default'...\"; "
            "exit 0"
        )

        self.assertEqual(
            result.returncode,
            1,
            "A run that exited 0 without saying OK was reported as a pass.",
        )
        self.assertIn("FAILED LOUDLY", result.stderr)
        self.assertIn("EXIT=0", result.stdout)
        self.assertIn("<none", result.stdout)

    def test_a_failing_run_keeps_its_exit_code_through_the_pipe(self):
        """The pipefail half, and the incident that prompted it.

        The script pipes the run through `tee` to keep output on screen and on
        disk. Without `${PIPESTATUS[0]}` this would report tee's status — 0 —
        and a failing suite would be a passing script. That is precisely the
        shape of the two incidents in the header: a failed run read as still
        running, and a failed `git checkout` followed by a `&&` that ran anyway.
        """
        result = self.run_with_stub(
            'echo "Ran 5 tests in 1.0s"; echo "FAILED (failures=1)"; exit 1'
        )

        self.assertEqual(
            result.returncode, 1, "tee's exit code was reported instead of the run's."
        )
        self.assertIn("EXIT=1", result.stdout)
        self.assertIn("FAILED (failures=1)", result.stdout)

    def test_an_unusual_exit_code_is_passed_through_unchanged(self):
        """Not flattened to 1. #61 exits 2, and 2 is what a caller should see.

        Also the case that names the issue: the message is four lines from the
        end of a long log and reads like a configuration problem, so the script
        says which bug it is and how to recover rather than leaving it to be
        rediscovered a third time.
        """
        result = self.run_with_stub(
            'echo "Creating test database for alias \'default\'..."; '
            'echo "Got an error recreating the test database: database '
            '\\"test_luffy_db\\" is being accessed by other users"; '
            "exit 2"
        )

        self.assertEqual(result.returncode, 2, "A non-1 exit code was rewritten.")
        self.assertIn("issue #61", result.stderr)
        self.assertIn("pg_terminate_backend", result.stderr)
