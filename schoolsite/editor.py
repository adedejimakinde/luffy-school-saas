"""The website editor and its preview, on the school's own host. `docs/school-sites.md` PR 4.

- **`/website/`** is the editor's frame, like every other portal page: a shell
  whose modules ask `/api/website/` who is asking before anything is shown
  (`schoolsite.api`). No `login_required`, for the oracle reason the other
  frames give.
- **`/website/photos/`** is Photos and albums (PR 5), a frame of its own the
  same way: uploading, describing, cropping, arranging, publishing albums and
  taking pictures down. The editor's section forms choose from what is here.
- **`/website/preview/…`** draws the *draft* through the same templates as the
  live site (`render.draw_snapshot`), any page of it, switched on or off, under
  a "Preview: not published" bar, with its links kept inside the preview. Only
  for whoever may edit: signed out is sent to the staff sign-in and back,
  signed in and not an editor is the portal's 403. Never indexed (`noindex`
  here, and `website.crawlers` keeps every `/website/` path out of a search
  engine), never cached: `no-store`, and nothing kept on the server.

- **`/website/pictures/<key>/<variant>`** sends a website picture to whoever may
  edit the site, published or not: what the preview draws pictures from, and the
  editor's thumbnails. Only a key that is one of this school's website pictures,
  looked up in this school's schema; every "no" is a 404, and it is never cached
  by anybody else. The public is sent a picture only on `/media/`, once published.

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

from files import service as files
from files import views as file_views

from . import access, render as site_render
from .models import PageKey, SitePicture
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

#: Photos and albums' modules (PR 5), entry point last: a frame of its own, so
#: neither it nor the editor passes the 150 KB a page may cost (`tests/test_budget.py`).
PHOTOS_MODULES = (
    "web/html.js",
    "web/http.js",
    "site-editor/api.js",
    "site-editor/photos-api.js",
    "site-editor/pictures.js",
    "site-editor/photos-app.js",
)

NOINDEX = "noindex, nofollow"


def photos_page(request):
    """The frame for `/website/photos/`. Its modules ask `/api/website/` before they draw anything."""
    return render(
        request,
        "schoolsite/photos_page.html",
        {"import_map": pages.import_map(*PHOTOS_MODULES), "portal_host": portal_host()},
    )


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


def _preview(request, key=None, slug=None, album=None):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("A school's website is previewed on the school's own address.")
    if not request.user.is_authenticated:
        return _sign_in_and_back(request)
    if not access.can_edit(request.user, school):
        raise PermissionDenied("The website's preview is for whoever may edit it.")
    drawn = site_render.draw_snapshot(
        school, snapshot(), key, split_domain_port(request.get_host())[0], slug=slug, preview=True, album=album,
        map_open=request.GET.get("map") == "1" and album is None,
    )
    if drawn is None:
        raise Http404("There is no such page in the draft.")
    response = HttpResponse(drawn.html, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = NOINDEX
    response["Content-Security-Policy"] = drawn.csp
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


@require_safe
def preview_album(request, slug):
    """An album's page as it would be published now, for whoever may edit the site."""
    return _preview(request, album=slug)


@require_safe
def picture(request, key, variant):
    """A website picture, published or not, for this school's editors. Every refusal is a 404."""
    school = getattr(request, "school", None)
    if school is None or not access.can_edit(request.user, school):
        raise Http404("No such file.")
    if not SitePicture.objects.filter(file_key=key).exists():
        raise Http404("No such file.")
    stored = files.find(key)
    if stored is None or stored.state != "ready":
        raise Http404("No such file.")
    return file_views.send(stored, variant, cache_control=file_views.PRIVATE)


__all__ = [
    "EDITOR_MODULES", "PHOTOS_MODULES", "editor_page", "photos_page", "picture", "preview", "preview_album", "preview_custom_page", "preview_page",
]
