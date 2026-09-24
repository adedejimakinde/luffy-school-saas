"""What an error report may carry off the server.

Sentry (EU) with personal data off, decided 2026-09-23. The options are checked
as `settings.py` really sets them — in a subprocess under the production
environment with a DSN, the way `tests/test_deployment.py` checks the rest —
and the two hooks in `schools/errors.py` are checked on events shaped like the
ones sentry-sdk builds.
"""

import json
import subprocess
import sys

from django.db import connection
from django.test import SimpleTestCase, TestCase

from schools.errors import before_breadcrumb, before_send
from schools.tests.tenants import connected_to, make_school
from tests.test_deployment import BASE_DIR, production_environment

TOKEN = "Zq3-SECRET_token_value_x9"


def event_for(url, **extra):
    return {
        "request": {
            "url": url,
            "method": "POST",
            "data": {"password": "correct-horse-battery", "full_name": "Kemi Bello"},
            "cookies": {"sessionid": "abc123"},
            "query_string": "token=" + TOKEN,
            "env": {"REMOTE_ADDR": "203.0.113.7"},
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Cookie": "sessionid=abc123",
                "Authorization": "Bearer x",
                "X-Forwarded-For": "203.0.113.7",
            },
        },
        **extra,
    }


class TheHooksTests(SimpleTestCase):
    def test_an_invitation_token_is_scrubbed_from_every_url_in_a_report(self):
        """The accept address makes whoever holds it a school's new member.

        CONTROL 10: `scrub_url()` returning its input unchanged makes this red.
        """
        event = before_send(
            event_for(
                f"https://app.example.test/api/invitations/{TOKEN}/accept/",
                transaction=f"/invitations/{TOKEN}/",
            ),
            {},
        )
        crumb = before_breadcrumb(
            {"category": "httplib", "data": {"url": f"https://app.example.test/invitations/{TOKEN}/"}}, {}
        )

        self.assertNotIn(TOKEN, json.dumps(event))
        self.assertNotIn(TOKEN, json.dumps(crumb))
        self.assertEqual(event["request"]["url"], "https://app.example.test/api/invitations/[token]/accept/")
        self.assertEqual(event["transaction"], "/invitations/[token]/")

    def test_bodies_cookies_query_strings_and_addresses_never_leave(self):
        event = before_send(event_for("https://stmarys.example.test/api/enrolment/roll/"), {})

        request = event["request"]
        for key in ("data", "cookies", "query_string", "env"):
            with self.subTest(dropped=key):
                self.assertNotIn(key, request)
        self.assertEqual(request["headers"], {"User-Agent": "Mozilla/5.0"})
        for leaked in ("Kemi Bello", "correct-horse", "abc123", "203.0.113.7"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, json.dumps(event))

    def test_sql_breadcrumbs_are_dropped(self):
        """A query's parameters are children's names, marks and numbers."""
        crumb = {"category": "query", "message": "SELECT … WHERE full_name = 'Kemi Bello'"}

        self.assertIsNone(before_breadcrumb(crumb, {}))


class EveryReportNamesTheSchoolTests(TestCase):
    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def test_the_school_the_connection_is_on_is_a_tag(self):
        school = make_school("St Mary's", "st-marys", "st_marys")

        with connected_to(school):
            event = before_send({"message": "boom"}, {})

        self.assertEqual(event["tags"]["school"], "St Mary's")


def client_options(**env):
    code = (
        "import json, settings, sentry_sdk; c = sentry_sdk.get_client(); "
        "o = c.options; print(json.dumps({'active': c.is_active(), "
        "'send_default_pii': o.get('send_default_pii'), "
        "'include_local_variables': o.get('include_local_variables'), "
        "'max_request_body_size': o.get('max_request_body_size'), "
        "'traces_sample_rate': o.get('traces_sample_rate'), "
        "'before_send': o.get('before_send') is not None, "
        "'before_breadcrumb': o.get('before_breadcrumb') is not None}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BASE_DIR,
        env={**production_environment(), **env},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


class TheOptionsTests(SimpleTestCase):
    def test_with_a_dsn_personal_data_is_off(self):
        options = client_options(SENTRY_DSN="https://public@o0.ingest.de.sentry.io/0")

        self.assertTrue(options["active"])
        self.assertIs(options["send_default_pii"], False)
        self.assertIs(options["include_local_variables"], False)
        self.assertEqual(options["max_request_body_size"], "never")
        self.assertEqual(options["traces_sample_rate"], 0.0)
        self.assertTrue(options["before_send"])
        self.assertTrue(options["before_breadcrumb"])

    def test_without_a_dsn_nothing_is_reported_anywhere(self):
        self.assertFalse(client_options()["active"])
