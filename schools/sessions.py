"""Django's session middleware, with a session of its own for each school's host.

## Two cookies, because there are two doors

The portal's session (`settings.SESSION_COOKIE_NAME`) is scoped to the platform
domain, so a sign-in on `app.<domain>` reaches every school's host, where
`SchoolAccessMiddleware` asks for a membership. That has not changed.

A sign-in on a school's own host (`<school>.<domain>/staff-sign-in/`) makes a
session in a cookie of its own, `settings.SCHOOL_SESSION_COOKIE_NAME`, with **no
`Domain` attribute**: the browser sends it back to that host and to no other,
not to another school's and not to the portal. The session is also bound to the
school (`schools.session_store.SIGNED_IN_AT`), and the store refuses it on any
other host, whatever cookie it arrives in. A second name rather than the first
cookie scoped two ways: two cookies of one name on one host reach the server in
an order nothing promises.

On a school's host the school's cookie is read first, when it names a live
session; otherwise the portal's, so a teacher signed in on the portal arrives at
her school exactly as before. A new session made on a school's host (a shared
handset's pick, before anybody is signed in) is the school's kind.

## A school's public website is left alone

`SESSION_SAVE_EVERY_REQUEST` slides a signed-in person's session on every
response, which writes the session back and sends its cookie again. On a page of
a school's public website (`schools.paths.is_public_site_request`) that would be
a database write and a `Set-Cookie` on a page that is the same for everybody,
and no cache could keep it. So there, a session nothing read is neither saved
nor sent, and no `Vary: Cookie` is added. The page reads nothing of the session
(`schoolsite.views`), so this changes no answer.
"""

import time
from importlib import import_module

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware as DjangoSessionMiddleware
from django.db import connection
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date
from django_tenants.utils import get_public_schema_name

from .paths import is_public_site_request
from .session_store import PORTAL, SCHOOL, SIGNED_IN_AT


def _store(key, kind, school_id):
    store = import_module(settings.SESSION_ENGINE).SessionStore(key)
    store.kind = kind
    store.school_id = school_id
    return store


def _host_school_id():
    """The school whose host this request is on, or None for the portal and Classnode's site."""
    tenant = getattr(connection, "tenant", None)
    if tenant is None or tenant.schema_name == get_public_schema_name():
        return None
    return tenant.pk


def cookie_of(kind):
    """The cookie's name and `Domain` for a kind of session."""
    if kind == SCHOOL:
        return settings.SCHOOL_SESSION_COOKIE_NAME, None
    return settings.SESSION_COOKIE_NAME, settings.SESSION_COOKIE_DOMAIN


def _live(store) -> bool:
    """Does the store name a session good on this host? Reads it, then forgets it was read."""
    store._get_session()
    store.accessed = False
    return not store.is_empty()


def begin_school_session(request):
    """Sign-in on a school's host happens in a session of the school's kind.

    Called by the doors just before they sign anybody in, or park a pick. A
    portal session the browser brought with it is put aside untouched (it stays
    good on the portal) rather than cycled into the school's: Django's `login()`
    would otherwise flush or re-key it, and that is the portal session.
    """
    session = request.session
    school_id = getattr(session, "school_id", None)
    if school_id is None or getattr(session, "kind", None) == SCHOOL:
        return
    request.session = _store(None, SCHOOL, school_id)


def bind_to_school(request, school):
    """Mark the session just signed in as the school's: good on its host alone."""
    request.session[SIGNED_IN_AT] = school.pk


def signed_in_here(request) -> bool:
    """Was this request's session signed in on this school's own door?"""
    session = getattr(request, "session", None)
    school_id = getattr(session, "school_id", None)
    return school_id is not None and session.get(SIGNED_IN_AT) == school_id


def end_every_session(request):
    """Sign out: the session in use, and on a school's host the portal's beside it.

    On a school's host a browser can hold both, and the school's is the one read.
    Ending only that one would leave the portal's in place, and the next page on
    this host would still be signed in: a Sign out that did not sign out.
    """
    session = request.session
    other = None
    if getattr(session, "kind", None) == SCHOOL:
        other = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    logout(request)
    if other:
        _store(None, PORTAL, None).delete(other)
        request._session_cookies_to_forget = [PORTAL]


class SessionMiddleware(DjangoSessionMiddleware):
    def process_request(self, request):
        school_id = _host_school_id()
        portal_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
        if school_id is None:
            request.session = _store(portal_key, PORTAL, None)
            return
        school_key = request.COOKIES.get(settings.SCHOOL_SESSION_COOKIE_NAME)
        if school_key:
            store = _store(school_key, SCHOOL, school_id)
            # A page of the school's website reads no session, so nothing is
            # probed for it: the school's cookie stands, unread.
            if not portal_key or is_public_site_request(request) or _live(store):
                request.session = store
                return
            # The school's cookie names nothing good here (it lapsed); the
            # portal's may. The lapsed one is cleared on the way out.
            request._session_cookies_to_forget = [SCHOOL]
            request.session = _store(portal_key, PORTAL, school_id)
            return
        request.session = _store(portal_key, PORTAL if portal_key else SCHOOL, school_id)

    def process_response(self, request, response):
        session = getattr(request, "session", None)
        if session is not None and not session.accessed and is_public_site_request(request):
            return response
        for kind in getattr(request, "_session_cookies_to_forget", ()):
            name, domain = cookie_of(kind)
            if name in request.COOKIES:
                response.delete_cookie(
                    name, path=settings.SESSION_COOKIE_PATH, domain=domain, samesite=settings.SESSION_COOKIE_SAMESITE
                )
        return self._save(request, response)

    def _save(self, request, response):
        """Django's `process_response`, with the cookie's name and domain this session's kind."""
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response
        name, domain = cookie_of(getattr(request.session, "kind", None) or PORTAL)
        if name in request.COOKIES and empty:
            response.delete_cookie(
                name, path=settings.SESSION_COOKIE_PATH, domain=domain, samesite=settings.SESSION_COOKIE_SAMESITE
            )
            patch_vary_headers(response, ("Cookie",))
            return response
        if accessed:
            patch_vary_headers(response, ("Cookie",))
        if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
            if request.session.get_expire_at_browser_close():
                max_age = None
                expires = None
            else:
                max_age = request.session.get_expiry_age()
                expires = http_date(time.time() + max_age)
            if response.status_code < 500:
                try:
                    request.session.save()
                except UpdateError:
                    raise SessionInterrupted(
                        "The request's session was deleted before the request completed. "
                        "The user may have logged out in a concurrent request, for example."
                    )
                response.set_cookie(
                    name,
                    request.session.session_key,
                    max_age=max_age,
                    expires=expires,
                    domain=domain,
                    path=settings.SESSION_COOKIE_PATH,
                    secure=settings.SESSION_COOKIE_SECURE or None,
                    httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                    samesite=settings.SESSION_COOKIE_SAMESITE,
                )
                patch_vary_headers(response, ("Cookie",))
        return response


__all__ = [
    "SessionMiddleware",
    "begin_school_session",
    "bind_to_school",
    "cookie_of",
    "end_every_session",
    "signed_in_here",
]
