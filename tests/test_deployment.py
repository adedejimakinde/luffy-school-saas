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


def production_settings(*names):
    """The named settings as `settings.py` computes them under `production.env`."""
    code = (
        "import json, settings; "
        f"print(json.dumps({{n: getattr(settings, n, None) for n in {list(names)!r}}}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BASE_DIR,
        env=production_environment(),
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
