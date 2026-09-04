"""Where a paper prints, and the backfill that must not reshuffle. Issue #42.

`Assessment.position` is the school's own answer to the order of a card's
columns. `gradebook.0003` gives existing papers the order they already had —
creation order — rather than a better one, and that restraint is the whole
point: the order is frozen onto every released card, and a frozen order cannot
be corrected on cards already in a parent's hand. A backfill that reshuffled
would leave cards released tomorrow disagreeing with cards sent home last term,
for the same child and the same term.

## The papers are created in an order alphabetical sorting cannot reproduce

"First CA", "Second CA", "Exam" — created in that order, which is the order they
are sat. Alphabetically they are "Exam, First CA, Second CA". Nothing here can
tell the two apart unless creation order and alphabetical order disagree, and in
the base setup's first term they happen to agree, so these papers go in a term
of their own.

## The backfill is run the way Django runs it

`number_papers_by_creation_order` is imported from the migration and called with
the historical registry — models rebuilt from migration state, carrying fields
and not methods. Handing it `django.apps` would test different code, and
different in the direction that hides bugs.

**And it is run against staged rows, never an empty table.** An empty database
makes the backfill a silent no-op that asserts nothing, which is how `0017`'s
deploy-stopper hid. `test_the_staging_is_real` is what says the rows are there
and were unnumbered before the function ran.
"""

from importlib import import_module

from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunPython

from gradebook.models import Assessment
from results import cards, revision
from results.models import ReleasedCard
from results.tests.test_card_api import ReportCardApiSetUp
from schools.tests.tenants import connected_to

from academics.models import TermName

#: Imported by path because a module name starting with a digit is not an
#: identifier. The real function, not a copy — a copy would go on passing after
#: the migration changed.
the_migration = import_module("gradebook.migrations.0003_where_a_paper_prints")

_historical_apps = None


def historical_apps():
    """The registry Django hands `0003`'s `RunPython`, which is not `django.apps`.

    Built from the migration's dependencies and walked forward through its own
    operations up to the `RunPython`, because that is where Django puts the
    state when it calls it: the `AddField` above is already applied, so the
    registry has the `position` column the function is about to write.
    """
    global _historical_apps
    if _historical_apps is None:
        migration = the_migration.Migration("0003_where_a_paper_prints", "gradebook")
        state = MigrationLoader(None, ignore_no_migrations=True).project_state(
            migration.dependencies
        )
        for operation in migration.operations:
            if isinstance(operation, RunPython):
                break
            operation.state_forwards("gradebook", state)
        _historical_apps = state.apps
    return _historical_apps


#: Sat in this order. Alphabetically they are "Exam, First CA, Second CA".
SAT_IN_ORDER = ("First CA", "Second CA", "Exam")
TERM = TermName.SECOND.value


class PrintOrderSetUp(ReportCardApiSetUp):
    """Three papers per subject, in both schools, created in the order sat.

    Two schools rather than one, because the backfill numbers per
    `(term, subject)` *within a schema*, and a numbering that leaked across
    tenants would still look correct read from either side on its own.
    """

    def setUp(self):
        super().setUp()
        for school, child in ((self.stmarys, self.ada), (self.grace, self.ngozi)):
            for subject_key in ("maths", "english"):
                for index, name in enumerate(SAT_IN_ORDER):
                    self._mark(school, TERM, child, subject_key, name, 50 + index * 10)
        for school, child in ((self.stmarys, self.bola),):
            for subject_key in ("maths", "english"):
                for index, name in enumerate(SAT_IN_ORDER):
                    self._mark(school, TERM, child, subject_key, name, 40 + index * 10)

    def papers_in(self, school, subject_key="maths"):
        """`(name, position)` for one subject's papers, in stored order."""
        with connected_to(school):
            return [
                (paper.name, paper.position)
                for paper in Assessment.objects.filter(
                    term=self.term_of(school, TERM),
                    subject_id=self.subjects_of(school)[subject_key],
                ).order_by("id")
            ]

    def printed_order(self, school):
        """Exactly what the freeze would copy onto a card, as it would order it."""
        with connected_to(school):
            term = self.term_of(school, TERM)
            subject_ids = list(self.subjects_of(school).values())
            return [
                (paper.subject.name, paper.name, paper.pk)
                for paper in cards._assessments_for(term, subject_ids)
            ]

    def run_the_backfill(self, school):
        with connected_to(school):
            the_migration.number_papers_by_creation_order(historical_apps(), None)


class TheBackfillTests(PrintOrderSetUp):
    """`0003` over rows that already exist, which is the case it must get right."""

    def test_the_staging_is_real(self):
        """The control against a silent no-op on an empty table.

        If this class ever stages nothing, every assertion below passes
        vacuously. So: the papers are there, and none of them is numbered yet —
        which is the shape `0003` finds, the column freshly added with its
        default.
        """
        for school in (self.stmarys, self.grace):
            with self.subTest(school=school.name):
                papers = self.papers_in(school)
                self.assertEqual([name for name, _ in papers], list(SAT_IN_ORDER))
                self.assertEqual([position for _, position in papers], [0, 0, 0])

    def test_the_backfill_numbers_papers_by_creation_order_in_tens(self):
        self.run_the_backfill(self.stmarys)

        self.assertEqual(
            self.papers_in(self.stmarys),
            [("First CA", 10), ("Second CA", 20), ("Exam", 30)],
        )

    def test_each_subject_is_numbered_from_the_start(self):
        """Per `(term, subject)`, because that is the set a card's columns come
        from. Numbering across the whole table would be a different order
        wearing the same name."""
        self.run_the_backfill(self.stmarys)

        for subject_key in ("maths", "english"):
            with self.subTest(subject=subject_key):
                self.assertEqual(
                    [p for _, p in self.papers_in(self.stmarys, subject_key)],
                    [10, 20, 30],
                )

    def test_the_other_school_is_numbered_within_its_own_schema(self):
        """Grace's papers start at 10 too, and St Mary's are untouched by hers."""
        self.run_the_backfill(self.grace)

        self.assertEqual(
            [p for _, p in self.papers_in(self.grace)], [10, 20, 30]
        )
        self.assertEqual(
            [p for _, p in self.papers_in(self.stmarys)], [0, 0, 0]
        )


class TheOrderIsUnchangedTests(PrintOrderSetUp):
    """The actual claim: `0003` writes down the order, it does not change it."""

    def test_the_printed_order_is_byte_identical_across_the_backfill(self):
        before = self.printed_order(self.stmarys)
        self.assertTrue(before, "nothing to compare — the staging built no papers")

        self.run_the_backfill(self.stmarys)

        self.assertEqual(self.printed_order(self.stmarys), before)

    def frozen_columns(self, school, membership, version):
        """One card version's columns as stored: `(subject, ordinal, name)`."""
        with connected_to(school):
            card = ReleasedCard.objects.get(
                term=self.term_of(school, TERM),
                student_membership_id=membership.pk,
                version=version,
            )
            return [
                (line.subject_id, line.position, line.assessment_name)
                for line in card.assessment_scores.order_by(
                    "subject_id", "position", "id"
                )
            ]

    def test_a_card_frozen_after_the_backfill_agrees_with_one_frozen_before(self):
        """The failure this whole decision exists to prevent.

        Re-reading the *same* frozen rows after the migration proves almost
        nothing — the backfill writes to `Assessment`, never to a released card,
        so those rows could hardly differ. The claim worth testing is the one a
        parent could notice: a card frozen **after** the backfill must carry the
        same columns, in the same places, as one frozen **before** it. So this
        releases, backfills, then reissues, and compares version 2 against
        version 1.

        `ReleasedAssessmentScore.position` is an ordinal — `1, 2, 3` from
        `enumerate()` over `cards._assessments_for()` — not a copy of
        `Assessment.position`. That is what makes the comparison meaningful: the
        ordinal follows the *ordering*, so a backfill that reshuffled would put
        different names against the same numbers, and the two versions of one
        child's card for one term would disagree.
        """
        self.release(self.stmarys, TERM)
        before = self.frozen_columns(self.stmarys, self.ada, version=1)
        self.assertTrue(before, "nothing was frozen — the release did nothing")

        self.run_the_backfill(self.stmarys)

        with connected_to(self.stmarys):
            revision.revise(
                self.ada,
                self.term_of(self.stmarys, TERM),
                self.principal,
                "Reissued to compare the column order across the backfill.",
            )

        self.assertEqual(
            self.frozen_columns(self.stmarys, self.ada, version=2),
            before,
            "a card frozen after the backfill disagrees with one frozen before",
        )
        self.assertEqual(
            self.frozen_columns(self.stmarys, self.ada, version=1),
            before,
            "the migration wrote into a card that had already been released",
        )

    def test_the_order_is_the_one_sat_and_not_the_alphabetical_one(self):
        """Guards the premise. If these ever coincide the tests above stop
        distinguishing anything, and this is what says so out loud."""
        names = [name for _, name, _ in self.printed_order(self.stmarys)]
        maths = [n for n in names if n in SAT_IN_ORDER][:3]

        self.assertEqual(maths, list(SAT_IN_ORDER))
        self.assertNotEqual(maths, sorted(SAT_IN_ORDER))
