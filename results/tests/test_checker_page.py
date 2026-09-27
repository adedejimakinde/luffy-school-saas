"""The result checker's page: a form on each school's own host, and nothing else.

`docs/messaging.md` D11. The page is a **shell** like the card page: the card
arrives from `POST /api/results/check/`, which is where the admission number and
the PIN meet the question, and `results/tests/test_checker.py` holds that half.
What is asserted here is the frame — served on both schools' hosts to somebody
who is not signed in, empty of any child, and absent from the portal.

The form's states — the one refusal, the wait, the withheld card — are tested in
`tests/js/checker.test.js`, because each is a pure function of one API answer.
"""

from django.templatetags.static import static

from results.tests.fixtures import HOST, PORTAL, THEIR_HOST, ChainSetUp

URL = "/check/"


class TheCheckerFrameCarriesNoCardTests(ChainSetUp):
    """Two schools and the portal, with nobody signed in."""

    def get_page(self, host=HOST):
        self.client.logout()
        return self.client.get(URL, HTTP_HOST=host)

    def test_each_school_host_serves_it_to_somebody_with_no_account(self):
        for host in (HOST, THEIR_HOST):
            with self.subTest(host=host):
                response = self.get_page(host)

                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Location", response)
                self.assertIn('id="checker"', response.content.decode())

    def test_the_portal_has_no_checker(self):
        """`urls_public.py` serves every tenant pattern, so the view refuses it
        itself: a form there would take a PIN on a host with no cards behind
        it and call it wrong."""
        response = self.get_page(PORTAL)

        self.assertEqual(response.status_code, 404)

    def test_no_child_and_no_school_is_named_in_the_frame(self):
        """Ada and Grace's child are real children at these two schools; the
        frame is the same document for both hosts and names neither."""
        for host in (HOST, THEIR_HOST):
            page = self.get_page(host).content.decode()
            for absent in ("Ada Obi", "Emeka Nwosu", self.grace_child.name, "St Mary", "Grace Academy", "JSS 1A"):
                with self.subTest(host=host, absent=absent):
                    self.assertNotIn(absent, page)

    def test_the_title_names_nobody(self):
        page = self.get_page().content.decode()

        self.assertIn("<title>Result checker</title>", page)

    def test_the_frame_names_the_portal_for_families_who_can_sign_in(self):
        page = self.get_page().content.decode()

        self.assertIn(f'data-portal="{PORTAL}"', page)

    def test_the_page_names_its_own_assets_and_the_card_page_styles(self):
        page = self.get_page().content.decode()

        for asset in ("checker/checker.css", "checker/app.js", "card/card.css", "card/print.css"):
            with self.subTest(asset=asset):
                self.assertIn(static(asset), page)

    def test_the_import_map_comes_before_the_module_that_needs_it(self):
        page = self.get_page().content.decode()

        self.assertLess(
            page.index('<script type="importmap">'),
            page.index('type="module"'),
        )

    def test_no_template_comment_prose_reached_the_document(self):
        page = self.get_page().content.decode()

        for prose in ("spanning lines", "shared computer", "dead link", "cache-busting"):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, page)
