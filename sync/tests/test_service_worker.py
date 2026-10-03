"""The offline worker, `/sw.js`: the same for everybody, and complete.

`docs/offline.md` slice S5, D10 and D8. Three claims, each tested at two
schools, because the failure each guards against is a worker that knows
something about one of them.

**It holds nobody's data.** The script is the same bytes at St Mary's, at
Grace, on the portal, for a teacher and for a caller with no session. A worker
rendered from the request, with a school's name or a user's id in it, would
hand one phone's knowledge to whichever host asked next.

**It keeps what the pages load, and nothing from the API.** The list of files
is derived from the two pages' own module lists, so a module added to either is
kept without anybody remembering to. `/api/` is not in it: what the server said
about a sheet is the page's to keep, under a person's name.

**The pages it keeps are real.** Each path it lists answers 200 at both schools.

The worker's behaviour is in `tests/js/service_worker.test.js`, which runs the
script against a fake cache.
"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.templatetags.static import static

from attendance.views import REGISTER_MODULES
from gradebook.tests.fixtures import MarkingSetUp
from gradebook.views import MARKING_MODULES
from schools.models import Domain, School

HOST = "st-marys.testserver"
GRACE_HOST = "grace.testserver"
PORTAL = "testserver"

WORKER = Path(settings.BASE_DIR) / "sync" / "worker.js"


def code_of(source):
    """The script without its comments, which say `/api/` in order to say it is not touched."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def config_of(body):
    """The `CONFIG` the view puts in front of the worker."""
    hit = re.match(r"const CONFIG = (\{.*?\n\});\n", body, re.S)
    assert hit, body[:200]
    return json.loads(hit.group(1))


class TheWorkerIsTheSameForEverybodyTests(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=GRACE_HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def fetch(self, host, user=None):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)
        return self.client.get("/sw.js", HTTP_HOST=host)

    def test_it_is_served_as_a_script_the_browser_will_check_each_time(self):
        response = self.fetch(HOST)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/javascript", response["Content-Type"])
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(response["Service-Worker-Allowed"], "/")

    def test_the_same_bytes_at_both_schools_the_portal_and_for_anyone(self):
        seen = {
            "st marys, signed out": self.fetch(HOST).content,
            "st marys, teacher": self.fetch(HOST, self.teacher.user).content,
            "grace, signed out": self.fetch(GRACE_HOST).content,
            "grace, its teacher": self.fetch(GRACE_HOST, self.grace_teacher.user).content,
            "portal": self.fetch(PORTAL).content,
        }

        self.assertEqual(len(set(seen.values())), 1, {k: len(v) for k, v in seen.items()})

    def test_no_school_person_or_id_is_in_it(self):
        body = self.fetch(HOST, self.teacher.user).content.decode()

        for absent in (
            "St Mary's",
            "Grace",
            self.teacher.user.full_name,
            self.grace_teacher.user.full_name,
            "Ada Obi",
            HOST,
            GRACE_HOST,
            "user_id",
            "userId",
        ):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, body)

    def test_it_sets_no_cookie(self):
        self.assertNotIn("Set-Cookie", self.fetch(HOST, self.teacher.user))


class TheWorkerKeepsWhatThePagesLoadTests(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=GRACE_HOST, is_primary=True)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def config(self):
        return config_of(self.client.get("/sw.js", HTTP_HOST=HOST).content.decode())

    def test_every_module_of_both_pages_is_in_the_shell(self):
        shell = set(self.config()["shell"])

        for module in (*MARKING_MODULES, *REGISTER_MODULES):
            with self.subTest(module=module):
                self.assertIn(static(module), shell)

    def test_the_stylesheets_and_fonts_the_pages_draw_with_are_in_it(self):
        shell = set(self.config()["shell"])

        for path in (
            "web/design.css",
            "marking/marking.css",
            "register/register.css",
            "web/fonts/hanken-grotesk-400.woff2",
            "web/fonts/hanken-grotesk-700.woff2",
        ):
            with self.subTest(path=path):
                self.assertIn(static(path), shell)

    def test_the_pages_it_keeps_answer_at_both_schools(self):
        for host in (HOST, GRACE_HOST):
            for path in self.config()["pages"]:
                with self.subTest(host=host, path=path):
                    self.assertEqual(self.client.get(path, HTTP_HOST=host).status_code, 200)

    def test_the_pages_are_the_marking_and_the_register_and_nothing_else(self):
        self.assertEqual(self.config()["pages"], ["/marking/", "/register/"])

    def test_nothing_from_the_api_is_kept_or_even_named(self):
        """The copies of what the server said are the pages', under a person's
        name. A worker that kept an API answer would keep it under nobody's."""
        config = self.config()
        source = code_of(WORKER.read_text())

        self.assertFalse([url for url in config["shell"] if "/api/" in url])
        self.assertNotIn("/api/", source)
        self.assertNotIn("api", config["static"])

    def test_the_version_changes_when_the_shell_does(self):
        """A new deploy hashes new names, and the worker must notice: its cache
        is named by this, and an old one is deleted when it activates."""
        from unittest import mock

        from sync import views

        first = self.config()["version"]
        with mock.patch.object(views, "STYLES", (*views.STYLES, "register/register.css.extra")):
            with mock.patch.object(views, "static", lambda path: "/static/" + path):
                changed = views.config()["version"]

        self.assertNotEqual(first, changed)
