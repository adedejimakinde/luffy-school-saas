"""The report card page: one HTML shell, and no card in it.

The page a family opens. What it serves is a document with no marks, no name
and no average anywhere in it — an empty frame, a stylesheet and three ES
modules. Everything a parent reads arrives afterwards, from
`GET /api/results/cards/<child>/<term>/`, which is the route that asks who is
allowed to read what.

## The shell asks no authority question, and that is the design

There is exactly one answer to "may this person read this card", and it lives
in `card_api._require_may_read()` and `_require_servable()`. A view that
rendered the card server-side would be a second place asking it, and the day
the two disagreed the wrong one would be the one nobody had tested — the same
argument `card_api` makes for having one payload assembly rather than two.

So this view is deliberately dumb: it takes two integers out of the URL, puts
them in a `data-` attribute, and returns. It does not look the child up, does
not check the term exists, and does not care whether the caller is signed in.
Being unauthenticated here is not a hole, because the shell has nothing in it:
an anonymous visitor gets the frame, the frame asks the API, the API answers
401, and the page renders the "sign in" state. A stranger who guesses two
integers learns exactly what the API tells them, which is a flat 404.

**The ids are not validated and must not be.** `<int:...>` is the whole of it.
A view that checked "does membership 5 exist at this school" before serving the
frame would answer a question the flat-404 convention exists to refuse: the
page would 404 for a child who does not exist and 200 for one who does, turning
the URL into an existence oracle in front of an API built not to be one.

## Served from the school's own host

`urls.py` — the tenant urlconf — is where this is mounted, so the page is on
`stmarys.example.com` beside the API it calls. That matters for one unglamorous
reason: the session cookie. A page served from the portal host calling a
school's host would be a cross-site request, and the cookie that authenticates
a parent would not be sent. Same host, same cookie, no CORS, no preflight.

`SchoolAccessMiddleware` still runs, so a signed-in user who belongs to a
different school is refused before this view — by the same middleware that
refuses them the API, rather than by a check written again here.
"""

import json

from django.conf import settings
from django.shortcuts import render
from django.templatetags.static import static

#: Every module the page loads, entry point last.
#:
#: Listed rather than globbed, because a directory listing would decide what a
#: page loads at runtime and a stray file would join it silently.
_MODULES = ("html.js", "api.js", "render.js", "states.js", "app.js")


def _import_map() -> str:
    """The hashed URL for every module, keyed by the URL its siblings ask for.

    **This exists because `collectstatic` does not rewrite `import` statements.**
    It rewrites `{% static %}` in templates and `url()` in stylesheets, and that
    is all: the hashed `app.4f21c0.js` still contains `from "./api.js"`, which
    the browser resolves against the *document's* static path to
    `/static/results/card/api.js` — the unhashed copy. It is served, so nothing
    looks broken, and that is the problem: the entry point is cache-busted and
    the four modules it imports are not. A deploy would hand a browser today's
    `app.js` against yesterday's `render.js` out of its own cache, and the
    symptom would be a page that is subtly wrong for one person and fine for
    everybody else.

    An import map is the fix that needs no bundler. The keys are the URLs the
    relative imports resolve to; the values are what `{% static %}` resolves
    to, hashed where the storage hashes. Under plain storage — development, and
    the test suite — key and value are identical and the map is a no-op, which
    is exactly what it should be where nothing is hashed.

    `STATIC_URL` is read rather than assumed, so a deployment that serves
    assets from a different prefix gets a map that still matches its own
    imports.
    """
    prefix = settings.STATIC_URL or "/"
    return json.dumps(
        {
            "imports": {
                f"{prefix}results/card/{name}": static(f"results/card/{name}")
                for name in _MODULES
            }
        },
        indent=2,
    )


def card_page(request, student_membership_id: int, term_id: int):
    """The frame for one card. Takes two integers and trusts neither.

    `render()` rather than a `TemplateView`, because there is no dispatch to
    customise and a class would be three lines of ceremony around one call.
    """
    return render(
        request,
        "results/card_page.html",
        {
            "student_membership_id": student_membership_id,
            "term_id": term_id,
            "import_map": _import_map(),
        },
    )


__all__ = ["card_page"]
