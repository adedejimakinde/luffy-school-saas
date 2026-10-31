"""The website editor, its preview and "Ready for the principal", at two schools. `docs/school-sites.md` PR 4.

- **Only the principal and the administrator open it**, and the administrator
  edits only while the principal allows it. A vice principal, a teacher, a
  bursar, a parent and a child are refused on the read and on every write, and
  a refused write changes nothing. Another school's principal is refused on
  this school's host.
- **Only the principal publishes, rolls back, sets the colour or the delegation.**
  A publish names the draft the principal confirmed, so a change made after is
  not published unseen.
- **The preview is the draft, for editors only, and never public**: signed out is
  sent to the staff sign-in and back, a non-editor is refused, it is `noindex`
  and `no-store`, it shows pages switched off with the bar saying so, its links
  stay inside it, and looking at it changes nothing.
- **"Ready for the principal" emails this school's principals, and nobody else's**,
  after the mark commits, with a link to this school's preview; when no
  principal has an address, the editor is told.
"""

import re
from urllib.parse import unquote

from django.core import mail

from accounts.models import Role, User
from accounts.services import grant_membership
from schools.tests.tenants import connected_to

from schoolsite import services
from schoolsite.models import Page, Section, SiteRevision, SiteSettings

from .test_public import GRACE, PORTAL, ST_MARYS, PublicSiteSetUp

BASE = "/api/website/"
PASSWORD = "a-long-password-1"


class EditorSetUp(PublicSiteSetUp):
    def setUp(self):
        super().setUp()
        User.objects.filter(pk=self.principal.pk).update(email="principal@stmarys.example")
        self.principal.refresh_from_db()
        User.objects.filter(pk=self.grace_principal.pk).update(email="principal@grace.example")
        self.admin = self.member("ade", Role.ADMIN, "Ade Bello")
        self.others = {
            role.value: self.member(f"st-marys-{role.value}", role)
            for role in (Role.VICE_PRINCIPAL_ACADEMIC, Role.TEACHER, Role.BURSAR, Role.PARENT, Role.STUDENT)
        }

    def member(self, username, role, full_name=""):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name or username)
        grant_membership(user, self.stmarys, role)
        return user

    def call(self, method, path, who=None, host=ST_MARYS, query="", **body):
        if who is None:
            self.client.logout()
        else:
            self.client.force_login(who)
        kwargs = {"HTTP_HOST": host}
        if body:
            kwargs.update(data=body, content_type="application/json")
        return getattr(self.client, method)(f"{BASE}{path}{query}", **kwargs)

    def overview(self, who=None, host=ST_MARYS):
        return self.call("get", "", who or self.principal, host=host)

    def delegate(self, on=True):
        with connected_to(self.stmarys):
            services.set_delegation_as(self.principal, self.stmarys, on)

    def versions(self):
        with connected_to(self.stmarys):
            return {p.key or p.slug: p.version for p in Page.objects.all()}, SiteSettings.objects.get(pk=1).version

    def draft(self, school=None):
        with connected_to(school or self.stmarys):
            return services.snapshot(), SiteSettings.objects.get(pk=1).draft_version


class WhoMayOpenTheEditorTests(EditorSetUp):
    def test_the_principal_opens_it_with_everything(self):
        body = self.overview().json()
        self.assertEqual((body["role"], body["can_edit"], body["can_publish"]), ("principal", True, True))
        self.assertEqual([p["ref"] for p in body["pages"]], ["home", "about", "admissions", "news", "gallery", "contact"])
        self.assertEqual(body["state"]["published"], False)
        self.assertEqual(body["preview"], "/website/preview/")

    def test_the_administrator_opens_it_and_edits_only_while_allowed(self):
        body = self.overview(self.admin).json()
        self.assertEqual((body["can_edit"], body["can_publish"], body["pages"]), (False, False, []))
        self.delegate(True)
        body = self.overview(self.admin).json()
        self.assertEqual((body["can_edit"], body["can_publish"]), (True, False))
        self.assertEqual(len(body["pages"]), 6)

    def test_nobody_else_at_the_school_and_no_other_schools_principal_opens_it(self):
        for name, who in self.others.items():
            with self.subTest(who=name):
                self.assertEqual(self.overview(who).status_code, 403)
        self.assertEqual(self.overview(self.grace_principal).status_code, 403)
        self.assertEqual(self.overview(self.grace_teacher, host=GRACE).status_code, 403)
        self.assertEqual(self.call("get", "", None).status_code, 401)

    def test_the_portal_and_classnodes_own_site_have_no_editor(self):
        self.assertEqual(self.overview(host=PORTAL).status_code, 404)

    def test_every_write_is_refused_the_same_way_to_everybody_else_and_changes_nothing(self):
        with connected_to(self.stmarys):
            section = services.add_section_as(self.principal, self.stmarys, "home",
                                              version=Page.objects.get(key="home").version, kind="admissions_cta",
                                              data={"heading": "Places"})
        before = self.draft()
        versions, settings_version = self.versions()
        routes = [
            ("post", "pages/", {"version": settings_version, "title": "Sports"}),
            ("put", "pages/about/", {"version": versions["about"], "enabled": True}),
            ("delete", "pages/about/", {}),
            ("put", "menu/", {"version": settings_version, "order": ["home"]}),
            ("post", "pages/home/sections/", {"version": versions["home"], "kind": "text", "data": {"body": "x"}}),
            ("put", "pages/home/sections/", {"version": versions["home"], "order": [section.pk]}),
            ("put", f"sections/{section.pk}/", {"version": section.version, "data": {"heading": "x"}}),
            ("delete", f"sections/{section.pk}/", {}),
            ("put", "footer/", {"version": settings_version, "footer": {}}),
            ("put", "colour/", {"version": settings_version, "colour": "#143D8C"}),
            ("put", "delegation/", {"on": True}),
            ("post", "ready/", {"note": ""}),
            ("post", "publish/", {"draft_version": before[1], "note": ""}),
            ("post", "rollback/", {"number": 1, "note": ""}),
        ]
        refusals = set()
        for who in [*self.others.values(), self.admin, self.grace_principal]:
            for method, path, body in routes:
                with self.subTest(who=who.username, route=f"{method} {path}"):
                    query = "?version=1" if method == "delete" else ""
                    response = self.call(method, path, who, query=query, **body)
                    self.assertEqual(response.status_code, 403)
                    # Another school's principal is turned away by `SchoolAccessMiddleware`
                    # before the API is reached; the school's own people get the API's one sentence.
                    if who is not self.grace_principal:
                        refusals.add(response.content)
        self.assertEqual(len(refusals), 1, "one sentence for every refusal of a person")
        self.assertEqual(self.draft(), before)
        with connected_to(self.stmarys):
            self.assertFalse(SiteRevision.objects.exists())

    def test_a_refusal_does_not_say_whether_the_page_or_section_exists(self):
        for path in ("pages/about/", "pages/no-such-page/", "sections/1/", "sections/999999/"):
            with self.subTest(path=path):
                self.assertEqual(self.call("delete", path, self.others["teacher"], query="?version=0").status_code, 403)


class TheDelegatedAdministratorTests(EditorSetUp):
    def setUp(self):
        super().setUp()
        self.delegate(True)

    def test_edits_the_draft_and_never_publishes_rolls_back_or_sets_the_colour_or_delegation(self):
        versions, settings_version = self.versions()
        self.assertEqual(self.call("post", "pages/", self.admin, version=settings_version, title="Boarding").status_code, 200)
        body = self.call("post", "pages/boarding/sections/", self.admin, version=self.versions()[0]["boarding"],
                         kind="text", data={"body": "Two houses."}).json()
        self.assertEqual([s["kind"] for s in body["pages"][-1]["sections"]], ["text"])
        for method, path, payload in (
            ("post", "publish/", {"draft_version": body["state"]["draft_version"]}),
            ("post", "rollback/", {"number": 1}),
            ("put", "colour/", {"version": body["version"], "colour": "#143D8C"}),
            ("put", "delegation/", {"on": False}),
        ):
            with self.subTest(route=path):
                self.assertEqual(self.call(method, path, self.admin, **payload).status_code, 403)

    def test_once_the_principal_stops_it_the_administrator_is_refused_on_the_next_request(self):
        self.delegate(False)
        _, settings_version = self.versions()
        self.assertEqual(self.call("post", "pages/", self.admin, version=settings_version, title="Boarding").status_code, 403)


class ThePrincipalsWorkTests(EditorSetUp):
    def test_build_a_page_publish_it_and_go_back(self):
        _, v = self.versions()
        body = self.call("post", "pages/", self.principal, version=v, title="Boarding").json()
        boarding = next(p for p in body["pages"] if p["ref"] == "boarding")
        self.assertEqual(boarding["preview"], "/website/preview/pages/boarding/")
        self.assertEqual([k["kind"] for k in boarding["kinds"] if k["available"]],
                         ["hero", "principal_message", "facts", "admissions_cta", "text"])
        self.assertEqual([k["kind"] for k in boarding["kinds"] if not k["available"]], ["gallery"])
        body = self.call("post", "pages/boarding/sections/", self.principal, version=boarding["version"],
                         kind="text", data={"body": "Two houses."}).json()
        boarding = next(p for p in body["pages"] if p["ref"] == "boarding")
        body = self.call("put", "pages/boarding/", self.principal, version=boarding["version"], enabled=True).json()
        self.assertTrue(body["state"]["changes"])
        body = self.call("post", "publish/", self.principal, draft_version=body["state"]["draft_version"],
                         note="Boarding page").json()
        self.assertEqual((body["state"]["published"], body["state"]["revision"], body["state"]["changes"]), (True, 1, False))
        self.assertEqual(self.get("/pages/boarding/").status_code, 200)
        self.assertEqual(body["log"][0]["note"], "Boarding page")
        # Change, publish again, and go back to version 1.
        home = next(p for p in body["pages"] if p["ref"] == "home")
        body = self.call("post", "pages/home/sections/", self.principal, version=home["version"],
                         kind="admissions_cta", data={"heading": "Places"}).json()
        body = self.call("post", "publish/", self.principal, draft_version=body["state"]["draft_version"]).json()
        self.assertEqual(body["state"]["revision"], 2)
        body = self.call("post", "rollback/", self.principal, number=1, note="Too soon").json()
        self.assertEqual(body["state"]["revision"], 3)
        self.assertEqual(body["log"][0]["kind"], "rolled_back")

    def test_a_publish_refuses_a_draft_changed_since_the_principal_confirmed(self):
        body = self.overview().json()
        confirmed = body["state"]["draft_version"]
        home = body["pages"][0]
        self.call("post", "pages/home/sections/", self.principal, version=home["version"], kind="admissions_cta",
                  data={"heading": "Places"})
        response = self.call("post", "publish/", self.principal, draft_version=confirmed)
        self.assertEqual(response.status_code, 409)
        with connected_to(self.stmarys):
            self.assertFalse(SiteRevision.objects.exists())

    def test_a_stale_save_is_a_409_and_a_refused_value_a_422_with_the_schools_sentence(self):
        body = self.overview().json()
        about = body["pages"][1]
        self.call("put", "pages/about/", self.principal, version=about["version"], enabled=True)
        stale = self.call("put", "pages/about/", self.principal, version=about["version"], enabled=False)
        self.assertEqual(stale.status_code, 409)
        self.assertIn("Somebody else changed this", stale.json()["detail"])
        refused = self.call("post", "pages/", self.principal, version=self.versions()[1], title="X", slug="register")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("kept for the site's own pages", refused.json()["detail"])

    def test_news_and_gallery_are_coming_soon_and_cannot_be_added(self):
        versions, _ = self.versions()
        response = self.call("post", "pages/home/sections/", self.principal, version=versions["home"],
                             kind="news", data={"count": 3})
        self.assertEqual(response.status_code, 422)
        self.assertIn("Coming soon", response.json()["detail"])
        kinds = {k["kind"]: k for k in self.overview().json()["pages"][0]["kinds"]}
        self.assertFalse(kinds["news"]["available"])
        self.assertFalse(kinds["gallery"]["available"])
        self.assertTrue(kinds["hero"]["available"])

    def test_the_colour_must_carry_white_writing_and_can_go_back_to_the_cards(self):
        _, v = self.versions()
        self.assertEqual(self.call("put", "colour/", self.principal, version=v, colour="#143d8c").json()["colour"], "#143D8C")
        _, v = self.versions()
        light = self.call("put", "colour/", self.principal, version=v, colour="#FFFF66")
        self.assertEqual(light.status_code, 422)
        self.assertIn("too light", light.json()["detail"])
        self.assertEqual(self.call("put", "colour/", self.principal, version=v, colour="").json()["colour"], "")

    def test_the_footer_and_the_menu_order(self):
        _, v = self.versions()
        body = self.call("put", "footer/", self.principal, version=v, footer={
            "address_line": "Off Ring Road", "social": [{"network": "facebook", "url": "https://facebook.com/stm"}]}).json()
        self.assertEqual(body["footer"]["address_line"], "Off Ring Road")
        order = ["home", "contact", "about", "admissions", "news", "gallery"]
        body = self.call("put", "menu/", self.principal, version=body["version"], order=order).json()
        self.assertEqual([p["ref"] for p in body["pages"]], order)


class ThePreviewTests(EditorSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            services.create_page_as(self.principal, self.stmarys, version=0, title="Boarding")
            services.add_section_as(self.principal, self.stmarys, "boarding",
                                    version=Page.objects.get(slug="boarding").version, kind="text",
                                    data={"body": "Two houses, in the draft."})
            services.add_section_as(self.principal, self.stmarys, "home", version=Page.objects.get(key="home").version,
                                    kind="hero", data={"heading": "Welcome, in the draft",
                                                       "buttons": [{"label": "Boarding", "link": "/pages/boarding/"},
                                                                   {"label": "Apply", "link": "https://example.com/apply"}]})
            services.save_page_as(self.principal, self.stmarys, "boarding",
                                  version=Page.objects.get(slug="boarding").version, enabled=True)

    def preview(self, path="/website/preview/", who=None, host=ST_MARYS):
        if who is None:
            self.client.logout()
        else:
            self.client.force_login(who)
        return self.client.get(path, HTTP_HOST=host)

    def test_signed_out_goes_to_the_staff_sign_in_and_back(self):
        response = self.preview("/website/preview/pages/boarding/")
        self.assertEqual(response.status_code, 302)
        door, back = response["Location"].split("?next=")
        self.assertEqual(door, f"//{PORTAL}/staff-sign-in/")
        self.assertEqual(unquote(back), f"http://{ST_MARYS}/website/preview/pages/boarding/")

    def test_somebody_who_may_not_edit_is_refused_with_the_portals_403(self):
        for who in [*self.others.values(), self.admin]:
            with self.subTest(who=who.username):
                self.assertEqual(self.preview(who=who).status_code, 403)
        self.assertEqual(self.preview(who=self.grace_principal).status_code, 403)
        self.delegate(True)
        self.assertEqual(self.preview(who=self.admin).status_code, 200)

    def test_it_draws_the_draft_never_indexed_never_stored_and_changes_nothing(self):
        before = self.draft()
        response = self.preview(who=self.principal)
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Welcome, in the draft", html)
        self.assertIn("Preview: not published", html)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("noindex", response["X-Robots-Tag"])
        self.assertIn('<meta name="robots" content="noindex, nofollow">', html)
        self.assertIn("script-src 'none'", response["Content-Security-Policy"])
        self.assertNotIn('<script type="application/ld+json">', html)
        self.assertEqual(self.draft(), before)
        # And the public site still shows nothing of it: nothing is published.
        self.assertNotIn("in the draft", self.get("/").content.decode())

    def test_links_to_the_sites_own_pages_stay_inside_the_preview(self):
        html = self.preview(who=self.principal).content.decode()
        self.assertIn('href="/website/preview/pages/boarding/">Boarding</a>', html)
        self.assertIn('href="https://example.com/apply">Apply</a>', html)
        nav = re.findall(r'<a href="([^"]+)"', html.split("<nav")[1].split("</nav>")[0])
        self.assertEqual(nav, ["/website/preview/", "/website/preview/pages/boarding/"])
        self.assertIn('class="school" href="/website/preview/"', html)

    def test_a_page_switched_off_is_shown_with_the_bar_saying_so(self):
        html = self.preview("/website/preview/about/", who=self.principal).content.decode()
        self.assertIn("This page is switched off", html)
        self.assertNotIn("switched off", self.preview(who=self.principal).content.decode())

    def test_a_page_the_draft_does_not_have_is_a_404(self):
        for path in ("/website/preview/pages/sports/", "/website/preview/home/", "/website/preview/nowhere/"):
            with self.subTest(path=path):
                self.assertEqual(self.preview(path, who=self.principal).status_code, 404)

    def test_one_schools_draft_is_never_previewed_on_anothers_host(self):
        with connected_to(self.grace):
            services.add_section_as(self.grace_principal, self.grace, "home",
                                    version=Page.objects.get(key="home").version, kind="hero",
                                    data={"heading": "Grace's own draft"})
        mine = self.preview(who=self.principal).content.decode()
        self.assertNotIn("Grace's own draft", mine)
        self.assertEqual(self.preview(who=self.principal, host=GRACE).status_code, 403)
        theirs = self.preview(who=self.grace_principal, host=GRACE).content.decode()
        self.assertIn("Grace&#x27;s own draft", theirs)
        self.assertNotIn("in the draft", theirs)

    def test_the_editors_frame_is_never_indexed(self):
        response = self.preview("/website/", who=self.principal)
        self.assertEqual(response.status_code, 200)
        self.assertIn("noindex", response["X-Robots-Tag"])
        self.assertIn('id="website-editor"', response.content.decode())


class ReadyForThePrincipalTests(EditorSetUp):
    def setUp(self):
        super().setUp()
        self.delegate(True)
        versions, _ = self.versions()
        self.call("post", "pages/home/sections/", self.admin, version=versions["home"], kind="admissions_cta",
                  data={"heading": "Places"})

    def ready(self, note="Please check the new home page"):
        with self.captureOnCommitCallbacks(execute=True):
            return self.call("post", "ready/", self.admin, note=note)

    def test_this_schools_principal_and_only_this_schools_is_emailed_a_link_to_the_preview(self):
        second = User.objects.create_user("second-head", PASSWORD, full_name="Mrs Second", email="second@stmarys.example")
        grant_membership(second, self.stmarys, Role.PRINCIPAL)
        body = self.ready().json()
        self.assertEqual(body["told"], 2)
        self.assertTrue(body["state"]["ready"])
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["principal@stmarys.example", "second@stmarys.example"])
        for message in mail.outbox:
            self.assertEqual(len(message.to), 1, "each principal is sent their own")
            self.assertIn(f"https://{ST_MARYS}/website/preview/", message.body)
            self.assertIn("Ade Bello", message.body)
            self.assertIn("Please check the new home page", message.body)
            self.assertNotIn("grace", " ".join(message.to + [message.body]).lower())

    def test_when_no_principal_has_an_address_the_administrator_is_told_and_nothing_is_sent(self):
        User.objects.filter(pk=self.principal.pk).update(email="")
        body = self.ready().json()
        self.assertEqual((body["told"], body["state"]["ready"]), (0, True))
        self.assertEqual(mail.outbox, [])

    def test_a_mark_that_is_refused_sends_nothing(self):
        self.ready()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            again = self.call("post", "ready/", self.admin, note="")
        self.assertEqual(again.status_code, 422)
        self.assertEqual(mail.outbox, [])

    def test_the_principal_marking_their_own_draft_emails_nobody(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.call("post", "ready/", self.principal, note="")
        self.assertEqual(mail.outbox, [])
