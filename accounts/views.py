"""The sign-in page. One door, on one hostname, with no data in it.

The page a guardian opens before anything else. Like the report card page it is
a **shell**: a frame, a stylesheet and three ES modules. It holds no account, no
child and no school, and it asks nothing of the database.

## Portal-only, by routing rather than by a check

Mounted in `urls_public.py` and not in `urls.py`, so it exists on the portal
host and nowhere else. That matches the routes it calls — `guardian_code()` and
`guardian_session()` both begin with `api._portal_only()` — and it matters for
the reason that function gives: a school's host refuses anyone without an active
membership *there*, so sign-in served from it would mean the same credentials
worked on one hostname and not another, and a parent with children at two
schools would need two sessions.

A page mounted where its API is not would be a form that submits into a 404.

## Nothing is remembered here, and the shared handset is why

The flow holds the number and the code in the page's own memory for the life of
the page — see `static/signin/app.js`. The server keeps no half-finished
sign-in, and the page keeps nothing in `sessionStorage`: one handset in a
household is the case this flow exists for, and a code left in a browser's
storage is a code the next person to pick up the phone can replay.
"""

from django.shortcuts import render

import pages

#: Every module the page loads, entry point last. `pages.import_map()` says why
#: each one has to be listed rather than only the entry point.
MODULES = ("web/html.js", "web/http.js", "signin/states.js", "signin/app.js")


def sign_in_page(request):
    """The frame. Takes nothing, reads nothing, tells the caller nothing."""
    return render(
        request,
        "accounts/sign_in.html",
        {"import_map": pages.import_map(*MODULES)},
    )


__all__ = ["sign_in_page", "MODULES"]
