"""The Celery application, and the one thing its filename is load-bearing for.

Started by `celery -A celery_app worker`, imported by every Django process
through `schools.apps.SchoolsConfig.ready()`. Both halves matter and they matter
for different reasons — see below.

## Why this file is not called `celery.py`

The Django tutorial's version of this file is `myproject/celery.py`, and that is
safe there because `myproject` is a package: the module's importable name is
`myproject.celery`, which collides with nothing. **This project has no project
package.** `settings.py`, `urls.py` and `manage.py` all sit at the repository
root, so the root *is* `sys.path[0]`, and a file named `celery.py` here would be
importable as the top-level name `celery` — shadowing the distribution for
every process started from this directory. `from celery import Celery`, three
lines below, would then import this file from inside itself.

The failure is not subtle when it happens, but it is very hard to read, so
`schools/tests/test_background.py` keeps a test that fails the day somebody adds
a root-level module shadowing one of our dependencies.

## Why every Django process imports it

`@shared_task` does not bind a task to an application at import time; it binds
to whichever app is *current* when the task is finally used. With no app
instantiated, Celery obligingly creates a default one — whose broker is
`amqp://guest@localhost:5672//`, because that is Celery's default and nothing
here has said otherwise. So `some_task.delay(...)` from a web process would
succeed at the call site, connect to nothing, and drop the job. There is no
error, because the process that would have raised it is the one that never got
the message.

Instantiating this app during app loading is what makes it the current one, so
`.delay()` from a request goes to the same Redis the worker is listening to.
`schools/tests/test_background.py` proves it in subprocesses, because the
difference is invisible from inside a process that has already imported this
module.

One wrinkle found while writing that proof, because it decides how much a green
broker check is worth: **Celery reads `CELERY_BROKER_URL` from the environment
by itself**, with no Django and no app configured. A deployment that exports the
variable — as docker-compose.yml and the CI workflow both do — therefore has a
default app that reaches the right Redis while running none of the settings
chosen in settings.py: jobs acknowledged on pickup rather than on completion,
four reserved at a time, and this project's tasks not registered. The variable
hides the failure rather than fixing it, which is why the control test asserts
on the settings an environment variable cannot reach.
"""

import os

from celery import Celery

# Set before `Celery()` is constructed, not after: Celery's Django fixup — the
# thing that calls `django.setup()` in the worker, so tasks can touch the ORM —
# installs itself only if it can see this variable at construction time.
# `manage.py` sets the same default for the other direction.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

app = Celery("luffy")

# One source of configuration, shared with the web process. `namespace="CELERY"`
# is what makes `CELERY_BROKER_URL` in settings.py mean `broker_url` here.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Every app in INSTALLED_APPS gets its `tasks` module imported by the worker.
app.autodiscover_tasks()
