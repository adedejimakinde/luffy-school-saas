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
from schools.hosts import portal_host

#: Every module the card page loads, entry point last.
#:
#: Listed rather than globbed, because a directory listing would decide what a
#: page loads at runtime and a stray file would join it silently.
CARD_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "card/api.js",
    "card/render.js",
    "card/states.js",
    "card/app.js",
)

#: The index page's own. It shares `web/` with the card page and the two
#: sign-in pages — one escape rule, one CSRF story and one sign-out for every
#: page, which is what `settings.STATICFILES_DIRS` argues for.
INDEX_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "index/states.js",
    "index/app.js",
)

#: The approval chain page's own. Staff, not family — the first page in this
#: app that is. It shares `web/` with every other page on the platform.
CHAIN_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "results/api.js",
    "results/states.js",
    "results/app.js",
)


def card_page(request, student_membership_id: int, term_id: int):
    """The frame for one card. Takes two integers and trusts neither.

    `render()` rather than a `TemplateView`, because there is no dispatch to
    customise and a class would be three lines of ceremony around one call.

    It reads one row it did not use to — the portal's hostname, for the two
    states that have to send a reader back to sign-in. See
    `schools.hosts.portal_host()`.
    Still no card data of any kind: who may read this card is
    `GET /api/results/cards/<child>/<term>/`'s question.
    """
    return render(
        request,
        "results/card_page.html",
        {
            "student_membership_id": student_membership_id,
            "term_id": term_id,
            "import_map": pages.import_map(*CARD_MODULES),
            "portal_host": portal_host(),
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
            "portal_host": portal_host(),
        },
    )


#: The comments page's own modules.
COMMENTS_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "comments/api.js",
    "comments/states.js",
    "comments/app.js",
)


def comments_page(request):
    """The frame for writing the two remarks. Reads one row, holds no remark.

    The fourth staff surface. A shell, like the three before it: who may sign
    which remark is `comments.write_as()`'s question, asked against the
    placement it writes with, and a view that rendered the card server-side
    would be a second place asking it.
    """
    return render(
        request,
        "results/comments_page.html",
        {
            "import_map": pages.import_map(*COMMENTS_MODULES),
            "portal_host": portal_host(),
        },
    )


def chain_page(request):
    """The frame for the approval chain. Reads one row, holds no result.

    The third staff surface, after the register and the marking sheet, and the
    first staff page in an app whose other two are family ones. Like them it is
    a **shell**: who may take which step is `results.services`' question, asked
    on the row read under the lock, and a view that rendered the chain
    server-side would be a second place asking it.

    **No `login_required`**, for the reason the card page gives: a redirect on
    a guessable URL is an oracle. The fetch inside the page meets the question.
    """
    return render(
        request,
        "results/chain_page.html",
        {
            "import_map": pages.import_map(*CHAIN_MODULES),
            "portal_host": portal_host(),
        },
    )


#: The broadsheet page's own modules.
BROADSHEET_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/signout.js",
    "broadsheet/api.js",
    "broadsheet/states.js",
    "broadsheet/app.js",
)


def broadsheet_page(request):
    """The frame for broadsheets and the overview. Holds no child and no number.

    A shell like the chain's, and for the same reasons: who may read a
    position is `results.api._require_position_authority()`'s question, and
    no `login_required`, because a redirect on a guessable URL is an oracle.

    **The one thing it says is whether this host is a school's.** The routes
    behind it answer a flat 404 both to somebody who may not read and to the
    portal, where there are no results at all — deliberately the same answer —
    so the page cannot tell those apart from the fetch and is told here.
    """
    return render(
        request,
        "results/broadsheet_page.html",
        {
            "import_map": pages.import_map(*BROADSHEET_MODULES),
            "portal_host": portal_host(),
            "on_school": getattr(request, "school", None) is not None,
        },
    )


__all__ = [
    "broadsheet_page",
    "card_page",
    "card_index_page",
    "chain_page",
    "comments_page",
    "CARD_MODULES",
    "INDEX_MODULES",
    "CHAIN_MODULES",
    "COMMENTS_MODULES",
    "BROADSHEET_MODULES",
]
