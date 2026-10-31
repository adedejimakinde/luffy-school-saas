"""A school's public website, on the school's own host. `docs/school-sites.md` §6, PR 3.

- **Before the school's first publish** the root is today's page
  (`schools.views.school_site`), drawn exactly as before and still noindex, and
  every other page of the site is a 404, as it was.
- **After it**, each page the school switched on, fixed or its own under
  `/pages/<slug>/`, is drawn from the latest published revision
  (`schoolsite.render`), marked indexable
  (`website.crawlers`), with its Content-Security-Policy, a short public cache
  life and an ETag. A page the school switched off is a 404.

Nothing here reads the session or who is asking: `schools.paths
.is_public_site_request` keeps the middleware from reading it on the way, and
`schools.sessions` keeps a cookie from going back. A drawn page is kept in the
`sites` cache under the school's schema, its revision, what it shows of the
school, the host and the path, so one school's page can never be handed out on
another's host, and a new publish is a new key.
"""

import hashlib
import logging

from django.core.cache import caches
from django.db import connection
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.http.request import split_domain_port
from django.views.decorators.http import require_safe

from results.models import ReportCardSettings
from schools.views import school_site
from schools.paths import NEVER_INDEXED, robots_path
from website.crawlers import ICONS, SCHOOL_ROBOTS

from . import render
from .models import PageKey
from .services import live_revision

log = logging.getLogger(__name__)

#: How long a drawn page is kept, in seconds. A publish is a new key at once;
#: this bounds how long a template change takes to reach every page after a
#: deploy, and how long the portal's address or the crest can lag behind.
CACHE_SECONDS = 600
#: Bumped by hand when the starter theme's templates change what they draw.
GENERATION = 1
#: What a browser and anything between it and us may do with a page.
CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=600"


def _school(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("A school's website is on the school's own address.")
    return school


def _host(request) -> str:
    return split_domain_port(request.get_host())[0]


def _school_key(school) -> str:
    """What the page shows of `School` and the card's look, so editing either is a new key."""
    from django.db.models import Subquery

    from files.models import StoredFile

    # The crest's file key in the same query: a new crest finished by the
    # media worker is a new key, though the settings row did not change.
    crest = StoredFile.objects.filter(
        schema_name=connection.schema_name, slot="crest", state="ready"
    ).values("key")[:1]
    look_updated, crest_key = (
        ReportCardSettings.objects.annotate(crest_key=Subquery(crest))
        .values_list("updated_at", "crest_key")
        .first()
    ) or (None, None)
    shown = "\n".join((school.name, school.about, school.address, school.phone, school.contact_email,
                       str(look_updated), str(crest_key)))
    return hashlib.sha256(shown.encode()).hexdigest()[:16]


def _cached_draw(school, revision, key, host, slug=None):
    page = f"pages/{slug}" if slug is not None else key
    cache_key = (
        f"site:{GENERATION}:{connection.schema_name}:{revision.number}:{_school_key(school)}:{host}:{page}"
    )
    cache = caches["sites"]
    try:
        hit = cache.get(cache_key)
    except Exception:
        # A cache that is down is a slower page, never a broken one.
        log.warning("The sites cache could not be read; drawing the page.", exc_info=True)
        hit = None
    if hit is not None:
        return render.Drawn(*hit)
    drawn = render.draw(school, revision, key, host, slug=slug)
    if drawn is not None:
        try:
            cache.set(cache_key, (drawn.html, drawn.style), CACHE_SECONDS)
        except Exception:
            log.warning("The sites cache could not be written.", exc_info=True)
    return drawn


def _served(request, body, content_type, *, style=None, indexable=True):
    """A public page's response: indexable, cacheable, conditional, and under its CSP."""
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    if etag in [t.strip() for t in request.headers.get("If-None-Match", "").split(",")]:
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(body, content_type=content_type)
    response["ETag"] = etag
    response["Cache-Control"] = CACHE_CONTROL
    if style is not None:
        response["Content-Security-Policy"] = render.csp(style)
    response.indexable = indexable
    return response


def _may_be_indexed(school) -> bool:
    """Classnode's demo school (`School.sales_demo`) publishes a site that is never indexed.

    It sits on the production server beside real schools and must not turn up
    in a search for a real one: its pages go out `noindex` (`website.crawlers`
    adds the header to every response not marked indexable), its robots.txt
    stays closed and it has no sitemap.
    """
    return not school.sales_demo


def _page(request, key, slug=None):
    school = _school(request)
    revision = live_revision(school)
    if revision is None:
        if key == PageKey.HOME:
            return school_site(request)
        raise Http404("This school has not published its website yet.")
    drawn = _cached_draw(school, revision, key, _host(request), slug)
    if drawn is None:
        raise Http404("This page is not on the school's website.")
    return _served(
        request, drawn.html, "text/html; charset=utf-8", style=drawn.style, indexable=_may_be_indexed(school)
    )


@require_safe
def home(request):
    return _page(request, PageKey.HOME)


@require_safe
def about(request):
    return _page(request, PageKey.ABOUT)


@require_safe
def admissions(request):
    return _page(request, PageKey.ADMISSIONS)


@require_safe
def news(request):
    return _page(request, PageKey.NEWS)


@require_safe
def gallery(request):
    return _page(request, PageKey.GALLERY)


@require_safe
def contact(request):
    return _page(request, PageKey.CONTACT)


@require_safe
def custom_page(request, slug):
    """A page the school made itself, at `/pages/<slug>/` (§2.1.1), as it published it."""
    return _page(request, None, slug)


@require_safe
def sitemap(request):
    school = _school(request)
    revision = live_revision(school)
    if revision is None or not _may_be_indexed(school):
        raise Http404("This school has not published its website yet.")
    return _served(request, render.sitemap(revision, _host(request)), "application/xml; charset=utf-8")


def open_robots(host) -> str:
    """A published school's robots.txt: the never-indexed paths named, the rest open, and the sitemap."""
    return (
        "User-agent: *\n"
        + "".join(f"Allow: {path}\n" for path in ICONS)
        + "".join(f"Disallow: {robots_path(name)}\n" for name in sorted(NEVER_INDEXED))
        + f"\nSitemap: https://{host}/sitemap.xml\n"
    )


@require_safe
def robots(request):
    """`/robots.txt` on a school's host: open once the school has published, closed until then.

    `website.crawlers` answers it for every other host, and for this one whenever
    this does not answer with a 200.
    """
    school = _school(request)
    closed = live_revision(school) is None or not _may_be_indexed(school)
    body = SCHOOL_ROBOTS if closed else open_robots(_host(request))
    response = HttpResponse(body, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = CACHE_CONTROL
    return response


__all__ = [
    "about", "admissions", "contact", "custom_page", "gallery", "home", "news", "open_robots", "robots", "sitemap",
]
