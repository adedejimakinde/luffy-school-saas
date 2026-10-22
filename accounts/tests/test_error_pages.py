"""The pages a person lands on when something is wrong, and the way out of each.

404, 500, 403 and the CSRF refusal were Django's own bare pages (serif, black on
white, no mark, no link), and `app.<domain>/` answered "Not Found" to anybody who
typed the portal's name. They now share `errors/base.html`, and each carries a
link back to `/`, which is the right place on every host.

The suite runs with `DEBUG` off, as a deployment does, so the 404 here is the
page a visitor gets and not Django's technical one.
"""

from django.template.loader import render_to_string
from django.test import Client, override_settings

from accounts.models import User
from accounts.tests.test_login import PASSWORD, PORTAL, SCHOOL_HOST, SignInSetUp
from website.tests.test_homepage import SITE


class ErrorPagesTests(SignInSetUp):
    def test_a_missing_page_is_classnodes_own_on_every_host(self):
        with override_settings(SITE_HOST=SITE):
            for host in (PORTAL, SCHOOL_HOST, SITE):
                with self.subTest(host=host):
                    response = self.client.get("/no-such-page/", HTTP_HOST=host)
                    html = response.content.decode()

                    self.assertEqual(response.status_code, 404)
                    self.assertTrue(html.lstrip().startswith("<!doctype html>"))
                    self.assertIn("We could not find that page", html)
                    self.assertIn('class="brand"', html)
                    self.assertIn('<a class="button" href="/">Go to the home page</a>', html)
                    self.assertNotIn("The requested resource", html)

    def test_an_unknown_school_is_the_same_page(self):
        response = self.client.get("/", HTTP_HOST="nobody-here.testserver")

        self.assertEqual(response.status_code, 404)
        self.assertIn("We could not find that page", response.content.decode())

    def test_the_500_page_needs_nothing_to_render(self):
        """Django renders it with no context, and the database may be what is down."""
        html = render_to_string("500.html")

        self.assertIn("Something went wrong on our side", html)
        self.assertIn('href="/"', html)
        self.assertNotIn("{{", html)

    def test_a_real_server_error_wears_it(self):
        client = Client(raise_request_exception=False)
        with self.settings(
            ROOT_URLCONF="accounts.tests.broken_urls", PUBLIC_SCHEMA_URLCONF="accounts.tests.broken_urls"
        ), self.assertLogs("django.request", "ERROR"):
            response = client.get("/boom/", HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong on our side", response.content.decode())

    def test_the_403_page_has_the_frame_and_a_way_back(self):
        html = render_to_string("403.html", {"detail": "Not for you.", "a_password_fixes_it": False})

        self.assertIn("You cannot open this page", html)
        self.assertIn("Not for you.", html)
        self.assertIn('class="brand"', html)
        self.assertIn('href="/"', html)

    def test_a_forged_form_gets_the_expired_page_and_a_link_to_open_it_again(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post("/admin/login/", {"username": "x", "password": "y"}, HTTP_HOST=PORTAL)
        html = response.content.decode()

        self.assertEqual(response.status_code, 403)
        self.assertIn("This page expired", html)
        self.assertIn('<a class="button" href="/admin/login/">Open the page again</a>', html)
        self.assertIn('href="/"', html)
        self.assertNotIn("CSRF verification failed", html)


class ThePortalRootTests(SignInSetUp):
    def test_the_portal_root_goes_to_the_staff_door(self):
        response = self.client.get("/", HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/staff-sign-in/")


class PlatformStaffLandTests(SignInSetUp):
    """A platform operator has no school; `/platform/` is their home."""

    def test_the_sign_in_answer_says_who_is_platform_staff(self):
        operator = User.objects.create_superuser("ops", PASSWORD, email="ops@classnode.example", full_name="Ops")

        self.assertTrue(self.sign_in(identifier="ops").json()["is_platform_staff"])
        self.client.logout()
        self.assertFalse(self.sign_in().json()["is_platform_staff"])
        self.assertTrue(operator.is_platform_staff)

    def test_the_platform_page_has_a_menu_and_sign_out_for_platform_staff(self):
        User.objects.create_superuser("ops", PASSWORD, email="ops@classnode.example", full_name="Ops")
        self.sign_in(identifier="ops")

        html = self.client.get("/platform/", HTTP_HOST=PORTAL).content.decode()

        for href in ("/platform/", "/platform/handover/", "/admin/"):
            self.assertIn(f'href="{href}"', html)
        self.assertIn('action="/sign-out/"', html)
        self.assertIn("Platform staff", html)
        self.assertNotIn('href="/help/"', html)

    def test_school_staff_get_sign_out_and_no_platform_links(self):
        self.sign_in()  # the teacher

        html = self.client.get("/platform/", HTTP_HOST=PORTAL).content.decode()

        self.assertIn('action="/sign-out/"', html)
        self.assertNotIn('href="/admin/"', html)
        self.assertNotIn('href="/platform/handover/"', html)
