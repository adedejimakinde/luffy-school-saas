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
import pathlib
import subprocess
import sys
from datetime import date

from celery import Task, current_app, shared_task
from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase

from academics.models import Term, TermName
from schools.tasks import (
    HANDLERS_CALLED_OUTSIDE_THE_BODY,
    TenantTask,
    UnknownSchool,
    school_for,
)
from schools.models import School
from schools.tests.test_tenant_isolation import make_school
from schools.tests.tenants import connected_to

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


#: Where each of `TenantTask`'s handlers found the connection, filled in by the
#: task below. A module-level dict because a handler has nowhere to return to.
HANDLER_SCHEMAS = {}


class RecordingHandlers:
    """The handler bodies, written the way a real subclass writes them.

    **The recording is the first line of each method, before any `super()`
    call, and that placement is the test.** It is where task 7's PDF job will
    put its "this render failed" write, and it is precisely what a base class
    that merely *overrode* these five could not reach: the tracer calls the most
    derived method, so the subclass's own body runs to completion before control
    ever arrives at the base. A version of this class that recorded *after*
    delegating upward would have passed against a guard that guarded nothing.

    Mixed in rather than written twice, so `RecordingTask` and the control below
    differ in exactly one thing — their base — and nothing else can explain a
    difference in what they record.
    """

    def before_start(self, task_id, args, kwargs):
        HANDLER_SCHEMAS["before_start"] = connection.schema_name
        super().before_start(task_id, args, kwargs)

    def on_success(self, retval, task_id, args, kwargs):
        HANDLER_SCHEMAS["on_success"] = connection.schema_name
        super().on_success(retval, task_id, args, kwargs)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        HANDLER_SCHEMAS["on_retry"] = connection.schema_name
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        HANDLER_SCHEMAS["on_failure"] = connection.schema_name
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        HANDLER_SCHEMAS["after_return"] = connection.schema_name
        super().after_return(status, retval, task_id, args, kwargs, einfo)


class RecordingTask(RecordingHandlers, TenantTask):
    """The shape task 7 needs: a job that records its own outcome."""


class RecordingPlainTask(RecordingHandlers, Task):
    """The control: the same handlers on Celery's own base, which does nothing.

    Its `run` takes a schema name and ignores it, exactly as the ones above do
    — so the *only* difference between this and `RecordingTask` is which base
    the handlers hang off. It records `public`, which is what every one of those
    handlers did before they were wrapped.
    """


@shared_task(base=RecordingTask)
def succeed_in_a_school(schema_name):
    return connection.schema_name


@shared_task(base=RecordingTask)
def fail_in_a_school(schema_name):
    raise RuntimeError("the render died")


@shared_task(base=RecordingPlainTask)
def succeed_without_the_base(schema_name):
    return connection.schema_name


class RootModuleShadowingTests(SimpleTestCase):
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

        # The parent directory, not `startswith` on the root. A shadowing
        # module can only be one sitting *directly* at the repository root,
        # because that is what is on `sys.path`. `startswith` also matches
        # everything *under* the root — including `.venv/lib/python3.11/
        # site-packages/celery/__init__.py`, which is where these packages live
        # for any developer who keeps their virtualenv inside the checkout, the
        # commonest Python layout there is and one nothing here forbids. That
        # spelling failed all three subTests with a message telling them to
        # rename a file that does not exist.
        root = pathlib.Path(settings.BASE_DIR).resolve()
        for module in (celery, redis, weasyprint):
            with self.subTest(module=module.__name__):
                self.assertNotEqual(
                    pathlib.Path(module.__file__).resolve().parent,
                    root,
                    f"{module.__name__} was imported from {module.__file__}, "
                    "a module at the repository root — which is on sys.path, so "
                    "it shadows the installed package. Rename it (see "
                    "celery_app.py).",
                )


class CeleryConfigurationTests(SimpleTestCase):
    """The settings a deployment can get wrong, read back off the live app.

    **None of these may assert on `broker_url` to prove the settings loaded**,
    and the reason is the wrinkle the PR that introduced this file documents:
    Celery reads `CELERY_BROKER_URL` straight from the environment, and that
    value *outranks* anything `config_from_object` supplies. `settings.py` reads
    the same variable. So in CI and in docker-compose — the two places these run
    in anger — `assertEqual(app.conf.broker_url, settings.CELERY_BROKER_URL)`
    compares the environment variable to itself, and stays green with
    `config_from_object` deleted outright. That is the precise failure the
    variable was said to hide, reproduced inside its own test.

    The assertions below are therefore on values **no environment variable
    reaches**, each of which differs from Celery's own default, so together they
    can only be true if this project's settings were actually applied.
    """

    def test_the_app_reads_its_configuration_from_django_settings(self):
        """Four non-default values, none of them reachable from the environment.

        Celery's defaults are `task_acks_late=False`,
        `worker_prefetch_multiplier=4` and `accept_content=['json', 'pickle',
        ...]`. Deleting `config_from_object` from `celery_app.py` turns this
        red, which is the property the broker-url comparison did not have.
        """
        conf = celery_app.app.conf
        self.assertTrue(conf.task_acks_late)
        self.assertEqual(conf.worker_prefetch_multiplier, 1)
        self.assertEqual(conf.accept_content, ["json"])
        self.assertEqual(conf.task_serializer, "json")

    def test_the_broker_is_redis_and_not_celerys_default(self):
        """That the URL is a Redis at all — which the environment may well be
        what supplies, and that is fine here: the claim is about where messages
        go, not about which layer routed them."""
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

    def test_a_worker_killed_mid_job_puts_the_job_back(self):
        """`acks_late` is only half of it, and the other half is a separate flag.

        A task whose child process is killed by a signal — an OOM kill, most
        deploy stops — is acknowledged by the worker even under `acks_late` and
        marked `WorkerLostError`, and the job is gone.
        `task_reject_on_worker_lost` is what returns it to the queue. Asserted
        beside `acks_late` because the guarantee the comment in `settings.py`
        states needs both, and asserting only the first is how that comment came
        to claim something it did not deliver.
        """
        self.assertTrue(celery_app.app.conf.task_reject_on_worker_lost)

    def test_a_returned_job_comes_back_in_minutes_rather_than_an_hour(self):
        """Redis has no unacked-delivery concept; kombu emulates one on a timer.

        Its default `visibility_timeout` is 3600s, so "another worker picks it
        up" would mean an hour for a parent waiting on a re-rendered card. The
        value must also stay above the longest task's runtime, or a task still
        running is redelivered alongside itself.
        """
        options = celery_app.app.conf.broker_transport_options
        self.assertEqual(options.get("visibility_timeout"), 300)


class CurrentAppTests(SimpleTestCase):
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
        """The mirror of the control below, asserted on the same three values.

        Not on the broker URL alone: `CELERY_BROKER_URL` is read by Celery
        itself, so the *default* app reaches the right Redis too wherever that
        variable is exported — which is CI and docker-compose. A URL comparison
        here would pass in exactly the deployments where it proves least, so it
        is checked alongside two values only `config_from_object` can supply.
        """
        broker, acks_late, prefetch = self.run_python(
            "import django; django.setup()\n"
            "from celery import current_app\n"
            "print(current_app.connection().as_uri())\n"
            "print(current_app.conf.task_acks_late)\n"
            "print(current_app.conf.worker_prefetch_multiplier)\n"
        ).splitlines()

        self.assertEqual(broker, settings.CELERY_BROKER_URL)
        self.assertEqual(acks_late, "True")
        self.assertEqual(prefetch, "1")

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
        """And **the portal row exists while this asserts it**, which is the point.

        The first version of this test asserted the same refusal without
        creating the row, and passed for a reason that had nothing to do with
        the code under test: `TenantTaskTests` happened to be the one class in
        this codebase that never builds a portal. `School(name="Portal",
        schema_name="public")` is created by `accounts.tests.test_login`,
        `test_session`, `test_admin_door` and `schools.tests.test_invitation_api`,
        and `results.services.school_on_this_connection()` documents at length
        why its existence is the whole hazard — where the row exists, a lookup
        for `"public"` *succeeds* and hands back the portal.

        So `school_for()` used to return `<School: Portal>` here, and a
        `TenantTask` pointed at `"public"` ran its body on the public schema,
        where `accounts_membership` and every other shared table is writable and
        no error is raised. That is the silent, platform-wide write the base
        class exists to prevent, reached through the guard rather than around
        it. The refusal is now a line of code; this is the row that proves it.
        """
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()

        with self.assertRaisesMessage(UnknownSchool, "is the portal, not a school"):
            school_for("public")

    def test_a_task_pointed_at_the_portal_writes_nothing_anywhere(self):
        """The refusal above, reached the way a real message would reach it."""
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()

        with self.assertRaises(UnknownSchool):
            record_a_term.apply(args=["public", "2025/2026"]).get()

        self.assertEqual(self.terms_in(self.st_marys), [])
        self.assertEqual(self.terms_in(self.grace), [])

    def test_a_task_called_with_no_arguments_says_what_is_missing(self):
        """`assertRaisesMessage`, because bare `TypeError` proves nothing here.

        Python raises `TypeError` for the missing positional parameters all by
        itself, so the loose version of this test passed with the guard in
        `schema_name_from()` deleted — it asserted the exception Python was
        going to raise anyway, under a name claiming it checked the message.
        """
        with self.assertRaisesMessage(TypeError, "needs the school's schema name"):
            record_a_term.apply(args=[]).get()

    def test_a_task_whose_schema_keyword_was_misspelled_is_told_what_arrived(self):
        """The common way to reach that refusal, and the one it used to misreport.

        An empty `.delay()` is rare. `delay(session=...)`, or a keyword whose
        name drifted, is not — and the old message told whoever was reading the
        worker log that the task "was called with no arguments at all", sending
        them to look for a call site that does not exist.
        """
        with self.assertRaisesMessage(TypeError, "session=..."):
            record_a_term.apply(kwargs={"session": "2025/2026"}).get()

    def test_the_handlers_run_in_the_school_too_not_only_the_body(self):
        """Celery calls these outside the body, and they used to run on `public`.

        `before_start` happens before the traced call and
        `on_success`/`after_return` after it — both outside the `with` block
        that `__call__` opens. A task recording its own outcome, which is what
        task 7's PDF job does, wrote to the wrong schema in both directions:
        loudly for a tenant table, silently for a shared one.
        """
        HANDLER_SCHEMAS.clear()
        succeed_in_a_school.apply(args=["st_marys"]).get()

        self.assertEqual(HANDLER_SCHEMAS.get("before_start"), "st_marys")
        self.assertEqual(HANDLER_SCHEMAS.get("on_success"), "st_marys")
        self.assertEqual(HANDLER_SCHEMAS.get("after_return"), "st_marys")

    def test_a_failure_handler_runs_in_the_school_that_failed(self):
        """The one that matters most: recording *that* a render failed."""
        HANDLER_SCHEMAS.clear()
        result = fail_in_a_school.apply(args=["grace"])

        self.assertTrue(result.failed())
        self.assertEqual(HANDLER_SCHEMAS.get("on_failure"), "grace")
        self.assertEqual(HANDLER_SCHEMAS.get("after_return"), "grace")

    def test_control_the_same_handlers_on_celerys_base_record_public(self):
        """The two tests above, minus the base class, with nothing else changed.

        `RecordingPlainTask` mixes in the identical handler bodies and takes the
        identical schema-name argument. Without this, both tests above would
        pass just as well against a `TenantTask` that did nothing at all in a
        suite that happened to run on `st_marys`.
        """
        HANDLER_SCHEMAS.clear()
        succeed_without_the_base.apply(args=["st_marys"]).get()

        self.assertEqual(HANDLER_SCHEMAS.get("before_start"), "public")
        self.assertEqual(HANDLER_SCHEMAS.get("on_success"), "public")
        self.assertEqual(HANDLER_SCHEMAS.get("after_return"), "public")

    def test_every_handler_a_subclass_defines_is_wrapped_including_on_retry(self):
        """The four above are reached by running a task. `on_retry` is not.

        Driving a retry through the eager path means `self.retry()` re-applying
        the task inside itself until `max_retries` is exhausted, which tests
        Celery's eager machinery far more than it tests this. So `on_retry` is
        covered where the wrapping actually happens: `__init_subclass__` marks
        each function it replaces, and this asserts all five are marked on a
        class that defines all five. A name misspelled in
        `HANDLERS_CALLED_OUTSIDE_THE_BODY` wraps nothing and would otherwise be
        silent — which is the same silence the whole module is about.
        """
        for name in HANDLERS_CALLED_OUTSIDE_THE_BODY:
            with self.subTest(handler=name):
                self.assertTrue(
                    getattr(getattr(RecordingTask, name), "_runs_inside_its_school", False),
                    f"{name} was not wrapped on a subclass that defines it.",
                )

    def test_the_handler_names_are_ones_celery_actually_calls(self):
        """A misspelling wraps a method nothing calls, and nothing complains.

        The mirror of the test above: that one proves the five names were
        wrapped, this one proves they are the five that exist. Together they
        rule out a tuple that is internally consistent and points at nothing.
        """
        for name in HANDLERS_CALLED_OUTSIDE_THE_BODY:
            with self.subTest(handler=name):
                self.assertTrue(
                    callable(getattr(Task, name, None)),
                    f"celery.Task has no {name}; the tuple names a method that "
                    "does not exist, so wrapping it protects nothing.",
                )

    def test_a_handler_is_not_wrapped_twice_down_a_chain_of_subclasses(self):
        """`RecordingTask` inherits its handlers; it must not re-wrap them.

        A subclass that inherits rather than redefines has nothing of its own in
        `__dict__`, so there is nothing to wrap — but a subclass *further* down
        that redefines one would otherwise wrap an already-wrapped function and
        set the search path twice per handler.
        """

        class RecordsTwice(RecordingTask):
            pass

        wrapped = RecordsTwice.on_failure
        self.assertIs(wrapped, RecordingTask.on_failure)

    def test_control_a_task_without_the_base_runs_on_public(self):
        """What every task would do if `TenantTask` were doing nothing.

        Public is where a worker's connection starts, and it is not empty — every
        shared table is there. This is the failure the base class exists to make
        impossible, and without this control the tests above would pass just as
        happily if `TenantTask.__call__` were removed and the schema happened to
        be right already.
        """
        self.assertEqual(report_the_schema.apply().get(), "public")


class BrokerConnectivityTests(SimpleTestCase):
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
            # **On CI this is a failure, not a skip.** The class exists because
            # a broker nothing can connect to is the failure mode with no other
            # symptom; a bare `skipTest` hands that same silence straight back.
            # A redis service that fails to start, an image tag that breaks, a
            # wrong port typed into tests.yml — every one of them would have
            # been swallowed here and the job would have gone green, because
            # `manage.py test` does not fail on skips. The one claim
            # configuration cannot make would also have been the one claim CI
            # could not make.
            if os.environ.get("CI"):
                raise AssertionError(
                    f"No broker at {settings.CELERY_BROKER_URL}: {exc}. CI runs "
                    "a redis service for this test (see .github/workflows/"
                    "tests.yml); if it is not reachable, that service or its "
                    "CELERY_BROKER_URL is broken and the suite must say so."
                ) from exc
            self.skipTest(
                f"No broker at {settings.CELERY_BROKER_URL}: {exc}. Start one "
                "(docker compose up redis) or set CELERY_BROKER_URL."
            )


class WeasyPrintEnvironmentTests(SimpleTestCase):
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
