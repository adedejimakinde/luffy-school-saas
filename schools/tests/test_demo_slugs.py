"""Demo school names cannot be created or exist on a server that holds real schools.

`schools/demo_slugs.py` says why there are two locks. Each is shown here on its
own, with two schools in every case (a real one beside a demo one, or two demo
ones), because a guard that looks at "the" school is a guard that cannot tell
which of two it refused.

A test run has `DEBUG` off and no `DEMO_SERVER`, which is exactly a production
server, so the tests that expect a refusal need nothing set. The ones that
expect an allowance switch it on explicitly.
"""

import importlib
import logging
import os
import sys
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, connection
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User
from schools import demo_slugs, showcase
from schools.demo_slugs import (
    DEMO_SLUGS,
    DemoSchoolRefused,
    demo_schools_present,
    is_demo_name,
    refuse_if_demo_schools_exist,
)
from schools.management.commands import seed_demo
from schools.models import Domain, School
from schools.onboarding import OnboardingError, create_school

PLATFORM = dict(
    PLATFORM_DOMAIN="classnode.test",
    PORTAL_HOST="app.classnode.test",
    INVITATION_CHANNEL="schools.tests.test_invitations.RecordingChannel",
    INVITATION_ACCEPT_URL="https://app.classnode.test/invitations/{token}/",
)


def row(slug, schema_name=None):
    """A school row with no schema behind it: the guard asks about names, not DDL."""
    school = School(name=slug.title(), slug=slug, schema_name=schema_name or slug.replace("-", "_"))
    school.auto_create_schema = False
    return school


def in_production(extra=None):
    """The environment of a server that is neither a developer's nor the demo's."""
    env = {key: value for key, value in os.environ.items() if key != "DEMO_SERVER"}
    return mock.patch.dict(os.environ, env | (extra or {}), clear=True)


class WhatIsADemoNameTests(SimpleTestCase):
    def test_the_names_the_demo_tooling_makes_are_all_demo_names(self):
        made = {slug for slug, _ in seed_demo.SCHOOLS} | {showcase.SLUG}
        self.assertEqual(made - DEMO_SLUGS, set(), "a demo school the guard has not heard of")
        for slug in DEMO_SLUGS:
            with self.subTest(slug=slug):
                self.assertTrue(is_demo_name(slug))
                self.assertTrue(is_demo_name(slug.replace("-", "_")), "the schema name too")

    def test_any_other_name_of_the_same_shape_is(self):
        for name in ("demo", "Demo", "crestfield-demo", "demo-secondary", "st_marys_demo", " harbour-demo "):
            with self.subTest(name=name):
                self.assertTrue(is_demo_name(name))

    def test_a_real_school_is_not(self):
        for name in ("stmarys", "sunrise", "harbour", "demolition-academy", "democrat-high", "demos", "", None, "public"):
            with self.subTest(name=name):
                self.assertFalse(is_demo_name(name))


class CreatingOneTests(TestCase):
    """The first lock: `School.save()` and `create_school()`."""

    def tearDown(self):
        connection.set_schema_to_public()

    def test_two_demo_schools_are_refused_and_a_real_one_beside_them_is_not(self):
        with in_production():
            real = row("stmarys")
            real.save()
            for slug in ("sunrise-demo", "harbour-demo"):
                with self.subTest(slug=slug):
                    with self.assertRaisesMessage(DemoSchoolRefused, f"{slug!r} is a demo school's name"):
                        row(slug).save()

        self.assertEqual(list(School.objects.values_list("slug", flat=True)), ["stmarys"])

    def test_the_showcase_is_refused_too(self):
        with in_production():
            with self.assertRaises(DemoSchoolRefused):
                row(showcase.SLUG).save()
        self.assertFalse(School.objects.filter(slug=showcase.SLUG).exists())

    def test_the_error_says_what_to_do(self):
        with in_production():
            with self.assertRaises(DemoSchoolRefused) as caught:
                row("sunrise-demo").save()
        message = str(caught.exception)
        for part in ("DJANGO_DEBUG=1", "DEMO_SERVER=1", "nothing was created", "Choose another name"):
            self.assertIn(part, message)

    def test_a_demo_schema_name_under_an_innocent_slug_is_refused(self):
        with in_production():
            with self.assertRaises(DemoSchoolRefused):
                row("harbour", schema_name="harbour_demo").save()
            row("sunrise", schema_name="sunrise").save()  # the other school is fine
        self.assertEqual(list(School.objects.values_list("slug", flat=True)), ["sunrise"])

    def test_renaming_a_real_school_to_a_demo_name_is_refused(self):
        with in_production():
            school = row("stmarys")
            school.save()
            school.slug = "stmarys-demo"
            with self.assertRaises(DemoSchoolRefused):
                school.save()
        self.assertEqual(School.objects.get(pk=school.pk).slug, "stmarys")

    @override_settings(DEBUG=True)
    def test_a_development_machine_may_make_two(self):
        with in_production():
            row("sunrise-demo").save()
            row("harbour-demo").save()
        self.assertEqual(School.objects.filter(slug__in=("sunrise-demo", "harbour-demo")).count(), 2)

    def test_the_demo_server_may_make_two(self):
        with in_production({"DEMO_SERVER": "1"}):
            row("sunrise-demo").save()
            row("harbour-demo").save()
        self.assertEqual(School.objects.filter(slug__in=("sunrise-demo", "harbour-demo")).count(), 2)

    def test_only_the_value_one_counts_as_the_demo_server(self):
        for value in ("0", "", "true", "yes", "2"):
            with self.subTest(value=value):
                with in_production({"DEMO_SERVER": value}):
                    with self.assertRaises(DemoSchoolRefused):
                        row("sunrise-demo").save()
        self.assertFalse(School.objects.exists())


@override_settings(**PLATFORM)
class CreatingOneByTheOperatorTests(TestCase):
    """`create_school()` says so in the operator's words, before it writes anything."""

    def setUp(self):
        self.operator = User.objects.create_superuser("ops", "a-long-password", full_name="Ops")

    def tearDown(self):
        connection.set_schema_to_public()

    def test_two_demo_names_are_refused_before_anything_is_written(self):
        with in_production():
            for slug in ("sunrise-demo", "showcase-demo", "anything-demo"):
                with self.subTest(slug=slug):
                    with self.assertRaises(OnboardingError) as caught:
                        create_school(
                            slug=slug, name="A School", operator=self.operator, admin_email="head@school.example"
                        )
                    self.assertIn("is a demo school's name", str(caught.exception))
                    self.assertIn("nothing was created", str(caught.exception))

        self.assertFalse(School.objects.exists())
        self.assertFalse(Domain.objects.exists())

    def test_the_management_command_reports_it_as_an_error_not_a_traceback(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with in_production():
            with self.assertRaisesMessage(CommandError, "is a demo school's name"):
                call_command(
                    "create_school", "harbour-demo", "Harbour", "--admin-email", "a@b.example",
                    "--operator", self.operator.username,
                )
        self.assertFalse(School.objects.exists())


class HavingOneTests(TestCase):
    """The second lock: a server that holds one does not start."""

    def setUp(self):
        # Written the way the first lock cannot stop: `bulk_create()` skips `save()`, as
        # a restore from a demo server's backup or a row typed in psql would.
        School.objects.bulk_create(
            [
                School(name="St Mary's", slug="stmarys", schema_name="stmarys"),
                School(name="Sunrise Demo", slug="sunrise-demo", schema_name="sunrise_demo"),
                School(name="Grace Academy", slug="grace", schema_name="grace"),
            ]
        )

    def tearDown(self):
        connection.set_schema_to_public()

    def test_it_refuses_and_names_the_demo_school_and_not_the_real_ones(self):
        with in_production():
            with self.assertRaises(ImproperlyConfigured) as caught:
                refuse_if_demo_schools_exist()
        message = str(caught.exception)
        self.assertIn("Refusing to start", message)
        self.assertIn("sunrise-demo", message)
        self.assertNotIn("stmarys", message)
        self.assertNotIn("grace", message)
        self.assertIn("DEMO_SERVER=1", message)

    def test_it_names_every_demo_school_it_finds(self):
        School.objects.bulk_create([School(name="Harbour", slug="harbour-demo", schema_name="harbour_demo")])
        with in_production():
            with self.assertRaisesMessage(ImproperlyConfigured, "harbour-demo, sunrise-demo"):
                refuse_if_demo_schools_exist()

    def test_a_schema_name_alone_is_enough(self):
        School.objects.filter(slug="sunrise-demo").delete()
        School.objects.bulk_create([School(name="Odd", slug="odd", schema_name="odd_demo")])
        with in_production():
            with self.assertRaisesMessage(ImproperlyConfigured, "odd"):
                refuse_if_demo_schools_exist()

    def test_two_real_schools_start(self):
        School.objects.filter(slug="sunrise-demo").delete()
        self.assertEqual(demo_schools_present(), [])
        with in_production():
            refuse_if_demo_schools_exist()

    @override_settings(DEBUG=True)
    def test_a_development_machine_starts_with_one(self):
        with in_production():
            refuse_if_demo_schools_exist()

    def test_the_demo_server_starts_with_one(self):
        with in_production({"DEMO_SERVER": "1"}):
            refuse_if_demo_schools_exist()

    def test_wsgi_asks_the_question_as_it_loads(self):
        """The wiring, not the function: `import wsgi` is what gunicorn does."""
        sys.modules.pop("wsgi", None)
        try:
            with in_production():
                with self.assertRaisesMessage(ImproperlyConfigured, "Refusing to start"):
                    importlib.import_module("wsgi")
            self.assertNotIn("wsgi", sys.modules, "a failed import leaves no module behind")

            School.objects.filter(slug="sunrise-demo").delete()
            with in_production():
                loaded = importlib.import_module("wsgi")
            self.assertTrue(callable(loaded.application))
        finally:
            sys.modules.pop("wsgi", None)

    def test_a_database_it_cannot_reach_does_not_stop_it_and_says_so(self):
        with in_production():
            with mock.patch.object(demo_slugs, "demo_schools_present", side_effect=OperationalError("down")):
                with self.assertLogs(demo_slugs.logger, level=logging.WARNING) as logged:
                    refuse_if_demo_schools_exist()
        self.assertIn("starting anyway", logged.output[0])
