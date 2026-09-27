"""The sidebar and the tab bar: a link only where its page will answer.

`menu.py` builds both from the roles of whoever is signed in. What is held
here is the one sentence that matters to the person using it: **no link in the
menu leads to "This page is not yours", and no page this login may open is
missing from it.** Both halves are asked of the real routes each page fetches
first, as the login in question, so the menu cannot pass while disagreeing
with a gate.

Two schools, and one person who is a teacher at the first and the principal at
the second: a menu keyed on the login rather than on the login *at this
school* would show her the principal's links on the teacher's school, and only
a fixture with both schools can see that.
"""

import re

from django.test import SimpleTestCase

import menu
from accounts.models import Role, User
from accounts.services import grant_membership
from results.tests.fixtures import HOST, PASSWORD, PORTAL, THEIR_HOST, ChainSetUp

#: The first thing each page asks the API, which is where its refusal comes
#: from. A page is "open to you" exactly when this answers 200.
FIRST_FETCH = {
    "home": "/api/home/",
    "register": "/api/attendance/where/",
    "marking": "/api/gradebook/where/",
    "comments": "/api/results/comments/classes/",
    "timetable": "/api/timetable/",
    "results": "/api/results/chain/",
    "broadsheet": "/api/results/broadsheets/",
    "absences": "/api/attendance/absences/",
    "fees": "/api/fees/classes/",
    "setup": "/api/academics/setup/",
    "roll": "/api/enrolment/roll/",
    "staff": "/api/schools/{slug}/invitations/",
}

TEACHER = {"register", "marking", "comments", "timetable", "results", "broadsheet"}
PRINCIPAL = {
    "home", "register", "marking", "comments", "timetable",
    "results", "broadsheet", "absences", "fees", "setup", "roll",
}

_SIDEBAR = re.compile(r'<nav id="sidebar".*?</nav>', re.S)
_TABBAR = re.compile(r'<nav class="tabbar".*?</nav>', re.S)
_HREF = re.compile(r'<a href="([^"]+)"')
_KEY_OF = {link.href: link.key for link in menu.LINKS}


class TheRulesTests(SimpleTestCase):
    def keys(self, roles, current="home"):
        return {link.key for link in menu.menu_for(roles, current).links}

    def test_every_page_has_a_first_fetch_to_be_checked_against(self):
        self.assertEqual(set(FIRST_FETCH), set(menu.BY_KEY))

    def test_a_teacher_sees_teacher_pages_and_nothing_else(self):
        self.assertEqual(self.keys({Role.TEACHER.value}), TEACHER)

    def test_two_roles_see_both_sets(self):
        both = self.keys({Role.TEACHER.value, Role.BURSAR.value})

        self.assertEqual(both, TEACHER | {"fees"})

    def test_signed_out_or_on_the_portal_is_no_menu_at_all(self):
        empty = menu.menu_for(frozenset(), "home")

        self.assertEqual((empty.links, empty.tabs, empty.home), ((), (), None))

    def test_a_parent_or_a_student_has_no_staff_menu(self):
        for role in (Role.PARENT, Role.STUDENT):
            with self.subTest(role=role):
                self.assertEqual(self.keys({role.value}), set())

    def test_each_roles_four_tabs_are_among_its_own_links(self):
        for role, tabs in menu.TABS.items():
            with self.subTest(role=role):
                self.assertEqual(len(tabs), 4)
                self.assertLessEqual(set(tabs), self.keys({role}))

    def test_the_page_you_are_on_is_always_a_tab(self):
        """A principal on the register (hers too) keeps it on the tab bar."""
        tabs = [link.key for link in menu.menu_for({Role.PRINCIPAL.value}, "register").tabs]

        self.assertEqual(tabs, ["home", "results", "broadsheet", "register"])

    def test_a_page_you_cannot_open_is_never_swapped_in(self):
        tabs = [link.key for link in menu.menu_for({Role.TEACHER.value}, "home").tabs]

        self.assertNotIn("home", tabs)

    def test_a_bursar_has_no_tab_bar_but_the_sidebar_still_lists_fees(self):
        bursar = menu.menu_for({Role.BURSAR.value}, "fees")

        self.assertEqual(bursar.tabs, ())
        self.assertEqual([link.key for link in bursar.links], ["fees"])
        self.assertEqual(bursar.home, "/fees/")

    def test_the_principal_leads_when_one_person_holds_both(self):
        tabs = [link.key for link in menu.menu_for({Role.TEACHER.value, Role.PRINCIPAL.value}, "home").tabs]

        self.assertEqual(tabs, list(menu.TABS[Role.PRINCIPAL.value]))


class EveryLinkOpensTests(ChainSetUp):
    """The menu against the real gates, as each login, at each school."""

    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )
        # A teacher at St Mary's who is the principal at Grace.
        tunde = User.objects.create_user("tunde-staff", PASSWORD, full_name="Tunde Oke")
        self.two_schools_teacher = grant_membership(tunde, self.stmarys, Role.TEACHER)
        self.two_schools_principal = grant_membership(tunde, self.grace, Role.PRINCIPAL)
        # A vice principal at St Mary's who also teaches there.
        self.both_here = grant_membership(self.vp.user, self.stmarys, Role.TEACHER)

    def shown(self, member, host=HOST):
        """The keys the sidebar and the tab bar link to, from a real page."""
        self.client.force_login(member.user)
        page = self.client.get("/results/", HTTP_HOST=host).content.decode()
        sidebar = {_KEY_OF[h] for h in _HREF.findall(_SIDEBAR.search(page).group(0))}
        tabbar = _TABBAR.search(page)
        tabs = {_KEY_OF[h] for h in _HREF.findall(tabbar.group(0))} if tabbar else set()
        return sidebar, tabs

    def opens(self, member, key, host, slug):
        self.client.force_login(member.user)
        return self.client.get(FIRST_FETCH[key].format(slug=slug), HTTP_HOST=host).status_code == 200

    def assert_menu_is_exactly_what_opens(self, member, host=HOST, slug="st-marys"):
        sidebar, tabs = self.shown(member, host)
        self.assertLessEqual(tabs, sidebar, "a tab that is not in the sidebar")
        for key in menu.BY_KEY:
            with self.subTest(member=member.user.username, host=host, page=key):
                opens = self.opens(member, key, host, slug)
                if key in sidebar:
                    self.assertTrue(opens, f"the menu links {key}, and it refuses this login")
                else:
                    self.assertFalse(opens, f"{key} opens for this login and the menu hides it")
        return sidebar

    def test_the_control_a_principal_really_has_a_full_menu(self):
        """Every exclusion below would pass against a menu that showed
        nothing to anybody."""
        self.assertEqual(self.assert_menu_is_exactly_what_opens(self.head), PRINCIPAL)

    def test_a_teacher_at_one_school_and_principal_at_another(self):
        here = self.assert_menu_is_exactly_what_opens(self.two_schools_teacher)
        there = self.assert_menu_is_exactly_what_opens(
            self.two_schools_principal, host=THEIR_HOST, slug="grace"
        )

        self.assertEqual(here, TEACHER, "St Mary's showed her more than a teacher's pages")
        self.assertEqual(there, PRINCIPAL, "Grace showed her less than a principal's pages")
        self.assertNotIn("home", here)

    def test_two_roles_at_one_school_see_both_sets(self):
        both = self.assert_menu_is_exactly_what_opens(self.both_here)

        self.assertLessEqual(TEACHER, both)
        self.assertIn("home", both, "the vice principal's own home is missing")

    def test_every_other_role_too(self):
        for member in (self.teacher, self.vp, self.bursar, self.admin):
            self.assert_menu_is_exactly_what_opens(member)

    def test_a_bursar_gets_no_tab_bar(self):
        sidebar, tabs = self.shown(self.bursar)

        self.assertEqual((sidebar, tabs), ({"fees"}, set()))

    def test_signed_out_there_is_no_menu(self):
        self.client.logout()
        page = self.client.get("/results/", HTTP_HOST=HOST).content.decode()

        self.assertEqual(_HREF.findall(_SIDEBAR.search(page).group(0)), [])
        self.assertIsNone(_TABBAR.search(page))
        self.assertNotIn("has-tabbar", page)

    def test_on_the_portal_there_is_no_menu(self):
        self.client.force_login(self.head.user)
        page = self.client.get("/results/", HTTP_HOST=PORTAL).content.decode()

        self.assertEqual(_HREF.findall(_SIDEBAR.search(page).group(0)), [])


class SignOutTests(ChainSetUp):
    """Sign out, in the menu, for every signed-in login: a staff-room computer
    is shared, and nobody could sign out once the page bodies lost the button."""

    def setUp(self):
        super().setUp()
        self.admin = grant_membership(
            User.objects.create_user("ade", PASSWORD, full_name="Ade Admin"), self.stmarys, Role.ADMIN
        )

    def page(self, client, path="/results/", host=HOST):
        return client.get(path, HTTP_HOST=host).content.decode()

    def test_every_role_is_offered_it_in_the_menu(self):
        for member in (self.head, self.vp, self.teacher, self.bursar, self.admin, self.children["ada"]):
            with self.subTest(role=member.role):
                self.client.force_login(member.user)
                sidebar = _SIDEBAR.search(self.page(self.client)).group(0)
                self.assertIn('<form class="nav nav-end" method="post" action="/sign-out/">', sidebar)
                self.assertIn('name="csrfmiddlewaretoken"', sidebar)
                self.assertIn(">Sign out</button>", sidebar)

    def test_nobody_signed_in_is_offered_it(self):
        self.client.logout()

        self.assertNotIn("/sign-out/", self.page(self.client))

    def csrf_client(self, member):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(member.user)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', self.page(client)).group(1)
        return client, token

    def signed_in(self, client):
        return client.get("/api/home/", HTTP_HOST=HOST).status_code != 401

    def test_it_signs_out_and_lands_on_the_staff_door(self):
        client, token = self.csrf_client(self.head)
        self.assertTrue(self.signed_in(client), "the control: signed in before")

        response = client.post(
            "/sign-out/", {"csrfmiddlewaretoken": token, "next": "/results/"}, HTTP_HOST=HOST
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"//{PORTAL}/staff-sign-in/")
        self.assertFalse(self.signed_in(client))

    def test_without_the_token_nobody_is_signed_out(self):
        """Another origin must not be able to end a teacher's session."""
        client, _ = self.csrf_client(self.head)

        response = client.post("/sign-out/", {}, HTTP_HOST=HOST)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.signed_in(client))

    def test_a_link_or_a_prefetch_cannot_sign_anybody_out(self):
        client, _ = self.csrf_client(self.head)

        self.assertEqual(client.get("/sign-out/", HTTP_HOST=HOST).status_code, 405)
        self.assertTrue(self.signed_in(client))

    def test_with_no_portal_it_goes_back_to_the_page_and_nowhere_else(self):
        from schools.models import Domain

        Domain.objects.filter(tenant__schema_name="public").delete()
        for asked, landed in (
            ("/results/", "/results/"),
            ("//evil.example/steal/", "/"),
            ("https://evil.example/", "/"),
        ):
            with self.subTest(next=asked):
                client, token = self.csrf_client(self.head)
                response = client.post(
                    "/sign-out/", {"csrfmiddlewaretoken": token, "next": asked}, HTTP_HOST=HOST
                )
                self.assertEqual(response["Location"], landed)
