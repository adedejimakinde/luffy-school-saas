# Work that does not happen in a request

Celery, Redis and WeasyPrint, and the two traps that come with them on a
schema-per-school platform. This is the infrastructure PR that precedes task 7;
it renders no report card. What it establishes is where a background job runs,
which school it runs for, and what happens when it cannot tell.

Code: `celery_app.py`, `schools/tasks.py`, the *Background work* section of
`settings.py`, `schools/tests/test_background.py`. Environment:
`docker-compose.yml`, `.devcontainer/Dockerfile`,
`.github/workflows/tests.yml`.

## Why any of it

A report card is HTML rendered to PDF, and a class of forty-five is enough
rendering that no principal should be watching a browser tab while it happens.
So the render moves off the web process: Celery is the queue, Redis is what
holds it, WeasyPrint is what makes the file. Task 7 writes the job; this is the
ground it stands on.

## Trap one: a worker does not know which school it is for

Every request on this platform already knows. `TenantMainMiddleware` reads the
host, finds the `School`, sets the connection's `search_path`, and only then does
a view run — so "which school?" is answered by the URL before any code has to
ask.

A worker has no host. It has a message, and a connection that starts on
`public`. That is not an empty place to be:

| a task that forgot its schema | outcome |
| --- | --- |
| reads `academics_term` | `ProgrammingError` — the table is not there |
| writes `accounts_membership` | **succeeds**, platform-wide |

Tenant tables fail loudly because they are genuinely absent from `public`.
Shared tables do not fail at all, because `public` is where they live — it is
the second entry on every school's search path, which is the mechanism that lets
one login span several schools (see [tenancy.md](tenancy.md)). So the dangerous
half of the failure is silent.

`schools.tasks.TenantTask` makes the schema the task's first argument and
resolves it to a real `School` before the body runs:

```python
@shared_task(base=TenantTask)
def render_card(schema_name, card_id):
    ...

render_card.delay(school.schema_name, card.pk)
```

Three consequences worth stating:

- **An unknown schema is `UnknownSchool`, raised before the body.** A typo, a
  deleted school, a message that has outlived the school it names. Not retried:
  a schema that does not exist now will not exist in sixty seconds.
- **`"public"` is refused by construction.** No `School` row carries that schema
  name, so a task written for a school cannot be pointed at the portal.
  Platform-wide work is an ordinary `@shared_task` with no base and no schema
  argument — which is also the control test in `test_background.py`, showing
  what every task would do if the base class were doing nothing.
- **The school is looked up on `public` explicitly**, not from wherever the last
  job left the connection. A worker reuses its connection between jobs.

## Trap two: `.delay()` can succeed and send the job nowhere

`@shared_task` binds to whichever Celery app is *current* when the task is used.
With no app instantiated, Celery makes a default one whose broker is
`amqp://guest@localhost:5672//` — so a call from a web process returns a task id,
connects to an AMQP server this platform does not run, and the job is gone. The
process that would have raised is the one that never got the message.

`schools.apps.SchoolsConfig.ready()` imports `celery_app`, which is what makes
this project's app the current one in every Django process. The Django
documentation puts that import in the project package's `__init__.py`; this
project has no project package — `settings.py` and `manage.py` sit at the
repository root — so it goes on the first app in `SHARED_APPS` instead.

**And the file is `celery_app.py`, not `celery.py`, because the root is
`sys.path[0]`.** A `celery.py` beside `settings.py` would be importable as the
top-level name `celery` and would shadow the distribution for every process
started here. `RootModuleShadowingTests` fails the day somebody adds one, for
`redis` and `weasyprint` too.

One wrinkle found while proving this, because it decides what a green broker
check is worth: **Celery reads `CELERY_BROKER_URL` from the environment on its
own**, with no Django and no app. A deployment that exports the variable — as
docker-compose and CI both do — has a default app that reaches the right Redis
while running none of the settings chosen in `settings.py`. The variable hides
the failure; it does not fix it. So the control test asserts on `task_acks_late`
and the prefetch count, which no environment variable reaches.

## What was chosen, and what was deliberately not

`settings.py` carries the reasoning; in short:

- **No result backend.** Nothing asks a task what it returned. The PDF job's
  answer is a file and a row recording it, in Postgres, where a parent's next
  request can find it — not a broker key that expires.
- **JSON only.** The worker can reach every school's schema; `pickle` in
  `accept_content` would make anybody who can write to the broker able to run
  code inside it.
- **Acknowledge late, prefetch one.** A worker killed mid-render — a deploy, an
  OOM kill — leaves the job on the queue instead of dropping it. The price is
  that a task must be safe to run twice, which "render this frozen snapshot"
  is, because the snapshot cannot have changed. A task that is *not* idempotent
  must say so in its docstring.

**No time limits and no retry policy.** Both want a measurement rather than a
guess, and task 7 is where the measurement happens — 45 cards, timed.

**No `beat`, no scheduler.** Nothing on this platform is periodic yet. Adding
one is adding a second process with its own failure modes, and there is nothing
for it to do.

## WeasyPrint is not pure Python

Its text layout is Pango's. The wheel installs on a machine with no Pango at all
and raises at the first import — which on this project would be a principal
pressing a button. Both environments install the libraries explicitly
(`.devcontainer/Dockerfile`, `.github/workflows/tests.yml`), fonts included: a
container with Pango and no font family renders a page of boxes and still
returns a PDF, which is the worse outcome because the file arrives.

`WeasyPrintEnvironmentTests` renders a real PDF and asserts a font program was
embedded, which is the part that would notice.

## Running it

Redis and a worker are both services in `docker-compose.yml`; the worker
installs dependencies at start because `postCreateCommand` installs them only in
the devcontainer's own service. By hand, inside the dev container:

```
celery -A celery_app worker --loglevel=info
```

`BrokerConnectivityTests` skips, with a message naming the URL, where no broker
is running. CI runs a Redis service so that it does not skip there — a broker
nothing can reach is the failure with no other symptom.
