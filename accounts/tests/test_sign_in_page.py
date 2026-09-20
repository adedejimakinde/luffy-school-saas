"""The sign-in page: one door, on one hostname, with nothing in it.

Two claims.

**It is served on the portal and nowhere else.** The routes behind it begin with
`api._portal_only()`, so a sign-in form on a school's host would submit into a
404 — and a school's host refuses anybody without an active membership there,
which is the opposite of what a door needs.

**It tells an anonymous caller nothing.** The frame holds no account, no child
and no school, and the view reads nothing from the database. Everything that
identifies anybody arrives through `POST /api/guardian/session/`, after a code.

The flow itself — four steps, the shared-handset 202, the refusals — is tested
in `tests/js/signin.test.js` under `node --test`, because every one of those
renderers is a pure function of an API body and needs no browser.
"""

from django.templatetags.static import static
from django.test import TestCase

from accounts.tests.test_guardian_signin import PORTAL, SCHOOL_HOST, GuardianSignInSetUp

URL = "/sign-in/"


class TheSignInPageIsPortalOnlyTests(GuardianSignInSetUp):
    """Where the page exists, asserted on both hosts the platform serves."""

    def test_the_portal_serves_it(self):
        response = self.client.get(URL, HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_a_schools_own_host_does_not(self):
        """404 and not 403, matching what the API answers there: the route does
        not exist on this host."""
        response = self.client.get(URL, HTTP_HOST=SCHOOL_HOST)

        self.assertEqual(response.status_code, 404)

    def test_the_page_is_served_to_somebody_with_no_session(self):
        """It has to be. The page is what asks for the code that creates one,
        so a `login_required` here would be a door that needs a key."""
        self.client.logout()
        response = self.client.get(URL, HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)


class TheSignInFrameCarriesNothingTests(GuardianSignInSetUp):
    """What is in the document, against a guardian who really exists."""

    def test_no_account_detail_is_in_the_page(self):
        """The control for this is the fixture itself: `GuardianSignInSetUp`
        builds a guardian with a name, a handset and a child, and none of the
        three may appear in a document served to whoever opens the URL."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        for absent in (self.mama.full_name, "08031234567", "Ada Okonkwo", "St Mary's"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_the_title_says_nothing_about_who_is_signing_in(self):
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        self.assertIn("<title>Sign in</title>", page)

    def test_the_page_names_its_own_assets(self):
        """Resolved through the same staticfiles storage the template uses, so
        this passes under plain storage locally and the hashed manifest in CI —
        and fails, naming the missing entry, where a deployment has no manifest
        for an asset."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        for asset in ("signin/signin.css", "signin/app.js"):
            with self.subTest(asset=asset):
                self.assertIn(static(asset), page)

    def test_the_import_map_comes_before_the_module_that_needs_it(self):
        """A map declared after the import it governs is ignored, silently —
        the page keeps working in development, where key and value are the same
        URL, and loses its remapping in production."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        self.assertLess(
            page.index('<script type="importmap">'),
            page.index('type="module"'),
        )

    def test_there_is_something_to_read_without_javascript(self):
        """The page is a form driven by a module, so a reader with no
        JavaScript gets a sentence and a way to ask a person — rather than a
        form that would submit into this same view and lose what they typed."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        self.assertIn("<noscript>", page)
        self.assertIn("school office", page)
        self.assertNotIn("<form", page, "a form without its module is a trap")

    def test_no_template_comment_prose_reached_the_document(self):
        """`{#` spanning lines is not a comment in Django and renders. Shipped
        here once already, which is why every comment in these templates is a
        `{% comment %}` block and why this assertion exists."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        for prose in ("deliberately", "long version", "cache-busted", "single-line"):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, page)
