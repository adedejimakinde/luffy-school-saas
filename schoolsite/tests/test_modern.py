"""Modern Campus, the designed theme, and what the engine gained for it, at two schools.

`docs/school-sites-theme-modern.md`, PR A.

- **The look is the principal's.** Four colours (main, accent, detail, dark band)
  and five animated backgrounds, set on `/website/look/` and held to the
  allow-list and the contrast rules (`schoolsite.themes`); the tints are worked
  out, never chosen. A delegated administrator, a teacher and another school's
  principal are refused, and a refusal changes nothing. The look is published
  with the site and a rollback brings the old one back.
- **A hero is a slideshow of one to five of the school's own hero photos**, or
  a video, or neither. Only the first photo is fetched with the page; the others
  wait for the site's script, which a page runs only when it has more than one.
  Another school's photo is never this school's slide, and taking a slide down
  takes only that slide.
- **Every school moved without a step by hand.** The migration turned each
  starter draft into Modern Campus with the demo's colours and every switch on,
  and each one-picture hero into a slideshow of one; a revision published before
  is drawn the same and is not reported as a change.
- **What the theme draws**: the admissions pill from the page's own admissions
  panel, Apply now to the first page of Admissions or Contact that is on, the
  footer's "Powered by Classnode", the line art only where it is switched on,
  and the school's colours only on the school's own host.
"""

import importlib
import re

from django.apps import apps

from schools.tests.tenants import connected_to
from schoolsite import pictures, render, sections, services, themes
from schoolsite.errors import NotAllowed, SiteRefused
from schoolsite.models import Page, Section, SiteRevision, SiteSettings
from schoolsite.sections import SectionRefused
from schoolsite.themes import ThemeRefused

from .test_editor import BASE, EditorSetUp
from .test_pictures import PicturesSetUp, photo
from .test_public import GRACE, ST_MARYS

STYLE = re.compile(r"<style>(.*?)</style>", re.S)


def settings_version():
    return SiteSettings.objects.get(pk=1).version


class TheLookTests(PicturesSetUp):
    def look(self, who=None, school=None, **change):
        school = school or self.stmarys
        with connected_to(school):
            return services.set_look_as(who or self.principal, school, version=settings_version(), **change)

    def test_the_principal_sets_four_colours_and_five_switches_and_the_rest_is_kept(self):
        self.look(colours={"primary": "7a1f2b", "accent": "#F2C14E"}, animations={"hero": False})
        self.look(animations={"contact": False})
        with connected_to(self.stmarys):
            options = SiteSettings.objects.get(pk=1).theme_options["modern"]
        self.assertEqual(options["colours"], {"primary": "#7A1F2B", "accent": "#F2C14E", "detail": "#C9A24A",
                                              "dark": "#0F1B33"})
        self.assertEqual(options["animations"], {"hero": False, "academics": True, "student_life": True,
                                                 "admissions": True, "contact": False})
        self.look(colours={"accent": ""})
        with connected_to(self.stmarys):
            self.assertNotIn("accent", SiteSettings.objects.get(pk=1).theme_options["modern"]["colours"],
                             "back to the theme's own")

    def test_writing_that_would_not_read_is_refused_and_nothing_is_kept(self):
        with connected_to(self.stmarys):
            before = SiteSettings.objects.get(pk=1).theme_options
        for colours, sentence in (
            ({"primary": "#FFD66B"}, "too light for white writing"),
            ({"accent": "#143D8C"}, "writing on #143D8C buttons"),
            ({"dark": "#8899AA"}, "too light for white writing on the dark band"),
            ({"detail": "#22314F"}, "would not show on the dark band"),
            ({"primary": "navy"}, "six hex digits"),
            ({"surface": "#FFFFFF"}, "Only the main, accent, detail and dark"),
        ):
            with self.subTest(colours=colours), self.assertRaisesMessage(ThemeRefused, sentence):
                self.look(colours=colours)
        for switches in ({"hero": "off"}, {"fireworks": True}):
            with self.subTest(switches=switches), self.assertRaises(ThemeRefused):
                self.look(animations=switches)
        with connected_to(self.stmarys):
            self.assertEqual(SiteSettings.objects.get(pk=1).theme_options, before)
        # The bounds: a white accent under a dark grey band reads, and is kept.
        self.assertEqual(themes.clean_options("modern", {"colours": {"accent": "#FFFFFF", "dark": "#3A3A3A"}}),
                         {"colours": {"accent": "#FFFFFF", "dark": "#3A3A3A"}})

    def test_the_tints_are_worked_out_and_the_text_must_read_on_each(self):
        colours = themes.palette("modern")
        self.assertEqual((colours["tint"], colours["mint"]), ("#EEF3FC", "#E8F6EF"))
        for panel in ("tint", "warm", "mist", "mint", "surface"):
            self.assertGreaterEqual(themes.contrast(colours["text"], colours[panel]), 4.5, panel)
        with self.assertRaisesMessage(ThemeRefused, "pale panels"):
            # Reads on white (4.95:1), not on the pale panels (4.45:1 at the least).
            themes.clean_options("modern", {"colours": {"text": "#707070"}})

    def test_only_this_schools_principal_changes_the_look(self):
        self.delegate()
        with connected_to(self.stmarys):
            before = SiteSettings.objects.get(pk=1).theme_options
        for who in (self.admin, self.teacher, self.grace_principal):
            with self.subTest(who=who.username), self.assertRaises(NotAllowed):
                self.look(who, colours={"accent": "#F2C14E"})
        with connected_to(self.stmarys):
            self.assertEqual(SiteSettings.objects.get(pk=1).theme_options, before)
        with connected_to(self.grace):
            self.assertNotIn("#F2C14E", str(SiteSettings.objects.get(pk=1).theme_options))

    def test_the_look_is_published_with_the_site_and_a_rollback_brings_the_old_one_back(self):
        self.build(self.principal, self.stmarys, "Welcome")
        self.look(colours={"primary": "#7A1F2B"}, animations={"hero": False})
        self.assertNotIn("#7A1F2B", self.get("/").content.decode(), "not until it is published")
        with connected_to(self.stmarys):
            second = services.publish_as(self.principal, self.stmarys)
        self.assertEqual(second.snapshot["options"]["colours"]["primary"], "#7A1F2B")
        self.assertTrue(second.summary["theme_changed"])
        page = self.get("/").content.decode()
        self.assertIn("--primary:#7A1F2B", page)
        with connected_to(self.stmarys):
            services.rollback_as(self.principal, self.stmarys, 1)
        page = self.get("/").content.decode()
        self.assertNotIn("#7A1F2B", page)
        self.assertIn("art-hero", page, "the hero's line art, switched on in the version gone back to")

    def test_one_schools_colours_are_never_on_the_others_host(self):
        self.build(self.principal, self.stmarys, "Welcome")
        self.build(self.grace_principal, self.grace, "Grace")
        self.look(colours={"accent": "#F2C14E"})
        self.look(self.grace_principal, self.grace, colours={"accent": "#9FE3C8"})
        for school, who in ((self.stmarys, self.principal), (self.grace, self.grace_principal)):
            with connected_to(school):
                services.publish_as(who, school)
        stmarys, grace = self.get("/").content.decode(), self.get("/", GRACE).content.decode()
        self.assertIn("--accent:#F2C14E", stmarys)
        self.assertNotIn("#9FE3C8", stmarys)
        self.assertIn("--accent:#9FE3C8", grace)
        self.assertNotIn("#F2C14E", grace)

    def test_switched_off_line_art_is_not_drawn_and_the_page_style_is_in_its_policy(self):
        self.build(self.principal, self.stmarys, "Welcome")
        page = self.get("/")
        self.assertIn('<span class="art art-hero" aria-hidden="true">', page.content.decode())
        style = STYLE.search(page.content.decode()).group(1)
        self.assertIn(f"'sha256-{render.style_hash(style)}'", page["Content-Security-Policy"])
        self.look(animations={"hero": False})
        with connected_to(self.stmarys):
            services.publish_as(self.principal, self.stmarys)
        self.assertNotIn("art-hero", self.get("/").content.decode())


class TheSlideshowTests(PicturesSetUp):
    def slides(self, *made, school=None, who=None, publish=True):
        school = school or self.stmarys
        who = who or (self.principal if school == self.stmarys else self.grace_principal)
        with connected_to(school):
            home = Page.objects.get(key="home")
            data = {"heading": "Welcome", "slides": [{"picture": p.pk} for p in made]}
            existing = home.sections.filter(kind="hero").first()
            if existing:
                services.save_section_as(who, school, existing.pk, version=existing.version, data=data)
            else:
                services.add_section_as(who, school, "home", version=home.version, kind="hero", data=data)
            if publish:
                return services.publish_as(who, school)

    def test_a_hero_holds_one_to_five_photos_each_once_or_a_video(self):
        hero = sections.clean("hero", {"heading": "Hi", "slides": [{"picture": 1}, {"picture": 2}]})
        self.assertEqual(hero["slides"], [{"picture": 1}, {"picture": 2}])
        self.assertNotIn("image", hero)
        self.assertEqual(sections.clean("hero", {"heading": "Hi", "image": 7})["slides"], [{"picture": 7}],
                         "an older client's one picture is a slideshow of one")
        self.assertNotIn("focal", sections.clean("hero", {"heading": "Hi", "focal": {"x": 0.2, "y": 0.4}}))
        for data, sentence in (
            ({"slides": [{"picture": n} for n in range(1, 7)]}, "at most 5"),
            ({"slides": [{"picture": 3}, {"picture": 3}]}, "once"),
            ({"slides": [{"picture": 3}], "video": 4}, "photos or a video"),
            ({"slides": [{"picture": 3}], "image": 3}, "its slides"),
            ({"slides": [{"picture": "3"}]}, "whole number"),
            ({"slides": [{"picture": 3, "alt": "x"}]}, "no field called 'alt'"),
        ):
            with self.subTest(data=data), self.assertRaisesMessage(SectionRefused, sentence):
                sections.clean("hero", {"heading": "Hi", **data})

    def test_only_this_schools_hero_photos_are_its_slides(self):
        theirs = self.upload(school=self.grace, alt="Grace's gate")
        portrait = self.upload(use="portrait", alt="The principal")
        # The ids name pictures that do not exist here, or are the wrong sort.
        for made in ((theirs,), (portrait,)):
            with self.subTest(made=made), self.assertRaises(SiteRefused):
                self.slides(*made, publish=False)
        with connected_to(self.stmarys):
            self.assertFalse(Section.objects.filter(kind="hero").exists())

    def test_only_the_first_photo_comes_with_the_page_and_the_rest_wait_for_the_script(self):
        made = [self.upload(raw=photo(colour=(40 * n, 90, 120)), alt=f"Photo {n}") for n in range(1, 4)]
        self.slides(*made)
        response = self.get("/")
        html = response.content.decode()
        first, later = html.split('<template class="later">')
        self.assertIn(f"/media/{made[0].file_key}/828.avif", first)
        self.assertIn('alt="Photo 1" fetchpriority="high"', first)
        self.assertIn(f'imagesrcset="/media/{made[0].file_key}/480.avif', html, "and preloaded")
        self.assertNotIn(made[1].file_key, first, "the second photo is fetched by nothing on the page")
        self.assertIn(made[1].file_key, later)
        self.assertIn('alt="Photo 3" loading="lazy"', later)
        self.assertIn('<div class="dots" hidden>', html)
        self.assertIn('aria-label="Show photo 3 of 3"', html)
        self.assertIn('data-slides role="group" aria-roledescription="slideshow"', html)
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(html.count('<script type="module"'), 1)

    def test_one_photo_is_a_picture_and_no_script(self):
        self.slides(self.upload())
        response = self.get("/")
        self.assertNotIn("<template", response.content.decode())
        self.assertNotIn("data-slides", response.content.decode())
        self.assertIn("script-src 'none'", response["Content-Security-Policy"])

    def test_taking_one_slide_down_takes_only_that_slide(self):
        made = [self.upload(alt=f"Photo {n}") for n in range(1, 4)]
        self.slides(*made)
        self.take_down(made[1])
        with connected_to(self.stmarys):
            self.assertEqual(Section.objects.get(kind="hero").data["slides"],
                             [{"picture": made[0].pk}, {"picture": made[2].pk}])
            live = SiteRevision.objects.order_by("-number").first().snapshot
        hero = next(s for s in live["pages"][0]["sections"] if s["kind"] == "hero")
        self.assertEqual(sections.hero_slides(hero["data"]), [made[0].pk, made[2].pk])
        html = self.get("/").content.decode()
        self.assertNotIn(made[1].file_key, html)
        self.assertIn(made[2].file_key, html)

    def test_a_slide_with_no_description_holds_the_publish(self):
        made = self.upload(alt="The gate")
        self.slides(made, publish=False)
        with connected_to(self.stmarys):
            made.refresh_from_db()
            # A hero photo's description is required when it is saved; a raw edit stands in
            # for one that lost it some other way.
            type(made).objects.filter(pk=made.pk).update(alt="")
            with self.assertRaisesMessage(SiteRefused, "no description"):
                services.publish_as(self.principal, self.stmarys)

    def take_down(self, picture):
        with connected_to(self.stmarys):
            return pictures.take_down_as(self.principal, self.stmarys, picture.pk, reason="Consent withdrawn")


class EverySchoolMovedOnTests(PicturesSetUp):
    """The migration and the revisions published before it."""

    def old_draft(self, picture):
        """The draft as the starter theme left it: its options, and a hero with one picture."""
        SiteSettings.objects.filter(pk=1).update(theme="starter", theme_options={"starter": {
            "colours": {"primary": "#7A1F2B"}}})
        hero = Section.objects.get(kind="hero")
        Section.objects.filter(pk=hero.pk).update(data={**{k: v for k, v in hero.data.items() if k != "slides"},
                                                        "image": picture.pk, "focal": {"x": 0.5, "y": 0.5}})

    def migrate(self):
        module = importlib.import_module("schoolsite.migrations.0005_modern_campus")
        module.forwards(apps, None)

    def test_the_migration_gives_every_starter_draft_modern_campus_and_a_slideshow_of_one(self):
        made = self.upload()
        self.with_hero(made, publish=False)
        with connected_to(self.stmarys):
            self.old_draft(made)
            self.migrate()
            settings = SiteSettings.objects.get(pk=1)
            self.assertEqual(settings.theme, "modern")
            self.assertEqual(settings.theme_options, {"modern": {
                "colours": {"accent": "#FFD66B", "detail": "#C9A24A", "dark": "#0F1B33", "primary": "#7A1F2B"},
                "animations": {name: True for name in themes.ANIMATIONS},
            }})
            themes.clean_options("modern", settings.theme_options["modern"])
            hero = Section.objects.get(kind="hero").data
            self.assertEqual(hero["slides"], [{"picture": made.pk}])
            self.assertNotIn("image", hero)
            self.assertNotIn("focal", hero)
        with connected_to(self.grace):
            self.assertEqual(SiteSettings.objects.get(pk=1).theme, "modern", "every school, not one")

    def test_a_revision_from_before_is_drawn_the_same_and_is_not_a_change_to_publish(self):
        made = self.upload()
        self.with_hero(made, publish=False)
        with connected_to(self.stmarys):
            self.old_draft(made)
            draft = services.snapshot()
            draft["pictures"] = pictures.snapshot_pictures(draft)
            old = SiteRevision.objects.create(number=1, snapshot=draft, published_by_id=self.principal.pk,
                                              published_by_name="Rev. Sr. Okafor")
            self.assertEqual(old.snapshot["theme"], "starter")
            pictures.sync_public()
            self.migrate()
            settings = SiteSettings.objects.get(pk=1)
            self.assertFalse(services.has_changes(settings, old.snapshot, services.snapshot()))
            with self.assertRaisesMessage(SiteRefused, "Nothing has changed"):
                services.publish_as(self.principal, self.stmarys)
        html = self.get("/").content.decode()
        self.assertIn(f"/media/{made.file_key}/828.avif", html, "its one picture, as the slideshow's first")
        self.assertIn("schoolsite/modern.", html)
        self.assertIn("--primary:#7A1F2B", html)
        self.assertIn("art-hero", html, "switches it never had are on")


class WhatTheThemeDrawsTests(PicturesSetUp):
    def home(self, *extra, pages=("about",)):
        with connected_to(self.stmarys):
            for key in pages:
                services.save_page_as(self.principal, self.stmarys, key, version=Page.objects.get(key=key).version,
                                      enabled=True)
            services.add_section_as(self.principal, self.stmarys, "home", version=Page.objects.get(key="home").version,
                                    kind="hero", data={"heading": "Welcome"})
            for kind, data in extra:
                services.add_section_as(self.principal, self.stmarys, "home",
                                        version=Page.objects.get(key="home").version, kind=kind, data=data)
            services.publish_as(self.principal, self.stmarys)
        return self.get("/").content.decode()

    def test_the_admissions_pill_comes_from_the_pages_own_panel_and_only_while_open(self):
        open_ = {"heading": "Admissions", "session": "2027/2028", "open": True}
        self.assertIn("Admissions open for 2027/2028</p>", self.home(("admissions_cta", open_)))

    def test_no_pill_while_admissions_are_closed_or_there_is_no_panel(self):
        self.assertIn('class="pill"', self.home(("admissions_cta", {"heading": "A", "open": True})))
        self.assertEqual(render.admissions_pill([{"kind": "admissions_cta", "data": {"open": False, "session": "2027/2028"}}]), "")
        self.assertEqual(render.admissions_pill([{"kind": "text", "data": {}}]), "")
        self.assertEqual(render.admissions_pill([{"kind": "admissions_cta", "data": {"open": True}}]), "Admissions open")

    def test_apply_now_goes_to_admissions_else_contact_else_nowhere(self):
        self.assertEqual(render.apply_href({"/", "/admissions/", "/contact/"}), "/admissions/")
        self.assertEqual(render.apply_href({"/", "/contact/"}), "/contact/")
        self.assertEqual(render.apply_href({"/"}), "")
        html = self.home(pages=("about",))
        self.assertNotIn("Apply now", html)

    def test_the_header_has_sign_in_and_apply_now_on_every_size_and_the_footer_classnode(self):
        html = self.home(pages=("about", "admissions"))
        self.assertIn('<a class="button accent apply" href="/admissions/">Apply now</a>', html)
        panel = html.split('<div class="panel">')[1].split("</details>\n  </div>")[0]
        self.assertIn('<summary class="button">Sign in</summary>', panel)
        self.assertIn('<a class="button accent" href="/admissions/">Apply now</a>', panel)
        self.assertIn('/sign-in/">Parent or guardian</a>', panel)
        self.assertIn('<a class="powered" href="https://classnode.co">Powered by Classnode</a>', html)


class TheLookScreenTests(EditorSetUp):
    def test_the_principal_opens_it_and_saves_and_nobody_else_writes(self):
        self.client.force_login(self.principal)
        frame = self.client.get("/website/look/", HTTP_HOST=ST_MARYS)
        self.assertEqual(frame.status_code, 200)
        self.assertIn("site-editor/look-app.", frame.content.decode())
        body = self.overview().json()
        self.assertEqual(body["look"]["animations"], {name: True for name in themes.ANIMATIONS})
        self.assertEqual(body["look"]["palette"]["tint"], themes.palette("modern", {"colours": {
            "primary": body["look"]["palette"]["primary"]}})["tint"])
        _, version = self.versions()
        answer = self.call("put", "look/", self.principal, version=version, colours={"accent": "#F2C14E"},
                           animations={"student_life": False})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["look"]["chosen"]["accent"], "#F2C14E")
        self.assertFalse(answer.json()["look"]["animations"]["student_life"])
        refused = self.call("put", "look/", self.principal, version=version + 1, colours={"accent": "#143D8C"})
        self.assertEqual(refused.status_code, 422)
        self.assertIn("buttons would be too hard to read", refused.json()["detail"])
        self.delegate()
        for who in (self.admin, *self.others.values()):
            with self.subTest(who=who.username):
                self.assertEqual(self.call("put", "look/", who, version=version + 1,
                                           colours={"accent": "#FFD66B"}).status_code, 403)
        self.assertEqual(self.call("put", "look/", self.grace_principal, version=version + 1,
                                   colours={"accent": "#FFD66B"}).status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(SiteSettings.objects.get(pk=1).theme_options["modern"]["colours"]["accent"], "#F2C14E")
