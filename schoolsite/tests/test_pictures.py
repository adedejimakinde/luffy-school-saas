"""Pictures and albums on a school's website, at two schools. `docs/school-sites.md` PR 5.

- **Who may**: the principal uploads, describes, arranges, deletes, publishes
  albums and takes pictures down; a delegated administrator uploads, describes,
  arranges and deletes draft pictures and adds photos to an album, and nothing
  more; nobody else does anything, and another school's principal is nobody here.
- **What is kept**: every upload goes through the upload service, with the
  uploader's consent ticked, a description where one is needed, at most five at
  a time, and against this school's quota only. SVG, GIF, a renamed PDF, a
  decompression bomb and an oversize file are refused; no size of any picture
  carries GPS.
- **Public only once published**: before, a picture is a 404 on `/media/` and
  sent only to this school's editors on `/website/pictures/`; after, it is on
  `/media/` on this school's host and never on another's.
- **Deleting** is for pictures nothing live or in the draft uses; going back to a
  version that showed a deleted picture draws that section without it.
- **Taking down** removes a picture from the draft, every album and the live
  site at once, publishes the live site again without it (and nothing else of
  the draft), deletes its file, moves the page cache to new keys, and logs who,
  when and why. The other school is untouched.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Role, User
from accounts.services import grant_membership
from files import service as files
from files import storage
from files.models import StoredFile
from files.tests import samples
from schools.tests.tenants import connected_to

from schoolsite import pictures, services
from schoolsite.themes import THEMES
from schoolsite.errors import NotAllowed, NotAllowedToPublish, SiteRefused
from schoolsite.models import Album, Page, Section, SitePicture, SitePublishEvent, SiteRevision

from .test_public import GRACE, ST_MARYS, PublicSiteSetUp

PASSWORD = "a-long-password-1"


def photo(size=(900, 600), colour=None):
    return samples.photo(size, colour=colour)


class PicturesSetUp(PublicSiteSetUp):
    def setUp(self):
        super().setUp()
        self.admin = self.member("ade", Role.ADMIN)
        self.teacher = self.member("tolu", Role.TEACHER)

    def member(self, username, role, school=None):
        user = User.objects.create_user(username, PASSWORD, full_name=username.title())
        grant_membership(user, school or self.stmarys, role)
        return user

    def delegate(self, on=True):
        with connected_to(self.stmarys):
            services.set_delegation_as(self.principal, self.stmarys, on)

    def upload(self, who=None, use="hero", raw=None, *, school=None, alt="The school gate", album=None,
               video=False, many=None):
        school = school or self.stmarys
        who = who or (self.principal if school == self.stmarys else self.grace_principal)
        with connected_to(school):
            made = pictures.upload_as(who, school, use, many or [raw or photo()], consent=True, alt=alt,
                                      album_id=album.pk if album else None, video=video)
        return made if many else made[0]

    def with_hero(self, picture, school=None, who=None, heading="Welcome", publish=True):
        school = school or self.stmarys
        who = who or (self.principal if school == self.stmarys else self.grace_principal)
        with connected_to(school):
            home = Page.objects.get(key="home")
            existing = home.sections.filter(kind="hero").first()
            data = {"heading": heading, "slides": [{"picture": picture.pk}]}
            if existing:
                services.save_section_as(who, school, existing.pk, version=existing.version, data=data)
            else:
                services.add_section_as(who, school, "home", version=home.version, kind="hero", data=data)
            if publish:
                return services.publish_as(who, school)

    def album(self, title="Sports day", school=None, who=None, photos=2, publish=True):
        school = school or self.stmarys
        who = who or (self.principal if school == self.stmarys else self.grace_principal)
        with connected_to(school):
            album = pictures.create_album_as(who, school, title=title)
        made = self.upload(who, "gallery", school=school, album=album, alt="",
                           many=[photo(colour=(30 * i, 90, 120)) for i in range(photos)])
        with connected_to(school):
            for n, p in enumerate(made, start=1):
                pictures.save_picture_as(who, school, p.pk, version=p.version, alt=f"Photo {n} of {title}",
                                         caption=f"Caption {n}")
            album.refresh_from_db()
            if publish:
                pictures.publish_album_as(who, school, album.pk, version=album.version)
                album.refresh_from_db()
        return album, made

    def gallery_page(self, album, school=None, who=None):
        """Switch the Gallery page on, with a gallery section showing `album`, and publish."""
        school = school or self.stmarys
        who = who or (self.principal if school == self.stmarys else self.grace_principal)
        with connected_to(school):
            page = Page.objects.get(key="gallery")
            services.save_page_as(who, school, "gallery", version=page.version, enabled=True)
            home = Page.objects.get(key="home")
            services.add_section_as(who, school, "home", version=home.version, kind="gallery",
                                    data={"album": album.pk, "count": 1})
            if not home.sections.filter(kind="hero").exists():
                services.add_section_as(who, school, "home", version=Page.objects.get(key="home").version,
                                        kind="hero", data={"heading": "Welcome"})
            return services.publish_as(who, school)

    def key_of(self, picture):
        return picture.file_key

    def media(self, picture, variant="480.webp", host=ST_MARYS):
        self.client.logout()
        return self.client.get(f"/media/{picture.file_key}/{variant}", HTTP_HOST=host)

    def editor_copy(self, picture, who, variant="480.webp", host=ST_MARYS):
        if who is None:
            self.client.logout()
        else:
            self.client.force_login(who)
        return self.client.get(f"/website/pictures/{picture.file_key}/{variant}", HTTP_HOST=host)

    def on_disk(self, picture, school=None):
        with connected_to(school or self.stmarys):
            stored = files.find(picture.file_key)
        if stored is None:
            return []
        return [v for v in stored.variants if storage.path_of(stored.schema_name, stored.key, v).exists()]


class TheControlTests(PicturesSetUp):
    """Each refusal below would pass against a site that showed no pictures at all."""

    def test_a_published_hero_is_drawn_and_sent_to_anybody_on_its_own_host(self):
        picture = self.upload()
        self.with_hero(picture)
        html = self.get("/").content.decode()
        self.assertIn(f"/media/{picture.file_key}/828.avif 828w", html)
        self.assertEqual(self.media(picture).status_code, 200)


class WhoMayUploadTests(PicturesSetUp):
    def test_the_principal_and_a_delegated_administrator_upload_and_nobody_else(self):
        self.assertTrue(self.upload(self.principal).pk)
        with self.assertRaises(NotAllowed):
            self.upload(self.admin)
        self.delegate()
        self.assertTrue(self.upload(self.admin).pk)
        self.delegate(False)
        for who in (self.admin, self.teacher, self.grace_principal, self.grace_teacher):
            with self.subTest(who=who.username), self.assertRaises(NotAllowed):
                self.upload(who)
        with connected_to(self.stmarys):
            self.assertEqual(SitePicture.objects.count(), 2)

    def test_another_schools_principal_is_nobody_here_and_their_upload_lands_at_their_school(self):
        theirs = self.upload(school=self.grace)
        with connected_to(self.stmarys):
            self.assertFalse(SitePicture.objects.filter(file_key=theirs.file_key).exists())
            self.assertIsNone(files.find(theirs.file_key))
        with connected_to(self.grace):
            self.assertTrue(SitePicture.objects.filter(file_key=theirs.file_key).exists())

    def test_nothing_is_kept_without_consent_and_a_hero_or_portrait_needs_its_description(self):
        with connected_to(self.stmarys):
            with self.assertRaisesMessage(SiteRefused, "Parents have agreed to photos of their children being published"):
                pictures.upload_as(self.principal, self.stmarys, "hero", [photo()], consent=False, alt="A gate")
            with self.assertRaisesMessage(SiteRefused, "description of the picture cannot be empty"):
                pictures.upload_as(self.principal, self.stmarys, "portrait", [photo()], consent=True, alt="")
            self.assertEqual(SitePicture.objects.count(), 0)
            self.assertEqual(StoredFile.objects.count(), 0)
        picture = self.upload()
        self.assertEqual((picture.consent, picture.consent_version), (True, "2026-11-01"))

    def test_at_most_five_at_a_time_and_one_for_a_hero(self):
        with connected_to(self.stmarys):
            album = pictures.create_album_as(self.principal, self.stmarys, title="Prize giving")
            with self.assertRaisesMessage(SiteRefused, "at most 5 photos at a time"):
                pictures.upload_as(self.principal, self.stmarys, "gallery", [photo()] * 6, consent=True,
                                   album_id=album.pk)
            with self.assertRaisesMessage(SiteRefused, "Choose one file"):
                pictures.upload_as(self.principal, self.stmarys, "hero", [photo()] * 2, consent=True, alt="Gate")
            with self.assertRaisesMessage(SiteRefused, "Only the hero can be a video"):
                pictures.upload_as(self.principal, self.stmarys, "portrait", [samples.video()], consent=True,
                                   alt="Me", video=True)

    def test_svg_gif_a_renamed_pdf_a_bomb_and_an_oversize_file_are_each_refused(self):
        oversize = SimpleUploadedFile("big.jpg", b"\xff\xd8" + b"0" * 10, content_type="image/jpeg")
        oversize.size = 16 * 1024 * 1024
        for name, raw in (("svg", samples.svg()), ("gif", samples.gif()), ("pdf", samples.pdf()),
                          ("bomb", samples.bomb()), ("oversize", oversize)):
            with self.subTest(name), connected_to(self.stmarys), self.assertRaises(SiteRefused):
                pictures.upload_as(self.principal, self.stmarys, "hero", [raw], consent=True, alt="A gate")
        with connected_to(self.stmarys):
            self.assertEqual(SitePicture.objects.count(), 0)

    def test_no_size_of_any_website_picture_carries_gps(self):
        from PIL import Image

        made = [self.upload(raw=samples.photo((1000, 700))),
                self.upload(use="portrait", raw=samples.photo((700, 900)))]
        with connected_to(self.stmarys):
            for picture in made:
                stored = files.find(picture.file_key)
                for variant in stored.variants:
                    with self.subTest(variant=variant):
                        image = Image.open(io.BytesIO(files.read(stored, variant)))
                        self.assertNotIn(0x8825, image.getexif())
                        self.assertIsNone(image.info.get("exif"))

    def test_the_quota_is_this_schools_alone(self):
        self.stmarys.storage_quota_bytes = 1024
        self.stmarys.save()
        with connected_to(self.stmarys), self.assertRaisesMessage(SiteRefused, "of storage"):
            pictures.upload_as(self.principal, self.stmarys, "hero", [photo()], consent=True, alt="A gate")
        self.assertTrue(self.upload(school=self.grace).pk)


class PublicOnlyOncePublishedTests(PicturesSetUp):
    def test_before_publishing_it_is_a_404_to_the_public_and_sent_only_to_this_schools_editors(self):
        picture = self.upload()
        self.with_hero(picture, publish=False)
        self.assertEqual(self.media(picture).status_code, 404)
        self.assertEqual(self.editor_copy(picture, self.principal).status_code, 200)
        # Another school's principal is stopped at the door, a 403 like any portal page.
        for who in (None, self.teacher, self.admin, self.grace_principal):
            with self.subTest(who=getattr(who, "username", "signed out")):
                response = self.editor_copy(picture, who)
                self.assertIn(response.status_code, (403, 404))
                self.assertNotIn("X-Accel-Redirect", response)
        self.delegate()
        self.assertEqual(self.editor_copy(picture, self.admin).status_code, 200)
        # A's editor asking on B's host, with A's key, is sent nothing.
        self.assertIn(self.editor_copy(picture, self.principal, host=GRACE).status_code, (403, 404))

    def test_after_publishing_it_is_on_media_on_its_own_host_and_never_on_another(self):
        picture = self.upload()
        self.with_hero(picture)
        response = self.media(picture)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(list(response.cookies), [])
        self.assertEqual(self.media(picture, host=GRACE).status_code, 404)

    def test_the_preview_draws_unpublished_pictures_from_the_editors_route_only(self):
        picture = self.upload()
        self.with_hero(picture, publish=False)
        self.client.force_login(self.principal)
        html = self.client.get("/website/preview/", HTTP_HOST=ST_MARYS).content.decode()
        self.assertIn(f"/website/pictures/{picture.file_key}/480.avif 480w", html)
        self.assertNotIn("/media/", html)

    def test_a_picture_only_in_the_draft_or_an_unpublished_album_stays_private_through_every_publish(self):
        live = self.upload()
        draft_only = self.upload(alt="Not yet")
        unpublished, in_it = self.album(publish=False)
        published, _ = self.album(title="Prize giving")
        self.with_hero(live)
        with connected_to(self.stmarys):
            published.refresh_from_db()
            pictures.unpublish_album_as(self.principal, self.stmarys, published.pk, version=published.version)
        for picture in (draft_only, *in_it, *_):
            with self.subTest(picture=picture.alt):
                self.assertEqual(self.media(picture).status_code, 404)
        self.assertEqual(self.media(live).status_code, 200)

    def test_a_picture_the_live_site_stops_showing_goes_private_again(self):
        first, second = self.upload(), self.upload(alt="The new block")
        self.with_hero(first)
        self.with_hero(second)
        self.assertEqual(self.media(first).status_code, 404)
        self.assertEqual(self.media(second).status_code, 200)


class AlbumTests(PicturesSetUp):
    def test_a_delegated_administrator_builds_an_album_and_only_the_principal_publishes_it(self):
        self.delegate()
        with connected_to(self.stmarys):
            album = pictures.create_album_as(self.admin, self.stmarys, title="Inter-house sports, 2026")
        self.assertEqual(album.slug, "inter-house-sports-2026")
        made = self.upload(self.admin, "gallery", album=album, alt="", many=[photo(), photo()])
        with connected_to(self.stmarys):
            album.refresh_from_db()
            with self.assertRaises(NotAllowedToPublish):
                pictures.publish_album_as(self.admin, self.stmarys, album.pk, version=album.version)
            with self.assertRaisesMessage(SiteRefused, "Photo 1 has no description"):
                pictures.publish_album_as(self.principal, self.stmarys, album.pk, version=album.version)
            for p in made:
                pictures.save_picture_as(self.admin, self.stmarys, p.pk, version=p.version, alt="The relay")
            album.refresh_from_db()
            pictures.publish_album_as(self.principal, self.stmarys, album.pk, version=album.version)
            event = SitePublishEvent.objects.order_by("-id").first()
        self.assertEqual((event.kind, event.subject, event.by_name), ("album_published", album.title, "Rev. Sr. Okafor"))
        self.assertEqual(self.media(made[0]).status_code, 200)

    def test_photos_reorder_and_the_album_and_gallery_section_draw_them_in_that_order(self):
        album, made = self.album(photos=3)
        with connected_to(self.stmarys):
            pictures.order_photos_as(self.principal, self.stmarys, album.pk, [made[2].pk, made[0].pk, made[1].pk],
                                     version=album.version)
            album.refresh_from_db()
            pictures.publish_album_as(self.principal, self.stmarys, album.pk, version=album.version)
        self.gallery_page(album)
        page = self.get(f"/gallery/{album.slug}/").content.decode()
        order = [page.index(p.file_key) for p in (made[2], made[0], made[1])]
        self.assertEqual(order, sorted(order))
        self.assertIn("<figcaption>Caption 3</figcaption>", page)
        self.assertIn('loading="lazy"', page)
        home = self.get("/").content.decode()
        self.assertIn(made[2].file_key, home)
        self.assertNotIn(made[0].file_key, home)  # the section's count is 1
        # The mosaic's last tile counts the photos not shown, and is the way to the album.
        self.assertIn(f'<li class="count-tile"><a href="/gallery/{album.slug}/"><strong>+2</strong>'
                      '<span>See all 3 photos</span></a></li>', home)
        listing = self.get("/gallery/").content.decode()
        self.assertIn(album.title, listing)

    def test_a_draft_photo_added_to_a_published_album_is_not_public_until_published(self):
        album, _ = self.album()
        self.gallery_page(album)
        self.delegate()
        (extra,) = self.upload(self.admin, "gallery", album=album, alt="", many=[photo()])
        self.assertNotIn(extra.file_key, self.get(f"/gallery/{album.slug}/").content.decode())
        self.assertEqual(self.media(extra).status_code, 404)

    def test_only_the_principal_takes_a_photo_out_of_a_published_album_and_it_goes_at_the_next_publish(self):
        album, made = self.album()
        self.delegate()
        with connected_to(self.stmarys):
            with self.assertRaises(NotAllowedToPublish):
                pictures.remove_photo_as(self.admin, self.stmarys, album.pk, made[0].pk, version=album.version)
            pictures.remove_photo_as(self.principal, self.stmarys, album.pk, made[0].pk, version=album.version)
            album.refresh_from_db()
        self.assertEqual(self.media(made[0]).status_code, 200)  # still published
        with connected_to(self.stmarys):
            pictures.publish_album_as(self.principal, self.stmarys, album.pk, version=album.version)
            self.assertFalse(SitePicture.objects.filter(pk=made[0].pk).exists())
        self.assertEqual(self.on_disk(made[0]), [])
        self.assertEqual(self.media(made[0]).status_code, 404)

    def test_a_delegated_administrator_removes_a_draft_photo_outright(self):
        album, _ = self.album(publish=False)
        self.delegate()
        (extra,) = self.upload(self.admin, "gallery", album=album, alt="", many=[photo()])
        with connected_to(self.stmarys):
            album.refresh_from_db()
            pictures.remove_photo_as(self.admin, self.stmarys, album.pk, extra.pk, version=album.version)
            self.assertFalse(SitePicture.objects.filter(pk=extra.pk).exists())

    def test_an_unpublished_album_is_previewed_by_this_schools_editors_only(self):
        album, made = self.album(publish=False)
        self.assertEqual(self.get(f"/gallery/{album.slug}/").status_code, 404)
        self.client.force_login(self.principal)
        response = self.client.get(f"/website/preview/gallery/{album.slug}/", HTTP_HOST=ST_MARYS)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/website/pictures/{made[0].file_key}/480.avif", response.content.decode())
        self.assertEqual(response["Cache-Control"], "no-store")
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(f"/website/preview/gallery/{album.slug}/", HTTP_HOST=ST_MARYS).status_code, 403)
        self.client.force_login(self.grace_principal)
        self.assertIn(self.client.get(f"/website/preview/gallery/{album.slug}/", HTTP_HOST=GRACE).status_code, (403, 404))

    def test_an_album_of_another_school_is_not_here(self):
        theirs, their_photos = self.album(school=self.grace)
        with connected_to(self.stmarys):
            with self.assertRaisesMessage(SiteRefused, "That album is not on this site"):
                pictures.publish_album_as(self.principal, self.stmarys, theirs.pk, version=theirs.version)
        self.assertEqual(self.get(f"/gallery/{theirs.slug}/").status_code, 404)
        self.assertEqual(self.media(their_photos[0]).status_code, 404)
        self.assertEqual(self.media(their_photos[0], host=GRACE).status_code, 200)


class DeletingTests(PicturesSetUp):
    def test_an_unused_picture_is_deleted_with_every_size_of_it(self):
        picture = self.upload()
        self.assertTrue(self.on_disk(picture))
        with connected_to(self.stmarys), self.captureOnCommitCallbacks(execute=True):
            pictures.delete_picture_as(self.principal, self.stmarys, picture.pk, version=picture.version)
        with connected_to(self.stmarys):
            self.assertIsNone(files.find(picture.file_key))
        self.assertFalse(any((storage.root() / "st_marys").rglob(f"{picture.file_key}-*")))

    def test_a_picture_the_live_site_or_the_draft_uses_is_not_deleted(self):
        live = self.upload()
        self.with_hero(live)
        self.delegate()
        with connected_to(self.stmarys):
            with self.assertRaisesMessage(SiteRefused, "Use Take down now"):
                pictures.delete_picture_as(self.principal, self.stmarys, live.pk, version=live.version)
            with self.assertRaisesMessage(SiteRefused, "Only the principal can take it down"):
                pictures.delete_picture_as(self.admin, self.stmarys, live.pk, version=live.version)
        draft = self.upload(alt="New block")
        self.with_hero(draft, publish=False)
        with connected_to(self.stmarys), self.assertRaisesMessage(SiteRefused, "The draft uses this picture"):
            pictures.delete_picture_as(self.admin, self.stmarys, draft.pk, version=draft.version)

    def test_going_back_to_a_version_whose_picture_was_deleted_draws_it_without_the_picture(self):
        old = self.upload()
        first = self.with_hero(old, heading="Old")
        self.with_hero(self.upload(alt="New"), heading="New")
        with connected_to(self.stmarys):
            old.refresh_from_db()
            pictures.delete_picture_as(self.principal, self.stmarys, old.pk, version=old.version)
            services.rollback_as(self.principal, self.stmarys, first.number)
        html = self.get("/").content.decode()
        self.assertIn("<h1>Old</h1>", html)
        self.assertNotIn(old.file_key, html)
        self.assertNotIn("<picture>", html)


class TakeDownTests(PicturesSetUp):
    def setUp(self):
        super().setUp()
        self.hero = self.upload()
        self.album_, self.photos = self.album()
        self.gallery_page(self.album_)
        self.with_hero(self.hero)
        # Somebody's change to the draft the principal has not published yet.
        with connected_to(self.stmarys):
            page = Page.objects.get(key="about")
            services.save_page_as(self.principal, self.stmarys, "about", version=page.version, enabled=True)
        self.theirs = self.upload(school=self.grace)
        self.with_hero(self.theirs, school=self.grace)

    def take_down(self, picture, who=None, reason="Consent withdrawn"):
        # The files leave the disk once the take-down commits.
        with connected_to(self.stmarys), self.captureOnCommitCallbacks(execute=True):
            return pictures.take_down_as(who or self.principal, self.stmarys, picture.pk, reason=reason)

    def test_only_the_principal_takes_down_and_says_why(self):
        self.delegate()
        for who in (self.admin, self.teacher, self.grace_principal):
            with self.subTest(who=who.username), self.assertRaises(NotAllowed):
                self.take_down(self.hero, who)
        with self.assertRaisesMessage(SiteRefused, "Say why"):
            self.take_down(self.hero, reason="  ")

    def test_a_live_hero_is_gone_from_everywhere_at_once_and_nothing_else_of_the_draft_goes_live(self):
        self.assertIn(self.hero.file_key, self.get("/").content.decode())  # cached now
        with connected_to(self.stmarys):
            before = SiteRevision.objects.order_by("-number").first()
        event = self.take_down(self.hero)
        with connected_to(self.stmarys):
            latest = SiteRevision.objects.order_by("-number").first()
            self.assertEqual(latest.number, before.number + 1)
            self.assertEqual(latest.note, "Taken down: Consent withdrawn")
            self.assertEqual(event.revision_id, latest.pk)
            self.assertEqual((event.kind, event.note, event.by_name), ("taken_down", "Consent withdrawn", "Rev. Sr. Okafor"))
            self.assertEqual(event.subject, "The school gate")
            # The About page the principal switched on but never published stays off.
            self.assertFalse(next(p for p in latest.snapshot["pages"] if p["key"] == "about")["enabled"])
            hero = Section.objects.get(kind="hero")
            self.assertEqual(hero.data["slides"], [])
            self.assertFalse(SitePicture.objects.filter(pk=self.hero.pk).exists())
            self.assertIsNone(files.find(self.hero.file_key))
        self.assertFalse(any((storage.root() / "st_marys").rglob(f"{self.hero.file_key}-*")))
        self.assertNotIn(self.hero.file_key, self.get("/").content.decode())
        self.assertEqual(self.media(self.hero).status_code, 404)
        self.assertEqual(self.get("/about/").status_code, 404)

    def test_a_published_album_photo_leaves_the_album_page_and_every_gallery_section(self):
        photo_ = self.photos[0]
        self.assertIn(photo_.file_key, self.get(f"/gallery/{self.album_.slug}/").content.decode())
        self.take_down(photo_, reason="A parent asked")
        with connected_to(self.stmarys):
            album = Album.objects.get(pk=self.album_.pk)
            self.assertNotIn(photo_.pk, [p["id"] for p in album.published["photos"]])
        for path in (f"/gallery/{self.album_.slug}/", "/", "/gallery/"):
            with self.subTest(path=path):
                self.assertNotIn(photo_.file_key, self.get(path).content.decode())
        self.assertEqual(self.media(photo_).status_code, 404)

    def test_going_back_to_an_earlier_version_does_not_bring_it_back(self):
        with connected_to(self.stmarys):
            first = SiteRevision.objects.order_by("number").last()
        self.take_down(self.hero)
        with connected_to(self.stmarys):
            services.rollback_as(self.principal, self.stmarys, first.number)
        self.assertNotIn(self.hero.file_key, self.get("/").content.decode())

    def test_the_other_school_is_untouched(self):
        self.take_down(self.hero)
        self.assertIn(self.theirs.file_key, self.get("/", host=GRACE).content.decode())
        self.assertEqual(self.media(self.theirs, host=GRACE).status_code, 200)
        self.assertTrue(self.on_disk(self.theirs, self.grace))

    def test_every_cached_page_of_the_school_moves_to_a_new_key(self):
        from schoolsite import views

        with connected_to(self.stmarys):
            before = views._school_key(self.stmarys)
        self.take_down(self.photos[1])
        with connected_to(self.stmarys):
            self.assertNotEqual(views._school_key(self.stmarys), before)


class DrawnTests(PicturesSetUp):
    def test_the_hero_is_a_picture_in_three_formats_sized_and_preloaded_and_lazy_elsewhere(self):
        picture = self.upload(raw=samples.photo((2400, 1600)))
        self.with_hero(picture)
        html = self.get("/").content.decode()
        key = picture.file_key
        self.assertIn(f'<source type="image/avif" srcset="/media/{key}/480.avif 480w, /media/{key}/828.avif 828w, '
                      f'/media/{key}/1920.avif 1920w" sizes="{THEMES["modern"].sizes["hero"]}">', html)
        self.assertIn(f'src="/media/{key}/828.jpg" srcset="/media/{key}/828.jpg 828w, /media/{key}/1920.jpg 1920w"', html)
        self.assertIn('width="1920" height="1280" alt="The school gate" fetchpriority="high"', html)
        self.assertIn('<link rel="preload" as="image" type="image/avif" imagesrcset=', html)
        self.assertRegex(html, rf"\.p{picture.pk}\{{object-position:50\.0% 50\.0%;background-color:#[0-9A-F]{{6}}\}}")

    def test_the_focal_point_is_in_the_pages_own_style_never_an_attribute(self):
        picture = self.upload()
        with connected_to(self.stmarys):
            pictures.save_picture_as(self.principal, self.stmarys, picture.pk, version=picture.version,
                                     focal={"x": 0.25, "y": 0.8})
        self.with_hero(picture)
        response = self.get("/")
        html = response.content.decode()
        self.assertIn(f".p{picture.pk}{{object-position:25.0% 80.0%", html)
        self.assertNotRegex(html, r'\sstyle="')

    def test_a_page_runs_the_sites_script_only_with_a_gallery_or_a_video(self):
        self.with_hero(self.upload())
        self.assertIn("script-src 'none'", self.get("/")["Content-Security-Policy"])
        album, _ = self.album()
        self.gallery_page(album)
        response = self.get(f"/gallery/{album.slug}/")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertIn('<script type="module" src="/static/schoolsite/site-app.', response.content.decode())

    def test_the_principals_portrait(self):
        portrait = self.upload(use="portrait", raw=samples.photo((700, 900)), alt="Rev. Sr. Okafor")
        with connected_to(self.stmarys):
            services.add_section_as(self.principal, self.stmarys, "home", version=Page.objects.get(key="home").version,
                                    kind="principal_message", data={"message": "Welcome.", "portrait": portrait.pk})
            services.publish_as(self.principal, self.stmarys)
        html = self.get("/").content.decode()
        self.assertIn(f"/media/{portrait.file_key}/320.avif 320w", html)
        self.assertIn(f'sizes="{THEMES["modern"].sizes["portrait"]}"', html)
        self.assertIn('alt="Rev. Sr. Okafor" loading="lazy"', html)

    def test_publishing_waits_for_a_description_and_the_wrong_sort_of_picture_is_refused(self):
        gallery_photo = self.upload(use="gallery", album=self.album(publish=False)[0], alt="")
        with connected_to(self.stmarys):
            home = Page.objects.get(key="home")
            with self.assertRaisesMessage(SiteRefused, "That is not a hero picture"):
                services.add_section_as(self.principal, self.stmarys, "home", version=home.version, kind="hero",
                                        data={"heading": "Hi", "image": gallery_photo.pk})
            with self.assertRaisesMessage(SiteRefused, "That picture is not on this site"):
                services.add_section_as(self.principal, self.stmarys, "home", version=home.version, kind="hero",
                                        data={"heading": "Hi", "image": 999_999})

    def test_a_hero_video_draws_its_poster_and_gives_the_video_no_source(self):
        video = self.upload(raw=samples.video(seconds=1.0), video=True, alt="Students arriving")
        with connected_to(self.stmarys):
            services.add_section_as(self.principal, self.stmarys, "home", version=Page.objects.get(key="home").version,
                                    kind="hero", data={"heading": "Hi", "video": video.pk}, variant="video")
            services.publish_as(self.principal, self.stmarys)
        response = self.get("/")
        html = response.content.decode()
        self.assertIn(f"/media/{video.file_key}/poster-480.avif 480w", html)
        self.assertIn(f'data-src="/media/{video.file_key}/loop.mp4"', html)
        self.assertNotRegex(html, r"<video[^>]*\ssrc=")
        self.assertIn('preload="none"', html)
        self.assertIn('<button type="button" class="pause" aria-pressed="false" hidden>Pause the video</button>', html)
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(self.media(video, "loop.mp4").status_code, 200)

    def test_one_schools_pictures_never_appear_on_the_others_page(self):
        mine, theirs = self.upload(), self.upload(school=self.grace)
        self.with_hero(mine)
        self.with_hero(theirs, school=self.grace)
        a, b = self.get("/").content.decode(), self.get("/", host=GRACE).content.decode()
        self.assertIn(mine.file_key, a)
        self.assertNotIn(theirs.file_key, a)
        self.assertIn(theirs.file_key, b)
        self.assertNotIn(mine.file_key, b)


class TheMapTests(PicturesSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            services.save_page_as(self.principal, self.stmarys, "contact",
                                  version=Page.objects.get(key="contact").version, enabled=True)
            services.add_section_as(self.principal, self.stmarys, "contact",
                                    version=Page.objects.get(key="contact").version, kind="contact_map",
                                    data={"latitude": 7.38, "longitude": 3.9})
            services.add_section_as(self.principal, self.stmarys, "home", version=Page.objects.get(key="home").version,
                                    kind="hero", data={"heading": "Welcome"})
            services.publish_as(self.principal, self.stmarys)

    def test_the_contact_page_frames_nothing_until_the_map_is_asked_for(self):
        response = self.get("/contact/")
        html = response.content.decode()
        self.assertIn("frame-src 'none'", response["Content-Security-Policy"])
        self.assertNotIn("<iframe", html)
        self.assertIn('<a class="map-tap" id="map" href="/contact/?map=1#map">', html)
        self.assertTrue(response.indexable)

    def test_asked_for_the_page_frames_google_maps_and_only_that_page_allows_it(self):
        response = self.get("/contact/?map=1")
        html = response.content.decode()
        self.assertIn("frame-src https://www.google.com;", response["Content-Security-Policy"])
        self.assertIn('src="https://www.google.com/maps?q=7.38,3.9&amp;z=16&amp;output=embed"', html)
        self.assertIn('referrerpolicy="no-referrer"', html)
        self.assertFalse(response.indexable)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        # The plain page, after, is as it was: the map's page is cached apart.
        self.assertIn("frame-src 'none'", self.get("/contact/")["Content-Security-Policy"])
        self.assertIn("frame-src 'none'", self.get("/?map=1")["Content-Security-Policy"])


class RenditionBudgetTests(PicturesSetUp):
    """§4.1: the hero within 120 KB at 828 px and 250 KB at 1920; gallery sizes within theirs."""

    def test_the_sizes_a_phone_and_a_desktop_are_sent_fit_their_budgets(self):
        hero = self.upload(raw=samples.photo((3000, 2000)))
        with connected_to(self.stmarys):
            album = pictures.create_album_as(self.principal, self.stmarys, title="Speech day")
        (shot,) = self.upload(use="gallery", album=album, alt="", many=[samples.photo((3000, 2000))])
        with connected_to(self.stmarys):
            hero_sizes = files.find(hero.file_key).variants
            gallery_sizes = files.find(shot.file_key).variants
        for fmt in ("avif", "webp", "jpg"):
            with self.subTest(fmt=fmt):
                self.assertLessEqual(hero_sizes[f"828.{fmt}"]["bytes"], 120 * 1024)
                self.assertLessEqual(hero_sizes[f"1920.{fmt}"]["bytes"], 250 * 1024)
                self.assertLessEqual(gallery_sizes[f"1600.{fmt}"]["bytes"], 200 * 1024)
        for fmt in ("avif", "webp"):
            self.assertLessEqual(gallery_sizes[f"480.{fmt}"]["bytes"], 25 * 1024)


class EditorRouteTests(PicturesSetUp):
    def test_the_editors_route_sends_only_website_pictures_of_this_school(self):
        with connected_to(self.stmarys):
            crest = files.accept("crest", samples.logo(), slot="crest", by=self.principal)
        self.client.force_login(self.principal)
        self.assertEqual(self.client.get(f"/website/pictures/{crest.key}/card.png", HTTP_HOST=ST_MARYS).status_code, 404)
        theirs = self.upload(school=self.grace)
        self.assertEqual(self.editor_copy(theirs, self.principal).status_code, 404)
        self.assertEqual(self.editor_copy(theirs, self.grace_principal, host=GRACE).status_code, 200)



class TheEditorsApiTests(PicturesSetUp):
    """The editor's routes: the same rules as the services, asked of the person first, a sentence for each no."""

    BASE = "/api/website/"

    def post_files(self, who, files_, host=ST_MARYS, **fields):
        self.client.force_login(who)
        data = {**fields, "photo": files_}
        return self.client.post(f"{self.BASE}pictures/", data=data, HTTP_HOST=host)

    def call(self, method, path, who, host=ST_MARYS, **body):
        self.client.force_login(who)
        kwargs = {"HTTP_HOST": host}
        if body:
            kwargs.update(data=body, content_type="application/json")
        return getattr(self.client, method)(f"{self.BASE}{path}", **kwargs)

    def jpeg(self, name="gate.jpg"):
        return SimpleUploadedFile(name, photo(), content_type="image/jpeg")

    def test_an_upload_answers_with_the_new_picture_and_the_overview_lists_it(self):
        response = self.post_files(self.principal, [self.jpeg()], use="hero", alt="The gate", consent="1")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        (made,) = body["made"]
        listed = next(p for p in body["pictures"] if p["id"] == made)
        self.assertEqual((listed["state"], listed["alt"], listed["use"]), ("ready", "The gate", "hero"))
        self.assertTrue(listed["thumb"].startswith("/website/pictures/"))
        self.assertEqual(body["consent"], "Parents have agreed to photos of their children being published.")

    def test_without_consent_or_from_anybody_else_it_is_refused_and_nothing_is_kept(self):
        self.assertEqual(self.post_files(self.principal, [self.jpeg()], use="hero", alt="Gate").status_code, 422)
        for who in (self.admin, self.teacher):
            with self.subTest(who=who.username):
                response = self.post_files(who, [self.jpeg()], use="hero", alt="Gate", consent="1")
                self.assertEqual(response.status_code, 403)
        self.assertIn(self.post_files(self.grace_principal, [self.jpeg()], use="hero", alt="Gate", consent="1").status_code,
                      (403, 404))
        with connected_to(self.stmarys):
            self.assertEqual(SitePicture.objects.count(), 0)
            self.assertEqual(StoredFile.objects.count(), 0)

    def test_gallery_photos_go_into_an_album_five_at_a_time(self):
        response = self.call("post", "albums/", self.principal, title="Sports day")
        album = response.json()["album"]
        self.assertEqual((album["slug"], album["count"], album["live"]), ("sports-day", 0, False))
        response = self.post_files(self.principal, [self.jpeg(f"{n}.jpg") for n in range(3)], use="gallery",
                                   album=str(album["id"]), consent="on")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["album"]["photos"]), 3)
        too_many = self.post_files(self.principal, [self.jpeg(f"{n}.jpg") for n in range(6)], use="gallery",
                                   album=str(album["id"]), consent="on")
        self.assertEqual(too_many.status_code, 422)

    def test_a_delegated_administrator_may_not_publish_an_album_or_take_down(self):
        album, made = self.album(publish=False)
        self.delegate()
        response = self.call("post", f"albums/{album.pk}/publish/", self.admin, version=album.version)
        self.assertEqual(response.status_code, 403)
        response = self.call("post", f"pictures/{made[0].pk}/take-down/", self.admin, reason="Consent withdrawn")
        self.assertEqual(response.status_code, 403)
        response = self.call("post", f"albums/{album.pk}/publish/", self.principal, version=album.version)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["album"]["live"])

    def test_take_down_through_the_editor_logs_the_reason(self):
        picture = self.upload()
        self.with_hero(picture)
        response = self.call("post", f"pictures/{picture.pk}/take-down/", self.principal, reason="Consent withdrawn")
        self.assertEqual(response.status_code, 200, response.content)
        line = response.json()["log"][0]
        self.assertEqual((line["kind"], line["note"], line["subject"]), ("taken_down", "Consent withdrawn", "The school gate"))
        self.assertEqual(self.call("post", f"pictures/{picture.pk}/take-down/", self.principal,
                                   reason="Again").status_code, 422)

    def test_another_schools_picture_or_album_is_not_here(self):
        theirs, their_photos = self.album(school=self.grace)
        for method, path, body in (
            ("get", f"albums/{theirs.pk}/", {}),
            ("put", f"pictures/{their_photos[0].pk}/", {"version": 1, "alt": "Mine now"}),
            ("delete", f"pictures/{their_photos[0].pk}/?version=1", {}),
            ("post", f"pictures/{their_photos[0].pk}/take-down/", {"reason": "x"}),
        ):
            with self.subTest(path=path):
                response = self.call(method, path, self.principal, **body)
                self.assertIn(response.status_code, (403, 422))
        with connected_to(self.grace):
            self.assertEqual(SitePicture.objects.filter(album=theirs).count(), 2)
            self.assertFalse(SitePicture.objects.filter(alt="Mine now").exists())
