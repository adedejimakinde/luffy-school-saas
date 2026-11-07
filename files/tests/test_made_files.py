"""A file the server made for one person (`Family.MADE`): kept a day, sent to that person only.

Report cards (`Kind.CLASS_CARDS`) were the first; a class's master broadsheet as
a PDF or an Excel file (`Kind.CLASS_BROADSHEET`) is the second, and it brought a
spreadsheet where there had only been PDFs. What is held here is what must stay
true of every made file, whichever feature made it:

- it is **private** and the generic `/files/` route sends it to nobody, because
  its kind has no readers (the feature's own route asks who the person is);
- a spreadsheet is sent **as a spreadsheet, as an attachment, under the name the
  feature gave it**, and a name that is not one of the known file types is refused;
- it is **removed a day after it was made** by the hourly sweep, in its own school
  only;
- an **uploaded** kind cannot be kept this way, and a made one cannot be uploaded.
"""

import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import override_settings
from django.utils import timezone

from files import service, storage
from files.kinds import Family, Kind, profile_for
from files.models import StoredFile
from files.views import PRIVATE, send
from schools.tests.tenants import connected_to
from schools.tests.test_paths import GRACE, ST_MARYS

from .test_isolation import FilesSetUp, body

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MadeFileTests(FilesSetUp):
    def make(self, school, *, name="class-broadsheet.xlsx", kind=Kind.CLASS_BROADSHEET, content=b"PK\x03\x04 a spreadsheet"):
        with connected_to(school):
            building = storage.building_dir(school.schema_name)
            self.addCleanup(lambda: __import__("shutil").rmtree(building, ignore_errors=True))
            source = building / name
            source.write_bytes(content)
            return service.keep_made(kind, source, name, by_id=self.principal.pk)

    def test_the_broadsheet_is_a_made_private_file_with_no_readers(self):
        profile = profile_for(Kind.CLASS_BROADSHEET)
        self.assertEqual(profile.family, Family.MADE)
        self.assertFalse(profile.public)
        self.assertEqual(profile.readers, frozenset())

    def test_a_spreadsheet_is_sent_as_one_and_as_an_attachment_for_the_person_it_was_made_for(self):
        stored = self.make(self.st_marys)
        with connected_to(self.st_marys):
            response = send(
                service.find(stored.key), "class-broadsheet.xlsx",
                cache_control=PRIVATE, download_name="broadsheet-jss-1a.xlsx",
            )
            self.assertEqual(response["Content-Type"], XLSX)
            self.assertEqual(response["Content-Disposition"], 'attachment; filename="broadsheet-jss-1a.xlsx"')
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.assertEqual(body(response), b"PK\x03\x04 a spreadsheet")

    def test_the_generic_route_sends_it_to_nobody(self):
        stored = self.make(self.st_marys)
        for user in (self.principal, self.teacher, self.ops, None):
            with self.subTest(user=getattr(user, "username", "nobody")):
                self.assertEqual(
                    self.get(f"/files/{stored.key}/class-broadsheet.xlsx", user=user).status_code, 404
                )
        self.assertEqual(self.get(f"/media/{stored.key}/class-broadsheet.xlsx").status_code, 404)

    def test_it_is_a_404_on_another_schools_host(self):
        stored = self.make(self.st_marys)
        for user in (None, self.their_principal):
            self.assertEqual(
                self.get(f"/files/{stored.key}/class-broadsheet.xlsx", host=GRACE, user=user).status_code, 404
            )

    def test_a_variant_that_is_not_a_known_file_type_is_refused(self):
        for name in ("class-broadsheet.exe", "class-broadsheet.xls", "../escape.xlsx", "x.xlsx.html"):
            with self.subTest(name=name):
                with self.assertRaises(storage.BadName):
                    self.make(self.st_marys, name=name)

    def test_it_is_removed_after_a_day_and_only_in_its_own_school(self):
        old = self.make(self.st_marys)
        young = self.make(self.st_marys)
        theirs = self.make(self.grace)
        with connected_to(self.st_marys):
            StoredFile.objects.filter(key=old.key).update(created_at=timezone.now() - timedelta(hours=24, seconds=1))
            StoredFile.objects.filter(key=young.key).update(created_at=timezone.now() - timedelta(hours=23, minutes=59))
            self.assertTrue(service.is_expired(service.find(old.key)))
            self.assertFalse(service.is_expired(service.find(young.key)))
        with connected_to(self.grace):
            StoredFile.objects.filter(key=theirs.key).update(created_at=timezone.now() - timedelta(days=3))
        with connected_to(self.st_marys), self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(service.sweep()["expired"], 1)
            self.assertFalse(StoredFile.objects.filter(key=old.key).exists())
            self.assertTrue(StoredFile.objects.filter(key=young.key).exists())
        self.assertFalse(storage.path_of("st_marys", old.key, "class-broadsheet.xlsx").exists())
        self.assertTrue(storage.path_of("st_marys", young.key, "class-broadsheet.xlsx").exists())
        # Grace's, a day past its time, is Grace's sweep's to remove, not St Mary's.
        self.assertTrue(storage.path_of("grace", theirs.key, "class-broadsheet.xlsx").exists())
        with connected_to(self.grace), self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(service.sweep()["expired"], 1)

    def test_an_uploaded_kind_cannot_be_kept_this_way(self):
        with self.assertRaises(ValueError):
            self.make(self.st_marys, kind=Kind.CREST, name="class-broadsheet.pdf")
