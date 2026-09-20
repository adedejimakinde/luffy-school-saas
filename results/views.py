"""The two pages a family sees, and neither has a card in it.

`card_index_page()` lists which children this caller stands for and which of
their cards exist; `card_page()` is one of those cards. Both serve a document
with no marks, no name and no average anywhere in it — an empty frame, a
stylesheet and a few ES modules. Everything a parent reads arrives afterwards
from `GET /api/results/cards/` and
`GET /api/results/cards/<child>/<term>/`, which are the routes that ask who is
allowed to read what.

The index is the page that makes a card reachable at all: both card routes are
keyed on `(student_membership_id, term_id)` and nothing this API said to a
family carried either number until the index route existed, so the card page
shipped openable only by typing two integers into a URL.

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

from django.shortcuts import render

import pages
from schools.models import Domain

#: Every module the card page loads, entry point last.
#:
#: Listed rather than globbed, because a directory listing would decide what a
#: page loads at runtime and a stray file would join it silently.
CARD_MODULES = (
    "web/html.js",
    "card/api.js",
    "card/render.js",
    "card/states.js",
    "card/app.js",
)

#: The index page's own. It shares `web/` with the card page and the sign-in
#: page — one escape rule for every page, which is what `settings.STATICFILES_DIRS`
#: argues for.
INDEX_MODULES = (
    "web/html.js",
    "web/http.js",
    "index/states.js",
    "index/app.js",
)


def _portal_host() -> str:
    """Where a parent signs in, read from the one place that knows.

    The index page needs it for a single sentence: its 401 state has to offer a
    way back, and sign-in is on the portal while this page is on a school's
    host, so the link cannot be relative.

    **The API deliberately will not answer this** — `api._portal_only()` says a
    client knows its own portal and that having the server name it would put the
    same fact in two places. This does not reopen that. It reads the fact from
    the single authority there is, the `Domain` row for the public schema, and
    renders it into a page this same deployment serves; it does not add an API
    that tells arbitrary callers where the front door is.

    Empty where no such row exists. The state then renders its sentence without
    a link, because a dead link is worse than being told to go back the way you
    came.
    """
    return (
        Domain.objects.filter(tenant__schema_name="public", is_primary=True)
        .values_list("domain", flat=True)
        .first()
        or ""
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
            "import_map": pages.import_map(*CARD_MODULES),
        },
    )


def card_index_page(request):
    """The frame for the index: which children, and which of their cards.

    Reads one row — the portal's hostname, for the sentence the 401 state needs
    — and no card data of any kind. Who this caller stands for is
    `GET /api/results/cards/`'s question, asked with the session cookie, and
    that route answers only about children the caller already has a claim on.

    Unauthenticated callers get the frame, exactly as the card page serves one:
    the fetch inside it is what meets the authority question, and a
    `login_required` here would turn the URL into an oracle in a deployment
    where a school's host is guessable.
    """
    return render(
        request,
        "results/card_index.html",
        {
            "import_map": pages.import_map(*INDEX_MODULES),
            "portal_host": _portal_host(),
        },
    )


__all__ = ["card_page", "card_index_page", "CARD_MODULES", "INDEX_MODULES"]
