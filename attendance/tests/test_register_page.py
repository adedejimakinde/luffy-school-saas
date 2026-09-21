"""The register page: the first staff surface, and no register in it.

Three claims.

**It is a shell.** The frame holds no class, no child and no mark, and the view
reads one row — the portal's hostname — and nothing else. Everything a teacher
marks arrives afterwards from the `attendance` routes, behind the session
cookie, which is where the authority question is asked.

**It is served to whoever opens the URL.** No `login_required`, for the reason
`results/views.py` gives about the card page: a redirect on a guessable URL is
an oracle, answering "this school exists and this is its register" to anybody
who types it. The fetch inside the page is what meets the question.

**The portal serves the frame too, and that is not a leak.** `urls_public.py`
splats the tenant patterns in, so `/register/` resolves there exactly as
`/cards/` does — and every route it calls begins with `_school_of()`, which
404s on the portal because the register tables do not exist in the public
schema. The page has a state for that answer rather than a routing rule
pretending the URL is absent.

The flow itself — the chooser, the marking screen, the two warnings the write
can come back with — is in `tests/js/register.test.js` under `node --test`,
because every one of those renderers is a pure function of an API body.
"""

from django.templatetags.static import static

from attendance.tests.test_api import HOST, RegisterApiSetUp
from schools.models import Domain

URL = "/register/"


class TheRegisterFrameHoldsNoRegisterTests(RegisterApiSetUp):
    def get_page(self, user=None, host=HOST):
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(URL, HTTP_HOST=host)

    def test_a_schools_own_host_serves_it(self):
        response = self.get_page(self.teacher.user)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn('id="register"', response.content.decode())

    def test_the_roster_really_exists_while_the_page_is_empty_of_it(self):
        """The control for the exclusion below, and it runs first: a page that
        names no child has two possible reasons, and this pins the one that is
        not the design."""
        self.client.force_login(self.teacher.user)

        rows = self.get(group=self.jss1a_id).json()["rows"]

        self.assertEqual(len(rows), 4, "the class is empty, so nothing is excluded")
        self.assertIn("Ada Obi", [row["student"] for row in rows])

    def test_no_child_and_no_class_is_named_in_the_frame(self):
        page = self.get_page(self.teacher.user).content.decode()

        for absent in ("Ada Obi", "Emeka Nwosu", "JSS 1A", "JSS 1B", "St Mary's"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_an_anonymous_caller_gets_the_frame_and_not_a_redirect(self):
        """A `login_required` here would turn the URL into an oracle in a
        deployment where a school's host is guessable."""
        response = self.get_page(None)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="register"', response.content.decode())

    def test_a_bursar_gets_the_frame_and_is_refused_by_the_route(self):
        """Where the authority actually lives. The page is the same document
        for everybody; the fetch inside it is what refuses her."""
        self.client.force_login(self.bursar.user)

        page = self.client.get(URL, HTTP_HOST=HOST)
        answer = self.client.get("/api/attendance/where/", HTTP_HOST=HOST)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 403)

    def test_the_frame_names_the_portal_so_the_signed_out_state_can_offer_a_way_back(self):
        """`/staff-sign-in/` is on the portal and this page is on a school's
        host, so the link cannot be relative."""
        page = self.get_page(self.teacher.user).content.decode()

        self.assertIn('data-portal="testserver"', page)

    def test_with_no_portal_domain_the_attribute_is_empty_rather_than_wrong(self):
        """The pair `card_page()` already has: this test passes for a view that
        never sets the variable at all, and the one above it is what refuses
        that reading."""
        Domain.objects.filter(tenant__schema_name="public").delete()

        page = self.get_page(self.teacher.user).content.decode()

        self.assertIn('data-portal=""', page)

    def test_the_stylesheet_and_entry_point_are_the_register_s_own(self):
        page = self.get_page(self.teacher.user).content.decode()

        self.assertIn(static("register/register.css"), page)
        self.assertIn(static("register/app.js"), page)

    def test_the_portal_serves_the_frame_too_and_that_is_the_documented_answer(self):
        """Not a leak: `urls_public.py` splats the tenant patterns in, so this
        resolves there exactly as `/cards/` does, and the frame holds nothing.
        Every route it calls 404s on the portal."""
        self.client.force_login(self.teacher.user)

        page = self.client.get(URL, HTTP_HOST="testserver")
        answer = self.client.get("/api/attendance/where/", HTTP_HOST="testserver")

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 404)
