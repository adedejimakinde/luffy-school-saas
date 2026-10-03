"""The service worker, as `/sw.js`.

`docs/offline.md` slice S5, D10. The worker's logic is `sync/worker.js`;
this view puts a `CONFIG` in front of it saying which pages and which static
files make up the shell, and serves the two as one script. The worker's source
is `sync/worker.js`, beside this file and not under `static/`: it is a classic
script served at `/sw.js`, not a module any page imports.

## Served from the root, by the host the phone is on

A worker's scope is the directory it is served from, so it cannot be served
from `/static/`: it would control nothing at `/marking/`. It is a route of
`urls.py`, which every host serves, and the portal's copy is harmless for the
reason `gradebook.views` gives the marking frame: it holds nothing.

## The shell is derived, never listed

The static files are the modules and stylesheets the two pages already name for
their own import maps (`MARKING_MODULES`, `REGISTER_MODULES`), looked up through
`static()` exactly as the pages look them up, so the hashed names a deploy
produces are the names the worker keeps. A third list written out here would be
a list that could miss the module somebody adds next month, and the page would
fail on it only for a phone with no connection.

## No caller's data in it

The script is the same bytes for every school's host and for a caller with no
session. It is not rendered from a request, and `no-cache` makes the browser
check for a new one each time (a worker that was cached for a day would be a
deploy that took a day).
"""

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.templatetags.static import static
from django.views.decorators.http import require_GET

from attendance.views import REGISTER_MODULES
from gradebook.views import MARKING_MODULES

#: The two pages the worker keeps, by path.
PAGES = ("/marking/", "/register/")

#: Stylesheets and fonts the two pages draw with besides their modules.
STYLES = (
    "web/design.css",
    "marking/marking.css",
    "register/register.css",
    "web/fonts/hanken-grotesk-400.woff2",
    "web/fonts/hanken-grotesk-700.woff2",
)


def shell_paths():
    """Every static path the two pages need, once each, in a stable order."""
    seen = []
    for path in (*MARKING_MODULES, *REGISTER_MODULES, *STYLES):
        if path not in seen:
            seen.append(path)
    return seen


SOURCE = Path(__file__).parent / "worker.js"


def config():
    prefix = settings.STATIC_URL or "/"
    shell = [static(path) for path in shell_paths()]
    source = SOURCE.read_text()
    version = hashlib.sha256((source + "\n".join(shell)).encode()).hexdigest()[:12]
    return {
        "version": version,
        "pages": list(PAGES),
        "shell": shell,
        "static": prefix,
        # Hashed names never change their bytes, so the worker may keep them.
        "hashed": static("web/html.js") != f"{prefix}web/html.js",
    }


@require_GET
def service_worker(request):
    source = SOURCE.read_text()
    body = f"const CONFIG = {json.dumps(config(), indent=2)};\n\n{source}"
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    # The script sits at the root, so its scope already is; said anyway so a
    # move to another path cannot silently narrow it to nothing.
    response["Service-Worker-Allowed"] = "/"
    return response
