"""Every page's import map, checked against the imports its modules actually make.

Project-level because `pages.import_map()` is, and because the claim spans three
pages in two apps: the sign-in page (`accounts`), and the card and index pages
(`results`). A per-app copy of this would be three copies of one rule.

## What is being refused

`collectstatic` hashes filenames and rewrites `{% static %}` and stylesheet
`url()`. It does **not** rewrite `import` statements. So a page whose map covers
only its entry point still works — the browser resolves `./api.js` to the
unhashed copy, which is served — and quietly loses cache-busting for every
module behind the entry point. A deploy can then pair a new entry point with an
old module out of the browser's own cache, and the symptom is a page that is
wrong for one person and right for everybody else.

The tests below are what make that impossible to ship: they read the `import`
statements out of the source, follow them, and require every module a page can
reach to be in that page's map.
"""

import json
import posixpath
import re
from pathlib import Path

from django.conf import settings
from django.templatetags.static import static
from django.test import SimpleTestCase

import pages
from accounts.views import MODULES as SIGN_IN_MODULES
from results.views import CARD_MODULES, INDEX_MODULES

#: The tree that is served, which is also the tree on disk — see
#: `settings.STATICFILES_DIRS` for why those two being the same is the whole
#: reason relative imports can work in a browser *and* under `node --test`.
STATIC = Path(settings.BASE_DIR) / "static"

#: Each page, by the name a failure should say out loud.
PAGES = {
    "sign-in": SIGN_IN_MODULES,
    "card": CARD_MODULES,
    "index": INDEX_MODULES,
}

#: `from "./x.js"` and `from "../web/x.js"` — the only import shape these
#: modules use, and the only one a browser resolves without a map entry.
_IMPORT = re.compile(r'from\s+"(\.[^"]+)"')


def imports_of(served_path: str) -> set[str]:
    """The modules `served_path` imports, as served paths.

    Resolved the way a browser resolves them — against the importing module's
    own URL directory — with `posixpath`, because a served path is a URL path
    and stays `/`-separated whatever the operating system is. Because the disk
    tree mirrors the served tree, the same arithmetic answers for both.
    """
    source = (STATIC / served_path).read_text()
    here = posixpath.dirname(served_path)
    return {
        posixpath.normpath(posixpath.join(here, rel)) for rel in _IMPORT.findall(source)
    }


def reachable(entry: str) -> set[str]:
    """Every module reachable from `entry`, including itself. Handles cycles."""
    seen, queue = set(), [entry]
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        queue.extend(imports_of(module))
    return seen


class EveryPagesMapCoversItsWholeGraphTests(SimpleTestCase):
    """The assertion that makes `MODULES` true rather than merely maintained."""

    def test_the_entry_point_is_last_in_every_list(self):
        """A convention, and it is load-bearing for readability rather than for
        the browser: the list reads as "what this page is built from, and then
        the thing that starts it"."""
        for page, modules in PAGES.items():
            with self.subTest(page=page):
                self.assertTrue(modules[-1].endswith("app.js"), modules)

    def test_every_module_a_page_can_reach_is_in_its_map(self):
        for page, modules in PAGES.items():
            with self.subTest(page=page):
                self.assertEqual(
                    reachable(modules[-1]),
                    set(modules),
                    "the page's map does not cover every module it imports",
                )

    def test_every_module_on_disk_belongs_to_some_page(self):
        """An orphan module is either dead code or a page that forgot it.

        Both are worth failing on: the first is a file nobody loads, and the
        second is the cache-busting hole this file exists to refuse.
        """
        on_disk = {str(path.relative_to(STATIC)) for path in STATIC.rglob("*.js")}
        listed = {module for modules in PAGES.values() for module in modules}

        self.assertEqual(on_disk, listed)

    def test_each_key_is_the_url_a_relative_import_resolves_to(self):
        """A key the browser never asks for remaps nothing."""
        for page, modules in PAGES.items():
            imports = json.loads(pages.import_map(*modules))["imports"]
            with self.subTest(page=page):
                self.assertEqual(len(imports), len(modules))
                for path in modules:
                    key = f"{settings.STATIC_URL}{path}"
                    self.assertIn(key, imports)
                    self.assertEqual(imports[key], static(path))

    def test_the_shared_modules_really_are_shared(self):
        """`web/` exists so that one escape rule serves every page.

        If this ever fails because a page stopped importing `web/html.js`, the
        question to ask is whether that page grew its own escaping — which is
        the duplication `settings.STATICFILES_DIRS` was changed to prevent.
        """
        for page, modules in PAGES.items():
            with self.subTest(page=page):
                self.assertIn("web/html.js", modules)
