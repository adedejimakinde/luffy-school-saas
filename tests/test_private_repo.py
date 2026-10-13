"""The repository is private: the server must still be able to get its code and
images, and nothing may quietly depend on the repository being public.

Structure tests on the files that carry that promise (the scripts cannot be run
against GitHub from here). docs/first-day.md steps 6 and 12 are the runbook.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)
BOOTSTRAP = (BASE_DIR / "deploy" / "bootstrap.sh").read_text()
DEPLOY = (BASE_DIR / "deploy" / "deploy.sh").read_text()
FIRST_DAY = (BASE_DIR / "docs" / "first-day.md").read_text()
HANDOVER = (BASE_DIR / "docs" / "handover.md").read_text()
WORKFLOWS = {p.name: p.read_text() for p in (BASE_DIR / ".github" / "workflows").glob("*.yml")}


class TheServerReadsThePrivateRepositoryTests(SimpleTestCase):
    def test_the_clone_is_over_ssh_not_an_anonymous_https_url(self):
        self.assertIn("git@github.com:adedejimakinde/luffy-school-saas.git", BOOTSTRAP)
        self.assertNotRegex(BOOTSTRAP, r"https://github\.com/adedejimakinde/luffy-school-saas")

    def test_githubs_host_key_is_pinned_not_trusted_on_first_use(self):
        self.assertIn("GITHUB_ED25519_FP=", BOOTSTRAP)
        self.assertIn("StrictHostKeyChecking yes", BOOTSTRAP)
        self.assertNotIn("StrictHostKeyChecking no", BOOTSTRAP)
        self.assertNotIn("accept-new", BOOTSTRAP)

    def test_the_server_makes_its_own_key_and_no_private_key_is_written_down(self):
        self.assertIn("ssh-keygen -q -t ed25519 -N ''", BOOTSTRAP)
        self.assertNotIn("PRIVATE KEY", BOOTSTRAP)

    def test_the_runbook_says_the_key_is_read_only(self):
        self.assertIn('Leave "Allow write', " ".join(FIRST_DAY.split()))

    def test_the_runbook_no_longer_curls_the_script_from_a_public_url(self):
        self.assertNotIn("raw.githubusercontent.com", FIRST_DAY)

    def test_the_workflows_download_nothing_from_the_repository_unauthenticated(self):
        for name, text in WORKFLOWS.items():
            with self.subTest(workflow=name):
                self.assertNotIn("raw.githubusercontent.com", text)
                self.assertNotIn("git clone", text)


class TheGhcrTokenIsInOneRootOnlyFileTests(SimpleTestCase):
    def test_deploy_logs_in_from_the_root_only_file_through_one_fixed_sudo_rule(self):
        self.assertIn("/root/ghcr-login", DEPLOY)
        self.assertIn("deploy ALL=(root) NOPASSWD: /usr/bin/cat /root/ghcr-login", BOOTSTRAP)
        rules = re.findall(r"NOPASSWD:(.*)", BOOTSTRAP)
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertNotIn("*", rule)
                self.assertNotIn("ALL", rule.replace("NOPASSWD", ""))

    def test_the_login_goes_into_a_throwaway_config_that_is_deleted(self):
        self.assertIn('DOCKER_CONFIG="$(mktemp -d)"', DEPLOY)
        self.assertIn("rm -rf \"$DOCKER_CONFIG\"", DEPLOY)
        self.assertIn("--password-stdin", DEPLOY)

    def test_the_login_comes_before_the_pull(self):
        self.assertLess(DEPLOY.index("docker login ghcr.io"), DEPLOY.index("docker compose pull"))

    def test_the_token_is_never_on_a_command_line(self):
        self.assertNotRegex(DEPLOY, r"docker login[^\n]*(-p |--password )")

    def test_the_file_is_made_root_only_before_the_token_goes_in(self):
        self.assertLess(
            FIRST_DAY.index("install -m 600 -o root -g root /dev/null /root/ghcr-login"),
            FIRST_DAY.index("nano /root/ghcr-login"),
        )

    def test_the_runbook_tells_the_founder_when_the_token_expires(self):
        text = " ".join(FIRST_DAY.split())
        self.assertIn("expiry date in your calendar", text)
        self.assertIn("Renewing the token", text)
        self.assertIn("expir", HANDOVER[: HANDOVER.index("\n---\n")])


class CiWorksWhenThePrivateTests(SimpleTestCase):
    def test_pushing_images_uses_the_runs_own_token_with_packages_write(self):
        tests = WORKFLOWS["tests.yml"]
        self.assertIn("secrets.GITHUB_TOKEN", tests)
        self.assertGreaterEqual(tests.count("packages: write"), 2)

    def test_every_image_names_the_repository_it_belongs_to(self):
        for dockerfile in ("Dockerfile", "deploy/caddy/Dockerfile", "deploy/postgres/Dockerfile"):
            with self.subTest(dockerfile=dockerfile):
                self.assertIn(
                    'LABEL org.opencontainers.image.source="https://github.com/adedejimakinde/luffy-school-saas"',
                    (BASE_DIR / dockerfile).read_text(),
                )


class TheLicenceIsAllRightsReservedTests(SimpleTestCase):
    text = (BASE_DIR / "LICENSE").read_text()

    def test_it_reserves_all_rights_for_classnode(self):
        self.assertIn("Classnode Edtech Limited", self.text)
        self.assertIn("All rights reserved", self.text)

    def test_no_open_source_licence_is_left(self):
        for needle in ("MIT License", "Permission is hereby granted", "Apache License", "GNU General Public"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)
        for name in ("package.json", "README.md"):
            self.assertNotRegex((BASE_DIR / name).read_text(), r'"license"\s*:\s*"(MIT|Apache|GPL|BSD|ISC)')
