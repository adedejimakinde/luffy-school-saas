"""Every page's import map, checked against the imports its modules actually make.

Project-level because `pages.import_map()` is, and because the claim spans four
pages in two apps: the two sign-in pages (`accounts`), and the card and index
pages (`results`). A per-app copy of this would be four copies of one rule.

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
from accounts.views import (
    INVITE_MODULES,
    ROLL_IMPORT_MODULES,
    ROLL_MODULES,
    STAFF_MODULES,
    STAFF_PAGE_MODULES,
)
from academics.views import PROMOTION_MODULES, SETUP_MODULES
from schools.views import PLATFORM_MODULES
from blog.write_views import EDITOR_MODULES as BLOG_EDITOR_MODULES
from cbt.views import EXAM_SLIPS_MODULES
from attendance.views import ABSENCE_MODULES, REGISTER_MODULES
from fees.views import BANK_MODULES, FEES_MODULES
from gradebook.views import MARKING_MODULES, SUBJECT_TEACHERS_MODULES, TEACHING_MODULES
from results.views import (
    BROADSHEET_MODULES,
    CARD_MODULES,
    CHAIN_MODULES,
    CHECKER_MODULES,
    COMMENTS_MODULES,
    INDEX_MODULES,
    OGSERA_MODULES,
)
from notices.views import SETTINGS_MODULES
from timetable.views import TIMETABLE_MODULES

#: The tree that is served, which is also the tree on disk — see
#: `settings.STATICFILES_DIRS` for why those two being the same is the whole
#: reason relative imports can work in a browser *and* under `node --test`.
STATIC = Path(settings.BASE_DIR) / "static"

#: Each page, by the name a failure should say out loud.
PAGES = {
    "sign-in": SIGN_IN_MODULES,
    "staff-sign-in": STAFF_MODULES,
    "card": CARD_MODULES,
    "index": INDEX_MODULES,
    "register": REGISTER_MODULES,
    "marking": MARKING_MODULES,
    "results-chain": CHAIN_MODULES,
    "comments": COMMENTS_MODULES,
    "setup": SETUP_MODULES,
    "promotion": PROMOTION_MODULES,
    "platform": PLATFORM_MODULES,
    "roll": ROLL_MODULES,
    "roll-import": ROLL_IMPORT_MODULES,
    "staff": STAFF_PAGE_MODULES,
    "broadsheet": BROADSHEET_MODULES,
    "invite": INVITE_MODULES,
    "absences": ABSENCE_MODULES,
    "fees": FEES_MODULES,
    "bank": BANK_MODULES,
    "timetable": TIMETABLE_MODULES,
    "checker": CHECKER_MODULES,
    "notices-settings": SETTINGS_MODULES,
    "ogsera": OGSERA_MODULES,
    "teaching": TEACHING_MODULES,
    "subject-teachers": SUBJECT_TEACHERS_MODULES,
    "exam-slips": EXAM_SLIPS_MODULES,
    "blog-editor": BLOG_EDITOR_MODULES,
}

#: Pages whose modules build no markup of their own, and so import no escaping
#: (`test_a_page_that_draws_no_markup_imports_no_escaping` says what holds them).
DRAWS_NO_MARKUP = {"blog-editor"}

#: `from "./x.js"` and `from "../web/x.js"`, and `import("../web/x.js")` for
#: the one module a page loads only if it can (`web/picker.js`): a dynamic
#: import resolves through the map like any other.
_IMPORT = re.compile(r'(?:from\s+|\bimport\(\s*)"(\.[^"]+)"')


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
            if page in DRAWS_NO_MARKUP:
                continue
            with self.subTest(page=page):
                self.assertIn("web/html.js", modules)

    def test_a_page_that_draws_no_markup_imports_no_escaping(self):
        """The control for the allowance above: it is used, and only where true.

        The blog editor writes text with `textContent` and puts in only the
        preview the server drew and sanitised (`blog.markdown.render`), so it
        builds no markup of its own to escape. A module there that started
        building HTML from strings would need `web/html.js` like every page.
        """
        for page in DRAWS_NO_MARKUP:
            with self.subTest(page=page):
                self.assertNotIn("web/html.js", PAGES[page])
                for module in PAGES[page]:
                    source = (STATIC / module).read_text()
                    self.assertNotRegex(source, r"innerHTML\s*=\s*`|insertAdjacentHTML|outerHTML")


class EverySelectOpensThePickerTests(SimpleTestCase):
    """A page that draws a `<select>` opens `web/picker.js`'s sheet, not the
    phone's own menu (`docs/design.md`, "The picker"): its map carries the
    module and its entry point starts it on the page's root. A new page with a
    select that forgot either would draw the grey system menu again."""

    def test_a_page_that_draws_a_select_starts_the_picker(self):
        drawing = []
        for page, modules in PAGES.items():
            if not any("<select" in (STATIC / module).read_text() for module in modules):
                continue
            drawing.append(page)
            with self.subTest(page=page):
                self.assertIn("web/picker.js", modules)
                entry = (STATIC / modules[-1]).read_text()
                # Loaded as an enhancement, so a picker that fails to load
                # leaves the page and its system menus working.
                self.assertRegex(
                    entry,
                    r'import\("\.\./web/picker\.js"\)\.then\(\(picker\) => picker\.enhanceSelects\(root\), \(\) => \{\}\);\s*\n\s*mount\(root',
                )
                self.assertNotRegex(entry, r'from "\.\./web/picker\.js"')
        self.assertGreaterEqual(len(drawing), 13, "the pattern finds the selects at all")

    def test_only_a_page_with_a_select_carries_it(self):
        """The picker is weight on a phone's data bundle: no page pays for it unused."""
        for page, modules in PAGES.items():
            if "web/picker.js" not in modules:
                continue
            with self.subTest(page=page):
                self.assertTrue(any("<select" in (STATIC / module).read_text() for module in modules))
