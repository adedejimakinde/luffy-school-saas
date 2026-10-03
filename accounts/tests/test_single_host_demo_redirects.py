"""The single-host demo behind a forwarder: where a sign-in sends people.

A Codespace's forwarded port reaches Django as `Host: localhost:8000`, with the
name the browser used in `X-Forwarded-Host`. Before this, the school was looked
up under the wrong name and the links after sign-in went to `http://localhost/`.
With `DEMO_SINGLE_HOST=1`:

1. `X-Forwarded-Host` is trusted, so the school is the one the browser asked
   for, at each of two schools;
2. every link after sign-in is a path (`path_only`), and sign-out goes to a path;
3. neither holds without the flag, and production settings never trust the
   header.
"""

import json
import subprocess
import sys

from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings

from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain
from schools.tests.test_invitations import make_school
from tests.test_deployment import BASE_DIR, production_environment

PORTAL = "testserver"
SUNRISE = "sunrise-8000.app.github.dev"
HARBOUR = "harbour-8000.app.github.dev"
FORWARDER = "localhost:8000"
PASSWORD = "correct-horse-battery"

DEMO = dict(DEBUG=True, DEMO_SINGLE_HOST=True, USE_X_FORWARDED_HOST=True)


class ForwardedSetUp(TestCase):
    def setUp(self):
        portal = make_school("Portal", "portal", "public")
        # A portal row named `localhost`: what turned every link into
        # `http://localhost/...` in the Codespace.
        Domain.objects.create(tenant=portal, domain="localhost", is_primary=True)
        self.sunrise = make_school("Sunrise", "sunrise", "sunrise")
        Domain.objects.create(tenant=self.sunrise, domain=SUNRISE, is_primary=True)
        self.harbour = make_school("Harbour", "harbour", "harbour")
        Domain.objects.create(tenant=self.harbour, domain=HARBOUR, is_primary=True)
        for username, school in (("sunrise.teacher", self.sunrise), ("harbour.teacher", self.harbour)):
            grant_membership(User.objects.create_user(username, PASSWORD, full_name=username), school, Role.TEACHER)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def sign_in(self, forwarded, username):
        client = Client(enforce_csrf_checks=True)
        headers = {"HTTP_HOST": FORWARDER, "HTTP_X_FORWARDED_HOST": forwarded}
        token = client.get("/api/csrf/", **headers).json()["csrf_token"]
        response = client.post(
            "/api/login/",
            data={"identifier": username, "password": PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
            **headers,
        )
        return client, response, headers


@override_settings(**DEMO)
class TheForwardedNameIsTheSchoolTests(ForwardedSetUp):
    def test_each_school_answers_under_the_name_the_browser_used(self):
        for host, username, slug in (
            (SUNRISE, "sunrise.teacher", "sunrise"),
            (HARBOUR, "harbour.teacher", "harbour"),
        ):
            with self.subTest(host=host):
                client, response, headers = self.sign_in(host, username)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([s["slug"] for s in response.json()["schools"]], [slug])
                self.assertEqual(client.get("/marking/", **headers).status_code, 200)

    def test_the_same_request_trusted_reaches_the_school(self):
        """The control for `WithoutTheFlagNothingChangesTests`: trusted, the
        same request reaches Sunrise, which refuses Harbour's teacher."""
        self.client.force_login(User.objects.get(username="harbour.teacher"))
        response = self.client.get("/marking/", HTTP_HOST=FORWARDER, HTTP_X_FORWARDED_HOST=SUNRISE)

        self.assertEqual(response.status_code, 403)

    def test_a_login_at_one_school_does_not_open_the_other(self):
        client, _, _ = self.sign_in(SUNRISE, "sunrise.teacher")

        refused = client.get("/marking/", HTTP_HOST=FORWARDER, HTTP_X_FORWARDED_HOST=HARBOUR)
        self.assertEqual(refused.status_code, 403)

    def test_every_school_in_the_answer_is_linked_by_path(self):
        for host, username in ((SUNRISE, "sunrise.teacher"), (HARBOUR, "harbour.teacher")):
            with self.subTest(host=host):
                _, response, _ = self.sign_in(host, username)
                self.assertTrue(all(s["path_only"] for s in response.json()["schools"]))

    def test_sign_out_lands_on_a_path_on_this_host(self):
        client, _, headers = self.sign_in(SUNRISE, "sunrise.teacher")
        token = client.get("/api/csrf/", **headers).json()["csrf_token"]

        response = client.post("/sign-out/", {"next": "/marking/", "csrfmiddlewaretoken": token}, **headers)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/staff-sign-in/")


class WithoutTheFlagNothingChangesTests(ForwardedSetUp):
    def test_the_answer_links_by_host(self):
        Domain.objects.filter(domain="localhost").update(domain=PORTAL)
        client = Client()
        token = client.get("/api/csrf/", HTTP_HOST=PORTAL).json()["csrf_token"]
        response = client.post(
            "/api/login/",
            data={"identifier": "sunrise.teacher", "password": PASSWORD},
            content_type="application/json",
            HTTP_HOST=PORTAL,
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(s["host"], s["path_only"]) for s in response.json()["schools"]], [(SUNRISE, False)]
        )

    def test_sign_out_still_goes_to_the_portal(self):
        user = User.objects.get(username="sunrise.teacher")
        self.client.force_login(user)

        response = self.client.post("/sign-out/", {"next": "/marking/"}, HTTP_HOST=SUNRISE)

        self.assertEqual(response["Location"], "//localhost/staff-sign-in/")

    def test_the_forwarded_name_is_not_trusted(self):
        """`Host: localhost:8000` is the portal's row here, whatever the header
        claims. Harbour's teacher asking for Sunrise's page is therefore served
        the portal's frame, not refused by Sunrise."""
        self.client.force_login(User.objects.get(username="harbour.teacher"))
        response = self.client.get("/marking/", HTTP_HOST=FORWARDER, HTTP_X_FORWARDED_HOST=SUNRISE)

        self.assertEqual(response.status_code, 200)


class TheSettingFollowsTheFlagTests(SimpleTestCase):
    """`settings.py` in its own process, so the derivation is what is tested."""

    def setting(self, env):
        result = subprocess.run(
            [sys.executable, "-c", "import json, settings; print(json.dumps(settings.USE_X_FORWARDED_HOST))"],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_production_never_trusts_the_header(self):
        self.assertIs(self.setting(production_environment()), False)

    def test_development_without_the_flag_does_not(self):
        env = production_environment()
        env["DJANGO_DEBUG"] = "1"
        self.assertIs(self.setting(env), False)

    def test_the_single_host_demo_does(self):
        env = production_environment()
        env.update(DJANGO_DEBUG="1", DEMO_SINGLE_HOST="1")
        self.assertIs(self.setting(env), True)
