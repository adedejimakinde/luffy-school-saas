"""Who is sent which file, at two schools.

A single school could not fail for the mistakes that matter here: a file
looked up somewhere shared, a key that works on any school's host, or a
private file on the public path. So there are two, St Mary's and Grace, each
with a public crest and a private child's photo, and the claims are:

- **A school's file is never served on another school's host**, with its key,
  signed in or not, whoever is asking, and in production mode Caddy is never
  told its path there.
- **A private file is never served to the public**: not on `/media/` at all,
  and on `/files/` only to that school's office (principal, administrator).
  Not to a teacher, not to platform staff, not to another school's principal.
- **The public path reads no session**: no cookie set, no `Vary: Cookie`.
- **The quota is per school**, and a nearly full disk refuses new uploads.
- **The queue is the default**: an upload answers `pending` and the media
  worker finishes it.
"""

from unittest import mock

from django.db import connection
from django.test import override_settings

from accounts.models import Role, User
from accounts.services import grant_membership
from files import service, storage
from files.kinds import Kind
from files.models import State, StoredFile
from schools.models import School
from schools.tests.tenants import connected_to
from schools.tests.test_paths import GRACE, ST_MARYS, TwoSchoolsSetUp

from . import samples

PASSWORD = "a-long-password-1"


def body(response) -> bytes:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


class FilesSetUp(TwoSchoolsSetUp):
    def setUp(self):
        super().setUp()
        self.principal = grant_membership(
            User.objects.create_user("pat", PASSWORD), self.st_marys, Role.PRINCIPAL
        ).user
        self.teacher = grant_membership(
            User.objects.create_user("tee", PASSWORD), self.st_marys, Role.TEACHER
        ).user
        self.their_principal = grant_membership(
            User.objects.create_user("gpat", PASSWORD), self.grace, Role.PRINCIPAL
        ).user
        self.ops = User.objects.get(username="ops")

        self.crest = self.upload(self.st_marys, Kind.CREST, samples.logo(), slot="crest", by=self.principal)
        self.photo = self.upload(self.st_marys, Kind.STUDENT_PHOTO, samples.photo((900, 1200)), slot="student_photo:1")
        self.their_crest = self.upload(self.grace, Kind.CREST, samples.logo(), slot="crest", by=self.their_principal)
        self.their_photo = self.upload(self.grace, Kind.STUDENT_PHOTO, samples.photo((900, 1200)), slot="student_photo:1")

    def upload(self, school, kind, raw, slot="", by=None):
        with connected_to(school):
            stored = service.accept(kind, raw, slot=slot, by=by)
            self.assertEqual(stored.state, State.READY, stored.error)
            return stored

    def get(self, path, host=ST_MARYS, user=None, **extra):
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(path, HTTP_HOST=host, **extra)


class TheControlTests(FilesSetUp):
    """Every refusal below would pass against a route that serves nothing."""

    def test_a_public_crest_is_served_on_its_own_host_to_anybody(self):
        response = self.get(f"/media/{self.crest.key}/site.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Cache-Control"], "public, max-age=31536000, immutable")
        with connected_to(self.st_marys):
            self.assertEqual(body(response), service.read(self.crest, "site.png"))

    def test_a_private_photo_is_served_to_its_schools_principal(self):
        response = self.get(f"/files/{self.photo.key}/card.jpg", user=self.principal)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Content-Type"], "image/jpeg")


class AFileIsNeverServedOnAnotherSchoolsHostTests(FilesSetUp):
    def test_st_marys_public_crest_is_a_404_on_graces_host(self):
        for user in (None, self.their_principal, self.ops):
            with self.subTest(user=getattr(user, "username", "nobody")):
                self.assertEqual(self.get(f"/media/{self.crest.key}/site.png", host=GRACE, user=user).status_code, 404)

    def test_st_marys_private_photo_is_a_404_on_graces_host_even_to_graces_principal(self):
        response = self.get(f"/files/{self.photo.key}/card.jpg", host=GRACE, user=self.their_principal)
        self.assertEqual(response.status_code, 404)

    def test_graces_principal_cannot_take_st_marys_photo_from_st_marys_host(self):
        response = self.get(f"/files/{self.photo.key}/card.jpg", host=ST_MARYS, user=self.their_principal)
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(b"JFIF", body(response))

    def test_each_host_serves_its_own_crest_and_not_the_others(self):
        self.assertEqual(self.get(f"/media/{self.their_crest.key}/site.png", host=GRACE).status_code, 200)
        self.assertEqual(self.get(f"/media/{self.their_crest.key}/site.png", host=ST_MARYS).status_code, 404)

    def test_a_row_naming_another_schema_is_not_found_even_in_this_one(self):
        """`schema_name` is checked as well as `search_path` (`files.models`)."""
        with connected_to(self.grace):
            StoredFile.objects.filter(pk=self.their_crest.pk).update(schema_name="st_marys")
            self.assertIsNone(service.find(self.their_crest.key))
            self.assertIsNone(service.current("crest"))
            self.assertEqual(service.usage()["files"], 1)
        self.assertEqual(self.get(f"/media/{self.their_crest.key}/site.png", host=GRACE).status_code, 404)

    def test_the_files_are_in_each_schools_own_directory(self):
        self.assertTrue(storage.path_of("st_marys", self.crest.key, "site.png").is_file())
        self.assertFalse(storage.path_of("grace", self.crest.key, "site.png").exists())
        self.assertTrue(storage.path_of("grace", self.their_crest.key, "site.png").is_file())

    @override_settings(FILES_X_ACCEL=True)
    def test_in_production_caddy_is_told_this_schools_path_and_no_other(self):
        sent = self.get(f"/media/{self.crest.key}/site.png")
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent["X-Accel-Redirect"], f"/st_marys/{self.crest.key[:2]}/{self.crest.key}-site.png")
        self.assertEqual(sent.content, b"")

        refused = self.get(f"/media/{self.crest.key}/site.png", host=GRACE)
        self.assertEqual(refused.status_code, 404)
        self.assertFalse(refused.has_header("X-Accel-Redirect"))


class APrivateFileIsNeverPublicTests(FilesSetUp):
    def test_a_private_photo_is_not_on_the_public_path_for_anybody(self):
        for user in (None, self.principal, self.teacher, self.ops):
            with self.subTest(user=getattr(user, "username", "nobody")):
                self.assertEqual(self.get(f"/media/{self.photo.key}/card.jpg", user=user).status_code, 404)

    def test_on_the_private_path_only_the_office_gets_it(self):
        for user in (None, self.teacher, self.ops):
            with self.subTest(user=getattr(user, "username", "nobody")):
                response = self.get(f"/files/{self.photo.key}/card.jpg", user=user)
                self.assertNotEqual(response.status_code, 200)
                self.assertNotIn(b"JFIF", body(response))

    def test_a_signature_is_private(self):
        signature = self.upload(self.st_marys, Kind.SIGNATURE, samples.logo((900, 300)), slot="signature")
        self.assertFalse(signature.public)
        self.assertEqual(self.get(f"/media/{signature.key}/card.png").status_code, 404)
        self.assertEqual(self.get(f"/files/{signature.key}/card.png", user=self.principal).status_code, 200)

    def test_a_variant_or_key_that_is_not_one_is_a_404_not_a_path(self):
        for path in (
            f"/media/{self.crest.key}/..%2f..%2fetc%2fpasswd",
            f"/media/{self.crest.key}/master.pdf",
            f"/media/{self.crest.key[:-1]}x/site.png",
            "/media/not-a-key/site.png",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 404)

    def test_a_document_is_sent_as_a_download_that_runs_nothing(self):
        document = self.upload(self.st_marys, Kind.DOCUMENT, samples.pdf(javascript=True))
        response = self.get(f"/files/{document.key}/document.pdf", user=self.principal)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertIn("sandbox", response["Content-Security-Policy"])


class ThePublicPathReadsNoSessionTests(FilesSetUp):
    def test_no_cookie_and_no_vary_on_cookie_even_when_signed_in(self):
        response = self.get(f"/media/{self.crest.key}/site.png", user=self.principal)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sessionid", response.cookies)
        self.assertNotIn("Cookie", response.get("Vary", ""))


class TheQuotaIsPerSchoolTests(FilesSetUp):
    def test_a_full_school_is_refused_and_the_other_is_not(self):
        School.objects.filter(pk=self.st_marys.pk).update(storage_quota_bytes=1024)
        self.st_marys.refresh_from_db()

        with connected_to(self.st_marys):
            connection.tenant.storage_quota_bytes = 1024
            with self.assertRaisesRegex(service.UploadRefused, "of its 0 MB of storage"):
                service.accept(Kind.GALLERY_IMAGE, samples.photo((800, 600)))
        self.upload(self.grace, Kind.GALLERY_IMAGE, samples.photo((800, 600)))

    def test_usage_counts_each_schools_own(self):
        with connected_to(self.st_marys):
            mine = service.usage()
        with connected_to(self.grace):
            theirs = service.usage()
        self.assertEqual(mine["files"], 2)
        self.assertEqual(theirs["files"], 2)
        self.assertEqual(mine["bytes"], self.crest.bytes + self.photo.bytes)

    def test_a_nearly_full_disk_refuses_new_uploads(self):
        with mock.patch.object(storage, "percent_used", return_value=91.0):
            with connected_to(self.st_marys):
                with self.assertRaisesRegex(service.UploadRefused, "storage is nearly full"):
                    service.accept(Kind.CREST, samples.logo(), slot="crest")


class ASlotHoldsOneFileTests(FilesSetUp):
    def test_a_new_crest_replaces_the_old_once_ready_and_the_old_is_kept_a_day(self):
        new = self.upload(self.st_marys, Kind.CREST, samples.logo((500, 500)), slot="crest")
        with connected_to(self.st_marys):
            self.assertEqual(service.current("crest").pk, new.pk)
            old = StoredFile.objects.get(pk=self.crest.pk)
        self.assertEqual(old.state, State.RETIRED)
        # A page cached a minute ago still points at the old one.
        self.assertEqual(self.get(f"/media/{self.crest.key}/site.png").status_code, 200)

    def test_a_replaced_private_photo_is_gone_at_once(self):
        self.upload(self.st_marys, Kind.STUDENT_PHOTO, samples.photo((900, 1200)), slot="student_photo:1")
        with connected_to(self.st_marys):
            self.assertFalse(StoredFile.objects.filter(pk=self.photo.pk).exists())
        self.assertEqual(self.get(f"/files/{self.photo.key}/card.jpg", user=self.principal).status_code, 404)

    def test_a_failed_upload_leaves_the_current_one_in_place(self):
        with connected_to(self.st_marys):
            refuse = mock.Mock(side_effect=service.images.Refused("That crest could not be read."))
            with mock.patch.dict("files.images.PROCESSORS", {"mark": refuse}):
                broken = service.accept(Kind.CREST, samples.logo(), slot="crest")
            self.assertEqual(broken.state, State.FAILED)
            self.assertEqual(service.current("crest").pk, self.crest.pk)
            self.assertEqual(service.status_of("crest")["problem"], "That crest could not be read.")


class TheQueueTests(FilesSetUp):
    """The fixture's uploads are processed inline; these turn that off."""

    @override_settings(FILES_PROCESS_INLINE=False)
    def test_an_upload_answers_pending_and_the_worker_finishes_it(self):
        with connected_to(self.st_marys):
            with mock.patch("files.tasks.process_upload.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    pending = service.accept(Kind.GALLERY_IMAGE, samples.photo((1600, 1000)))
            self.assertEqual(pending.state, State.PENDING)
            self.assertTrue(storage.incoming_path("st_marys", pending.key).is_file())
            publish.assert_called_once_with(args=["st_marys", pending.key], retry=False)

            with self.captureOnCommitCallbacks(execute=True):
                done = service.process("st_marys", pending.key)
            self.assertEqual(done.state, State.READY)
            self.assertFalse(storage.incoming_path("st_marys", pending.key).exists())
            # Redelivered: nothing happens a second time.
            self.assertEqual(service.process("st_marys", pending.key).processed_at, done.processed_at)

    def test_the_jobs_go_to_the_media_queue(self):
        from django.conf import settings

        self.assertEqual(settings.CELERY_TASK_ROUTES["files.tasks.*"], {"queue": "media"})

    @override_settings(FILES_PROCESS_INLINE=False)
    def test_a_broker_that_is_down_leaves_it_pending_for_the_next_read_to_ask_again(self):
        with connected_to(self.st_marys):
            with mock.patch("files.tasks.process_upload.apply_async", side_effect=OSError("broker down")):
                with self.captureOnCommitCallbacks(execute=True):
                    pending = service.accept(Kind.CREST, samples.logo(), slot="crest")
            self.assertEqual(StoredFile.objects.get(pk=pending.pk).state, State.PENDING)
            StoredFile.objects.filter(pk=pending.pk).update(last_enqueued_at="2000-01-01T00:00Z")
            with mock.patch("files.tasks.process_upload.apply_async") as publish:
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertTrue(service.status_of("crest")["processing"])
            publish.assert_called_once()
