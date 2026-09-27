"""The home page: a frame, and not one figure in it.

The claims every staff frame makes: it is a shell, it is served to whoever
opens the URL, and the route behind it is what refuses. What it draws is in
`tests/js/home.test.js` under `node --test`.
"""

from django.templatetags.static import static

from results.tests.fixtures import HOST, ChainSetUp

URL = "/home/"


class TheHomeFrameHoldsNoFiguresTests(ChainSetUp):
    def get_page(self, member=None):
        if member is not None:
            self.client.force_login(member.user)
        else:
            self.client.logout()
        return self.client.get(URL, HTTP_HOST=HOST)

    def test_a_schools_own_host_serves_it(self):
        response = self.get_page(self.head)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="home"', response.content.decode())

    def test_no_school_class_or_figure_is_named_in_the_frame(self):
        page = self.get_page(self.head).content.decode()

        for absent in ("JSS 1A", "St Mary's", "Ada Obi", "₦"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)

    def test_an_anonymous_caller_gets_the_frame_and_not_a_redirect(self):
        """A `login_required` would make the URL an oracle."""
        self.assertEqual(self.get_page(None).status_code, 200)

    def test_a_bursar_gets_the_frame_and_is_refused_by_the_route(self):
        self.client.force_login(self.bursar.user)

        self.assertEqual(self.client.get(URL, HTTP_HOST=HOST).status_code, 200)
        self.assertEqual(self.client.get("/api/home/", HTTP_HOST=HOST).status_code, 403)

    def test_the_shell_names_the_four_leadership_screens_with_home_current(self):
        page = self.get_page(self.head).content.decode()

        for href in ("/home/", "/results/", "/broadsheet/", "/absences/"):
            with self.subTest(href=href):
                # Once in the sidebar, once in the tab bar.
                self.assertEqual(page.count(f'<a href="{href}"'), 2)
        self.assertEqual(page.count('<a href="/home/" aria-current="page">'), 2)
        self.assertIn('<svg class="logo-mark"><use href="#i-brand-mark"/></svg>classnode', page)

    def test_the_stylesheet_and_entry_point_are_the_home_pages_own(self):
        page = self.get_page(self.head).content.decode()

        self.assertIn(static("home/home.css"), page)
        self.assertIn(static("home/app.js"), page)
