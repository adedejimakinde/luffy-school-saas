"""A school's own contact email — `PUT /api/academics/contact-email/`. D17.

Two schools throughout, as `test_setup_api.py` keeps: a write scoped to the
wrong school, or read from the wrong one, has somewhere to show.

Gated exactly as the rest of setup is (`can_set_up()`): the principal or an
administrator. Set on `School` itself, shared rather than tenant-scoped, so
it is asserted against the plain model row as well as the API's own answer.
"""

from django.test import override_settings

from results.tests.fixtures import HOST, THEIR_HOST, ChainSetUp
from schools.models import School
from schools.tests.tenants import connected_to

SETUP = "/api/academics/setup/"
CONTACT_EMAIL = "/api/academics/contact-email/"


class ContactEmailApiTests(ChainSetUp):
    def as_user(self, user):
        self.client.force_login(user.user)

    def set_contact_email(self, user, address, host=HOST):
        self.as_user(user)
        return self.client.put(
            CONTACT_EMAIL,
            data={"contact_email": address},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def setup_for(self, user, host=HOST):
        self.as_user(user)
        return self.client.get(SETUP, HTTP_HOST=host)

    def test_blank_by_default(self):
        self.assertEqual(self.setup_for(self.head).json()["contact_email"], "")

    def test_the_principal_sets_it_and_the_setup_screen_reads_it_back(self):
        response = self.set_contact_email(self.head, "office@stmarys.example")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["contact_email"], "office@stmarys.example")
        self.assertEqual(
            self.setup_for(self.head).json()["contact_email"], "office@stmarys.example"
        )

    def test_it_is_stored_on_the_school_row_itself(self):
        self.set_contact_email(self.head, "office@stmarys.example")

        self.assertEqual(
            School.objects.get(pk=self.stmarys.pk).contact_email, "office@stmarys.example"
        )

    def test_something_that_does_not_look_like_an_email_is_refused(self):
        response = self.set_contact_email(self.head, "not-an-email")

        self.assertEqual(response.status_code, 422)
        self.assertIn("does not look like an email address", response.json()["detail"])
        self.assertEqual(School.objects.get(pk=self.stmarys.pk).contact_email, "")

    def test_blank_clears_it(self):
        self.set_contact_email(self.head, "office@stmarys.example")

        response = self.set_contact_email(self.head, "")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["contact_email"], "")
        self.assertEqual(School.objects.get(pk=self.stmarys.pk).contact_email, "")

    def test_a_teacher_may_not_set_it(self):
        response = self.set_contact_email(self.teacher, "office@stmarys.example")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(School.objects.get(pk=self.stmarys.pk).contact_email, "")

    def test_grace_setting_its_own_never_touches_st_marys(self):
        self.set_contact_email(self.head, "office@stmarys.example")

        response = self.set_contact_email(self.their_head, "office@grace.example", host=THEIR_HOST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            School.objects.get(pk=self.stmarys.pk).contact_email, "office@stmarys.example"
        )
        self.assertEqual(
            School.objects.get(pk=self.grace.pk).contact_email, "office@grace.example"
        )
