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
what holds those two facts together — and since #122 closed, that the refusal
now *says* where to go, naming the door by the portal's full URL because a path
would resolve against the school's host she was refused on.

The flow itself — the one step, the five answers, the landing that links nowhere
— is tested in `tests/js/staff_signin.test.js` under `node --test`, because
every one of those renderers is a pure function of an API body and needs no
browser.
"""

from django.templatetags.static import static
from django.test import RequestFactory

from accounts import services
from accounts.models import Role, User
from accounts.refusals import (
    CodeSessionCannotEscalate,
    NoMembershipHere,
    SchoolAccessRefused,
)
from accounts.tests.test_guardian_signin import (
    HANDSET,
    PASSWORD,
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

    def test_the_refusal_carries_its_sentence_to_her(self):
        """**Issue #122, and the half of it that is about being read at all.**

        The sentence has existed since PR C and reached nobody: with no
        `403.html` in the repository Django's default handler rendered
        `ERROR_PAGE_TEMPLATE` with empty `details` and discarded it, so she saw
        "403 Forbidden" and was told neither what had happened nor that
        anything would fix it.

        This replaces `test_the_refusal_still_does_not_say_where_to_go`, which
        asserted that absence and said in its own docstring to delete it and
        move its case here the day #122 closed.
        """
        self.sign_in_with_a_code()

        refused = self.client.get("/api/csrf/", HTTP_HOST=self.OTHER_HOST)
        body = refused.content.decode()

        self.assertEqual(refused.status_code, 403)
        self.assertIn(
            "sign-in code",
            body,
            "the refusal's own sentence is still being discarded",
        )

    def test_the_refusal_names_the_password_door_by_its_full_url(self):
        """The other half: a remedy she can act on without ringing anybody.

        **The full URL is the assertion, not the path**, and that is the whole
        point of the test rather than a stricter way of writing it.
        `/staff-sign-in/` is mounted in `urls_public.py` and not in `urls.py`,
        so it exists on the portal and nowhere else — while this page renders
        on a school's host, which is where she was refused. A bare
        `/staff-sign-in/` in the markup would resolve against
        `grace.testserver` and hand her a 404 from the one screen whose job is
        telling her how to get back in, and an assertion on the path alone
        would have called that a pass.

        Scheme-relative rather than a hard-coded `https://`, matching
        `static/card/states.js` `wayBack()`: it keeps whatever scheme the
        deployment is served over.
        """
        self.sign_in_with_a_code()

        refused = self.client.get("/api/csrf/", HTTP_HOST=self.OTHER_HOST)
        body = refused.content.decode()

        self.assertEqual(refused.status_code, 403)
        self.assertIn(
            f"//{PORTAL}{URL}",
            body,
            "the refusal does not name the password door on the portal's host",
        )
        self.assertNotIn(
            f'href="{URL}"',
            body,
            "the door is linked by path, which resolves to a 404 on this host",
        )

    def test_the_other_refusal_offers_no_password_door(self):
        """The refusal next to it, which a password fixes nothing about.

        Somebody signed in with a password who holds no membership at this
        school is refused by the same middleware, through the same handler, to
        the same status. Offering her `/staff-sign-in/` would be a **false
        remedy** — she is already signed in with the password, and what she
        lacks is a membership only the school can give her.

        This is why the two refusals are separate exception types rather than
        one message the template reads: the remedy is a property of which
        refusal fired, and prose is not where that should be recovered from.
        """
        stranger = User.objects.create_user(
            "stranger", PASSWORD, full_name="No Body"
        )
        self.client.force_login(stranger)

        refused = self.client.get("/api/csrf/", HTTP_HOST=self.OTHER_HOST)
        body = refused.content.decode()

        self.assertEqual(refused.status_code, 403)
        self.assertIn("do not have access", body)
        self.assertNotIn(
            URL,
            body,
            "the password door is offered to somebody a password cannot help",
        )

    def test_the_two_refusals_are_told_apart_by_type_not_by_wording(self):
        """What holds the pair above together, asserted directly.

        Both are `PermissionDenied`, both reach `accounts.views.refused()`, and
        both answer 403. The only thing that makes them different pages is
        `a_password_fixes_it`, which is a class attribute — so a reworded
        sentence cannot change which remedy a reader is offered.
        """
        self.assertTrue(CodeSessionCannotEscalate.a_password_fixes_it)
        self.assertFalse(NoMembershipHere.a_password_fixes_it)
        self.assertTrue(issubclass(CodeSessionCannotEscalate, SchoolAccessRefused))
        self.assertTrue(issubclass(NoMembershipHere, SchoolAccessRefused))


    def test_both_urlconfs_resolve_the_same_403_handler(self):
        """The portal needs its own name for it, and that is easy to forget.

        Django looks `handler403` up as an attribute of whichever urlconf is in
        force, and `django_tenants` gives the public schema `urls_public` in
        place of `urls`. `urls_public` imports the name rather than repeating
        the dotted path, so there is one definition — but nothing else in this
        suite would notice if that import were dropped, because
        `SchoolAccessMiddleware` never refuses anybody on the portal and the
        two refusals above are raised on a school's host.

        So the wiring is asserted directly. Without this, the portal would
        quietly fall back to Django's default handler while every school's host
        used ours, and no test on the platform would have said so.
        """
        from django.urls import get_resolver

        from accounts.views import refused as ours

        for urlconf in ("urls", "urls_public"):
            with self.subTest(urlconf=urlconf):
                self.assertIs(
                    get_resolver(urlconf).resolve_error_handler(403),
                    ours,
                    f"{urlconf} does not resolve the platform's 403 handler",
                )


class ThePageServedForAnyOtherRefusalTests(GuardianSignInSetUp):
    """A `PermissionDenied` that is not one of ours still renders a page.

    It renders **without a sentence**, which is the deliberate part. An
    arbitrary exception's `str()` is written for whoever debugs it, and the 403
    page is not where a codebase should start printing that to whoever asked.
    """

    def test_a_plain_permission_denied_prints_no_detail(self):
        from django.core.exceptions import PermissionDenied

        from accounts.views import refused

        request = RequestFactory().get("/", HTTP_HOST=PORTAL)

        response = refused(request, PermissionDenied("internal: quota exceeded"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("quota exceeded", body)
        self.assertNotIn(URL, body, "a remedy was offered for an unknown refusal")

    def test_a_foreign_exception_carrying_the_flag_gets_no_remedy(self):
        """The attribute is not a duck type, and this is what says so.

        The first shape of `refused()` read the flag off whatever arrived, with
        `getattr(exception, "a_password_fixes_it", False)`. That gates the
        remedy on a *name* rather than on a type, so any future
        `PermissionDenied` that happened to carry it — from another app, for
        another reason — would have been offered the staff door while its
        sentence was withheld as untrusted. Offering a remedy the page has no
        grounds for is the failure `accounts/refusals.py` exists to prevent, so
        both halves are gated on the same `isinstance`.
        """
        from django.core.exceptions import PermissionDenied

        from accounts.views import refused

        class Impostor(PermissionDenied):
            a_password_fixes_it = True

        request = RequestFactory().get("/", HTTP_HOST=PORTAL)

        response = refused(request, Impostor("not ours"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(
            URL,
            body,
            "the staff door was offered to an exception that merely carries the name",
        )
        self.assertNotIn("not ours", body)
