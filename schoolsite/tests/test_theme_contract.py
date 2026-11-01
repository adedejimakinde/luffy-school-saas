"""What every theme must do, held for every theme in `schoolsite.themes.THEMES`.

`docs/school-sites.md` §3.3. A theme is a directory of templates and one
stylesheet; adding one adds nothing here, and every test below runs on it:

1. every section kind, in every variant, draws, for a school with everything,
   a school with almost nothing, and a school whose names are long;
2. its templates mark nothing safe, run no script, and name no other host;
3. a page weighs under the 150 KB budget, asks for nothing off the school's
   host, and costs a fixed number of queries at either school;
4. its fonts carry the Nigerian alphabets (§11.2), or the gap is named here.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.html import escape

from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from tests import glyphs
from tests.test_budget import BUDGET, STATIC, _ASSET, served_files, urls_in_css
from website.crawlers import ICONS

from schoolsite import render, sections
from schoolsite.demo import publish_demo_site
from schoolsite.models import PageKey, SectionKind
from schoolsite.themes import THEMES

THEME_DIR = Path(settings.BASE_DIR) / "schoolsite" / "templates" / "schoolsite" / "themes"
PORTAL = "app.classnode.testserver"
HOSTS = ("st-marys.classnode.testserver", "grace.classnode.testserver")

#: One valid example of each kind, through `sections.clean` so it is what a school could store.
EXAMPLES = {
    SectionKind.HERO: {"heading": "Welcome", "subheading": "A school in Ibadan",
                       "buttons": [{"label": "Apply", "link": "/admissions/"}]},
    SectionKind.CREST_MOTTO: {"motto": "بِسْمِ ٱللَّٰهِ", "language": "ar", "translation": "In the name of God",
                              "founded": 1962},
    SectionKind.PRINCIPAL_MESSAGE: {"name": "Alhaji Musa", "title": "Principal",
                                    "message": "Welcome.\n\nOur doors are open."},
    SectionKind.FACTS: {"items": [{"figure": "98%", "label": "WAEC credits"}, {"figure": "1962", "label": "Founded"}]},
    SectionKind.NEWS: {"count": 3},
    SectionKind.GALLERY: {"album": 1, "count": 6},
    SectionKind.ADMISSIONS_CTA: {"heading": "Admissions", "session": "2027/2028", "open": True,
                                 "closes": "2027-04-30"},
    SectionKind.CONTACT_MAP: {"whatsapp": "0803 000 0000", "latitude": 7.38, "longitude": 3.9},
    SectionKind.TEXT: {"heading": "Our story", "body": "Founded in 1962."},
}

LONG_NAME = "Federal Government Girls' College, Abuloma, Port Harcourt, Rivers State"
LONG_MOTTO = {"motto": "Ìmọ̀ ni agbára, ìwà ni ẹwà", "language": "yo",
              "translation": "Knowledge is power, character is beauty", "founded": 1975}


def _fetched(html):
    """The page without its canonical link, which names an address and fetches nothing."""
    return re.sub(r'<link rel="canonical"[^>]*>', "", html)


def snapshot(pages, theme="starter"):
    return {"theme": theme, "options": {}, "footer": {}, "pages": [
        {"key": key, "enabled": key in pages or key == PageKey.HOME, "title": "", "description": "",
         "sections": [{"id": i + 1000 * n, **section} for i, section in enumerate(pages.get(key, []))]}
        for n, key in enumerate(PageKey.values)
    ]}


def section(kind, variant, data=None):
    return {"kind": kind, "variant": variant, "data": sections.clean(kind, data or EXAMPLES[kind])}


def every_kind_in_every_variant():
    """Each kind × variant on a page it may sit on; a hero only first, one per page."""
    pages = {key: [] for key in PageKey.values}
    heroes = iter(PageKey.values)
    for kind, variants in sections.VARIANTS.items():
        for variant in variants:
            if kind == SectionKind.HERO:
                pages[next(heroes)].insert(0, section(kind, variant))
            else:
                key = next(k for k in PageKey.values if k in sections.ALLOWED_ON[kind])
                pages[key].append(section(kind, variant))
    return pages


@override_settings(ALLOWED_HOSTS=[".classnode.testserver", "testserver"])
class ContractSetUp(TestCase):
    @classmethod
    def setUpTestData(cls):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

    def setUp(self):
        self.schools = []
        for (name, slug, schema), host in zip((("St Mary's College", "st-marys", "st_marys"),
                                               ("Grace Academy", "grace", "grace")), HOSTS):
            school = make_school(name, slug, schema)
            Domain.objects.create(tenant=school, domain=host, is_primary=True)
            self.schools.append((school, host))

    def tearDown(self):
        connection.set_schema_to_public()

    def draw(self, theme, pages, key, school=None):
        school = school or self.schools[0][0]
        revision = SimpleNamespace(number=1, snapshot=snapshot(pages, theme), published_at=timezone.now())
        with connected_to(school):
            return render.draw(school, revision, key, HOSTS[0])


class EveryKindInEveryVariantDrawsTests(ContractSetUp):
    def test_every_theme_draws_every_kind_and_variant_on_every_page(self):
        pages = every_kind_in_every_variant()
        for theme in THEMES:
            for key in PageKey.values:
                with self.subTest(theme=theme, page=key):
                    drawn = self.draw(theme, pages, key)
                    self.assertIsNotNone(drawn)
                    self.assertIn("</footer>", drawn.html)
                    self.assertEqual(drawn.html.count("<h1"), 1)

    def test_every_theme_has_a_part_for_every_kind(self):
        for theme in THEMES:
            for kind in SectionKind.values:
                with self.subTest(theme=theme, kind=kind):
                    self.assertTrue((THEME_DIR / theme / "parts" / f"{kind}.html").is_file())

    def test_a_school_with_almost_nothing_still_draws_a_whole_page(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                drawn = self.draw(theme, {}, PageKey.HOME)
                self.assertIn("<h1 class=\"page-title\">St Mary&#x27;s College</h1>", drawn.html)
                self.assertNotIn("<nav", drawn.html)  # one page is no menu

    def test_long_names_and_mottos_are_drawn_whole(self):
        school = self.schools[0][0]
        school.name = LONG_NAME
        school.save()
        pages = {PageKey.HOME: [section(SectionKind.CREST_MOTTO, "default", LONG_MOTTO)]}
        for theme in THEMES:
            with self.subTest(theme=theme):
                html = self.draw(theme, pages, PageKey.HOME, school).html
                self.assertIn("Federal Government Girls&#x27; College, Abuloma, Port Harcourt, Rivers State", html)
                self.assertIn('<p class="motto-words" lang="yo">Ìmọ̀ ni agbára, ìwà ni ẹwà</p>', html)

    def test_news_and_a_gallery_with_nothing_published_draw_nothing(self):
        pages = {PageKey.HOME: [section(SectionKind.NEWS, "default"), section(SectionKind.GALLERY, "grid")]}
        for theme in THEMES:
            with self.subTest(theme=theme):
                html = self.draw(theme, pages, PageKey.HOME).html
                self.assertNotIn("<section", html)


class TheTemplatesAreSafeTests(ContractSetUp):
    def test_nothing_is_marked_safe_no_script_runs_and_no_other_host_is_named(self):
        for theme in THEMES:
            for path in sorted((THEME_DIR / theme).rglob("*.html")):
                text = path.read_text()
                with self.subTest(theme=theme, template=path.name):
                    self.assertNotIn("|safe", text)
                    self.assertNotIn("mark_safe", text)
                    self.assertNotRegex(text, r"autoescape\s+off")
                    # Structured data, and the site's own module from `static/` (the
                    # gallery and the hero video, §4.3): no other script, none inline.
                    self.assertNotRegex(
                        text,
                        r"<script(?![^>]*application/ld\+json)(?! type=\"module\" src=\"\{% static 'schoolsite/site-app\.js' %\}\"></script>)",
                    )
                    self.assertNotRegex(text, r'\sstyle="')
                    self.assertNotRegex(text, r'\son[a-z]+="')
                    self.assertNotRegex(text, r'(?:src|<link[^>]*href)="(?:https?:)?//')


class UnderTheBudgetTests(ContractSetUp):
    def setUp(self):
        super().setUp()
        for school, _ in self.schools:
            principal = User.objects.create_user(f"{school.slug}-principal", "a-long-password-1")
            grant_membership(principal, school, Role.PRINCIPAL)
            with connected_to(school):
                publish_demo_site(principal, school)
        self.served = served_files()

    def assets_of(self, html):
        found = [self.served[url] for url in _ASSET.findall(_fetched(html)) if url in self.served]
        for path in list(found):
            if path.endswith(".css"):
                found.extend(urls_in_css(path, text=html))
        return sorted(set(found))

    def test_every_page_weighs_under_150_kb_and_asks_nothing_of_another_host(self):
        for _, host in self.schools:
            for path in ("/", "/about/", "/admissions/", "/contact/"):
                response = self.client.get(path, HTTP_HOST=host)
                html = response.content.decode()
                assets = self.assets_of(html)
                weight = len(response.content) + sum((STATIC / a).stat().st_size for a in assets)
                with self.subTest(host=host, path=path):
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("schoolsite/starter.css", assets)
                    self.assertIn("web/fonts/hanken-grotesk-400.woff2", assets)
                    self.assertLess(weight, BUDGET, f"{path} weighs {weight} bytes")
                    for url in _ASSET.findall(_fetched(html)):
                        if url not in ICONS:
                            self.assertTrue(url.startswith(settings.STATIC_URL) or url.startswith("data:"), url)

    def test_each_theme_stylesheet_is_within_its_30_kb(self):
        for key, theme in THEMES.items():
            with self.subTest(theme=key):
                self.assertLess((STATIC / theme.stylesheet).stat().st_size, 30 * 1024)

    def test_a_page_costs_the_same_queries_at_both_schools_drawn_and_from_the_cache(self):
        from django.core.cache import caches

        counts = []
        for _, host in self.schools:
            caches["sites"].clear()
            with CaptureQueriesContext(connection) as cold:
                self.client.get("/about/", HTTP_HOST=host)
            with CaptureQueriesContext(connection) as warm:
                self.client.get("/about/", HTTP_HOST=host)
            counts.append((len(cold), len(warm)))
        # Drawn: the tenant, the published revision, the card's look (read for
        # the key and twice by `results.look`) and the portal's hostname, for
        # the Sign in menu. From the cache: the tenant, the revision and the
        # look for the key. Each after its search path.
        self.assertEqual(counts, [(12, 6), (12, 6)])


class TheNigerianAlphabetsTests(ContractSetUp):
    """No theme is excused: every letter of §11.2 is drawn by the theme's own fonts."""

    def test_every_themes_fonts_carry_every_letter_between_them(self):
        from fontTools.ttLib import TTFont

        for key, theme in THEMES.items():
            held = set()
            for font in theme.fonts:
                held |= set(TTFont(STATIC / font).getBestCmap())
            with self.subTest(theme=key):
                self.assertEqual(
                    sorted(f"U+{ord(c):04X}" for c in glyphs.CHARACTERS if ord(c) not in held), []
                )

    def test_a_page_with_every_letter_draws_with_the_design_stack_and_no_exception(self):
        """The page's text is in the design's font stack, which names both families."""
        pages = {PageKey.HOME: [section(SectionKind.TEXT, "default", {"body": "\n".join(glyphs.NAMES)})]}
        pages[PageKey.ABOUT] = pages[PageKey.HOME]
        for theme in THEMES:
            with self.subTest(theme=theme):
                html = self.draw(theme, pages, PageKey.ABOUT).html
                for name in glyphs.NAMES:
                    self.assertIn(escape(name), html)
        self.assertRegex((STATIC / "web" / "design.css").read_text(), r'--font:\s*"Hanken Grotesk",\s*"Noto Sans"')
