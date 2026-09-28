"""The settings screen: three switches, and who gets the daily money summary.

A shell like the others — `fees/views.py`'s docstring gives the reason there
is no `login_required` and no authority check here: the API refuses whoever
may not read or change these, and a page that also checked would be a second
place that check could drift from.
"""

from django.shortcuts import render

import pages
from schools.hosts import portal_host

#: Every module the page loads, entry point last.
SETTINGS_MODULES = (
    "web/html.js",
    "web/http.js",
    "notices/api.js",
    "notices/states.js",
    "notices/app.js",
)


def settings_page(request):
    return render(
        request,
        "notices/settings_page.html",
        {
            "import_map": pages.import_map(*SETTINGS_MODULES),
            "portal_host": portal_host(),
            "on_school": getattr(request, "school", None) is not None,
        },
    )


__all__ = ["SETTINGS_MODULES", "settings_page"]
