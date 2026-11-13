"""Every file in `.github/workflows/` is a workflow GitHub can read.

A workflow file GitHub cannot parse runs nothing and reports nothing: the run
ends in no seconds with no jobs, and the pull request shows no checks at all, so
it looks like CI has not started rather than like a mistake. PR #281's first
push did exactly that. A step named `Caddy image: reuse the published one` has a
colon and a space in an unquoted value, which is not YAML, and every test in the
suite passed because none of them parsed the file.

So this parses each one with a YAML parser and fails on any error, whatever the
error is: a colon in a name, a tab, a key indented one space too far, an
unclosed quote. It then holds the shape a parser alone does not: a workflow has
jobs, a job has somewhere to run (or a workflow to call), and a step does
something. GitHub rejects those too, and a mis-indented key often parses
cleanly and lands in the wrong place.

PyYAML reads YAML 1.1 and GitHub reads 1.2, which differ in corners a workflow
file does not use (`on` parses as `True` here, which is why it is looked up as
either).
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.test import SimpleTestCase

WORKFLOWS = sorted((Path(settings.BASE_DIR) / ".github" / "workflows").glob("*.y*ml"))


def load(path):
    with path.open() as handle:
        return yaml.safe_load(handle)


class EveryWorkflowParsesTests(SimpleTestCase):
    def test_there_are_workflows_to_check(self):
        names = {path.name for path in WORKFLOWS}
        self.assertTrue({"tests.yml", "deploy.yml"} <= names, names)

    def test_each_file_parses(self):
        for path in WORKFLOWS:
            with self.subTest(file=path.name):
                try:
                    document = load(path)
                except yaml.YAMLError as error:
                    self.fail(f"{path.name} is not valid YAML: {error}")
                self.assertIsInstance(document, dict, f"{path.name} is not a mapping")

    def test_each_has_a_trigger_and_jobs(self):
        for path in WORKFLOWS:
            with self.subTest(file=path.name):
                document = load(path)
                self.assertTrue("on" in document or True in document, "no trigger")
                self.assertIsInstance(document.get("jobs"), dict)
                self.assertTrue(document["jobs"], "no jobs")

    def test_each_job_has_somewhere_to_run_and_each_step_does_something(self):
        for path in WORKFLOWS:
            for job_id, job in load(path)["jobs"].items():
                with self.subTest(file=path.name, job=job_id):
                    self.assertIsInstance(job, dict)
                    if "uses" in job:
                        continue
                    self.assertIn("runs-on", job)
                    steps = job.get("steps")
                    self.assertIsInstance(steps, list)
                    self.assertTrue(steps, "no steps")
                    for number, step in enumerate(steps, start=1):
                        self.assertIsInstance(step, dict, f"step {number}")
                        self.assertTrue(
                            "run" in step or "uses" in step,
                            f"step {number} ({step.get('name')!r}) neither runs nor uses anything",
                        )
                        if "name" in step:
                            self.assertIsInstance(step["name"], str, f"step {number}")

    def test_a_needs_names_a_job_that_exists(self):
        for path in WORKFLOWS:
            document = load(path)
            for job_id, job in document["jobs"].items():
                needs = job.get("needs", [])
                for needed in [needs] if isinstance(needs, str) else needs:
                    with self.subTest(file=path.name, job=job_id, needs=needed):
                        self.assertIn(needed, document["jobs"])


class PublishRunsOnMainWhenTheShardsAreSkippedTests(SimpleTestCase):
    """4a74985 could not be deployed: on a push to `main` the shards and
    `screens` are skipped by design, and `publish`, whose `if` had only the
    implicit `success()` (evaluated over every ancestor job), was skipped with
    them, so the deploy guard never saw it succeed."""

    def setUp(self):
        self.jobs = load(Path(settings.BASE_DIR) / ".github/workflows/tests.yml")["jobs"]

    def test_publish_needs_pins_the_gate_and_the_image(self):
        self.assertEqual(set(self.jobs["publish"]["needs"]), {"pins", "test", "image"})

    def test_publish_condition_overrides_the_implicit_success_check(self):
        condition = str(self.jobs["publish"]["if"])
        self.assertIn("!cancelled()", condition)
        for job in ("pins", "test", "image"):
            self.assertIn(f"needs.{job}.result == 'success'", condition)
        # Never asks about the shards or screens: they are skipped on main.
        self.assertNotIn("shard", condition)
        self.assertNotIn("screens", condition)
        self.assertIn("refs/heads/main", condition)

    def test_the_shards_stay_off_main(self):
        self.assertIn("pull_request", self.jobs["shard"]["if"])

    def gate(self, event, **results):
        import os
        import subprocess

        step = self.jobs["test"]["steps"][0]
        env = {
            "PATH": os.environ["PATH"],
            "EVENT": event,
            "CHANGES": "success", "SHARDS": "skipped",
            "SCREENS": "skipped", "PINS": "success",
        }
        env.update({k.upper(): v for k, v in results.items()})
        return subprocess.run(["bash", "-e", "-c", step["run"]], env=env,
                              capture_output=True, text=True).returncode

    def test_the_gate_passes_on_main_with_the_shards_and_screens_skipped(self):
        self.assertEqual(self.gate("push"), 0)

    def test_the_gate_refuses_skipped_shards_on_a_pull_request(self):
        self.assertEqual(self.gate("pull_request"), 1)

    def test_the_gate_refuses_failed_pins_or_shards_on_main(self):
        self.assertEqual(self.gate("push", pins="failure"), 1)
        self.assertEqual(self.gate("push", shards="failure"), 1)
        self.assertEqual(self.gate("push", pins="skipped"), 1)
