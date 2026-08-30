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
since before a school was renamed. Platform-wide work is an ordinary
`@shared_task` with no base, which runs on `public` and says so by having no
schema argument at all.

**`"public"` is refused by a line of code, not by the absence of a row.** The
first draft of this module reasoned that no `School` carries that schema name,
so the portal could not be reached by a task written for a school. That premise
is false, and `results.services.school_on_this_connection()` had already
written down why: this codebase creates a `School(name="Portal",
schema_name="public")` row in its own fixtures, and where one exists the lookup
below *succeeds* and hands back the portal. A `TenantTask` pointed at `"public"`
— a stale message, a typo, a caller that passed the wrong variable — would then
run its body on the public schema, where every shared table is writable. That is
precisely the silent, platform-wide write this class exists to prevent, arrived
at through the guard rather than around it.

`UnknownSchool` is deliberately not retried. A schema that does not exist now
will not exist in sixty seconds, and a task that retries forever is a queue that
never drains.
"""

from contextlib import contextmanager
from functools import wraps

from celery import Task
from django_tenants.utils import (
    get_public_schema_name,
    schema_context,
    tenant_context,
)


class UnknownSchool(Exception):
    """A task named a schema that no school on this platform has.

    Its own type rather than a `ValueError` so that a caller inside the worker
    can tell "this school is gone" apart from anything the task's own body might
    have raised about its arguments.

    Not, note, so that a *monitor* can: with `CELERY_RESULT_BACKEND` off — see
    `settings.py`, where that is a decision rather than an oversight — the
    exception type is stored nowhere a monitor can read it. `AsyncResult.result`
    is always `None` and flower has nothing to show. The only place this type is
    legible from outside the process is the worker's own stderr, where it is a
    traceback like any other.
    """


#: The five methods Celery calls **outside** the body, in the order it calls
#: them. `on_retry`, `on_failure` and `after_return` are reached through
#: `TraceInfo`; the rest from `build_tracer` directly. All five run between that
#: tracer's `push_request` and its `pop_request`, which is what lets the wrapper
#: below read a job's arguments off `self.request` rather than off its own
#: signature — five signatures that put `args` and `kwargs` in four different
#: positions.
HANDLERS_CALLED_OUTSIDE_THE_BODY = (
    "before_start",
    "on_success",
    "on_retry",
    "on_failure",
    "after_return",
)


def _runs_inside_its_school(handler):
    """Wrap one handler so that its own body runs inside the school."""

    @wraps(handler)
    def inside(self, *args, **kwargs):
        with self._inside_its_school():
            return handler(self, *args, **kwargs)

    inside._runs_inside_its_school = True
    return inside


class TenantTask(Task):
    """Base for a task that runs inside one school's schema.

    The schema name is the task's first argument, positional or keyword. It is
    resolved to a `School` on the public schema, and the body then runs inside
    `tenant_context(school)` — which sets the same `search_path` a request would
    have set, and the same `connection.tenant` that `schools.logging` reads to
    put the school's name on every line the task logs.

    ## The handlers are inside the school too, and the obvious way to do that fails

    Wrapping `__call__` alone covers the body and nothing else. Celery's tracer
    calls `before_start` before it and `on_success` / `on_retry` / `on_failure` /
    `after_return` after it, all **outside** the `with` block, which closes the
    moment the body returns. A subclass overriding `on_failure` to record that a
    render failed — which is precisely what task 7's PDF job wants one for —
    would run that write on `public`: a `ProgrammingError` for a tenant table,
    and a silent platform-wide write for a shared one. Same two outcomes this
    class exists to prevent, one altitude up.

    **Overriding the five handlers here does not fix that, and the first draft
    of this class did exactly that and shipped a guard that guarded nothing.**
    The tracer takes the *most derived* bound method — `task.before_start`, not
    `TenantTask.before_start` — so a subclass's override is what runs, and its
    body runs to completion before its `super()` call ever reaches the context
    manager. The one line the wrapping exists to protect is the one line it sits
    behind. A base-class override protects only a subclass that writes nothing
    before delegating upward, which is not a subclass anybody would write.

    So the handlers are wrapped rather than overridden: `__init_subclass__`
    replaces each of the five a subclass brings — defined on it, or inherited
    from a mixin — with the same function inside `tenant_context`. The subclass
    keeps its own method and needs to know nothing; there is no `super()` call
    it can forget or misplace. (A handler *assigned* onto a class after it is
    built is not wrapped — nothing here does that, and a handler is a method in
    practice.) Nothing is defined for the five names on this class, which also
    keeps Celery's own `task_has_custom` honest: it stops at `Task`, so defining
    them here would have told the tracer every `TenantTask` had custom handlers
    and made it call three no-ops per job.

    The school is resolved once per execution and cached on `self.request`,
    which Celery creates fresh per call — not on `self`, because a worker reuses
    one task instance for every message it handles, and a school cached there
    would be the *previous* job's school.

    Where the schema cannot be resolved at all, a handler runs where the worker
    started rather than not running. That case is a task that already failed —
    `__call__` refused it — and the failure handler reporting it should not
    itself disappear. A tenant table touched there fails loudly, which is the
    honest outcome for a job that never had a school.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name in HANDLERS_CALLED_OUTSIDE_THE_BODY:
            # Resolved through the MRO, not read out of `cls.__dict__`. A
            # handler a subclass gets from a **mixin** is not in its own dict,
            # and the dict spelling skipped it silently — which is the shape the
            # test scaffolding here uses, and a normal way to share a handler
            # between two task classes. Whatever `getattr` finds is what Celery's
            # tracer will find, so it is the thing that has to be wrapped.
            handler = getattr(cls, name, None)
            if handler is None or handler is getattr(Task, name, None):
                continue
            # A subclass of a subclass resolves to its parent's already-wrapped
            # function. Wrapping again is harmless — `tenant_context` nests —
            # but it is a second `search_path` write per handler per job.
            if getattr(handler, "_runs_inside_its_school", False):
                continue
            setattr(cls, name, _runs_inside_its_school(handler))

    def _school(self, args, kwargs):
        """The school this execution belongs to, resolved at most once."""
        request = getattr(self, "request", None)
        cached = getattr(request, "_tenant_task_school", None)
        if cached is not None:
            return cached

        school = school_for(schema_name_from(args, kwargs))
        if request is not None:
            # `Context` takes arbitrary attributes; guard anyway, because a
            # failure to cache must not become a failure to run.
            try:
                request._tenant_task_school = school
            except (AttributeError, TypeError):
                pass
        return school

    @contextmanager
    def _inside_its_school(self):
        """`tenant_context`, or nothing at all where there is no school to enter.

        The arguments are read off `self.request` rather than passed in, for the
        reason `HANDLERS_CALLED_OUTSIDE_THE_BODY` gives: they are the same
        objects the tracer hands each handler, and taking them from one place
        means the wrapper does not have to know which of the five it is wrapping.
        """
        request = getattr(self, "request", None)
        try:
            school = self._school(
                getattr(request, "args", None) or (),
                getattr(request, "kwargs", None) or {},
            )
        except (UnknownSchool, TypeError):
            yield None
            return
        with tenant_context(school):
            yield school

    def __call__(self, *args, **kwargs):
        # Its own arguments, not `self.request`: this is the refusal point, and
        # it must not depend on the tracer having pushed a request. And not
        # `_inside_its_school`, which swallows the refusal — the body must *not*
        # run when the school cannot be resolved.
        school = self._school(args, kwargs)
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
    # Report what did arrive. The common way to reach here is not an empty
    # `.delay()` — it is `delay(card_id=7)`, or a keyword whose name drifted
    # (`school_schema=...`), where there are arguments and none of them is the
    # one wanted. A message saying "no arguments at all" sends the person
    # reading the worker log looking for a call site that does not exist.
    given = ", ".join(
        [repr(value) for value in args] + [f"{name}=..." for name in sorted(kwargs)]
    )
    raise TypeError(
        "A TenantTask needs the school's schema name as its first argument, "
        "positionally or as schema_name=. This one was called with "
        f"{given or 'no arguments at all'}. Platform-wide work belongs in a "
        "task with no base=TenantTask."
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

    **The portal is refused before the query, not by it.** See the module
    docstring: a `School` row with `schema_name="public"` exists in this
    codebase's own fixtures, so the lookup below returns it rather than nothing,
    and a task pointed at `"public"` would run against every shared table on the
    platform. `results.services.school_on_this_connection()` refuses the portal
    in the same shape and for the same reason.
    """
    if schema_name == get_public_schema_name():
        raise UnknownSchool(
            f"{schema_name!r} is the portal, not a school. A TenantTask runs "
            "inside one school's schema; work that belongs to the platform "
            "belongs in a task with no base=TenantTask, which says so by "
            "taking no schema name."
        )

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
