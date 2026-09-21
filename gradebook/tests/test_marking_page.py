"""The marking page: a frame, and not one mark in it.

Three claims, the same three the register page makes and for the same reasons.

**It is a shell.** The frame holds no child, no class and no mark; the view
reads one row — the portal's hostname — and nothing else.

**It is served to whoever opens the URL.** No `login_required`: a redirect on a
guessable URL is an oracle answering "this school exists and here is its
gradebook". The fetch inside the page meets the authority question.

**The portal serves the frame too**, because `urls_public.py` splats the tenant
patterns in — exactly as it already does for `/cards/` and `/register/`. Every
route the page calls begins with `_school_of()`, which 404s there.

The flow itself — blur saving, the conflict note, the locked sheet — is in
`tests/js/marking.test.js` under `node --test`.
"""

from django.templatetags.static import static

from gradebook.tests.fixtures import MarkingSetUp
from schools.models import Domain, School

HOST = "st-marys.testserver"


class TheMarkingFrameHoldsNoMarksTests(MarkingSetUp):
    def setUp(self):
        super().setUp()
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

    def get_page(self, user=None, host=HOST):
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get("/marking/", HTTP_HOST=host)

    def test_a_schools_own_host_serves_it(self):
        response = self.get_page(self.teacher.user)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn('id="marking"', response.content.decode())

    def test_the_roster_really_exists_while_the_page_is_empty_of_it(self):
        """The control for the exclusion below, and it runs first: a page that
        names no child has two possible reasons, and this pins the one that is
        not the design."""
        self.client.force_login(self.teacher.user)

        body = self.client.get(
            f"/api/gradebook/assessments/{self.first_ca_id}/sheet/"
            f"?class_group_id={self.jss1a_id}",
            HTTP_HOST=HOST,
        ).json()

        self.assertEqual(len(body["rows"]), 4, "the class is empty, so nothing is excluded")
        self.assertIn("Ada Obi", [row["student"] for row in body["rows"]])

    def test_no_child_and_no_class_is_named_in_the_frame(self):
        page = self.get_page(self.teacher.user).content.decode()

        for absent in ("Ada Obi", "Bimpe Ojo", "JSS 1A", "Mathematics", "St Mary's"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_an_anonymous_caller_gets_the_frame_and_not_a_redirect(self):
        response = self.get_page(None)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="marking"', response.content.decode())

    def test_a_bursar_gets_the_frame_and_is_refused_by_the_route(self):
        """Where the authority lives. The page is the same document for
        everybody; the fetch inside it is what refuses her."""
        self.client.force_login(self.bursar.user)

        page = self.client.get("/marking/", HTTP_HOST=HOST)
        answer = self.client.get("/api/gradebook/where/", HTTP_HOST=HOST)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 403)

    def test_the_frame_names_the_portal_so_the_signed_out_state_can_offer_a_way_back(self):
        page = self.get_page(self.teacher.user).content.decode()

        self.assertIn('data-portal="testserver"', page)

    def test_with_no_portal_domain_the_attribute_is_empty_rather_than_wrong(self):
        """The pair the card page already has: this passes for a view that
        never sets the variable, and the test above is what refuses that."""
        Domain.objects.filter(tenant__schema_name="public").delete()

        self.assertIn('data-portal=""', self.get_page(self.teacher.user).content.decode())

    def test_the_stylesheet_and_entry_point_are_the_marking_pages_own(self):
        page = self.get_page(self.teacher.user).content.decode()

        self.assertIn(static("marking/marking.css"), page)
        self.assertIn(static("marking/app.js"), page)

    def test_the_portal_serves_the_frame_and_the_route_behind_it_404s(self):
        self.client.force_login(self.teacher.user)

        page = self.client.get("/marking/", HTTP_HOST="testserver")
        answer = self.client.get("/api/gradebook/where/", HTTP_HOST="testserver")

        self.assertEqual(page.status_code, 200)
        self.assertEqual(answer.status_code, 404)
