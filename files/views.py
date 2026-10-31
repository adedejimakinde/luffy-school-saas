"""Sending a file: Django decides, Caddy sends.

Two routes on a school's host, and nothing on the portal's:

- **`/media/<key>/<variant>`**, a page of the school's public website
  (`schools.paths.PUBLIC_SITE`): only files marked public (a crest, a published
  website photo). It reads no session and sets no cookie, like every public
  page, and is cached for a year: a key's variants never change.
- **`/files/<key>/<variant>`**, a portal path: private files (a child's photo,
  the principal's signature, a document), for a signed-in member of *this*
  school whose role the kind allows (`files.kinds.OFFICE` by default). Never
  cached by anybody else.

Either way the key is looked up **in the current school's schema only**, so a
key from another school is simply not there: school B's crest asked for on
school A's host is a 404, with or without its key, whoever is signed in. Every
"no" is a 404, so a private file's existence is not given away by a 403.

With `FILES_X_ACCEL` on (production) the response carries no body: it names
the file in `X-Accel-Redirect`, and Caddy's `handle_response` sends it from a
read-only mount of the files directory (deploy/caddy/Caddyfile). Gunicorn never
streams a byte.
"""

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.views.decorators.http import require_http_methods

from . import service, storage
from .kinds import profile_for
from .models import State

YEAR = "public, max-age=31536000, immutable"
PRIVATE = "private, no-store"


def send(stored, variant, *, cache_control, download_name=None):
    """The response that sends `variant` of `stored`, with `cache_control`."""
    if stored is None or stored.state not in (State.READY, State.RETIRED) or not stored.has(variant):
        raise Http404("No such file.")
    relative = storage.relative(stored.schema_name, stored.key, variant)
    content_type = storage.content_type(variant)
    if settings.FILES_X_ACCEL:
        response = HttpResponse(content_type=content_type)
        # A path under Caddy's read-only root, built only from checked names.
        response["X-Accel-Redirect"] = "/" + relative
    else:
        try:
            handle = open(storage.root() / relative, "rb")
        except FileNotFoundError:
            raise Http404("No such file.")
        response = FileResponse(handle, content_type=content_type)
    response["Cache-Control"] = cache_control
    response["X-Content-Type-Options"] = "nosniff"
    # Nothing served from here is a page: no script runs in it, whatever it is.
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; media-src 'self'; sandbox"
    if variant.endswith(".pdf"):
        response["Content-Disposition"] = f'attachment; filename="{download_name or "document.pdf"}"'
    return response


@require_http_methods(["GET", "HEAD"])
def public_file(request, key, variant):
    """A public file of this school. Reads nothing about who is asking."""
    if service.school_here() is None:
        raise Http404("No such file.")
    stored = service.find(key)
    if stored is None or not stored.public:
        raise Http404("No such file.")
    return send(stored, variant, cache_control=YEAR)


def _private_ready(stored):
    """A private file is sent only while it is the current one."""
    return stored is not None and stored.state == State.READY


def may_read(user, school, kind) -> bool:
    if school is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(set(user.roles_at(school)) & profile_for(kind).readers)


@require_http_methods(["GET", "HEAD"])
def private_file(request, key, variant):
    """A file of this school, for its office. Every refusal is a 404."""
    school = service.school_here()
    stored = service.find(key)
    if not _private_ready(stored) or not may_read(request.user, school, stored.kind):
        raise Http404("No such file.")
    return send(stored, variant, cache_control=PRIVATE)


def url_for(stored, variant) -> str:
    """Where a page points for this file: `/media/...` if public, `/files/...` if not."""
    prefix = "media" if stored.public else "files"
    return f"/{prefix}/{stored.key}/{variant}"


__all__ = ["PRIVATE", "YEAR", "may_read", "private_file", "public_file", "send", "url_for"]
