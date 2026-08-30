"""What a release does when the roster moves underneath it. Issue #43.

`release()` freezes four things in one transaction, and the lock `_move()` takes
is on the **`ResultSheet` row** and reaches no further. `ClassPlacement` is not
locked, not joined to that row, and not covered by anything else — so the office
can put a child into the class being released at any point during the freeze, and
Postgres will let them.

That was survivable while each freeze read the roster for itself and disagreeing
about one child cost one inconsistent section. It stopped being survivable when
`ReleasedCard.card_id` became NOT NULL: the second roster read returned a child
the card freeze had never seen, `card_by_student.get()` returned `None`, and the
whole class's release died on

    IntegrityError: null value in column "card_id" ... violates not-null constraint

which names a column, not a cause, on the screen of a principal who pressed
release and has no idea a placement landed underneath them.

## Why this file needs threads

A `TestCase` wraps the whole test in one transaction, so a placement written
inside it is the releasing transaction's own uncommitted work and every read sees
it — which is the wrong shape entirely. The race is *another session committing*
between two statements of ours. So: `TransactionTestCase`, a real second
connection, and a real commit, exactly as `test_ratings_concurrency` and
`test_approval_concurrency` do it.

**The timing is not left to the scheduler.** `cards.freeze_for_release()` is
wrapped, and the placing thread is started and joined inside that wrapper, so the
commit lands between the card freeze and the section freezes every single run.
A test that raced for real would pass by luck most of the time, which is worse
than not having it.

## What is asserted, and what it would have said before

Two claims, and they are different:

1. The release **completes**, and completes whole.
2. Who was on it was decided **once**. The child placed mid-release is not on
   this release at all — no card, no conduct section, no remark — because the
   roster the cards were written for is the roster everything else uses.

The second is the one that says the fix is the fix rather than a swallowed
error. Reverting `ratings`/`comments`/`sessions` to `positions.roster_ids()` and
`.get()` fails the first with the `IntegrityError` above; the control run is in
the PR.

Two schools, and Grace is used rather than built and ignored: the placing thread
resolves its own school from `connection.schema_name`, so a thread whose
`search_path` were wrong would write into the other school's schema and no
single-tenant test could tell that apart from working.
"""

import contextlib
import threading
from datetime import date
from unittest import mock

from django.db import connection, connections
from django.test import SimpleTestCase, TransactionTestCase
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from gradebook.models import Assessment, Score, Subject
from results import cards, comments, services
from results import ratings
from results.models import (
    CommentAuthor,
    ReleasedCard,
    ReleasedComment,
    ReleasedSessionResult,
    ReleasedSubjectResult,
    ReleasedTraitRating,
    SheetState,
    TraitGroup,
)
from schools.models import School

PASSWORD = "correct-horse-battery"
SESSION = "2025/2026"

TERM_DATES = {
    TermName.FIRST.value: (date(2025, 9, 15), date(2025, 12, 12)),
    TermName.SECOND.value: (date(2026, 1, 12), date(2026, 4, 2)),
    TermName.THIRD.value: (date(2026, 4, 27), date(2026, 7, 24)),
}


@contextlib.contextmanager
def connected_to(school):
    with schema_context(school.schema_name):
        yield


class ReleaseUnderARosterChangeSetUp(TransactionTestCase):
    """St Mary's releases JSS 1A's third term. Grace Academy releases nothing.

    Third term deliberately: it is the only one where `sessions.freeze_for_release()`
    writes anything, so all three section freezes run and all three have to agree
    with the cards about who is on the roster.

    Ada is placed in all three terms and marked, and has a remark, so every
    section has a row to write. Bola is **enrolled and not placed** — she is the
    child the office puts into the class while the release is running.
    """

    def setUp(self):
        self.school = self._school("St Mary's", "st-marys", "st_marys")
        self.other_school = self._school("Grace Academy", "grace", "grace")

        self.teacher = self._staff("kemi", "Kemi Bello", self.school, Role.TEACHER)
        self.vp = self._staff(
            "ify", "Ify Nwosu", self.school, Role.VICE_PRINCIPAL_ACADEMIC
        )
        self.principal = self._staff(
            "tunde", "Tunde Alabi", self.school, Role.PRINCIPAL
        )

        self.ada = self._student("ada", "Ada Obi", self.school)
        #: Enrolled, deliberately not placed. The office places her mid-release.
        self.bola = self._student("bola", "Bola Eze", self.school)

        self.terms, self.group_id, self.subject_id = self._academics(
            self.school, self.teacher
        )
        self._place(self.school, self.ada, every_term=True)
        self._mark(self.school, TermName.THIRD.value, self.ada, 80)
        self._remark(self.school, TermName.THIRD.value, self.ada)

        # Grace, built the same way and released never. The placing thread must
        # not be able to reach it.
        #
        # Ngozi is placed *and* marked *and* remarked, so Grace holds everything
        # a release would freeze. A second school with nothing in it can only
        # prove that nothing was written where there was nothing to write; this
        # one has a card's worth of content sitting there, and the assertion that
        # no `ReleasedCard`, `ReleasedSubjectResult` or `ReleasedComment` exists
        # in Grace is therefore about the release and not about the fixture.
        self.their_teacher = self._staff(
            "chika", "Chika Obi", self.other_school, Role.TEACHER
        )
        self.their_principal = self._staff(
            "amaka", "Amaka Udo", self.other_school, Role.PRINCIPAL
        )
        self.their_child = self._student("ngozi", "Ngozi Eze", self.other_school)
        (
            self.their_terms,
            self.their_group_id,
            self.their_subject_id,
        ) = self._academics(self.other_school, self.their_teacher)
        self._place(self.other_school, self.their_child, every_term=True)
        self._mark(self.other_school, TermName.THIRD.value, self.their_child, 91)
        self._remark(self.other_school, TermName.THIRD.value, self.their_child)

    # -- fixtures ------------------------------------------------------------

    def _school(self, name, slug, schema_name):
        school = School(name=name, slug=slug, schema_name=schema_name)
        school.save()
        return school

    def _staff(self, username, full_name, school, role):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        grant_membership(user, school, role)
        return user

    def _student(self, username, full_name, school):
        user = User.objects.create_user(username, PASSWORD, full_name=full_name)
        return enroll_student(user, school)

    def _academics(self, school, teacher):
        with connected_to(school):
            terms = {}
            for name, (starts_on, ends_on) in TERM_DATES.items():
                terms[name] = Term.objects.create(
                    session=SESSION, name=name, starts_on=starts_on, ends_on=ends_on
                ).pk
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            subject = Subject.objects.create(name="Mathematics", code="MTH")
            teaching = teacher.memberships.get(school=school, role=Role.TEACHER)
            for term_id in terms.values():
                academics.assign_class_teacher(
                    group, Term.objects.get(pk=term_id), teaching
                )
            ratings.set_group_enabled(TraitGroup.AFFECTIVE, True)
            return terms, group.pk, subject.pk

    def _place(self, school, membership, *, every_term):
        terms = self.terms if school == self.school else self.their_terms
        group_id = self.group_id if school == self.school else self.their_group_id
        names = list(TERM_DATES) if every_term else [TermName.THIRD.value]
        with connected_to(school):
            group = ClassGroup.objects.get(pk=group_id)
            for name in names:
                academics.place_student(
                    group, Term.objects.get(pk=terms[name]), membership
                )

    def _mark(self, school, term_name, membership, value):
        """A mark for this child, in *this* school's term and subject.

        The branch is not decoration. Each tenant schema has its own sequences,
        so `Term.objects.get(pk=self.terms[...])` inside Grace's schema resolves
        to a different, existing Grace term with the same id rather than raising
        — a helper that took `school` and then read St Mary's ids would mark the
        wrong term in the wrong school and every assertion would stay green.
        `_place()` branches for the same reason.
        """
        terms = self.terms if school == self.school else self.their_terms
        subject_id = (
            self.subject_id if school == self.school else self.their_subject_id
        )
        with connected_to(school):
            term = Term.objects.get(pk=terms[term_name])
            assessment, _ = Assessment.objects.get_or_create(
                term=term,
                subject_id=subject_id,
                name="Exam",
                defaults={"max_score": 100},
            )
            Score.objects.create(
                assessment=assessment,
                student_membership_id=membership.pk,
                value=value,
            )

    def _remark(self, school, term_name, membership):
        """A principal's remark for this child. Branches as `_mark()` does."""
        terms = self.terms if school == self.school else self.their_terms
        principal = (
            self.principal if school == self.school else self.their_principal
        )
        with connected_to(school):
            comments.write_as(
                principal,
                Term.objects.get(pk=terms[term_name]),
                membership,
                CommentAuthor.PRINCIPAL,
                "A good term's work.",
            )

    # -- shorthands ----------------------------------------------------------

    def term(self, name=TermName.THIRD.value):
        return Term.objects.get(pk=self.terms[name])

    def group(self):
        return ClassGroup.objects.get(pk=self.group_id)

    def approve_the_third_term(self):
        """Everything up to but not including release."""
        with connected_to(self.school):
            sheet = services.open_sheet(self.group(), self.term(), self.principal)
            services.submit(sheet, self.teacher)
            services.check(sheet, self.vp)
            services.approve(sheet, self.principal)
            return sheet.pk

    def place_bola_from_another_connection(self):
        """Commit a placement into the class being released, from its own session.

        A thread, because it needs a connection of its own: the point of the
        whole file is that this is *another session's committed work* arriving
        between two of the releasing transaction's statements. Started and joined
        by the caller, so the commit is done before this returns.
        """
        failed = []

        def run():
            try:
                with connected_to(self.school):
                    academics.place_student(
                        ClassGroup.objects.get(pk=self.group_id),
                        Term.objects.get(pk=self.terms[TermName.THIRD.value]),
                        self.bola,
                    )
            except Exception as exc:  # noqa: BLE001 — reported, never swallowed
                failed.append(exc)
            finally:
                connections.close_all()

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(15)
        self.assertFalse(thread.is_alive(), "the placing thread never finished")
        self.assertEqual(failed, [], f"the placing thread failed: {failed}")

    def release_while_the_roster_moves(self):
        """Release, with the placement committing between the two roster reads.

        The wrapper is on `cards.freeze_for_release` and the commit happens after
        it returns, which is precisely the gap #43 is about: the cards have been
        written for the roster as it was, and the section freezes have not run
        yet. Deterministic on purpose — see the module docstring.
        """
        real = cards.freeze_for_release
        landed = []

        def freeze_then_let_the_office_in(*args, **kwargs):
            card_by_student = real(*args, **kwargs)
            self.place_bola_from_another_connection()
            landed.append(True)
            return card_by_student

        with connected_to(self.school):
            sheet = services.sheet_for(self.group(), self.term())
            with mock.patch.object(
                cards, "freeze_for_release", freeze_then_let_the_office_in
            ):
                services.release(sheet, self.principal)

        self.assertEqual(landed, [True], "the placement never landed mid-release")

    def tearDown(self):
        connection.set_schema_to_public()
        # Drop the schemas, not just the rows. `TransactionTestCase` flushes the
        # public tables, which removes the `School` rows — but a tenant schema is
        # not a table and survives into the next test's `setUp()`.
        # `test_approval_concurrency` sets this out at length, and #20 tracks the
        # fact that every one of these files copies it by hand.
        with connection.cursor() as cursor:
            for school in (self.school, self.other_school):
                cursor.execute(f'DROP SCHEMA IF EXISTS "{school.schema_name}" CASCADE')
        super().tearDown()


class TheRosterIsReadOnceTests(ReleaseUnderARosterChangeSetUp):
    """A placement committed mid-release no longer decides anything.

    Before #43's fix these two tests were one crash: `ratings` re-read the roster,
    found Bola, asked the card map for her card, got `None`, and the release died
    on a NOT NULL. Now the card freeze's roster is the only roster, so Bola is
    simply not on this release — which is the truthful answer, since she was not
    in the class when the cards were written.
    """

    def test_the_precondition_bola_really_does_land_mid_release(self):
        """The control for everything below. Without it these pass by no race.

        A test that asserts a release survived a race it never had is a test that
        passes for the wrong reason, and this file's whole subject is a bug that
        only appears when the placement is genuinely there and genuinely
        committed by somebody else.
        """
        self.approve_the_third_term()
        self.release_while_the_roster_moves()

        with connected_to(self.school):
            placed = academics.placement_of(
                self.bola.pk, Term.objects.get(pk=self.terms[TermName.THIRD.value])
            )
            group_name = placed.class_group.name if placed else None

        self.assertIsNotNone(placed, "the placement never committed")
        self.assertEqual(group_name, "JSS 1A", "she landed in the wrong class")

    def test_the_release_completes_instead_of_dying_on_a_null_column(self):
        self.approve_the_third_term()
        self.release_while_the_roster_moves()

        with connected_to(self.school):
            sheet = services.sheet_for(self.group(), self.term())
            state = sheet.state

        self.assertEqual(state, SheetState.RELEASED)

    def test_the_child_who_arrived_mid_release_is_not_on_it(self):
        """No card, and therefore no section — the two go together by design.

        The alternative, a card with nothing on it, is what issue #31 is about.
        The roster is decided once, and she was not on it.
        """
        self.approve_the_third_term()
        self.release_while_the_roster_moves()

        with connected_to(self.school):
            hers = {
                "cards": ReleasedCard.objects.filter(
                    student_membership_id=self.bola.pk
                ).count(),
                "ratings": ReleasedTraitRating.objects.filter(
                    student_membership_id=self.bola.pk
                ).count(),
                "comments": ReleasedComment.objects.filter(
                    student_membership_id=self.bola.pk
                ).count(),
                "sessions": ReleasedSessionResult.objects.filter(
                    student_membership_id=self.bola.pk
                ).count(),
            }

        self.assertEqual(hers, {"cards": 0, "ratings": 0, "comments": 0, "sessions": 0})

    def test_the_omission_is_written_down_instead_of_passing_in_silence(self):
        """She is off the release, and the release says so somewhere.

        Being off it is the truthful outcome; being off it *quietly* is not. The
        principal sees a release that succeeded, and one child has no card, no
        sections, and — until task 8's revision path exists — no way to be given
        them, because `_move()` refuses a released sheet and the correction paths
        reach it through her current placement, which is now this released class.
        Issue #31 is that dead end and #47 is putting this in front of a person
        rather than only in a log.
        """
        self.approve_the_third_term()

        with self.assertLogs("results.services", level="WARNING") as logged:
            self.release_while_the_roster_moves()

        said = "\n".join(logged.output)
        self.assertIn(str(self.bola.pk), said, "the log does not name the child")
        self.assertIn("JSS 1A", said)
        self.assertIn("no released card", said)

    def test_an_undisturbed_release_says_nothing(self):
        """The control. A warning logged every time would pass the test above.

        `assertNoLogs` and not an absent `assertLogs`: the point is that the
        quiet case is quiet, and a release nobody interfered with is the case
        that runs every day.
        """
        self.approve_the_third_term()

        with self.assertNoLogs("results.services", level="WARNING"):
            with connected_to(self.school):
                sheet = services.sheet_for(self.group(), self.term())
                services.release(sheet, self.principal)

        with connected_to(self.school):
            self.assertEqual(
                ReleasedCard.objects.filter(
                    student_membership_id=self.ada.pk
                ).count(),
                1,
                "the undisturbed release did not actually release anything",
            )

    def test_the_child_who_was_on_the_roster_got_the_whole_card(self):
        """The other half. A release that froze nothing would pass the test above.

        All four, because the bug was in the three that hang off the first, and a
        release that wrote cards and no sections would be the same failure wearing
        a different face.
        """
        self.approve_the_third_term()
        self.release_while_the_roster_moves()

        with connected_to(self.school):
            hers = {
                "cards": ReleasedCard.objects.filter(
                    student_membership_id=self.ada.pk
                ).count(),
                "ratings": ReleasedTraitRating.objects.filter(
                    student_membership_id=self.ada.pk
                ).count()
                > 0,
                "comments": ReleasedComment.objects.filter(
                    student_membership_id=self.ada.pk
                ).count(),
                "sessions": ReleasedSessionResult.objects.filter(
                    student_membership_id=self.ada.pk
                ).count(),
            }

        self.assertEqual(
            hers, {"cards": 1, "ratings": True, "comments": 1, "sessions": 1}
        )

    def test_every_frozen_row_points_at_a_card_of_this_release(self):
        """The invariant the null column was the symptom of.

        Counting rows is not enough: a section row could hang off some other
        release's card and every count above would still be right.
        """
        self.approve_the_third_term()
        self.release_while_the_roster_moves()

        with connected_to(self.school):
            card_ids = set(
                ReleasedCard.objects.values_list("pk", flat=True)
            )
            hanging = {
                "ratings": set(
                    ReleasedTraitRating.objects.values_list("card_id", flat=True)
                ),
                "comments": set(
                    ReleasedComment.objects.values_list("card_id", flat=True)
                ),
                "sessions": set(
                    ReleasedSessionResult.objects.values_list("card_id", flat=True)
                ),
            }

        self.assertTrue(card_ids, "the release wrote no cards at all")
        for section, ids in hanging.items():
            self.assertTrue(ids, f"{section} froze nothing, so it proves nothing")
            self.assertTrue(
                ids <= card_ids, f"{section} hangs off a card this release did not write"
            )

    def test_the_other_school_is_untouched(self):
        """Grace releases nothing, and the placing thread must not reach it.

        Each thread resolves its own school from `connection.schema_name`. A
        thread whose `search_path` were wrong would place a child into Grace's
        schema and write Grace's rows, and no single-tenant test could tell that
        apart from working.
        """
        self.approve_the_third_term()
        self.release_while_the_roster_moves()

        with connected_to(self.other_school):
            theirs = {
                "cards": ReleasedCard.objects.count(),
                "ratings": ReleasedTraitRating.objects.count(),
                "subject_results": ReleasedSubjectResult.objects.count(),
                "comments": ReleasedComment.objects.count(),
                "placements": ClassPlacement.objects.roster(
                    ClassGroup.objects.get(pk=self.their_group_id),
                    Term.objects.get(pk=self.their_terms[TermName.THIRD.value]),
                ).count(),
            }

        self.assertEqual(theirs["cards"], 0, "a release leaked into the other school")
        self.assertEqual(theirs["ratings"], 0)
        # Ngozi has a mark and a remark, so these two are zero because nothing
        # released her, not because there was nothing of hers to release.
        self.assertEqual(theirs["subject_results"], 0)
        self.assertEqual(theirs["comments"], 0)
        self.assertEqual(theirs["placements"], 1, "the other school's roster moved")


class TheRosterMovedIsNamedTests(SimpleTestCase):
    """Belt and braces: the failure has a sentence even where it cannot happen.

    The roster is read once now, so nothing on the release path can reach for a
    child the cards never saw. `cards.the_card_for()` exists for the paths that
    do not go through `release()` and for the fourth section somebody adds next
    year, reaching for `positions.roster_ids()` out of habit.

    Asserted directly rather than through a release, because a test that can only
    fire this by breaking the release path is a test that will be deleted the
    first time somebody reads it.

    **`SimpleTestCase`, and deliberately not the fixture above.** `the_card_for()`
    is a dict lookup and a raise; it takes a mapping and an integer and touches
    no database at all. Inheriting `ReleaseUnderARosterChangeSetUp` would build
    two tenant schemas, six users, six terms and two class groups — the most
    expensive thing this suite does, paid three times — to supply two numbers
    that can be written down. `ON_ROSTER` and `NOT_ON_ROSTER` are those numbers.
    """

    #: Two membership ids. Any two distinct integers do; these are named so the
    #: assertions read as what they are about rather than as arithmetic.
    ON_ROSTER = 11
    NOT_ON_ROSTER = 22

    def test_a_missing_card_raises_something_a_caller_can_catch(self):
        with self.assertRaises(cards.TheRosterMovedDuringRelease) as refused:
            cards.the_card_for({self.ON_ROSTER: object()}, self.NOT_ON_ROSTER)

        self.assertIsInstance(refused.exception, services.ResultsError)
        self.assertEqual(
            refused.exception.student_membership_id, self.NOT_ON_ROSTER
        )

    def test_the_sentence_says_what_happened_and_what_to_do(self):
        """Not `null value in column "card_id"`, which names neither."""
        with self.assertRaises(cards.TheRosterMovedDuringRelease) as refused:
            cards.the_card_for({}, self.NOT_ON_ROSTER)

        said = str(refused.exception)
        self.assertIn("roster changed", said)
        self.assertIn("Nothing has been saved", said)
        self.assertIn("release the term again", said)

    def test_it_finds_the_card_when_the_child_is_on_the_roster(self):
        """The control. A function that always raised would pass both above."""
        card = object()
        self.assertIs(
            cards.the_card_for({self.ON_ROSTER: card}, self.ON_ROSTER), card
        )
