"""What search engines are told, on every host the platform answers.

Only Classnode's public site (`settings.SITE_HOST`) is for a search engine.
Everything else is somebody's school or a door into one: the portal and its
sign-in pages, every school's host (demo schools and test schools are school
hosts too), `/platform/` and `/healthz/`. So the rule is written as default
deny: a response is marked `X-Robots-Tag: noindex, nofollow` unless it comes
from the site host, and every page drawn from `templates/design/head.html`
carries the same in a meta tag unless its view says it is the public site's.

This middleware also answers `/robots.txt` for every host (the site's points to
its sitemap; every other host disallows everything but its icons, `ICONS`,
which are Classnode's mark and nobody's school), and sends `www.` on the
site host to the bare domain over https in one hop. It sits near the top of
the stack, under `/healthz/` alone, so it sees every response, the 404 of a
host nobody owns included, and `schools.health` marks its own answers.
"""

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.http.request import split_domain_port

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
            body = SITE_ROBOTS.format(site_url=site_url()) if on_site else CLOSED_ROBOTS
            response = HttpResponse(body, content_type="text/plain; charset=utf-8")
        else:
            response = self.get_response(request)

        if not on_site:
            response["X-Robots-Tag"] = NOINDEX
        return response


__all__ = ["CLOSED_ROBOTS", "ICONS", "CrawlerMiddleware", "NOINDEX", "site_url"]
