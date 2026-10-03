"""The development-only single-host demo (`settings.DEMO_SINGLE_HOST`).

A Codespace forwards one port, so one hostname. With the flag on **and** `DEBUG`
on, a school's own host answers the two sign-in pages and the sign-in API as
well as the portal. Three things are pinned, each with its control:

1. Off (the default) a school's host serves none of it: the portal-only rule
   of `urls_public.py` and `api._portal_only()` is exactly as before.
2. On, it works, school by school: a login made on one school's host reaches
   that school and not the other's (two schools throughout).
3. **It cannot be had with `DEBUG` off.** Production settings refuse to start
   with the flag, in a separate process, under `deploy/production.env`; and
   with the flag forced on but `DEBUG` off the routes are still 404.
"""

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
SUNRISE = "sunrise.testserver"
HARBOUR = "harbour.testserver"
PASSWORD = "correct-horse-battery"

DOORS = ("/sign-in/", "/staff-sign-in/")
DEMO = dict(DEBUG=True, DEMO_SINGLE_HOST=True)


class SingleHostSetUp(TestCase):
    def setUp(self):
        portal = make_school("Portal", "portal", "public")
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)
        self.sunrise = make_school("Sunrise", "sunrise", "sunrise")
        Domain.objects.create(tenant=self.sunrise, domain=SUNRISE, is_primary=True)
        self.harbour = make_school("Harbour", "harbour", "harbour")
        Domain.objects.create(tenant=self.harbour, domain=HARBOUR, is_primary=True)

        self.ada = User.objects.create_user("sunrise.teacher", PASSWORD, full_name="Ada")
        grant_membership(self.ada, self.sunrise, Role.TEACHER)
        self.tunde = User.objects.create_user("harbour.teacher", PASSWORD, full_name="Tunde")
        grant_membership(self.tunde, self.harbour, Role.TEACHER)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def sign_in(self, host, username):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/csrf/", HTTP_HOST=host).json()["csrf_token"]
        response = client.post(
            "/api/login/",
            data={"identifier": username, "password": PASSWORD},
            content_type="application/json",
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=token,
        )
        return client, response


class WithTheFlagOffAFixedHostServesNoDoorTests(SingleHostSetUp):
    def test_no_door_page_on_either_school(self):
        for host in (SUNRISE, HARBOUR):
            for url in DOORS:
                with self.subTest(host=host, url=url):
                    self.assertEqual(self.client.get(url, HTTP_HOST=host).status_code, 404)

    def test_the_login_api_is_a_404_on_a_school_host(self):
        _, response = self.sign_in(SUNRISE, "sunrise.teacher")
        self.assertEqual(response.status_code, 404)

    def test_the_flag_alone_with_debug_off_changes_nothing(self):
        """The second lock: settings refuse this combination at start-up, and
        `schools.demo.single_host()` refuses it again per request."""
        with override_settings(DEBUG=False, DEMO_SINGLE_HOST=True):
            for url in DOORS:
                with self.subTest(url=url):
                    self.assertEqual(self.client.get(url, HTTP_HOST=SUNRISE).status_code, 404)
            _, response = self.sign_in(SUNRISE, "sunrise.teacher")
            self.assertEqual(response.status_code, 404)


@override_settings(**DEMO)
class WithTheFlagOnASchoolHostAnswersTheDoorsTests(SingleHostSetUp):
    def test_both_pages_answer_on_each_school_host(self):
        for host in (SUNRISE, HARBOUR):
            for url in DOORS:
                with self.subTest(host=host, url=url):
                    response = self.client.get(url, HTTP_HOST=host)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("text/html", response["Content-Type"])

    def test_the_portal_still_serves_its_own(self):
        for url in DOORS:
            self.assertEqual(self.client.get(url, HTTP_HOST=PORTAL).status_code, 200)

    def test_a_teacher_signs_in_on_their_own_schools_host(self):
        client, response = self.sign_in(SUNRISE, "sunrise.teacher")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["slug"] for s in response.json()["schools"]], ["sunrise"])
        # ...and the session works there.
        self.assertEqual(client.get("/marking/", HTTP_HOST=SUNRISE).status_code, 200)

    def test_a_login_on_one_schools_host_does_not_open_the_other(self):
        """Two schools: Ada signs in on Sunrise's host and Harbour's host
        refuses her, as it does today."""
        client, _ = self.sign_in(SUNRISE, "sunrise.teacher")

        response = client.get("/marking/", HTTP_HOST=HARBOUR)
        self.assertEqual(response.status_code, 403)

    def test_only_the_doors_are_opened(self):
        """The platform screen's API stays portal only in the demo mode."""
        client, _ = self.sign_in(SUNRISE, "sunrise.teacher")

        response = client.get("/api/platform/schools/", HTTP_HOST=SUNRISE)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/platform/", HTTP_HOST=SUNRISE).status_code, 404)
        self.assertEqual(self.client.get("/admin/", HTTP_HOST=SUNRISE).status_code, 404)


class ProductionSettingsRefuseTheFlagTests(SimpleTestCase):
    """`settings.py` imported in its own process under `deploy/production.env`."""

    def import_settings(self, **extra):
        env = production_environment()
        env.update(extra)
        return subprocess.run(
            [sys.executable, "-c", "import settings; print(settings.DEMO_SINGLE_HOST)"],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_production_refuses_to_start_with_it(self):
        result = self.import_settings(DEMO_SINGLE_HOST="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("DEMO_SINGLE_HOST", result.stderr)

    def test_production_without_it_starts_and_has_it_off(self):
        """The control: the same environment minus the flag imports fine, so
        the refusal above is the flag's and not something else's."""
        result = self.import_settings()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "False")

    def test_it_is_only_ever_on_with_debug(self):
        result = self.import_settings(DEMO_SINGLE_HOST="1", DJANGO_DEBUG="1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "True")
