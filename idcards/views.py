"""The two pages: the staff page that prints cards, and the page a card's QR code opens.

## The print page is a shell

A frame, a stylesheet and a few ES modules, with **no `login_required`**,
because a redirect on a guessable URL is an oracle. `idcards.api` asks who is
asking before it reads anything, and answers 403 to everybody but the principal,
the vice principal (academic) and the administrator.

## The verification page is public, and says almost nothing

`/verify/<token>/` is what the QR code on the back of a card opens. It is for
anybody with a phone: a gate guard, a bus marshal, an examiner. It is served on
the **school's own host** and reads only that school's schema, so a card issued
by another school has no row here and is refused. It shows the child's name,
class and photo and whether the card is valid or expired, and nothing else:
no admission number, no date of birth, no contact, no date even. What it may say
is `idcards.cards.Verification`, a dataclass with exactly those fields, and the
template is handed that object and nothing it could print more from.

It is never cached (validity changes with the date and with the roll), is not
indexed, and sends no referrer, so the token does not travel on to a link.
"""

import pages
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_safe

from schools.brand import classnode_href, for_request
from schools.hosts import sign_in_host

from . import cards

#: The print page's modules, entry point last.
ID_CARDS_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/picker.js",
    "id-cards/api.js",
    "id-cards/states.js",
    "id-cards/app.js",
)


def id_cards_page(request):
    """The frame for `/id-cards/`: choose a class, choose the children, print."""
    return render(
        request,
        "idcards/page.html",
        {
            "import_map": pages.import_map(*ID_CARDS_MODULES),
            "portal_host": sign_in_host(request),
        },
    )


@require_safe
def verify_page(request, token):
    """What a card's QR code opens: valid or expired, with the child's name, class and photo.

    A 404 with a plain sentence for a token this school never issued, which is
    also what a card from another school gets: the page does not say whether
    some other school issued it.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("Cards are checked on each school's own address.")
    result = cards.verification(token, school)
    response = render(
        request,
        "idcards/verify.html",
        {
            "result": result,
            "door": True,
            "brand": for_request(request, door=True),
            "classnode_href": classnode_href(),
        },
        status=200 if result is not None else 404,
    )
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


__all__ = ["ID_CARDS_MODULES", "id_cards_page", "verify_page"]
