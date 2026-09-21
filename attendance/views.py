"""The register screen: a frame, and no register in it.

The first page on a school's host that is a **staff** surface. Everything
before it was family — `/cards/` and the card itself, which `card_api
._children_of()` keeps to "the children the caller is a parent or guardian of"
and says in so many words is "Never staff's roster".

Like every page on this platform it is a **shell**: a frame, a stylesheet and a
few ES modules. It holds no class, no child and no mark, and this view reads
nothing from the database. Who may take a register is
`attendance.api._refuse_non_markers()`'s question, asked with the session
cookie by the fetches inside the page — and asked *before* either lookup, so
the route cannot become an existence oracle for the school's class groups.

## Where the work is, and what the portal does with this URL

Mounted in `urls.py`, which is what a tenant host gets. `urls_public.py` splats
those patterns in, so **the portal serves this frame as well** — exactly as it
already serves `/cards/`. That is not a leak and not an oversight: the frame
holds nothing, and every `attendance` route it fetches begins with
`_school_of()`, which raises `Http404` on the portal because the register
tables do not exist in the public schema at all. `docs/tenancy.md` is why.

So the page has a state for "this is not a school's host" rather than a routing
rule pretending the URL is absent. The mirror image of the two sign-in pages,
which really are portal-only, and for the opposite reason: a door needs a host
that lets somebody with no membership through, and a register needs the one
host that will not.

## No `login_required`, for the reason the card page gives

An unauthenticated caller gets the frame; the fetch inside it is what meets the
authority question. A `login_required` here would redirect, and a redirect on a
page whose URL is guessable turns that URL into an oracle — it would answer
"this school exists and this is its register" to anybody who typed it.

What the page does instead is read the portal's hostname, so its signed-out
state can offer a way back to a door that is on another host.
`schools.hosts.portal_host()` says why that link cannot be relative, and the
403 page added with #122 is on the same rule.
"""

from django.shortcuts import render

import pages
from schools.hosts import portal_host

#: Every module the register page loads, entry point last. `pages.import_map()`
#: says why each one has to be listed rather than only the entry point:
#: `collectstatic` hashes filenames and does not rewrite `import` statements.
REGISTER_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "register/api.js",
    "register/states.js",
    "register/app.js",
)


def register_page(request):
    """The frame. Takes nothing, reads one row, tells an anonymous caller nothing.

    The one row is the portal's hostname — the same thing `card_page()` and
    `card_index_page()` read, and for the same sentence: a staff member whose
    session has lapsed has to be sent back to `/staff-sign-in/`, which is on
    the portal while this page is on a school's host.
    """
    return render(
        request,
        "attendance/register_page.html",
        {
            "import_map": pages.import_map(*REGISTER_MODULES),
            "portal_host": portal_host(),
        },
    )


__all__ = ["register_page", "REGISTER_MODULES"]
