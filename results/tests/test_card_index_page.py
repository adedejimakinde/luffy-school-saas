"""The index page: the frame that makes a card reachable, and nothing else in it.

Both card routes are keyed on `(student_membership_id, term_id)` and nothing
this API said to a family carried either number until `GET /api/results/cards/`
existed — so the card page shipped openable only by typing two integers into a
URL. This page is what closes that, and like the card page it is a **shell**:
the list a parent reads arrives from the API, behind the session cookie.

The list itself — the withheld mark, the two kinds of silence, the expired
session — is tested in `tests/js/index.test.js`, because every one of those
renderers is a pure function of one API answer.
"""

from django.templatetags.static import static
from django.test import TestCase

from academics.models import TermName
from results import cards
from results.tests.test_card_api import HOST, ReportCardApiSetUp
from schools.models import Domain
from schools.tests.tenants import connected_to

URL = "/cards/"


class TheIndexFrameCarriesNoListTests(ReportCardApiSetUp):
    """What the document holds, against a family whose card really exists."""

    def setUp(self):
        super().setUp()
        self.release()

    def get_page(self, user=None, host=HOST):
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(URL, HTTP_HOST=host)

    def test_the_school_host_serves_it(self):
        response = self.get_page(self.mama)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn('id="index"', response.content.decode())

    def test_the_card_really_exists_while_the_page_is_empty_of_it(self):
        """The control for the exclusion below, and it runs first: a page that
        says nothing about Ada has two possible reasons, and this pins the one
        that is not the design."""
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))

        self.assertIsNotNone(card, "nothing was released, so nothing is excluded")
        self.assertEqual(card.student_name, "Ada Obi")

    def test_no_child_and_no_card_is_named_in_the_frame(self):
        page = self.get_page(self.mama).content.decode()

        for absent in ("Ada Obi", "Bola Eze", "First term", "JSS 1A", "St Mary's"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_a_visitor_who_is_not_signed_in_gets_the_frame(self):
        """Not a redirect and not a 403: the page's job when nobody is signed in
        is to render its "please sign in" state, which it can only do if it is
        served."""
        response = self.get_page(None)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)

    def test_the_frame_names_the_portal_so_the_401_state_can_offer_a_way_back(self):
        """The only thing the server writes into this page.

        Sign-in is on the portal and this page is on a school's host, so the
        link out cannot be relative. `api._portal_only()` settles that the *API*
        will not answer where the portal is; this is read from the one authority
        there is — the `Domain` row for the public schema — and rendered into a
        page the same deployment serves.
        """
        page = self.get_page(self.mama).content.decode()

        self.assertIn('data-portal="testserver"', page)

    def test_a_deployment_with_no_portal_domain_renders_an_empty_one(self):
        """And the state then says its sentence without a link, rather than
        linking to `//undefined/sign-in/`. Asserted here because the alternative
        is a dead link on the page a parent reaches when their session lapses."""
        Domain.objects.filter(tenant__schema_name="public").delete()

        page = self.get_page(self.mama).content.decode()

        self.assertIn('data-portal=""', page)

    def test_the_page_names_its_own_assets(self):
        page = self.get_page(self.mama).content.decode()

        for asset in ("index/index.css", "index/app.js"):
            with self.subTest(asset=asset):
                self.assertIn(static(asset), page)

    def test_the_import_map_comes_before_the_module_that_needs_it(self):
        page = self.get_page(self.mama).content.decode()

        self.assertLess(
            page.index('<script type="importmap">'),
            page.index('type="module"'),
        )

    def test_no_template_comment_prose_reached_the_document(self):
        page = self.get_page(self.mama).content.decode()

        for prose in ("never a multi-line", "authority", "deployment has no portal"):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, page)
