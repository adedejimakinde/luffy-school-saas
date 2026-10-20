"""CI's Caddy image is reused when `deploy/caddy` has not changed (`scripts/caddy-image.sh`).

Run 525 on main failed in `docker build deploy/caddy` — `xcaddy build` could not
verify a module against sum.golang.org — in a commit that changed nothing under
`deploy/`, while the same Dockerfile had built on its pull request. The build is
a download of about two hundred Go modules, and it ran on every pull request and
every push. So the image published for the commit that last changed
`deploy/caddy` is pulled and renamed, and the build runs only when there is
nothing to pull.

**Behaviour, not strings.** The script is run against a real git repository with
a stand-in `docker` on the PATH that records what it was asked. A match on the
script's text cannot tell a script that reuses from one that merely mentions it.
And it is held to the one rule the fix has: **no retries**. A pull that fails
leads to one build; a build that fails fails the script, after one attempt.
"""

import os
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)
SCRIPT = BASE_DIR / "scripts" / "caddy-image.sh"
WORKFLOW = (BASE_DIR / ".github" / "workflows" / "tests.yml").read_text()

REPOSITORY = "ghcr.io/example/school/caddy"
NAME = "ghcr.io/example/school/caddy:candidate-abc"

#: Answers `docker pull <image>` from `PUBLISHED`, a space-separated list of image
#: names, and `docker build` from `BUILD_FAILS`; writes every call to `DOCKER_LOG`.
DOCKER = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    echo "$*" >> "$DOCKER_LOG"
    case "$1" in
      pull) case " $PUBLISHED " in *" $2 "*) exit 0;; *) echo "not found" >&2; exit 1;; esac ;;
      build) [ -z "${BUILD_FAILS:-}" ] ;;
      *) exit 0 ;;
    esac
    """
)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


class ScriptRun:
    """A repository, a recording `docker`, and the script run inside them."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        (self.repo / "deploy" / "caddy").mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        docker = self.bin / "docker"
        docker.write_text(DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        self.log = root / "docker.log"
        self.log.write_text("")
        git(self.repo, "init", "-q")

    def commit(self, message, **files):
        for name, text in files.items():
            path = self.repo / name.replace("__", "/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def run(self, published=(), build_fails=False):
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "DOCKER_LOG": str(self.log),
            "PUBLISHED": " ".join(f"{REPOSITORY}:{sha}" for sha in published),
            "BUILD_FAILS": "1" if build_fails else "",
        }
        done = subprocess.run(
            ["bash", str(SCRIPT), REPOSITORY, NAME],
            cwd=self.repo, env=env, capture_output=True, text=True,
        )
        self.calls = [line for line in self.log.read_text().splitlines() if line]
        return done

    def count(self, verb):
        return sum(1 for call in self.calls if call.split()[0] == verb)


class ReuseTests(SimpleTestCase):
    def setUp(self):
        self.ci = ScriptRun()
        self.addCleanup(self.ci.tmp.cleanup)

    def test_a_commit_that_leaves_caddy_alone_reuses_the_image_of_the_one_that_changed_it(self):
        changed = self.ci.commit("caddy", deploy__caddy__Dockerfile="FROM caddy:2.11.4\n")
        self.ci.commit("something else", app="x")
        head = self.ci.commit("and another", app="y")
        self.assertNotEqual(changed, head)

        done = self.ci.run(published=[changed])

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ci.calls, [f"pull {REPOSITORY}:{changed}", f"tag {REPOSITORY}:{changed} {NAME}"])
        self.assertEqual(self.ci.count("build"), 0, "nothing was built, so nothing was downloaded")

    def test_the_head_that_changes_caddy_is_built_because_nothing_is_published_for_it(self):
        self.ci.commit("caddy", deploy__caddy__Dockerfile="FROM caddy:2.11.4\n")
        head = self.ci.commit("caddy again", deploy__caddy__Dockerfile="FROM caddy:2.11.5\n")

        done = self.ci.run(published=[])

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ci.calls, [f"pull {REPOSITORY}:{head}", f"build -t {NAME} deploy/caddy"])

    def test_with_nothing_published_for_the_last_change_it_is_built(self):
        changed = self.ci.commit("caddy", deploy__caddy__Dockerfile="FROM caddy:2.11.4\n")
        self.ci.commit("something else", app="x")

        done = self.ci.run(published=[])

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ci.calls, [f"pull {REPOSITORY}:{changed}", f"build -t {NAME} deploy/caddy"])

    def test_an_image_published_for_some_other_commit_is_not_taken_for_it(self):
        self.ci.commit("caddy", deploy__caddy__Dockerfile="FROM caddy:2.11.4\n")
        other = self.ci.commit("something else", app="x")

        self.ci.run(published=[other])

        self.assertEqual(self.ci.count("build"), 1)
        self.assertEqual(self.ci.count("tag"), 0)


class NoRetriesTests(SimpleTestCase):
    def setUp(self):
        self.ci = ScriptRun()
        self.addCleanup(self.ci.tmp.cleanup)
        self.ci.commit("caddy", deploy__caddy__Dockerfile="FROM caddy:2.11.4\n")

    def test_a_build_that_fails_fails_the_script_after_one_attempt(self):
        done = self.ci.run(published=[], build_fails=True)

        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.ci.count("pull"), 1)
        self.assertEqual(self.ci.count("build"), 1)

    def test_the_script_and_the_step_hold_no_loop_and_no_retry_wrapper(self):
        code = "\n".join(
            line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotRegex(code, r"(?m)^\s*(for|while|until)\b")
        for needle in ("retry", "sleep"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, code)
        step = WORKFLOW.split("Caddy image: reuse the published one, or build it", 1)[1].split("- name:", 1)[0]
        self.assertNotIn("retry", step.lower())


class TheWorkflowUsesItTests(SimpleTestCase):
    image = WORKFLOW.split("\n  image:\n", 1)[1].split("\n  publish:", 1)[0]

    def test_the_image_job_has_the_whole_history_the_script_asks_for(self):
        self.assertIn("fetch-depth: 0", self.image.split("- name: Build the application image", 1)[0])

    def test_the_caddy_image_comes_from_the_script_and_is_no_longer_built_inline(self):
        self.assertIn('scripts/caddy-image.sh "ghcr.io/${{ github.repository }}/caddy" "$CADDY_IMAGE"', self.image)
        self.assertNotIn('docker build -t "$CADDY_IMAGE" deploy/caddy', self.image)

    def test_what_it_names_is_what_the_validate_and_push_steps_use(self):
        self.assertIn('CADDY_IMAGE: ghcr.io/${{ github.repository }}/caddy:candidate-${{ github.sha }}', self.image)
        self.assertLess(self.image.index("caddy-image.sh"), self.image.index("The Caddyfile is valid"))
        self.assertIn('docker push "$CADDY_IMAGE"', self.image)
