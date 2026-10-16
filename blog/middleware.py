"""A blog account reaches the blog, and nothing else on the platform.

A writer or an editor (`accounts.User.blog_role`) signs in on the portal, and
the session cookie is the platform's (`SESSION_COOKIE_DOMAIN`), so it travels
to every school's host and to `/platform/` like anybody's. This is what stops
it there, for every request, in one place:

- **On a school's host**, every path is refused, whatever else is true of the
  login. Two other rules already keep a blog account out (it can hold no
  membership, by a trigger, and it is never platform staff, by a check), and
  this does not lean on either: a school's data is three rules away.
- **On the portal**, only the blog's own pages (`/write/`), the CSRF token
  and signing out answer. `/platform/`, its handover, its API, the admin, the
  doors and everything a school's pages ask the portal for are refused.
- **On classnode.co** nothing is asked: it is public, and asking would read a
  session on every page of the public site.

Refused with Django's 403 (`accounts.views.refused`, which prints the sentence
for `accounts.refusals.BlogAccountOnly`), before any view runs, so
no school, no list and no name is read on the way. Placed after
`AuthenticationMiddleware` and before `SchoolAccessMiddleware`.
"""

from django.conf import settings
from django.db import connection
from django_tenants.utils import get_public_schema_name

from accounts.refusals import BlogAccountOnly

#: What a blog account may open on the portal. Everything else is refused.
PORTAL_PATHS = ("/write/", "/api/csrf/", "/api/logout/")

REFUSED = "This account is for Classnode's blog only."


def _allowed_on_portal(path: str) -> bool:
    if path.startswith(PORTAL_PATHS):
        return True
    return bool(settings.DEBUG and path.startswith("/dev/outbox/"))


class BlogAccountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "urlconf", None) == settings.SITE_URLCONF:
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.blog_role:
            tenant = getattr(connection, "tenant", None)
            on_portal = tenant is None or tenant.schema_name == get_public_schema_name()
            if not on_portal:
                raise BlogAccountOnly(REFUSED)
            if not _allowed_on_portal(request.path):
                raise BlogAccountOnly(REFUSED)
        return self.get_response(request)
