"""What every page on this platform needs from the server, and nothing else.

Project-level, beside `api.py` and `urls.py`, because it is not any one app's:
the report card page is `results`', the sign-in page is `accounts`', and the
rule below is the same rule for both. Put in one app it would be imported
across an app boundary by the other, which is the shape that turns two apps
into one with extra steps.
"""

import json

from django.conf import settings
from django.templatetags.static import static


def import_map(*modules: str) -> str:
    """The hashed URL for every module a page loads, keyed by what it asks for.

    **This exists because `collectstatic` does not rewrite `import`
    statements.** It rewrites `{% static %}` in templates and `url()` in
    stylesheets, and that is all: a hashed `app.4f21c0.js` still contains
    `from "./api.js"`, which the browser resolves against the document's static
    path to the *unhashed* copy. That copy is served, so nothing looks broken —
    and that is the problem. The entry point is cache-busted and everything it
    imports is not, so a deploy can hand a browser today's entry point against
    yesterday's module out of its own cache, and the symptom is a page that is
    subtly wrong for one person and fine for everybody else.

    An import map is the fix that needs no bundler. Keys are the URLs the
    relative imports resolve to; values are what `{% static %}` resolves to,
    hashed where the storage hashes. Under plain storage — development and the
    test suite — key and value are identical and the map is a no-op, which is
    exactly right where nothing is hashed.

    Takes static paths as they are served (`"web/html.js"`, `"card/app.js"`),
    because that is what both halves of the map are derived from. `STATIC_URL`
    is read rather than assumed, so a deployment serving assets from another
    prefix gets a map that matches its own imports.

    Each page lists **every module it loads, including the ones its modules
    import**. A map that covers only the entry point would compile and serve
    and lose the cache-busting it exists to provide; `test_pages.py` walks the
    `import` graph from each entry point and refuses a page whose map has a
    hole in it.
    """
    prefix = settings.STATIC_URL or "/"
    return json.dumps(
        {"imports": {f"{prefix}{path}": static(path) for path in modules}}, indent=2
    )


__all__ = ["import_map"]
