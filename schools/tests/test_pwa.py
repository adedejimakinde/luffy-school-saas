"""The installed app: each host's manifest and offline page, at two schools.

`docs/pwa.md`. A manifest names a school, so the claim to hold is the one every tenancy test
here holds: a school's name, crest and colour come out of its own host and no other's. Two
schools have crests (St Mary's, Grace); a third, Harbour, has none and a colour too light to
read, which must keep the navy and Classnode's icons and nothing of anybody else's.
"""

import io
import json
import re
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase
from PIL import Image

from accounts.models import Role, User
from accounts.services import grant_membership
from files import service, storage
from files.models import StoredFile
from files.tests.test_isolation import FilesSetUp, body
from schools import brand
from schools.models import Domain
from schools.pwa import short_name
from schools.tests.tenants import connected_to, make_school
from schools.tests.test_paths import GRACE, ST_MARYS
from website.tests.test_homepage import PORTAL, SITE

HARBOUR = "harbour.classnode.testserver"
DARK = "#7A1F2B"  # reads on white
PALE = "#F5C518"  # does not: the navy stays


def set_colour(school, colour):
    from schoolsite.models import SiteSettings

    with connected_to(school):
        row = SiteSettings.objects.get(pk=1)
        row.theme_options = {**row.theme_options, row.theme: {"colours": {"primary": colour}}}
        row.save(update_fields=["theme_options"])


class PwaSetUp(FilesSetUp):
    def setUp(self):
        super().setUp()
        self.harbour = make_school("Harbour College", "harbour", "harbour")
        Domain.objects.create(tenant=self.harbour, domain=HARBOUR, is_primary=True)
        set_colour(self.st_marys, DARK)
        set_colour(self.grace, PALE)
        set_colour(self.harbour, PALE)

    def manifest(self, host, user=None):
        response = self.get("/site.webmanifest", host=host, user=user)
        self.assertEqual(response.status_code, 200, host)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/manifest+json")
        return json.loads(body(response))

    def image(self, host, src):
        response = self.get(src, host=host)
        self.assertEqual(response.status_code, 200, f"{host}{src}")
        return Image.open(io.BytesIO(body(response)))


class EachSchoolsManifestIsItsOwnTests(PwaSetUp):
    def test_st_marys_is_named_coloured_and_iconed_as_itself(self):
        manifest = self.manifest(ST_MARYS)

        self.assertEqual(manifest["name"], "St Mary's College")
        self.assertEqual(manifest["short_name"], "St Mary's")
        self.assertEqual(manifest["theme_color"], DARK)
        self.assertEqual((manifest["start_url"], manifest["scope"], manifest["display"]), ("/home/", "/", "standalone"))
        self.assertEqual(
            [(i["sizes"], i["purpose"], i["src"]) for i in manifest["icons"]],
            [
                (f"{n}x{n}", purpose, f"/media/{self.crest.key}/icon-{n}.png")
                for n in (192, 512)
                for purpose in ("any", "maskable")
            ],
        )

    def test_grace_is_itself_and_its_pale_colour_is_the_navy(self):
        manifest = self.manifest(GRACE)

        self.assertEqual((manifest["name"], manifest["short_name"]), ("Grace Academy", "Grace"))
        self.assertEqual(manifest["theme_color"], brand.NAVY)
        self.assertTrue(all(i["src"].startswith(f"/media/{self.their_crest.key}/") for i in manifest["icons"]))

    def test_a_school_with_no_crest_keeps_its_name_and_classnodes_icons_not_another_schools(self):
        manifest = self.manifest(HARBOUR)

        self.assertEqual(manifest["name"], "Harbour College")
        self.assertEqual(manifest["theme_color"], brand.NAVY)
        self.assertEqual([i["src"] for i in manifest["icons"]], ["/icon-192.png", "/icon-512.png"])

    def test_nothing_of_one_school_is_in_anothers_manifest_or_offline_page(self):
        seen = {
            ST_MARYS: (self.manifest(ST_MARYS), self.crest.key, "St Mary", DARK),
            GRACE: (self.manifest(GRACE), self.their_crest.key, "Grace", PALE),
            HARBOUR: (self.manifest(HARBOUR), None, "Harbour", PALE),
        }
        for host, (manifest, key, name, colour) in seen.items():
            text = json.dumps(manifest) + self.get("/offline/", host=host).content.decode()
            for other, (_, other_key, other_name, other_colour) in seen.items():
                if other == host:
                    continue
                with self.subTest(host=host, other=other):
                    self.assertNotIn(other_name, text)
                    self.assertNotIn(other_colour, text)
                    if other_key:
                        self.assertNotIn(other_key, text)

    def test_one_request_after_another_never_carries_the_last_schools_manifest(self):
        for _ in range(2):
            for host, name in ((ST_MARYS, "St Mary's College"), (GRACE, "Grace Academy"), (HARBOUR, "Harbour College")):
                self.assertEqual(self.manifest(host)["name"], name)

    def test_another_schools_icon_is_not_served_on_this_host(self):
        for host, theirs in ((ST_MARYS, self.their_crest.key), (GRACE, self.crest.key)):
            for size in (192, 512):
                self.assertEqual(self.get(f"/media/{theirs}/icon-{size}.png", host=host).status_code, 404)

    def test_it_is_the_same_to_a_stranger_and_to_a_member_of_another_school(self):
        """A browser fetches a manifest with no say in who is signed in; it must never be a refusal."""
        self.assertEqual(self.manifest(ST_MARYS, user=None), self.manifest(ST_MARYS, user=self.their_principal))
        self.assertEqual(self.get("/offline/", host=ST_MARYS, user=self.their_principal).status_code, 200)


class TheIconsAreTheCrestInsideTheSafeZoneTests(PwaSetUp):
    def test_each_is_an_opaque_square_of_its_size_with_the_crest_inside_the_middle(self):
        for size in (192, 512):
            icon = self.image(ST_MARYS, f"/media/{self.crest.key}/icon-{size}.png")
            with self.subTest(size=size):
                self.assertEqual((icon.format, icon.size, icon.mode), ("PNG", (size, size), "RGB"))
                # Opaque white at the corners, and the crest's own colour at the centre.
                self.assertEqual(icon.getpixel((0, 0)), (255, 255, 255))
                self.assertNotEqual(icon.getpixel((size // 2, size // 2)), (255, 255, 255))
                # A maskable icon keeps its mark inside the middle 80%: the outer tenth is bare.
                edge = round(size * 0.1)
                outer = [
                    icon.getpixel((x, y))
                    for x in range(size)
                    for y in range(size)
                    if min(x, y, size - 1 - x, size - 1 - y) < edge
                ]
                self.assertTrue(all(pixel == (255, 255, 255) for pixel in outer))

    def test_a_crest_uploaded_before_they_existed_is_given_them_the_first_time_an_app_asks(self):
        with connected_to(self.st_marys):
            row = StoredFile.objects.get(pk=self.crest.pk)
            storage.delete_variants(row.schema_name, row.key, ["icon-192.png", "icon-512.png"])
            row.variants = {k: v for k, v in row.variants.items() if not k.startswith("icon-")}
            row.save(update_fields=["variants"])
        self.assertEqual(self.get(f"/media/{self.crest.key}/icon-192.png", host=ST_MARYS).status_code, 404)

        manifest = self.manifest(ST_MARYS)

        self.assertIn(f"/media/{self.crest.key}/icon-512.png", [i["src"] for i in manifest["icons"]])
        self.assertEqual(self.image(ST_MARYS, f"/media/{self.crest.key}/icon-192.png").size, (192, 192))
        with connected_to(self.st_marys):
            row = StoredFile.objects.get(pk=self.crest.pk)
            self.assertTrue(row.has("icon-192.png") and row.has("icon-512.png"))
            self.assertEqual(row.bytes, sum(meta["bytes"] for meta in row.variants.values()))

    def test_other_marks_do_not_get_app_icons(self):
        made = service.ensure_icons(self.photo)
        self.assertFalse(made)


class ClassnodesOwnManifestsTests(PwaSetUp):
    def test_the_portal_is_classnode_with_the_staff_door_as_its_start(self):
        manifest = self.manifest(PORTAL)
        self.assertEqual((manifest["name"], manifest["short_name"], manifest["display"]), ("Classnode", "Classnode", "standalone"))
        self.assertEqual(manifest["start_url"], "/staff-sign-in/")
        self.assertEqual([i["src"] for i in manifest["icons"]], ["/icon-192.png", "/icon-512.png"])
        self.assertNotIn("St Mary", json.dumps(manifest))
        # Signed in at a school or not, the portal's is the same.
        self.assertEqual(manifest, self.manifest(PORTAL, user=self.principal))

    def test_the_public_site_keeps_the_manifest_it_always_had(self):
        manifest = self.manifest(SITE)
        self.assertEqual((manifest["name"], manifest["display"], manifest["start_url"]), ("Classnode", "browser", "/"))
        self.assertEqual([i["src"] for i in manifest["icons"]], ["/icon-192.png", "/icon-512.png"])


class TheOfflinePageTests(PwaSetUp):
    def test_it_says_so_in_the_schools_words_with_the_schools_crest(self):
        html = self.get("/offline/", host=ST_MARYS).content.decode()

        self.assertIn("You&rsquo;re offline.", html)
        self.assertIn("Reconnect to continue.", html)
        self.assertIn(f'<img src="/media/{self.crest.key}/site.png"', html)
        self.assertIn("St Mary&#x27;s College", html)
        self.assertIn(f"<style>:root{{--brand:{DARK}}}</style>", html)

    def test_a_school_with_no_crest_wears_its_initials_and_the_navy(self):
        html = self.get("/offline/", host=HARBOUR).content.decode()
        self.assertIn(">HC</span>", html)
        self.assertNotIn("--brand:", html)

    def test_the_portal_wears_classnodes(self):
        html = self.get("/offline/", host=PORTAL).content.decode()
        self.assertIn("classnode", html)
        self.assertNotIn("/media/", html)

    def test_it_names_no_person_whoever_opens_it(self):
        """One kept copy serves whoever opens the app next: the bytes are the same signed in or out."""
        signed_in = self.get("/offline/", host=ST_MARYS, user=self.principal).content
        self.assertEqual(signed_in, self.get("/offline/", host=ST_MARYS, user=self.teacher).content)
        self.assertEqual(signed_in, self.get("/offline/", host=ST_MARYS).content)

    def test_it_is_never_indexed(self):
        response = self.get("/offline/", host=ST_MARYS)
        self.assertIn('<meta name="robots" content="noindex, nofollow">', response.content.decode())
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")


class TheInstallButtonIsOnTheMenusPagesOnlyTests(PwaSetUp):
    def test_every_page_with_the_menu_has_the_button_hidden_and_the_script(self):
        for host, user in ((ST_MARYS, self.principal), (GRACE, self.their_principal)):
            for path in ("/home/", "/timetable/", "/marking/", "/register/", "/fees/"):
                html = self.get(path, host=host, user=user).content.decode()
                with self.subTest(host=host, path=path):
                    self.assertRegex(html, r'<div id="install" class="nav nav-install" hidden>')
                    self.assertIn("Install app", html)
                    self.assertIn("Tap Share, then Add to Home Screen.", html)
                    self.assertRegex(html, r'<script type="module" src="[^"]*web/portal-app[^"]*\.js"></script>')

    def test_the_public_website_the_exam_door_and_the_doors_do_not_load_it(self):
        for host, path in ((ST_MARYS, "/"), (ST_MARYS, "/sit/"), (ST_MARYS, "/sign-in/"), (ST_MARYS, "/offline/")):
            html = self.get(path, host=host).content.decode()
            with self.subTest(host=host, path=path):
                self.assertNotIn("portal-app", html)
                self.assertNotIn('id="install"', html)

    def test_every_page_links_this_hosts_manifest(self):
        html = self.get("/home/", host=ST_MARYS, user=self.principal).content.decode()
        self.assertEqual(html.count('<link rel="manifest" href="/site.webmanifest">'), 1)


class TwoWorkersTwoScopesTests(PwaSetUp):
    """What the server says that keeps `/sit/` its own worker's (the browser proof is `tests/ui/pwa.test.js`)."""

    def test_the_portal_worker_and_the_exams_are_two_scripts_with_two_scopes(self):
        portal = self.get("/sw.js", host=ST_MARYS)
        sit = self.get("/sit/sw.js", host=ST_MARYS)

        self.assertEqual(portal["Service-Worker-Allowed"], "/")
        self.assertEqual(sit["Service-Worker-Allowed"], "/sit/")
        self.assertNotEqual(portal.content, sit.content)

    def test_the_portal_worker_is_told_to_leave_the_exam_alone(self):
        from sync.tests.test_service_worker import config_of

        config = config_of(self.get("/sw.js", host=ST_MARYS).content.decode())
        self.assertEqual(config["leave"], ["/sit/"])
        self.assertEqual(config["offline"], "/offline/")
        self.assertEqual(config["signOut"], ["/sign-out/", "/api/logout/"])
        # Nothing the exam's page or worker names is in the portal's shell.
        self.assertFalse([s for s in config["shell"] if "/sit/" in s or "sit.css" in s])

    def test_neither_worker_script_nor_the_page_script_can_remove_a_worker_or_the_others_caches(self):
        from sync.tests.test_service_worker import code_of

        root = Path(settings.BASE_DIR)
        for path in ("sync/worker.js", "cbt/sit_worker.js", "static/web/portal-app.js", "static/web/offline.js", "static/sit/app.js"):
            code = code_of((root / path).read_text())
            with self.subTest(path=path):
                self.assertNotRegex(code, r"unregister|getRegistrations|getRegistration\b|registration\.update")
        # The caches each deletes by name: the portal's `luffy-`, the exam's `sit-`.
        portal = code_of((root / "sync/worker.js").read_text())
        sit = code_of((root / "cbt/sit_worker.js").read_text())
        self.assertEqual(set(re.findall(r"caches\.delete\(([^)]*)\)", portal)), {"name"})
        self.assertIn('name.startsWith(CONFIG.prefix)', portal)
        self.assertIn('name.startsWith("luffy-shell-")', portal)
        self.assertIn('name.startsWith("sit-shell-")', sit)
        self.assertNotIn("luffy", sit)
        self.assertNotIn("sit-", portal)


class ShortNamesFitUnderAnIconTests(SimpleTestCase):
    def test_the_whole_name_if_it_fits(self):
        for name in ("Grace", "Sunrise Demo", "  St   Mary's "):
            self.assertEqual(short_name(name), " ".join(name.split()))

    def test_a_long_name_loses_its_generic_words_first(self):
        self.assertEqual(short_name("St Mary's College"), "St Mary's")
        self.assertEqual(short_name("Grace Academy"), "Grace")
        self.assertEqual(short_name("Saint Mary's International School"), "Saint Mary's")
        self.assertEqual(short_name("The Royal Crest Nursery and Primary School"), "Royal Crest")

    def test_one_long_word_is_cut_and_a_name_of_only_generic_words_is_not_empty(self):
        self.assertEqual(short_name("Abeokutaschoolhouse"), "Abeokutascho")
        self.assertTrue(short_name("International High School Group"))
        self.assertLessEqual(len(short_name("International High School Group")), 12)
