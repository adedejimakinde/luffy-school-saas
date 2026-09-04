"""What a rating does when somebody else is holding the sheet.

`results/tests/test_ratings.py` proves the rules one connection at a time. This
file proves the two that are only true under a second one, and it needs
`TransactionTestCase` and real threads to do it: a `TestCase` wraps the whole
test in one transaction, so two "connections" inside it are one, and a lock
neither takes nor waits for anything.

The pair here mirrors `test_approval_concurrency.LockScopeTests` — one test
reads the SQL and names the property, the other proves the consequence by
contention — because either alone is a test that passes for the wrong reason.

Two schools, as everywhere in this project. The race itself needs one, but each
thread resolves its own school from `connection.schema_name`, so a thread whose
`search_path` is wrong would authorise against one school and write into
another's schema — and no single-tenant test can tell that apart from working.
"""

import threading
from datetime import date

from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from results import ratings, services
from results.models import ResultSheet, SheetState, Trait, TraitGroup, TraitRating
from schools.models import School
from schools.tests.tenants import connected_to

PASSWORD = "correct-horse-battery"


class RatingsUnderConcurrencySetUp(TransactionTestCase):
    """St Mary's teaches JSS 1A: Kemi is its class teacher, Ada sits in it.

    The affective section is on, and **no sheet is opened here**. Some of these
    tests want the chain started and some want it not started — a rating before
    anybody opens the sheet is the ordinary order of events — so each says which
    it needs.
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

        self.their_teacher = self._staff(
            "chika", "Chika Obi", self.other_school, Role.TEACHER
        )
        self.their_child = self._student("ngozi", "Ngozi Eze", self.other_school)

        self.term_id, self.group_id = self._class_with_a_child(
            self.school, self.teacher, self.ada
        )
        self.their_term_id, self.their_group_id = self._class_with_a_child(
            self.other_school, self.their_teacher, self.their_child
        )

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
        grant_membership(user, school, Role.STUDENT)
        return user

    def _class_with_a_child(self, school, teacher, student):
        with connected_to(school):
            term = Term.objects.create(
                session="2025/2026",
                name=TermName.FIRST,
                starts_on=date(2025, 9, 15),
                ends_on=date(2025, 12, 12),
            )
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.assign_class_teacher(
                group,
                term,
                teacher.memberships.get(school=school, role=Role.TEACHER),
            )
            academics.place_student(
                group,
                term,
                student.memberships.get(school=school, role=Role.STUDENT),
            )
            ratings.set_group_enabled(TraitGroup.AFFECTIVE, True)
            return term.pk, group.pk

    # -- shorthands ----------------------------------------------------------

    def term(self):
        return Term.objects.get(pk=self.term_id)

    def group(self):
        return ClassGroup.objects.get(pk=self.group_id)

    def trait(self):
        """Whichever trait leads the affective section. Never named.

        `migrations/0006` says why nothing in the code may name a seeded row: a
        school may hide any of them, and a test that depends on one is a test
        that breaks when the feature is used as designed.
        """
        return Trait.objects.in_group(TraitGroup.AFFECTIVE).visible().first()

    def membership(self):
        return self.ada.memberships.get(school=self.school, role=Role.STUDENT)

    def open_a_sheet(self):
        with connected_to(self.school):
            return services.open_sheet(
                self.group(), self.term(), self.principal
            ).pk

    def rate(self, score, actor=None):
        return ratings.rate_as(
            actor or self.teacher,
            self.term(),
            self.trait(),
            self.membership(),
            score,
        )

    def tearDown(self):
        connection.set_schema_to_public()
        # Drop the schemas, not just the rows — `test_approval_concurrency`
        # sets out why at length: `TransactionTestCase` flushes the public
        # tables, which removes the `School` rows, but a tenant schema is not a
        # table and survives into the next test's `setUp()`.
        with connection.cursor() as cursor:
            for school in (self.school, self.other_school):
                cursor.execute(f'DROP SCHEMA IF EXISTS "{school.schema_name}" CASCADE')
        super().tearDown()


class TheRatingLockTests(RatingsUnderConcurrencySetUp):
    """A rating is only editable while the sheet is in `draft`.

    That rule is a read of the sheet's state followed by a write that depends on
    it, which is two statements — and between two statements is where this
    codebase keeps finding its bugs: `schools.Invitation.accept()` decided on
    rows it had not locked, and `_require_class_teacher_scope()` authorised
    against an instance while `_move()` wrote to a row.

    Postgres does not close this one on its own. Migration `0007`'s trigger
    refuses a rating for a **released** term, deliberately and narrowly; the
    in-review states are the service's to hold, and they are exactly the states
    a teacher is likely to be typing in.
    """

    def test_the_lock_a_rating_takes_reaches_no_joined_table(self):
        """Named on the SQL, so an ordering added later fails here first.

        `ResultSheet.Meta.ordering` is `["term", "class_group"]` — two relations
        — so a `select_for_update()` that inherits it locks a row in
        `academics_term` and `academics_classgroup` as well, neither of which a
        rating writes. Every teacher saving a rating would then contend with
        anything touching that term.
        """
        self.open_a_sheet()

        with connected_to(self.school):
            with CaptureQueriesContext(connection) as captured:
                self.rate(4)

        locking = [
            query["sql"]
            for query in captured.captured_queries
            if "FOR UPDATE" in query["sql"]
        ]
        self.assertTrue(locking, "the rating took no row lock at all")
        self.assertTrue(
            any("results_resultsheet" in sql for sql in locking),
            f"the rating never locked the sheet it checked:\n{locking}",
        )
        for sql in locking:
            self.assertNotIn("JOIN", sql, f"this lock reaches a joined table:\n{sql}")

    def test_a_rating_cannot_land_under_a_submission_in_flight(self):
        """The consequence, proved by contention rather than by reading SQL.

        A thread holds a submission's transaction open — so the sheet row is
        locked and the new state is not yet visible to anybody else — and a
        second thread saves a rating. Unlocked, it reads `draft`, writes, and
        commits a rating into a document that was submitted a millisecond later;
        the vice principal's signature is then on a sheet that moved underneath
        it. Locked, it waits, and refuses when it sees what happened.

        Both halves are asserted. That the rating *waited* is what says the lock
        did it, and not merely that the thread happened to be slow.
        """
        self.open_a_sheet()

        holding = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        failed = []
        outcome = []

        def hold_a_submission():
            try:
                with connected_to(self.school):
                    with transaction.atomic():
                        sheet = ResultSheet.objects.get(
                            class_group=self.group(), term=self.term()
                        )
                        services.submit(sheet, self.teacher)
                        holding.set()
                        release.wait(15)
            except Exception as exc:  # noqa: BLE001 — reported, not swallowed
                failed.append(exc)
                holding.set()
            finally:
                connections.close_all()

        def save_a_rating():
            try:
                with connected_to(self.school):
                    outcome.append(self.rate(5))
            except Exception as exc:  # noqa: BLE001 — this is the result
                outcome.append(exc)
            finally:
                finished.set()
                connections.close_all()

        submitter = threading.Thread(target=hold_a_submission)
        submitter.start()
        self.assertTrue(holding.wait(15), "the submitting thread never started")
        self.assertEqual(failed, [], f"the submitting thread failed: {failed}")

        rater = threading.Thread(target=save_a_rating)
        rater.start()
        try:
            self.assertFalse(
                finished.wait(2),
                f"the rating did not wait for the sheet's lock: {outcome}",
            )
        finally:
            release.set()
            submitter.join(15)
            rater.join(15)

        self.assertTrue(finished.is_set(), "the rating never finished")
        [result] = outcome
        self.assertIsInstance(result, ratings.RatingsLocked)
        self.assertEqual(result.state, SheetState.SUBMITTED)

        with connected_to(self.school):
            self.assertFalse(
                TraitRating.objects.exists(),
                "a rating landed on a sheet that had been submitted",
            )
            self.assertEqual(
                ResultSheet.objects.get(pk=ResultSheet.objects.first().pk).state,
                SheetState.SUBMITTED,
                "the submission itself must still have gone through",
            )


class TwoTabsRatingAtOnceTests(RatingsUnderConcurrencySetUp):
    """The insert race, which is the one `rate()` used to have a retry for.

    Only the class teacher may rate, so the two writers are one person in two
    tabs. **No sheet is opened**: with one, both raters queue on its row lock
    and the second finds the row already there, so the race cannot happen — it
    is reachable only before the chain starts, which is a perfectly ordinary
    moment to be entering ratings.

    `rate()` no longer catches the collision. Django's `update_or_create()`
    takes the row lock and `get_or_create()` re-reads after a unique violation,
    so the loser finds the winner's row and applies its own values to it. This
    test is what says that is true here rather than true in the release notes.
    """

    def test_two_at_once_leave_one_row_and_one_of_the_two_scores(self):
        ready = threading.Barrier(2, timeout=15)
        results = []

        def rate(score):
            def run():
                try:
                    with connected_to(self.school):
                        ready.wait()
                        results.append(self.rate(score))
                except Exception as exc:  # noqa: BLE001 — reported, not swallowed
                    results.append(exc)
                finally:
                    connections.close_all()

            return run

        threads = [threading.Thread(target=rate(score)) for score in (3, 5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)

        errors = [row for row in results if isinstance(row, Exception)]
        self.assertEqual(errors, [], f"a rating was refused: {errors}")

        with connected_to(self.school):
            self.assertEqual(
                TraitRating.objects.count(), 1, "one child, one trait, one row"
            )
            self.assertIn(TraitRating.objects.get().score, (3, 5))

        with connected_to(self.other_school):
            self.assertEqual(
                TraitRating.objects.count(),
                0,
                "a thread wrote into the wrong school's schema",
            )
