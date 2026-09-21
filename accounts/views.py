"""The two sign-in pages. One hostname, no data in either.

Two doors, because there are two ways to prove who you are and they have almost
nothing in common. A guardian signs in with a code on a channel the school
verified — `POST /api/guardian/code/` then `POST /api/guardian/session/`, four
steps and a 202 for a shared handset. A member of staff signs in with a
password — `POST /api/login/`, one step and no chooser. Neither page can be the
other with a flag: the four-step flow has no password field and cannot have
one, and the one-step flow has nothing to keep between requests.

Like the report card page both are **shells**: a frame, a stylesheet and a few
ES modules. Neither holds an account, a child or a school, and neither view
reads anything from the database.

## Portal-only, by routing rather than by a check

Both are mounted in `urls_public.py` and not in `urls.py`, so they exist on the
portal host and nowhere else. That matches the routes they call —
`guardian_code()`, `guardian_session()` and `sign_in()` all begin with
`api._portal_only()` — and it matters for the reason that function gives: a
school's host refuses anyone without an active membership *there*, so sign-in
served from it would mean the same credentials worked on one hostname and not
another, and a teacher who is also a parent elsewhere would need two sessions.

A page mounted where its API is not would be a form that submits into a 404.

## Nothing is remembered on either, and the shared handset is why

The guardian flow holds the number and the code in the page's own memory for the
life of the page — see `static/signin/app.js`. The staff flow holds neither:
there is no second request, so the password goes from the field into the POST
body and is copied nowhere. Neither page uses `sessionStorage`, because one
handset in a household is the case this platform exists for and anything left in
a browser's storage is something the next person to pick up the phone can
replay.
"""

from django.shortcuts import render

import pages

#: Every module the guardian page loads, entry point last. `pages.import_map()`
#: says why each one has to be listed rather than only the entry point.
MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "signin/states.js",
    "signin/app.js",
)

#: The staff page's own. It shares `web/` with every other page — one escape
#: rule, one CSRF story and one sign-out for the whole platform, which is what
#: `settings.STATICFILES_DIRS` argues for.
STAFF_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "staff-signin/states.js",
    "staff-signin/app.js",
)


def sign_in_page(request):
    """The guardian frame. Takes nothing, reads nothing, tells the caller nothing."""
    return render(
        request,
        "accounts/sign_in.html",
        {"import_map": pages.import_map(*MODULES)},
    )


def staff_sign_in_page(request):
    """The staff frame. Identical in what it holds, which is nothing.

    **"Staff" is what this page is for, not what the route behind it checks.**
    `POST /api/login/` resolves any identifier `User.matching_identifier()`
    knows — an email, a phone number, or a school-issued handle — so a student
    with a password can sign in here too and nothing about the page stops them.
    It is framed for staff because staff are who needed a door and had none;
    claiming it refuses anybody else would be a claim the route does not make.

    Served to whoever opens the URL, like its guardian counterpart. A
    `login_required` on a sign-in page is a door that needs a key.
    """
    return render(
        request,
        "accounts/staff_sign_in.html",
        {"import_map": pages.import_map(*STAFF_MODULES)},
    )


__all__ = ["sign_in_page", "staff_sign_in_page", "MODULES", "STAFF_MODULES"]
