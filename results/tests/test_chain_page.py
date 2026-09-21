"""The chain page: a frame, and not one result in it.

The same three claims the register and marking pages make, and for the same
reasons: it is a shell, it is served to whoever opens the URL, and the portal
serves the frame while every route behind it 404s there.

The flow — the per-role buttons, the send-back box, the four refusals — is in
`tests/js/chain.test.js` under `node --test`.
"""

from django.templatetags.static import static

from results.tests.fixtures import HOST, PORTAL, ChainSetUp
from schools.models import Domain

URL = "/results/"


class TheChainFrameHoldsNoResultsTests(ChainSetUp):
    def get_page(self, user=None, host=HOST):
        if user is not None:
            self.client.force_login(user.user)
        else:
            self.client.logout()
        return self.client.get(URL, HTTP_HOST=host)

    def test_a_schools_own_host_serves_it(self):
        response = self.get_page(self.head)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn('id="results"', response.content.decode())

    def test_the_classes_really_exist_while_the_page_is_empty_of_them(self):
        """The control for the exclusion below, and it runs first: a page that
        names no class has two possible reasons, and this pins the one that is
        not the design."""
        self.client.force_login(self.head.user)

        rows = self.client.get("/api/results/chain/", HTTP_HOST=HOST).json()["rows"]

        self.assertEqual(sorted(r["class_group"] for r in rows), ["JSS 1A", "JSS 1B"])

    def test_no_class_and_no_state_is_named_in_the_frame(self):
        page = self.get_page(self.head).content.decode()

        for absent in ("JSS 1A", "JSS 1B", "Submitted", "St Mary's", "Ada Obi"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_an_anonymous_caller_gets_the_frame_and_not_a_redirect(self):
        """A `login_required` here would turn the URL into an oracle in a
        deployment where a school's host is guessable."""
        response = self.get_page(None)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="results"', response.content.decode())

    def test_a_bursar_gets_the_frame_and_is_refused_by_the_route(self):
        """Where the authority lives. The page is the same document for
        everybody; the fetch inside it is what refuses her."""
        self.client.force_login(self.bursar.user)

        page = self.client.get(URL, HTTP_HOST=HOST)
        answer = self.client.get("/api/results/chain/", HTTP_HOST=HOST)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 403)

    def test_the_frame_names_the_portal_so_the_signed_out_state_can_offer_a_way_back(self):
        self.assertIn('data-portal="testserver"', self.get_page(self.head).content.decode())

    def test_with_no_portal_domain_the_attribute_is_empty_rather_than_wrong(self):
        """The pair the card page already has: this passes for a view that
        never sets the variable, and the test above is what refuses that."""
        Domain.objects.filter(tenant__schema_name="public").delete()

        self.assertIn('data-portal=""', self.get_page(self.head).content.decode())

    def test_the_stylesheet_and_entry_point_are_the_chain_pages_own(self):
        page = self.get_page(self.head).content.decode()

        self.assertIn(static("results/results.css"), page)
        self.assertIn(static("results/app.js"), page)

    def test_the_portal_serves_the_frame_and_the_route_behind_it_404s(self):
        self.client.force_login(self.head.user)

        page = self.client.get(URL, HTTP_HOST=PORTAL)
        answer = self.client.get("/api/results/chain/", HTTP_HOST=PORTAL)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 404)
