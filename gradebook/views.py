"""The marking screen: a frame, and not one mark in it.

The second staff surface, after the register. Like every page on this platform
it is a **shell** — a frame, a stylesheet and a few ES modules — and this view
reads one row, the portal's hostname, so its signed-out state can offer a way
back to a door on another host.

## The authority question is asked once, and not here

`gradebook.api.marking_sheet()` gates on `can_enter_marks()`, and the write
routes gate on the same thing. A view that rendered the sheet server-side would
be a second place asking it, and the day the two disagreed the wrong one would
be the one nobody had tested — the argument `results/views.py` makes about the
card and `card_api` makes about the payload.

**No `login_required`**, for the reason the card page gives: a redirect on a
guessable URL is an oracle, answering "this school exists and here is its
gradebook" to anybody who types it. The fetch inside the page meets the
question instead.

## Where it is, and what the portal does with this URL

Mounted in `urls.py`, which is what a tenant host gets. `urls_public.py` splats
those patterns in, so the portal serves this frame too — exactly as it already
serves `/cards/` and `/register/`. Harmless and deliberate: the frame holds
nothing, and every `gradebook` route it calls begins with `_school_of()`, which
raises `Http404` there because these tables do not exist in the public schema.
The page has a state for that answer.
"""

from django.shortcuts import render

import pages
from schools.hosts import portal_host

#: Every module the marking page loads, entry point last. `pages.import_map()`
#: says why each one is listed rather than only the entry point: `collectstatic`
#: hashes filenames and does not rewrite `import` statements.
MARKING_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "marking/outbox.js",
    "marking/store.js",
    "marking/api.js",
    "marking/states.js",
    "marking/app.js",
)


def marking_page(request):
    """The frame. Takes nothing, reads one row, tells an anonymous caller nothing."""
    return render(
        request,
        "gradebook/marking_page.html",
        {
            "import_map": pages.import_map(*MARKING_MODULES),
            "portal_host": portal_host(),
        },
    )


__all__ = ["marking_page", "MARKING_MODULES"]
