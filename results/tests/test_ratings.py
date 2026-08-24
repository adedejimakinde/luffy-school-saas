"""Affective and psychomotor ratings: off by default, and frozen at release.

Two schools throughout, as everywhere in this project, and here the second one
earns its place twice over: the trait list is per schema, so a school that has
enabled the section and a school that has not must not see each other's
configuration *or* each other's ratings.

The sections:

- off by default, and off means **absent** — no section, not an empty one;
- one group on and the other off, which is the ordinary case;
- only the class teacher of the group may rate — not another teacher, not the
  administrator who may submit the sheet, not the principal;
- **the trait is the row, not the argument**: an instance claiming to be visible,
  or to belong to a section this school prints, or read on the other school's
  connection, is refused on what the schema on this connection actually says;
- a refusal says what went wrong — the write no longer answers every
  `IntegrityError` with "somebody else got there first";
- the scale is 1-5, refused at both layers;
- ratings are editable while the sheet is in `draft` and not after, and a
  send-back opens them again;
- **the freeze**: release a card, then rename, hide, reorder, relabel and
  disable, and the released card is unchanged — with a control proving the same
  edits do move a card that has *not* been released;
- the frozen rows are append-only, and a released term's live ratings are shut,
  both in the database rather than only in the service.

The rules that are only true under a second connection — the sheet's row lock,
and two tabs rating at once — are in `test_ratings_concurrency.py`, which needs
`TransactionTestCase` and real threads to say anything at all.
"""

import contextlib
from datetime import date

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from results import ratings, services
from results.models import (
    RatingScalePoint,
    ReleasedTraitRating,
    ReportCardSettings,
    Trait,
    TraitGroup,
    TraitRating,
)
from schools.models import School

PASSWORD = "correct-horse-battery"


def make_school(name, slug, schema_name):
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.save()
    return school


@contextlib.contextmanager
def connected_to(school):
    with schema_context(school.schema_name):
        yield


class RatingsSetUp(TestCase):
    """Two schools. St Mary's teaches JSS 1A (Kemi) and JSS 3B (Sade)."""

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.kemi = self._staff("kemi", "Kemi Bello", self.stmarys, Role.TEACHER)
        self.sade = self._staff("sade", "Sade Johnson", self.stmarys, Role.TEACHER)
        self.registrar = self._staff("bola", "Bola Ade", self.stmarys, Role.ADMIN)
        self.principal = self._staff(
            "tunde", "Tunde Alabi", self.stmarys, Role.PRINCIPAL
        )
        self.vp = self._staff(
            "ify", "Ify Nwosu", self.stmarys, Role.VICE_PRINCIPAL_ACADEMIC
        )
        self.their_teacher = self._staff("chika", "Chika Obi", self.grace, Role.TEACHER)

        self.ada = self._student("ada", "Ada Obi", self.stmarys)
        self.bisi = self._student("bisi", "Bisi Lawal", self.stmarys)
        self.their_child = self._student("ngozi", "Ngozi Eze", self.grace)

        self.term_id, self.jss1a_id, self.jss3b_id = self._academics(self.stmarys)
        self.their_term_id, self.their_jss1a_id, _ = self._academics(self.grace)

        self._assign(self.stmarys, self.kemi, self.jss1a_id, self.term_id)
        self._assign(self.stmarys, self.sade, self.jss3b_id, self.term_id)
        self._assign(
            self.grace, self.their_teacher, self.their_jss1a_id, self.their_term_id
        )

        self._place(self.stmarys, self.ada, self.jss1a_id, self.term_id)
        self._place(self.stmarys, self.bisi, self.jss1a_id, self.term_id)
        self._place(
            self.grace, self.their_child, self.their_jss1a_id, self.their_term_id
        )

    # -- fixtures ------------------------------------------------------------

    def _staff(self, username, full_name, school, role):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, school, role)
        return user

    def _student(self, username, full_name, school):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, school, Role.STUDENT)
        return user

    def _academics(self, school):
        with connected_to(school):
            term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )
            jss1a = ClassGroup.objects.create(name="JSS 1A", level=1)
            jss3b = ClassGroup.objects.create(name="JSS 3B", level=3)
            return term.pk, jss1a.pk, jss3b.pk

    def _assign(self, school, user, class_group_id, term_id):
        membership = user.memberships.get(school=school, role=Role.TEACHER)
        with connected_to(school):
            academics.assign_class_teacher(
                ClassGroup.objects.get(pk=class_group_id),
                Term.objects.get(pk=term_id),
                membership,
            )

    def _place(self, school, user, class_group_id, term_id):
        membership = self.membership_of(user, school)
        with connected_to(school):
            academics.place_student(
                ClassGroup.objects.get(pk=class_group_id),
                Term.objects.get(pk=term_id),
                membership,
            )

    def membership_of(self, user, school=None):
        return user.memberships.get(school=school or self.stmarys, role=Role.STUDENT)

    # -- shorthands ----------------------------------------------------------

    def term(self):
        return Term.objects.get(pk=self.term_id)

    def jss1a(self):
        return ClassGroup.objects.get(pk=self.jss1a_id)

    def trait(self, name, group=TraitGroup.AFFECTIVE):
        return Trait.objects.get(group=group, name=name)

    def enable(self, school, *groups):
        with connected_to(school):
            for group in groups:
                ratings.set_group_enabled(group, True)

    def rate(self, name, score, student=None, group=TraitGroup.AFFECTIVE):
        return ratings.rate_as(
            self.kemi,
            self.term(),
            self.trait(name, group),
            self.membership_of(student or self.ada),
            score,
        )

    def sections(self, student=None):
        return ratings.card_sections(
            self.membership_of(student or self.ada).pk, self.jss1a(), self.term()
        )

    def walk_to_released(self):
        """Take JSS 1A's sheet the whole way, with four different people.

        Refreshed before it is handed back, because every step in the chain
        writes the *row* it locked and not the instance it was passed — the
        distinction `a2a9656` was about. Without this the helper returns a sheet
        still claiming to be a draft, and a test asserting on `sheet.state`
        would be reading a copy four transitions out of date.
        """
        sheet = services.open_sheet(self.jss1a(), self.term(), self.principal)
        services.submit(sheet, self.kemi)
        services.check(sheet, self.vp)
        services.approve(sheet, self.principal)
        services.release(sheet, self.principal)
        sheet.refresh_from_db()
        return sheet

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()


class OffByDefaultTests(RatingsSetUp):
    """A school that has not asked for this must see no trace of it."""

    def test_both_sections_are_off_in_a_fresh_school(self):
        with connected_to(self.stmarys):
            self.assertFalse(ratings.is_enabled(TraitGroup.AFFECTIVE))
            self.assertFalse(ratings.is_enabled(TraitGroup.PSYCHOMOTOR))
            self.assertEqual(ratings.enabled_groups(), [])

    def test_the_card_has_no_section_at_all_not_an_empty_one(self):
        """The distinction the whole default turns on.

        An empty section is a heading and a rule across the page with nothing
        under it, which is worse than the feature being absent: it looks like
        the teacher forgot.
        """
        with connected_to(self.stmarys):
            self.assertEqual(self.sections(), [])

    def test_the_seeded_traits_are_there_to_be_turned_on(self):
        """Off is a setting, not an empty database.

        The seed exists so that a school saying yes finds a list already there.
        Counted rather than named: nothing in the code may depend on a
        particular seeded trait existing, because hiding it is the first thing
        the feature promises a school it may do.
        """
        with connected_to(self.stmarys):
            self.assertEqual(Trait.objects.in_group(TraitGroup.AFFECTIVE).count(), 7)
            self.assertEqual(Trait.objects.in_group(TraitGroup.PSYCHOMOTOR).count(), 4)
            self.assertEqual(RatingScalePoint.objects.count(), 5)
            self.assertEqual(
                list(RatingScalePoint.objects.values_list("value", flat=True)),
                [5, 4, 3, 2, 1],
                "the key on a card reads highest first",
            )

    def test_rating_is_refused_while_the_section_is_off(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ratings.SectionNotEnabled):
                self.rate("Punctuality", 5)

    def test_one_group_on_leaves_the_other_absent(self):
        """A school printing conduct and not skills is the ordinary case."""
        self.enable(self.stmarys, TraitGroup.AFFECTIVE)

        with connected_to(self.stmarys):
            headings = [section.group for section in self.sections()]

        self.assertEqual(headings, [TraitGroup.AFFECTIVE.value])

    def test_the_other_school_is_unaffected_by_ours_turning_it_on(self):
        self.enable(self.stmarys, TraitGroup.AFFECTIVE, TraitGroup.PSYCHOMOTOR)

        with connected_to(self.grace):
            self.assertEqual(ratings.enabled_groups(), [])
            self.assertEqual(
                ratings.card_sections(
                    self.membership_of(self.their_child, self.grace).pk,
                    ClassGroup.objects.get(pk=self.their_jss1a_id),
                    Term.objects.get(pk=self.their_term_id),
                ),
                [],
            )


class OnlyTheClassTeacherRatesTests(RatingsSetUp):
    """Narrower than submitting the sheet, and deliberately so.

    `SUBMITTING_ROLES` admits an administrator because transcribing a paper
    sheet is office work. A conduct rating has no paper behind it — it is a
    judgement about a child by the person who taught them — so there is no
    clerical version of it and no office exemption.
    """

    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE, TraitGroup.PSYCHOMOTOR)

    def test_the_class_teacher_may_rate_her_own_class(self):
        with connected_to(self.stmarys):
            rating = self.rate("Punctuality", 5)

        self.assertEqual(rating.score, 5)
        self.assertEqual(rating.rated_by_id, self.kemi.pk)

    def test_another_class_teacher_may_not(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ratings.NotAllowedToRate) as refused:
                ratings.rate_as(
                    self.sade,
                    self.term(),
                    self.trait("Punctuality"),
                    self.membership_of(self.ada),
                    5,
                )

        self.assertIn("not the class teacher", str(refused.exception))

    def test_the_administrator_may_not_rate_though_she_may_submit(self):
        """The divergence from `submit()`, pinned so it cannot drift back."""
        with connected_to(self.stmarys):
            with self.assertRaises(ratings.NotAllowedToRate) as refused:
                ratings.rate_as(
                    self.registrar,
                    self.term(),
                    self.trait("Punctuality"),
                    self.membership_of(self.ada),
                    5,
                )

        self.assertIn("not the office's to enter", str(refused.exception))

    def test_the_principal_may_not_rate_either(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ratings.NotAllowedToRate):
                ratings.rate_as(
                    self.principal,
                    self.term(),
                    self.trait("Punctuality"),
                    self.membership_of(self.ada),
                    5,
                )

    def test_the_other_schools_teacher_may_not_rate_our_child(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ratings.NotAllowedToRate):
                ratings.rate_as(
                    self.their_teacher,
                    self.term(),
                    self.trait("Punctuality"),
                    self.membership_of(self.ada),
                    5,
                )

    def test_a_group_with_no_class_teacher_says_so(self):
        with connected_to(self.stmarys):
            academics.unassign_class_teacher(self.jss1a(), self.term())

            with self.assertRaises(ratings.NotAllowedToRate) as refused:
                self.rate("Punctuality", 5)

        self.assertIn("has no class teacher", str(refused.exception))

    def test_a_child_in_no_class_group_cannot_be_rated(self):
        """No placement, no group; no group, no class teacher and no sheet."""
        with connected_to(self.stmarys):
            academics.remove_placement(self.term(), self.membership_of(self.ada))

            with self.assertRaises(ratings.NotPlacedThisTerm):
                self.rate("Punctuality", 5)

    def test_another_schools_child_is_not_ours_to_rate(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ratings.NotThisSchoolsStudent):
                ratings.rate_as(
                    self.kemi,
                    self.term(),
                    self.trait("Punctuality"),
                    self.membership_of(self.their_child, self.grace),
                    5,
                )


class TheScaleTests(RatingsSetUp):
    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE)

    def test_a_score_off_the_scale_is_refused(self):
        with connected_to(self.stmarys):
            for score in (0, 6, -1, 100):
                with self.subTest(score=score):
                    with self.assertRaises(ratings.RatingsError):
                        self.rate("Punctuality", score)

    def test_the_database_refuses_it_too(self):
        """The layer that holds when the service is bypassed."""
        with connected_to(self.stmarys):
            with self.assertRaises(Exception) as refused:
                with transaction.atomic():
                    TraitRating.objects.create(
                        term=self.term(),
                        student_membership_id=self.membership_of(self.ada).pk,
                        trait=self.trait("Punctuality"),
                        score=9,
                    )

        self.assertIn("a_rating_is_within_the_scale", str(refused.exception))

    def test_the_stored_integer_renders_as_the_schools_word(self):
        with connected_to(self.stmarys):
            self.rate("Punctuality", 4)
            line = self._line("Punctuality")

        self.assertEqual(line.score, 4)
        self.assertEqual(line.label, "Very Good")

    def test_a_school_may_rename_a_scale_point(self):
        with connected_to(self.stmarys):
            ratings.set_scale_label_as(self.principal, 4, "V. Good")
            self.rate("Punctuality", 4)
            self.assertEqual(self._line("Punctuality").label, "V. Good")

    def test_an_unrated_trait_prints_a_blank_line_not_a_zero(self):
        """`gradebook`'s rule, and for the same reason.

        A zero says the teacher looked and judged them lowest. A blank says
        nobody has said yet, and those are different sentences to a parent.
        """
        with connected_to(self.stmarys):
            line = self._line("Honesty")

        self.assertIsNone(line.score)
        self.assertEqual(line.label, "")
        self.assertFalse(line.is_rated)

    def _line(self, name):
        for section in self.sections():
            for line in section.lines:
                if line.name == name:
                    return line
        raise AssertionError(f"no line named {name!r}")


class TheTraitListIsTheSchoolsTests(RatingsSetUp):
    """Adding, hiding and reordering, none of which may need a migration."""

    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE)

    def names(self):
        [section] = self.sections()
        return [line.name for line in section.lines]

    def test_a_school_may_add_a_trait_and_it_lands_at_the_end(self):
        with connected_to(self.stmarys):
            ratings.add_trait_as(
                self.principal, TraitGroup.AFFECTIVE, "Respect for school property"
            )
            self.assertEqual(self.names()[-1], "Respect for school property")

    def test_a_school_may_hide_a_trait_and_it_leaves_the_sheet(self):
        with connected_to(self.stmarys):
            ratings.set_trait_hidden_as(self.principal, self.trait("Honesty"))
            self.assertNotIn("Honesty", self.names())

    def test_hiding_never_deletes(self):
        with connected_to(self.stmarys):
            ratings.set_trait_hidden_as(self.principal, self.trait("Honesty"))
            self.assertTrue(
                Trait.objects.filter(name="Honesty").exists(),
                "the row is what every past rating and released card names",
            )

    def test_a_hidden_trait_cannot_be_rated(self):
        with connected_to(self.stmarys):
            ratings.set_trait_hidden_as(self.principal, self.trait("Honesty"))
            with self.assertRaises(ratings.TraitIsHidden):
                self.rate("Honesty", 5)

    def test_a_school_may_reorder_and_the_order_is_not_alphabetical(self):
        with connected_to(self.stmarys):
            before = self.names()
            self.assertEqual(before[0], "Punctuality")

            wanted = ["Honesty", "Neatness", "Punctuality"]
            ratings.reorder_as(
                self.principal,
                TraitGroup.AFFECTIVE,
                [self.trait(name).pk for name in wanted],
            )
            after = self.names()

        self.assertEqual(after[:3], wanted)
        # And the traits the screen did not name follow the ones it did, in the
        # order they were already printing. The tail is the half that breaks
        # first: leave those rows where they were and one of them keeps a
        # position a named trait has just been given, so it prints *between*
        # two traits the school had just put next to each other.
        self.assertEqual(after[3:], [name for name in before if name not in wanted])

    def test_reordering_ignores_ids_from_another_group(self):
        """Reordering is not a way to move a trait between sections."""
        with connected_to(self.stmarys):
            handwriting = self.trait("Handwriting", TraitGroup.PSYCHOMOTOR)
            ratings.reorder_as(
                self.principal, TraitGroup.AFFECTIVE, [handwriting.pk]
            )
            handwriting.refresh_from_db()

        self.assertEqual(handwriting.group, TraitGroup.PSYCHOMOTOR)
        self.assertNotIn("Handwriting", self.names_in_schema())

    def names_in_schema(self):
        with connected_to(self.stmarys):
            return self.names()

    def test_only_the_office_may_change_the_list(self):
        with connected_to(self.stmarys):
            for actor in (self.kemi, self.vp):
                with self.subTest(actor=str(actor)):
                    with self.assertRaises(ratings.NotAllowedToConfigureRatings):
                        ratings.add_trait_as(actor, TraitGroup.AFFECTIVE, "Diligence")

    def test_a_teacher_may_not_turn_a_section_on(self):
        with connected_to(self.stmarys):
            with self.assertRaises(ratings.NotAllowedToConfigureRatings):
                ratings.set_group_enabled_as(self.kemi, TraitGroup.PSYCHOMOTOR, True)

    def test_one_schools_trait_list_is_not_the_others(self):
        with connected_to(self.stmarys):
            ratings.add_trait_as(self.principal, TraitGroup.AFFECTIVE, "Diligence")

        with connected_to(self.grace):
            self.assertFalse(Trait.objects.filter(name="Diligence").exists())


class TheTraitIsTheRowNotTheArgumentTests(RatingsSetUp):
    """The checks and the write have to be about the same trait.

    `_require_a_ratable_trait()` reads `is_hidden` and `group`; the write uses
    `pk` alone. Trust the instance for the first and the row for the second and
    they are two different traits — the shape `a2a9656` corrected in
    `_require_class_teacher_scope()`, one module along.

    None of these instances is exotic. A `Trait` deserialised from a cache, one
    carried over from an earlier request, or one read on another school's
    connection all arrive looking exactly like this.
    """

    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE)

    def test_a_hidden_trait_cannot_be_rated_by_an_instance_that_says_otherwise(self):
        with connected_to(self.stmarys):
            honesty = self.trait("Honesty")
            ratings.set_trait_hidden_as(self.principal, honesty)

            claiming_to_be_visible = Trait(
                pk=honesty.pk, group=honesty.group, name=honesty.name, is_hidden=False
            )
            with self.assertRaises(ratings.TraitIsHidden):
                ratings.rate_as(
                    self.kemi,
                    self.term(),
                    claiming_to_be_visible,
                    self.membership_of(self.ada),
                    5,
                )

            self.assertFalse(
                TraitRating.objects.exists(), "the refused rating must not have landed"
            )

    def test_a_section_this_school_does_not_print_cannot_be_rated_either(self):
        """The same hole, through `group` instead of `is_hidden`.

        Psychomotor is off at St Mary's. An instance naming a psychomotor row by
        `pk` while claiming to be affective passes an enabled-section check made
        on the argument, and writes a rating into a section the school does not
        print.
        """
        with connected_to(self.stmarys):
            handwriting = self.trait("Handwriting", TraitGroup.PSYCHOMOTOR)
            claiming_to_be_affective = Trait(
                pk=handwriting.pk,
                group=TraitGroup.AFFECTIVE,
                name=handwriting.name,
                is_hidden=False,
            )
            with self.assertRaises(ratings.SectionNotEnabled):
                ratings.rate_as(
                    self.kemi,
                    self.term(),
                    claiming_to_be_affective,
                    self.membership_of(self.ada),
                    5,
                )

            self.assertFalse(TraitRating.objects.exists())

    def test_a_trait_read_on_the_other_schools_connection_is_not_ours(self):
        """Two schools, and the ids coincide — which is what makes this bite.

        Every schema is seeded by the same migration in the same order, so
        Grace Academy's "Honesty" and St Mary's "Honesty" hold the same `pk` out
        of two different sequences. Hide it here, leave it showing there, and an
        instance read on their connection is a row that says "visible" and a
        `pk` that names a hidden trait of ours.
        """
        with connected_to(self.stmarys):
            ours = self.trait("Honesty")
            ratings.set_trait_hidden_as(self.principal, ours)

        with connected_to(self.grace):
            theirs = Trait.objects.get(group=TraitGroup.AFFECTIVE, name="Honesty")

        self.assertEqual(
            theirs.pk,
            ours.pk,
            "the schemas seed identically; if that changes this test no longer "
            "reaches the confusion it was written for",
        )
        self.assertFalse(theirs.is_hidden, "hidden at St Mary's only")

        with connected_to(self.stmarys):
            with self.assertRaises(ratings.TraitIsHidden):
                ratings.rate_as(
                    self.kemi,
                    self.term(),
                    theirs,
                    self.membership_of(self.ada),
                    5,
                )

            self.assertFalse(TraitRating.objects.exists())


class ARefusedWriteSaysWhatWentWrongTests(RatingsSetUp):
    """`rate()` had an `except IntegrityError` that answered for all of them.

    It was written for the insert race — two tabs, neither finding a row, both
    inserting — and retried as an `UPDATE`. Django's `update_or_create()`
    already locks and recovers from that race itself, so what the branch caught
    was the *other* refusals: the `CHECK` behind a bare id, the foreign key onto
    a trait deleted meanwhile, and migration `0007`'s trigger, which raises
    `restrict_violation` and so also arrives as `IntegrityError`. Each was
    retried as an `UPDATE` matching nothing and then re-read, turning a sentence
    written for a teacher into `TraitRating matching query does not exist`.

    `gradebook.tests.test_scores` pins the same discrimination one app along.
    """

    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE)

    def test_an_integrity_error_that_is_not_a_collision_is_not_relabelled(self):
        """`rated_by_id` is a bare id with `CHECK (... >= 0)` behind it.

        A negative stamp is therefore a genuine, synchronous, non-collision
        `IntegrityError` at INSERT — exactly the kind that must reach the caller
        as itself.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                ratings.rate(
                    self.term(),
                    self.trait("Punctuality"),
                    self.membership_of(self.ada),
                    4,
                    by=-1,
                )

            self.assertFalse(TraitRating.objects.exists())

    def test_a_refusal_leaves_the_surrounding_transaction_usable(self):
        """A whole class is one transaction, and one refused row is not fatal.

        The write takes its own `atomic()` block for this: an `IntegrityError`
        marks the enclosing transaction unusable, so without the savepoint a
        caller who caught the refusal could not go on to the next child.
        """
        with connected_to(self.stmarys):
            with transaction.atomic():
                with self.assertRaises(IntegrityError):
                    ratings.rate(
                        self.term(),
                        self.trait("Punctuality"),
                        self.membership_of(self.ada),
                        4,
                        by=-1,
                    )

                self.assertEqual(
                    ratings.rate(
                        self.term(),
                        self.trait("Punctuality"),
                        self.membership_of(self.bisi),
                        4,
                    ).score,
                    4,
                )

    def test_the_first_rater_is_still_named_after_somebody_corrects_it(self):
        """Two columns that always agreed would be one column.

        `rated_by_id` is written at the insert and never again; `updated_by_id`
        moves. Passing both in `defaults` — which is what a single dict does —
        had every correction overwrite the teacher who made the judgement with
        whoever last touched the row.

        The timestamps say the same thing from the other side: `created_at` is
        when the judgement was entered and does not move, `updated_at` is when
        it was last touched and does.

        **What is not kept is the old score.** A correction overwrites it, and
        there is no rating history table — `ResultSheetTransition` is the log of
        how the *sheet* moved, not of what a mark was before. What survives a
        correction is who first rated, when, who last changed it, when, and the
        value now. If a school ever needs "she was a 3 in March", that is an
        append-only history to build deliberately, not something this row
        happens to remember.
        """
        with connected_to(self.stmarys):
            first = ratings.rate(
                self.term(),
                self.trait("Punctuality"),
                self.membership_of(self.ada),
                3,
                by=self.kemi,
            )
            entered_at, first_touch = first.created_at, first.updated_at

            corrected = ratings.rate(
                self.term(),
                self.trait("Punctuality"),
                self.membership_of(self.ada),
                5,
                by=self.principal,
            )

            self.assertEqual(
                TraitRating.objects.count(), 1, "a correction leaves one row, not two"
            )

        self.assertEqual(corrected.pk, first.pk, "a correction, not a second row")
        self.assertEqual(corrected.score, 5)
        self.assertEqual(corrected.rated_by_id, self.kemi.pk)
        self.assertEqual(corrected.updated_by_id, self.principal.pk)
        self.assertEqual(
            corrected.created_at, entered_at, "when it was entered does not move"
        )
        self.assertGreater(
            corrected.updated_at, first_touch, "when it was last touched does"
        )


class RatingsFollowTheChainTests(RatingsSetUp):
    """Part of what gets submitted, checked and approved — so they stop moving."""

    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE)

    def test_ratings_may_be_entered_before_the_sheet_exists(self):
        with connected_to(self.stmarys):
            self.assertIsNone(ratings.sheet_for(self.jss1a(), self.term()))
            self.assertEqual(self.rate("Punctuality", 5).score, 5)

    def test_a_submitted_sheet_shuts_its_ratings(self):
        with connected_to(self.stmarys):
            self.rate("Punctuality", 5)
            sheet = services.open_sheet(self.jss1a(), self.term(), self.principal)
            services.submit(sheet, self.kemi)

            with self.assertRaises(ratings.RatingsLocked) as refused:
                self.rate("Punctuality", 3)

        self.assertEqual(refused.exception.state, "submitted")
        self.assertIn("being reviewed", str(refused.exception))

    def test_a_send_back_opens_them_again(self):
        """The reason the test is `draft` rather than "never submitted".

        A vice principal who sends the sheet back because a rating is wrong has
        to leave the teacher able to fix it.
        """
        with connected_to(self.stmarys):
            self.rate("Punctuality", 5)
            sheet = services.open_sheet(self.jss1a(), self.term(), self.principal)
            services.submit(sheet, self.kemi)
            services.send_back(sheet, self.vp, "Ada's punctuality looks wrong.")

            self.assertEqual(self.rate("Punctuality", 3).score, 3)

    def test_a_released_sheet_shuts_them_for_good(self):
        with connected_to(self.stmarys):
            self.rate("Punctuality", 5)
            self.walk_to_released()

            with self.assertRaises(ratings.RatingsLocked) as refused:
                self.rate("Punctuality", 3)

        self.assertEqual(refused.exception.state, "released")
        self.assertIn("revision", str(refused.exception))

    def test_another_classs_sheet_does_not_shut_ours(self):
        """The lock is per class group, not per term."""
        with connected_to(self.stmarys):
            jss3b = ClassGroup.objects.get(pk=self.jss3b_id)
            other = services.open_sheet(jss3b, self.term(), self.principal)
            services.submit(other, self.sade)

            self.assertEqual(self.rate("Punctuality", 5).score, 5)

    def test_the_database_shuts_them_too(self):
        """The service is not the guarantee — an import never calls it.

        Narrow on purpose: the trigger fires for `released` only, which is the
        state with no legitimate exception. The in-review states are the
        service's to hold, for the reason migration 0007 sets out.
        """
        with connected_to(self.stmarys):
            self.rate("Punctuality", 5)
            self.walk_to_released()

            with self.assertRaises(IntegrityError) as refused:
                with transaction.atomic():
                    TraitRating.objects.filter(
                        term=self.term(), trait=self.trait("Punctuality")
                    ).update(score=1)

        self.assertIn("released", str(refused.exception))

    def test_the_database_refuses_a_new_rating_for_a_released_term(self):
        with connected_to(self.stmarys):
            self.walk_to_released()

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    TraitRating.objects.create(
                        term=self.term(),
                        student_membership_id=self.membership_of(self.ada).pk,
                        trait=self.trait("Honesty"),
                        score=5,
                    )


class TheFreezeTests(RatingsSetUp):
    """**The one to get right.** A released card does not change. Ever.

    Release a card, then do every edit a school legitimately makes to its own
    configuration — rename a trait, hide one, reorder the section, relabel the
    scale, turn the whole section off — and the released card must read exactly
    as it did.

    Each of those reaches the card by a different join, which is why the test
    does all five rather than one: renaming goes through `Trait.name`, hiding
    through `is_hidden`, reordering through `position`, relabelling through
    `RatingScalePoint`, and disabling through `ReportCardSettings`. A freeze that
    caught four of the five would pass a smaller test.
    """

    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE, TraitGroup.PSYCHOMOTOR)

    def rate_the_class(self):
        with connected_to(self.stmarys):
            self.rate("Punctuality", 5)
            self.rate("Neatness", 4)
            self.rate("Honesty", 3)
            self.rate("Handwriting", 2, group=TraitGroup.PSYCHOMOTOR)
            self.rate("Punctuality", 2, student=self.bisi)

    def rendered(self, student=None):
        """The card as text: heading, then each line and what it says."""
        return [
            (section.heading, [(line.name, line.score, line.label) for line in section.lines])
            for section in self.sections(student)
        ]

    def churn_the_configuration(self):
        """Every edit a school might make next term. None may reach backwards."""
        with connected_to(self.stmarys):
            ratings.rename_trait_as(self.principal, self.trait("Neatness"), "Tidiness")
            ratings.set_trait_hidden_as(self.principal, self.trait("Honesty"))
            ratings.reorder_as(
                self.principal,
                TraitGroup.AFFECTIVE,
                [
                    self.trait("Relationship with others").pk,
                    self.trait("Punctuality").pk,
                ],
            )
            ratings.set_scale_label_as(self.principal, 5, "Outstanding")
            ratings.set_group_enabled_as(
                self.principal, TraitGroup.PSYCHOMOTOR, False
            )

    def test_a_released_card_survives_every_edit_to_the_trait_list(self):
        self.rate_the_class()

        with connected_to(self.stmarys):
            self.walk_to_released()
            before = self.rendered()

        self.churn_the_configuration()

        with connected_to(self.stmarys):
            after = self.rendered()

        self.assertEqual(after, before)

    def test_and_the_card_it_survived_as_is_the_right_one(self):
        """A freeze that returned nothing would also survive every edit.

        So the invariant needs a witness: this asserts what the card actually
        says, in order, before anybody touches anything.
        """
        self.rate_the_class()

        with connected_to(self.stmarys):
            self.walk_to_released()
            card = self.rendered()

        self.assertEqual(
            card,
            [
                (
                    "Affective (conduct)",
                    [
                        ("Punctuality", 5, "Excellent"),
                        ("Attendance", None, ""),
                        ("Neatness", 4, "Very Good"),
                        ("Politeness", None, ""),
                        ("Honesty", 3, "Good"),
                        ("Attentiveness in class", None, ""),
                        ("Relationship with others", None, ""),
                    ],
                ),
                (
                    "Psychomotor (skills)",
                    [
                        ("Handwriting", 2, "Fair"),
                        ("Games/Sports", None, ""),
                        ("Drawing/Craft", None, ""),
                        ("Handling of tools and equipment", None, ""),
                    ],
                ),
            ],
        )

    def test_the_control_the_same_edits_do_move_an_unreleased_card(self):
        """The control, and without it the test above proves nothing.

        If `card_sections()` were simply insensitive to configuration — reading
        some cache, or returning a fixed list — the freeze test would pass with
        no freeze in it at all. So: the identical five edits, against a card
        that has *not* been released, must change it.
        """
        self.rate_the_class()

        with connected_to(self.stmarys):
            before = self.rendered()

        self.churn_the_configuration()

        with connected_to(self.stmarys):
            after = self.rendered()

        self.assertNotEqual(after, before)

        headings = [heading for heading, _ in after]
        self.assertEqual(
            headings,
            ["Affective (conduct)"],
            "the psychomotor section was turned off and must be gone entirely",
        )
        names = [name for _, lines in after for name, _, _ in lines]
        self.assertIn("Tidiness", names)
        self.assertNotIn("Neatness", names)
        self.assertNotIn("Honesty", names)
        self.assertEqual(names[0], "Relationship with others")

    def test_the_freeze_records_the_traits_nobody_rated(self):
        """What is frozen is the section, not only the marks in it.

        "Which traits existed and in what order" is precisely what a later edit
        rewrites, so an unrated trait needs a row saying it was there and blank.
        """
        self.rate_the_class()

        with connected_to(self.stmarys):
            sheet = self.walk_to_released()
            frozen = ReleasedTraitRating.objects.filter(
                sheet=sheet, student_membership_id=self.membership_of(self.ada).pk
            )

            self.assertEqual(frozen.count(), 11, "seven affective, four psychomotor")
            self.assertEqual(frozen.filter(score__isnull=True).count(), 7)

    def test_every_child_on_the_roster_is_frozen_not_only_the_rated_ones(self):
        self.rate_the_class()

        with connected_to(self.stmarys):
            sheet = self.walk_to_released()
            self.assertEqual(
                ReleasedTraitRating.objects.filter(sheet=sheet).count(),
                22,
                "two children on the roster, eleven traits each",
            )

    def test_a_school_with_the_feature_off_freezes_nothing(self):
        """And its released card renders with no section, for ever."""
        with connected_to(self.stmarys):
            ratings.set_group_enabled(TraitGroup.AFFECTIVE, False)
            ratings.set_group_enabled(TraitGroup.PSYCHOMOTOR, False)

            sheet = self.walk_to_released()
            self.assertEqual(
                ReleasedTraitRating.objects.filter(sheet=sheet).count(), 0
            )
            self.assertEqual(self.sections(), [])

            # And turning it on afterwards must not retrofit a section onto a
            # card that went home without one.
            ratings.set_group_enabled(TraitGroup.AFFECTIVE, True)
            self.assertEqual(self.sections(), [])

    def test_the_frozen_rows_are_append_only_in_the_database(self):
        """`.update()` never calls `save()`, which is why the trigger exists."""
        self.rate_the_class()

        with connected_to(self.stmarys):
            sheet = self.walk_to_released()

            with self.assertRaises(IntegrityError) as refused:
                with transaction.atomic():
                    ReleasedTraitRating.objects.filter(sheet=sheet).update(score=1)

            self.assertIn("append-only", str(refused.exception))

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedTraitRating.objects.filter(sheet=sheet).delete()

    def test_the_model_refuses_before_the_database_has_to(self):
        self.rate_the_class()

        with connected_to(self.stmarys):
            sheet = self.walk_to_released()
            row = ReleasedTraitRating.objects.filter(sheet=sheet).first()
            row.score = 1

            with self.assertRaises(Exception) as refused:
                row.save()

        self.assertIn("released", str(refused.exception))

    def test_the_other_schools_card_is_untouched_by_our_release(self):
        self.rate_the_class()

        with connected_to(self.stmarys):
            self.walk_to_released()

        with connected_to(self.grace):
            self.assertEqual(ReleasedTraitRating.objects.count(), 0)


class UnratedTests(RatingsSetUp):
    """A report, not a rule. The school decides whether a blank line matters."""

    def setUp(self):
        super().setUp()
        self.enable(self.stmarys, TraitGroup.AFFECTIVE)

    def test_it_lists_what_is_still_to_do(self):
        with connected_to(self.stmarys):
            self.rate("Punctuality", 5)
            missing = ratings.unrated(self.jss1a(), self.term())

        ada = self.membership_of(self.ada).pk
        self.assertEqual(len(missing[ada]), 6)
        self.assertNotIn("Punctuality", missing[ada])

    def test_it_does_not_block_release(self):
        """Deliberate. Blocking would be this module inventing a school policy."""
        with connected_to(self.stmarys):
            sheet = self.walk_to_released()

        self.assertEqual(sheet.state, "released")
