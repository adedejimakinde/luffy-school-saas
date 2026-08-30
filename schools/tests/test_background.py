"""Proof that the background half of this platform is wired to the right things.

Three dependencies arrive together — Celery, Redis and WeasyPrint — and each of
them fails in a way that a test asserting "it is in requirements.txt" would sail
straight past:

- a task sent to the **wrong broker** is not an error at the call site. The
  default Celery app takes the message, connects to an AMQP server that is not
  there, and the job is gone. `CurrentAppTests` runs the control that shows it.
- a task run on the **wrong schema** is not an error either, for the half of the
  tables that are shared. `TenantTaskTests` writes into two schools and reads
  back from both.
- WeasyPrint **installs** without Pango and only fails when something first
  imports it, which on this project would be a principal pressing a button.
  `WeasyPrintEnvironmentTests` renders a real PDF here instead.

Everything except the broker connection is proven without a running Redis, so
these tests are part of the ordinary suite. The one that needs a live broker
skips with a message naming what is missing — CI has one (see
.github/workflows/tests.yml) and so does docker-compose.
"""

import os
import subprocess
import sys
from datetime import date

from celery import current_app, shared_task
from django.conf import settings
from django.db import connection
from django.test import TestCase

from academics.models import Term, TermName
from schools.tasks import TenantTask, UnknownSchool, school_for
from schools.tests.test_tenant_isolation import connected_to, make_school

import celery_app


# --------------------------------------------------------------------------
# The two tasks under test. Declared at module level because that is where a
# task is declared everywhere else: `@shared_task` binds to whichever Celery
# app is current at import time, which is the property CurrentAppTests is about.
# --------------------------------------------------------------------------


@shared_task(base=TenantTask)
def record_a_term(schema_name, session):
    """Write one tenant-table row, and report where it landed."""
    Term.objects.create(
        session=session,
        name=TermName.FIRST,
        starts_on=date(2025, 9, 15),
        ends_on=date(2025, 12, 12),
    )
    return connection.schema_name


@shared_task
def report_the_schema():
    """A task with no base, to show what the base is actually doing."""
    return connection.schema_name


class RootModuleShadowingTests(TestCase):
    """No file at the repository root may shadow a dependency's top-level name.

    `celery_app.py` explains the specific case at length: this project keeps
    `settings.py` and `manage.py` at the repository root, so the root is on
    `sys.path`, and a `celery.py` beside them would be imported *as* `celery` by
    every process started here. The same trap is open for `redis.py` and
    `weasyprint.py`, and it is worth one cheap test rather than an afternoon of
    reading an import error that says a module has no attribute it obviously has.
    """

    def test_the_dependencies_are_imported_from_site_packages(self):
        import celery
        import redis
        import weasyprint

        root = str(settings.BASE_DIR)
        for module in (celery, redis, weasyprint):
            with self.subTest(module=module.__name__):
                self.assertFalse(
                    str(module.__file__).startswith(root + os.sep),
                    f"{module.__name__} was imported from {module.__file__}, "
                    "inside the repository root — a module there is shadowing "
                    "the installed package. Rename it (see celery_app.py).",
                )


class CeleryConfigurationTests(TestCase):
    """The settings a deployment can get wrong, read back off the live app."""

    def test_the_app_reads_its_configuration_from_django_settings(self):
        self.assertEqual(celery_app.app.conf.broker_url, settings.CELERY_BROKER_URL)

    def test_the_broker_is_redis_and_not_celerys_default(self):
        self.assertTrue(
            celery_app.app.conf.broker_url.startswith("redis://"),
            celery_app.app.conf.broker_url,
        )

    def test_there_is_no_result_backend(self):
        """Off on purpose — settings.py says why. Pinned so it stays a decision."""
        self.assertIsNone(celery_app.app.conf.result_backend)

    def test_a_pickled_message_would_not_be_accepted(self):
        """The worker can reach every school's schema. It eats JSON only."""
        self.assertEqual(celery_app.app.conf.accept_content, ["json"])
        self.assertNotIn("pickle", celery_app.app.conf.accept_content)

    def test_a_job_is_acknowledged_when_it_finishes_not_when_it_starts(self):
        self.assertTrue(celery_app.app.conf.task_acks_late)
        self.assertEqual(celery_app.app.conf.worker_prefetch_multiplier, 1)


class CurrentAppTests(TestCase):
    """`.delay()` from a web process must reach the same queue the worker reads.

    The mechanism is `schools.apps.SchoolsConfig.ready()` importing `celery_app`,
    and it is invisible from inside a process that has already done so — this
    test process included. So both halves run in a subprocess, and the control
    is the interesting one: with Django not set up, the current app's effective
    broker is an AMQP server that this platform does not run and never has.
    """

    def run_python(self, source, without=()):
        environment = {k: v for k, v in os.environ.items() if k not in without}
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=str(settings.BASE_DIR),
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_django_startup_makes_the_projects_app_current(self):
        broker = self.run_python(
            "import django; django.setup()\n"
            "from celery import current_app\n"
            "print(current_app.connection().as_uri())\n"
        )
        self.assertEqual(broker, settings.CELERY_BROKER_URL)

    def test_control_without_django_the_process_runs_none_of_this_configuration(self):
        """The default app is a different app, and it is nobody's intended one.

        Asserted on the settings an environment variable cannot reach, because
        the broker URL turns out to be reachable by one — see the test below.
        Everything this project chose deliberately is absent here: jobs would be
        acknowledged on pickup rather than on completion, and a worker would
        reserve four of them at a time.
        """
        main, acks_late, prefetch = self.run_python(
            "from celery import current_app\n"
            "print(current_app.main)\n"
            "print(current_app.conf.task_acks_late)\n"
            "print(current_app.conf.worker_prefetch_multiplier)\n"
        ).splitlines()

        self.assertEqual(main, "default")
        self.assertEqual(acks_late, "False")
        self.assertEqual(prefetch, "4")
        self.assertTrue(celery_app.app.conf.task_acks_late)
        self.assertEqual(celery_app.app.conf.worker_prefetch_multiplier, 1)

    def test_control_an_unconfigured_celery_sends_to_a_broker_nobody_runs(self):
        """`.delay()` with no app: an AMQP server on localhost that does not exist.

        `CELERY_BROKER_URL` is dropped from the subprocess environment on
        purpose, and that is worth knowing rather than working around: Celery
        honours a variable of that name **without any Django involved**, so a
        deployment that exports it would find its jobs reaching Redis while
        running none of the configuration above. The variable can hide this
        failure; it cannot fix it.
        """
        broker = self.run_python(
            "from celery import current_app\n"
            "print(current_app.connection().as_uri())\n",
            without=["CELERY_BROKER_URL"],
        )

        self.assertTrue(broker.startswith("amqp://"), broker)
        self.assertNotEqual(broker, settings.CELERY_BROKER_URL)

    def test_a_shared_task_is_registered_on_the_projects_app(self):
        """`@shared_task` above bound to our app, not to a default one."""
        self.assertIn(record_a_term.name, celery_app.app.tasks)
        self.assertEqual(current_app.main, "luffy")


class TenantTaskTests(TestCase):
    """A task runs in the school it was given, and refuses one it was not.

    Two real schools, both used. The second is not scenery: the assertion that
    matters is that St Mary's term is *absent* from Grace Academy, which one
    school cannot make.
    """

    def setUp(self):
        self.st_marys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

    def terms_in(self, school):
        with connected_to(school):
            return list(Term.objects.values_list("session", flat=True))

    def test_the_row_lands_in_the_school_the_task_was_given(self):
        record_a_term.apply(args=["st_marys", "2025/2026"]).get()

        self.assertEqual(self.terms_in(self.st_marys), ["2025/2026"])
        self.assertEqual(self.terms_in(self.grace), [])

    def test_two_schools_two_schemas_one_task(self):
        record_a_term.apply(args=["st_marys", "2025/2026"]).get()
        record_a_term.apply(args=["grace", "2024/2025"]).get()

        self.assertEqual(self.terms_in(self.st_marys), ["2025/2026"])
        self.assertEqual(self.terms_in(self.grace), ["2024/2025"])

    def test_the_body_runs_with_the_schools_search_path_set(self):
        landed = record_a_term.apply(args=["grace", "2024/2025"]).get()
        self.assertEqual(landed, "grace")

    def test_the_schema_name_may_be_a_keyword_argument(self):
        landed = record_a_term.apply(
            kwargs={"schema_name": "grace", "session": "2024/2025"}
        ).get()
        self.assertEqual(landed, "grace")
        self.assertEqual(self.terms_in(self.grace), ["2024/2025"])

    def test_the_connection_is_left_where_it_was_found(self):
        """A worker reuses its connection between jobs. This one puts it back."""
        before = connection.schema_name
        record_a_term.apply(args=["st_marys", "2025/2026"]).get()
        self.assertEqual(connection.schema_name, before)

    def test_an_unknown_schema_is_refused_before_the_body_runs(self):
        with self.assertRaises(UnknownSchool):
            record_a_term.apply(args=["not_a_school", "2025/2026"]).get()

        self.assertEqual(self.terms_in(self.st_marys), [])
        self.assertEqual(self.terms_in(self.grace), [])

    def test_the_portal_is_not_a_school_a_task_can_be_pointed_at(self):
        """`public` has no School row, so a school task cannot land there."""
        with self.assertRaises(UnknownSchool):
            school_for("public")

    def test_a_task_called_with_no_arguments_says_what_is_missing(self):
        with self.assertRaises(TypeError):
            record_a_term.apply(args=[]).get()

    def test_control_a_task_without_the_base_runs_on_public(self):
        """What every task would do if `TenantTask` were doing nothing.

        Public is where a worker's connection starts, and it is not empty — every
        shared table is there. This is the failure the base class exists to make
        impossible, and without this control the tests above would pass just as
        happily if `TenantTask.__call__` were removed and the schema happened to
        be right already.
        """
        self.assertEqual(report_the_schema.apply().get(), "public")


class BrokerConnectivityTests(TestCase):
    """The one claim configuration cannot make: that the URL reaches a Redis.

    Skipped where no broker is running, which is a developer's machine before
    `docker compose up`. CI runs a Redis service precisely so this does not skip
    there — a broker that nothing can connect to is the failure mode with no
    other symptom.
    """

    def test_the_configured_broker_accepts_a_connection(self):
        from kombu import Connection
        from kombu.exceptions import OperationalError

        try:
            with Connection(settings.CELERY_BROKER_URL, connect_timeout=2) as conn:
                conn.ensure_connection(max_retries=0, timeout=2)
                self.assertTrue(conn.connected)
        except (OperationalError, OSError) as exc:
            self.skipTest(
                f"No broker at {settings.CELERY_BROKER_URL}: {exc}. Start one "
                "(docker compose up redis) or set CELERY_BROKER_URL."
            )


class WeasyPrintEnvironmentTests(TestCase):
    """Pango, HarfBuzz and a font are present, proven by producing a PDF.

    This is an assertion about the *environment*, not about this project's code,
    and that is the point: WeasyPrint's wheel installs on a machine with none of
    them and raises only at import. The two places that build an environment for
    this project — .devcontainer/Dockerfile and the CI workflow — install the
    libraries, and this is what would notice if either stopped.
    """

    HTML = "<html><body><h1>Report card</h1><p>Grace Academy</p></body></html>"

    def test_a_pdf_comes_out(self):
        import weasyprint

        pdf = weasyprint.HTML(string=self.HTML).write_pdf()
        self.assertTrue(pdf.startswith(b"%PDF"), pdf[:16])

    def test_a_real_font_was_found_and_embedded(self):
        """Pango with no font family renders boxes and still returns a PDF.

        So "bytes came back" is not enough to know the container has fonts. An
        embedded font program is: `/FontFile*` only appears when a face was
        actually resolved and subset into the file. Read uncompressed because
        WeasyPrint compresses object streams by default.
        """
        import weasyprint

        pdf = weasyprint.HTML(string=self.HTML).write_pdf(uncompressed_pdf=True)
        self.assertIn(b"/FontFile", pdf)
