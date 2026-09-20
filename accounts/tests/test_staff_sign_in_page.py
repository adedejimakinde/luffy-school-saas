"""The staff sign-in page: the other door, on the same host, with nothing in it.

Three claims, and the third is what makes this page different from its
neighbour.

**It is served on the portal and nowhere else.** `api.sign_in()` begins with
`_portal_only()` exactly as the guardian routes do, so a password form on a
school's host would submit into a 404 — and a school's host refuses anybody
without an active membership there, which is the opposite of what a door needs.

**It tells an anonymous caller nothing.** The frame holds no account, no school
and no role, and the view reads nothing from the database.

**It is the page `SchoolAccessMiddleware` has been pointing at since PR C.** A
guardian signed in with a code who reaches a school where she holds no PARENT
role is refused with "This session was opened with a sign-in code, which reaches
a guardian's own children and nothing else", and `settings.GUARDIAN_SESSION_AGE`
justifies thirty days on the back of that narrowing with the sentence "She gets
her staff powers again by signing in with her password." Until this page there
was nowhere to do that. `TheEscalationRefusalHasSomewhereToPointTests` below is
what holds those two facts together — including the half that is still missing,
which is that the refusal does not yet *say* where to go.

The flow itself — the one step, the five answers, the landing that links nowhere
— is tested in `tests/js/staff_signin.test.js` under `node --test`, because
every one of those renderers is a pure function of an API body and needs no
browser.
"""

from django.templatetags.static import static

from accounts import services
from accounts.models import Role
from accounts.tests.test_guardian_signin import (
    HANDSET,
    PORTAL,
    SCHOOL_HOST,
    GuardianSignInSetUp,
)
from schools.models import Domain
from schools.tests.test_invitations import make_school

URL = "/staff-sign-in/"


class TheStaffSignInPageIsPortalOnlyTests(GuardianSignInSetUp):
    """Where the page exists, asserted on both hosts the platform serves."""

    def test_the_portal_serves_it(self):
        response = self.client.get(URL, HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_a_schools_own_host_does_not(self):
        """404 and not 403, matching what `/api/login/` answers there: the route
        does not exist on this host."""
        response = self.client.get(URL, HTTP_HOST=SCHOOL_HOST)

        self.assertEqual(response.status_code, 404)

    def test_the_page_is_served_to_somebody_with_no_session(self):
        """It has to be. The page is what asks for the password that creates
        one, so a `login_required` here would be a door that needs a key."""
        self.client.logout()
        response = self.client.get(URL, HTTP_HOST=PORTAL)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)

    def test_it_is_a_second_route_and_not_the_guardian_page_with_a_flag(self):
        """Two URLs, two documents. A page whose form depends on a query
        parameter is a page nobody can link to, and these two flows share no
        step: there is no password in one and nothing to keep between requests
        in the other."""
        staff = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()
        guardian = self.client.get("/sign-in/", HTTP_HOST=PORTAL).content.decode()

        self.assertNotEqual(staff, guardian)
        self.assertIn("staff-signin/app.js", staff)
        self.assertNotIn("staff-signin/app.js", guardian)


class TheStaffSignInFrameCarriesNothingTests(GuardianSignInSetUp):
    """What is in the document, against people and a school that really exist."""

    def test_no_account_or_school_detail_is_in_the_page(self):
        """The control for this is the fixture: `GuardianSignInSetUp` builds a
        school, a guardian with a name and a handset, and a child, and none of
        them may appear in a document served to whoever opens the URL."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        for absent in (self.mama.full_name, "08031234567", "Ada Okonkwo", "St Mary's"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_the_title_names_the_door_and_nobody_behind_it(self):
        """"Staff sign in" is which of the two doors this is, which the reader
        needs. It says nothing about who is signing in, and a tab title outlives
        the page in history and bookmarks."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        self.assertIn("<title>Staff sign in</title>", page)

    def test_the_page_names_its_own_assets(self):
        """Resolved through the same staticfiles storage the template uses, so
        this passes under plain storage locally and the hashed manifest in CI —
        and fails, naming the missing entry, where a deployment has no manifest
        for an asset."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        for asset in ("staff-signin/staff-signin.css", "staff-signin/app.js"):
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
        form that would submit into this same view and lose what they typed,
        which here would include a password."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        self.assertIn("<noscript>", page)
        self.assertIn("school office", page)
        self.assertNotIn("<form", page, "a form without its module is a trap")

    def test_no_password_field_is_in_the_document(self):
        """The form is built by the module, so the server never renders an
        input a browser would offer to fill before anything has loaded."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        self.assertNotIn('type="password"', page)

    def test_no_template_comment_prose_reached_the_document(self):
        """`{#` spanning lines is not a comment in Django and renders. Shipped
        here once already, which is why every comment in these templates is a
        `{% comment %}` block and why this assertion exists."""
        page = self.client.get(URL, HTTP_HOST=PORTAL).content.decode()

        for prose in ("deliberately", "long version", "cache-busted", "single-line"):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, page)


class TheEscalationRefusalHasSomewhereToPointTests(GuardianSignInSetUp):
    """The reachability gap this page closes, and the half of it that is open.

    The person is the staff-parent `settings.GUARDIAN_SESSION_AGE` is written
    about: a guardian at one school and a teacher at another. On a session
    opened with six digits off an SMS, `User.roles_at()` narrows her to PARENT,
    which at the school where she only teaches leaves nothing — and
    `SchoolAccessMiddleware` refuses her with "This session was opened with a
    sign-in code, which reaches a guardian's own children and nothing else".
    The constant justifies thirty days on that narrowing and ends "She gets her
    staff powers again by signing in with her password." Until this change that
    sentence named a page that did not exist.
    """

    OTHER_HOST = "grace.testserver"

    def setUp(self):
        super().setUp()
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.grace, domain=self.OTHER_HOST, is_primary=True)
        # She teaches here and has no child here. This is the whole shape of
        # the case: a role the code session is not allowed to carry, at a school
        # where the parent role it *is* allowed to carry does not exist.
        services.grant_membership(self.mama, self.grace, Role.TEACHER)

    def sign_in_with_a_code(self):
        self.client.post(
            "/api/guardian/code/",
            data={"value": HANDSET},
            content_type="application/json",
            HTTP_HOST=PORTAL,
        )
        answered = self.answer(self.mint())
        self.assertEqual(answered.status_code, 200, answered.content)

    def test_a_password_session_reaches_the_school_she_teaches_at(self):
        """The control for the class, and it has to come first: everything
        below would pass just as well against a middleware that refused this
        person on every credential."""
        self.client.force_login(self.mama)

        response = self.client.get("/api/csrf/", HTTP_HOST=self.OTHER_HOST)

        self.assertEqual(response.status_code, 200)

    def test_a_code_session_is_refused_there(self):
        """The escalation refusal itself, attributable to the credential rather
        than to a missing membership — because the test above just reached the
        same URL as the same person with a password."""
        self.sign_in_with_a_code()

        response = self.client.get("/api/csrf/", HTTP_HOST=self.OTHER_HOST)

        self.assertEqual(response.status_code, 403)

    def test_the_password_door_the_refusal_names_now_has_a_page(self):
        """What this change closes. The sentence in `settings.py` and
        `accounts/middleware.py` has somewhere to send her."""
        self.sign_in_with_a_code()
        self.client.get("/api/csrf/", HTTP_HOST=self.OTHER_HOST)

        page = self.client.get(URL, HTTP_HOST=PORTAL)

        self.assertEqual(
            page.status_code,
            200,
            "the password door named by the escalation refusal has no page",
        )
        self.assertIn("Staff sign in", page.content.decode())

    def test_the_refusal_still_does_not_say_where_to_go(self):
        """**A known limit, asserted rather than written down.**

        Operating rule 5 inverts here: there is no guard to control, because
        what is being recorded is an absence. `SchoolAccessMiddleware` raises
        `PermissionDenied` carrying a sentence written for the person it
        refuses, and there is no `403.html` in this repository — so Django's
        default handler renders `ERROR_PAGE_TEMPLATE` with empty `details` and
        the sentence reaches nobody. She sees "403 Forbidden" and is told
        neither what happened nor that a password would fix it.

        **Issue #122.** Closing it is a platform-wide surface rather than a
        template: the same
        handler answers "You do not have access to this school", which is a
        different refusal with a different remedy, and telling them apart wants
        a distinguishable exception rather than a template branching on a
        message string. It is also what would give these 403s an identity their
        bodies do not currently carry — the reason this class establishes which
        refusal fired by controlling the credential instead of reading the body.

        **This test goes red the day #122 is closed**, which is the point of
        it. When it does: delete it, and move its case into a test asserting
        that the refusal names this page.
        """
        self.sign_in_with_a_code()

        refused = self.client.get("/api/csrf/", HTTP_HOST=self.OTHER_HOST)
        body = refused.content.decode()

        self.assertEqual(refused.status_code, 403)
        self.assertNotIn("sign-in code", body, "the refusal now carries its sentence")
        self.assertNotIn(URL.strip("/"), body, "the refusal now names this page")
        self.assertNotIn("password", body.lower(), "the refusal now names the remedy")
