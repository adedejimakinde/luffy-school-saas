"""The frame for the principal's home. Holds no figure and no child.

A shell like every other staff page: who may read the home is
`home.api.home()`'s question, asked before any read. **No `login_required`**,
for the reason `results/views.py` gives: a redirect on a guessable URL is an
oracle, and the fetch inside the page meets the question instead.
"""

from django.shortcuts import render

import pages
from schools.hosts import portal_host

#: Every module the home page loads, entry point last. `fees/money.js` is the
#: fee book's own formatter, reused so a naira reads the same on both pages.
HOME_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "fees/money.js",
    "home/api.js",
    "home/states.js",
    "home/app.js",
)


def home_page(request):
    return render(
        request,
        "home/home_page.html",
        {
            "import_map": pages.import_map(*HOME_MODULES),
            "portal_host": portal_host(),
        },
    )


__all__ = ["HOME_MODULES", "home_page"]
