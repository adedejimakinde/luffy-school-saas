"""`/api/attendance/where/` names the caller, so the page can keep a copy of
what it was shown under that person's name (`docs/offline.md` D8).

At two schools: the id is the caller's own at each, and never anybody else's.
"""

import json

from django.db import connection

from gradebook.tests.fixtures import MarkingSetUp
from schools.models import Domain

HOST = "st-marys.testserver"
GRACE_HOST = "grace.testserver"


class TheCallerIsNamedTests(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=GRACE_HOST, is_primary=True)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def test_it_is_the_signed_in_users_own_id(self):
        self.client.force_login(self.teacher.user)

        body = self.client.get("/api/attendance/where/", HTTP_HOST=HOST).json()

        self.assertEqual(body["user_id"], self.teacher.user.pk)

    def test_the_same_teacher_at_two_schools_is_the_same_id_and_a_colleague_is_not(self):
        from accounts.models import Role
        from accounts.services import grant_membership

        grant_membership(self.teacher.user, self.grace, Role.TEACHER)
        self.client.force_login(self.teacher.user)

        here = self.client.get("/api/attendance/where/", HTTP_HOST=HOST).json()["user_id"]
        there = self.client.get("/api/attendance/where/", HTTP_HOST=GRACE_HOST).json()["user_id"]

        self.assertEqual(here, there)
        self.assertEqual(here, self.teacher.user.pk)
        self.assertNotEqual(here, self.bursar.user.pk)

    def test_it_is_their_own_name_on_both_screens_and_nobody_elses(self):
        """`docs/offline.md` D7: a shared phone says "held for Kemi"."""
        from accounts.models import Role
        from accounts.services import grant_membership

        grant_membership(self.teacher.user, self.grace, Role.TEACHER)
        self.client.force_login(self.teacher.user)

        for host in (HOST, GRACE_HOST):
            for url in ("/api/attendance/where/", "/api/gradebook/where/"):
                with self.subTest(host=host, url=url):
                    body = self.client.get(url, HTTP_HOST=host).json()
                    self.assertEqual(body["full_name"], self.teacher.user.full_name)

        other = self.grace_teacher
        self.client.force_login(other.user)
        body = self.client.get("/api/attendance/where/", HTTP_HOST=GRACE_HOST).json()
        self.assertEqual(body["full_name"], other.user.full_name)
        self.assertNotIn(self.teacher.user.full_name, json.dumps(body))
