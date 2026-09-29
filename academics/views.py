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


#: The end-of-session promotion page's modules, entry point last.
PROMOTION_MODULES = (
    "web/html.js",
    "web/http.js",
    "promotion/api.js",
    "promotion/states.js",
    "promotion/app.js",
)


def promotion_page(request):
    """A shell, like setup's: the API asks who may promote, and asks it first."""
    return render(
        request,
        "academics/promotion_page.html",
        {
            "import_map": pages.import_map(*PROMOTION_MODULES),
            "portal_host": portal_host(),
            "on_school": getattr(request, "school", None) is not None,
        },
    )


__all__ = ["PROMOTION_MODULES", "SETUP_MODULES", "promotion_page", "setup_page"]
