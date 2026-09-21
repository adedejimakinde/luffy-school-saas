"""The remarks page: a frame, and not one remark in it.

The same three claims the three staff pages before it make: a shell, served to
whoever opens the URL, and the portal serves the frame while every route behind
it 404s there.

The flow — both remarks, the bank, the conduct grid, the four refusals — is in
`tests/js/comments.test.js` under `node --test`.
"""

from django.templatetags.static import static

from results.tests.fixtures import HOST, PORTAL
from results.tests.test_comments_api import TheCommentScreenSetUp
from schools.models import Domain

URL = "/comments/"


class TheCommentsFrameHoldsNoRemarksTests(TheCommentScreenSetUp):
    def get_page(self, user=None, host=HOST):
        if user is not None:
            self.client.force_login(user.user)
        else:
            self.client.logout()
        return self.client.get(URL, HTTP_HOST=host)

    def test_a_schools_own_host_serves_it(self):
        response = self.get_page(self.teacher)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn('id="comments"', response.content.decode())

    def test_the_remark_really_exists_while_the_page_is_empty_of_it(self):
        """The control for the exclusion below, and it runs first: a page that
        names no remark has two possible reasons, and this pins the one that is
        not the design."""
        self.write(self.teacher, "class_teacher", "A steady term.")

        body = self.child(self.teacher).json()

        self.assertEqual(
            [r["body"] for r in body["remarks"] if r["author"] == "class_teacher"],
            ["A steady term."],
        )

    def test_no_child_and_no_remark_is_named_in_the_frame(self):
        self.write(self.teacher, "class_teacher", "A steady term.")

        page = self.get_page(self.teacher).content.decode()

        for absent in ("Ada Obi", "A steady term.", "JSS 1A", "St Mary's"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_an_anonymous_caller_gets_the_frame_and_not_a_redirect(self):
        response = self.get_page(None)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="comments"', response.content.decode())

    def test_a_bursar_gets_the_frame_and_is_refused_by_the_route(self):
        """Where the authority lives. The page is the same document for
        everybody; the fetch inside it is what refuses her."""
        self.client.force_login(self.bursar.user)

        page = self.client.get(URL, HTTP_HOST=HOST)
        answer = self.client.get(
            f"/api/results/comments/?class_group_id={self.jss1a_id}", HTTP_HOST=HOST
        )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 403)

    def test_the_frame_names_the_portal_so_the_signed_out_state_can_offer_a_way_back(self):
        self.assertIn('data-portal="testserver"', self.get_page(self.teacher).content.decode())

    def test_with_no_portal_domain_the_attribute_is_empty_rather_than_wrong(self):
        """The pair the card page already has: this passes for a view that
        never sets the variable, and the test above is what refuses that."""
        Domain.objects.filter(tenant__schema_name="public").delete()

        self.assertIn('data-portal=""', self.get_page(self.teacher).content.decode())

    def test_the_stylesheet_and_entry_point_are_the_comments_pages_own(self):
        page = self.get_page(self.teacher).content.decode()

        self.assertIn(static("comments/comments.css"), page)
        self.assertIn(static("comments/app.js"), page)

    def test_the_portal_serves_the_frame_and_the_route_behind_it_404s(self):
        self.client.force_login(self.teacher.user)

        page = self.client.get(URL, HTTP_HOST=PORTAL)
        answer = self.client.get(
            f"/api/results/comments/?class_group_id={self.jss1a_id}", HTTP_HOST=PORTAL
        )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 404)
