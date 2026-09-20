"""The page a family opens, and the claim that there is no card in it.

Task: the report card page. The page is a **shell** — a frame, a stylesheet and
three ES modules — and every mark a parent reads arrives afterwards from
`GET /api/results/cards/<child>/<term>/`, which is the one place that asks who
may read what.

Two claims, and the second is the one with teeth.

**It is served.** At the school's own host, to whoever asks, including somebody
not signed in — because the frame has nothing in it and the fetch inside it is
what meets the authority question.

**It cannot leak a card, structurally.** The tests below release a real card,
prove the numbers are on the frozen row, and then assert that not one of them
is in the page's bytes. That is the same shape as `test_pdf.py`'s exclusion
tests: "absent from the response" has two causes, and only one of them is the
design working.

The client-side half — the marks table, and the four states a refusal puts the
page in — is tested where it lives, in `results/tests/js/` under `node --test`,
because those renderers are pure functions of a payload and need no browser.
"""

from django.templatetags.static import static
from django.test import TestCase

from academics.models import TermName
from results import cards
from results.tests.test_card_api import HOST, ReportCardApiSetUp
from schools.tests.tenants import connected_to


class ThePageIsAFrameAndNotACardTests(ReportCardApiSetUp):
    """What the shell contains, asserted against a card that really exists."""

    def setUp(self):
        super().setUp()
        self.release()

    def page_url(self, membership, term_name=TermName.FIRST.value):
        return f"/cards/{membership.pk}/{self.terms_of(self.stmarys)[str(term_name)]}/"

    def get_page(self, user=None, host=HOST):
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(self.page_url(self.ada), HTTP_HOST=host)

    def test_the_school_host_serves_the_page(self):
        response = self.get_page(self.mama)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_the_card_really_exists_while_the_page_is_empty_of_it(self):
        """The control for the exclusion test below, and it runs first.

        A page that says nothing about Ada's marks says nothing for one of two
        reasons: the shell is empty, or there was never a card. This pins the
        second one shut.
        """
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))

        self.assertIsNotNone(card, "nothing was released, so nothing is being excluded")
        self.assertEqual(card.student_name, "Ada Obi")
        self.assertGreater(card.total_scored, 0)

    def test_not_one_figure_from_the_card_is_in_the_page(self):
        """The structural claim. The frame is served before anybody is known.

        The shell is public — it has to be, because the fetch inside it is what
        authenticates — so anything the *server* wrote into it would be readable
        by whoever opened the URL. That includes the browser tab's title and a
        bookmark of it, which is why the title is "Report card" and not the
        child's name.
        """
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))
        page = self.get_page(self.mama).content.decode()

        for absent in (
            card.student_name,
            card.class_group_name,
            card.school_name,
            str(card.total_scored),
            str(card.own_average),
        ):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page, "the shell is carrying card content")

    def test_a_visitor_who_is_not_signed_in_gets_the_frame(self):
        """Not a redirect, and not a 403.

        The page's job when nobody is signed in is to render the "please sign
        in" state, which it can only do if it is served. A `login_required` here
        would also make the URL an oracle in a different way: a redirect for a
        stranger and a page for a parent tells the stranger the URL is real.
        """
        response = self.get_page(None)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)

    def test_the_ids_are_not_checked_and_must_not_be(self):
        """No existence oracle in front of an API built not to be one.

        `card_api` answers one flat 404 for "no such child", "no card released"
        and "not yours". A shell that 404'd for a membership id that does not
        exist would answer the first of those three by itself, in front of the
        route that refuses to.
        """
        self.client.force_login(self.mama)
        nobody = self.client.get(
            f"/cards/999999/{self.terms_of(self.stmarys)[TermName.FIRST.value]}/",
            HTTP_HOST=HOST,
        )
        somebody = self.get_page(self.mama)

        self.assertEqual(nobody.status_code, 200)
        self.assertEqual(nobody.status_code, somebody.status_code)

        # The two frames are the same document once each one's own ids are
        # taken out. Comparing raw bytes would fail on the digit count of the
        # id the caller themselves sent — which is not a disclosure, and a test
        # that called it one would be measuring its own fixture. What matters
        # is that nothing *else* differs between a real child and an invented
        # one.
        term_id = self.terms_of(self.stmarys)[TermName.FIRST.value]
        self.assertEqual(
            nobody.content.decode()
            .replace("999999", "ID")
            .replace(str(term_id), "TERM"),
            somebody.content.decode()
            .replace(str(self.ada.pk), "ID")
            .replace(str(term_id), "TERM"),
            "the frames differ by more than the ids the caller sent",
        )

    def test_the_page_names_its_own_assets(self):
        """The template's `{% static %}` references, resolved the way it does.

        The expected URLs are computed through the *same* staticfiles storage
        the template uses, so this passes under plain storage locally and under
        the hashed manifest in CI — and fails loudly, naming the missing entry,
        if a deployment's storage has no manifest for an asset. That failure is
        the one this project would otherwise meet as "the page is broken".
        """
        page = self.get_page(self.mama).content.decode()

        for asset in (
            "card/app.js",
            "card/card.css",
            "card/print.css",
        ):
            with self.subTest(asset=asset):
                self.assertIn(static(asset), page)

    def test_the_frame_says_which_card_it_is_for_and_nothing_more(self):
        """The two integers are the whole of what the server tells the client.

        They are not a disclosure: they are the ids the caller already put in
        the URL. Everything else is the API's to answer.
        """
        page = self.get_page(self.mama).content.decode()
        term_id = self.terms_of(self.stmarys)[TermName.FIRST.value]

        self.assertIn(f'data-student-membership-id="{self.ada.pk}"', page)
        self.assertIn(f'data-term-id="{term_id}"', page)

    def test_the_import_map_is_declared_before_the_module_that_needs_it(self):
        """An import map after the import it governs is ignored, silently.

        The page would keep working in development, where key and value are the
        same URL, and lose its remapping in production — the same asymmetry
        `tests.test_pages` is about.
        """
        page = self.get_page(self.mama).content.decode()

        self.assertLess(
            page.index('<script type="importmap">'),
            page.index('type="module"'),
            "the import map is declared after the module script",
        )

    def test_the_template_has_no_unclosed_comment_rendering_on_the_page(self):
        """A trap this project has shipped before, pinned here.

        `{#` is a single-line comment in Django templates: spanning lines it is
        not a comment at all and every word of it renders. The page's comments
        are `{% comment %}` blocks for that reason, and this asserts none of
        their prose reached the document.
        """
        page = self.get_page(self.mama).content.decode()

        for prose in ("deliberately", "bundler", "build step", "authority check"):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, page)


class ThePortalServesAFrameThatCannotWorkTests(ReportCardApiSetUp):
    """What the portal host does with this route, stated rather than assumed.

    `urls_public.py` reuses `urls.py`'s patterns wholesale, on purpose — "a
    route added there cannot go missing here" — so the page is mounted on the
    portal as well. That is a dead frame rather than a leak, and the difference
    is worth a test: the shell carries no card either way, and the API it would
    fetch from has no school to answer for on the public schema, so the page
    settles in its "no report card here" state.
    """

    def test_the_portal_frame_is_empty_and_its_api_refuses(self):
        self.release()
        term_id = self.terms_of(self.stmarys)[TermName.FIRST.value]
        self.client.force_login(self.mama)

        frame = self.client.get(
            f"/cards/{self.ada.pk}/{term_id}/", HTTP_HOST="testserver"
        )
        self.assertEqual(frame.status_code, 200, "the portal serves the reused route")
        self.assertNotIn("Ada Obi", frame.content.decode())

        answer = self.client.get(
            f"/api/results/cards/{self.ada.pk}/{term_id}/", HTTP_HOST="testserver"
        )
        self.assertEqual(
            answer.status_code, 404, "the portal has no card to answer with"
        )
