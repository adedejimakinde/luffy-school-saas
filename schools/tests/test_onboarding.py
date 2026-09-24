"""Bringing the portal and a school onto the platform: `setup_portal`, `create_school`.

The rule both go through (`schools.onboarding.check_host`): every host is **one
valid label under `PLATFORM_DOMAIN`** — under it, because the session cookie
spans the portal and every school; one label, because the wildcard certificate
covers nothing deeper. And a school arrives with its first administrator
invited, in the same transaction, or not at all.

These run real `CREATE SCHEMA` and migrations for the schools they make
(`School.save()`), so they are few.
"""

from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from accounts.models import Membership, MembershipStatus, Role, User
from schools.models import Domain, Invitation, School
from schools.delivery import DeliveryNotConfigured
from schools.onboarding import OnboardingError, create_school, setup_portal
from schools.tests.test_invitations import RecordingChannel

PLATFORM = dict(
    PLATFORM_DOMAIN="classnode.test",
    PORTAL_HOST="app.classnode.test",
    INVITATION_CHANNEL="schools.tests.test_invitations.RecordingChannel",
    INVITATION_ACCEPT_URL="https://app.classnode.test/invitations/{token}/",
)


#: The real email channel, with nowhere to send: SMTP and no host — exactly a
#: deployment that has not signed up with a provider yet.
NO_PROVIDER = dict(
    INVITATION_CHANNEL="schools.delivery.EmailChannel",
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="",
)

#: The real email channel, sending — into Django's test outbox.
WITH_PROVIDER = dict(
    INVITATION_CHANNEL="schools.delivery.EmailChannel",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)

ACCEPT_PAGE = "https://app.classnode.test/invitations/"


def schema_exists(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", [name])
        return cursor.fetchone() is not None


@override_settings(**PLATFORM)
class OnboardingTests(TestCase):
    def setUp(self):
        RecordingChannel.sent = []
        self.operator = User.objects.create_superuser("ops", "a-long-password", full_name="Ops")

    def tearDown(self):
        # `TenantMainMiddleware` (and a migrated schema) leave the connection on
        # a school's schema, and `School.save()` refuses to create a tenant
        # anywhere but public — so without this the failure lands in whichever
        # test happens to run next. `BroadsheetApiSetUp` carries the same line.
        connection.set_schema_to_public()
        super().tearDown()

    def make(self, slug="stmarys", **kw):
        kw.setdefault("name", "St Mary's")
        kw.setdefault("admin_email", "head@stmarys.example")
        kw.setdefault("operator", self.operator)
        with self.captureOnCommitCallbacks(execute=True):
            return create_school(slug=slug, **kw)

    def refused(self, message=None, **kw):
        """Refused **by the onboarding rules** — not by Postgres rejecting a
        schema name further down, which would be a refusal with the wrong
        identity and, for a name Postgres accepts, no refusal at all. Anything
        else that raises is a failure that names what refused instead."""
        try:
            self.make(**kw)
        except OnboardingError as exc:
            if message:
                self.assertIn(message, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — the point is to name it
            self.fail(f"refused by {type(exc).__name__}, not by the host rule: {exc}")
        self.fail(f"created with {kw!r}, where the host rule should have refused it")

    def nothing_was_written(self):
        """No school, no host and no invitation — nothing to clean up by hand."""
        self.assertFalse(School.objects.exists())
        self.assertFalse(Domain.objects.exists())
        self.assertFalse(Invitation.objects.exists())

    # -- the portal ---------------------------------------------------------------

    def test_setup_portal_puts_the_portal_on_its_host_and_can_run_twice(self):
        setup_portal()
        setup_portal()

        domain = Domain.objects.get(domain="app.classnode.test")
        self.assertEqual(domain.tenant.schema_name, "public")
        self.assertTrue(domain.is_primary)
        self.assertEqual(School.objects.filter(schema_name="public").count(), 1)

    # -- a school, the whole way --------------------------------------------------

    def test_a_school_gets_a_real_schema_its_host_and_an_invited_administrator(self):
        """The control: every refusal below would pass against a command that
        created nothing for anybody."""
        school, host, invitation, link = self.make()

        self.assertIsNone(link, "a delivered invitation's link came back to be printed")
        self.assertEqual(host, "stmarys.classnode.test")
        self.assertTrue(schema_exists("stmarys"))
        self.assertEqual(Domain.objects.get(domain=host).tenant, school)
        self.assertEqual(invitation.sent_to, "head@stmarys.example")
        self.assertEqual(invitation.membership.role, Role.ADMIN)
        self.assertEqual(invitation.membership.status, MembershipStatus.INVITED)
        self.assertEqual(
            RecordingChannel.sent[-1]["accept_url"].split(RecordingChannel.sent[-1]["raw_token"])[0],
            "https://app.classnode.test/invitations/",
        )

    def test_the_command_says_where_the_school_answers(self):
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command(
                "create_school", "grace", "Grace Academy",
                admin_email="head@grace.example", operator="ops", stdout=out,
            )

        self.assertIn("https://grace.classnode.test/", out.getvalue())

    # -- delivery: emailed, or handed over by the operator -----------------------

    def test_with_no_email_provider_the_school_is_made_and_its_link_handed_over(self):
        """Decided 2026-09-24: before the deployment has an email provider, the
        operator is the delivery. The school, its host and the invitation are
        all made, and the accept link comes back — a working one.

        CONTROL 9: dropping the hand-over fallback makes this red.
        """
        with override_settings(**NO_PROVIDER):
            try:
                created = self.make()
            except DeliveryNotConfigured as exc:
                self.fail(f"refused for want of an email provider, where the link should come back: {exc}")

        self.assertTrue(schema_exists("stmarys"))
        self.assertEqual(created.invitation.sent_to, "head@stmarys.example")
        link = created.link_to_hand_over
        self.assertTrue(link.startswith(ACCEPT_PAGE), link)
        token = link[len(ACCEPT_PAGE):].rstrip("/")
        self.assertEqual(Invitation.validate_token(token), created.invitation, "the link does not open it")
        self.assertEqual(len(mail.outbox), 0)

    def test_the_command_prints_the_link_for_the_operator_to_hand_over(self):
        """CONTROL 9 too: without the fallback the command refuses instead."""
        out = StringIO()
        with override_settings(**NO_PROVIDER):
            try:
                call_command(
                    "create_school", "grace", "Grace Academy",
                    admin_email="head@grace.example", operator="ops", stdout=out,
                )
            except CommandError as exc:
                self.fail(f"the command refused, where it should hand the link over: {exc}")

        printed = out.getvalue()
        self.assertIn("No email provider is configured", printed)
        self.assertIn("Give this link to head@grace.example yourself", printed)
        self.assertIn(ACCEPT_PAGE, printed)

    def test_with_an_email_provider_it_is_emailed_and_the_link_not_printed(self):
        """The link is a credential. Emailed, it went where it belongs, and a
        copy in the operator's terminal would be one more place it lives."""
        out = StringIO()
        with override_settings(**WITH_PROVIDER):
            with self.captureOnCommitCallbacks(execute=True):
                call_command(
                    "create_school", "grace", "Grace Academy",
                    admin_email="head@grace.example", operator="ops", stdout=out,
                )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["head@grace.example"])
        self.assertIn(ACCEPT_PAGE, mail.outbox[0].body)
        self.assertIn("invited by email at head@grace.example", out.getvalue())
        self.assertNotIn("/invitations/", out.getvalue())

    def test_no_provider_and_no_accept_page_still_refuses_the_whole_school(self):
        """Then there is nothing to hand over either."""
        with override_settings(**NO_PROVIDER, INVITATION_ACCEPT_URL=None):
            with self.assertRaises(DeliveryNotConfigured):
                self.make()

        self.nothing_was_written()
        self.assertFalse(schema_exists("stmarys"))

    # -- the host rule ------------------------------------------------------------

    def test_a_host_more_than_one_label_deep_is_refused_before_anything_is_written(self):
        """The certificate covers `*.classnode.test` and nothing deeper.

        CONTROL 7: `create_school` skipping `check_host()` makes this red.
        """
        self.refused("more than one label", slug="st.marys")

        self.nothing_was_written()

    def test_no_platform_domain_is_refused(self):
        """Without it there is no parent for the host, and no cookie reaches it.

        CONTROL 7 too: skipping the check makes a school on `stmarys.None`.
        """
        with override_settings(PLATFORM_DOMAIN=None):
            self.refused("PLATFORM_DOMAIN is not set")

        self.nothing_was_written()

    def test_a_label_that_is_not_a_dns_label_is_refused(self):
        for slug in ("St Marys", "-stmarys", "stmarys-", "st_marys"):
            with self.subTest(slug=slug):
                self.refused("not a usable subdomain", slug=slug)

    def test_the_portals_subdomain_and_the_reserved_ones_are_refused(self):
        for slug in ("app", "www", "admin"):
            with self.subTest(slug=slug):
                self.refused("reserved", slug=slug)

    # -- refusals that leave nothing behind ---------------------------------------

    def test_a_second_school_on_the_same_slug_is_refused(self):
        self.make()

        with self.assertRaisesMessage(OnboardingError, "already a school"):
            self.make(name="Another St Mary's", admin_email="other@example.com")

        self.assertEqual(School.objects.filter(slug="stmarys").count(), 1)

    def test_only_platform_staff_may_create_a_school(self):
        somebody = User.objects.create_user("head", "a-long-password", full_name="A Head")

        with self.assertRaisesMessage(OnboardingError, "not platform staff"):
            self.make(operator=somebody)

        self.nothing_was_written()

    def test_a_school_nobody_can_be_invited_to_is_not_created(self):
        """No accept page address means no invitation can be sent, and a school
        with no way in is refused whole — schema, host and all."""
        from schools.delivery import DeliveryNotConfigured

        with override_settings(INVITATION_ACCEPT_URL=None):
            with self.assertRaises(DeliveryNotConfigured):
                self.make()

        self.nothing_was_written()
        self.assertFalse(schema_exists("stmarys"))
        self.assertFalse(Membership.objects.filter(role=Role.ADMIN).exists())

    def test_the_command_turns_a_refusal_into_a_message(self):
        """A `CommandError` carrying the host rule's words — not a traceback
        from further down, and not a school."""
        try:
            call_command(
                "create_school", "st.marys", "St Mary's",
                admin_email="head@example.com", operator="ops", stdout=StringIO(),
            )
        except CommandError as exc:
            self.assertIn("more than one label", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — the point is to name it
            self.fail(f"the command failed with {type(exc).__name__}, not a refusal: {exc}")
        self.fail("the command created a school on a host two labels deep")
