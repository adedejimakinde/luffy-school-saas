"""A school's own pages, the menu that orders them, and the limits on both, at two schools.

`docs/school-sites.md` §2.1.1 and PR 3b. A school makes pages such as Boarding or
Sports from the same safe sections as the fixed six, at `/pages/<slug>/`; it
switches any page on or off but Home, orders them in one menu, and publishes them
like everything else. The draft is the services' alone: who may make, rename,
delete or order pages is who may edit, and only the principal publishes. The
limits, 20 pages and 15 sections a page, are the services' and Postgres's both.
In public, a page is drawn only once it is published and switched on, only on
its own school's host, and is otherwise a 404 and in no menu or sitemap.
"""

import re

from django.db import IntegrityError, connection, transaction

from schools.tests.tenants import connected_to

from schoolsite import services
from schoolsite.errors import NotAllowedToEdit, NotAllowedToPublish, SiteRefused, StaleDraft
from schoolsite.models import CUSTOM_PAGE_SLOTS, MOST_SECTIONS, Page, PageKind, Section, SiteSettings
from schoolsite.render import MENU_ON_A_PHONE
from schoolsite.sections import REFUSED_SLUGS, SectionRefused
from schools.paths import PORTAL, RESERVED

from .test_public import GRACE, ST_MARYS, PublicSiteSetUp
from .test_services import HERO, SiteSetUp

TEXT = {"heading": "Our boarding houses", "body": "Two houses, one for boys and one for girls."}


def settings_version():
    return SiteSettings.objects.get(pk=1).version


def constraints_hold():
    """Check the deferred rules now, as a commit would. A test never commits."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


class CustomPageSetUp(SiteSetUp):
    def make(self, who=None, title="Boarding", slug=None, school=None):
        school = school or self.stmarys
        with connected_to(school):
            return services.create_page_as(
                who or self.principal, school, version=settings_version(), title=title, slug=slug
            )

    def add(self, who, kind="hero", data=None, key="home", school=None, variant=None):
        school = school or self.stmarys
        with connected_to(school):
            return services.add_section_as(
                who, school, key, version=self.page(key, school).version, kind=kind,
                data=HERO if data is None else data, variant=variant,
            )

    def page(self, ref, school=None):
        with connected_to(school or self.stmarys):
            return Page.objects.get(slug=ref) if ref not in ("home", "about", "admissions", "news", "gallery",
                                                              "contact") else Page.objects.get(key=ref)

    def switch(self, ref, on=True, who=None, school=None):
        school = school or self.stmarys
        with connected_to(school):
            return services.save_page_as(
                who or self.principal, school, ref, version=self.page(ref, school).version, enabled=on
            )


class MakingAPageTests(CustomPageSetUp):
    def test_a_page_is_made_switched_off_empty_and_last_in_the_menu(self):
        page = self.make(title="Boarding & Hostel")
        self.assertEqual((page.kind, page.key, page.slug, page.slot), (PageKind.CUSTOM, "", "boarding-hostel", 1))
        self.assertFalse(page.enabled)
        self.assertEqual(page.menu_position, 6)
        self.assertEqual(page.path, "/pages/boarding-hostel/")
        with connected_to(self.stmarys):
            self.assertEqual(page.sections.count(), 0)
            self.assertEqual(Page.objects.order_by("menu_position").last().pk, page.pk)

    def test_the_address_is_the_one_given_else_made_from_the_title(self):
        self.assertEqual(self.make(title="Sports", slug="games").slug, "games")
        self.assertEqual(self.make(title="Ìmọ̀ Club").slug, "imo-club")
        long = self.make(title="A very long title about the many clubs and societies of our school")
        self.assertEqual(long.slug, "a-very-long-title-about-the-many-clubs")
        self.assertLessEqual(len(long.slug), 40)

    def test_a_made_address_another_page_has_gets_a_number_and_a_given_one_is_refused(self):
        self.assertEqual(self.make(title="Clubs").slug, "clubs")
        self.assertEqual(self.make(title="Clubs").slug, "clubs-2")
        self.assertEqual(self.make(title="Clubs!").slug, "clubs-3")
        with self.assertRaisesMessage(SiteRefused, "/pages/clubs/ already"):
            self.make(title="More clubs", slug="clubs")

    def test_an_address_that_is_a_fixed_page_a_reserved_path_or_a_portal_name_is_refused(self):
        for slug in ("home", "about", "admissions", "news", "gallery", "contact", *RESERVED, *PORTAL, "pages"):
            if not re.match(r"^[a-z0-9-]+$", slug):
                continue
            with self.subTest(slug=slug):
                with self.assertRaisesMessage(SectionRefused, "kept for the site's own pages"):
                    self.make(title="A page", slug=slug)
        self.assertLessEqual({"sit", "website", "applicants", "home", "register", "about"}, REFUSED_SLUGS)
        with self.assertRaisesMessage(SectionRefused, "kept for the site's own pages"):
            self.make(title="Contact")
        with connected_to(self.stmarys):
            self.assertEqual(Page.objects.filter(kind=PageKind.CUSTOM).count(), 0)

    def test_an_address_out_of_shape_is_refused(self):
        for slug in ("Boarding_House", "two  words", "-edge", "edge-", "dou--ble", "x" * 41, "", "café"):
            with self.subTest(slug=slug), self.assertRaises(SectionRefused):
                self.make(title="A page", slug=slug)
        self.assertEqual(self.make(title="A page", slug="  Boarding  ").slug, "boarding")
        with self.assertRaises(SectionRefused):
            self.make(title="")
        with self.assertRaisesMessage(SectionRefused, "no letters or numbers"):
            self.make(title="!!!")

    def test_a_stale_list_of_pages_is_refused(self):
        with connected_to(self.stmarys):
            stale = settings_version()
            services.create_page_as(self.principal, self.stmarys, version=stale, title="Sports")
            with self.assertRaises(StaleDraft):
                services.create_page_as(self.principal, self.stmarys, version=stale, title="Clubs")


class TwentyPagesAndFifteenSectionsTests(CustomPageSetUp):
    def test_a_fifteenth_page_of_the_schools_own_is_refused_by_the_service(self):
        for n in range(CUSTOM_PAGE_SLOTS):
            self.make(title=f"Page {n}")
        with self.assertRaisesMessage(SiteRefused, "at most 20 pages"):
            self.make(title="One too many")
        with connected_to(self.stmarys):
            self.assertEqual(Page.objects.count(), 20)
            self.assertEqual(sorted(Page.objects.filter(kind=PageKind.CUSTOM).values_list("slot", flat=True)),
                             list(range(1, CUSTOM_PAGE_SLOTS + 1)))

    def test_a_deleted_page_frees_its_slot(self):
        for n in range(CUSTOM_PAGE_SLOTS):
            self.make(title=f"Page {n}")
        with connected_to(self.stmarys):
            gone = Page.objects.get(slug="page-3")
            services.delete_page_as(self.principal, self.stmarys, "page-3", version=gone.version)
        self.assertEqual(self.make(title="Again").slot, gone.slot)

    def test_postgres_refuses_a_fifteenth_page_and_a_slot_twice_however_it_is_written(self):
        self.make(title="Boarding")
        with connected_to(self.stmarys):
            for slot in (0, CUSTOM_PAGE_SLOTS + 1, 1):
                with self.subTest(slot=slot), self.assertRaises(IntegrityError), transaction.atomic():
                    Page.objects.create(kind=PageKind.CUSTOM, slug=f"by-hand-{slot}", slot=slot,
                                        title="By hand", menu_position=50 + slot)
                    constraints_hold()

    def test_postgres_refuses_a_page_that_is_neither_fixed_nor_the_schools_own(self):
        with connected_to(self.stmarys):
            shapes = (
                dict(kind=PageKind.CUSTOM, slug="about", slot=2, title="x"),
                dict(kind=PageKind.CUSTOM, slug="Bad Slug", slot=2, title="x"),
                dict(kind=PageKind.CUSTOM, slug="ok", key="about", slot=2, title="x"),
                dict(kind=PageKind.CUSTOM, slug="ok", slot=None, title="x"),
                dict(kind=PageKind.FIXED, key="about", slug="about", title="x"),
                dict(kind=PageKind.FIXED, key="boarding", title="x"),
                dict(kind=PageKind.FIXED, key="about", title="x"),
            )
            for n, shape in enumerate(shapes):
                with self.subTest(shape=shape), self.assertRaises(IntegrityError), transaction.atomic():
                    Page.objects.create(menu_position=60 + n, **shape)
                    constraints_hold()

    def test_a_sixteenth_section_is_refused_by_the_service(self):
        for n in range(MOST_SECTIONS):
            self.add(self.principal, kind="admissions_cta", data={"heading": f"Panel {n}"})
        with self.assertRaisesMessage(SiteRefused, f"at most {MOST_SECTIONS} sections"):
            self.add(self.principal, kind="admissions_cta", data={"heading": "One too many"})
        with self.assertRaisesMessage(SiteRefused, f"at most {MOST_SECTIONS} sections"):
            self.add(self.principal)  # a hero, which would push the rest down
        with connected_to(self.stmarys):
            self.assertEqual(Section.objects.filter(page__key="home").count(), MOST_SECTIONS)
            constraints_hold()

    def test_postgres_refuses_a_sixteenth_section_and_two_in_one_place(self):
        self.add(self.principal, kind="admissions_cta", data={"heading": "Panel"})
        with connected_to(self.stmarys):
            home = Page.objects.get(key="home")
            for position in (MOST_SECTIONS, 0):
                with self.subTest(position=position), self.assertRaises(IntegrityError), transaction.atomic():
                    Section.objects.create(page=home, kind="admissions_cta", variant="default",
                                           data={"heading": "By hand"}, position=position)
                    constraints_hold()

    def test_adding_a_hero_and_reordering_leave_one_section_per_place(self):
        for n in range(3):
            self.add(self.principal, kind="admissions_cta", data={"heading": f"Panel {n}"})
        self.add(self.principal)
        with connected_to(self.stmarys):
            constraints_hold()
            home = Page.objects.get(key="home")
            ids = list(home.sections.order_by("position").values_list("id", flat=True))
            services.move_sections_as(self.principal, self.stmarys, "home", [ids[0], *reversed(ids[1:])],
                                      version=home.version)
            constraints_hold()
            self.assertEqual(list(home.sections.order_by("position").values_list("position", flat=True)),
                             [0, 1, 2, 3])


class SectionsOnAPageOfTheSchoolsOwnTests(CustomPageSetUp):
    def test_the_safe_kinds_go_on_and_the_rest_are_refused(self):
        self.make(title="Boarding")
        allowed = {
            "hero": HERO,
            "text": TEXT,
            "facts": {"items": [{"figure": "2", "label": "houses"}, {"figure": "120", "label": "boarders"}]},
            "gallery": {"album": 1},
            "principal_message": {"message": "Welcome to boarding."},
            "admissions_cta": {"heading": "Boarding places for 2027/2028"},
        }
        for kind, data in allowed.items():
            with self.subTest(kind=kind):
                self.add(self.principal, kind=kind, data=data, key="boarding")
        for kind, data in (("news", {"count": 3}), ("contact_map", {}), ("crest_motto", {"motto": "Lux"})):
            with self.subTest(kind=kind), self.assertRaisesMessage(SectionRefused, "cannot go on the Boarding page"):
                self.add(self.principal, kind=kind, data=data, key="boarding")

    def test_add_remove_and_reorder_on_a_custom_page_through_the_same_services(self):
        self.make(title="Sports")
        first = self.add(self.principal, kind="text", data=TEXT, key="sports")
        second = self.add(self.principal, kind="text", data={"body": "Football and athletics."}, key="sports")
        with connected_to(self.stmarys):
            page = Page.objects.get(slug="sports")
            services.move_sections_as(self.principal, self.stmarys, "sports", [second.pk, first.pk],
                                      version=page.version)
            first.refresh_from_db()
            services.remove_section_as(self.principal, self.stmarys, first.pk, version=first.version)
            self.assertEqual(list(page.sections.values_list("id", "position")), [(second.pk, 0)])

    def test_a_button_may_link_to_a_page_the_draft_has_and_never_to_one_it_has_not(self):
        self.make(title="Boarding")
        self.add(self.principal, data={"heading": "Board with us",
                                       "buttons": [{"label": "Boarding", "link": "/pages/boarding/"}]})
        self.add(self.principal, kind="admissions_cta",
                 data={"heading": "Places", "button": "See boarding", "link": "/pages/boarding/"})
        with self.assertRaisesMessage(SiteRefused, "no page at /pages/sports/"):
            self.add(self.principal, kind="admissions_cta",
                     data={"heading": "Places", "link": "/pages/sports/"}, key="about")
        with self.assertRaisesMessage(SectionRefused, "the school's own pages"):
            self.add(self.principal, kind="admissions_cta",
                     data={"heading": "Places", "link": "https://example.com/"}, key="about")
        with self.assertRaisesMessage(SectionRefused, "a page this site does not have"):
            self.add(self.principal, kind="admissions_cta", data={"heading": "Places", "link": "/home/"},
                     key="about")


class RenamingDeletingAndOrderingTests(CustomPageSetUp):
    def test_the_title_changes_and_the_address_changes_only_until_the_first_publish(self):
        page = self.make(title="Boarding")
        with connected_to(self.stmarys):
            page = services.rename_page_as(self.principal, self.stmarys, "boarding", version=page.version,
                                           title="Boarding houses", slug="houses")
            self.assertEqual((page.title, page.slug), ("Boarding houses", "houses"))
        self.switch("houses")
        self.publish(self.principal)
        with connected_to(self.stmarys):
            page = Page.objects.get(slug="houses")
            self.assertTrue(page.ever_published)
            with self.assertRaisesMessage(SiteRefused, "its address stays"):
                services.rename_page_as(self.principal, self.stmarys, "houses", version=page.version, slug="boarding")
            page = services.rename_page_as(self.principal, self.stmarys, "houses", version=page.version,
                                           title="Our boarding houses")
            self.assertEqual((page.title, page.slug), ("Our boarding houses", "houses"))
            with self.assertRaises(SectionRefused):
                services.rename_page_as(self.principal, self.stmarys, "houses", version=page.version, title="")

    def test_a_page_switched_off_when_published_keeps_an_address_fixed(self):
        self.make(title="Boarding")
        self.publish_with_a_change()
        with connected_to(self.stmarys):
            page = Page.objects.get(slug="boarding")
            self.assertFalse(page.ever_published, "published switched off: nobody has had its address")
            services.rename_page_as(self.principal, self.stmarys, "boarding", version=page.version, slug="houses")

    def publish_with_a_change(self):
        self.add(self.principal, kind="admissions_cta", data={"heading": "Places"})
        return self.publish(self.principal)

    def test_a_fixed_page_is_never_renamed_or_deleted_here(self):
        with connected_to(self.stmarys):
            about = Page.objects.get(key="about")
            with self.assertRaisesMessage(SiteRefused, "one of the six"):
                services.rename_page_as(self.principal, self.stmarys, "about", version=about.version, title="Us")
            with self.assertRaisesMessage(SiteRefused, "one of the six"):
                services.delete_page_as(self.principal, self.stmarys, "about", version=about.version)

    def test_a_page_is_deleted_while_unpublished_or_switched_off_and_never_while_live(self):
        self.make(title="Draft only")
        self.switch("draft-only")
        with connected_to(self.stmarys):
            services.delete_page_as(self.principal, self.stmarys, "draft-only",
                                    version=Page.objects.get(slug="draft-only").version)
        self.make(title="Boarding")
        self.add(self.principal, kind="text", data=TEXT, key="boarding")
        self.switch("boarding")
        self.publish(self.principal)
        with connected_to(self.stmarys):
            page = Page.objects.get(slug="boarding")
            with self.assertRaisesMessage(SiteRefused, "Switch it off first"):
                services.delete_page_as(self.principal, self.stmarys, "boarding", version=page.version)
        self.switch("boarding", on=False)
        with connected_to(self.stmarys):
            services.delete_page_as(self.principal, self.stmarys, "boarding",
                                    version=Page.objects.get(slug="boarding").version)
            self.assertFalse(Page.objects.filter(slug="boarding").exists())
            self.assertFalse(Section.objects.filter(page__slug="boarding").exists())
            self.assertEqual(list(Page.objects.values_list("menu_position", flat=True)), list(range(6)))
            constraints_hold()

    def test_the_menu_is_ordered_whole_with_home_first(self):
        self.make(title="Boarding")
        self.make(title="Sports")
        with connected_to(self.stmarys):
            order = ["home", "sports", "about", "boarding", "admissions", "news", "gallery", "contact"]
            services.order_menu_as(self.principal, self.stmarys, order, version=settings_version())
            constraints_hold()
            self.assertEqual([p.ref for p in Page.objects.order_by("menu_position")], order)
            for bad, message in (
                (["sports", "home", *order[2:]], "Home stays first"),
                (order[:-1], "each once"),
                ([*order[:-1], "about"], "each once"),
                ([*order, "nowhere"], "each once"),
            ):
                with self.subTest(order=bad), self.assertRaisesMessage(SiteRefused, message):
                    services.order_menu_as(self.principal, self.stmarys, bad, version=settings_version())
            with self.assertRaises(StaleDraft):
                services.order_menu_as(self.principal, self.stmarys, order, version=settings_version() - 1)


class WhoMayChangeThePagesTests(CustomPageSetUp):
    def attempts(self, who, school):
        """Each page service, as `who`, on `school`'s schema, with whatever version is current."""
        with connected_to(school):
            boarding = Page.objects.filter(slug="boarding").first()
            refs = [p.ref for p in Page.objects.order_by("menu_position")]
            return {
                "make": lambda: services.create_page_as(who, school, version=settings_version(), title="Sports"),
                "rename": lambda: services.rename_page_as(who, school, "boarding", version=boarding.version,
                                                          title="Renamed"),
                "switch": lambda: services.save_page_as(who, school, "boarding", version=boarding.version,
                                                        enabled=True),
                "order": lambda: services.order_menu_as(who, school, [refs[0], *reversed(refs[1:])],
                                                        version=settings_version()),
                "delete": lambda: services.delete_page_as(who, school, "boarding", version=boarding.version),
            }

    def test_nobody_but_the_principal_or_a_delegated_administrator_changes_the_pages(self):
        self.make(title="Boarding")
        refused = [self.admin, self.grace_principal, *self.others.values()]
        for who in refused:
            for name, attempt in self.attempts(who, self.stmarys).items():
                with self.subTest(who=who.username, service=name), connected_to(self.stmarys):
                    with self.assertRaises(NotAllowedToEdit):
                        attempt()
        with connected_to(self.stmarys):
            self.assertEqual(list(Page.objects.filter(kind=PageKind.CUSTOM).values_list("slug", "title")),
                             [("boarding", "Boarding")])

    def test_a_delegated_administrator_changes_the_pages_and_never_publishes_them(self):
        self.make(title="Boarding")
        self.delegate(on=True)
        for name in ("make", "rename", "switch", "order"):
            with self.subTest(service=name), connected_to(self.stmarys):
                self.attempts(self.admin, self.stmarys)[name]()
        with self.assertRaises(NotAllowedToPublish):
            self.publish(self.admin)

    def test_one_schools_editor_never_reaches_anothers_pages_with_the_same_address(self):
        self.make(title="Boarding")
        self.make(title="Boarding", who=self.grace_principal, school=self.grace)
        # Grace's principal, asking about St Mary's on Grace's schema or on St Mary's.
        for schema in (self.grace, self.stmarys):
            for name, attempt in self.attempts(self.grace_principal, self.stmarys).items():
                with self.subTest(schema=schema.schema_name, service=name), connected_to(schema):
                    with self.assertRaises((NotAllowedToEdit, SiteRefused)):
                        attempt()
        # St Mary's principal, naming St Mary's while the connection is on Grace's schema.
        with connected_to(self.grace):
            page = Page.objects.get(slug="boarding")
            with self.assertRaises(NotAllowedToEdit):
                services.rename_page_as(self.principal, self.stmarys, "boarding", version=page.version, title="X")
        self.assertEqual(self.page("boarding", self.grace).title, "Boarding")
        self.assertEqual(self.page("boarding").title, "Boarding")


class TheSnapshotTests(CustomPageSetUp):
    def test_a_publish_keeps_each_pages_kind_address_and_place(self):
        self.make(title="Boarding")
        self.add(self.principal, kind="text", data=TEXT, key="boarding")
        self.switch("boarding")
        live = self.publish(self.principal)
        boarding = [p for p in live.snapshot["pages"] if p["kind"] == "custom"]
        self.assertEqual(len(boarding), 1)
        self.assertEqual({k: boarding[0][k] for k in ("key", "slug", "menu_position", "enabled", "title")},
                         {"key": "", "slug": "boarding", "menu_position": 6, "enabled": True, "title": "Boarding"})
        self.assertIn("boarding", live.summary["pages_on"])
        self.assertEqual(live.snapshot["pages"][0]["key"], "home")


class CustomPagesInPublicTests(PublicSiteSetUp):
    def make(self, who, school, title, *, sections=(), on=True, slug=None):
        with connected_to(school):
            page = services.create_page_as(who, school, version=settings_version(), title=title, slug=slug)
            for kind, data in sections:
                services.add_section_as(who, school, page.slug, version=Page.objects.get(pk=page.pk).version,
                                        kind=kind, data=data)
            if on:
                services.save_page_as(who, school, page.slug, version=Page.objects.get(pk=page.pk).version,
                                      enabled=True)
            return page.slug

    def publish(self, who, school):
        with connected_to(school):
            return services.publish_as(who, school)

    def nav(self, html):
        header = html.split("</header>")[0]
        return re.findall(r'<a href="(/[^"]*)"', header)

    def test_a_published_page_is_drawn_at_its_address_on_its_own_schools_host_only(self):
        self.build(self.principal, self.stmarys, "St Mary's", publish=False)
        self.make(self.principal, self.stmarys, "Boarding", sections=[("text", {"body": "St Mary's boarders."})])
        self.publish(self.principal, self.stmarys)
        self.build(self.grace_principal, self.grace, "Grace", publish=False)
        self.make(self.grace_principal, self.grace, "Boarding", sections=[("text", {"body": "Grace boarders."})])
        self.make(self.grace_principal, self.grace, "Sports", sections=[("text", {"body": "Grace sports."})])
        self.publish(self.grace_principal, self.grace)

        mine, theirs = self.get("/pages/boarding/"), self.get("/pages/boarding/", GRACE)
        self.assertEqual((mine.status_code, theirs.status_code), (200, 200))
        self.assertIn("St Mary&#x27;s boarders.", mine.content.decode())
        self.assertNotIn("Grace", mine.content.decode())
        self.assertIn("Grace boarders.", theirs.content.decode())
        self.assertIn(f'<link rel="canonical" href="https://{ST_MARYS}/pages/boarding/">', mine.content.decode())
        self.assertIn("<title>Boarding | St Mary&#x27;s College</title>", mine.content.decode())
        # Grace's own page is never on St Mary's host, cached or not.
        self.assertEqual(self.get("/pages/sports/", GRACE).status_code, 200)
        self.assertEqual(self.get("/pages/sports/").status_code, 404)
        self.assertNotIn("/pages/sports/", self.get("/").content.decode())
        self.assertNotIn("/pages/sports/", self.get("/sitemap.xml").content.decode())

    def test_a_page_switched_off_or_never_published_is_a_404_and_in_no_menu_or_sitemap(self):
        self.build(self.principal, self.stmarys, "St Mary's", publish=False)
        self.make(self.principal, self.stmarys, "Boarding", sections=[("text", {"body": "Boarders."})])
        self.make(self.principal, self.stmarys, "Alumni", sections=[("text", {"body": "Old students."})], on=False)
        self.publish(self.principal, self.stmarys)
        self.make(self.principal, self.stmarys, "Sports", sections=[("text", {"body": "Games."})])  # after the publish
        home = self.get("/").content.decode()
        sitemap = self.get("/sitemap.xml").content.decode()
        self.assertEqual(self.get("/pages/boarding/").status_code, 200)
        self.assertIn("/pages/boarding/", self.nav(home))
        self.assertIn(f"https://{ST_MARYS}/pages/boarding/", sitemap)
        for slug in ("alumni", "sports"):
            with self.subTest(slug=slug):
                self.assertEqual(self.get(f"/pages/{slug}/").status_code, 404)
                self.assertNotIn(f"/pages/{slug}/", home)
                self.assertNotIn(f"/pages/{slug}/", sitemap)
        # Switched off and published: gone from the site, the menu and the sitemap.
        with connected_to(self.stmarys):
            services.save_page_as(self.principal, self.stmarys, "boarding",
                                  version=Page.objects.get(slug="boarding").version, enabled=False)
            services.publish_as(self.principal, self.stmarys)
        self.assertEqual(self.get("/pages/boarding/").status_code, 404)
        self.assertNotIn("/pages/boarding/", self.get("/").content.decode())
        self.assertNotIn("/pages/boarding/", self.get("/sitemap.xml").content.decode())

    def test_a_fixed_pages_key_or_any_other_address_under_pages_is_a_404(self):
        self.build(self.principal, self.stmarys, "St Mary's")
        for path in ("/pages/about/", "/pages/home/", "/pages/Boarding/", "/pages/", "/pages/sit/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 404)

    def test_before_the_first_publish_no_page_of_the_schools_own_answers(self):
        self.make(self.principal, self.stmarys, "Boarding", sections=[("text", {"body": "Boarders."})])
        self.assertEqual(self.get("/pages/boarding/").status_code, 404)

    def test_the_menu_follows_the_schools_order_with_home_first_and_more_on_a_phone(self):
        self.build(self.principal, self.stmarys, "St Mary's", pages=("about", "admissions", "news", "contact"),
                   publish=False)
        for title in ("Boarding", "Sports"):
            self.make(self.principal, self.stmarys, title, sections=[("text", {"body": title})])
        with connected_to(self.stmarys):
            order = ["home", "boarding", "about", "sports", "admissions", "news", "gallery", "contact"]
            services.order_menu_as(self.principal, self.stmarys, order, version=settings_version())
        self.publish(self.principal, self.stmarys)
        html = self.get("/pages/sports/").content.decode()
        drawn = ["/", "/pages/boarding/", "/about/", "/pages/sports/", "/admissions/", "/news/", "/contact/"]
        nav = html.split("<nav aria-label=\"The school's pages\">")[1].split("</nav>")[0]
        wide = re.findall(r'<li(?: class="wide")?><a href="([^"]+)"', nav.split('<li class="more">')[0])
        self.assertEqual(wide, drawn)
        self.assertEqual(re.findall(r'<li class="wide"><a href="([^"]+)"', nav), drawn[MENU_ON_A_PHONE:])
        self.assertEqual(len(drawn), 7)
        more = nav.split('<li class="more">')[1]
        self.assertIn("<summary>More</summary>", more)
        self.assertEqual(re.findall(r'href="([^"]+)"', more), drawn[MENU_ON_A_PHONE:])
        self.assertIn('<a href="/pages/sports/" aria-current="page">Sports</a>', nav)
        footer = html.split('<footer class="site-footer">')[1]
        self.assertEqual(re.findall(r'href="(/[^"]*)"', footer), drawn)

    def test_five_pages_or_fewer_have_no_more_menu(self):
        self.build(self.principal, self.stmarys, "St Mary's", pages=("about", "contact"), publish=False)
        self.make(self.principal, self.stmarys, "Boarding", sections=[("text", {"body": "Boarders."})])
        self.publish(self.principal, self.stmarys)
        html = self.get("/").content.decode()
        self.assertNotIn('class="more"', html)
        self.assertNotIn('class="wide"', html)

    def test_a_button_to_a_page_that_is_off_or_unpublished_is_left_out(self):
        with connected_to(self.stmarys):
            v = settings_version()
            services.create_page_as(self.principal, self.stmarys, version=v, title="Boarding")
            services.create_page_as(self.principal, self.stmarys, version=settings_version(), title="Sports")
            home = Page.objects.get(key="home")
            services.add_section_as(self.principal, self.stmarys, "home", version=home.version, kind="hero", data={
                "heading": "Welcome", "buttons": [{"label": "Boarding", "link": "/pages/boarding/"},
                                                  {"label": "Sports", "link": "/pages/sports/"}]})
            services.add_section_as(self.principal, self.stmarys, "home",
                                    version=Page.objects.get(key="home").version, kind="admissions_cta",
                                    data={"heading": "Places", "button": "Boarding places", "link": "/pages/sports/"})
            services.save_page_as(self.principal, self.stmarys, "boarding",
                                  version=Page.objects.get(slug="boarding").version, enabled=True)
            services.publish_as(self.principal, self.stmarys)
        html = self.get("/").content.decode()
        main = html.split("<main")[1].split("</main>")[0]
        self.assertIn('href="/pages/boarding/">Boarding</a>', main)
        self.assertNotIn("/pages/sports/", main)
        self.assertNotIn("Boarding places", main)
        self.assertEqual(self.get("/pages/sports/").status_code, 404)

    def test_a_button_to_a_fixed_page_that_is_off_is_left_out_too(self):
        self.build(self.principal, self.stmarys, "St Mary's", pages=())  # its hero links to /about/, which is off
        main = self.get("/").content.decode().split("<main")[1].split("</main>")[0]
        self.assertNotIn('href="/about/"', main)
