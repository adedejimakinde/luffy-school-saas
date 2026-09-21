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
from schools.hosts import portal_host

from .refusals import SchoolAccessRefused

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


def refused(request, exception=None):
    """The 403 page, which says what happened and whether anything fixes it.

    Issue #122. `SchoolAccessMiddleware` has always raised `PermissionDenied`
    carrying a sentence written for the person it refuses, and with no
    `403.html` in the repository Django's default handler rendered
    `ERROR_PAGE_TEMPLATE` with empty `details` and threw the sentence away.

    **The remedy is read off the exception's type, never off its text.**
    `accounts.refusals` says why at length: the two refusals this middleware
    raises are one password apart and infinitely far apart respectively, and a
    template branching on prose would start offering the wrong one the day
    somebody reworded a sentence.

    Three things are deliberately narrow here.

    `detail` is printed only for a `SchoolAccessRefused`. Any other
    `PermissionDenied` — from the admin, from a future view — renders the page
    with no sentence, because an arbitrary exception's `str()` is written for
    whoever debugs it and an error page is not where to start trusting that.

    `portal_host()` is called **only** when a password is the remedy. It is a
    database query, and a page answering a refusal should not make one it has
    no use for.

    And there is no link when that query comes back empty. A deployment with no
    primary `Domain` for the public schema gets the sentence without the link,
    which is the rule `schools.hosts.portal_host()` states and the card page
    already keeps: a dead link is worse than being told to go back the way you
    came.
    """
    ours = isinstance(exception, SchoolAccessRefused)
    a_password_fixes_it = getattr(exception, "a_password_fixes_it", False)
    return render(
        request,
        "403.html",
        {
            "detail": str(exception) if ours else "",
            "a_password_fixes_it": a_password_fixes_it,
            "portal_host": portal_host() if a_password_fixes_it else "",
        },
        status=403,
    )


__all__ = [
    "sign_in_page",
    "staff_sign_in_page",
    "refused",
    "MODULES",
    "STAFF_MODULES",
]
