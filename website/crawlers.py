"""What search engines are told, on every host the platform answers.

Only Classnode's public site (`settings.SITE_HOST`) is for a search engine.
Everything else is somebody's school or a door into one: the portal and its
sign-in pages, every school's host (demo schools and test schools are school
hosts too), `/platform/` and `/healthz/`. So the rule is written as default
deny: a response is marked `X-Robots-Tag: noindex, nofollow` unless it comes
from the site host, and every page drawn from `templates/design/head.html`
carries the same in a meta tag unless its view says it is the public site's.

**One exception is designed and not yet used: a school's own website**
(`docs/school-sites.md` §6). On a school's host, a response escapes the header
only when all three hold: its view marked it (`response.indexable = True`), its
path is one of the website's, and it was served for a school, never for the
portal (`schools.paths.is_public_site_request`). Only a published school
website's pages are marked (`schoolsite.views`), so a school that has not
published is noindex exactly as before. No one condition is enough: a marked response on
`/sit/` or any portal path is still noindex, and so is an unmarked root.

This middleware also answers `/robots.txt` for every host. The site's points to
its sitemap. The portal's disallows everything but the icons (`ICONS`, which
are Classnode's mark and nobody's school). Every other host's, a school's or one
with no school behind it (this runs before the host is looked up), says the
same, and also names each path that must stay out of a search engine even once
a school's website is open (`schools.paths.NEVER_INDEXED`), ahead of the
`Disallow: /` that closes the rest. A school that has published its website
answers its own instead (`schoolsite.views.robots`): the same names, no
closing line, and its sitemap. It also sends `www.` on
the site host to the bare domain over https in one hop. It sits near the top of
the stack, under `/healthz/` alone, so it sees every response, the 404 of a
host nobody owns included, and `schools.health` marks its own answers.
"""

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.http.request import split_domain_port

from schools.hosts import portal_host
from schools.paths import NEVER_INDEXED, is_public_site_request, robots_path

NOINDEX = "noindex, nofollow"

#: The files every host serves at its root (`WHITENOISE_ROOT` in settings.py),
#: which a search engine fetches for the icon beside a result.
ICONS = (
    "/favicon.ico",
    "/favicon.svg",
    "/apple-touch-icon.png",
    "/icon-192.png",
    "/icon-512.png",
    "/site.webmanifest",
)

SITE_ROBOTS = "User-agent: *\nAllow: /\n\nSitemap: {site_url}/sitemap.xml\n"
#: The allowances first: a crawler that takes the first matching line, as
#: Python's own `urllib.robotparser` does, then agrees with one that takes the
#: longest, as Google does.
CLOSED_ROBOTS = "User-agent: *\n" + "".join(f"Allow: {path}\n" for path in ICONS) + "Disallow: /\n"
#: `CLOSED_ROBOTS` with the paths a school's host never lets in named before
#: the closing line. The same answer to every crawler today; what changes when
#: a school's website opens is the last line, and these stay.
SCHOOL_ROBOTS = (
    "User-agent: *\n"
    + "".join(f"Allow: {path}\n" for path in ICONS)
    + "".join(f"Disallow: {robots_path(name)}\n" for name in sorted(NEVER_INDEXED))
    + "Disallow: /\n"
)


def site_url():
    """The public site's own address: `https://` and the bare domain."""
    return f"https://{settings.SITE_HOST}"


def _host(request):
    """The request's hostname, lower case and without a port; `""` if refused."""
    try:
        return split_domain_port(request.get_host())[0]
    except DisallowedHost:
        return ""


class CrawlerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        site = getattr(settings, "SITE_HOST", None)
        host = _host(request)
        on_site = bool(site) and host == site

        if site and host == f"www.{site}":
            return HttpResponsePermanentRedirect(f"{site_url()}{request.get_full_path()}")

        if request.path == "/robots.txt":
            if on_site:
                response = _robots(SITE_ROBOTS.format(site_url=site_url()))
            elif host == portal_host():
                response = _robots(CLOSED_ROBOTS)
            else:
                # A school's host answers its own (`schoolsite.views.robots`),
                # open once the school has published; a host with no school
                # behind it, or one that cannot answer, gets the closed one.
                response = self.get_response(request)
                if response.status_code != 200:
                    response = _robots(SCHOOL_ROBOTS)
        else:
            response = self.get_response(request)

        if not on_site and not _a_school_website_page(request, response):
            response["X-Robots-Tag"] = NOINDEX
        return response


def _robots(body):
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def _a_school_website_page(request, response):
    """Whether this is a page of a school's own website its view let be indexed.

    Asked after the response, when the request has been served for a school or
    for nobody: a marked response, on one of the website's paths, served for a
    school (`schools.paths.is_public_site_request`), never for the portal.
    """
    return getattr(response, "indexable", False) is True and is_public_site_request(request)


__all__ = ["CLOSED_ROBOTS", "ICONS", "SCHOOL_ROBOTS", "CrawlerMiddleware", "NOINDEX", "site_url"]
