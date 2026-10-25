"""Django's session middleware, which leaves a school's public website alone.

`SESSION_SAVE_EVERY_REQUEST` slides a signed-in person's session on every
response, which writes the session back and sends its cookie again. On a page of
a school's public website (`schools.paths.is_public_site_request`) that would be
a database write and a `Set-Cookie` on a page that is the same for everybody,
and no cache could keep it. So there, a session nothing read is neither saved
nor sent, and no `Vary: Cookie` is added. Everywhere else this is Django's.

The page reads nothing of the session (`schoolsite.views`), so this changes no
answer. A session that something on the way did read is handled as Django
handles it, so a mistake shows as a cookie in a test rather than a stale login.
"""

from django.contrib.sessions.middleware import SessionMiddleware as DjangoSessionMiddleware

from .paths import is_public_site_request


class SessionMiddleware(DjangoSessionMiddleware):
    def process_response(self, request, response):
        session = getattr(request, "session", None)
        if session is not None and not session.accessed and is_public_site_request(request):
            return response
        return super().process_response(request, response)


__all__ = ["SessionMiddleware"]
