"""The timetable page: a frame, and no lesson in it.

A shell on the broadsheet's terms. Who may read the timetable is
`timetable.services.may_read()`, asked by every route the page fetches, and
those routes answer a flat 404 both to a refused reader and on the portal — so
the one thing this frame says is whether the host is a school's. No
`login_required`, because a redirect on a guessable URL is an oracle.
"""

from django.shortcuts import render

import pages
from schools.hosts import portal_host

#: Every module the page loads, entry point last. `pages.import_map()` says why
#: each has to be listed.
TIMETABLE_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "timetable/api.js",
    "timetable/states.js",
    "timetable/app.js",
)


def timetable_page(request):
    return render(
        request,
        "timetable/timetable_page.html",
        {
            "import_map": pages.import_map(*TIMETABLE_MODULES),
            "portal_host": portal_host(),
            "on_school": getattr(request, "school", None) is not None,
        },
    )


__all__ = ["TIMETABLE_MODULES", "timetable_page"]
