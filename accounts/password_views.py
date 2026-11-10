"""The two "Forgot password" pages. `docs/sign-in-page.md`, "Forgot password".

`/forgot-password/` asks for a link and `/reset-password/<token>/` is where the
link lands. The rules are `accounts.password_reset`'s, where they hold for any
caller; these are the two pages around them.

**Plain forms, drawn here, and no module.** The sign-in doors are shells drawn
by a module because they talk to an API with several answers. These have one
field and one answer each, so they are a form and a POST: nothing to load,
nothing to wait for, and they work on a phone whose browser has given up on
scripts. Django's own CSRF check covers both (`CsrfViewMiddleware`), and a
failed one is `accounts.views.csrf_failed`'s page.

**On every host, in that host's look, and every link relative.** On a school's
host the pages wear the school (`views._door_brand`), speak for its members
alone (`request.school`), and send the reader back to a door on the same host:
nothing here names another host, so nobody is carried from their school to
`app.<domain>` (#334).

**`no-store` on both.** The page a link opens is served from an address that is
a password until it is used, as an invitation's is (`views.invitation_page`),
so no cache keeps a copy.

**And the referrer policy is left as the site's, `same-origin`
(`settings.SECURE_REFERRER_POLICY`), on purpose.** That already keeps the
address from every other origin ("Powered by Classnode" is the one link off the
host). `no-referrer` looks stricter and breaks the page: under it a browser
sends `Origin: null` with the form's POST, and Django's CSRF check refuses a
null origin, so nobody could choose a password. The test client sends no
`Origin` at all and cannot see that; `tests/ui/password_reset.test.js` posts
the form in a real browser, and `test_password_reset.py` pins the header.
"""

from django.contrib.auth.password_validation import password_validators_help_texts
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from . import password_reset
from .views import _door_brand

#: The door a "back to sign in" link goes to: where the reader came from, when
#: they came from the parents' door, else the door a password is typed at. A
#: closed list, so `?from=` can never be a link to anywhere else.
BACK = {"sign-in": "/sign-in/"}
PASSWORD_DOOR = "/staff-sign-in/"


def _back(request) -> tuple[str, str]:
    """`(from, href)`: the door to go back to, and the key that names it."""
    came_from = request.POST.get("from") or request.GET.get("from") or ""
    if came_from in BACK:
        return came_from, BACK[came_from]
    return "", PASSWORD_DOOR


def _page(request, template, context, *, status=200):
    came_from, back = _back(request)
    response = render(
        request,
        template,
        {
            **_door_brand(request),
            "from": came_from,
            "back": back,
            "minutes": password_reset.minutes(),
            **context,
        },
        status=status,
    )
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["GET", "POST"])
def forgot_password_page(request):
    """Ask for a reset link. One sentence back, whatever was typed.

    The answer to a POST is the same page, with the same status and the same
    words, for an account that was emailed, one that was not, and nobody at
    all (`password_reset.SENT`). What was typed is not shown back: the page
    after a POST is the same bytes for everybody.

    The one thing told apart is an empty box, which is said under the box: it
    says nothing about anybody, and "we've sent a link" to nothing typed would
    be a sentence that is not true of anyone.
    """
    if request.method == "POST":
        # No NUL (Postgres refuses one in a string, which would be a 500 that
        # only some inputs get) and no more than an address can be long.
        identifier = (request.POST.get("identifier") or "").replace("\x00", "").strip()[:254]
        if not identifier:
            return _page(
                request,
                "accounts/forgot_password.html",
                {"error": "Type the email address or phone number your school has for you."},
            )
        password_reset.request_reset(request, identifier, school=getattr(request, "school", None))
        return _page(request, "accounts/forgot_password.html", {"sent": password_reset.SENT})
    return _page(request, "accounts/forgot_password.html", {})


@require_http_methods(["GET", "POST"])
def reset_password_page(request, token):
    """Where a reset link lands: choose a new password, or be told the link is dead.

    A dead link is one page and one status (404), whatever killed it. A good
    one shows the form; a POST that works changes the password, signs every
    session of that person out (`password_reset.complete`), and goes to the
    door a password is typed at, **on this host**: the redirect is a path.
    """
    school = getattr(request, "school", None)
    if password_reset.holder(token, school=school) is None:
        return _dead_link(request)
    context = {"rules": password_validators_help_texts()}

    if request.method == "POST":
        password = request.POST.get("password") or ""
        again = request.POST.get("password_again") or ""
        if not password:
            context["error"] = "Type a new password."
        elif password != again:
            context["error"] = "The two passwords are not the same. Type them again."
        else:
            try:
                password_reset.complete(request, token, password, school=school)
            except password_reset.LinkNotValid:
                return _dead_link(request)
            except password_reset.WeakPassword as exc:
                context["error"] = " ".join(exc.messages)
            else:
                response = HttpResponseRedirect(PASSWORD_DOOR)
                response["Cache-Control"] = "no-store"
                return response

    return _page(request, "accounts/reset_password.html", context)


def _dead_link(request):
    return _page(
        request,
        "accounts/reset_password.html",
        {"dead": password_reset.LINK_NOT_VALID},
        status=404,
    )


__all__ = ["forgot_password_page", "reset_password_page"]
