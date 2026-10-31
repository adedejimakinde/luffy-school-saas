"""Every path a school's own host routes, in the one of two kinds it belongs to.

A school's host serves two things from one namespace: the portal its staff,
parents and students sign in to, and, later, the school's public website
(`docs/school-sites.md`). They must never trade places. A search engine may only
ever be let into the website, and the website may only ever have the paths the
note fixes for it, so that no page of it can land on `/home/` (the staff
dashboard), `/register/` (the attendance register) or `/sit/` (the exam door).

So every first path segment `urls.py` routes is named here, once, as one or the
other, and `schools/tests/test_paths.py` fails on a route that is neither, on a
name that is both, and on a name here that nothing routes.

- **`PUBLIC_SITE`**: the website's paths. The only ones that may be indexed, and
  even then only for a response its view marks (`website.crawlers`). Today only
  the root is routed, and it is not marked: every school host is noindex.
- **`PORTAL`**: everything the host already routes for signed-in people and for
  the doors with no session (the result checker, the demo's sign-in pages).
  Never indexed, whatever a view says.
- **`RESERVED`**: names held for work not yet built. Routed now, to a 404
  (`schools.views.reserved`), so nothing else can take them and nothing is
  served there by accident. Never indexed. When the work is built, its name
  moves from here to `PORTAL` in the same change that routes the real view.
"""

#: `docs/school-sites.md` §2.1. `""` is the root. `pages` holds the pages a
#: school makes itself, at `/pages/<slug>/` (§2.1.1). `robots.txt` is the site's
#: own file for crawlers, never itself indexed.
PUBLIC_SITE = frozenset(
    {"", "about", "admissions", "news", "gallery", "contact", "pages", "media", "sitemap.xml", "robots.txt"}
)

PORTAL = frozenset(
    {
        "absences",
        "api",
        "bank",
        "broadsheet",
        "cards",
        "check",
        "comments",
        "exam-slips",
        "fees",
        # A school's private files: photos, signatures, documents (`files.views`).
        "files",
        "help",
        "home",
        "marking",
        "notices",
        "ogsera",
        "promotion",
        "register",
        "results",
        "roll",
        "setup",
        "sign-in",
        "sign-out",
        "staff",
        "staff-sign-in",
        "start",
        "subject-teachers",
        "sw.js",
        "teaching",
        "timetable",
        # The school's website editor and its preview (docs/school-sites.md, PR 4).
        "website",
    }
)

#: Each held name, and what it is held for.
RESERVED = {
    "sit": "the CBT exam door (docs/cbt.md, CBT PR 4)",
    "applicants": "the admissions list (docs/school-sites.md, PR 9b)",
}

#: What `website.crawlers` keeps out of a search engine on a school's host
#: whatever the response says, and what `robots.txt` there names.
NEVER_INDEXED = PORTAL | frozenset(RESERVED)


def first_segment(path: str) -> str:
    """`"sit"` for `/sit/` and `/sit/a/b`, `""` for `/`, `"sw.js"` for `/sw.js`."""
    return path.lstrip("/").split("/", 1)[0]


def is_public_site(path: str) -> bool:
    """Whether `path` is one of the website's, and so ever allowed to be indexed."""
    segment = first_segment(path)
    return segment in PUBLIC_SITE and segment not in NEVER_INDEXED


def is_public_site_request(request) -> bool:
    """Is this a request for a page of a school's public website, on that school's host?

    What every layer that would otherwise read the session asks first
    (`accounts.middleware`, `blog.middleware`, `schools.sessions`): a public
    page is the same for everybody, signed in or not, so nothing on its way
    reads who is asking, refuses a stranger, or writes a cookie back. The
    portal and Classnode's own site are never a school's host.
    """
    from django.db import connection
    from django_tenants.utils import get_public_schema_name

    tenant = getattr(connection, "tenant", None)
    on_a_school = tenant is not None and tenant.schema_name != get_public_schema_name()
    return on_a_school and is_public_site(request.path)


def robots_path(segment: str) -> str:
    """The prefix `robots.txt` disallows for a segment: `/sit/`, but `/sw.js`."""
    return f"/{segment}" if "." in segment else f"/{segment}/"


__all__ = [
    "NEVER_INDEXED",
    "PORTAL",
    "PUBLIC_SITE",
    "RESERVED",
    "first_segment",
    "is_public_site",
    "is_public_site_request",
    "robots_path",
]
