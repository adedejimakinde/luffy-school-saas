"""The production configuration, tested as it is committed.

Every test here reads `deploy/production.env` — the file the server runs with —
and imports `settings.py` in a **separate process** under exactly that
environment, with nothing inherited from the shell running the tests. So what
these assert is the deployed configuration, not a value typed into a test: a
change to `production.env` or to the settings logic that derives from it is a
change these see.

Four claims, each the reason for a setting that would otherwise be easy to
"tidy" away:

1. **Connections are not pooled** (issue #115). Tenant isolation is Postgres
   `search_path`, which is per-connection state; a pooler in transaction mode
   would hand one school's `search_path` to another school's queries, silently.
2. **Behind the proxy, an HTTPS request is seen as HTTPS.** Without the proxy
   header the HTTPS redirect sends every request back to HTTPS for ever.
3. **The sign-in throttle counts the client, not the proxy.** Behind Caddy
   every request arrives from Caddy's address.
4. **`/healthz/` asks the database**, so a deploy onto a server that cannot
   reach Postgres is not waved through.
"""

import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import OperationalError
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from accounts.throttling import client_address
from schools.models import Domain, School

BASE_DIR = Path(settings.BASE_DIR)
PRODUCTION_ENV = BASE_DIR / "deploy" / "production.env"


def read_env_file(path):
    """`KEY=VALUE` lines, as compose's `env_file` reads them."""
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def production_environment():
    """`production.env` plus placeholder secrets, and nothing from this shell.

    Deliberately not `os.environ` plus the file: the devcontainer sets
    `DJANGO_DEBUG=1` and a console email backend, and a test that inherited
    them would be describing the development configuration while claiming the
    production one.
    """
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp")}
    env.update(read_env_file(PRODUCTION_ENV))
    env.update(
        {
            # Placeholders for what lives in the server's secrets.env. Random, so
            # `check --deploy` judges the key's strength as it would a real one.
            "DJANGO_SECRET_KEY": "test-only-" + secrets.token_urlsafe(48),
            "POSTGRES_PASSWORD": "unused-by-these-tests",
        }
    )
    return env


def production_settings(*names, extra_env=None):
    """The named settings as `settings.py` computes them under `production.env`
    (plus `extra_env`: what a server's `secrets.env` could add)."""
    code = (
        "import json, settings; "
        f"print(json.dumps({{n: getattr(settings, n, None) for n in {list(names)!r}}}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BASE_DIR,
        env={**production_environment(), **(extra_env or {})},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"settings.py did not import under production.env:\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


class TheParentDomainIsNamedOnceTests(SimpleTestCase):
    def test_everything_that_must_agree_with_it_is_derived_from_it(self):
        """`PLATFORM_DOMAIN` is the one place a deployment names its domain.
        The cookie domain, allowed hosts and From address follow from it rather
        than being typed again, so they cannot drift apart."""
        domain = read_env_file(PRODUCTION_ENV)["PLATFORM_DOMAIN"]
        derived = production_settings(
            "PLATFORM_DOMAIN",
            "SESSION_COOKIE_DOMAIN",
            "ALLOWED_HOSTS",
            "DEFAULT_FROM_EMAIL",
            "PORTAL_HOST",
            "INVITATION_ACCEPT_URL",
        )

        self.assertEqual(derived["PLATFORM_DOMAIN"], domain)
        self.assertEqual(derived["SESSION_COOKIE_DOMAIN"], f".{domain}")
        self.assertEqual(derived["ALLOWED_HOSTS"], [f".{domain}"])
        self.assertEqual(derived["DEFAULT_FROM_EMAIL"], f"no-reply@{domain}")
        # The portal, and the accept page on it (urls_public.py).
        self.assertEqual(derived["PORTAL_HOST"], f"app.{domain}")
        self.assertEqual(
            derived["INVITATION_ACCEPT_URL"], f"https://app.{domain}/invitations/{{token}}/"
        )

    def test_the_domain_appears_nowhere_else_in_the_deployment_files(self):
        """Named once means named once: the Caddyfile and the compose file read
        the variable, and a literal copy anywhere would be the one that is
        missed when the domain changes."""
        domain = read_env_file(PRODUCTION_ENV)["PLATFORM_DOMAIN"]
        for name in (
            "deploy/compose.yml",
            "deploy/caddy/Caddyfile",
            "deploy/deploy.sh",
            "deploy/restore-check.sh",
            "deploy/cron/classnode",
            "settings.py",
        ):
            with self.subTest(file=name):
                self.assertNotIn(domain, (BASE_DIR / name).read_text())


class ConnectionsAreNotPooledTests(SimpleTestCase):
    def test_a_connection_per_request_and_no_pool(self):
        """**Issue #115.** Tenant isolation is Postgres `search_path`, set per
        request on the connection that request uses. With a connection per
        request, connection identity and tenant identity coincide by
        construction — the only topology the suite proves. Raising
        `CONN_MAX_AGE`, adding a client-side pool, or disabling server-side
        cursors for a transaction-mode pooler all step outside it, and
        `docs/tenancy.md` bans a transaction-mode pooler outright.

        CONTROL 1: raising `CONN_MAX_AGE` in settings.py makes this red.
        """
        database = production_settings("DATABASES")["DATABASES"]["default"]

        self.assertEqual(database.get("CONN_MAX_AGE"), 0)
        self.assertNotIn("pool", database.get("OPTIONS", {}))
        self.assertFalse(database.get("DISABLE_SERVER_SIDE_CURSORS", False))


class BehindTheProxyTests(TestCase):
    """A request as Caddy forwards it: plain HTTP on gunicorn's socket, with
    `X-Forwarded-Proto: https` saying what the client actually used."""

    def setUp(self):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)
        derived = production_settings(
            "SECURE_PROXY_SSL_HEADER",
            "SECURE_SSL_REDIRECT",
            "SECURE_HSTS_SECONDS",
            "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        )
        header = derived["SECURE_PROXY_SSL_HEADER"]
        self.production = {
            "SECURE_PROXY_SSL_HEADER": tuple(header) if header else None,
            "SECURE_SSL_REDIRECT": derived["SECURE_SSL_REDIRECT"],
            "SECURE_HSTS_SECONDS": derived["SECURE_HSTS_SECONDS"],
            "SECURE_HSTS_INCLUDE_SUBDOMAINS": derived["SECURE_HSTS_INCLUDE_SUBDOMAINS"],
        }

    def test_a_forwarded_https_request_is_served_not_redirected(self):
        """The failure this prevents is not subtle: with the redirect on and
        the proxy header off, every HTTPS request is redirected to HTTPS, for
        ever, and the whole platform is a redirect loop.

        CONTROL 2: settings.py not setting `SECURE_PROXY_SSL_HEADER` behind the
        proxy makes this red.
        """
        with override_settings(**self.production):
            response = Client().get("/staff-sign-in/", HTTP_X_FORWARDED_PROTO="https")

        self.assertEqual(response.status_code, 200, "an HTTPS request was sent back to HTTPS")
        self.assertIn("includeSubDomains", response.get("Strict-Transport-Security", ""))

    def test_a_plain_http_request_is_sent_to_https(self):
        """The control for the one above: the redirect really is on, so a 200
        there is the proxy header working and not the redirect being off."""
        with override_settings(**self.production):
            response = Client().get("/staff-sign-in/", HTTP_X_FORWARDED_PROTO="http")

        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].startswith("https://"))


class TheThrottleCountsTheClientTests(SimpleTestCase):
    CADDY = "172.18.0.5"
    CLIENT = "203.0.113.7"

    def address(self, forwarded_for):
        count = production_settings("TRUSTED_PROXY_COUNT")["TRUSTED_PROXY_COUNT"]
        request = RequestFactory().post(
            "/api/login/", REMOTE_ADDR=self.CADDY, HTTP_X_FORWARDED_FOR=forwarded_for
        )
        with override_settings(TRUSTED_PROXY_COUNT=count):
            return client_address(request)

    def test_behind_caddy_the_address_counted_is_the_clients(self):
        """Every request reaches gunicorn from Caddy. Counting that address
        would put the whole platform in one bucket, so fifty wrong passwords
        from anybody would lock out everybody.

        CONTROL 3: `TRUSTED_PROXY_COUNT` left at 0 in production.env makes this
        red.
        """
        self.assertEqual(self.address(self.CLIENT), self.CLIENT)

    def test_an_address_the_client_invented_is_not_believed(self):
        """Caddy overwrites the header, so this cannot arrive through it — but
        if it ever did, only the right-hand entry is one we wrote."""
        self.assertEqual(self.address(f"198.51.100.1, {self.CLIENT}"), self.CLIENT)


class HealthzTests(TestCase):
    def test_it_answers_ok_on_any_host_when_the_database_answers(self):
        """Ahead of tenancy, so it needs no `Domain` row — the container's own
        healthcheck asks `127.0.0.1`, which is nobody's host."""
        for host in ("127.0.0.1", "testserver", "nobody.example"):
            with self.subTest(host=host):
                response = Client().get("/healthz/", HTTP_HOST=host)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"ok\n")
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_it_is_503_when_the_database_does_not_answer(self):
        """A process that cannot reach Postgres serves nothing but errors, and
        a deploy must not be waved onto it.

        CONTROL 4: `/healthz/` answering without touching the database makes
        this red.
        """
        broken = mock.MagicMock()
        broken.cursor.side_effect = OperationalError("could not connect to server")

        with mock.patch("schools.health.connection", broken):
            response = Client().get("/healthz/", HTTP_HOST="127.0.0.1")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"database unavailable\n")

    def test_it_is_not_behind_the_https_redirect(self):
        """The container healthcheck speaks plain HTTP inside the network, with
        no proxy in front and so no `X-Forwarded-Proto` — the redirect alone is
        what it has to be ahead of."""
        derived = production_settings("SECURE_SSL_REDIRECT")
        self.assertTrue(derived["SECURE_SSL_REDIRECT"], "the redirect is off, so this proves nothing")

        with override_settings(SECURE_SSL_REDIRECT=True):
            response = Client().get("/healthz/", HTTP_HOST="127.0.0.1")

        self.assertEqual(response.status_code, 200)


class TheDeploymentChecklistTests(SimpleTestCase):
    def test_check_deploy_is_clean_under_production_env(self):
        """Django's deployment checklist, and this project's own checks
        registered with it (`accounts.E001`, `.E002`), under the configuration
        the server runs. `--fail-level WARNING`: every warning fails it, and
        the one silenced (`security.W021`, HSTS preload) is silenced in
        settings.py with its reason."""
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=BASE_DIR,
            env=production_environment(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class HostsAndOriginsComeFromTheEnvironmentTests(SimpleTestCase):
    def test_allowed_hosts_can_be_set_from_the_environment(self):
        """`DJANGO_ALLOWED_HOSTS` replaces the default derived from the domain,
        and blanks around the commas are not part of a host.

        CONTROL 9: settings.py ignoring `DJANGO_ALLOWED_HOSTS` makes this red.
        """
        derived = production_settings(
            "ALLOWED_HOSTS", extra_env={"DJANGO_ALLOWED_HOSTS": "app.example.org, .schools.example.org ,"}
        )

        self.assertEqual(derived["ALLOWED_HOSTS"], ["app.example.org", ".schools.example.org"])

    def test_csrf_trusted_origins_can_be_set_from_the_environment(self):
        """`DJANGO_CSRF_TRUSTED_ORIGINS` names extra origins, full ones.

        CONTROL 10: settings.py ignoring `DJANGO_CSRF_TRUSTED_ORIGINS` makes
        this red.
        """
        derived = production_settings(
            "CSRF_TRUSTED_ORIGINS",
            extra_env={"DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.org, https://*.example.org"},
        )

        self.assertEqual(
            derived["CSRF_TRUSTED_ORIGINS"], ["https://app.example.org", "https://*.example.org"]
        )

    def test_with_nothing_set_production_trusts_no_extra_origin(self):
        """The platform never posts across hosts (`docs/sign-in-page.md`), so
        an unset variable means none, not a wildcard under the domain."""
        self.assertEqual(production_settings("CSRF_TRUSTED_ORIGINS")["CSRF_TRUSTED_ORIGINS"], [])


class NoSecretsInTheRepoOrTheImageTests(SimpleTestCase):
    """What a checkout can hold that a deploy must never carry."""

    SECRET_KEY_NAME = re.compile(r"SECRET|PASSWORD|TOKEN|DSN|API_KEY|PRIVATE|CREDENTIAL", re.I)
    FORBIDDEN_TRACKED = re.compile(r"(^|/)(\.env(\..+)?|.*\.(rdb|pem|key|sqlite3?))$")

    def tracked_files(self):
        try:
            listed = subprocess.run(
                ["git", "ls-files"], cwd=BASE_DIR, capture_output=True, text=True, check=True
            ).stdout.splitlines()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        return listed

    def test_production_env_names_no_secret(self):
        """`deploy/production.env` is committed so a deployment is reviewable;
        a key whose name says secret, password, token or DSN belongs in
        `secrets.env` on the server (docs/deployment.md).

        CONTROL 11: adding `SENTRY_DSN=...` to production.env makes this red.
        """
        named = [k for k in read_env_file(PRODUCTION_ENV) if self.SECRET_KEY_NAME.search(k)]

        self.assertEqual(named, [])

    def test_no_environment_file_snapshot_or_key_is_tracked(self):
        """A `.env`, a Redis snapshot (`dump.rdb` held queued task arguments and
        was tracked, and so copied into the image), a key or a SQLite file.

        CONTROL 12: `git add -f dump.rdb` makes this red.
        """
        tracked = [f for f in self.tracked_files() if self.FORBIDDEN_TRACKED.search(f)]

        self.assertEqual(tracked, [])

    def test_the_image_leaves_those_out(self):
        """The Dockerfile says `COPY . .`, so `.dockerignore` is the only thing
        between a developer's local `.env` and the image's layers.

        CONTROL 13: deleting the `.env` or `*.rdb` line makes this red.
        """
        ignored = {
            line.strip()
            for line in (BASE_DIR / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }

        for pattern in (".env", ".env.*", "*.rdb", "*.sqlite3", "deploy", ".git"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignored)

    def test_the_settings_key_is_not_a_default_outside_development(self):
        """The one literal key in the repo is development's, and only `DEBUG`
        selects it: with it off and no `DJANGO_SECRET_KEY`, settings refuse."""
        env = {k: v for k, v in production_environment().items() if k != "DJANGO_SECRET_KEY"}
        result = subprocess.run(
            [sys.executable, "-c", "import settings"],
            cwd=BASE_DIR, env=env, capture_output=True, text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY is not set", result.stderr)


class TheServerHasOneLayoutTests(SimpleTestCase):
    """The repository is cloned to `/opt/classnode` (docs/demo-server.md, step 2)
    so the deploy files sit in `/opt/classnode/deploy/`. Everything that names
    a path on the server has to agree, or a cron job `cd`s into a directory
    with no compose file in it and fails every night, silently."""

    ROOT = "/opt/classnode"
    FILES = ("deploy/cron/classnode", ".github/workflows/deploy.yml", "docs/deployment.md")

    def paths(self):
        found = []
        for name in self.FILES:
            for match in re.finditer(r"/opt/classnode((?:/[\w.-]+)*)", (BASE_DIR / name).read_text()):
                found.append((name, match.group(0), BASE_DIR / match.group(1).lstrip("/")))
        return found

    def test_every_path_on_the_server_exists_in_the_clone(self):
        """CONTROL 14: a cron line back at `cd /opt/classnode` makes this red
        (there is no compose.yml at the clone's root)."""
        for name, written, local in self.paths():
            with self.subTest(file=name, path=written):
                self.assertTrue(local.exists(), f"{written} (in {name}) is not in the repository")

    def test_cron_runs_compose_from_the_directory_that_has_the_compose_file(self):
        for line in (BASE_DIR / "deploy/cron/classnode").read_text().splitlines():
            match = re.search(r"cd (/opt/classnode\S*) &&", line)
            if match:
                with self.subTest(line=line[:60]):
                    directory = BASE_DIR / match.group(1)[len(self.ROOT):].lstrip("/")
                    self.assertTrue((directory / "compose.yml").is_file(), match.group(1))
