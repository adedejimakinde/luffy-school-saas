"""Demo school names cannot exist on a server that holds real schools.

`seed_demo` and `load_demo` make fictional schools (`sunrise-demo`,
`harbour-demo`, `showcase-demo`) with fake children and a login for every role.
Each has its own lock: `seed_demo` wants `DEBUG`, `load_demo` wants
`DEMO_SERVER=1` and refuses when a real school is in the database. Neither lock
sat on the other side of the door: nothing stopped `create_school` from making
`sunrise-demo` on a production server, where it would be a school with a name
the demo's own tooling treats as disposable, and where a later `load_demo` run
with a stray `DEMO_SERVER` would find it already "a demo school" and carry on.

So the name is the thing refused, in two places, because either alone has a way
round it:

1. **Creating one** (`School.save()`, and `create_school()` ahead of it so the
   operator gets a sentence rather than a traceback) is refused unless the
   process is a development machine (`DEBUG`) or the demo server
   (`DEMO_SERVER=1`).
2. **Having one**: `wsgi.py` asks `refuse_if_demo_schools_exist()` as the web
   process starts, and a server that holds a demo school and is neither of those
   does not start. A `bulk_create()`, a restore from a backup of a demo server,
   or a row written in `psql` all skip `save()`; none skips this.

**Why `DEMO_SERVER` is allowed and not only `DEBUG`.** The demo server
(`docs/demo-server.md`) runs with `DEBUG` off, as it must, and makes its schools
with `load_demo`. `deploy/init-env.sh` already refuses a production
`secrets.env` that sets `DEMO_SERVER`, and a deploy check cannot be the only
lock, which is why this exists.

**What a demo name is.** The three that `seed_demo` and `showcase` make, and any
other that has the same shape: `demo`, a name starting `demo-`, or one ending
`-demo` (with an underscore too, because the schema name is the slug with its
hyphens turned into underscores and is checked as well). A real school called
"Demonstration Secondary School" is not one: `demolition-academy` is not
`demo-...`.

**The limit.** If Postgres cannot be reached at the moment the web process
starts, the check cannot tell and lets the process start (it says so in the
log). `/healthz/` already answers 503 in that case and the deploy script rolls
back on it. The creation guard still applies to everything made afterwards.
"""

import logging
import os
import re

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError

logger = logging.getLogger(__name__)

#: The ones the demo tooling makes. Named once, here; `seed_demo.SCHOOLS` and
#: `showcase.SLUG` are asserted to be inside it by a test, so a fourth demo
#: school cannot be added without this list hearing about it.
DEMO_SLUGS = frozenset({"sunrise-demo", "harbour-demo", "showcase-demo"})

_DEMO_SHAPE = re.compile(r"^(?:demo|demo[-_].+|.+[-_]demo)$")


class DemoSchoolRefused(Exception):
    """A demo school's name was used where demo schools are not allowed."""


def is_demo_name(value) -> bool:
    """Is this slug or schema name a demo school's?"""
    value = (value or "").strip().lower()
    return value in DEMO_SLUGS or value.replace("_", "-") in DEMO_SLUGS or bool(_DEMO_SHAPE.match(value))


def demo_schools_allowed() -> bool:
    """Is this process a development machine or the demo server?

    Read at the moment it is asked, not at import: `DEMO_SERVER` is an
    environment switch like `load_demo`'s own, and a test must be able to
    show both answers without reloading settings.
    """
    from django.conf import settings

    return bool(settings.DEBUG) or os.environ.get("DEMO_SERVER") == "1"


def creating_message(name) -> str:
    return (
        f"{name!r} is a demo school's name. Demo schools exist only on a "
        "development machine (DJANGO_DEBUG=1) or the demo server (DEMO_SERVER=1), "
        "and this server is neither, so nothing was created. Choose another name."
    )


def refuse_creating(*names) -> None:
    """Raise `DemoSchoolRefused` naming the first demo name among `names`."""
    if demo_schools_allowed():
        return
    for name in names:
        if is_demo_name(name):
            raise DemoSchoolRefused(creating_message(name))


def demo_schools_present() -> list:
    """The slugs of every school whose slug or schema name is a demo name."""
    from schools.models import School

    found = []
    for slug, schema_name in School.objects.values_list("slug", "schema_name"):
        if is_demo_name(slug) or is_demo_name(schema_name):
            found.append(slug)
    return sorted(found)


def refuse_if_demo_schools_exist() -> None:
    """Refuse to start a server that holds a demo school and is not allowed to.

    Called as the web process starts (`wsgi.py`). Raises `ImproperlyConfigured`,
    which gunicorn reports as a worker that failed to boot, and the container
    exits: `deploy.sh` then sees the new image unhealthy and goes back to the
    previous one.
    """
    if demo_schools_allowed():
        return
    try:
        present = demo_schools_present()
    except DatabaseError as error:
        logger.warning(
            "Could not check for demo schools at start-up (%s); starting anyway. "
            "/healthz/ reports an unreachable database.",
            error.__class__.__name__,
        )
        return
    if present:
        raise ImproperlyConfigured(
            "Refusing to start: this server is not a development machine or the "
            f"demo server, and its database holds demo school(s): {', '.join(present)}. "
            "Demo schools hold fake children and logins with published passwords. "
            "Remove them (and their schemas) before starting this server, or, if "
            "this is the demo server, set DEMO_SERVER=1."
        )
