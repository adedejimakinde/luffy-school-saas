"""Issue #56: a released card owes a file, and somebody can find out that it does.

Task 7 built a renderer, a job and a table, and nothing called any of them. What
is under test here is the way in — `results.renders`, which marks every card at
release and asks for a render after the commit — and the way out,
`card_api.report_card_pdf()`, which hands over the file or says why there is not
one yet.

The claim that matters most is not "a release enqueues". It is **a release that
failed to enqueue still leaves a row saying the file is owed**, because that is
the difference between a missing card somebody can query for and a missing card
whose first reader is a parent, weeks later, with no way to open it. So the
broker is knocked over on purpose below, twice: once to prove the release
survives it, and once to prove the marker does.

Two schools throughout, because a job takes a schema name as its first argument
and every one of those assertions is meaningless in a fixture with one school —
per-schema sequences mean Grace's card and St Mary's card can both be id 1, and
a publish naming the wrong school would still satisfy a count of 1.

`transaction.on_commit` does not fire inside a `TestCase`, whose every test is a
transaction that rolls back. That is not an obstacle to test around: it is the
thing being asserted, so the publishes are captured with
`captureOnCommitCallbacks` and the "before the commit" half is the assertion
made while they are still uncalled.
"""

import threading
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunPython
from django.utils import timezone

from academics.models import TermName
from results import cards, renders, revision, services
from results.models import PdfState, ReleasedCard, ReleasedCardPdf
from results.tests.test_card_api import HOST, THEIR_HOST, ReportCardApiSetUp
from results.tests.test_release_roster_race import ReleaseUnderARosterChangeSetUp
from schools.tests.tenants import connected_to

#: `0022`'s own backfill, imported by path because a module name starting with a
#: digit is not an identifier. `TheBackfillTests` runs the real function rather
#: than a copy, which would go on passing after the migration changed.
the_migration = import_module(
    "results.migrations.0022_a_card_owes_a_file_from_the_moment_it_is_released"
)

_historical_apps = None


def historical_apps():
    """The registry Django hands `0022`'s `RunPython`, which is **not** `django.apps`.

    A migration's models are rebuilt from migration state and carry fields
    rather than methods, so handing the backfill the live registry is a test of
    different code — and different in the direction that hides bugs.

    Built from the migration's declared dependencies and then walked forward
    through its own operations up to the `RunPython`, because that is where
    Django puts the state when it calls it: the two `AddField`s above it are
    already applied, and a registry taken from the dependencies alone would have
    no `state` column for the function to write.
    """
    global _historical_apps
    if _historical_apps is None:
        migration = the_migration.Migration(
            "0022_a_card_owes_a_file_from_the_moment_it_is_released", "results"
        )
        state = MigrationLoader(None, ignore_no_migrations=True).project_state(
            migration.dependencies
        )
        for operation in migration.operations:
            if isinstance(operation, RunPython):
                break
            operation.state_forwards("results", state)
        _historical_apps = state.apps
    return _historical_apps


def the_state_constraint():
    """The constraint `0022` adds, taken from the migration rather than retyped."""
    return the_migration.Migration.operations[-1].constraint


#: A stand-in for a rendered card. These tests are about what the route does
#: with stored bytes, not about WeasyPrint — task 7 asserts that it really
#: renders, and repeating a several-second render here to prove that a
#: `HttpResponse` carries the bytes it was given would buy nothing.
A_PRETEND_PDF = b"%PDF-1.7 pretend"


class CardHelpers(ReportCardApiSetUp):
    """The reading and the staging, and **no release**.

    Kept apart from `MarkerSetUp` below because the tests that assert what a
    release does have to perform it themselves, inside the capture that says
    when the message went out.
    """

    def markers_in(self, school):
        with connected_to(school):
            return list(ReleasedCardPdf.objects.order_by("card_id"))

    def card_of(self, school, child, term_name=TermName.FIRST.value):
        with connected_to(school):
            return cards.card_for(child, self.term_of(school, term_name))

    def set_state(self, school, card, **fields):
        """Straight onto the row, because the point is the route and not the job."""
        with connected_to(school):
            ReleasedCardPdf.objects.filter(card=card).update(**fields)

    def make_it_built(self, school, card, content=A_PRETEND_PDF):
        self.set_state(
            school,
            card,
            state=PdfState.BUILT,
            content=content,
            byte_size=len(content),
            error="",
        )

    def make_it_failed(self, school, card, error="RuntimeError: no fonts"):
        self.set_state(
            school,
            card,
            state=PdfState.FAILED,
            content=None,
            byte_size=None,
            error=error,
        )


class MarkerSetUp(CardHelpers):
    """Both schools release their first term. St Mary's has two children, Grace one."""

    def setUp(self):
        super().setUp()
        self.sheet = self.release()
        self.their_sheet = self.release(self.grace)


class EveryReleasedCardOwesAFileTests(MarkerSetUp):
    """The marker is written at release, and there is one for every card."""

    def test_a_release_writes_a_pending_row_for_every_card(self):
        markers = self.markers_in(self.stmarys)

        self.assertEqual(len(markers), 2, "One per child, and there are two.")
        for marker in markers:
            self.assertEqual(marker.state, PdfState.PENDING)
            self.assertIsNone(marker.content)
            self.assertEqual(marker.error, "")
            self.assertIsNotNone(
                marker.last_enqueued_at, "A render was asked for and not recorded."
            )

    def test_no_released_card_anywhere_is_without_one(self):
        """The invariant the download route and the model docstring both rely on.

        Asserted as a query rather than as a count of two, because a count
        passes on a fixture that happens to be the right size and this is a
        claim about *every* card.
        """
        for school in (self.stmarys, self.grace):
            with connected_to(school):
                orphans = ReleasedCard.objects.filter(pdf__isnull=True)
                self.assertFalse(
                    orphans.exists(),
                    f"{school.name}: {list(orphans)} released with no marker.",
                )

    def test_a_release_marks_the_school_that_released_and_no_other(self):
        """Grace released one card, St Mary's two. Neither wrote into the other."""
        theirs = self.markers_in(self.grace)

        self.assertEqual(len(theirs), 1)
        with connected_to(self.grace):
            self.assertEqual(theirs[0].card.student_name, "Ngozi Ade")
        for marker in self.markers_in(self.stmarys):
            with connected_to(self.stmarys):
                self.assertNotEqual(marker.card.student_name, "Ngozi Ade")

    def test_a_revision_owes_a_file_of_its_own(self):
        """Version 2 is a different card, so it needs its own marker.

        And this is the *only* path by which a child placed into a term after it
        was released (#31) gets a card at all: marking at release alone would
        leave hers the one card on the platform with no marker and no render —
        the exact case this design exists to make impossible.
        """
        with connected_to(self.stmarys):
            revision.revise(
                self.ada,
                self.term_of(self.stmarys, TermName.FIRST.value),
                self.principal,
                "A maths script was re-marked.",
            )
            versions = {
                card.version: card.pdf.state
                for card in ReleasedCard.objects.filter(
                    student_membership_id=self.ada.pk
                ).select_related("pdf")
            }

        self.assertEqual(versions, {1: PdfState.PENDING, 2: PdfState.PENDING})


class TheJobIsPublishedAfterTheCommitTests(CardHelpers):
    """When the message goes out, what is in it, and what happens when it cannot.

    These release inside the test rather than in `setUp`, because what is under
    test is the ordering *around* the commit — and a release performed in
    `setUp` has left its `on_commit` callbacks somewhere no assertion can see
    them fail to have run.
    """

    def a_release(self, school=None):
        return self.release(school or self.stmarys)

    def test_nothing_is_published_before_the_release_commits(self):
        """The bug a bare `.delay()` would be, asserted rather than reasoned about.

        A worker is another process on another connection. A message published
        inside the transaction can be picked up before it commits, and under
        READ COMMITTED that worker sees no card — so it fails permanently for a
        card that was fine three milliseconds later.
        """
        with patch("results.renders.render_card_pdf") as job:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.a_release()

            self.assertFalse(
                job.apply_async.called,
                "A render was published while the release was still open.",
            )

            for callback in callbacks:
                callback()

            self.assertEqual(job.apply_async.call_count, 2)

    def test_the_message_names_the_schema_and_one_card(self):
        """Two schools, because the schema name is the argument that cannot be guessed."""
        with patch("results.renders.render_card_pdf") as job:
            with self.captureOnCommitCallbacks(execute=True):
                self.a_release(self.grace)

        expected = self.card_of(self.grace, self.ngozi).pk

        job.apply_async.assert_called_once_with(
            args=["grace", expected], retry=False
        )

    def test_a_broker_that_is_down_does_not_fail_the_release(self):
        """`on_commit` runs after the commit, so a raise here is a 500 for cards that went home.

        The release is durable by the time the publish is attempted. Letting the
        exception out would give the principal an error page for a class whose
        cards are already released and readable — and would tell them nothing
        they could act on, because the release is not the thing that failed.
        """
        with patch(
            "results.renders.render_card_pdf.apply_async",
            side_effect=OSError("Connection refused"),
        ):
            with self.assertLogs("results.renders", level="ERROR") as logged:
                with self.captureOnCommitCallbacks(execute=True):
                    sheet = self.a_release()

        with connected_to(self.stmarys):
            sheet.refresh_from_db()
            self.assertEqual(sheet.state, "released")
            markers = ReleasedCardPdf.objects.filter(card__sheet=sheet)
            self.assertEqual(markers.count(), 2)
            self.assertTrue(all(m.state == PdfState.PENDING for m in markers))

        self.assertEqual(len(logged.records), 2, "One line per card that was lost.")
        self.assertIn("Could not queue a render", logged.output[0])

    def test_one_card_failing_to_publish_does_not_stop_the_rest(self):
        """Forty-five cards, one broker hiccup, and the other forty-four still asked for."""
        with patch(
            "results.renders.render_card_pdf.apply_async",
            side_effect=[OSError("Connection refused"), None],
        ) as publish:
            with self.assertLogs("results.renders", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    self.a_release()

        self.assertEqual(publish.call_count, 2)


class TheDebounceTests(MarkerSetUp):
    """`enqueue_if_pending()`: who is asked for again, and how often.

    The window exists because `PENDING` means both "queued a moment ago" and
    "queued never". Without it, results week turns every parent's refresh into
    another render of the same forty-five cards.
    """

    def setUp(self):
        super().setUp()
        self.card = self.card_of(self.stmarys, self.ada)

    def marker(self):
        with connected_to(self.stmarys):
            return ReleasedCardPdf.objects.get(card=self.card)

    def ask(self, marker=None):
        """Read the row and ask for it, **inside one connection block**.

        `marker()` opens a block of its own inside this one, which is safe since
        issue #58: an inner exit restores the schema it found rather than
        forcing `public`. The outer block is still the load-bearing part.
        Nesting fixes an inner block inside an outer one; it does not conjure
        the outer one, and `enqueue_if_pending` reads the row's lazy relations.
        """
        with connected_to(self.stmarys):
            if marker is None:
                marker = self.marker()
            return renders.enqueue_if_pending(marker)

    def age_the_request(self, by=renders.RE_ENQUEUE_AFTER + timedelta(seconds=1)):
        with connected_to(self.stmarys):
            ReleasedCardPdf.objects.filter(card=self.card).update(
                last_enqueued_at=timezone.now() - by
            )

    def test_a_card_asked_for_a_moment_ago_is_not_asked_for_again(self):
        self.assertFalse(self.ask())

    def test_a_card_whose_render_never_came_back_is_asked_for_again(self):
        self.age_the_request()

        with patch("results.renders.render_card_pdf") as job:
            with self.captureOnCommitCallbacks(execute=True):
                asked = self.ask()

        self.assertTrue(asked)
        job.apply_async.assert_called_once_with(
            args=["st_marys", self.card.pk], retry=False
        )

    def test_asking_moves_the_window(self):
        """The claim `last_enqueued_at` makes, which nothing else in this file checks."""
        self.age_the_request()
        before = self.marker().last_enqueued_at

        self.assertTrue(self.ask())

        self.assertGreater(self.marker().last_enqueued_at, before)
        self.assertFalse(
            self.ask(), "The second ask was inside the window it had just moved."
        )

    def test_a_built_card_is_never_asked_for(self):
        self.age_the_request()
        self.make_it_built(self.stmarys, self.card)

        self.assertFalse(self.ask())

    def test_a_failed_card_is_never_asked_for(self):
        """What a failed render needs is a person, not another attempt.

        `RenderACard.on_failure` wrote the reason down precisely so that
        somebody reads it. A download that re-queued a `FAILED` card would be a
        retry loop driven by a parent hitting reload against a template that
        cannot render.
        """
        self.age_the_request()
        self.make_it_failed(self.stmarys, self.card)

        self.assertFalse(self.ask())

    def test_the_claim_is_the_update_and_not_the_read(self):
        """Two callers that both read a stale `PENDING`; one job.

        This is the race the conditional `UPDATE` exists for, staged by handing
        both callers the *same* row as they read it. Postgres re-evaluates the
        `WHERE` clause against the newer row version, so the second `UPDATE`
        matches nothing — which is only true because the check and the claim
        are one statement.
        """
        self.age_the_request()
        stale = self.marker()

        self.assertTrue(self.ask(stale))
        self.assertFalse(self.ask(stale), "The same stale read enqueued twice.")


class TheMarkerIsRepairedRatherThanMissedTests(MarkerSetUp):
    """A card with no marker is a bug in something else. It must not be silent."""

    def test_a_card_that_lost_its_marker_gets_one_and_says_so(self):
        card = self.card_of(self.stmarys, self.ada)
        with connected_to(self.stmarys):
            ReleasedCardPdf.objects.filter(card=card).delete()

            with self.assertLogs("results.renders", level="WARNING") as logged:
                marker = renders.marker_for(card)

        self.assertEqual(marker.state, PdfState.PENDING)
        self.assertIsNone(marker.last_enqueued_at, "It has not been asked for yet.")
        self.assertIn("had no ReleasedCardPdf row", logged.output[0])

    def test_the_marker_a_card_already_has_is_the_one_it_keeps(self):
        """The control. Without it the test above passes against a function that
        writes a new row every time, which would lose a `BUILT` card's file."""
        card = self.card_of(self.stmarys, self.ada)
        self.make_it_built(self.stmarys, card)

        with connected_to(self.stmarys):
            marker = renders.marker_for(card)

        self.assertEqual(marker.state, PdfState.BUILT)
        self.assertEqual(bytes(marker.content), A_PRETEND_PDF)


class TheFileRouteTests(MarkerSetUp):
    """`GET …/pdf/`: the bytes, or 202 and which unfinished state this is."""

    def pdf_url(self, school, membership, term_name=TermName.FIRST.value):
        return f"{self.card_url(school, membership, term_name)}pdf/"

    def fetch_pdf(self, user, school, membership, term_name=TermName.FIRST.value):
        self.client.force_login(user)
        return self.client.get(
            self.pdf_url(school, membership, term_name),
            HTTP_HOST=HOST if school == self.stmarys else THEIR_HOST,
        )

    def test_a_built_card_is_served_as_the_file_itself(self):
        card = self.card_of(self.stmarys, self.ada)
        self.make_it_built(self.stmarys, card)

        response = self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.content, A_PRETEND_PDF)

    def test_the_file_is_named_for_the_child_and_the_term(self):
        """What a browser writes into a Downloads folder, and it is not an id."""
        card = self.card_of(self.stmarys, self.ada)
        self.make_it_built(self.stmarys, card)

        response = self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertEqual(
            response["Content-Disposition"],
            'inline; filename="ada-obi-first-term-2025-2026.pdf"',
        )

    def test_a_revised_card_says_which_version_it_is(self):
        with connected_to(self.stmarys):
            revision.revise(
                self.ada,
                self.term_of(self.stmarys, TermName.FIRST.value),
                self.principal,
                "A maths script was re-marked.",
            )
        card = self.card_of(self.stmarys, self.ada)
        self.assertEqual(card.version, 2)
        self.make_it_built(self.stmarys, card)

        response = self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertIn("v2.pdf", response["Content-Disposition"])

    def test_a_card_still_being_prepared_is_202_and_is_asked_for_again(self):
        card = self.card_of(self.stmarys, self.ada)
        with connected_to(self.stmarys):
            ReleasedCardPdf.objects.filter(card=card).update(
                last_enqueued_at=timezone.now() - renders.RE_ENQUEUE_AFTER * 2
            )

        with patch("results.renders.render_card_pdf") as job:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["state"], "pending")
        self.assertEqual(response.json()["state_label"], "Not built yet")
        self.assertIn("still being prepared", response.json()["detail"])
        job.apply_async.assert_called_once_with(
            args=["st_marys", card.pk], retry=False
        )

    def test_a_refresh_inside_the_window_does_not_queue_a_second_render(self):
        """Results week: every parent of a class, on the day, hitting reload."""
        with patch("results.renders.render_card_pdf") as job:
            with self.captureOnCommitCallbacks(execute=True):
                self.fetch_pdf(self.mama, self.stmarys, self.ada)
                self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertFalse(job.apply_async.called)

    def test_a_failed_card_is_202_and_is_not_queued_again(self):
        card = self.card_of(self.stmarys, self.ada)
        self.make_it_failed(self.stmarys, card)

        with patch("results.renders.render_card_pdf") as job:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["state"], "failed")
        self.assertFalse(job.apply_async.called)

    def test_the_reason_a_render_failed_is_not_in_the_body(self):
        """`error` holds a Python exception written for whoever debugs the render.

        A parent reading `TemplateSyntaxError: unexpected '%'` learns nothing
        they can act on, and this module does not vary a payload by who is
        asking — so it is absent for staff too, who can read the row.
        """
        card = self.card_of(self.stmarys, self.ada)
        self.make_it_failed(self.stmarys, card, error="TemplateSyntaxError: at line 4")

        for reader in (self.mama, self.principal):
            with self.subTest(reader=reader.username):
                body = self.fetch_pdf(reader, self.stmarys, self.ada).json()
                self.assertNotIn("TemplateSyntaxError", str(body))
                self.assertNotIn("error", body)

    def test_the_file_asks_the_same_authority_question_as_the_json(self):
        """Not a second permission, and not a second answer to the same question.

        A PDF of a card you may read is the card you may read. Two answers is
        one answer nobody tested, and the day they disagree the file route is
        the one that leaks.
        """
        card = self.card_of(self.stmarys, self.ada)
        self.make_it_built(self.stmarys, card)

        refused = self.fetch_pdf(self.bolas_father, self.stmarys, self.ada)
        self.assertEqual(refused.status_code, 404)

        allowed = self.fetch_pdf(self.ada.user, self.stmarys, self.ada)
        self.assertEqual(allowed.status_code, 200)

    def test_a_term_never_released_looks_exactly_like_a_card_not_yours(self):
        """The existence oracle, on the route it would be cheapest to forget.

        Four characters on the end of a URL must not turn the JSON route's flat
        404 into a distinguishable pair of answers.
        """
        not_yours = self.fetch_pdf(self.bolas_father, self.stmarys, self.ada)
        never_released = self.fetch_pdf(
            self.mama, self.stmarys, self.ada, term_name=TermName.THIRD.value
        )

        self.assertEqual(not_yours.status_code, never_released.status_code)
        self.assertEqual(not_yours.content, never_released.content)

    def test_grace_serves_its_own_card_and_not_st_marys(self):
        """Per-schema sequences make both cards id 1; the bytes say whose this is."""
        theirs = self.card_of(self.grace, self.ngozi)
        self.make_it_built(self.grace, theirs, content=b"%PDF-1.7 grace")

        response = self.fetch_pdf(self.their_principal, self.grace, self.ngozi)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-1.7 grace")
        self.assertIn("ngozi-ade", response["Content-Disposition"])


class TwoDownloadsAtOnceTests(ReleaseUnderARosterChangeSetUp):
    """The debounce under a second connection, which is the only place it is real.

    `TheDebounceTests` hands one caller the same stale row twice and proves that
    the claim is the `UPDATE` rather than the read it started from. What it
    cannot show is the half `results/renders.py` asserts about Postgres: that a
    second session's `UPDATE` **blocks** on the first and then re-evaluates its
    `WHERE` clause against the row the first one committed. A `TestCase` is one
    transaction, so two "connections" inside it are one and nothing ever blocks
    — the same reason `test_release_roster_race` and `test_ratings_concurrency`
    exist, and this class borrows the first's fixture rather than building a
    third of its own.

    Two real threads, one released card, and a barrier so both are inside
    `enqueue_if_pending()` at once. One render is published, not two. This is a
    load claim rather than a correctness one — the job is idempotent, so a
    double render would be merely wasteful — and results week is every parent of
    a class refreshing on the day the cards go home, which is the load the queue
    exists to smooth rather than to receive.
    """

    def setUp(self):
        super().setUp()
        self.approve_the_third_term()
        # Patched through the release as well: this is a `TransactionTestCase`,
        # so its commit is real and `on_commit` fires for every card. Without
        # this the fixture publishes into whatever Redis the environment has.
        with patch("results.renders.render_card_pdf"):
            with connected_to(self.school):
                services.release(
                    services.sheet_for(self.group(), self.term()), self.principal
                )

        with connected_to(self.school):
            self.card = cards.card_for(self.ada, self.term())
            ReleasedCardPdf.objects.filter(card=self.card).update(
                last_enqueued_at=timezone.now() - renders.RE_ENQUEUE_AFTER * 2
            )
            #: The one read both threads start from, which is what makes this
            #: the race rather than two sequential asks.
            self.stale = ReleasedCardPdf.objects.get(card=self.card)

    def an_asking_thread(self, outcomes, barrier):
        def run():
            try:
                barrier.wait(timeout=10)
                with connected_to(self.school):
                    outcomes.append(renders.enqueue_if_pending(self.stale))
            finally:
                # A thread of our own means a connection of our own, and
                # `TransactionTestCase` tears the database down underneath any
                # that are left open.
                connections.close_all()

        return threading.Thread(target=run)

    def test_two_downloads_at_once_queue_one_render(self):
        outcomes = []
        barrier = threading.Barrier(2)

        with patch("results.renders.render_card_pdf") as job:
            threads = [self.an_asking_thread(outcomes, barrier) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

        self.assertEqual(
            sorted(outcomes), [False, True], "Both asks claimed the same card."
        )
        job.apply_async.assert_called_once_with(
            args=["st_marys", self.card.pk], retry=False
        )

    def test_neither_thread_reached_the_other_school(self):
        """Grace released nothing, so a marker there is a thread on the wrong schema.

        Each thread opens its own connection and sets its own `search_path`; a
        thread that inherited the wrong one would write a row into a school that
        has never released a card, and no single-tenant fixture could tell that
        apart from working.
        """
        outcomes = []
        barrier = threading.Barrier(2)

        with patch("results.renders.render_card_pdf"):
            threads = [self.an_asking_thread(outcomes, barrier) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

        with connected_to(self.other_school):
            self.assertFalse(ReleasedCardPdf.objects.exists())


class TheBackfillTests(MarkerSetUp):
    """`0022` on a database that already has released cards. Issue #56.

    Every test above runs against a schema where `0022` was applied to an empty
    table, which is the one case the migration does not have to get right. A
    real school has years of releases: rows written by a job that ran, and — for
    every card released before task 7 existed at all — no row whatsoever. This
    class stages both and runs the migration's own function over them.

    The staging drops the new constraint and puts the rows back into the two
    shapes the *old* one permitted, which is the only way to have pre-`0022`
    data inside a database where `0022` has already run. `test_the_control_…`
    is what says the staging is real rather than a shape the new constraint
    would have accepted anyway.
    """

    TABLE = "results_releasedcardpdf"

    def historical_model(self):
        return historical_apps().get_model("results", "ReleasedCardPdf")

    def stage(self, adas_row):
        """St Mary's as it looked before `0022`, and Grace's card with no row at all.

        Ada keeps a row in one of the two old shapes with `state` back at its
        default; Bola's row goes entirely, which is the card released before the
        table existed. Grace's goes too, so that "the `INSERT … SELECT` wrote
        into the schema it was run in" is a claim with something to fail on —
        the statement names its tables unqualified and leans on the search path,
        which is exactly where a migration crosses schemas by accident.
        """
        adas = self.card_of(self.stmarys, self.ada)
        bolas = self.card_of(self.stmarys, self.bola)
        theirs = self.card_of(self.grace, self.ngozi)

        with connected_to(self.stmarys):
            with connection.cursor() as cursor:
                # The release in `setUp` is still in this test's transaction
                # with its deferred foreign-key checks queued, and Postgres
                # refuses to ALTER a table that has pending trigger events.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE;")
            with connection.schema_editor(atomic=False) as editor:
                editor.remove_constraint(self.historical_model(), the_state_constraint())

            was = {
                "built": {
                    "state": PdfState.PENDING,
                    "content": A_PRETEND_PDF,
                    "byte_size": len(A_PRETEND_PDF),
                    "error": "",
                },
                "failed": {
                    "state": PdfState.PENDING,
                    "content": None,
                    "byte_size": None,
                    "error": "RuntimeError: no fonts",
                },
            }[adas_row]
            ReleasedCardPdf.objects.filter(card=adas).update(**was)
            ReleasedCardPdf.objects.filter(card=bolas).delete()

        with connected_to(self.grace):
            ReleasedCardPdf.objects.filter(card=theirs).delete()

        return adas, bolas, theirs

    def run_the_backfill(self):
        """The real function, in St Mary's schema, against the registry it will get."""
        with connected_to(self.stmarys):
            the_migration.name_the_state_of_every_row(
                historical_apps(), connection.schema_editor()
            )

    def put_the_constraint_back(self):
        """Postgres validates existing rows on `ADD CONSTRAINT`, so this is an assertion.

        It is the strongest one in the file: it does not check the states the
        backfill wrote against a list somebody typed here, it checks them
        against the rule the migration itself installs one operation later.
        """
        with connected_to(self.stmarys):
            with connection.schema_editor(atomic=False) as editor:
                editor.add_constraint(self.historical_model(), the_state_constraint())

    def rows_in(self, school):
        with connected_to(school):
            return {row.card_id: row for row in ReleasedCardPdf.objects.all()}

    def test_a_row_holding_bytes_is_named_built(self):
        adas, _, _ = self.stage("built")

        self.run_the_backfill()

        row = self.rows_in(self.stmarys)[adas.pk]
        self.assertEqual(row.state, PdfState.BUILT)
        self.assertEqual(bytes(row.content), A_PRETEND_PDF, "It rewrote the file.")

    def test_a_row_holding_a_reason_is_named_failed(self):
        adas, _, _ = self.stage("failed")

        self.run_the_backfill()

        row = self.rows_in(self.stmarys)[adas.pk]
        self.assertEqual(row.state, PdfState.FAILED)
        self.assertEqual(row.error, "RuntimeError: no fonts")

    def test_a_card_with_no_row_at_all_is_given_one(self):
        """The half that makes old cards reachable by the download route.

        Without it they arrive there as a fourth case — no row — for ever, and
        `ReleasedCardPdf`'s docstring is false on every database that has ever
        released a card.
        """
        _, bolas, _ = self.stage("built")

        self.run_the_backfill()

        row = self.rows_in(self.stmarys)[bolas.pk]
        self.assertEqual(row.state, PdfState.PENDING)
        self.assertIsNone(row.content)
        self.assertEqual(row.error, "")
        self.assertIsNone(
            row.last_enqueued_at, "It claimed a render nobody has asked for."
        )

    def test_a_card_that_has_a_row_does_not_get_a_second(self):
        """The `NOT EXISTS`. Without it the insert dies on the `OneToOne` — or,
        worse, would not, and a card would have two answers about its file."""
        adas, _, _ = self.stage("built")

        self.run_the_backfill()

        with connected_to(self.stmarys):
            self.assertEqual(ReleasedCardPdf.objects.filter(card=adas).count(), 1)
            self.assertEqual(ReleasedCardPdf.objects.count(), 2)

    def test_the_constraint_that_follows_it_accepts_every_row(self):
        """Run in the order the migration runs them, which is where this would break."""
        for shape in ("built", "failed"):
            with self.subTest(shape=shape):
                self.stage(shape)
                self.run_the_backfill()
                self.put_the_constraint_back()

    def test_the_control_the_staged_rows_are_refused_without_the_backfill(self):
        """Otherwise every test above passes against data that never needed fixing."""
        self.stage("built")

        with self.assertRaises(IntegrityError) as caught:
            # Inside an atomic block, so the failed DDL does not leave this
            # test's transaction broken for its own assertions.
            with transaction.atomic():
                self.put_the_constraint_back()

        self.assertIn("a_card_pdf_is_pending_a_file_or_a_reason", str(caught.exception))

    def test_the_other_school_is_not_touched(self):
        """django-tenants runs this per schema; the SQL must not reach past its own."""
        _, _, theirs = self.stage("built")

        self.run_the_backfill()

        self.assertEqual(
            self.rows_in(self.grace), {}, f"{theirs.pk} was backfilled in Grace."
        )
