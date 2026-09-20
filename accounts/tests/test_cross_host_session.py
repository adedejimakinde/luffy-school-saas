"""A session opened on the portal has to reach a school's host. Proved, not assumed.

This is the join between the two pages PR 4 adds: a guardian signs in at
`portal/sign-in/` and is sent to `st-marys/cards/`. If the cookie minted by the
first request is not sent with the second, every part of the flow still *looks*
like it worked — 200, a cookie, a redirect — and the parent arrives
unauthenticated. `accounts.checks.session_cookie_spans_every_host` refuses that
deployment; these tests are the mechanism behind that refusal.

## Why this is not tested with a round trip

**Django's test client is not a browser and does not scope cookies.** It keeps
one jar and sends it with whatever `HTTP_HOST` you pass, so

    sign in on the portal, then GET the school host

passes **whether or not a real browser would have sent that cookie**. A test of
that shape is a false green on exactly the claim it appears to make, and
`test_the_round_trip_proves_nothing` below is the control that says so out loud
rather than leaving the next reader to find it.

What a browser actually uses is the `Domain` attribute on the `Set-Cookie`
header, under the RFC 6265 domain-match rule. So that is what is asserted, in
both directions: with the setting, the cookie's domain covers both hosts;
without it, the cookie is host-only and the school host would never see it.
"""

from django.test import override_settings

from accounts import guardian_contacts
from accounts.checks import session_cookie_spans_every_host
from results.tests.test_card_api import HOST, ReportCardApiSetUp

#: The portal's host in this fixture, and the school's.
PORTAL = "testserver"
SCHOOL_HOST = HOST

#: `give_verified_channel(self.mama, ...)` in the fixture used this number.
HANDSET = "08030000001"

#: The parent of both hosts the fixture serves: `testserver` and
#: `st-marys.testserver`.
PARENT_DOMAIN = ".testserver"


def a_browser_would_send(cookie_domain: str, to_host: str) -> bool:
    """RFC 6265's domain-match rule, written out because the claim rests on it.

    A cookie with no `Domain` attribute is *host-only*: it goes back to the
    exact host that set it and nowhere else. A cookie with one goes to that
    domain and every subdomain of it.
    """
    if not cookie_domain:
        return False
    domain = cookie_domain.lstrip(".")
    return to_host == domain or to_host.endswith(f".{domain}")


class GuardianSignsInAtThePortal(ReportCardApiSetUp):
    """The results fixture, because these tests read a tenant table.

    `ReportCardApiSetUp` builds real schemas for two schools, a released card
    and a guardian with a verified handset. The guardian sign-in module's own
    fixture deliberately does not: it imports a row-only `make_school` and says
    why — every model it touches is public-schema, so it skips `CREATE SCHEMA`.
    That is right for testing the doors and wrong for a test that has to ask the
    index for a card.
    """

    def mint(self):
        """A live sign-in code, through the service the route uses.

        The raw code never leaves the service — it is stored as a SHA-256 — so
        a test that wants to answer one has to be the caller that minted it.

        The contact is fetched by relation rather than by `value=HANDSET`:
        `GuardianContact.normalize_value()` stores a phone number in E.164, so
        the stored string is not the one the fixture typed and not the one a
        parent types either. The route normalises what it is given, which is
        why `HANDSET` is still what gets posted.
        """
        account = guardian_contacts.guardian_account_for(self.mama)
        contact = account.contacts.get()
        _, raw_code = guardian_contacts.request_sign_in_code(contact)
        return raw_code

    def ask_for_a_code(self, value=HANDSET, host=PORTAL):
        return self.client.post(
            "/api/guardian/code/",
            data={"value": value},
            content_type="application/json",
            HTTP_HOST=host,
        )

    def answer(self, code, value=HANDSET, guardian=None, host=PORTAL):
        payload = {"value": value, "code": code}
        if guardian is not None:
            payload["guardian"] = guardian
        return self.client.post(
            "/api/guardian/session/",
            data=payload,
            content_type="application/json",
            HTTP_HOST=host,
        )

    def sign_in(self):
        """Through the real doors: ask for a code, then answer it."""
        self.ask_for_a_code()
        response = self.answer(self.mint())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("sessionid", response.cookies, "no session was minted")
        return response


class TheSessionCookieSpansBothHostsTests(GuardianSignsInAtThePortal):
    """The mechanism, asserted on the header a browser reads."""

    @override_settings(SESSION_COOKIE_DOMAIN=PARENT_DOMAIN)
    def test_the_cookie_is_scoped_to_the_parent_of_both_hosts(self):
        response = self.sign_in()
        domain = response.cookies["sessionid"]["domain"]

        self.assertEqual(domain, PARENT_DOMAIN)
        self.assertTrue(
            a_browser_would_send(domain, SCHOOL_HOST),
            f"a browser would not send a {domain} cookie to {SCHOOL_HOST}",
        )
        self.assertTrue(
            a_browser_would_send(domain, PORTAL),
            "the portal itself must keep working",
        )

    def test_without_the_setting_the_cookie_never_leaves_the_portal(self):
        """The failure the deploy check exists to refuse, demonstrated.

        `SESSION_COOKIE_DOMAIN` is unset in development and in this suite, which
        is exactly why the check is `deploy=True` — and why this test asserts
        the *absence* rather than skipping.
        """
        response = self.sign_in()
        domain = response.cookies["sessionid"]["domain"]

        self.assertEqual(domain, "", "expected a host-only cookie")
        self.assertFalse(
            a_browser_would_send(domain, SCHOOL_HOST),
            "a host-only cookie cannot reach a school's host",
        )

    def test_the_round_trip_proves_nothing(self):
        """CONTROL. The obvious test passes in the broken configuration.

        With no `Domain` attribute — the configuration the test above shows a
        browser would never carry across — the test client reads the school
        host perfectly happily, because it sends its jar regardless of host.
        Anybody who writes "sign in, then fetch the other host" and sees green
        has measured the test client, not the platform.
        """
        self.sign_in()
        answer = self.client.get("/api/results/cards/", HTTP_HOST=SCHOOL_HOST)

        self.assertEqual(
            answer.status_code,
            200,
            "if this ever 401s, the client has started scoping cookies and the "
            "tests above can be simplified",
        )
        self.assertEqual(
            self.client.cookies["sessionid"]["domain"],
            "",
            "the cookie the client just used is one a browser would not have sent",
        )

    @override_settings(SESSION_COOKIE_DOMAIN=PARENT_DOMAIN)
    def test_the_setting_that_makes_it_work_is_the_one_production_must_have(self):
        """Ties the mechanism to the guard, so neither drifts alone.

        `accounts.E001` is the only thing standing between this platform and a
        deployment where sign-in succeeds and every school host is
        unauthenticated. Its condition and the cookie attribute above are the
        same fact, and this asserts they stay the same fact.
        """
        self.assertEqual(session_cookie_spans_every_host(None), [])

    def test_unset_is_refused_at_deploy_by_name(self):
        errors = session_cookie_spans_every_host(None)

        self.assertEqual([error.id for error in errors], ["accounts.E001"])


class TheSignedInGuardianReachesTheIndexTests(GuardianSignsInAtThePortal):
    """The other half: once the cookie does arrive, the index answers.

    Scoping is necessary and not sufficient — the school's host also has
    `SchoolAccessMiddleware` in front of it, which refuses anybody without an
    active membership *there*. A guardian signed in on the portal has to get
    past that too, so the flow is only proved end to end by asking the index
    for real.
    """

    @override_settings(SESSION_COOKIE_DOMAIN=PARENT_DOMAIN)
    def test_the_index_lists_this_guardians_child_at_the_school_host(self):
        self.release()
        self.ask_for_a_code()
        self.answer(self.mint())

        answer = self.client.get("/api/results/cards/", HTTP_HOST=SCHOOL_HOST)

        self.assertEqual(answer.status_code, 200, answer.content)
        names = [child["student_name"] for child in answer.json()["children"]]
        self.assertIn("Ada Obi", names)
        self.assertNotIn(
            "Bola Eze", names, "a guardian sees their own children and no others"
        )

    @override_settings(SESSION_COOKIE_DOMAIN=PARENT_DOMAIN)
    def test_the_index_page_itself_is_served_at_the_school_host(self):
        """The frame, which is what the redirect actually lands on."""
        page = self.client.get("/cards/", HTTP_HOST=SCHOOL_HOST)

        self.assertEqual(page.status_code, 200)
        self.assertIn('id="index"', page.content.decode())
