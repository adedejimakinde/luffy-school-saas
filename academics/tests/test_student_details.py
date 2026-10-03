"""A child's details: learner's ID, sex, date of birth and passport photo.

Two schools in every test. The details live in each school's own schema
(`academics.StudentDetails`), and the child they are about is a **shared**
`Membership`, so what keeps one school's office out of another's children is
`details.student_here()`'s scoped lookup and the roll's authority check, not
the schema alone.
"""

import io
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from PIL import Image

from academics import details
from academics.models import StudentDetails
from accounts.tests.test_enrolment_api import EnrolmentSetUp
from results.tests.fixtures import HOST, THEIR_HOST
from schools.models import School
from schools.tests.tenants import connected_to

ROLL = "/api/enrolment/roll/"


def picture(fmt="JPEG", size=(1200, 1600), colour=(200, 120, 90), exif=None):
    out = io.BytesIO()
    image = Image.new("RGB", size, colour)
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def upload(raw, name="photo.jpg", content_type="image/jpeg"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, raw, content_type=content_type)


class DetailsSetUp(EnrolmentSetUp):
    def setUp(self):
        super().setUp()
        self.ada = self.children["ada"]
        self.emeka = self.children["emeka"]

    def details_url(self, child, part="details"):
        return f"{ROLL}{child.pk}/{part}/"

    def put(self, who, child, host=HOST, **values):
        self.client.force_login(who.user)
        body = {"learner_id": "", "sex": "", "date_of_birth": None}
        body.update(values)
        return self.client.put(
            self.details_url(child), data=body, content_type="application/json", HTTP_HOST=host
        )

    def get(self, who, child, host=HOST, part="details"):
        self.client.force_login(who.user)
        return self.client.get(self.details_url(child, part), HTTP_HOST=host)

    def send_photo(self, who, child, raw, host=HOST):
        self.client.force_login(who.user)
        return self.client.post(self.details_url(child, "photo"), {"photo": upload(raw)}, HTTP_HOST=host)


class RecordingDetailsTests(DetailsSetUp):
    def test_the_office_records_and_reads_back_a_childs_details(self):
        response = self.put(
            self.admin, self.ada, learner_id="OG/ABS/0042", sex="female", date_of_birth="2013-05-02"
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = self.get(self.admin, self.ada).json()
        self.assertEqual(
            (body["learner_id"], body["sex"], body["date_of_birth"], body["has_photo"]),
            ("OG/ABS/0042", "female", "2013-05-02", False),
        )
        self.assertTrue(body["may_edit"])

    def test_a_principal_may_keep_them_too(self):
        self.assertEqual(self.put(self.head, self.ada, sex="female").status_code, 200)

    def test_blank_clears_each(self):
        self.put(self.admin, self.ada, learner_id="X1", sex="male", date_of_birth="2013-05-02")
        self.put(self.admin, self.ada)
        body = self.get(self.admin, self.ada).json()
        self.assertEqual((body["learner_id"], body["sex"], body["date_of_birth"]), ("", "", None))

    def test_the_roll_lists_the_learner_id(self):
        self.put(self.admin, self.ada, learner_id="OG/ABS/0042")
        self.client.force_login(self.admin.user)
        children = self.client.get(ROLL, HTTP_HOST=HOST).json()["children"]
        by_name = {c["student"]: c["learner_id"] for c in children}
        self.assertEqual(by_name["Ada Obi"], "OG/ABS/0042")
        self.assertEqual(by_name["Emeka Nwosu"], "")

    def test_a_date_of_birth_in_the_future_is_refused_with_a_sentence(self):
        tomorrow = (date.today() + timedelta(days=2)).isoformat()
        response = self.put(self.admin, self.ada, date_of_birth=tomorrow)
        self.assertEqual(response.status_code, 422)
        self.assertIn("cannot be in the future", response.json()["detail"])

    def test_a_sex_that_is_not_one_is_refused(self):
        response = self.put(self.admin, self.ada, sex="x")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Female or Male", response.json()["detail"])


class ReadingWhatWasTypedTests(DetailsSetUp):
    def test_dates_are_day_first_and_iso_and_never_month_first(self):
        for typed in ("02/03/2014", "02-03-2014", "02.03.2014", "2014-03-02", date(2014, 3, 2)):
            with self.subTest(typed=typed):
                self.assertEqual(details.read_date_of_birth(typed), date(2014, 3, 2))

    def test_a_date_that_is_not_one_is_refused(self):
        for typed in ("31/02/2014", "yesterday", "13/13/13", "1/1/14"):
            with self.subTest(typed=typed), self.assertRaises(details.DetailsRefused):
                details.read_date_of_birth(typed)

    def test_sex_reads_the_ways_an_office_writes_it(self):
        for typed, read in (("F", "female"), ("female", "female"), ("Girl", "female"), ("M", "male"), (" Male ", "male"), ("", "")):
            with self.subTest(typed=typed):
                self.assertEqual(details.read_sex(typed), read)


class TheLearnerIdTests(DetailsSetUp):
    def test_two_children_at_one_school_cannot_share_one_ignoring_case(self):
        self.assertEqual(self.put(self.admin, self.ada, learner_id="OG/1").status_code, 200)

        response = self.put(self.admin, self.emeka, learner_id="og/1")

        self.assertEqual(response.status_code, 422)
        self.assertIn("already another child's learner's ID", response.json()["detail"])

    def test_a_child_keeps_her_own_on_a_second_save(self):
        self.put(self.admin, self.ada, learner_id="OG/1")
        self.assertEqual(self.put(self.admin, self.ada, learner_id="OG/1", sex="female").status_code, 200)

    def test_a_child_at_the_other_school_may_hold_the_same_one(self):
        self.put(self.admin, self.ada, learner_id="OG/1")
        response = self.put(self.their_admin, self.grace_child, host=THEIR_HOST, learner_id="OG/1")
        self.assertEqual(response.status_code, 200, response.content)

    def test_the_database_refuses_a_second_holder_by_the_constraints_name(self):
        """The service asks first; the constraint is what holds when two race."""
        with connected_to(self.stmarys):
            StudentDetails.objects.create(student_membership_id=self.ada.pk, learner_id="OG/1")
            with self.assertRaisesMessage(IntegrityError, "one_child_per_learner_id_per_school"):
                with transaction.atomic():
                    StudentDetails.objects.create(student_membership_id=self.emeka.pk, learner_id="og/1")

    def test_blank_is_not_a_value_two_children_collide_on(self):
        with connected_to(self.stmarys):
            StudentDetails.objects.create(student_membership_id=self.ada.pk, learner_id="")
            StudentDetails.objects.create(student_membership_id=self.emeka.pk, learner_id="")


class WhoMayTests(DetailsSetUp):
    def test_the_control_the_admin_reads_her_own_child(self):
        """Runs first: every refusal below would pass against a route that refused everybody."""
        self.assertEqual(self.get(self.admin, self.ada).status_code, 200)

    def test_a_teacher_and_a_bursar_are_refused_reading_and_writing(self):
        for who in (self.teacher, self.bursar):
            with self.subTest(who=who.user.username):
                self.assertEqual(self.get(who, self.ada).status_code, 403)
                self.assertEqual(self.put(who, self.ada, sex="female").status_code, 403)
                self.assertEqual(self.send_photo(who, self.ada, picture()).status_code, 403)
                self.assertEqual(self.get(who, self.ada, part="photo").status_code, 403)
        with connected_to(self.stmarys):
            self.assertFalse(StudentDetails.objects.exists())

    def test_the_other_schools_admin_cannot_reach_this_schools_child_from_her_own_host(self):
        self.put(self.admin, self.ada, learner_id="OG/1")
        self.send_photo(self.admin, self.ada, picture())

        for response in (
            self.get(self.their_admin, self.ada, host=THEIR_HOST),
            self.get(self.their_admin, self.ada, host=THEIR_HOST, part="photo"),
            self.put(self.their_admin, self.ada, host=THEIR_HOST, learner_id="STOLEN"),
            self.send_photo(self.their_admin, self.ada, picture(), host=THEIR_HOST),
        ):
            self.assertEqual(response.status_code, 404, response.content)
        with connected_to(self.stmarys):
            self.assertEqual(StudentDetails.objects.get().learner_id, "OG/1")
        with connected_to(self.grace):
            self.assertFalse(StudentDetails.objects.exists())

    def test_the_other_schools_admin_is_refused_on_this_schools_host(self):
        self.assertEqual(self.get(self.their_admin, self.ada).status_code, 403)

    def test_a_teacher_membership_id_is_not_a_child(self):
        self.assertEqual(self.get(self.admin, self.teacher).status_code, 404)


class ThePhotoTests(DetailsSetUp):
    def test_a_photo_is_redrawn_to_a_passport_frame_as_a_fresh_jpeg(self):
        exif = Image.Exif()
        exif[0x010F] = "SecretCam"  # Make
        response = self.send_photo(self.admin, self.ada, picture(size=(3000, 4000), exif=exif.tobytes()))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["has_photo"])
        served = self.get(self.admin, self.ada, part="photo")
        self.assertEqual(served["Content-Type"], "image/jpeg")
        image = Image.open(io.BytesIO(served.content))
        self.assertEqual((image.format, image.size), ("JPEG", details.PHOTO_SIZE))
        self.assertNotIn(b"SecretCam", served.content)

    def test_a_landscape_photo_is_cropped_not_stretched(self):
        raw = picture(size=(1600, 900))
        image = Image.open(io.BytesIO(details.redraw_photo(raw)))
        self.assertEqual(image.size, details.PHOTO_SIZE)

    def test_what_is_not_a_photo_is_refused_with_a_sentence(self):
        for raw, said in (
            (b"not an image at all", "not an image this can read"),
            (picture(fmt="GIF"), "PNG or a JPG"),
        ):
            with self.subTest(said=said):
                response = self.send_photo(self.admin, self.ada, raw)
                self.assertEqual(response.status_code, 422)
                self.assertIn(said, response.json()["detail"])

    def test_a_file_over_five_megabytes_is_refused_unread(self):
        response = self.send_photo(self.admin, self.ada, b"\xff\xd8" + b"x" * details.MAX_PHOTO_BYTES)
        self.assertEqual(response.status_code, 422)
        self.assertIn("at most 5 MB", response.json()["detail"])

    def test_removing_the_photo_leaves_the_rest(self):
        self.put(self.admin, self.ada, learner_id="OG/1")
        self.send_photo(self.admin, self.ada, picture())
        self.client.force_login(self.admin.user)
        response = self.client.delete(self.details_url(self.ada, "photo"), HTTP_HOST=HOST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["has_photo"], response.json()["learner_id"]), (False, "OG/1"))
        self.assertEqual(self.get(self.admin, self.ada, part="photo").status_code, 404)

    def test_each_schools_photo_is_its_own(self):
        self.send_photo(self.admin, self.ada, picture(colour=(250, 0, 0)))
        self.send_photo(self.their_admin, self.grace_child, picture(colour=(0, 0, 250)), host=THEIR_HOST)

        mine = Image.open(io.BytesIO(self.get(self.admin, self.ada, part="photo").content)).getpixel((140, 180))
        theirs = Image.open(
            io.BytesIO(self.get(self.their_admin, self.grace_child, host=THEIR_HOST, part="photo").content)
        ).getpixel((140, 180))
        self.assertGreater(mine[0], 200)
        self.assertGreater(theirs[2], 200)


class TheLocalGovernmentAreaTests(DetailsSetUp):
    def put_lga(self, who, lga, host=HOST):
        self.client.force_login(who.user)
        return self.client.put(
            "/api/academics/lga/", data={"lga": lga}, content_type="application/json", HTTP_HOST=host
        )

    def test_the_office_sets_it_and_setup_reads_it_back_per_school(self):
        self.assertEqual(self.put_lga(self.admin, "  Abeokuta   South ").status_code, 200)
        self.assertEqual(self.put_lga(self.their_admin, "Ifo", host=THEIR_HOST).status_code, 200)

        self.client.force_login(self.admin.user)
        body = self.client.get("/api/academics/setup/", HTTP_HOST=HOST).json()
        self.assertEqual(body["lga"], "Abeokuta South")
        self.assertEqual(len(body["lga_choices"]), 20)
        self.assertEqual(School.objects.get(pk=self.grace.pk).lga, "Ifo")

    def test_a_teacher_may_not_set_it(self):
        self.assertEqual(self.put_lga(self.teacher, "Ifo").status_code, 403)
        self.assertEqual(School.objects.get(pk=self.stmarys.pk).lga, "")

    def test_a_long_one_is_refused(self):
        self.assertEqual(self.put_lga(self.admin, "x" * 61).status_code, 422)
