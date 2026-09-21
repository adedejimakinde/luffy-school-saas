"""The two remarks, the phrase bank and the conduct grid, over HTTP.

Two schools in every test, because the failure most likely in a list like this
is that it is not scoped — a missing term filter, a read on the wrong
connection. A single-school fixture cannot fail for any of them.

The rules themselves belong to `results/comments.py` and `results/ratings.py`
and were tested when those were built. What is asserted here is the door: who
may open it, what each refusal comes back as, and that the list costs no child
a query.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext

from academics.models import Term
from accounts.models import Role
from accounts.services import grant_membership
from results import comments as comments_service
from results.models import (
    CommentAuthor,
    ReportCardSettings,
    ResultSheet,
    SheetState,
    Trait,
    TraitGroup,
)
from results.tests.fixtures import HOST, PORTAL, THEIR_HOST, ChainSetUp
from schools.tests.tenants import connected_to

LIST = "/api/results/comments/"


class TheCommentScreenSetUp(ChainSetUp):
    """St Mary's with conduct switched on and a trait to rate."""

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            settings = ReportCardSettings.objects.get_or_create(pk=1)[0]
            settings.affective_enabled = True
            settings.psychomotor_enabled = False
            settings.save()
            # **Seeded, not created.** `0006_seed_traits_and_scale` already
            # puts a school's traits and the five scale points in every schema,
            # so creating "Punctuality" here violates
            # `uniq_trait_name_per_group`. Reading the seeded row is also the
            # more honest fixture: it is the data a real school starts with.
            self.trait = Trait.objects.in_group(TraitGroup.AFFECTIVE).visible().first()
            self.assertIsNotNone(self.trait, "no affective trait is seeded")
            self.trait_id = self.trait.pk

    def ada(self):
        return self.children["ada"].pk

    def as_user(self, user):
        self.client.force_login(user.user)

    def child(self, user, student=None, host=HOST):
        self.as_user(user)
        return self.client.get(
            f"{LIST}{student or self.ada()}/", HTTP_HOST=host
        )

    def write(self, user, author, body, student=None, host=HOST):
        self.as_user(user)
        return self.client.put(
            f"{LIST}{student or self.ada()}/{author}/",
            data={"body": body},
            content_type="application/json",
            HTTP_HOST=host,
        )


class TheClassListTests(TheCommentScreenSetUp):
    def list_for(self, user, group=None, host=HOST):
        self.as_user(user)
        return self.client.get(
            f"{LIST}?class_group_id={group or self.jss1a_id}", HTTP_HOST=host
        )

    def test_the_list_really_lists_children(self):
        """The control, and it runs first: every exclusion below would pass
        against a list that returned nothing for everybody."""
        rows = self.list_for(self.teacher).json()["rows"]

        self.assertEqual(
            sorted(r["student"] for r in rows),
            ["Ada Obi", "Bisi Ade", "Emeka Nwosu", "Tunde Cole"],
        )

    def test_both_remarks_are_outstanding_before_anybody_writes(self):
        rows = {r["student"]: r for r in self.list_for(self.teacher).json()["rows"]}

        self.assertEqual(
            sorted(rows["Ada Obi"]["outstanding"]),
            sorted(a.value for a in CommentAuthor),
        )

    def test_writing_one_removes_it_from_outstanding(self):
        self.write(self.teacher, CommentAuthor.CLASS_TEACHER.value, "A steady term.")

        rows = {r["student"]: r for r in self.list_for(self.teacher).json()["rows"]}

        self.assertEqual(
            rows["Ada Obi"]["outstanding"], [CommentAuthor.PRINCIPAL.value]
        )

    def test_another_group_at_the_same_school_is_absent(self):
        rows = self.list_for(self.teacher, group=self.jss1b_id).json()["rows"]

        self.assertEqual([r["student"] for r in rows], ["Bimpe Ojo"])

    def test_one_schools_list_never_contains_the_others_children(self):
        ours = [r["student"] for r in self.list_for(self.teacher).json()["rows"]]
        theirs = [
            r["student"]
            for r in self.list_for(
                self.grace_teacher, group=self.grace_group_id, host=THEIR_HOST
            ).json()["rows"]
        ]

        self.assertNotIn("Chidi Eze", ours)
        self.assertEqual(theirs, ["Chidi Eze"])

    def test_the_list_does_not_cost_more_as_the_class_grows(self):
        """**The decision the shape turns on, asserted as a shape.** A
        per-child read here would be one query per row on the screen a teacher
        opens for a whole class.

        A fixed number would have to count `django_tenants`' `SET search_path`
        before every statement — it issues one per query, so a literal count is
        double and moves whenever that library does. Comparing two runs cancels
        it out.
        """
        from accounts.models import User
        from accounts.services import enroll_student
        from academics import services as academics

        self.as_user(self.teacher)
        self.client.get(f"{LIST}?class_group_id={self.jss1a_id}", HTTP_HOST=HOST)

        with CaptureQueriesContext(connection) as small:
            self.client.get(f"{LIST}?class_group_id={self.jss1a_id}", HTTP_HOST=HOST)

        for n in range(5):
            child = enroll_student(
                User.objects.create_user(f"extra{n}", "correct-horse-battery",
                                         full_name=f"Extra {n}"),
                self.stmarys,
            )
            with connected_to(self.stmarys):
                academics.place_student(
                    self.jss1a, Term.objects.get(pk=self.term_id), child
                )

        with CaptureQueriesContext(connection) as larger:
            response = self.client.get(
                f"{LIST}?class_group_id={self.jss1a_id}", HTTP_HOST=HOST
            )

        self.assertEqual(len(response.json()["rows"]), 9)
        self.assertEqual(
            len(larger.captured_queries),
            len(small.captured_queries),
            "the list costs more when the class has more children",
        )

    def test_a_bursar_is_refused_before_anything_is_looked_up(self):
        response = self.list_for(self.bursar)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Ada Obi", response.content.decode())

    def test_the_class_group_is_required_and_the_host_answers_first(self):
        """Required by hand, not as a required query parameter: ninja would
        validate one before the view runs, putting a 422 in front of the host
        check and the authority check."""
        self.as_user(self.teacher)

        self.assertEqual(self.client.get(LIST, HTTP_HOST=HOST).status_code, 422)
        self.assertEqual(self.client.get(LIST, HTTP_HOST=PORTAL).status_code, 404)

    def test_a_parent_omitting_the_group_is_refused_before_being_corrected(self):
        self.as_user(self.parent) if hasattr(self, "parent") else self.as_user(self.bursar)

        self.assertEqual(self.client.get(LIST, HTTP_HOST=HOST).status_code, 403)


class OneChildsScreenTests(TheCommentScreenSetUp):
    def remarks(self, response):
        return {r["author"]: r for r in response.json()["remarks"]}

    def test_both_remarks_are_served_and_only_one_is_editable(self):
        """**Confirmed decision 4.** Hiding the other would make a half-written
        card look finished, and the principal has to read the teacher's line
        before adding hers."""
        teacher_view = self.remarks(self.child(self.teacher))
        head_view = self.remarks(self.child(self.head))

        self.assertEqual(sorted(teacher_view), sorted(a.value for a in CommentAuthor))
        self.assertTrue(teacher_view[CommentAuthor.CLASS_TEACHER.value]["may_edit"])
        self.assertFalse(teacher_view[CommentAuthor.PRINCIPAL.value]["may_edit"])
        self.assertTrue(head_view[CommentAuthor.PRINCIPAL.value]["may_edit"])
        self.assertFalse(head_view[CommentAuthor.CLASS_TEACHER.value]["may_edit"])

    def test_each_signatory_is_offered_only_their_own_phrase_bank(self):
        """A teacher picking a remark must never be shown one written for a
        principal to sign — which is why `comments.phrases()` refuses to answer
        without being told whose."""
        with connected_to(self.stmarys):
            comments_service.add_phrase(CommentAuthor.CLASS_TEACHER.value, "A steady term.")
            comments_service.add_phrase(CommentAuthor.PRINCIPAL.value, "Keep it up.")

        banks = self.child(self.teacher).json()["phrases"]

        self.assertEqual(list(banks), [CommentAuthor.CLASS_TEACHER.value])
        self.assertEqual(banks[CommentAuthor.CLASS_TEACHER.value], ["A steady term."])

    def test_a_teacher_of_another_class_may_edit_neither(self):
        """Issue #25's scope, in a third module."""
        other = grant_membership(
            self.vp.user.__class__.objects.create_user(
                "tola", "correct-horse-battery", full_name="Tola Ibe"
            ),
            self.stmarys,
            Role.TEACHER,
        )

        view = self.remarks(self.child(other))

        self.assertFalse(any(r["may_edit"] for r in view.values()))

    def test_the_conduct_grid_appears_only_for_switched_on_groups(self):
        body = self.child(self.teacher).json()

        self.assertEqual([s["group"] for s in body["sections"]], [TraitGroup.AFFECTIVE])
        names = [t["name"] for t in body["sections"][0]["traits"]]
        self.assertIn(self.trait.name, names)
        self.assertTrue(names, "the seeded affective traits are not served")

    def test_a_school_with_conduct_switched_off_gets_no_grid_at_all(self):
        with connected_to(self.stmarys):
            ReportCardSettings.objects.filter(pk=1).update(affective_enabled=False)

        body = self.child(self.teacher).json()

        self.assertEqual(body["sections"], [])

    def test_only_the_class_teacher_may_rate(self):
        """Narrower than the remarks beside it: the principal signs her own
        remark for any child and rates nobody."""
        self.assertTrue(self.child(self.teacher).json()["may_rate"])
        self.assertFalse(self.child(self.head).json()["may_rate"])

    def test_a_locked_sheet_is_reported_before_anybody_types(self):
        """The marking sheet's lesson: a screen that learns from the refusal
        after the paragraph is typed tells her at the worst moment."""
        with connected_to(self.stmarys):
            ResultSheet.objects.create(
                class_group=self.jss1a,
                term=Term.objects.get(pk=self.term_id),
                state=SheetState.SUBMITTED,
            )

        body = self.child(self.teacher).json()

        self.assertTrue(body["locked"])
        self.assertIn("JSS 1A", body["locked_reason"])


class WritingARemarkTests(TheCommentScreenSetUp):
    def test_a_class_teacher_writes_her_own_classs_remark(self):
        """The control for every refusal below."""
        response = self.write(
            self.teacher, CommentAuthor.CLASS_TEACHER.value, "A steady term."
        )

        self.assertEqual(response.status_code, 200)
        with connected_to(self.stmarys):
            self.assertEqual(
                comments_service.comments_for(
                    self.ada(), Term.objects.get(pk=self.term_id)
                )[CommentAuthor.CLASS_TEACHER.value],
                "A steady term.",
            )

    def test_a_teacher_cannot_write_the_principals_remark(self):
        response = self.write(self.teacher, CommentAuthor.PRINCIPAL.value, "Well done.")

        self.assertEqual(response.status_code, 403)

    def test_a_principal_writes_her_own_for_any_child(self):
        response = self.write(self.head, CommentAuthor.PRINCIPAL.value, "Well done.")

        self.assertEqual(response.status_code, 200)

    def test_a_teacher_cannot_write_for_another_class(self):
        bimpe = self.bimpe.pk

        response = self.write(
            self.teacher, CommentAuthor.CLASS_TEACHER.value, "Hello.", student=bimpe
        )

        self.assertEqual(response.status_code, 403)

    def test_a_blank_remark_is_refused_with_a_sentence(self):
        response = self.write(self.teacher, CommentAuthor.CLASS_TEACHER.value, "   ")

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()["detail"])

    def test_a_locked_sheet_refuses_the_write_as_423(self):
        """423 and not 403: the caller's authority has not changed, and no
        reload reopens a term that has left draft."""
        with connected_to(self.stmarys):
            ResultSheet.objects.create(
                class_group=self.jss1a,
                term=Term.objects.get(pk=self.term_id),
                state=SheetState.SUBMITTED,
            )

        response = self.write(
            self.teacher, CommentAuthor.CLASS_TEACHER.value, "A steady term."
        )

        self.assertEqual(response.status_code, 423)

    def test_a_teacher_cannot_write_at_the_other_school(self):
        response = self.write(
            self.teacher,
            CommentAuthor.CLASS_TEACHER.value,
            "Hello.",
            student=self.grace_child.pk,
            host=THEIR_HOST,
        )

        self.assertEqual(response.status_code, 403)


class RatingTests(TheCommentScreenSetUp):
    def rate(self, user, score, trait=None, student=None):
        self.as_user(user)
        return self.client.put(
            f"/api/results/ratings/{student or self.ada()}/{trait or self.trait_id}/",
            data={"score": score},
            content_type="application/json",
            HTTP_HOST=HOST,
        )

    def test_the_class_teacher_rates(self):
        """The control: every refusal below would pass against a route that
        refused everybody."""
        self.assertEqual(self.rate(self.teacher, 4).status_code, 200)

    def test_the_principal_does_not_rate(self):
        self.assertEqual(self.rate(self.head, 4).status_code, 403)

    def test_a_score_outside_the_scale_is_refused_with_a_sentence(self):
        response = self.rate(self.teacher, 99)

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()["detail"])

    def test_the_score_comes_back_on_the_next_read(self):
        self.rate(self.teacher, 4)

        body = self.child(self.teacher).json()

        self.assertEqual(body["sections"][0]["traits"][0]["score"], 4)
