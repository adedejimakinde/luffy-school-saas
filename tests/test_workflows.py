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
