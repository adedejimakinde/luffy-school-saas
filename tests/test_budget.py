"""The speed budget: what a page may cost the person opening it.

The people this platform is for open it on a mid-range Android phone, on a
metered connection, often a slow one. So every page is held to four limits,
and a change that breaks one fails here rather than in somebody's data bundle:

1. **Under 150 KB**, counting everything the page asks for before it can draw:
   the HTML, every stylesheet (the print one too — a browser fetches it), every
   module in its import map, and both font files. Uncompressed bytes, so the
   limit does not lean on the server's compression to be met.
2. **No CDN.** Every asset comes from the school's own host, under
   `STATIC_URL`: no `//other.host/…` in a `src` or `href`, no `@import`, and
   no `url()` that leaves the static tree.
3. **No JS framework.** The modules are this repository's own: no bare import
   specifier (`from "react"`) anywhere in `static/`, and no script on a page
   that is not a module from `static/` or its import map.
4. **A fixed query count per page.** Each frame's queries are pinned, and must
   be the same at two schools — a page whose cost depends on which school
   opens it is a page whose cost grows with a school.

Frames only. What a page's modules then fetch is the API's cost, and the API
routes each have their own tests; pinning those here too is the follow-up this
file's `QUERIES` comment names.
"""

import json
import posixpath
import re
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.templatetags.static import static
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain, School
from schools.tests.tenants import make_school
from website.crawlers import ICONS

STATIC = Path(settings.BASE_DIR) / "static"

#: 150 KB, the budget the design was given.
BUDGET = 150 * 1024

PORTAL = "testserver"
SCHOOLS = (("St Mary's", "st-marys", "st_marys"), ("Grace Academy", "grace", "grace"))

#: The portal's own pages, opened by somebody not yet signed in.
PORTAL_PAGES = ("/sign-in/", "/staff-sign-in/", "/invitations/not-a-token/", "/platform/")

#: A school's pages, opened by a member of staff there.
SCHOOL_PAGES = (
    "/home/",
    "/setup/",
    "/roll/",
    "/roll/import/",
    "/staff/",
    "/register/",
    "/absences/",
    "/marking/",
    "/results/",
    "/broadsheet/",
    "/comments/",
    "/fees/",
    "/bank/",
    "/timetable/",
    "/cards/",
    "/cards/1/1/",
    "/check/",
    "/notices/settings/",
    "/promotion/",
    "/ogsera/",
    "/teaching/",
    "/subject-teachers/",
    "/exam-slips/",
    "/help/",
    # The website editor (docs/school-sites.md PR 4), and its photos and albums (PR 5).
    "/website/",
    "/website/photos/",
    "/",
)

#: What each frame costs the database, signed in, at either school. Eight
#: statements, each after the `SET search_path` django-tenants issues before
#: it: the tenant for this hostname, the session, the user, their roles here,
#: the portal's hostname (for the states that link back to sign-in), and the
#: session written back in its savepoint (`SESSION_SAVE_EVERY_REQUEST`). None
#: of it is the page's own; a change here is a change to what every page load
#: costs, and should be one somebody meant.
#:
#: The frames carry no data, so this is the floor. What each page's modules
#: fetch after it draws is the API's cost, and pinning those per page, at two
#: sizes of school, is the follow-up to this file.
QUERIES = {path: 16 for path in SCHOOL_PAGES}
#: The school's public page, before the school has published its website: the
#: tenant for this hostname, whether there is a published revision, its crest
#: and colour (the row, read twice by `results.look.for_site`) and the portal's
#: hostname, each after its search path. No session, user or roles: a page of
#: the public website reads none of them (`schools.paths.is_public_site_request`).
QUERIES["/"] = 10
#: The dashboard draws its figures server-side too (`docs/dashboard.md`), and
#: does not ask for the portal's hostname, which only its signed-out state
#: needs. These schools have no students, so it is the set-up checklist: one
#: aggregate statement and its search path, never cached. A school with
#: students costs three statements on a cold cache and none on a warm one
#: (`home.tests.test_dashboard.ThreeStatementsAndThenNoneTests`).
QUERIES["/home/"] = 16
#: These logins are teachers in their first fourteen days, so Home also asks
#: whether each has taken a register and entered a mark yet, for the first-days
#: card (`onboarding.first`): one statement and its search path.
QUERIES["/home/"] += 2
#: Help and next steps draws tips and support, and reads nothing of its own;
#: like Home it does not ask for the portal's hostname.
QUERIES["/help/"] = 14
#: These logins are teachers, whom the principal may have named exam officer, so
#: the menu asks whether they are one (`cbt.access.menu_keys()`): one statement and
#: its search path, once per page. The principal, the administrator, a bursar and a
#: parent are never asked, and cost what they did; nor are the pages with no staff
#: menu (the public page, the cards and the result checker).
for _path in SCHOOL_PAGES:
    if _path not in ("/", "/cards/", "/cards/1/1/", "/check/"):
        QUERIES[_path] += 2

_ASSET = re.compile(r'<(?:link|script|img|iframe|source|video|audio)\b[^>]*?\b(?:src|href)="([^"]*)"', re.I)
_IMPORT_MAP = re.compile(r'<script type="importmap">(.*?)</script>', re.S)
_SCRIPT = re.compile(r"<script\b([^>]*)>", re.I)
_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
#: Every specifier a module asks for: `import … from "x"`, `export … from "x"`,
#: `import "x"` and `import("x")`, statements only — not prose in a comment.
_SPECIFIER = re.compile(
    r"""^\s*(?:import|export)\b[^;'"]*?\bfrom\s*["']([^"']+)["']"""
    r"""|^\s*import\s*["']([^"']+)["']"""
    r"""|\bimport\(\s*["']([^"']+)["']""",
    re.M,
)
_EXTERNAL = re.compile(r"^(?:[a-z]+:)?//", re.I)


def served_files():
    """Every file under `static/`, keyed by the URL a template renders for it."""
    return {
        static(str(path.relative_to(STATIC))): path.relative_to(STATIC).as_posix()
        for path in STATIC.rglob("*")
        if path.is_file()
    }


_FACE = re.compile(r"@font-face\s*{(.*?)}", re.S)
_RANGE = re.compile(r"U\+([0-9A-Fa-f]+)(?:-([0-9A-Fa-f]+))?")


def _faces_a_page_asks_for(css, text):
    """`css` without the `@font-face` rules whose `unicode-range` holds no character of `text`.

    A browser fetches a face with a `unicode-range` only for a page that draws a
    character in it, so a page with none of the Hausa hooks never asks for the
    Noto Sans that draws them (`docs/design.md`). A face with no range is always asked for.
    """

    def keep(match):
        spec = re.search(r"unicode-range:\s*([^;]+);", match.group(1))
        if spec is None:
            return match.group(0)
        ranges = [(int(a, 16), int(b or a, 16)) for a, b in _RANGE.findall(spec.group(1))]
        wanted = any(low <= ord(c) <= high for c in set(text) for low, high in ranges)
        return match.group(0) if wanted else ""

    return _FACE.sub(keep, css)


def urls_in_css(relative, text=None):
    """What a stylesheet pulls in, as static paths beside it.

    With `text`, only what a page drawing that text asks for (`_faces_a_page_asks_for`);
    without it, every `url()`, for the tests that hold them all to the same rules.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / relative).read_text(), flags=re.S)
    if text is not None:
        css = _faces_a_page_asks_for(css, text)
    here = posixpath.dirname(relative)
    return [posixpath.normpath(posixpath.join(here, url)) for url in _URL.findall(css)]


class SpeedBudgetSetUp(TestCase):
    @classmethod
    def setUpTestData(cls):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

        cls.hosts = {}
        for name, slug, schema in SCHOOLS:
            school = make_school(name, slug, schema)
            host = f"{slug}.{PORTAL}"
            Domain.objects.create(tenant=school, domain=host, is_primary=True)
            teacher = grant_membership(
                User.objects.create_user(f"{slug}-teacher", "a-long-password-1", full_name="T"),
                school,
                Role.TEACHER,
            )
            cls.hosts[host] = teacher.user
        cls.served = served_files()

    def tearDown(self):
        # A request to a school's host leaves the connection on its schema.
        connection.set_schema_to_public()

    def pages(self):
        """(host, path, user) for every page, at both schools."""
        for path in PORTAL_PAGES:
            yield PORTAL, path, None
        for host, user in self.hosts.items():
            for path in SCHOOL_PAGES:
                yield host, path, user
            # The 403 page: signed in, but at the other school.
            stranger = next(u for h, u in self.hosts.items() if h != host)
            yield host, "/register/", stranger

    def open(self, host, path, user):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)
        return self.client.get(path, HTTP_HOST=host)

    def assets_of(self, html):
        """Every static path the page will fetch, fonts included."""
        found = []
        for url in _ASSET.findall(html):
            if url in self.served:
                found.append(self.served[url])
        for block in _IMPORT_MAP.findall(html):
            for url in json.loads(block)["imports"].values():
                found.append(self.served[url])
        for path in list(found):
            if path.endswith(".css"):
                found.extend(urls_in_css(path, text=html))
        return sorted(set(found))


class EveryPageIsUnderBudgetTests(SpeedBudgetSetUp):
    def test_every_page_weighs_under_150_kb(self):
        for host, path, user in self.pages():
            response = self.open(host, path, user)
            html = response.content.decode()
            assets = self.assets_of(html)
            weight = len(response.content) + sum((STATIC / a).stat().st_size for a in assets)
            with self.subTest(host=host, page=path, status=response.status_code):
                self.assertIn(response.status_code, (200, 403))
                if response.status_code == 200:
                    self.assertIn("web/design.css", assets)
                self.assertLess(
                    weight, BUDGET, f"{path} weighs {weight} bytes: {', '.join(assets)}"
                )

    def test_the_picker_comes_whole_or_not_at_all(self):
        """`web/picker.js` draws with `web/picker.css`'s rules, and that stylesheet
        draws every select: a page with one and not the other shows a picker
        with no styles, or a select styled for a picker that never opens."""
        carried = 0
        for host, path, user in self.pages():
            response = self.open(host, path, user)
            assets = self.assets_of(response.content.decode())
            with self.subTest(host=host, page=path):
                self.assertEqual("web/picker.js" in assets, "web/picker.css" in assets, assets)
                carried += "web/picker.js" in assets
        self.assertTrue(carried, "no page carries the picker")

    def test_the_budget_counts_the_fonts_and_the_modules(self):
        """The control for the one above: an asset list that came back empty
        would pass any budget."""
        response = self.open(next(iter(self.hosts)), "/cards/1/1/", next(iter(self.hosts.values())))
        assets = self.assets_of(response.content.decode())

        for expected in (
            "web/design.css",
            "web/fonts/hanken-grotesk-400.woff2",
            "web/fonts/hanken-grotesk-700.woff2",
            "card/card.css",
            "card/print.css",
            "card/app.js",
            "web/html.js",
        ):
            self.assertIn(expected, assets)


class AFaceWithARangeIsCountedOnlyWhereItIsUsedTests(SpeedBudgetSetUp):
    """The control for counting the Hausa fallback by use: the count is not just ignoring it."""

    FRAME = '<link rel="stylesheet" href="%s"><body>%s'

    def assets_for(self, body):
        return self.assets_of(self.FRAME % (static("web/design.css"), body))

    def test_a_page_with_no_hausa_hook_does_not_ask_for_the_noto_faces(self):
        assets = self.assets_for("<p>Ọláòlúwa Adéṣínà, ṣ ẹ ọ ị ụ ₦125,000</p>")
        self.assertIn("web/fonts/hanken-grotesk-400.woff2", assets)
        self.assertIn("web/fonts/hanken-grotesk-700.woff2", assets)
        self.assertFalse([a for a in assets if "noto-sans" in a], assets)

    def test_a_page_with_one_asks_for_both_weights_of_them(self):
        for hook in "ɓɗƙƴƁƊƘƳǹǸ":
            with self.subTest(hook=hook):
                assets = self.assets_for(f"<p>Ba{hook}a</p>")
                self.assertIn("web/fonts/noto-sans-hausa-400.woff2", assets)
                self.assertIn("web/fonts/noto-sans-hausa-700.woff2", assets)

    def test_the_stylesheets_own_urls_are_all_still_counted_where_the_rules_are_held(self):
        """`urls_in_css()` with no text is every `url()`: the off-host and framework tests read it so."""
        self.assertIn("web/fonts/noto-sans-hausa-400.woff2", urls_in_css("web/design.css"))


class NoCdnAndNoFrameworkTests(SpeedBudgetSetUp):
    def test_every_asset_a_page_names_is_on_its_own_host(self):
        for host, path, user in self.pages():
            html = self.open(host, path, user).content.decode()
            with self.subTest(host=host, page=path):
                for url in _ASSET.findall(html):
                    self.assertNotRegex(url, _EXTERNAL, "an asset from another host")
                    # The icons are the one exception, and still this host's:
                    # fixed names at its root (`website.crawlers.ICONS`), fetched
                    # after the page has drawn, so not in its weight either.
                    if url not in ICONS:
                        self.assertTrue(url.startswith(settings.STATIC_URL), url)

    def test_every_script_is_a_module_or_the_map_that_resolves_them(self):
        for host, path, user in self.pages():
            html = self.open(host, path, user).content.decode()
            with self.subTest(host=host, page=path):
                for attrs in _SCRIPT.findall(html):
                    self.assertRegex(attrs, r'type="(module|importmap)"', attrs)

    def test_no_stylesheet_imports_or_reaches_off_the_host(self):
        for css in STATIC.rglob("*.css"):
            relative = css.relative_to(STATIC).as_posix()
            with self.subTest(stylesheet=relative):
                self.assertNotIn("@import", css.read_text())
                for url in urls_in_css(relative):
                    self.assertNotRegex(url, _EXTERNAL)
                    self.assertTrue((STATIC / url).is_file(), url)

    def test_no_module_imports_a_package(self):
        """A bare specifier is a package — which is what a framework arrives as."""
        for module in STATIC.rglob("*.js"):
            with self.subTest(module=module.relative_to(STATIC).as_posix()):
                specifiers = [s for match in _SPECIFIER.findall(module.read_text()) for s in match if s]
                self.assertTrue(specifiers or module.name != "app.js", "the pattern finds imports at all")
                self.assertEqual([s for s in specifiers if not s.startswith(("./", "../"))], [])


class AFixedQueryCountPerPageTests(SpeedBudgetSetUp):
    def test_each_frame_costs_what_it_is_pinned_to_at_both_schools(self):
        for host, user in self.hosts.items():
            for path in SCHOOL_PAGES:
                self.open(host, "/sign-in/", None)  # a fresh client state
                self.client.force_login(user)
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(path, HTTP_HOST=host)
                with self.subTest(host=host, page=path):
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        len(queries),
                        QUERIES[path],
                        "\n".join(q["sql"][:160] for q in queries.captured_queries),
                    )

    def test_every_school_page_has_a_pinned_count(self):
        self.assertEqual(set(QUERIES), set(SCHOOL_PAGES))
