"""The report card settings for the affective and psychomotor sections.

Two schools, St Mary's and Grace, on `ReportCardApiSetUp`: a whole session each,
a class, children, and a released first term.

- **authority**: St Mary's principal cannot change Grace's settings, a class
  teacher cannot change anyone's, and a refusal changes nothing;
- **released cards do not move**: rename, hide, add, reorder, relabel, switch
  off — the card payload, the Ogun key and a reissued version are unchanged;
- **off means absent on new cards**, per domain, and only on new ones;
- **off keeps the ratings**, and switching on again brings them back;
- **every change is logged** with who and when, and a change that changed
  nothing is not.
"""

from django.db import IntegrityError, transaction

from academics.models import Term, TermName
from accounts.models import Role
from results import ratings, revision
from results.models import (
    ConductSettingChange,
    RatingScalePoint,
    ReleasedCard,
    Trait,
    TraitGroup,
    TraitRating,
)
from results.tests.test_card_api import HOST, THEIR_HOST, ReportCardApiSetUp
from schools.tests.tenants import connected_to

URL = "/api/results/report-card/conduct/"
AFFECTIVE, PSYCHOMOTOR = TraitGroup.AFFECTIVE.value, TraitGroup.PSYCHOMOTOR.value


class ConductSetUp(ReportCardApiSetUp):
    def send(self, method, path, user, body=None, host=HOST):
        self.client.force_login(user)
        call = getattr(self.client, method)
        if method == "get":
            return call(path, HTTP_HOST=host)
        return call(path, data=body or {}, content_type="application/json", HTTP_HOST=host)

    def trait(self, school, group, index=0):
        with connected_to(school):
            return list(Trait.objects.in_group(group).visible())[index]

    def names(self, school, group, hidden=False):
        with connected_to(school):
            return [t.name for t in ratings.traits(group, include_hidden=hidden)]

    def switch(self, school, user, **groups):
        with connected_to(school):
            for group, on in groups.items():
                ratings.set_group_enabled_as(user, group, on)

    def rate_everything(self, school, term_name=TermName.FIRST.value):
        """Ada gets a 5 on every trait of the school, whatever is switched on."""
        with connected_to(school):
            term = self.term_of(school, term_name)
            for trait in Trait.objects.all():
                TraitRating.objects.create(
                    term=term, student_membership_id=self.child_of(school).pk,
                    trait=trait, score=5,
                )

    def child_of(self, school):
        return self.ada if school == self.stmarys else self.ngozi

    def card(self, school=None):
        school = school or self.stmarys
        who = self.principal if school == self.stmarys else self.their_principal
        response = self.fetch(who, school, self.child_of(school))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class WhoMayChangeThemTests(ConductSetUp):
    def test_the_principal_of_one_school_cannot_change_the_others(self):
        for path, body, method in (
            (f"{URL}{AFFECTIVE}/enabled/", {"enabled": True}, "put"),
            (f"{URL}{AFFECTIVE}/traits/", {"name": "Kindness"}, "post"),
            (f"{URL}scale/5/", {"label": "Superb"}, "put"),
        ):
            with self.subTest(path=path):
                # St Mary's principal, at Grace's own address: no standing there.
                response = self.send(method, path, self.principal, body, host=THEIR_HOST)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.send("get", URL, self.principal, host=THEIR_HOST).status_code, 403)
        with connected_to(self.grace):
            self.assertEqual(ratings.enabled_groups(), [])
            self.assertEqual(ConductSettingChange.objects.count(), 0)
            self.assertNotIn("Kindness", [t.name for t in Trait.objects.all()])
            self.assertNotEqual(ratings.scale_labels()[5], "Superb")

    def test_the_service_refuses_a_principal_on_the_other_schools_connection(self):
        # The same refusal one layer down: the connection is Grace's, the actor
        # is St Mary's principal.
        with connected_to(self.grace):
            with self.assertRaises(ratings.NotAllowedToConfigureRatings):
                ratings.set_group_enabled_as(self.principal, AFFECTIVE, True)
            with self.assertRaises(ratings.NotAllowedToConfigureRatings):
                ratings.add_trait_as(self.principal, AFFECTIVE, "Kindness")
            self.assertEqual(ratings.enabled_groups(), [])

    def test_a_class_teacher_cannot_read_or_change_them(self):
        trait = self.trait(self.stmarys, AFFECTIVE)
        calls = (
            ("get", URL, None),
            ("put", f"{URL}{AFFECTIVE}/enabled/", {"enabled": True}),
            ("post", f"{URL}{PSYCHOMOTOR}/traits/", {"name": "Kindness"}),
            ("put", f"{URL}traits/{trait.pk}/", {"name": "Tidiness", "hidden": True}),
            ("put", f"{URL}{AFFECTIVE}/order/", {"trait_ids": [trait.pk]}),
            ("put", f"{URL}scale/5/", {"label": "Superb"}),
        )
        for method, path, body in calls:
            with self.subTest(path=path):
                self.assertEqual(self.send(method, path, self.teacher, body).status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(ratings.enabled_groups(), [])
            self.assertEqual(Trait.objects.get(pk=trait.pk).name, trait.name)
            self.assertEqual(ConductSettingChange.objects.count(), 0)
            self.assertNotEqual(ratings.scale_labels()[5], "Superb")

    def test_a_teacher_gets_the_same_403_for_a_trait_that_does_not_exist(self):
        # Authority first: the status must not say which ids are real.
        response = self.send("put", f"{URL}traits/999999/", self.teacher, {"name": "x"})
        self.assertEqual(response.status_code, 403)

    def test_the_principal_and_the_administrator_may(self):
        for user in (self.principal, self.staff_of(self.stmarys)[Role.ADMIN]):
            with self.subTest(user=user.username):
                on = self.send("put", f"{URL}{AFFECTIVE}/enabled/", user, {"enabled": True})
                self.assertEqual(on.status_code, 200, on.content)
                self.assertTrue(on.json()["sections"][0]["enabled"])

    def test_the_two_switches_are_separate(self):
        self.send("put", f"{URL}{PSYCHOMOTOR}/enabled/", self.principal, {"enabled": True})
        sections = {s["group"]: s for s in self.send("get", URL, self.principal).json()["sections"]}
        self.assertEqual(
            (sections[AFFECTIVE]["enabled"], sections[PSYCHOMOTOR]["enabled"]), (False, True)
        )
        self.assertEqual(sections[AFFECTIVE]["label"], "Affective (conduct)")
        self.assertEqual(sections[PSYCHOMOTOR]["label"], "Psychomotor (skills)")

    def test_a_school_sees_its_own_trait_list_and_nobody_elses(self):
        self.send("post", f"{URL}{AFFECTIVE}/traits/", self.principal, {"name": "Kindness"})
        mine = self.send("get", URL, self.principal).json()
        theirs = self.send("get", URL, self.their_principal, host=THEIR_HOST).json()
        self.assertIn("Kindness", [t["name"] for t in mine["sections"][0]["traits"]])
        self.assertNotIn("Kindness", [t["name"] for t in theirs["sections"][0]["traits"]])
        self.assertEqual(theirs["changes"], [])


class EditingTests(ConductSetUp):
    def test_rename_add_hide_reorder_and_relabel_over_http(self):
        first, second = self.trait(self.stmarys, AFFECTIVE, 0), self.trait(self.stmarys, AFFECTIVE, 1)

        renamed = self.send("put", f"{URL}traits/{first.pk}/", self.principal, {"name": "Tidiness"})
        added = self.send("post", f"{URL}{AFFECTIVE}/traits/", self.principal, {"name": "Kindness"})
        hidden = self.send("put", f"{URL}traits/{second.pk}/", self.principal, {"hidden": True})
        relabelled = self.send("put", f"{URL}scale/4/", self.principal, {"label": "Very Good"})

        for response in (renamed, added, hidden, relabelled):
            self.assertEqual(response.status_code, 200, response.content)
        shown = {t["name"]: t["is_hidden"] for t in relabelled.json()["sections"][0]["traits"]}
        self.assertEqual((shown["Tidiness"], shown["Kindness"], shown[second.name]), (False, False, True))
        self.assertEqual({p["value"]: p["label"] for p in relabelled.json()["scale"]}[4], "Very Good")

        kindness = [t for t in added.json()["sections"][0]["traits"] if t["name"] == "Kindness"][0]
        ids = [t["trait_id"] for t in added.json()["sections"][0]["traits"]]
        reordered = self.send(
            "put", f"{URL}{AFFECTIVE}/order/", self.principal,
            {"trait_ids": [kindness["trait_id"]]},
        )
        self.assertEqual(reordered.json()["sections"][0]["traits"][0]["name"], "Kindness")
        self.assertEqual(
            sorted(t["trait_id"] for t in reordered.json()["sections"][0]["traits"]), sorted(ids)
        )

    def test_the_scale_stays_one_to_five_and_a_bad_edit_says_why(self):
        self.assertEqual(self.send("put", f"{URL}scale/7/", self.principal, {"label": "Super"}).status_code, 422)
        self.assertEqual(self.send("put", f"{URL}scale/3/", self.principal, {"label": "  "}).status_code, 422)
        self.assertEqual(self.send("post", f"{URL}{AFFECTIVE}/traits/", self.principal, {"name": " "}).status_code, 422)
        self.assertEqual(self.send("put", f"{URL}conduct/enabled/", self.principal, {"enabled": True}).status_code, 422)
        with connected_to(self.stmarys):
            self.assertEqual(sorted(ratings.scale_labels()), [1, 2, 3, 4, 5])
            self.assertEqual(ConductSettingChange.objects.count(), 0)

    def test_a_trait_that_has_been_rated_can_be_hidden_and_is_never_deleted(self):
        self.switch(self.stmarys, self.principal, **{AFFECTIVE: True})
        self.rate_everything(self.stmarys)
        trait = self.trait(self.stmarys, AFFECTIVE)
        response = self.send("put", f"{URL}traits/{trait.pk}/", self.principal, {"hidden": True})
        row = [t for t in response.json()["sections"][0]["traits"] if t["trait_id"] == trait.pk][0]
        self.assertEqual((row["is_hidden"], row["has_ratings"]), (True, True))
        with connected_to(self.stmarys):
            with self.assertRaises(Exception):
                with transaction.atomic():
                    Trait.objects.filter(pk=trait.pk).delete()


class TheLogTests(ConductSetUp):
    def test_every_change_is_logged_with_who_and_when(self):
        trait = self.trait(self.stmarys, PSYCHOMOTOR)
        self.send("put", f"{URL}{AFFECTIVE}/enabled/", self.principal, {"enabled": True})
        self.send("put", f"{URL}traits/{trait.pk}/", self.principal, {"name": "Penmanship"})
        self.send("put", f"{URL}scale/5/", self.staff_of(self.stmarys)[Role.ADMIN], {"label": "Superb"})

        with connected_to(self.stmarys):
            rows = list(ConductSettingChange.objects.order_by("id"))
        self.assertEqual(
            [(r.kind, r.by_id, r.by_name) for r in rows],
            [
                ("section_on", self.principal.pk, self.principal.full_name),
                ("trait_renamed", self.principal.pk, self.principal.full_name),
                ("scale_label", self.staff_of(self.stmarys)[Role.ADMIN].pk,
                 self.staff_of(self.stmarys)[Role.ADMIN].full_name),
            ],
        )
        self.assertTrue(all(r.at is not None for r in rows))
        self.assertIn("Penmanship", rows[1].summary)
        self.assertIn(trait.name, rows[1].summary)
        self.assertIn("Superb", rows[2].summary)

        shown = self.send("get", URL, self.principal).json()["changes"]
        self.assertEqual([c["by"] for c in shown], [self.staff_of(self.stmarys)[Role.ADMIN].full_name,
                                                      self.principal.full_name, self.principal.full_name])
        self.assertTrue(all(c["at"] for c in shown))

    def test_a_change_that_changes_nothing_is_not_logged_and_the_other_school_has_no_log(self):
        self.send("put", f"{URL}{AFFECTIVE}/enabled/", self.principal, {"enabled": False})
        trait = self.trait(self.stmarys, AFFECTIVE)
        self.send("put", f"{URL}traits/{trait.pk}/", self.principal, {"name": trait.name, "hidden": False})
        with connected_to(self.stmarys):
            current = ratings.scale_labels()[3]
        self.send("put", f"{URL}scale/3/", self.principal, {"label": current})
        with connected_to(self.stmarys):
            self.assertEqual(ConductSettingChange.objects.count(), 0)

        self.send("put", f"{URL}{AFFECTIVE}/enabled/", self.principal, {"enabled": True})
        with connected_to(self.stmarys):
            self.assertEqual(ConductSettingChange.objects.count(), 1)
        with connected_to(self.grace):
            self.assertEqual(ConductSettingChange.objects.count(), 0)

    def test_a_refused_change_leaves_no_row(self):
        self.send("post", f"{URL}{AFFECTIVE}/traits/", self.principal, {"name": " "})
        self.send("put", f"{URL}scale/9/", self.principal, {"label": "x"})
        with connected_to(self.stmarys):
            self.assertEqual(ConductSettingChange.objects.count(), 0)

    def test_the_log_cannot_be_edited_or_deleted(self):
        self.send("put", f"{URL}{AFFECTIVE}/enabled/", self.principal, {"enabled": True})
        with connected_to(self.stmarys):
            row = ConductSettingChange.objects.get()
            with self.assertRaises(IntegrityError), transaction.atomic():
                ConductSettingChange.objects.filter(pk=row.pk).update(summary="nothing happened")
            with self.assertRaises(IntegrityError), transaction.atomic():
                from django.db import connection

                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM results_conductsettingchange")
            with self.assertRaises(ValueError):
                row.delete()


class ReleasedCardsDoNotMoveTests(ConductSetUp):
    """Release with both sections on, then change everything the school can."""

    def setUp(self):
        super().setUp()
        for school, who in ((self.stmarys, self.principal), (self.grace, self.their_principal)):
            self.switch(school, who, **{AFFECTIVE: True, PSYCHOMOTOR: True})
            self.rate_everything(school)
        self.release()
        self.release(self.grace)

    def change_everything(self, school, who, host):
        first = self.trait(school, AFFECTIVE, 0)
        second = self.trait(school, AFFECTIVE, 1)
        skill = self.trait(school, PSYCHOMOTOR, 0)
        self.send("put", f"{URL}traits/{first.pk}/", who, {"name": "Renamed afterwards"}, host=host)
        self.send("put", f"{URL}traits/{second.pk}/", who, {"hidden": True}, host=host)
        self.send("put", f"{URL}traits/{skill.pk}/", who, {"name": "Also renamed", "hidden": True}, host=host)
        self.send("post", f"{URL}{AFFECTIVE}/traits/", who, {"name": "Added afterwards"}, host=host)
        order = [t.pk for t in reversed(self_ordered(school, AFFECTIVE))]
        self.send("put", f"{URL}{AFFECTIVE}/order/", who, {"trait_ids": order}, host=host)
        for value, label in ((5, "Perfect"), (4, "Fine"), (1, "Dreadful")):
            self.send("put", f"{URL}scale/{value}/", who, {"label": label}, host=host)
        self.send("put", f"{URL}{AFFECTIVE}/enabled/", who, {"enabled": False}, host=host)
        self.send("put", f"{URL}{PSYCHOMOTOR}/enabled/", who, {"enabled": False}, host=host)

    def test_the_released_card_is_the_same_after_every_change(self):
        before, theirs_before = self.card(), self.card(self.grace)
        self.assertEqual([s["group"] for s in before["sections"]], [AFFECTIVE, PSYCHOMOTOR])

        self.change_everything(self.stmarys, self.principal, HOST)

        self.assertEqual(self.card(), before)
        self.assertEqual(self.card(self.grace), theirs_before)
        with connected_to(self.stmarys):
            self.assertEqual(ratings.enabled_groups(), [], "the changes did land")
            self.assertEqual(ratings.scale_labels()[5], "Perfect")

    def test_the_released_card_keeps_its_names_its_order_and_its_words(self):
        before = self.card()
        names = [t["trait_name"] for s in before["sections"] for t in s["traits"]]
        words = {t["score_label"] for s in before["sections"] for t in s["traits"]}
        self.change_everything(self.stmarys, self.principal, HOST)
        after = self.card()
        self.assertEqual([t["trait_name"] for s in after["sections"] for t in s["traits"]], names)
        self.assertNotIn("Renamed afterwards", names)
        self.assertEqual({t["score_label"] for s in after["sections"] for t in s["traits"]}, words)
        self.assertNotIn("Perfect", words)

    def test_a_reissued_card_carries_the_section_it_was_sent_with(self):
        before = self.card()
        self.change_everything(self.stmarys, self.principal, HOST)
        with connected_to(self.stmarys):
            revision.revise(
                self.ada, self.term_of(self.stmarys, TermName.FIRST.value),
                self.principal, "A misspelt name",
            )
            self.assertEqual(ReleasedCard.objects.filter(student_membership_id=self.ada.pk).count(), 2)
        after = self.card()
        self.assertEqual(after["sections"], before["sections"])

    def test_the_stored_card_rows_are_untouched(self):
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            rows = list(card.trait_ratings.order_by("id").values_list("trait_name", "score", "score_label", "position"))
            scale = card.rating_scale
        self.change_everything(self.stmarys, self.principal, HOST)
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            self.assertEqual(
                list(card.trait_ratings.order_by("id").values_list("trait_name", "score", "score_label", "position")),
                rows,
            )
            self.assertEqual(card.rating_scale, scale)
        self.assertEqual(scale[0], [5, "Excellent"])


def self_ordered(school, group):
    with connected_to(school):
        return list(Trait.objects.in_group(group))


class OffMeansAbsentOnNewCardsTests(ConductSetUp):
    def test_a_domain_that_is_off_shows_nowhere_on_a_new_card_and_the_other_still_does(self):
        self.switch(self.stmarys, self.principal, **{AFFECTIVE: True, PSYCHOMOTOR: True})
        self.rate_everything(self.stmarys)
        self.switch(self.stmarys, self.principal, **{PSYCHOMOTOR: False})
        self.release()

        card = self.card()

        self.assertEqual([s["group"] for s in card["sections"]], [AFFECTIVE])
        text = str(card)
        for trait in self.names(self.stmarys, PSYCHOMOTOR):
            self.assertNotIn(trait, text)
        with connected_to(self.stmarys):
            self.assertEqual(
                set(ReleasedCard.objects.get(student_membership_id=self.ada.pk).trait_ratings.values_list("group", flat=True)),
                {AFFECTIVE},
            )

    def test_both_off_means_no_section_and_no_trace(self):
        self.rate_everything(self.stmarys)
        self.release()
        card = self.card()
        self.assertEqual(card["sections"], [])
        for trait in self.names(self.stmarys, AFFECTIVE) + self.names(self.stmarys, PSYCHOMOTOR):
            self.assertNotIn(trait, str(card))

    def test_one_school_switching_a_domain_on_does_not_put_it_on_the_others_cards(self):
        self.switch(self.stmarys, self.principal, **{AFFECTIVE: True})
        self.rate_everything(self.stmarys)
        self.rate_everything(self.grace)
        self.release()
        self.release(self.grace)
        self.assertEqual([s["group"] for s in self.card()["sections"]], [AFFECTIVE])
        self.assertEqual(self.card(self.grace)["sections"], [])

    def test_switching_a_domain_on_later_does_not_add_it_to_a_card_already_sent(self):
        self.switch(self.stmarys, self.principal, **{AFFECTIVE: True})
        self.rate_everything(self.stmarys)
        self.release()
        before = self.card()
        self.switch(self.stmarys, self.principal, **{PSYCHOMOTOR: True})
        self.assertEqual(self.card(), before)

    def test_a_draft_card_follows_the_switches(self):
        self.switch(self.stmarys, self.principal, **{PSYCHOMOTOR: True})
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            groups = lambda: [  # noqa: E731
                s.group for s in ratings.card_sections(self.ada.pk, self.group_of(self.stmarys), term)
            ]
            self.assertEqual(groups(), [PSYCHOMOTOR])
        self.switch(self.stmarys, self.principal, **{PSYCHOMOTOR: False})
        with connected_to(self.stmarys):
            self.assertEqual(groups(), [])


class OffKeepsTheRatingsTests(ConductSetUp):
    def grid(self):
        with connected_to(self.stmarys):
            Term.objects.update(is_current=False)
            Term.objects.filter(pk=self.term_of(self.stmarys, TermName.FIRST.value).pk).update(is_current=True)
        self.client.force_login(self.teacher)
        response = self.client.get(f"/api/results/comments/{self.ada.pk}/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_off_hides_the_grid_keeps_the_ratings_and_on_brings_them_back(self):
        self.switch(self.stmarys, self.principal, **{AFFECTIVE: True, PSYCHOMOTOR: True})
        self.rate_everything(self.stmarys)
        with connected_to(self.stmarys):
            kept = sorted(TraitRating.objects.values_list("trait_id", "score"))
        self.assertEqual([s["group"] for s in self.grid()["sections"]], [AFFECTIVE, PSYCHOMOTOR])

        self.switch(self.stmarys, self.principal, **{AFFECTIVE: False, PSYCHOMOTOR: False})
        self.assertEqual(self.grid()["sections"], [], "the class teacher no longer sees a grid")
        with connected_to(self.stmarys):
            self.assertEqual(sorted(TraitRating.objects.values_list("trait_id", "score")), kept)

        self.switch(self.stmarys, self.principal, **{AFFECTIVE: True})
        grid = self.grid()
        self.assertEqual([s["group"] for s in grid["sections"]], [AFFECTIVE])
        self.assertEqual({t["score"] for t in grid["sections"][0]["traits"]}, {5})

    def test_a_teacher_cannot_rate_into_a_section_that_is_off(self):
        self.switch(self.stmarys, self.principal, **{AFFECTIVE: True})
        trait = self.trait(self.stmarys, AFFECTIVE)
        self.switch(self.stmarys, self.principal, **{AFFECTIVE: False})
        self.grid()
        response = self.client.put(
            f"/api/results/ratings/{self.ada.pk}/{trait.pk}/", data={"score": 3},
            content_type="application/json", HTTP_HOST=HOST,
        )
        self.assertEqual(response.status_code, 422)
        with connected_to(self.stmarys):
            self.assertEqual(TraitRating.objects.count(), 0)


class TheOgunKeyTests(ConductSetUp):
    def test_the_ogun_key_on_a_released_card_keeps_its_words(self):
        from results import ogun

        with connected_to(self.stmarys):
            ogun.set_template_as(self.principal, self.stmarys, "ogun")
        self.rate_everything(self.stmarys)
        self.release()
        before = self.card()["ogun"]["key"]
        self.assertEqual(before[0], {"value": 5, "label": "Excellent"})

        self.send("put", f"{URL}scale/5/", self.principal, {"label": "Outstanding"})

        self.assertEqual(self.card()["ogun"]["key"], before)
        with connected_to(self.stmarys):
            self.assertEqual(RatingScalePoint.objects.get(value=5).label, "Outstanding")
            self.assertEqual(
                ConductSettingChange.objects.filter(kind="template_applied").count(), 1
            )
