"""Work done for one school, with no request to say which school that is.

A request never has this problem. `TenantMainMiddleware` reads the host, finds
the `School`, and sets the connection's `search_path` before any view runs — so
by the time application code executes, "which school?" has already been answered
by the URL the browser asked for.

**A worker has no host.** It has a message off a queue, and the connection it
picks up is on `public` — where none of a school's tables exist, but where every
*shared* table does, because `public` is the second entry on every school's
search path (see docs/tenancy.md). That asymmetry is the whole hazard:

    a task that forgets its schema        reading academics_term  -> ProgrammingError
    the same task                         writing accounts_*      -> succeeds, wrongly

The first is loud. The second is a background job quietly writing platform-wide
rows while believing it is inside one school. So the schema is not something a
task may forget to set: it is the task's first argument, and `TenantTask`
refuses to run the body until it has been resolved to a real school.

## How to write one

    from celery import shared_task
    from schools.tasks import TenantTask

    @shared_task(base=TenantTask)
    def render_card(schema_name, card_id):
        ...

    render_card.delay(school.schema_name, card.pk)

The schema name is passed through to the function as well as consumed by the
base, so it appears in the task's arguments where an operator watching a queue
can see which school a job belongs to — and so the function can log it.

## What it refuses

An unknown schema name raises `UnknownSchool` before the body runs. That covers
the typo, the deleted school, and the message that has been sitting on the queue
since before a school was renamed. It also covers `"public"`: no `School` row
carries that schema name, so the portal cannot be reached by a task written for
a school. Platform-wide work is an ordinary `@shared_task` with no base, which
runs on `public` and says so by having no schema argument at all.

`UnknownSchool` is deliberately not retried. A schema that does not exist now
will not exist in sixty seconds, and a task that retries forever is a queue that
never drains.
"""

from celery import Task
from django_tenants.utils import (
    get_public_schema_name,
    schema_context,
    tenant_context,
)


class UnknownSchool(Exception):
    """A task named a schema that no school on this platform has.

    Its own type rather than a `ValueError` so that a caller — or a monitor
    reading the failure — can tell "this school is gone" apart from anything the
    task's own body might have raised about its arguments.
    """


class TenantTask(Task):
    """Base for a task that runs inside one school's schema.

    The schema name is the task's first argument, positional or keyword. It is
    resolved to a `School` on the public schema, and the body then runs inside
    `tenant_context(school)` — which sets the same `search_path` a request would
    have set, and the same `connection.tenant` that `schools.logging` reads to
    put the school's name on every line the task logs.
    """

    def __call__(self, *args, **kwargs):
        school = school_for(schema_name_from(args, kwargs))
        with tenant_context(school):
            return super().__call__(*args, **kwargs)


def schema_name_from(args, kwargs):
    """The first argument, however the caller chose to pass it.

    `delay("st_marys", 7)` and `delay(schema_name="st_marys", card_id=7)` are the
    same call to everybody except the code unpacking it, and a base class that
    only understood one of them would fail on the other in the worker — a long
    way from the call site that chose the form.
    """
    if "schema_name" in kwargs:
        return kwargs["schema_name"]
    if args:
        return args[0]
    raise TypeError(
        "A TenantTask needs the school's schema name as its first argument, "
        "and this one was called with no arguments at all. Platform-wide work "
        "belongs in a task with no base=TenantTask."
    )


def school_for(schema_name):
    """The school owning `schema_name`, or `UnknownSchool`.

    Read on the public schema explicitly. `schools.School` is shared, so it is
    readable from inside a school's schema too — but only because `public` is on
    the search path, and the point of this lookup is to establish where we are
    rather than to assume it. A worker process reuses its connection between
    jobs, so "wherever the last task left it" is not a base to read from.

    **`is_active` is deliberately not checked.** The field exists on `School` and
    nothing on the platform enforces it — a request to an inactive school is
    served like any other — so refusing one here would be a second, stricter
    policy invented in the least visible place on the platform. Issue #50 holds
    the decision; when it is made, this function is one of the call sites that
    has to honour it.
    """
    with schema_context(get_public_schema_name()):
        # Deferred to keep this module importable by Celery's autodiscovery
        # before the app registry is populated.
        from schools.models import School

        school = School.objects.filter(schema_name=schema_name).first()
    if school is None:
        raise UnknownSchool(
            f"No school on this platform has the schema {schema_name!r}. "
            "Refusing to run: a task that cannot find its school would run on "
            "the public schema, where every shared table is writable."
        )
    return school
