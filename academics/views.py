"""The setup screen: a school's calendar and the groups children sit in.

The fifth staff surface, and the first for the office rather than the
classroom. A **shell**, like the four before it: who may shape a school is
`academics.services.can_set_up()`'s question, and a view that rendered the
terms server-side would be a second place asking it.

**No `login_required`**, for the reason the card page gives: a redirect on a
guessable URL is an oracle. The fetch inside the page meets the question.

Both tables are tenant-local, so the page carries **no school slug** — the
connection has already been pointed at one schema, and a slug would be a second
opinion free to disagree with it.
"""

from django.shortcuts import render

import pages
from schools.hosts import portal_host

#: Every module the setup page loads, entry point last.
SETUP_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "setup/api.js",
    "setup/states.js",
    "setup/app.js",
)


def setup_page(request):
    """The frame. Takes nothing, reads one row, tells an anonymous caller nothing."""
    return render(
        request,
        "academics/setup_page.html",
        {
            "import_map": pages.import_map(*SETUP_MODULES),
            "portal_host": portal_host(),
        },
    )


__all__ = ["setup_page", "SETUP_MODULES"]
