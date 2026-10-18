"""The deploy button moves the server's checkout to the SHA being released
before `deploy.sh` runs (`.github/workflows/deploy.yml`).

`deploy.sh` pulls the images for its SHA argument, but it reads `compose.yml` —
and its own text — from the checkout at `/opt/classnode`. A checkout left on an
older commit deploys the new images with the old orchestration, and nothing says
so: the deploy goes green.

Two kinds of test, because each fails to see what the other sees:

* **Structure.** The checkout step exists, comes before the step that runs
  `deploy.sh`, fetches and then checks out the SHA itself (not a branch, not a
  pull), and checks the result. These fail the day someone deletes the step or
  "simplifies" it to `git pull`.
* **Behaviour.** The step's script is lifted out of the workflow and run, as the
  server would run it, against a real repository with a real origin. A string
  match cannot tell a checkout that works from one that merely looks right.

And a rollback is never silent (2026-10-18: two green runs deployed a week-old
SHA pasted in place of the new one, and the run list named the new one). The run
is named after its SHA, the checkout refuses a SHA older than `deployed-sha`
unless `rollback` is ticked, and the last step reads `deployed-sha` back into
the run's summary and fails when it is not the SHA asked for.
"""

import os
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)
WORKFLOW = BASE_DIR / ".github" / "workflows" / "deploy.yml"
SERVER_CHECKOUT = "/opt/classnode"

STEP_CHECKOUT = "Check out the SHA on the server"
STEP_DEPLOY = "Deploy over SSH"
STEP_RESTORE = "Put the checkout back on what is running"
STEP_READ_BACK = "Read back what is running"


def steps():
    """`{name: text}` for the workflow's steps, in file order."""
    text = WORKFLOW.read_text()
    parts = re.split(r"(?m)^      - (?:uses: .*|name: (.+))$", text)
    found = {}
    # re.split with one group yields [pre, name_or_None, body, name_or_None, body, ...]
    for name, body in zip(parts[1::2], parts[2::2]):
        if name:
            found[name.strip()] = body
    return found


def remote_script(step_name):
    """The bash the step sends over SSH, as it will read on the server."""
    body = steps()[step_name]
    match = re.search(r"<<'REMOTE'\n(.*?)\n\s*REMOTE\b", body, re.S)
    if not match:
        raise AssertionError(f"step {step_name!r} sends no REMOTE script")
    return textwrap.dedent(match.group(1)) + "\n"


def run_block(step_name):
    """The bash a step runs on the runner: its `run: |` block, dedented."""
    match = re.search(r"\n        run: \|\n(.*)", steps()[step_name], re.S)
    if not match:
        raise AssertionError(f"step {step_name!r} has no run block")
    return textwrap.dedent(match.group(1)).rstrip() + "\n"


class TheWorkflowChecksOutTheShaTests(SimpleTestCase):
    def test_there_is_a_checkout_step_before_the_deploy_step(self):
        """CONTROL 1: deleting the checkout step makes this red.
        CONTROL 2: moving it below the deploy step makes this red."""
        order = list(steps())

        self.assertIn(STEP_CHECKOUT, order)
        self.assertIn(STEP_DEPLOY, order)
        self.assertLess(order.index(STEP_CHECKOUT), order.index(STEP_DEPLOY))

    def test_deploy_sh_runs_only_after_the_checkout(self):
        """No earlier step may run `deploy.sh`, whatever it is called."""
        seen_checkout = False
        for name, body in steps().items():
            if name == STEP_CHECKOUT:
                seen_checkout = True
            if "deploy/deploy.sh" in body:
                with self.subTest(step=name):
                    self.assertTrue(seen_checkout, f"{name!r} runs deploy.sh before the checkout")

    def test_the_deploy_step_is_given_the_same_sha(self):
        self.assertRegex(steps()[STEP_DEPLOY], r"deploy/deploy\.sh \$SHA")
        self.assertIn('"$SHA"', steps()[STEP_CHECKOUT])

    def test_it_fetches_and_then_checks_out_the_sha_itself(self):
        """CONTROL 3: `git pull` in place of the two lines makes this red."""
        script = remote_script(STEP_CHECKOUT)

        self.assertIn("git fetch", script)
        self.assertRegex(script, r'git checkout [^\n]*"\$sha"')
        self.assertLess(script.index("git fetch"), script.index("git checkout"))

    def test_it_never_follows_a_branch_or_discards_edits(self):
        """`git pull` and `checkout main` land on whatever main is now, not on
        the commit CI passed; `reset --hard` and `checkout -f` would delete what
        someone changed on the server instead of refusing to deploy over it."""
        script = remote_script(STEP_CHECKOUT)
        for forbidden in ("git pull", "checkout main", "checkout origin", "reset --hard", "checkout -f", "--force"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, script)

    def test_it_asks_git_where_it_ended_up(self):
        """CONTROL 4: deleting the `rev-parse` comparison makes this red."""
        script = remote_script(STEP_CHECKOUT)

        self.assertIn("git rev-parse HEAD", script)
        self.assertIn("exit 1", script)

    def test_it_stops_on_the_first_failure(self):
        self.assertIn("set -euo pipefail", remote_script(STEP_CHECKOUT))

    def test_it_runs_in_the_directory_deploy_sh_runs_from(self):
        self.assertIn(f"cd {SERVER_CHECKOUT}", remote_script(STEP_CHECKOUT))
        self.assertIn(f"{SERVER_CHECKOUT}/deploy/deploy.sh", steps()[STEP_DEPLOY])

    def test_a_failed_deploy_puts_the_checkout_back_without_hiding_the_failure(self):
        body = steps()[STEP_RESTORE]

        self.assertIn("failure()", body)
        self.assertIn("continue-on-error: true", body)
        self.assertIn("deploy/deployed-sha", remote_script(STEP_RESTORE))
        # Only when the checkout step ran at all: before it, there is nothing to put back.
        self.assertIn("steps.checkout.outcome", body)
        self.assertIn("id: checkout", steps()[STEP_CHECKOUT])


class ARollbackIsNeverSilentTests(SimpleTestCase):
    def test_the_run_is_named_after_the_sha_it_was_given(self):
        """The run list showed main's head beside two runs that deployed
        something else: GitHub names a dispatched run after its branch."""
        (run_name,) = re.findall(r"(?m)^run-name: (.+)$", WORKFLOW.read_text())
        self.assertIn("${{ inputs.sha }}", run_name)
        self.assertIn("inputs.rollback", run_name)

    def test_rollback_is_a_box_left_unticked(self):
        text = WORKFLOW.read_text()
        (block,) = re.findall(r"(?m)^      rollback:\n((?:        .*\n)+)", text)
        self.assertIn("type: boolean", block)
        self.assertIn("default: false", block)
        self.assertIn("ROLLBACK: ${{ inputs.rollback }}", text)
        self.assertIn('bash -s -- "$SHA" "$ROLLBACK"', steps()[STEP_CHECKOUT])

    def test_the_check_comes_before_anything_moves(self):
        """CONTROL 7: the comparison moved below `git checkout` makes this red."""
        script = remote_script(STEP_CHECKOUT)
        self.assertIn("deploy/deployed-sha", script)
        self.assertLess(script.index('git merge-base --is-ancestor "$running" "$sha"'),
                        script.index("git checkout"))

    def test_the_read_back_comes_after_the_deploy_and_before_the_put_back(self):
        order = list(steps())
        self.assertLess(order.index(STEP_DEPLOY), order.index(STEP_READ_BACK))
        self.assertLess(order.index(STEP_READ_BACK), order.index(STEP_RESTORE))
        body = steps()[STEP_READ_BACK]
        # Runs after a failed deploy too, to say what is serving instead; not
        # before there is a key to log in with.
        self.assertIn("!cancelled()", body)
        self.assertIn("steps.ssh.outcome == 'success'", body)
        self.assertIn("id: ssh", steps()["Set up SSH"])
        self.assertNotIn("continue-on-error", body)


class TheReadBackWorksTests(SimpleTestCase):
    """The step's own script, run with an `ssh` that runs the remote command
    here, against a `deployed-sha` in a temporary directory."""

    SHA = "b4396458769f0029a786c9a9c6c1635fa338a789"
    OLD = "d895d50ab55c2d1b43a12f996966fd08957a909c"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.server = root / "server"
        (self.server / "deploy").mkdir(parents=True)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        fake_ssh = bin_dir / "ssh"
        fake_ssh.write_text(
            "#!/usr/bin/env bash\n"
            f'exec bash -c "$(printf %s "${{@: -1}}" | sed "s#{SERVER_CHECKOUT}#{self.server}#g")"\n'
        )
        fake_ssh.chmod(0o755)
        self.summary = root / "summary.md"
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(root),
            "SHA": self.SHA,
            "ROLLBACK": "false",
            "DEPLOY_HOST": "server.example.test",
            "GITHUB_STEP_SUMMARY": str(self.summary),
        }

    def read_back(self, deployed):
        if deployed is not None:
            (self.server / "deploy" / "deployed-sha").write_text(deployed + "\n")
        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", run_block(STEP_READ_BACK)],
            env=self.env, capture_output=True, text=True,
        )

    def test_the_sha_asked_for_is_running_green_and_in_the_summary(self):
        result = self.read_back(self.SHA)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = self.summary.read_text()
        self.assertIn(f"| Asked for | `{self.SHA}` |", summary)
        self.assertIn(f"| Running now (`deploy/deployed-sha`) | `{self.SHA}` |", summary)
        self.assertIn("| Rollback ticked | false |", summary)

    def test_another_sha_running_is_red_and_named(self):
        """What happened on 2026-10-18, read back.

        CONTROL 8: the comparison's `exit 1` removed makes this red."""
        result = self.read_back(self.OLD)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"The server is running {self.OLD}, not {self.SHA}.", result.stdout)
        self.assertIn(f"| Running now (`deploy/deployed-sha`) | `{self.OLD}` |", self.summary.read_text())

    def test_nothing_recorded_is_red(self):
        result = self.read_back(None)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("| Running now (`deploy/deployed-sha`) | `nothing` |", self.summary.read_text())


class TheCheckoutStepWorksAgainstARealRepositoryTests(SimpleTestCase):
    """The step's own script, run as the server would run it, with
    `/opt/classnode` pointed at a clone in a temporary directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        self.work = root / "work"
        self.server = root / "server"
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
        }
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=root)
        self.git("clone", "-q", str(self.origin), str(self.work), cwd=root)
        self.v1 = self.commit("v1")
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.work)
        # The server's clone, as bootstrap.sh makes it: on the first release.
        self.git("clone", "-q", str(self.origin), str(self.server), cwd=root)
        self.v2 = self.commit("v2")
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.work)

    def git(self, *args, cwd):
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True
        ).stdout.strip()

    def commit(self, version):
        """A commit whose deploy.sh and compose.yml say which version they are."""
        deploy = self.work / "deploy"
        deploy.mkdir(exist_ok=True)
        (deploy / "compose.yml").write_text(f"{version}\n")
        # Identical in every commit: git carries a local edit to it across a
        # checkout without a word, which is what the status check is for.
        (deploy / "Caddyfile").write_text("same in every release\n")
        script = deploy / "deploy.sh"
        script.write_text(f'#!/usr/bin/env bash\necho "deploy.sh {version} for $1 with compose {version}"\n')
        script.chmod(0o755)
        self.git("add", "-A", cwd=self.work)
        self.git("commit", "-q", "-m", version, cwd=self.work)
        return self.git("rev-parse", "HEAD", cwd=self.work)

    def head(self):
        return self.git("rev-parse", "HEAD", cwd=self.server)

    def record(self, sha):
        """What `deploy.sh` writes after a deploy that went green."""
        (self.server / "deploy" / "deployed-sha").write_text(sha + "\n")

    def run_remote(self, step_name, *args):
        script = remote_script(step_name).replace(SERVER_CHECKOUT, str(self.server))
        return subprocess.run(
            ["bash", "-s", "--", *args], input=script, cwd=self.tmp.name,
            env=self.env, capture_output=True, text=True,
        )

    def deploy_sh(self, sha):
        """What the next workflow step runs: the checkout's own deploy.sh."""
        return subprocess.run(
            [str(self.server / "deploy" / "deploy.sh"), sha], capture_output=True, text=True
        ).stdout.strip()

    def test_the_server_moves_to_the_sha_and_the_new_deploy_sh_is_what_runs(self):
        """The failure this exists for: with the checkout still on v1, deploy.sh
        v1 runs with compose v1 though the images are v2's.

        CONTROL 5: the step's `git checkout` line removed makes this red.
        """
        self.assertEqual(self.head(), self.v1)

        result = self.run_remote(STEP_CHECKOUT, self.v2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v2)
        self.assertEqual(self.deploy_sh(self.v2), f"deploy.sh v2 for {self.v2} with compose v2")

    def test_it_is_the_exact_sha_even_when_main_has_moved_on(self):
        v3 = self.commit("v3")
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.work)

        result = self.run_remote(STEP_CHECKOUT, self.v2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v2)
        self.assertNotEqual(self.head(), v3)

    def test_it_can_go_back_to_an_older_release(self):
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)

        result = self.run_remote(STEP_CHECKOUT, self.v1)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v1)

    def test_an_older_sha_than_the_one_running_is_refused_and_moves_nothing(self):
        """The 2026-10-18 deploy: a week-old SHA pasted in place of the new one.

        CONTROL 9: the refusal's `exit 1` removed makes this red."""
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)
        self.record(self.v2)

        result = self.run_remote(STEP_CHECKOUT, self.v1)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{self.v2} is running and {self.v1} is not newer", result.stderr)
        self.assertIn("rollback", result.stderr)
        self.assertEqual(self.head(), self.v2)

    def test_unticked_is_the_same_as_leaving_it_out(self):
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)
        self.record(self.v2)

        result = self.run_remote(STEP_CHECKOUT, self.v1, "false")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.head(), self.v2)

    def test_ticked_it_goes_back_and_says_so(self):
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)
        self.record(self.v2)

        result = self.run_remote(STEP_CHECKOUT, self.v1, "true")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Rolling back from {self.v2} to {self.v1}", result.stdout)
        self.assertEqual(self.head(), self.v1)

    def test_a_newer_sha_and_the_same_sha_need_no_box(self):
        self.record(self.v1)
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)
        self.assertEqual(self.head(), self.v2)
        self.record(self.v2)

        result = self.run_remote(STEP_CHECKOUT, self.v2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Rolling back", result.stdout)
        self.assertEqual(self.head(), self.v2)

    def test_a_running_sha_git_cannot_place_needs_the_box(self):
        """A `deployed-sha` that is not in the history (a hand edit, a rewritten
        main) cannot be shown to be older or newer: ask, rather than guess."""
        self.record("f" * 40)

        refused = self.run_remote(STEP_CHECKOUT, self.v2)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.head(), self.v1)

        result = self.run_remote(STEP_CHECKOUT, self.v2, "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v2)

    def test_running_it_twice_changes_nothing(self):
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)
        result = self.run_remote(STEP_CHECKOUT, self.v2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v2)

    def test_a_sha_the_server_cannot_find_fails_and_moves_nothing(self):
        result = self.run_remote(STEP_CHECKOUT, "0" * 40)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.head(), self.v1)

    def test_a_sha_that_is_not_on_main_is_not_fetched(self):
        """The workflow already refuses a SHA that is not on main; the server
        side does not widen that by fetching other branches."""
        self.git("checkout", "-q", "-b", "side", cwd=self.work)
        side = self.commit("side")
        self.git("push", "-q", "origin", "side", cwd=self.work)

        result = self.run_remote(STEP_CHECKOUT, side)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.head(), self.v1)

    def test_local_edits_are_refused_not_overwritten(self):
        """A hand-edited Caddyfile that the release does not change would survive
        `git checkout` untouched, and be deployed as if it were the release's.

        CONTROL 6: deleting the `git status` check makes this red.
        """
        edited = self.server / "deploy" / "Caddyfile"
        edited.write_text("edited by hand\n")

        result = self.run_remote(STEP_CHECKOUT, self.v2)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stderr)
        self.assertEqual(self.head(), self.v1)
        self.assertEqual(edited.read_text(), "edited by hand\n")

    def test_a_local_edit_to_a_file_the_release_changes_is_refused_too(self):
        edited = self.server / "deploy" / "compose.yml"
        edited.write_text("edited by hand\n")

        result = self.run_remote(STEP_CHECKOUT, self.v2)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.head(), self.v1)
        self.assertEqual(edited.read_text(), "edited by hand\n")

    def test_the_file_deploy_sh_writes_does_not_count_as_an_edit(self):
        """`deployed-sha` is untracked, and is there on every server but the first run."""
        (self.server / "deploy" / "deployed-sha").write_text(self.v1 + "\n")

        result = self.run_remote(STEP_CHECKOUT, self.v2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v2)

    def test_a_failed_deploy_puts_the_checkout_back_on_what_is_running(self):
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)
        (self.server / "deploy" / "deployed-sha").write_text(self.v1 + "\n")

        result = self.run_remote(STEP_RESTORE)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v1)

    def test_with_nothing_deployed_yet_putting_back_changes_nothing(self):
        self.assertEqual(self.run_remote(STEP_CHECKOUT, self.v2).returncode, 0)

        result = self.run_remote(STEP_RESTORE)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(), self.v2)
