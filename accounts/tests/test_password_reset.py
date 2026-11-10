"""Forgot password, end to end: ask on a host, open the emailed link, choose a new one.

`docs/sign-in-page.md`, "Forgot password", and `accounts/password_reset.py`.
Every request here goes through the two real pages with CSRF enforced, the
email goes through the fake provider as a worker would send it, and the link
used is the one read out of that email.

Two schools throughout, with real schemas, and the portal: Sunrise and Harbour,
a teacher at each, and one who teaches at both. "Only on the host it was asked
for from" and "only this school's members" need a second school to be claims at
all, and the teacher at both is who a careless version lets through, because
both hosts would admit her.

Each rule the pull request names was broken by hand and seen to fail here (the
pull request lists the controls); the docstrings name what turns red.
"""

import hashlib
import re
from datetime import timedelta
from unittest import mock
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts import password_reset, throttling
from accounts.deletion import deactivate_user
from accounts.models import (
    PasswordReset,
    PasswordResetLog,
    PasswordResetLogIsKept,
    Role,
    SignInScope,
    User,
)
from accounts.password_reset import Result, send_password_changed, send_reset_link
from accounts.services import grant_membership
from messaging.models import FakeMessage
from messaging.tests.fake import SendsThroughTheFake
from schools.models import Domain
from schools.paths import NEVER_INDEXED, first_segment, is_door
from schools.tests.tenants import make_school as make_school_with_schema
from schools.tests.test_brand import HARBOUR_COLOUR, SUNRISE_COLOUR, give_crest, set_colour
from schools.tests.test_invitations import make_school

PORTAL = "testserver"
SUNRISE = "sunrise.testserver"
HARBOUR = "harbour.testserver"
OLD = "the-old-password-1"
NEW = "a-brand-new-password-2"

SCHOOL_COOKIE = settings.SCHOOL_SESSION_COOKIE_NAME

_CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
_LINK = re.compile(r"(https?://\S+/reset-password/[^/\s]+/)")
_HREF = re.compile(r'(?:href|action|src)="([^"]*)"')


class ResetSetUp(SendsThroughTheFake, TestCase):
    def setUp(self):
        super().setUp()
        portal = make_school("Portal", "portal", "public")
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)
        self.sunrise = make_school_with_schema("Sunrise Academy", "sunrise", "sunrise")
        Domain.objects.create(tenant=self.sunrise, domain=SUNRISE, is_primary=True)
        self.harbour = make_school_with_schema("Harbour College", "harbour", "harbour")
        Domain.objects.create(tenant=self.harbour, domain=HARBOUR, is_primary=True)

        self.ada = self.person("ada", "Ada Sunrise", "ada@sunrise.test", "08031110001")
        grant_membership(self.ada, self.sunrise, Role.TEACHER)
        self.tunde = self.person("tunde", "Tunde Harbour", "tunde@harbour.test", "08031110002")
        grant_membership(self.tunde, self.harbour, Role.TEACHER)
        # Teaches at both: whom both hosts admit, so only the link's own host
        # can be what refuses her link on the other one.
        self.folake = self.person("folake", "Folake Both", "folake@both.test", "08031110003")
        grant_membership(self.folake, self.sunrise, Role.TEACHER)
        grant_membership(self.folake, self.harbour, Role.TEACHER)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def person(self, username, name, email=None, phone=None, password=OLD):
        return User.objects.create_user(username, password, full_name=name, email=email, phone=phone)

    # -- the two pages, as a browser uses them ---------------------------------

    def ask(self, host, identifier, client=None, **extra):
        """Ask for a link on `host`, and send what was queued, as a worker would."""
        client = client or Client(enforce_csrf_checks=True)
        page = client.get("/forgot-password/", HTTP_HOST=host, **extra)
        token = _CSRF.search(page.content.decode()).group(1)
        with mock.patch("accounts.password_reset.send_reset_link.apply_async") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                response = client.post(
                    "/forgot-password/",
                    {"identifier": identifier, "csrfmiddlewaretoken": token},
                    HTTP_HOST=host,
                    **extra,
                )
        connection.set_schema_to_public()
        self.jobs = [call.kwargs["args"] for call in publish.call_args_list]
        for args in self.jobs:
            send_reset_link(*args)
        return response

    def links_to(self, email):
        """Every reset link the fake was handed for `email`, oldest first."""
        sent = FakeMessage.objects.filter(address=email, kind="password_reset").order_by("created_at", "id")
        return [_LINK.search(message.text).group(1) for message in sent]

    def link_for(self, host, user):
        """Ask on `host` for `user`'s link, and read it out of the email."""
        before = len(self.links_to(user.email))
        self.ask(host, user.email)
        links = self.links_to(user.email)
        self.assertEqual(len(links), before + 1, f"no link was emailed to {user.email}")
        return links[-1]

    def open(self, link, host=None, client=None):
        """GET the link's page, on the link's own host or on `host`."""
        parts = urlsplit(link)
        response = (client or Client()).get(parts.path, HTTP_HOST=host or parts.netloc)
        connection.set_schema_to_public()
        return response

    def choose(self, link, password=NEW, again=None, host=None, client=None):
        """Open the link and submit a new password; send what was queued."""
        parts = urlsplit(link)
        host = host or parts.netloc
        client = client or Client(enforce_csrf_checks=True)
        page = client.get(parts.path, HTTP_HOST=host)
        found = _CSRF.search(page.content.decode())
        data = {"password": password, "password_again": password if again is None else again}
        if found:
            data["csrfmiddlewaretoken"] = found.group(1)
        else:
            # A dead link draws no form. A request forged past that is still
            # refused by the link, not only by having no form to send.
            client = Client()
        with mock.patch("accounts.password_reset.send_password_changed.apply_async") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                response = client.post(parts.path, data, HTTP_HOST=host)
        connection.set_schema_to_public()
        for call in publish.call_args_list:
            send_password_changed(*call.kwargs["args"])
        return response

    def door(self, host, identifier, password, client=None):
        """A real sign-in at `host`'s staff door, CSRF enforced."""
        client = client or Client(enforce_csrf_checks=True)
        token = client.get("/api/csrf/", HTTP_HOST=host).json()["csrf_token"]
        response = client.post(
            "/api/login/",
            data={"identifier": identifier, "password": password},
            content_type="application/json",
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=token,
        )
        connection.set_schema_to_public()
        return client, response

    def signed_in(self, client, host):
        """Whether `client` is anybody on `host`: a route every member is answered by."""
        response = client.get("/api/results/cards/", HTTP_HOST=host)
        connection.set_schema_to_public()
        return response.status_code == 200

    def results(self):
        return list(PasswordResetLog.objects.order_by("at", "id").values_list("event", "result"))


class OneAnswerWhateverWasTypedTests(ResetSetUp):
    def test_the_page_is_the_same_bytes_and_status_whoever_or_nobody_it_was_for(self):
        """An account that is emailed, nobody, a member of the other school, a
        deactivated one and one with only a phone number: one status, one page.
        Red if any outcome draws a word of its own."""
        phone_only = self.person("bola", "Bola Phone", phone="08031110009")
        grant_membership(phone_only, self.sunrise, Role.TEACHER)
        gone = self.person("gone", "Gone Away", "gone@sunrise.test")
        grant_membership(gone, self.sunrise, Role.TEACHER)
        deactivate_user(gone)

        for host in (SUNRISE, PORTAL):
            typed = {
                "emailed": "ada@sunrise.test",
                "by phone": "0803 111 0001",
                "nobody": "nobody@nowhere.test",
                "not a number or an address": "let me in",
                "another school's": "tunde@harbour.test",
                "deactivated": "gone@sunrise.test",
                "phone only": "08031110009",
            }
            answers = {what: self.ask(host, value) for what, value in typed.items()}
            first = answers["emailed"]
            self.assertEqual(first.status_code, 200)
            self.assertIn("If an account matches, we&#x27;ve sent a link", first.content.decode())
            for what, response in answers.items():
                with self.subTest(host=host, typed=what):
                    self.assertEqual(response.status_code, first.status_code)
                    self.assertEqual(response.content, first.content)
        # The control: the outcomes really did differ, and only the log says so.
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 4)
        self.assertEqual(self.links_to("gone@sunrise.test"), [])
        self.assertIn(("requested", Result.NO_ACCOUNT), self.results())
        self.assertIn(("requested", Result.NO_EMAIL), self.results())

    def test_nothing_typed_is_shown_back_and_nothing_names_the_account(self):
        html = self.ask(SUNRISE, "ada@sunrise.test").content.decode()
        self.assertNotIn("ada@sunrise.test", html)
        self.assertNotIn("Ada", html)

    def test_an_empty_box_is_the_one_thing_said_and_sends_nothing(self):
        response = self.ask(SUNRISE, "   ")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Type the email address or phone number", response.content.decode())
        self.assertNotIn("sent a link", response.content.decode())
        self.assertEqual(self.results(), [])

    def test_nonsense_typed_into_the_box_is_answered_like_anything_else(self):
        """A NUL byte, and far more than an address is long: the one page, never a 500."""
        first = self.ask(SUNRISE, "nobody@nowhere.test")
        for typed in ("ada\x00@sunrise.test", "x" * 5000, "'; DROP TABLE accounts_user; --"):
            with self.subTest(typed=typed[:20]):
                response = self.ask(SUNRISE, typed)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, first.content)

    def test_a_request_without_a_csrf_token_is_refused(self):
        response = Client(enforce_csrf_checks=True).post(
            "/forgot-password/", {"identifier": "ada@sunrise.test"}, HTTP_HOST=SUNRISE
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PasswordReset.objects.exists())


class TheLinkTests(ResetSetUp):
    def test_the_email_carries_a_link_on_the_host_it_was_asked_for_from(self):
        link = self.link_for(SUNRISE, self.ada)
        self.assertTrue(link.startswith(f"http://{SUNRISE}/reset-password/"), link)
        message = FakeMessage.objects.get(address="ada@sunrise.test", kind="password_reset")
        self.assertEqual(message.subject, "Reset your password")
        self.assertIn("Sunrise Academy", message.text)
        self.assertIn("30 minutes", message.text)
        self.assertNotIn("Harbour", message.text)
        self.assertNotIn(PORTAL + "/", message.text.replace(SUNRISE, ""))

        portal_link = self.link_for(PORTAL, self.tunde)
        self.assertTrue(portal_link.startswith(f"http://{PORTAL}/reset-password/"), portal_link)
        self.assertIn("your Classnode account", FakeMessage.objects.get(address="tunde@harbour.test").text)

    def test_only_a_hash_of_the_token_is_kept_and_the_queue_never_holds_it(self):
        link = self.link_for(SUNRISE, self.ada)
        raw = urlsplit(link).path.split("/")[2]
        self.assertGreaterEqual(len(raw), 40)

        (row,) = PasswordReset.objects.all()
        self.assertEqual(row.token_hash, hashlib.sha256(raw.encode()).hexdigest())
        self.assertNotIn(raw, repr(PasswordReset.objects.values().get()))
        self.assertNotIn(raw, repr(list(PasswordResetLog.objects.values())))
        # What crossed the broker was sealed (`messaging.seal`).
        (job,) = self.jobs
        self.assertNotIn(raw, repr(job))

    def test_it_works_once(self):
        """Red if `complete()` stops spending the link."""
        link = self.link_for(SUNRISE, self.ada)
        self.assertEqual(self.open(link).status_code, 200)

        done = self.choose(link)
        self.assertEqual(done.status_code, 302)
        self.assertEqual(self.open(link).status_code, 404)

        again = self.choose(link, password="a-third-password-3")
        self.assertEqual(again.status_code, 404)
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.check_password(NEW))

    def test_it_lasts_thirty_minutes_and_not_a_second_more(self):
        link = self.link_for(SUNRISE, self.ada)
        (row,) = PasswordReset.objects.all()
        self.assertEqual(row.expires_at - row.created_at, timedelta(minutes=30))

        with mock.patch("django.utils.timezone.now", return_value=row.created_at + timedelta(minutes=29, seconds=59)):
            self.assertEqual(self.open(link).status_code, 200)
        with mock.patch("django.utils.timezone.now", return_value=row.created_at + timedelta(minutes=30)):
            self.assertEqual(self.open(link).status_code, 404)
            self.assertEqual(self.choose(link).status_code, 404)
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.check_password(OLD))

    def test_a_newer_request_ends_the_one_before_it(self):
        """Red if minting stops superseding: both links would open."""
        first = self.link_for(SUNRISE, self.ada)
        second = self.link_for(SUNRISE, self.ada)
        self.assertNotEqual(first, second)

        self.assertEqual(self.open(first).status_code, 404)
        self.assertEqual(self.choose(first).status_code, 404)
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.check_password(OLD))
        self.assertEqual(self.choose(second).status_code, 302)

    def test_a_newer_request_on_another_host_ends_it_too(self):
        first = self.link_for(SUNRISE, self.folake)
        self.link_for(HARBOUR, self.folake)
        self.assertEqual(self.open(first).status_code, 404)

    def test_every_dead_link_is_the_same_page(self):
        """Unknown, used, replaced and expired are one status and one body: a
        guessed token learns nothing about a real one."""
        used = self.link_for(SUNRISE, self.ada)
        self.choose(used)
        replaced = self.link_for(SUNRISE, self.folake)
        self.link_for(SUNRISE, self.folake)
        never = f"http://{SUNRISE}/reset-password/never-a-token-anybody-made/"

        pages = [self.open(link) for link in (never, used, replaced)]
        for page in pages:
            self.assertEqual(page.status_code, 404)
            self.assertEqual(page.content, pages[0].content)
        self.assertIn("This link no longer works.", pages[0].content.decode())
        self.assertNotIn("csrfmiddlewaretoken", pages[0].content.decode())

    def test_a_weak_password_is_refused_and_leaves_the_link_unspent(self):
        """The existing rule (`AUTH_PASSWORD_VALIDATORS`): ten characters."""
        link = self.link_for(SUNRISE, self.ada)

        short = self.choose(link, password="too-short")
        self.assertEqual(short.status_code, 200)
        self.assertIn("at least 10 characters", short.content.decode())
        unlike = self.choose(link, password=NEW, again=NEW + "x")
        self.assertEqual(unlike.status_code, 200)
        self.assertIn("not the same", unlike.content.decode())
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.check_password(OLD))

        self.assertEqual(self.choose(link).status_code, 302)

    def test_the_link_page_is_never_cached_and_its_address_goes_to_no_other_origin(self):
        link = self.link_for(SUNRISE, self.ada)
        for response in (self.open(link), self.open(link.replace("/reset-password/", "/reset-password/x"))):
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(self.ask(SUNRISE, "ada@sunrise.test")["Cache-Control"], "no-store")

    def test_a_browser_can_post_the_form_the_link_page_draws(self):
        """`no-referrer` on this page would make a browser send `Origin: null`
        with the form, and Django's CSRF check refuses a null origin: the page
        would open and nobody could use it. A browser's own `Origin` is let in,
        a null one is not, and the page asks for neither."""
        link = self.link_for(SUNRISE, self.ada)
        parts = urlsplit(link)
        page = self.open(link)
        self.assertNotIn("no-referrer", page.content.decode())
        self.assertNotEqual(page["Referrer-Policy"], "no-referrer")

        def post(origin):
            client = Client(enforce_csrf_checks=True)
            token = _CSRF.search(client.get(parts.path, HTTP_HOST=SUNRISE).content.decode()).group(1)
            response = client.post(
                parts.path,
                {"password": NEW, "password_again": NEW, "csrfmiddlewaretoken": token},
                HTTP_HOST=SUNRISE,
                HTTP_ORIGIN=origin,
            )
            connection.set_schema_to_public()
            return response

        self.assertEqual(post("null").status_code, 403)
        self.assertEqual(post(f"http://{SUNRISE}").status_code, 302)


class OnlyOnTheHostItWasAskedForFromTests(ResetSetUp):
    """Two schools and the portal. Folake teaches at both, so nothing but the
    link's own host refuses her link on the other one."""

    def test_a_link_asked_for_on_one_schools_host_is_dead_on_the_others_and_on_the_portal(self):
        """Red if `holder()` stops comparing the link's school with the host's."""
        link = self.link_for(SUNRISE, self.folake)
        never = "/reset-password/never-a-token-anybody-made/"

        for host in (HARBOUR, PORTAL):
            with self.subTest(host=host):
                page = self.open(link, host=host)
                self.assertEqual(page.status_code, 404)
                # Exactly what that host says to a token nobody made.
                self.assertEqual(page.content, Client().get(never, HTTP_HOST=host).content)
                connection.set_schema_to_public()
                self.assertEqual(self.choose(link, host=host).status_code, 404)
        self.folake.refresh_from_db()
        self.assertTrue(self.folake.check_password(OLD))

        # The control: it was a good link all along, on its own host.
        self.assertEqual(self.choose(link).status_code, 302)
        self.folake.refresh_from_db()
        self.assertTrue(self.folake.check_password(NEW))

    def test_a_link_asked_for_on_the_portal_is_dead_on_a_schools_host(self):
        link = self.link_for(PORTAL, self.folake)
        for host in (SUNRISE, HARBOUR):
            with self.subTest(host=host):
                self.assertEqual(self.open(link, host=host).status_code, 404)
                self.assertEqual(self.choose(link, host=host).status_code, 404)
        self.assertEqual(self.choose(link).status_code, 302)

    def test_a_member_of_one_school_cannot_reset_through_the_others_host(self):
        """Tunde is Harbour's. On Sunrise's host he is sent nothing, and nothing
        is made; on Harbour's he is sent Harbour's link. Red if the membership
        rule goes from `_may_be_reset_here()`."""
        self.ask(SUNRISE, "tunde@harbour.test")
        self.ask(SUNRISE, "0803 111 0002")
        self.assertEqual(self.links_to("tunde@harbour.test"), [])
        self.assertFalse(PasswordReset.objects.exists())
        self.assertEqual(
            self.results(), [("requested", Result.NOT_A_MEMBER), ("requested", Result.NOT_A_MEMBER)]
        )

        link = self.link_for(HARBOUR, self.tunde)
        self.assertTrue(link.startswith(f"http://{HARBOUR}/"))
        self.assertEqual(self.choose(link).status_code, 302)
        self.assertNotIn("Sunrise", FakeMessage.objects.filter(address="tunde@harbour.test").first().text)

    def test_a_link_dies_when_its_holder_leaves_the_school_it_was_asked_at(self):
        link = self.link_for(SUNRISE, self.ada)
        membership = self.ada.memberships.get(school=self.sunrise)
        membership.end()

        self.assertEqual(self.open(link).status_code, 404)
        self.assertEqual(self.choose(link).status_code, 404)

    def test_an_invited_or_suspended_member_is_sent_nothing(self):
        from accounts.models import MembershipStatus

        for status in (MembershipStatus.INVITED, MembershipStatus.SUSPENDED):
            person = self.person(f"p-{status}", "Not Yet", f"{status}@sunrise.test")
            grant_membership(person, self.sunrise, Role.TEACHER, status=status)
            self.ask(SUNRISE, person.email)
            self.assertEqual(self.links_to(person.email), [])


class WhoIsSentOneTests(ResetSetUp):
    def test_a_deactivated_account_is_sent_nothing_on_any_host(self):
        deactivate_user(self.ada)
        for host in (SUNRISE, PORTAL):
            self.ask(host, "ada@sunrise.test")
        self.assertEqual(self.links_to("ada@sunrise.test"), [])
        self.assertFalse(PasswordReset.objects.exists())
        self.assertEqual(self.results(), [("requested", Result.DEACTIVATED)] * 2)

    def test_a_link_asked_for_before_deactivation_is_dead_after_it(self):
        link = self.link_for(SUNRISE, self.ada)
        deactivate_user(self.ada)

        self.assertEqual(self.open(link).status_code, 404)
        self.assertEqual(self.choose(link).status_code, 404)
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.check_password(OLD))

    def test_an_account_with_only_a_phone_number_is_sent_nothing(self):
        """The link goes by email and there is no SMS version yet."""
        bola = self.person("bola", "Bola Phone", phone="08031110009")
        grant_membership(bola, self.sunrise, Role.TEACHER)

        self.ask(SUNRISE, "08031110009")
        self.assertFalse(FakeMessage.objects.exists())
        self.assertFalse(PasswordReset.objects.exists())
        self.assertEqual(self.results(), [("requested", Result.NO_EMAIL)])

    def test_a_phone_number_finds_the_account_and_the_link_goes_to_its_email(self):
        self.ask(SUNRISE, "0803 111 0001")
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 1)
        self.assertFalse(FakeMessage.objects.filter(channel_type="phone").exists())

    def test_a_parent_is_sent_one_like_anybody_else(self):
        parent = User.objects.create_user("mama", None, full_name="Mama Obi", email="mama@obi.test")
        grant_membership(parent, self.sunrise, Role.PARENT)

        link = self.link_for(SUNRISE, parent)
        self.assertEqual(self.choose(link).status_code, 302)
        _, response = self.door(SUNRISE, "mama@obi.test", NEW)
        self.assertEqual(response.status_code, 200)

    def test_platform_staff_and_blog_accounts_are_never_reset_by_email(self):
        operator = User.objects.create_superuser("root", OLD, full_name="Operator", email="root@classnode.test")
        writer = User.objects.create_user(
            "writer@classnode.test", None, full_name="Writer", email="writer@classnode.test", blog_role="writer"
        )
        for host in (PORTAL, SUNRISE):
            self.ask(host, operator.email)
            self.ask(host, writer.email)
        self.assertFalse(FakeMessage.objects.exists())
        self.assertFalse(PasswordReset.objects.exists())

    def test_a_school_that_sends_nothing_sends_no_link(self):
        """Classnode's demo school (`schools.quiet`): on its own host, and on the
        portal for somebody who belongs nowhere else."""
        demo = make_school_with_schema("Crestfield", "crestfield", "crestfield")
        Domain.objects.create(tenant=demo, domain="crestfield.testserver", is_primary=True)
        demo.sales_demo = True
        demo.save(update_fields=["sales_demo"])
        made_up = self.person("demo-teacher", "Made Up", "made.up@demo.test")
        grant_membership(made_up, demo, Role.TEACHER)

        self.ask("crestfield.testserver", "made.up@demo.test")
        self.ask(PORTAL, "made.up@demo.test")
        self.assertFalse(FakeMessage.objects.exists())
        self.assertFalse(PasswordReset.objects.exists())
        self.assertEqual(self.results(), [("requested", Result.SWITCHED_OFF)] * 2)

    def test_somebody_signed_in_at_another_school_still_reaches_both_pages_here(self):
        """A door: no membership here is needed to open it (`schools.paths.DOORS`)."""
        client, response = self.door(PORTAL, "tunde", OLD)
        self.assertEqual(response.status_code, 200)

        self.assertTrue(is_door("/forgot-password/"))
        self.assertTrue(is_door("/reset-password/anything/"))
        self.assertEqual(client.get("/forgot-password/", HTTP_HOST=SUNRISE).status_code, 200)
        self.assertEqual(client.get("/reset-password/anything/", HTTP_HOST=SUNRISE).status_code, 404)
        self.assertIn("This link no longer works.", client.get("/reset-password/anything/", HTTP_HOST=SUNRISE).content.decode())


class AResetSignsEverySessionOutTests(ResetSetUp):
    def test_every_session_the_person_had_ends_and_they_are_told_by_email(self):
        """One session from the school's own door, one from the portal's, both
        good on Sunrise's host; both gone after the reset. Red if the password
        is changed in a way that leaves the session hash alone."""
        at_school, response = self.door(SUNRISE, "ada", OLD)
        self.assertEqual(response.status_code, 200)
        self.assertIn(SCHOOL_COOKIE, at_school.cookies)
        at_portal, response = self.door(PORTAL, "ada", OLD)
        self.assertEqual(response.status_code, 200)
        # Somebody else, who must be left alone.
        other, _ = self.door(SUNRISE, "folake", OLD)
        for client in (at_school, at_portal, other):
            self.assertTrue(self.signed_in(client, SUNRISE))

        done = self.choose(self.link_for(SUNRISE, self.ada))

        self.assertEqual(done.status_code, 302)
        self.assertFalse(self.signed_in(at_school, SUNRISE))
        self.assertFalse(self.signed_in(at_portal, SUNRISE))
        self.assertTrue(self.signed_in(other, SUNRISE))

        (told,) = FakeMessage.objects.filter(kind="password_changed")
        self.assertEqual(told.address, "ada@sunrise.test")
        self.assertEqual(told.subject, "Your password was changed")
        self.assertIn("Sunrise Academy", told.text)
        self.assertIn(f"{SUNRISE}/forgot-password/", told.text)
        self.assertNotIn(NEW, told.text)

    def test_a_session_opened_with_a_parents_code_ends_too(self):
        """A code session carries the same hash of the account's password as any other."""
        from accounts.services import enroll_student, link_guardian
        from tests.guardians import give_verified_channel

        child = enroll_student(self.person("child", "Sunny Child", password=None), self.sunrise, reference="S1")
        mama = User.objects.create_user("mama", None, full_name="Mama Sunrise", email="mama@obi.test")
        link_guardian(mama, child)
        give_verified_channel(mama, "08039990001")
        handset = Client()
        self.deliver(lambda: handset.post(
            "/api/guardian/code/", {"value": "08039990001"}, content_type="application/json", HTTP_HOST=SUNRISE,
        ))
        answered = handset.post(
            "/api/guardian/session/", {"value": "08039990001", "code": self.code_sent_to("+2348039990001")},
            content_type="application/json", HTTP_HOST=SUNRISE,
        )
        connection.set_schema_to_public()
        self.assertEqual(answered.status_code, 200, answered.content)
        self.assertTrue(self.signed_in(handset, SUNRISE))

        self.choose(self.link_for(SUNRISE, mama))
        self.assertFalse(self.signed_in(handset, SUNRISE))

    def test_they_land_on_the_password_door_of_the_same_host_and_the_new_password_opens_it(self):
        for host, user in ((SUNRISE, self.ada), (HARBOUR, self.tunde), (PORTAL, self.folake)):
            with self.subTest(host=host):
                done = self.choose(self.link_for(host, user))
                self.assertEqual(done.status_code, 302)
                # A path: wherever it is followed, it is followed on this host.
                self.assertEqual(done["Location"], "/staff-sign-in/")
                self.assertEqual(self.door(host, user.username, OLD)[1].status_code, 401)
                self.assertEqual(self.door(host, user.username, NEW)[1].status_code, 200)

    def test_wrong_passwords_typed_before_the_reset_do_not_hold_the_new_one_out(self):
        with override_settings(SIGN_IN_MAX_FAILURES_PER_IDENTIFIER=2):
            for _ in range(2):
                self.door(SUNRISE, "ada@sunrise.test", "a-wrong-password")
            self.assertEqual(self.door(SUNRISE, "ada@sunrise.test", OLD)[1].status_code, 429)

            self.choose(self.link_for(SUNRISE, self.ada))
            self.assertEqual(self.door(SUNRISE, "ada@sunrise.test", NEW)[1].status_code, 200)

    def test_the_confirmation_is_sent_once_however_often_the_job_runs(self):
        link = self.link_for(SUNRISE, self.ada)
        self.choose(link)
        (row,) = PasswordReset.objects.all()
        send_password_changed(row.pk, SUNRISE)
        send_reset_link(*self.jobs[0])
        self.assertEqual(FakeMessage.objects.filter(kind="password_changed").count(), 1)
        self.assertEqual(FakeMessage.objects.filter(kind="password_reset").count(), 1)


class ThrottledTests(ResetSetUp):
    def test_five_an_hour_for_one_account_however_it_is_named(self):
        """Its email and its phone number are one bucket. The sixth request is
        answered with the same page and sends nothing. Red if the account's
        requests stop being counted."""
        answers = [
            self.ask(SUNRISE, typed)
            for typed in ("ada@sunrise.test", "0803 111 0001", "ADA@sunrise.test", "+2348031110001", "ada")
        ]
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 5)

        sixth = self.ask(SUNRISE, "ada@sunrise.test")
        seventh = self.ask(PORTAL, "08031110001", REMOTE_ADDR="10.9.9.9")
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 5)
        self.assertEqual(sixth.status_code, answers[0].status_code)
        self.assertEqual(sixth.content, answers[0].content)
        self.assertEqual(seventh.status_code, 200)
        self.assertEqual(self.results()[-2:], [("requested", Result.THROTTLED)] * 2)

        # Somebody else, from the same address, is not held up by it.
        self.ask(SUNRISE, "folake@both.test")
        self.assertEqual(len(self.links_to("folake@both.test")), 1)

    def test_the_window_is_an_hour(self):
        for _ in range(5):
            self.ask(SUNRISE, "ada@sunrise.test")
        self.ask(SUNRISE, "ada@sunrise.test")
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 5)

        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(minutes=59)):
            self.ask(SUNRISE, "ada@sunrise.test")
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 5)
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(minutes=61)):
            self.ask(SUNRISE, "ada@sunrise.test")
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 6)

    @override_settings(PASSWORD_RESET_MAX_PER_ADDRESS=3)
    def test_one_address_is_counted_across_every_account_real_or_not(self):
        """Red if the address's requests stop being counted."""
        room = {"REMOTE_ADDR": "10.1.2.3"}
        for typed in ("nobody-1@x.test", "nobody-2@x.test", "tunde@harbour.test"):
            self.ask(PORTAL, typed, **room)
        self.assertEqual(len(self.links_to("tunde@harbour.test")), 1)

        held = self.ask(PORTAL, "ada@sunrise.test", **room)
        self.assertEqual(self.links_to("ada@sunrise.test"), [])
        self.assertIn("If an account matches", held.content.decode())
        self.assertEqual(self.results()[-1], ("requested", Result.THROTTLED))

        # Another address is another bucket.
        self.ask(PORTAL, "ada@sunrise.test", REMOTE_ADDR="10.1.2.4")
        self.assertEqual(len(self.links_to("ada@sunrise.test")), 1)

    def test_asking_for_links_never_closes_anybodys_sign_in_door(self):
        """Buckets of their own (`SignInScope.RESET_*`)."""
        for _ in range(7):
            self.ask(SUNRISE, "ada@sunrise.test")
        self.assertIsNone(throttling.blocked_for(SignInScope.IDENTIFIER, "ada@sunrise.test"))
        self.assertIsNone(throttling.blocked_for(SignInScope.ADDRESS, "127.0.0.1"))
        self.assertEqual(self.door(SUNRISE, "ada@sunrise.test", OLD)[1].status_code, 200)

    def test_the_defaults_are_five_and_twenty_an_hour_and_a_half_hour_link(self):
        self.assertEqual(settings.PASSWORD_RESET_MAX_PER_ACCOUNT, 5)
        self.assertEqual(settings.PASSWORD_RESET_MAX_PER_ADDRESS, 20)
        self.assertEqual(settings.PASSWORD_RESET_THROTTLE_WINDOW, 60 * 60)
        self.assertEqual(settings.PASSWORD_RESET_TTL, 30 * 60)


class EveryRequestAndResetIsWrittenDownTests(ResetSetUp):
    def test_each_request_and_the_reset_are_logged_with_where_they_came_from(self):
        self.ask(SUNRISE, "nobody@nowhere.test", REMOTE_ADDR="10.0.0.7")
        link = self.link_for(SUNRISE, self.ada)
        with self.assertLogs("accounts.password_reset", level="INFO") as logged:
            self.choose(link)

        rows = list(PasswordResetLog.objects.order_by("at", "id"))
        self.assertEqual(
            [(r.event, r.result) for r in rows],
            [("requested", "no_account"), ("requested", "sent"), ("completed", "changed")],
        )
        nobody, asked, changed = rows
        self.assertEqual(nobody.address, "10.0.0.7")
        self.assertIsNone(nobody.account_id)
        self.assertEqual(nobody.host_school_id, self.sunrise.pk)
        # What was typed is kept as a digest, never as typed.
        self.assertEqual(len(nobody.identifier_digest), 64)
        self.assertNotIn("nobody@nowhere.test", repr(PasswordResetLog.objects.values().first()))
        self.assertEqual((asked.account_id, changed.account_id), (self.ada.pk, self.ada.pk))
        self.assertEqual(asked.reset_id, changed.reset_id)
        self.assertEqual(changed.address, "127.0.0.1")
        self.assertTrue(any("completed: changed" in line for line in logged.output))

    def test_a_request_on_the_portal_is_logged_with_no_school(self):
        self.ask(PORTAL, "ada@sunrise.test")
        self.assertIsNone(PasswordResetLog.objects.get().host_school_id)

    def test_the_log_is_append_only(self):
        self.ask(SUNRISE, "ada@sunrise.test")
        row = PasswordResetLog.objects.get()
        row.result = "something-else"
        with self.assertRaises(PasswordResetLogIsKept):
            row.save()
        with self.assertRaises(PasswordResetLogIsKept):
            row.delete()

    def test_the_worker_knows_both_jobs_by_name(self):
        import celery_app
        from accounts import tasks

        for task in (tasks.send_reset_link, tasks.send_password_changed):
            self.assertIn(task.name, celery_app.app.tasks)


class ThePagesWearTheSchoolAndStayOnItsHostTests(ResetSetUp):
    def setUp(self):
        super().setUp()
        self.crest = give_crest(self.sunrise)
        set_colour(self.sunrise, SUNRISE_COLOUR)
        set_colour(self.harbour, HARBOUR_COLOUR)

    def pages(self, host, user):
        """Every state of both pages on `host`, as HTML: ask, sent, choose, dead."""
        link = self.link_for(host, user)
        ask = Client().get("/forgot-password/", HTTP_HOST=host)
        sent = self.ask(host, "nobody@nowhere.test")
        choose = self.open(link)
        dead = Client().get("/reset-password/never-a-token/", HTTP_HOST=host)
        connection.set_schema_to_public()
        self.assertEqual([r.status_code for r in (ask, sent, choose, dead)], [200, 200, 200, 404])
        return {name: r.content.decode() for name, r in (("ask", ask), ("sent", sent), ("choose", choose), ("dead", dead))}

    def test_on_a_schools_host_every_state_shows_its_crest_name_and_colour(self):
        crest = f"/media/{self.crest}/site.png"
        sunrise = self.pages(SUNRISE, self.ada)
        harbour = self.pages(HARBOUR, self.tunde)
        for state in ("ask", "sent", "choose", "dead"):
            with self.subTest(state=state):
                html = sunrise[state]
                self.assertIn('class="door-name">Sunrise Academy<', html)
                self.assertIn(f'<img src="{crest}"', html)
                self.assertIn(f"--brand:{SUNRISE_COLOUR}", html)
                self.assertIn("Powered by Classnode", html)
                self.assertNotIn('class="logo-mark"', html)
                self.assertNotIn("Harbour College", html)

                # No crest: the initials. A colour under 4.5:1: the navy.
                html = harbour[state]
                self.assertIn('class="door-name">Harbour College<', html)
                self.assertIn('<span class="crest" aria-hidden="true">HC</span>', html)
                self.assertNotIn("--brand:", html)
                self.assertIn("Powered by Classnode", html)
                self.assertNotIn("Sunrise Academy", html)
                self.assertNotIn(self.crest, html)

    def test_on_the_portal_they_are_classnodes(self):
        for state, html in self.pages(PORTAL, self.ada).items():
            with self.subTest(state=state):
                self.assertIn('class="logo-mark"', html)
                self.assertNotIn("Powered by Classnode", html)
                self.assertNotIn("Sunrise Academy", html)
                self.assertNotIn("Harbour College", html)

    def test_every_link_and_form_on_them_is_a_path_on_this_host(self):
        """Nothing on a school's pages names the portal or another school: the
        one address with a host in it is "Powered by Classnode", to the public site."""
        from schools.brand import classnode_href

        for host, user in ((SUNRISE, self.ada), (HARBOUR, self.tunde), (PORTAL, self.folake)):
            for state, html in self.pages(host, user).items():
                with self.subTest(host=host, state=state):
                    # `#i-alert` and the like are this document's own icons.
                    targets = [t for t in _HREF.findall(html) if t != classnode_href() and not t.startswith("#")]
                    self.assertTrue(targets)
                    for target in targets:
                        self.assertRegex(target, r"^/(?!/)", f"{target} leaves the host")
                    for other in {PORTAL, SUNRISE, HARBOUR} - {host}:
                        self.assertNotIn(f"//{other}", html)
                    self.assertNotIn("app.", html)

    def test_the_way_back_is_the_door_the_reader_came_from(self):
        staff = Client().get("/forgot-password/", HTTP_HOST=SUNRISE).content.decode()
        self.assertIn('<a href="/staff-sign-in/">Back to sign in</a>', staff)
        parent = Client().get("/forgot-password/?from=sign-in", HTTP_HOST=SUNRISE).content.decode()
        self.assertIn('<a href="/sign-in/">Back to sign in</a>', parent)
        self.assertIn('<input type="hidden" name="from" value="sign-in">', parent)
        # A closed list: `from` is never a link to anywhere else.
        elsewhere = Client().get("/forgot-password/?from=//evil.example/", HTTP_HOST=SUNRISE).content.decode()
        self.assertNotIn("evil.example", elsewhere)
        self.assertIn('<a href="/staff-sign-in/">Back to sign in</a>', elsewhere)

    def test_both_doors_offer_forgot_password_as_a_path(self):
        """Drawn by each door's module, with no host in it, so it cannot leave
        the host the door is on (`test_school_links.py` holds the parent link the same way)."""
        import pathlib

        staff = pathlib.Path("static/staff-signin/states.js").read_text()
        self.assertIn('<a href="/forgot-password/">Forgot password?</a>', staff)
        parent = pathlib.Path("static/signin/states.js").read_text()
        self.assertIn('<a href="/forgot-password/?from=sign-in">Forgot password?</a>', parent)

    def test_they_are_never_indexed(self):
        for path in ("/forgot-password/", "/reset-password/x/"):
            with self.subTest(path=path):
                self.assertIn(first_segment(path), NEVER_INDEXED)
                for host in (SUNRISE, PORTAL):
                    response = Client().get(path, HTTP_HOST=host)
                    connection.set_schema_to_public()
                    self.assertIn("noindex", response["X-Robots-Tag"])
                    self.assertIn('<meta name="robots" content="noindex, nofollow">', response.content.decode())
        robots = Client().get("/robots.txt", HTTP_HOST=SUNRISE).content.decode()
        for name in ("/forgot-password/", "/reset-password/"):
            self.assertIn(f"Disallow: {name}", robots)
