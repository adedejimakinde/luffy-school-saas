"""A school's website draft, its publishing and its record, at two schools.

`docs/school-sites.md` PR 2. Who may do what (`schoolsite.access`), that one
school can never see, change or publish another's, that a stale save is refused,
that every publish and rollback writes exactly one log line naming who did it,
that what was published never changes, and that the draft holds only what
`schoolsite.sections` and `schoolsite.themes` let through.
"""

from django.contrib.auth.models import AnonymousUser
from django.db import connection, transaction
from django.test import TestCase

from accounts.models import MembershipStatus, Role, User
from accounts.services import grant_membership
from schools.tests.tenants import connected_to, make_school
from tests.refusals import RefusalAssertions

from schoolsite import services
from schoolsite.errors import (
    NotAllowed,
    NotAllowedToEdit,
    NotAllowedToPublish,
    NotAllowedToReadLog,
    SiteRefused,
    StaleDraft,
)
from schoolsite.models import (
    Page,
    RecordIsFixed,
    Section,
    SiteDelegationEvent,
    SitePublishEvent,
    SiteRevision,
    SiteSettings,
)
from schoolsite.sections import SectionRefused, clean_link
from schoolsite.themes import ThemeRefused

HERO = {"heading": "Welcome to St Mary's", "subheading": "A school for every child"}
MOTTO = {"motto": "Lux et veritas", "language": "la", "translation": "Light and truth", "founded": 1962}


def user(username, full_name=""):
    return User.objects.create_user(username, "a-long-password-1", full_name=full_name)


class SiteSetUp(RefusalAssertions, TestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's College", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.principal = user("principal", "Rev. Sr. Ngozi Okafor")
        self.admin = user("admin", "Tunde Bello")
        self.grace_principal = user("grace-principal", "Dr Amina Yusuf")
        grant_membership(self.principal, self.stmarys, Role.PRINCIPAL)
        grant_membership(self.admin, self.stmarys, Role.ADMIN)
        grant_membership(self.grace_principal, self.grace, Role.PRINCIPAL)
        self.others = {}
        for role in (Role.TEACHER, Role.BURSAR, Role.VICE_PRINCIPAL_ACADEMIC, Role.PARENT, Role.STUDENT):
            somebody = user(f"st-marys-{role.value}")
            grant_membership(somebody, self.stmarys, role)
            self.others[role.value] = somebody

    def tearDown(self):
        connection.set_schema_to_public()

    # -- helpers, each on the school's own schema ----------------------------

    def draft(self, school=None):
        with connected_to(school or self.stmarys):
            return services.snapshot()

    def page_version(self, key="home", school=None):
        with connected_to(school or self.stmarys):
            return Page.objects.get(key=key).version

    def settings_row(self, school=None):
        with connected_to(school or self.stmarys):
            return SiteSettings.objects.get(pk=1)

    def counts(self, school=None):
        with connected_to(school or self.stmarys):
            return (
                Section.objects.count(),
                SiteRevision.objects.count(),
                SitePublishEvent.objects.count(),
                SiteDelegationEvent.objects.count(),
                SiteSettings.objects.get(pk=1).draft_version,
            )

    def add(self, who, kind="hero", data=None, key="home", school=None, variant=None):
        school = school or self.stmarys
        with connected_to(school):
            version = Page.objects.get(key=key).version
            return services.add_section_as(
                who, school, key, version=version, kind=kind, data=HERO if data is None else data, variant=variant
            )

    def publish(self, who, school=None, note=""):
        school = school or self.stmarys
        with connected_to(school):
            return services.publish_as(who, school, note)

    def delegate(self, on=True):
        with connected_to(self.stmarys):
            return services.set_delegation_as(self.principal, self.stmarys, on)


class EveryNewSchoolStartsWithTheSameDraftTests(SiteSetUp):
    def test_six_pages_only_home_on_and_nothing_published_at_both_schools(self):
        for school in (self.stmarys, self.grace):
            with self.subTest(school=school.name), connected_to(school):
                pages = {p.key: p.enabled for p in Page.objects.all()}
                self.assertEqual(
                    pages,
                    {"home": True, "about": False, "admissions": False, "news": False,
                     "gallery": False, "contact": False},
                )
                self.assertEqual(SiteSettings.objects.get(pk=1).theme, "modern")
                self.assertIsNone(services.live_revision(school))


class WhoMayDoWhatTests(SiteSetUp):
    def test_the_principal_edits_marks_ready_publishes_and_rolls_back(self):
        self.add(self.principal)
        with connected_to(self.stmarys):
            services.mark_ready_as(self.principal, self.stmarys)
        first = self.publish(self.principal)
        self.add(self.principal, "crest_motto", MOTTO)
        self.publish(self.principal)
        with connected_to(self.stmarys):
            back = services.rollback_as(self.principal, self.stmarys, first.number)
        self.assertEqual(back.rollback_of_id, first.pk)

    def test_an_administrator_not_delegated_changes_nothing_but_reads_the_log(self):
        before = self.counts()
        with connected_to(self.stmarys):
            with self.assertRaises(NotAllowedToEdit):
                services.add_section_as(self.admin, self.stmarys, "home", version=0, kind="hero", data=HERO)
            with self.assertRaises(NotAllowedToEdit):
                services.draft_as(self.admin, self.stmarys)
            with self.assertRaises(NotAllowedToEdit):
                services.mark_ready_as(self.admin, self.stmarys)
            self.assertEqual(services.publish_log_as(self.admin, self.stmarys)["events"], [])
        self.assertEqual(self.counts(), before)

    def test_delegated_the_administrator_edits_drafts_and_marks_ready_and_never_publishes(self):
        self.delegate(True)
        section = self.add(self.admin)
        with connected_to(self.stmarys):
            services.save_section_as(self.admin, self.stmarys, section.pk, version=section.version,
                                     data={**HERO, "heading": "Welcome"})
            ready = services.mark_ready_as(self.admin, self.stmarys)
            self.assertEqual((ready.by_id, ready.by_role), (self.admin.pk, "admin"))
            before = self.counts()
            with self.assertRaises(NotAllowedToPublish):
                services.publish_as(self.admin, self.stmarys)
            with self.assertRaises(NotAllowedToPublish):
                services.rollback_as(self.admin, self.stmarys, 1)
            with self.assertRaises(NotAllowedToPublish):
                services.set_theme_as(self.admin, self.stmarys, "modern", version=0)
            with self.assertRaises(NotAllowedToPublish):
                services.set_delegation_as(self.admin, self.stmarys, False)
            self.assertEqual(self.counts(), before)
            self.assertTrue(SiteSettings.objects.get(pk=1).is_ready)

    def test_ending_the_delegation_takes_effect_on_the_next_call_without_signing_out(self):
        self.delegate(True)
        self.add(self.admin)
        self.delegate(False)
        before = self.counts()
        with connected_to(self.stmarys), self.assertRaises(NotAllowedToEdit):
            services.add_section_as(self.admin, self.stmarys, "about", version=self.page_version("about"),
                                    kind="text", data={"body": "Founded in 1962."})
        self.assertEqual(self.counts(), before)

    def test_nobody_else_writes_reads_the_draft_or_reads_the_log(self):
        self.delegate(True)
        refused = [*self.others.values(), AnonymousUser()]
        before = self.counts()
        for who in refused:
            with self.subTest(who=str(who)), connected_to(self.stmarys):
                with self.assertRaises(NotAllowedToEdit):
                    services.add_section_as(who, self.stmarys, "home", version=0, kind="hero", data=HERO)
                with self.assertRaises(NotAllowedToEdit):
                    services.save_page_as(who, self.stmarys, "about", version=0, enabled=True)
                with self.assertRaises(NotAllowedToEdit):
                    services.save_footer_as(who, self.stmarys, {}, version=0)
                with self.assertRaises(NotAllowedToEdit):
                    services.mark_ready_as(who, self.stmarys)
                with self.assertRaises(NotAllowedToEdit):
                    services.draft_as(who, self.stmarys)
                with self.assertRaises(NotAllowedToPublish):
                    services.publish_as(who, self.stmarys)
                with self.assertRaises(NotAllowedToPublish):
                    services.set_theme_as(who, self.stmarys, "modern", version=0)
                with self.assertRaises(NotAllowedToPublish):
                    services.set_delegation_as(who, self.stmarys, False)
                with self.assertRaises(NotAllowedToReadLog):
                    services.publish_log_as(who, self.stmarys)
        self.assertEqual(self.counts(), before)

    def test_a_suspended_or_invited_principal_can_do_nothing(self):
        for status in (MembershipStatus.SUSPENDED, MembershipStatus.INVITED):
            somebody = user(f"principal-{status}")
            grant_membership(somebody, self.stmarys, Role.PRINCIPAL, status=status)
            with self.subTest(status=status), connected_to(self.stmarys):
                with self.assertRaises(NotAllowedToEdit):
                    services.add_section_as(somebody, self.stmarys, "home", version=0, kind="hero", data=HERO)
                with self.assertRaises(NotAllowedToPublish):
                    services.publish_as(somebody, self.stmarys)


class OneSchoolNeverReachesAnothersTests(SiteSetUp):
    def test_st_marys_principal_cannot_see_edit_or_publish_grace_on_graces_own_schema(self):
        self.add(self.grace_principal, school=self.grace)
        before = self.counts(self.grace)
        with connected_to(self.grace):
            with self.assertRaises(NotAllowedToEdit):
                services.draft_as(self.principal, self.grace)
            with self.assertRaises(NotAllowedToEdit):
                services.add_section_as(self.principal, self.grace, "home", version=1, kind="crest_motto", data=MOTTO)
            with self.assertRaises(NotAllowedToPublish):
                services.publish_as(self.principal, self.grace)
            with self.assertRaises(NotAllowedToPublish):
                services.set_delegation_as(self.principal, self.grace, True)
            with self.assertRaises(NotAllowedToReadLog):
                services.publish_log_as(self.principal, self.grace)
        self.assertEqual(self.counts(self.grace), before)

    def test_naming_its_own_school_from_anothers_schema_is_refused_and_writes_nowhere(self):
        before = (self.counts(self.stmarys), self.counts(self.grace))
        with connected_to(self.grace):
            for call in (
                lambda: services.add_section_as(self.principal, self.stmarys, "home", version=0, kind="hero", data=HERO),
                lambda: services.draft_as(self.principal, self.stmarys),
                lambda: services.mark_ready_as(self.principal, self.stmarys),
                lambda: services.publish_as(self.principal, self.stmarys),
                lambda: services.set_delegation_as(self.principal, self.stmarys, True),
                lambda: services.publish_log_as(self.principal, self.stmarys),
            ):
                with self.assertRaises(NotAllowed):
                    call()
            self.assertIsNone(services.live_revision(self.stmarys))
        self.assertEqual((self.counts(self.stmarys), self.counts(self.grace)), before)

    def test_what_one_school_publishes_is_only_ever_on_its_own_site(self):
        self.add(self.principal)
        mine = self.publish(self.principal)
        self.add(self.grace_principal, data={"heading": "Grace Academy, Abuja"}, school=self.grace)
        theirs = self.publish(self.grace_principal, school=self.grace)
        self.assertEqual((mine.number, theirs.number), (1, 1))
        with connected_to(self.stmarys):
            heading = services.live_revision(self.stmarys).snapshot["pages"][0]["sections"][0]["data"]["heading"]
            self.assertEqual(heading, HERO["heading"])
            self.assertIsNone(services.live_revision(self.grace))
        with connected_to(self.grace):
            heading = services.live_revision(self.grace).snapshot["pages"][0]["sections"][0]["data"]["heading"]
            self.assertEqual(heading, "Grace Academy, Abuja")

    def test_a_delegation_at_one_school_is_nothing_at_another(self):
        grant_membership(self.admin, self.grace, Role.ADMIN)
        self.delegate(True)
        self.add(self.admin)
        with connected_to(self.grace), self.assertRaises(NotAllowedToEdit):
            services.add_section_as(self.admin, self.grace, "home", version=0, kind="hero", data=HERO)
        self.assertEqual(self.counts(self.grace)[0], 0)


class AStaleSaveIsRefusedTests(SiteSetUp):
    def test_a_page_a_section_and_the_settings_each_refuse_an_old_version(self):
        section = self.add(self.principal)
        with connected_to(self.stmarys):
            services.save_section_as(self.principal, self.stmarys, section.pk, version=section.version,
                                     data={**HERO, "heading": "First"})
            before = self.counts()
            with self.assertRaises(StaleDraft):
                services.save_section_as(self.principal, self.stmarys, section.pk, version=section.version,
                                         data={**HERO, "heading": "Second"})
            with self.assertRaises(StaleDraft):
                services.save_page_as(self.principal, self.stmarys, "home", version=0, title="Home")
            with self.assertRaises(StaleDraft):
                services.add_section_as(self.principal, self.stmarys, "home", version=0, kind="crest_motto", data=MOTTO)
            services.save_footer_as(self.principal, self.stmarys, {"address_line": "Ring Road"}, version=0)
            with self.assertRaises(StaleDraft):
                services.set_theme_as(self.principal, self.stmarys, "modern", version=0)
            self.assertEqual(Section.objects.get(pk=section.pk).data["heading"], "First")
        self.assertEqual(self.counts()[:4], before[:4])


class PublishingTests(SiteSetUp):
    def test_each_publish_writes_one_revision_and_one_log_line_naming_who(self):
        self.add(self.principal)
        revision = self.publish(self.principal, note="Our new website")
        with connected_to(self.stmarys):
            (event,) = SitePublishEvent.objects.all()
            self.assertEqual((event.kind, event.revision_id, event.by_id, event.by_name, event.by_role),
                             ("published", revision.pk, self.principal.pk, "Rev. Sr. Ngozi Okafor", "principal"))
            self.assertEqual((revision.number, revision.published_by_id, revision.note), (1, self.principal.pk,
                                                                                          "Our new website"))
            self.assertEqual(revision.summary["added"], 1)
            log = services.publish_log_as(self.principal, self.stmarys)["events"]
            self.assertEqual([(e["kind"], e["revision"], e["by"]) for e in log],
                             [("published", 1, "Rev. Sr. Ngozi Okafor")])

    def test_publishing_nothing_new_is_refused_and_writes_nothing(self):
        self.add(self.principal)
        self.publish(self.principal)
        before = self.counts()
        with connected_to(self.stmarys), self.assertRaises(SiteRefused):
            services.publish_as(self.principal, self.stmarys)
        self.assertEqual(self.counts(), before)

    def test_what_was_published_does_not_move_when_the_draft_does(self):
        section = self.add(self.principal)
        revision = self.publish(self.principal)
        with connected_to(self.stmarys):
            services.save_section_as(self.principal, self.stmarys, section.pk, version=section.version,
                                     data={**HERO, "heading": "Changed after"})
            live = services.live_revision(self.stmarys)
        self.assertEqual(live.pk, revision.pk)
        self.assertEqual(live.snapshot["pages"][0]["sections"][0]["data"]["heading"], HERO["heading"])

    def test_a_rollback_republishes_an_older_snapshot_logs_once_and_leaves_the_draft(self):
        self.add(self.principal)
        first = self.publish(self.principal)
        self.add(self.principal, "crest_motto", MOTTO)
        self.publish(self.principal)
        draft = self.draft()
        with connected_to(self.stmarys):
            back = services.rollback_as(self.principal, self.stmarys, first.number, note="Wrong motto")
            self.assertEqual((back.number, back.rollback_of_id, back.snapshot), (3, first.pk, first.snapshot))
            self.assertEqual(back.summary["removed"], 1)
            kinds = list(SitePublishEvent.objects.order_by("id").values_list("kind", flat=True))
            self.assertEqual(kinds, ["published", "published", "rolled_back"])
            log = services.publish_log_as(self.principal, self.stmarys)["events"]
            self.assertEqual((log[0]["kind"], log[0]["rollback_of"], log[0]["note"]), ("rolled_back", 1, "Wrong motto"))
        self.assertEqual(self.draft(), draft)

    def test_rolling_back_to_what_is_live_or_to_nothing_is_refused(self):
        self.add(self.principal)
        self.publish(self.principal)
        before = self.counts()
        with connected_to(self.stmarys):
            for number in (1, 2, 0):
                with self.subTest(number=number), self.assertRaises(SiteRefused):
                    services.rollback_as(self.principal, self.stmarys, number)
        self.assertEqual(self.counts(), before)


class ReadyForThePrincipalTests(SiteSetUp):
    def test_ready_is_a_draft_version_and_publishing_clears_it(self):
        self.delegate(True)
        section = self.add(self.admin)
        with connected_to(self.stmarys):
            services.mark_ready_as(self.admin, self.stmarys, note="Please check the hero")
            self.assertTrue(SiteSettings.objects.get(pk=1).is_ready)
            with self.assertRaises(SiteRefused):
                services.mark_ready_as(self.admin, self.stmarys)
            services.save_section_as(self.admin, self.stmarys, section.pk, version=section.version,
                                     data={**HERO, "heading": "One more change"})
            self.assertFalse(SiteSettings.objects.get(pk=1).is_ready)
            services.mark_ready_as(self.admin, self.stmarys)
            services.publish_as(self.principal, self.stmarys)
            settings = SiteSettings.objects.get(pk=1)
            self.assertFalse(settings.is_ready)
            self.assertIsNone(settings.ready_by_id)
            self.assertEqual(SitePublishEvent.objects.filter(kind="marked_ready").count(), 2)

    def test_a_draft_nobody_has_touched_is_nothing_to_mark_ready_or_publish(self):
        before = self.counts()
        with connected_to(self.stmarys):
            with self.assertRaises(SiteRefused):
                services.mark_ready_as(self.principal, self.stmarys)
            with self.assertRaises(SiteRefused):
                services.publish_as(self.principal, self.stmarys)
        self.assertEqual(self.counts(), before)


class TheRecordNeverChangesTests(SiteSetUp):
    def setUp(self):
        super().setUp()
        self.delegate(True)
        self.add(self.principal)
        self.publish(self.principal)

    def test_postgres_refuses_to_update_or_delete_a_revision_or_a_log_row(self):
        with connected_to(self.stmarys):
            for model, table in ((SiteRevision, "schoolsite_siterevision"),
                                 (SitePublishEvent, "schoolsite_sitepublishevent"),
                                 (SiteDelegationEvent, "schoolsite_sitedelegationevent")):
                with self.subTest(table=table):
                    field = "note" if model is not SiteDelegationEvent else "by_name"
                    with transaction.atomic(), self.assertRefusedBy(f"{table} is append-only"):
                        model.objects.update(**{field: "rewritten"})
                    # Plain SQL, as a shell or an import would send it: the ORM's own
                    # delete would stop at the PROTECT foreign keys first.
                    with self.assertRefusedBy(f"{table} is append-only"), transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(f"DELETE FROM {table}")

    def test_the_models_refuse_too_in_words(self):
        with connected_to(self.stmarys):
            for row in (SiteRevision.objects.get(), SitePublishEvent.objects.get(), SiteDelegationEvent.objects.get()):
                with self.subTest(row=str(row)):
                    with self.assertRaises(RecordIsFixed):
                        row.save()
                    with self.assertRaises(RecordIsFixed):
                        row.delete()


class TheDraftHoldsOnlyWhatIsAllowedTests(SiteSetUp):
    def test_postgres_holds_one_hero_per_page_at_the_top_and_home_always_on(self):
        self.add(self.principal)
        with connected_to(self.stmarys):
            page = Page.objects.get(key="home")
            with transaction.atomic(), self.assertRefusedBy("a_page_has_at_most_one_hero"):
                Section.objects.create(page=page, kind="hero", variant="plain", data=HERO, position=0)
            with transaction.atomic(), self.assertRefusedBy("a_hero_comes_first"):
                Section.objects.filter(kind="hero").update(position=3)
            with transaction.atomic(), self.assertRefusedBy("the_home_page_is_always_on"):
                Page.objects.filter(key="home").update(enabled=False)

    def test_the_services_hold_the_same_rules_in_words(self):
        hero = self.add(self.principal)
        motto = self.add(self.principal, "crest_motto", MOTTO)
        with connected_to(self.stmarys):
            version = Page.objects.get(key="home").version
            with self.assertRaises(SiteRefused):
                services.add_section_as(self.principal, self.stmarys, "home", version=version, kind="hero", data=HERO)
            with self.assertRaises(SiteRefused):
                services.move_sections_as(self.principal, self.stmarys, "home", [motto.pk, hero.pk],
                                          version=version)
            with self.assertRaises(SiteRefused):
                services.save_page_as(self.principal, self.stmarys, "home", version=version, enabled=False)
            with self.assertRaises(SectionRefused):
                services.add_section_as(self.principal, self.stmarys, "home", version=version, kind="text",
                                        data={"body": "A text section belongs on About."})

    def test_unknown_fields_wrong_types_long_text_and_control_characters_are_refused(self):
        for data in (
            {**HERO, "html": "<b>hi</b>"},
            {"heading": 7},
            {"heading": "x" * 121},
            {"heading": "Bell\x07"},
            {"heading": ""},
            {**HERO, "buttons": [{"label": "Apply", "link": "/admissions/"}] * 3},
        ):
            with self.subTest(data=str(data)[:40]), connected_to(self.stmarys), self.assertRaises(SectionRefused):
                services.add_section_as(self.principal, self.stmarys, "home", version=0, kind="hero", data=data)
        self.assertEqual(self.counts()[0], 0)

    def test_a_link_is_one_of_the_sites_pages_https_tel_or_mailto_and_nothing_else(self):
        for good in ("/admissions/", "https://wa.me/2348030000000", "tel:+234 803 000 0000",
                     "mailto:office@stmarys.edu.ng", "https://stmarys.edu.ng/prospectus.pdf"):
            with self.subTest(link=good):
                self.assertEqual(clean_link(good), good)
        for bad in ("javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,<script>", "vbscript:x",
                    "//evil.example", "http://plain.example", "HTTPS://shout.example", "https://user@host.example",
                    "https://a b.example", "https://evil.example\\@good.example", "https://localhost",
                    "/home/", "/sit/", "tel:not-a-number", "mailto:not an address", "ftp://files.example"):
            with self.subTest(link=bad), self.assertRaises(SectionRefused):
                clean_link(bad)

    def test_news_is_checked_for_shape_and_a_gallery_for_shape_and_its_album(self):
        from schoolsite import pictures
        from schoolsite.errors import SiteRefused

        with connected_to(self.stmarys):
            album = pictures.create_album_as(self.principal, self.stmarys, title="Sports day")
        self.add(self.principal, "gallery", {"album": album.pk, "count": 12}, key="gallery")
        self.add(self.principal, "news", {"count": 6}, key="news")
        for data in ({"album": 1, "photos": [1]}, {}, {"album": 0}, {"album": 1, "count": 13},
                     {"photos": [1] * 13}, {"photos": [1], "count": 2}, {"album": True}):
            with self.subTest(data=data), connected_to(self.stmarys), self.assertRaises(SectionRefused):
                services.add_section_as(self.principal, self.stmarys, "gallery",
                                        version=Page.objects.get(key="gallery").version, kind="gallery", data=data)
        # An album or photo the school does not have is refused too (PR 5).
        for data in ({"album": 999_999}, {"photos": [999_999]}):
            with self.subTest(data=data), connected_to(self.stmarys), self.assertRaises(SiteRefused):
                services.add_section_as(self.principal, self.stmarys, "gallery",
                                        version=Page.objects.get(key="gallery").version, kind="gallery", data=data)

    def test_the_footer_links_only_to_known_networks_on_their_own_hosts(self):
        with connected_to(self.stmarys):
            services.save_footer_as(self.principal, self.stmarys, {
                "social": [{"network": "facebook", "url": "https://www.facebook.com/stmarys"}],
                "address_line": "Off Ring Road, Ibadan",
            }, version=0)
            for footer in ({"social": [{"network": "facebook", "url": "https://evil.example/stmarys"}]},
                           {"social": [{"network": "myspace", "url": "https://myspace.com/x"}]},
                           {"social": [{"network": "x", "url": "javascript:alert(1)"}]},
                           {"colour": "red"}):
                with self.subTest(footer=footer), self.assertRaises(SectionRefused):
                    services.save_footer_as(self.principal, self.stmarys, footer, version=1)


class ThemeOptionsAreAnAllowListTests(SiteSetUp):
    def test_only_a_known_theme_and_its_own_options_are_kept_and_kept_clean(self):
        with connected_to(self.stmarys):
            services.set_theme_as(self.principal, self.stmarys, "modern", {
                "header_style": "sticky", "font_pairing": "hanken",
                "colours": {"primary": "143d8c", "text": "#1A1A1A", "surface": "#ffffff"},
                "animations": {"hero": False},
            }, version=0)
            stored = SiteSettings.objects.get(pk=1).theme_options
            self.assertEqual(stored, {"modern": {
                "header_style": "sticky", "font_pairing": "hanken",
                "colours": {"primary": "#143D8C", "surface": "#FFFFFF", "text": "#1A1A1A"},
                "animations": {"hero": False},
            }})
            before = self.counts()
            for key, options in (
                ("golden", None),
                ("starter", {}),
                ("modern", {"css": "body{display:none}"}),
                ("modern", {"header_style": "<script>alert(1)</script>"}),
                ("modern", {"font_pairing": "comic"}),
                ("modern", {"colours": {"primary": "red"}}),
                ("modern", {"colours": {"primary": "#fff"}}),
                ("modern", {"colours": {"glow": "#000000"}}),
                ("modern", {"colours": {"primary": "url(javascript:x)"}}),
                ("modern", {"colours": {"text": "#BBBBBB", "surface": "#FFFFFF"}}),
                ("modern", {"animations": {"hero": "off"}}),
                ("modern", {"animations": {"fireworks": True}}),
                ("modern", {"animations": "all"}),
                ("modern", "header_style=solid"),
            ):
                with self.subTest(key=key, options=options), self.assertRaises(ThemeRefused):
                    services.set_theme_as(self.principal, self.stmarys, key, options, version=1)
            self.assertEqual(self.counts(), before)
            self.assertEqual(SiteSettings.objects.get(pk=1).theme_options, stored)


class TheSummaryTests(SiteSetUp):
    def test_it_counts_what_was_added_removed_changed_moved_and_switched(self):
        hero = self.add(self.principal)
        motto = self.add(self.principal, "crest_motto", MOTTO)
        first = self.publish(self.principal)
        with connected_to(self.stmarys):
            services.save_section_as(self.principal, self.stmarys, hero.pk, version=hero.version,
                                     data={**HERO, "heading": "Changed"})
            services.remove_section_as(self.principal, self.stmarys, motto.pk, version=motto.version)
            services.save_page_as(self.principal, self.stmarys, "about", version=0, enabled=True)
        self.add(self.principal, "text", {"body": "Founded in 1962."}, key="about")
        second = self.publish(self.principal)
        self.assertTrue(first.summary["theme_changed"])
        self.assertEqual(
            {k: second.summary[k] for k in ("added", "removed", "changed", "pages_on", "pages_off", "theme_changed")},
            {"added": 1, "removed": 1, "changed": 1, "pages_on": ["about"], "pages_off": [], "theme_changed": False},
        )
