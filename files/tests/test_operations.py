"""The operator's side: moving old files, the hourly check, and the platform page.

- `move_files_to_disk` writes nothing on a dry run, moves each school's own
  bytes into that school's storage on `--apply`, moves nothing twice, and its
  rollback leaves the previous release showing the same crest and photo.
- `check_storage` emails hello@classnode.co past 70% (once a day), prints a
  line to the cron log every time, and fails the run past the line.
- The platform page's storage figures and quota are platform staff's alone.
"""

import io
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import override_settings

from academics.models import StudentDetails
from files import service, storage
from files.kinds import Kind
from files.models import StoredFile
from results.models import ReportCardSettings
from schools.models import School
from schools.tests.tenants import connected_to
from schools.tests.test_paths import PORTAL_HOST

from . import samples
from .test_isolation import FilesSetUp, body


def solid(colour):
    """A passport photo of one colour, as the old column held: a 280 x 360 JPEG."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (280, 360), colour).save(out, format="JPEG", quality=85)
    return out.getvalue()


def run(*args):
    out = io.StringIO()
    call_command("move_files_to_disk", *args, stdout=out)
    return out.getvalue()


class TheMoveTests(FilesSetUp):
    def setUp(self):
        super().setUp()
        # What the release before this one left behind: bytes in the columns.
        for school, colour in ((self.st_marys, (200, 0, 0)), (self.grace, (0, 0, 200))):
            with connected_to(school):
                StoredFile.objects.all().delete()
                ReportCardSettings.objects.update_or_create(pk=1, defaults={"crest": samples.logo()})
                StudentDetails.objects.create(student_membership_id=7, photo=solid(colour))

    def files(self, school):
        with connected_to(school):
            return StoredFile.objects.count()

    def test_a_dry_run_says_what_would_move_and_writes_nothing(self):
        said = run()

        self.assertIn("DRY RUN", said)
        self.assertIn("st_marys: 1 crest", said)
        self.assertIn("grace: 1 student_photo", said)
        self.assertEqual((self.files(self.st_marys), self.files(self.grace)), (0, 0))

    def test_apply_moves_each_schools_own_into_its_own_storage_and_twice_is_once(self):
        said = run("--apply")
        self.assertIn("Done.", said)
        self.assertEqual((self.files(self.st_marys), self.files(self.grace)), (2, 2))

        with connected_to(self.st_marys):
            from academics.details import photo_of
            from PIL import Image

            crest = service.current("crest")
            self.assertEqual(crest.origin, "migrated")
            self.assertTrue(storage.path_of("st_marys", crest.key, "card.png").is_file())
            self.assertGreater(Image.open(io.BytesIO(photo_of(7))).getpixel((140, 180))[0], 150)
            # The column is left as it was until a later release drops it.
            self.assertIsNotNone(ReportCardSettings.objects.get(pk=1).crest)
        with connected_to(self.grace):
            self.assertGreater(Image.open(io.BytesIO(photo_of(7))).getpixel((140, 180))[2], 150)

        self.assertIn("Nothing to do.", run("--apply"))
        self.assertEqual((self.files(self.st_marys), self.files(self.grace)), (2, 2))

    def test_the_rollback_puts_the_current_files_back_and_removes_them(self):
        run("--apply")
        # A new crest uploaded after the deploy must survive going back.
        newer = self.upload(self.st_marys, Kind.CREST, samples.logo((500, 300)), slot="crest")
        with connected_to(self.st_marys):
            expected = service.read(newer, "card.png")

        self.assertIn("would be copied back", run("--rollback"))
        # The new crest, the moved one it replaced (kept a day), and the photo.
        self.assertEqual(self.files(self.st_marys), 3)

        said = run("--rollback", "--apply")
        self.assertIn("Rolled back.", said)
        self.assertEqual((self.files(self.st_marys), self.files(self.grace)), (0, 0))
        with connected_to(self.st_marys):
            self.assertEqual(bytes(ReportCardSettings.objects.get(pk=1).crest), expected)


class TheHourlyCheckTests(FilesSetUp):
    def setUp(self):
        super().setUp()
        self.forget_the_last_alert()
        self.addCleanup(self.forget_the_last_alert)

    def forget_the_last_alert(self):
        (storage.root() / ".disk-alert-sent").unlink(missing_ok=True)

    def check(self, used_percent):
        out = io.StringIO()
        total = 100 * 1024 ** 3
        with mock.patch.object(storage, "disk_usage", return_value=(int(total * used_percent / 100), total)):
            try:
                call_command("check_storage", stdout=out)
                failed = False
            except CommandError:
                failed = True
        return out.getvalue(), failed

    def test_below_seventy_percent_it_prints_a_line_and_emails_nobody(self):
        said, failed = self.check(41)
        self.assertIn("check_storage: disk 41.0% used", said)
        self.assertIn("2 schools keep", said)
        self.assertFalse(failed)
        self.assertEqual(len(mail.outbox), 0)

    def test_past_seventy_percent_it_emails_hello_once_a_day_and_fails_the_run(self):
        said, failed = self.check(72)
        self.assertTrue(failed)
        self.assertIn("ALERT: [Classnode] Disk 72% full", said)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["hello@classnode.co"])
        self.assertIn("St Mary's College (st-marys)", mail.outbox[0].body)

        said, failed = self.check(73)
        self.assertTrue(failed)
        self.assertIn("already emailed", said)
        self.assertEqual(len(mail.outbox), 1)

    def test_past_ninety_percent_it_emails_every_time(self):
        self.check(91)
        self.check(92)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("being refused now", mail.outbox[1].body)

    def test_an_alert_that_cannot_be_emailed_says_so_in_the_log(self):
        with mock.patch("schools.alerts.send_mail", side_effect=OSError("no mail host")):
            said, failed = self.check(80)
        self.assertTrue(failed)
        self.assertIn("ALERT NOT EMAILED to hello@classnode.co", said)

    def test_the_backup_script_alerts_through_the_same_path(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("restic: unable to open repository")):
            call_command("send_ops_alert", "Media backup FAILED", stdout=out)
        self.assertIn("ALERT: [Classnode] Media backup FAILED", out.getvalue())
        self.assertEqual(mail.outbox[0].to, ["hello@classnode.co"])
        self.assertIn("unable to open repository", mail.outbox[0].body)


class ThePlatformPageTests(FilesSetUp):
    def test_platform_staff_see_each_schools_storage_and_set_a_quota(self):
        self.client.force_login(self.ops)
        answer = self.client.get("/api/platform/storage/", HTTP_HOST=PORTAL_HOST)
        self.assertEqual(answer.status_code, 200, answer.content)
        rows = {r["subdomain"]: r for r in answer.json()["schools"]}
        self.assertEqual(rows["st-marys"]["files"], 2)
        self.assertEqual(rows["st-marys"]["quota_bytes"], 1024 ** 3)
        self.assertTrue(rows["st-marys"]["default_quota"])
        self.assertIn("percent", answer.json()["disk"])

        changed = self.client.put("/api/platform/schools/grace/quota/", {"quota_mb": 2048},
                                  content_type="application/json", HTTP_HOST=PORTAL_HOST)
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(School.objects.get(pk=self.grace.pk).storage_quota_bytes, 2048 * 1024 ** 2)
        self.assertEqual(School.objects.get(pk=self.st_marys.pk).storage_quota_bytes, None)

        back = self.client.put("/api/platform/schools/grace/quota/", {"quota_mb": None},
                               content_type="application/json", HTTP_HOST=PORTAL_HOST)
        self.assertEqual(back.status_code, 200)
        self.assertIsNone(School.objects.get(pk=self.grace.pk).storage_quota_bytes)

    def test_a_schools_principal_cannot_see_or_set_them(self):
        self.client.force_login(self.principal)
        self.assertEqual(self.client.get("/api/platform/storage/", HTTP_HOST=PORTAL_HOST).status_code, 403)
        self.assertEqual(
            self.client.put("/api/platform/schools/st-marys/quota/", {"quota_mb": 99999},
                            content_type="application/json", HTTP_HOST=PORTAL_HOST).status_code,
            403,
        )
        self.assertIsNone(School.objects.get(pk=self.st_marys.pk).storage_quota_bytes)
