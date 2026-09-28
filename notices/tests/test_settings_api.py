"""The settings screen's one route: `/api/notices/settings/`.

Two schools throughout, as every other notices test file keeps: St Mary's is
under test, and Grace has its own admin and its own staff, so a read or a
write that forgot to scope by school has somewhere to leak into.

**Nobody is chosen by default** — the daily money summary's own extension to
D15 — so a school that turns the digest on and picks nobody gets a row that
says so, and the page reads the same live staff list `active_staff()` already
serves the staff-invitations screen.
"""

import json

from django.db import connection
from django.test import TestCase

from accounts.models import Role, User
from accounts.services import grant_membership
from notices.models import MoneySummaryRecipient, NoticeSettings
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"


class SettingsApiSetUp(TestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=THEIR_HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        self.admin = self.staff("ade", "Ade Admin", Role.ADMIN, self.stmarys, "ade@stmarys.example")
        self.principal = self.staff("ngozi", "Ngozi Head", Role.PRINCIPAL, self.stmarys, "ngozi@stmarys.example")
        self.bursar = self.staff("bola", "Bola Bursar", Role.BURSAR, self.stmarys, "bola@stmarys.example")
        self.teacher = self.staff("kemi", "Kemi Teacher", Role.TEACHER, self.stmarys, "kemi@stmarys.example")
        self.their_admin = self.staff("grace-ade", "Grace Admin", Role.ADMIN, self.grace, "admin@grace.example")

    def tearDown(self):
        connection.set_schema_to_public()

    def staff(self, username, name, role, school, email):
        user = User.objects.create_user(username, PASSWORD, full_name=name, email=email)
        membership = grant_membership(user, school, role)
        user.membership_id = membership.pk
        return user

    def get(self, user, host=HOST):
        self.client.force_login(user)
        return self.client.get("/api/notices/settings/", HTTP_HOST=host)

    def post(self, user, body, host=HOST):
        self.client.force_login(user)
        return self.client.post(
            "/api/notices/settings/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=host,
        )


class ReadingTests(SettingsApiSetUp):
    def test_all_three_switches_are_off_and_nobody_is_chosen_by_default(self):
        body = self.get(self.admin).json()

        self.assertEqual(body["payment_receipts"], False)
        self.assertEqual(body["absence_alerts"], False)
        self.assertEqual(body["daily_money_summary"], False)
        self.assertEqual(body["money_summary_recipient_ids"], [])

    def test_the_live_staff_list_is_offered_to_pick_recipients_from(self):
        body = self.get(self.admin).json()

        names = {row["name"] for row in body["staff"]}
        self.assertEqual(
            names,
            {self.admin.full_name, self.principal.full_name, self.bursar.full_name, self.teacher.full_name},
        )

    def test_the_principal_may_read_it_too(self):
        self.assertEqual(self.get(self.principal).status_code, 200)

    def test_a_bursar_or_a_teacher_may_not(self):
        for user in (self.bursar, self.teacher):
            with self.subTest(user=user.username):
                response = self.get(user)
                self.assertEqual(response.status_code, 403)
                self.assertIn("principal or an administrator", response.json()["detail"])

    def test_the_portal_has_no_settings_to_read(self):
        self.client.force_login(self.admin)
        response = self.client.get("/api/notices/settings/", HTTP_HOST="testserver")

        self.assertEqual(response.status_code, 404)

    def test_grace_never_sees_st_marys_staff_or_settings(self):
        with connected_to(self.stmarys):
            NoticeSettings.objects.create(pk=1, payment_receipts=True)

        body = self.get(self.their_admin, host=THEIR_HOST).json()

        self.assertEqual(body["payment_receipts"], False)
        names = {row["name"] for row in body["staff"]}
        self.assertEqual(names, {self.their_admin.full_name})


class WritingTests(SettingsApiSetUp):
    def test_an_administrator_turns_on_payment_receipts_and_absence_alerts(self):
        response = self.post(self.admin, {"payment_receipts": True, "absence_alerts": True})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["payment_receipts"])
        self.assertTrue(body["absence_alerts"])
        with connected_to(self.stmarys):
            row = NoticeSettings.objects.get(pk=1)
        self.assertTrue(row.payment_receipts)
        self.assertTrue(row.absence_alerts)

    def test_turning_on_the_summary_picks_nobody_by_itself(self):
        response = self.post(self.admin, {"daily_money_summary": True})

        self.assertEqual(response.json()["money_summary_recipient_ids"], [])
        with connected_to(self.stmarys):
            self.assertEqual(MoneySummaryRecipient.objects.count(), 0)

    def test_picking_a_live_staff_member_is_kept(self):
        response = self.post(
            self.admin,
            {"daily_money_summary": True, "money_summary_recipient_ids": [self.admin.membership_id]},
        )

        self.assertEqual(response.json()["money_summary_recipient_ids"], [self.admin.membership_id])
        with connected_to(self.stmarys):
            self.assertEqual(
                list(MoneySummaryRecipient.objects.values_list("membership_id", flat=True)),
                [self.admin.membership_id],
            )

    def test_picking_somebody_not_on_this_schools_live_staff_is_refused(self):
        response = self.post(
            self.admin,
            {"money_summary_recipient_ids": [self.their_admin.membership_id]},
        )

        self.assertEqual(response.status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(MoneySummaryRecipient.objects.count(), 0)

    def test_a_second_save_replaces_the_picked_list_rather_than_adding_to_it(self):
        self.post(self.admin, {"money_summary_recipient_ids": [self.admin.membership_id]})

        response = self.post(self.admin, {"money_summary_recipient_ids": [self.principal.membership_id]})

        self.assertEqual(response.json()["money_summary_recipient_ids"], [self.principal.membership_id])

    def test_a_bursar_may_not_change_anything(self):
        response = self.post(self.bursar, {"payment_receipts": True})

        self.assertEqual(response.status_code, 403)
        with connected_to(self.stmarys):
            self.assertFalse(NoticeSettings.objects.filter(pk=1, payment_receipts=True).exists())

    def test_the_principal_may_write_too(self):
        response = self.post(self.principal, {"absence_alerts": True})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["absence_alerts"])

    def test_grace_writing_its_own_settings_never_touches_st_marys(self):
        self.post(self.admin, {"payment_receipts": True})

        response = self.post(self.their_admin, {"payment_receipts": False}, host=THEIR_HOST)

        self.assertEqual(response.status_code, 200)
        with connected_to(self.stmarys):
            self.assertTrue(NoticeSettings.objects.get(pk=1).payment_receipts)
