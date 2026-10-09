"""The restore drill and the backup commands, as the repository's own files
describe them.

Nothing here starts Docker or reaches B2; those are the launch session's
(`docs/demo-server.md`, section 7). What these hold is that the pieces the
documentation names are the pieces that exist, and that the weekly script asks
the question it is supposed to ask, in the order it has to.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)


def section_7():
    text = (BASE_DIR / "docs/demo-server.md").read_text()
    start = text.index("## 7. Backups and restore")
    return text[start : text.index("\n## ", start + 1)]


class TheRestoreScriptCountsOneSchoolsRowsTests(SimpleTestCase):
    def setUp(self):
        self.script = (BASE_DIR / "deploy/restore-check.sh").read_text()

    def test_it_takes_the_live_counts_before_it_restores_anything(self):
        """The baseline has to come from the live database and be taken before
        the throwaway one exists, or there is nothing to compare with.

        CONTROL 16: deleting the `--print-counts` call makes this red.
        """
        taken = self.script.index("--print-counts")
        restored = self.script.index("up -d restore-db")

        self.assertLess(taken, restored)

    def test_it_hands_them_to_verify_restore_pointed_at_the_restored_database(self):
        last = [l for l in self.script.splitlines() if "verify_restore" in l and "docker compose" in l][-1]
        rest = self.script[self.script.index(last) :]

        self.assertIn("POSTGRES_HOST=restore-db", last)
        self.assertIn('--expect-counts "$LIVE_COUNTS"', rest)

    def test_the_live_counts_are_not_taken_from_the_restored_database(self):
        capture = self.script[self.script.index("LIVE_COUNTS=") : self.script.index("# Only the throwaway")]

        self.assertNotIn("restore-db", capture)

    def test_the_script_is_executable_and_parses(self):
        import os
        import subprocess

        self.assertTrue(os.access(BASE_DIR / "deploy/restore-check.sh", os.X_OK))
        subprocess.run(["bash", "-n", str(BASE_DIR / "deploy/restore-check.sh")], check=True)


class TheBackupCommandsInTheDocsAreRealTests(SimpleTestCase):
    def test_the_commands_section_7_runs_are_the_ones_the_repository_ships(self):
        """Section 7 is what a person types at the launch. A command renamed in
        the image or the script and not here is a runbook that fails when the
        database is already gone.

        CONTROL 17: renaming `classnode-backup` in the Dockerfile makes this red.
        """
        doc = section_7()
        dockerfile = (BASE_DIR / "deploy/postgres/Dockerfile").read_text()

        self.assertIn("classnode-backup", doc)
        self.assertRegex(dockerfile, r"COPY backup\.sh /usr/local/bin/classnode-backup")
        self.assertIn("wal-g backup-list", doc)
        self.assertIn("/opt/classnode/deploy/restore-check.sh", doc)
        self.assertTrue((BASE_DIR / "deploy/restore-check.sh").is_file())
        self.assertIn("verify_restore", doc)
        self.assertTrue((BASE_DIR / "schools/management/commands/verify_restore.py").is_file())
        self.assertIn("/opt/classnode/deploy/cron/classnode", doc)
        self.assertTrue((BASE_DIR / "deploy/cron/classnode").is_file())

    def test_every_variable_it_asks_for_is_one_the_scripts_read(self):
        doc = section_7()
        scripts = "".join(
            (BASE_DIR / name).read_text()
            for name in ("deploy/postgres/backup.sh", "deploy/postgres/entrypoint.sh", "deploy/restore-check.sh")
        )
        block = doc[doc.index("WALG_S3_PREFIX") : doc.index("```", doc.index("WALG_S3_PREFIX"))]
        names = re.findall(r"^([A-Z0-9_]+)=", block, re.M)

        self.assertIn("WALG_S3_PREFIX", names)
        for name in ("WALG_S3_PREFIX", "BACKUP_HEARTBEAT_URL"):
            with self.subTest(name=name):
                self.assertIn(name, scripts)

    def test_it_names_the_files_the_stack_reads_the_variables_from(self):
        compose = (BASE_DIR / "deploy/compose.yml").read_text()

        self.assertIn("/etc/classnode/backup.env", section_7())
        self.assertIn("backup.env", compose)
