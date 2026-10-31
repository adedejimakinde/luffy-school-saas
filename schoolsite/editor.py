"""The website editor and its preview, on the school's own host. `docs/school-sites.md` PR 4.

- **`/website/`** is the editor's frame, like every other portal page: a shell
  whose modules ask `/api/website/` who is asking before anything is shown
  (`schoolsite.api`). No `login_required`, for the oracle reason the other
  frames give.
- **`/website/preview/…`** draws the *draft* through the same templates as the
  live site (`render.draw_snapshot`), any page of it, switched on or off, under
  a "Preview: not published" bar, with its links kept inside the preview. Only
  for whoever may edit: signed out is sent to the staff sign-in and back,
  signed in and not an editor is the portal's 403. Never indexed (`noindex`
  here, and `website.crawlers` keeps every `/website/` path out of a search
  engine), never cached: `no-store`, and nothing kept on the server.

Unlike the public pages, these read the session: `website` is a portal path
(`schools.paths.PORTAL`), so the middleware reads who is asking as it does on
`/home/`.
"""

from urllib.parse import quote

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.http.request import split_domain_port
from django.shortcuts import render
from django.views.decorators.http import require_safe

from schools.hosts import portal_host
import pages

from . import access, render as site_render
from .models import PageKey
from .services import snapshot

#: The editor's modules, entry point last.
EDITOR_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/picker.js",
    "site-editor/api.js",
    "site-editor/forms.js",
    "site-editor/states.js",
    "site-editor/app.js",
)

NOINDEX = "noindex, nofollow"


def editor_page(request):
    """The frame for `/website/`. The modules ask `/api/website/` before they draw anything."""
    return render(
        request,
        "schoolsite/editor_page.html",
        {"import_map": pages.import_map(*EDITOR_MODULES), "portal_host": portal_host()},
    )


def _sign_in_and_back(request):
    portal = portal_host()
    back = quote(request.build_absolute_uri(request.get_full_path()), safe="")
    door = f"//{portal}/staff-sign-in/" if portal else "/staff-sign-in/"
    return HttpResponseRedirect(f"{door}?next={back}")


def _preview(request, key=None, slug=None):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("A school's website is previewed on the school's own address.")
    if not request.user.is_authenticated:
        return _sign_in_and_back(request)
    if not access.can_edit(request.user, school):
        raise PermissionDenied("The website's preview is for whoever may edit it.")
    drawn = site_render.draw_snapshot(
        school, snapshot(), key, split_domain_port(request.get_host())[0], slug=slug, preview=True
    )
    if drawn is None:
        raise Http404("There is no such page in the draft.")
    response = HttpResponse(drawn.html, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = NOINDEX
    response["Content-Security-Policy"] = site_render.csp(drawn.style)
    return response


@require_safe
def preview(request):
    return _preview(request, PageKey.HOME)


@require_safe
def preview_page(request, key):
    if key not in PageKey.values or key == PageKey.HOME:
        raise Http404("There is no such page in the draft.")
    return _preview(request, key)


@require_safe
def preview_custom_page(request, slug):
    return _preview(request, slug=slug)


__all__ = ["EDITOR_MODULES", "editor_page", "preview", "preview_custom_page", "preview_page"]
