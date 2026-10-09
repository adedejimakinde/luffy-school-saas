"""The first-day runbook (`docs/first-day.md`) and the two scripts it has the
founder run (`deploy/bootstrap.sh`, `deploy/init-env.sh`), as the repository's
own files describe them.

Nothing here starts a server. What these hold is that the pieces the runbook
names are the pieces that exist, and the four promises it makes a non-technical
reader that a wrong edit would break without anyone noticing until the day:

1. **The firewall lets in 22, 80 and 443 and nothing else.**
2. **Password login stays on until the key has been seen to work.** The SSH
   lock is its own command, never part of an ordinary run.
3. **No secret is typed into a command or committed.** The templates hold only
   placeholders, and no command in the runbook assigns a secret.
4. **The deploy workflow and the server agree** on the user, the secrets and
   the paths, so the button that was tested on day one is the one that is pressed.
"""

import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)
DOC = BASE_DIR / "docs" / "first-day.md"
BOOTSTRAP = BASE_DIR / "deploy" / "bootstrap.sh"
INIT_ENV = BASE_DIR / "deploy" / "init-env.sh"
TEMPLATES = BASE_DIR / "deploy" / "env"

SECRET_ASSIGNMENT = re.compile(r"\b\w*(SECRET|PASSWORD|TOKEN|DSN|API_KEY|PRIVATE)\w*=\S", re.I)


def steps():
    """`{number: heading}` for the runbook's `## N. heading` lines."""
    return {
        int(m.group(1)): m.group(2)
        for m in re.finditer(r"^## (\d+)\. (.+)$", DOC.read_text(), re.M)
    }


def code_blocks():
    return re.findall(r"```(?:bash|powershell)?\n(.*?)```", DOC.read_text(), re.S)


class TheScriptsParseTests(SimpleTestCase):
    def test_each_is_valid_bash_and_executable(self):
        """CONTROL 1: an unclosed `if` in either makes this red."""
        for path in (BOOTSTRAP, INIT_ENV):
            with self.subTest(script=path.name):
                result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(path.stat().st_mode & 0o111, f"{path.name} is not executable")


class TheFirewallTests(SimpleTestCase):
    def test_only_22_80_and_443_are_allowed(self):
        """Docker publishes ports around ufw, so a port added here would be a
        door that looks closed; the set is the whole policy.

        CONTROL 2: adding `ufw allow 5432/tcp` makes this red.
        """
        allowed = re.findall(r"^ufw allow (\S+)", BOOTSTRAP.read_text(), re.M)

        self.assertEqual(sorted(allowed), ["22/tcp", "443/tcp", "443/udp", "80/tcp"])

    def test_ssh_is_allowed_before_the_firewall_is_switched_on(self):
        text = BOOTSTRAP.read_text()

        self.assertLess(text.index("ufw allow 22/tcp"), text.index("ufw --force enable"))

    def test_the_default_policy_is_deny(self):
        self.assertIn("ufw default deny incoming", BOOTSTRAP.read_text())


class PasswordLoginIsTurnedOffOnlyOnRequestTests(SimpleTestCase):
    def test_the_lock_is_written_only_inside_the_lock_branch(self):
        """The drop-in that turns passwords off is installed once, after the
        `lock` branch begins and before the ordinary run's first step. A plain
        run therefore cannot reach it.

        CONTROL 3: moving the `install_file "$SSHD_DROPIN"` call below
        "1. checks" makes this red.
        """
        text = BOOTSTRAP.read_text()
        installs = [m.start() for m in re.finditer(r'install_file "\$SSHD_DROPIN"', text)]
        lock = text.index('if [ "$MODE" = lock ]')
        ordinary = text.index("# -------------------------------------------------------------------- 1. checks")

        self.assertEqual(len(installs), 1)
        self.assertTrue(lock < installs[0] < ordinary)

    def test_the_lock_asks_first_and_checks_sshd_afterwards(self):
        text = BOOTSTRAP.read_text()
        lock = text[text.index('if [ "$MODE" = lock ]') : text.index("# ---", text.index('if [ "$MODE" = lock ]'))]

        self.assertIn("Type yes to lock", lock)
        self.assertIn("authorized_keys", lock)
        self.assertIn("sshd -T", lock)
        self.assertIn("rm -f \"$SSHD_DROPIN\"", lock)  # taken back if sshd disagrees

    def test_the_drop_in_sorts_before_cloud_inits(self):
        """sshd keeps the FIRST value it reads, and cloud-init's
        `50-cloud-init.conf` turns passwords on."""
        self.assertRegex(BOOTSTRAP.read_text(), r"SSHD_DROPIN=/etc/ssh/sshd_config\.d/0\d-")

    def test_a_plain_run_does_not_turn_password_login_off(self):
        text = BOOTSTRAP.read_text()
        ordinary = text[text.index("# -------------------------------------------------------------------- 1. checks") :]

        self.assertNotIn("PasswordAuthentication no", ordinary)


class TheBootstrapHasWhatTheTaskNamesTests(SimpleTestCase):
    def test_every_piece_is_there(self):
        text = BOOTSTRAP.read_text()
        for needle in (
            "apt-get",  # updates
            "fail2ban",
            "unattended-upgrades",
            "docker-ce",
            "adduser --disabled-password",  # the deploy user
            "usermod -aG docker deploy",
            "/home/deploy/.ssh/authorized_keys",
            "/opt/classnode",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_it_refuses_a_private_key_in_the_public_key_slot(self):
        text = BOOTSTRAP.read_text()

        self.assertIn("ssh-ed25519", text)
        self.assertIn("ssh-keygen -l", text)


class TheTemplatesHoldNoSecretTests(SimpleTestCase):
    def values(self, name):
        found = {}
        for line in (TEMPLATES / name).read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                found[key] = value
        return found

    def test_every_value_is_a_placeholder_or_a_fixed_setting(self):
        """CONTROL 4: a real-looking token on any line makes this red."""
        allowed = {"GENERATE", "CHANGE_ME", "hex"}
        for path in sorted(TEMPLATES.glob("*.env.example")):
            for key, value in self.values(path.name).items():
                with self.subTest(file=path.name, key=key):
                    self.assertIn(value, allowed)

    def test_caddy_gets_the_two_values_the_compose_file_says_and_nothing_else(self):
        self.assertEqual(set(self.values("caddy.env.example")), {"CLOUDFLARE_API_TOKEN", "ACME_EMAIL"})

    def test_the_database_secrets_are_generated_not_typed(self):
        secrets = self.values("secrets.env.example")

        self.assertEqual(secrets["DJANGO_SECRET_KEY"], "GENERATE")
        self.assertEqual(secrets["POSTGRES_PASSWORD"], "GENERATE")

    def test_demo_server_is_never_switched_on_for_production(self):
        """`DEMO_SERVER` unlocks `load_demo`; the template may warn about it but
        must not set it."""
        self.assertNotIn("DEMO_SERVER", self.values("secrets.env.example"))

    def test_backup_env_has_every_name_the_database_image_reads(self):
        names = set(self.values("backup.env.example"))
        entrypoint = (BASE_DIR / "deploy/postgres/entrypoint.sh").read_text()

        for name in ("WALG_S3_PREFIX", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_ENDPOINT",
                     "AWS_REGION", "WALG_LIBSODIUM_KEY", "WALG_LIBSODIUM_KEY_TRANSFORM"):
            with self.subTest(name=name):
                self.assertIn(name, names)
        self.assertIn("WALG_S3_PREFIX", entrypoint)

    def test_init_env_never_overwrites_and_never_echoes(self):
        """CONTROL 5: removing the `-e "$dest"` guard makes this red."""
        text = INIT_ENV.read_text()

        self.assertIn('if [ -e "$dest" ]', text)
        self.assertNotRegex(text, r"echo[^\n]*\$\{?(value|token|tmp)")
        self.assertIn("root -g deploy", text)


class TheRunbookTests(SimpleTestCase):
    def test_the_steps_are_numbered_one_to_n_without_gaps(self):
        numbers = sorted(steps())

        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        self.assertGreaterEqual(len(numbers), 25)

    def test_the_order_is_the_order_asked_for(self):
        """first login, bootstrap, key check, lock, secrets, first deploy,
        create_school, uptime monitor, restore drill."""
        text = DOC.read_text()
        order = [
            "## 4. First login, as root",
            "## 6. Run the bootstrap script",
            "## 7. Prove your key works",
            "## 8. ⚠ Turn off password login",
            "## 11. ⚠ Create secrets.env and caddy.env",
            "## 15. ⚠ Deploy by hand, once",
            "## 20. ⚠ Create the first school",
            "## 21. Create the monitor",
            "## 28. ⚠ Drill B",
        ]
        positions = [text.index(h) for h in order]

        self.assertEqual(positions, sorted(positions))

    def test_every_step_that_changes_something_says_how_to_undo_it(self):
        text = DOC.read_text()
        for number, heading in steps().items():
            start = text.index(f"## {number}. ")
            nxt = re.search(r"^(## \d+\. |# Part |# If you locked|# Where things)", text[start + 3 :], re.M)
            body = text[start : start + 3 + nxt.start()] if nxt else text[start:]
            with self.subTest(step=number, heading=heading):
                self.assertIn("**Undo.**", body)

    def test_the_risky_steps_are_marked(self):
        for number in (8, 11, 15, 20, 24, 25, 28):
            with self.subTest(step=number):
                self.assertIn("⚠", steps()[number])

    def test_the_lock_out_section_uses_the_vnc_console(self):
        text = DOC.read_text()
        section = text[text.index("# If you locked yourself out") :]

        self.assertIn("VNC", section)
        self.assertIn("--unlock-ssh", section)

    def test_it_names_this_server(self):
        self.assertIn("169.58.181.9", DOC.read_text())

    def test_no_command_assigns_a_secret(self):
        """A secret typed in a command lands in shell history and the process
        list. They go into files, with `nano`, or are generated.

        CONTROL 6: `CLOUDFLARE_API_TOKEN=abc` in a code block makes this red.
        """
        for block in code_blocks():
            for line in block.splitlines():
                with self.subTest(line=line[:60]):
                    self.assertIsNone(SECRET_ASSIGNMENT.search(line))

    def test_every_repository_path_it_names_exists(self):
        for path in sorted(set(re.findall(r"(?<![\w/])(deploy/[\w./-]+|docs/[\w-]+\.md)", DOC.read_text()))):
            path = path.rstrip(".")
            with self.subTest(path=path):
                self.assertTrue((BASE_DIR / path).exists(), path)

    def test_a_step_number_in_a_file_points_at_the_step_it_means(self):
        """The scripts and templates say "docs/first-day.md, step N"; renumbering
        the runbook without them sends the reader to the wrong step."""
        expected = {
            "deploy/bootstrap.sh": {5: "public keys"},
            "deploy/env/caddy.env.example": {10: "token"},
            "deploy/env/backup.env.example": {24: "backup.env"},
        }
        headings = steps()
        for name, wanted in expected.items():
            text = (BASE_DIR / name).read_text()
            for number, keyword in wanted.items():
                with self.subTest(file=name, step=number):
                    self.assertRegex(text, rf"first-day\.md,? step {number}\b")
                    self.assertIn(keyword.lower(), headings[number].lower())


class TheWorkflowAndTheServerAgreeTests(SimpleTestCase):
    workflow = (BASE_DIR / ".github/workflows/deploy.yml").read_text()

    def test_the_workflow_logs_in_as_the_user_the_bootstrap_makes(self):
        self.assertIn("deploy@", self.workflow)
        self.assertIn("adduser --disabled-password", BOOTSTRAP.read_text())
        self.assertRegex(BOOTSTRAP.read_text(), r"/home/deploy/\.ssh/authorized_keys")

    def test_the_runbook_sets_exactly_the_secrets_the_workflow_reads(self):
        read = set(re.findall(r"secrets\.(DEPLOY_\w+)", self.workflow))
        text = DOC.read_text()
        set_by_runbook = set(re.findall(r"\| `(DEPLOY_\w+)` \|", text))

        self.assertEqual(read, {"DEPLOY_HOST", "DEPLOY_SSH_KEY", "DEPLOY_KNOWN_HOSTS"})
        self.assertEqual(read, set_by_runbook)

    def test_the_workflow_uses_the_environment_the_runbook_creates(self):
        self.assertIn("environment: production", self.workflow)
        self.assertIn("name it `production`", " ".join(DOC.read_text().split()))

    def test_the_secrets_directory_is_readable_by_deploy(self):
        """`docker compose` reads an env_file as whoever runs it, and the deploy
        user runs it: root-only files would fail the very first button press."""
        self.assertIn("install -d -m 750 -o root -g deploy /etc/classnode", BOOTSTRAP.read_text())
