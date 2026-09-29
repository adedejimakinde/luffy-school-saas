"""The platform admin page's frame."""

from django.http import Http404
from django.shortcuts import render

import pages
from results import look
from schools.hosts import portal_host

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


def school_site(request):
    """A school's public page, on its own address: who it is and where to go.

    Open to anyone, signed in or not, and **all server-drawn**: no script, no
    request to another host, no fetch. It says only what the office chose to
    publish (name, crest, colour, about, address, phone, contact email) and links
    to the two things a family comes for, the result checker on this address and
    the parent sign-in on the portal. Every piece of text goes through Django's
    escaping. Not on the portal, which is not any school.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("This is a school's own page; the portal has none.")
    return render(
        request,
        "schools/site.html",
        {
            "school": school,
            "look": look.for_site(school.name),
            "portal_host": portal_host(),
        },
    )
