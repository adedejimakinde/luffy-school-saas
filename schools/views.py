"""The platform admin page's frame."""

from django.shortcuts import render

import pages

#: The platform page's own modules, entry point last.
PLATFORM_MODULES = (
    "web/html.js",
    "web/http.js",
    "platform/api.js",
    "platform/states.js",
    "platform/app.js",
)


def platform_page(request):
    """The frame for the platform admin screen. Holds no school and no name.

    A shell, like every page here: who may see the list is
    `schools.platform_api`'s question, asked by the page's first fetch, and a
    view that rendered the list would be a second place asking it. Routed on the
    portal host alone (`urls_public.py`); a school's host has no such page.
    """
    return render(
        request,
        "schools/platform_page.html",
        {"import_map": pages.import_map(*PLATFORM_MODULES)},
    )
