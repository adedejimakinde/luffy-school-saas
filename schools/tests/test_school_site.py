"""A school's public page on its own address, and the setup call that edits it.

Two schools throughout, each saying different things, so a page that read the
wrong school's row (or a setup write that landed on the wrong one) has somewhere
to show. The page is open to anyone; the edit is the principal's and an
administrator's, exactly as the contact email is.
"""

import io
import os

from PIL import Image

from accounts.models import Role, User
from accounts.services import grant_membership
from results import look
from results.tests.fixtures import HOST, PASSWORD, PORTAL, THEIR_HOST, ChainSetUp
from schools.models import School
from schools.tests.tenants import connected_to
from tests.test_budget import BUDGET, STATIC, _ASSET, served_files

PUBLIC = "/api/academics/public-page/"
SETUP = "/api/academics/setup/"
DETAILS = {"about": "Teaching since 1961.", "address": "1 Ring Road, Ibadan", "phone": "0803 555 0100"}


class SiteSetUp(ChainSetUp):
    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )
        School.objects.filter(pk=self.stmarys.pk).update(
            **DETAILS, contact_email="office@stmarys.example"
        )
        School.objects.filter(pk=self.grace.pk).update(
            about="Grace is small.", address="9 Palm Close", phone="0701 000 0001",
            contact_email="hello@grace.example",
        )

    def put(self, user, body, host=HOST):
        self.client.force_login(user.user)
        return self.client.put(PUBLIC, data=body, content_type="application/json", HTTP_HOST=host)

    def page(self, host=HOST):
        self.client.logout()
        return self.client.get("/", HTTP_HOST=host)

    def row(self, school):
        return School.objects.get(pk=school.pk)


class ThePageTests(SiteSetUp):
    def test_each_school_shows_its_own_name_details_and_nobody_elses(self):
        ours, theirs = self.page(HOST).content.decode(), self.page(THEIR_HOST).content.decode()

        self.assertIn("Teaching since 1961.", ours)
        self.assertIn("1 Ring Road, Ibadan", ours)
        self.assertIn("office@stmarys.example", ours)
        self.assertNotIn("Grace", ours)
        self.assertNotIn("9 Palm Close", ours)
        self.assertIn("Grace is small.", theirs)
        self.assertIn("hello@grace.example", theirs)
        self.assertNotIn("Ring Road", theirs)

    def test_it_has_the_two_buttons_and_they_go_to_the_checker_and_the_portal_sign_in(self):
        html = self.page().content.decode()

        self.assertIn('href="/check/"', html)
        self.assertIn("Check a result", html)
        self.assertIn(f'href="//{PORTAL}/sign-in/"', html)
        self.assertIn("Parent sign in", html)

    def test_it_is_open_without_signing_in(self):
        self.assertEqual(self.page().status_code, 200)

    def test_the_schools_colour_and_initials_show_when_it_has_no_crest(self):
        with connected_to(self.stmarys):
            look.set_colour_as(self.head.user, self.stmarys, "#0B6E4F")
        html = self.page().content.decode()

        self.assertIn("--school: #0B6E4F", html)
        self.assertIn("SM", html)  # initials of St Mary's stand in for a crest

    def test_a_blank_field_is_left_off_the_page(self):
        School.objects.filter(pk=self.stmarys.pk).update(about="", address="", phone="", contact_email="")
        html = self.page().content.decode()

        for heading in ("About us", "Find us", "tel:", "mailto:"):
            self.assertNotIn(heading, html)
        self.assertIn("Check a result", html)

    def test_text_the_school_typed_cannot_run_as_markup(self):
        School.objects.filter(pk=self.stmarys.pk).update(
            about='<script>alert(1)</script> & "x"', address="<img src=x onerror=alert(1)>"
        )
        html = self.page().content.decode()

        self.assertNotIn("<script", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)

    def test_it_asks_for_nothing_from_another_host_and_runs_no_script(self):
        html = self.page().content.decode()

        self.assertNotIn("<script", html)
        for url in _ASSET.findall(html):
            self.assertTrue(url.startswith(("/static/", "data:")), url)

    def test_the_portal_has_no_school_page(self):
        self.assertEqual(self.page(PORTAL).status_code, 404)

    def test_with_a_crest_it_stays_far_under_150_kb_even_for_a_crest_of_pure_noise(self):
        noise = Image.frombytes("RGBA", (256, 256), os.urandom(256 * 256 * 4))
        buf = io.BytesIO()
        noise.save(buf, format="PNG")
        with connected_to(self.stmarys):
            look.set_crest_as(self.head.user, self.stmarys, buf.getvalue())

        response = self.page()
        html = response.content.decode()
        served = served_files()
        assets = [served[u] for u in _ASSET.findall(html) if u in served]
        assets += ["web/fonts/hanken-grotesk-400.woff2", "web/fonts/hanken-grotesk-700.woff2"]
        weight = len(response.content) + sum((STATIC / a).stat().st_size for a in set(assets))

        self.assertIn('class="crest" src="data:image/png;base64,', html)
        self.assertLess(weight, BUDGET, f"{weight} bytes")


class EditingThePageTests(SiteSetUp):
    def test_the_principal_and_an_administrator_may_edit_and_the_page_shows_it(self):
        for who in (self.head, self.admin):
            with self.subTest(who=who):
                new = {"about": f"By {who.user.username}.", "address": "2 New Rd", "phone": "+234 803 555 0100"}
                self.assertEqual(self.put(who, new).status_code, 200)
                self.assertIn(new["about"], self.page().content.decode())
                self.client.force_login(who.user)
                self.assertEqual(self.client.get(SETUP, HTTP_HOST=HOST).json()["address"], "2 New Rd")

    def test_it_lands_on_this_school_only(self):
        self.put(self.head, {"about": "Changed", "address": "New", "phone": "1"})

        self.assertEqual(self.row(self.stmarys).about, "Changed")
        self.assertEqual(self.row(self.grace).about, "Grace is small.")
        self.assertEqual(self.row(self.grace).address, "9 Palm Close")

    def test_a_principal_elsewhere_cannot_edit_this_school(self):
        response = self.put(self.their_head, {"about": "Hijack"}, host=HOST)

        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.row(self.stmarys).about, DETAILS["about"])

    def test_others_are_refused_and_nothing_changes(self):
        for who in (self.teacher, self.vp):
            with self.subTest(who=who):
                self.assertEqual(self.put(who, {"about": "no"}).status_code, 403)
        self.assertEqual(self.row(self.stmarys).about, DETAILS["about"])

    def test_blank_clears_a_field(self):
        self.put(self.head, {"about": "", "address": "", "phone": ""})

        self.assertEqual((self.row(self.stmarys).about, self.row(self.stmarys).phone), ("", ""))

    def test_too_long_or_a_bad_phone_is_refused_with_a_sentence_and_nothing_changes(self):
        for body in (
            {"about": "x" * 601, "address": "", "phone": ""},
            {"about": "", "address": "y" * 301, "phone": ""},
            {"about": "", "address": "", "phone": "call me maybe"},
        ):
            with self.subTest(body=list(body.values())):
                response = self.put(self.head, body)
                self.assertEqual(response.status_code, 422)
                self.assertTrue(response.json()["detail"])
        self.assertEqual(self.row(self.stmarys).about, DETAILS["about"])
