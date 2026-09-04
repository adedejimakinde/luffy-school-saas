"""Task 7: the rendered card, and what must not be on it.

Two claims, and the second is the one with teeth.

**It renders.** WeasyPrint produces a real PDF from a real released card, in an
environment with Pango and a font — which is an assertion about the deployment
as much as about this code, and `schools.tests.test_background` already makes
the environment half of it.

**It cannot leak a staff-only field, structurally.** The renderer is handed
`card_api.card_payload()`, which has no slot for `position`, `roster_size`,
`subject_position`, the term-absence reasons or the promotion suggestion. The
tests below assert those numbers are absent from the rendered HTML *while
proving the same numbers are on the card row* — because "absent from the page"
has two causes, and only one of them is the exclusion working.

And then the job around it, which is a separate set of claims: that the file
lands in the school named by the message and not the one the connection happened
to be left on, that running it twice leaves one row rather than two, and that a
render which dies leaves a **reason** where the file would have been. Those last
two are not tidiness — `acks_late` means a killed worker's message is handed to
another worker, so a job that is unsafe to run twice is a bug, and a failure that
writes nothing is a card that is simply missing with no way to find out why.
"""

import time
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils.html import escape

from academics.models import Term, TermName
from academics.services import place_student
from accounts.models import User
from accounts.services import enroll_student
from gradebook.models import Assessment
from results import cards, pdf
from results.models import PdfState, ReleasedCard, ReleasedCardPdf
from results.tasks import render_card_pdf
from results.tests.test_card_api import PASSWORD, ReportCardApiSetUp
from schools.tests.test_tenant_isolation import connected_to


class TheRenderedPageTests(ReportCardApiSetUp):
    """What the HTML says, asserted as text so no Pango is needed to read it."""

    def setUp(self):
        super().setUp()
        self.release()

    def card(self):
        """The lookup, in a context of its own — safe to call from inside one.

        This is the obvious way to write the helper, and until issue #58 it was
        the broken one. `connected_to` forced `public` on the way out, so a card
        fetched here and rendered by a caller that had opened its own block died
        on `relation "results_releasedsubjectresult" does not exist`: a
        `ReleasedCard` is a lazy object whose subject lines, sections and
        remarks are all still unread, and they were read after the inner block
        had already dropped the connection. This module worked around it by
        keeping a second, context-free lookup and repeating the block in every
        helper. The helper nests now, so there is one lookup again.
        """
        with connected_to(self.stmarys):
            return cards.card_for(
                self.ada, self.term_of(self.stmarys, TermName.FIRST.value)
            )

    def html(self):
        """And this is the nesting: `card()` opens and closes a block of its own
        inside this one, and the lazy reads `html_for` makes afterwards still
        land on St Mary's. Before issue #58 they landed on `public`."""
        with connected_to(self.stmarys):
            return pdf.html_for(self.card())

    def test_no_template_source_reaches_the_page(self):
        """No comment, tag or variable delimiter survives into the output.

        Two multi-line `{# … #}` blocks in this template were **not comments**.
        Django's lexer matches that form with a non-greedy `.` and no
        `re.DOTALL`, so one spanning more than a single line is never recognised
        as a comment token and every line of it is emitted as text. One sat
        inside the masthead, so about fifteen lines of developer prose printed
        directly under the school name on the card a family reads; the other was
        in the attendance cell and leaked on exactly the row shape its branch
        was written for.

        Every other test here asserts that something expected is **present**,
        which is why none of them saw it: the leaked prose happened to contain
        none of the strings they look for, and the staff-only tests look for
        `position` and `Rank`, which developer prose about a badge does not use.
        A page can be wrong by containing something, not only by missing
        something, and this is the assertion for that direction.
        """
        html = self.html()

        for delimiter in ("{#", "#}", "{%", "{{", "}}"):
            self.assertNotIn(
                delimiter,
                html,
                f"Template source {delimiter!r} reached the rendered card.",
            )

    def test_the_page_carries_the_things_a_family_reads(self):
        """Asserted through `escape()`, and that is not a workaround.

        St Mary's has an apostrophe, and Django's autoescaping renders it
        `St Mary&#x27;s` — so a raw `assertIn("St Mary\'s", html)` fails against
        a page that is perfectly correct. Escaping the expected value rather
        than unescaping the page keeps the assertion on what was actually
        written, and pins the property that matters more than the apostrophe: a
        school, class or child name is somebody's typed input, and it reaches
        this template as **text**, not as markup.
        """
        html = self.html()
        for expected in ("Ada Obi", "St Mary's", "JSS 1A", "Mathematics"):
            with self.subTest(expected=expected):
                self.assertIn(escape(expected), html)

    def test_a_name_that_looks_like_markup_is_printed_and_not_obeyed(self):
        """The other half of that, since the fixture's apostrophe raised it.

        Every name on this card is copied from something a person typed. A card
        is not a browser, but a name that closed the surrounding tag would break
        the page's structure for every field after it, and the frozen name is
        kept for as long as the card exists.
        """
        with connected_to(self.stmarys):
            card = self.card()
            card.student_name = "<script>Ada</script>"
            html = pdf.html_for(card)

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_the_control_the_staff_only_numbers_really_are_on_the_row(self):
        """Without this, every absence test below passes against an empty card.

        `TheSnapshotReallyHoldsTheStaffOnlyNumbers` makes the same argument for
        the JSON payload, and it is the same argument: absence has two causes.
        """
        card = self.card()
        self.assertIsNotNone(card.position)
        self.assertEqual(card.roster_size, 2)

    def test_the_class_position_is_not_on_the_page(self):
        """Nigerian secondary schools do not print position — `card_api` says so.

        Asserted on the rendered HTML rather than on the payload, because this
        is the surface where a template could have reached past the payload for
        it. `roster_size` is 2 here, which is why the position is 1 and why the
        assertion below is about the label rather than the digit: a bare "1"
        appears legitimately in a dozen places on a card.
        """
        html = self.html()
        for absent in ("Position", "position", "Rank", "out of"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, html)

    def test_the_renderer_is_given_no_way_to_print_one(self):
        """The structural half, and the half that survives a template rewrite.

        The test above says today's template does not print a position. This
        says a future one could not: the object it is handed has no such
        attribute, so a template reaching for it renders empty rather than
        leaking, and a developer adding the column finds nothing to fill it.
        """
        from results.card_api import card_payload

        with connected_to(self.stmarys):
            payload = card_payload(self.card())
        for absent in ("position", "roster_size"):
            with self.subTest(absent=absent):
                self.assertFalse(
                    hasattr(payload, absent),
                    f"{absent} is reachable from the template.",
                )
        for line in payload.subjects:
            self.assertFalse(hasattr(line, "subject_position"))


class TheColumnsAreTheUnionTests(ReportCardApiSetUp):
    """An assessment belongs to a subject, so two subjects need not share one.

    A header row taken from the first subject would label Mathematics' columns
    and print English's marks under them. This is the case that catches it: the
    two subjects are marked in assessments with *different names*.
    """

    def setUp(self):
        super().setUp()
        self._mark(self.stmarys, TermName.FIRST.value, self.ada, "maths", "Mid-term", 12)
        self._mark(self.stmarys, TermName.FIRST.value, self.bola, "maths", "Mid-term", 9)
        self.release()

    def test_every_assessment_name_gets_a_column(self):
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST.value))
            from results.card_api import card_payload

            columns = pdf._columns(card_payload(card))

        names = [column["name"] for column in columns]
        self.assertIn("Exam", names)
        self.assertIn("Mid-term", names)
        keys = [(column["name"], column["max_score"]) for column in columns]
        self.assertEqual(len(keys), len(set(keys)), "A column was repeated.")

    def test_a_subject_without_one_gets_a_gap_and_not_a_shifted_row(self):
        """The bug this alignment exists to prevent, stated as a row length.

        English has no Mid-term. Its cells must still be as long as the header,
        with a `None` where the assessment does not exist — otherwise the row
        shifts left and English's Exam mark prints under the Mid-term column.
        """
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST.value))
            from results.card_api import card_payload

            payload = card_payload(card)
            columns = pdf._columns(payload)
            rows = pdf._rows(payload, columns)

        self.assertGreater(len(rows), 1)
        for row in rows:
            with self.subTest(subject=row["line"].subject_name):
                self.assertEqual(len(row["cells"]), len(columns))

        english = next(r for r in rows if r["line"].subject_name == "English")
        names = [column["name"] for column in columns]
        self.assertIsNone(english["cells"][names.index("Mid-term")])


class ItReallyProducesAPdfTests(ReportCardApiSetUp):
    """One real render, through Pango, asserting the bytes are a PDF."""

    def test_a_released_card_renders_to_a_pdf(self):
        self.release()
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST.value))
            content = pdf.render(card)

        self.assertTrue(content.startswith(b"%PDF-"), content[:16])
        self.assertGreater(len(content), 1000)


class FortyFiveCardsTests(ReportCardApiSetUp):
    """**The measurement the task asked for**, and a correctness claim with it.

    Forty-five is a Nigerian class, and the question is whether a principal
    pressing "release" can be handed a batch that finishes. The number is
    printed rather than asserted: a threshold assertion on wall-clock time is a
    test that goes red on a busy CI runner and teaches everyone to ignore it.
    What *is* asserted is that all forty-five render, and that each is a
    distinct file for the child it names — a batch that renders the same card
    forty-five times would be fast and wrong.
    """

    CLASS_SIZE = 45

    def setUp(self):
        super().setUp()
        term_name = TermName.FIRST.value
        self.extras = []
        with connected_to(self.stmarys):
            group = self.group_of(self.stmarys)
            term = self.term_of(self.stmarys, term_name)
        # Two children exist already; add the rest of a full class.
        for index in range(self.CLASS_SIZE - 2):
            child = enroll_student(
                User.objects.create_user(
                    f"pupil{index}", PASSWORD, full_name=f"Pupil Number {index}"
                ),
                self.stmarys,
            )
            with connected_to(self.stmarys):
                place_student(group, term, child)
            self.extras.append(child)
            self._mark(
                self.stmarys, term_name, child, "maths", "Exam", 40 + index % 55
            )
            self._mark(
                self.stmarys, term_name, child, "english", "Exam", 35 + index % 60
            )

        self.release()

    def test_a_class_of_forty_five_renders_and_the_seconds_are_reported(self):
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            roster = list(ReleasedCard.objects.filter(term=term).order_by("id"))
            self.assertEqual(len(roster), self.CLASS_SIZE)

            started = time.perf_counter()
            files = [pdf.render(card) for card in roster]
            seconds = time.perf_counter() - started

        total = sum(len(f) for f in files)
        print(
            f"\n[task 7] {self.CLASS_SIZE} cards rendered in {seconds:.2f}s "
            f"({seconds / self.CLASS_SIZE * 1000:.0f} ms/card), "
            f"{total / 1024:.0f} KiB total, "
            f"{total / self.CLASS_SIZE / 1024:.1f} KiB/card"
        )

        for content in files:
            self.assertTrue(content.startswith(b"%PDF-"))
        # Every card is a different child's, so no two files are identical. A
        # renderer that ignored its argument would pass every assertion above.
        self.assertEqual(len(set(files)), self.CLASS_SIZE)


class TheJobSetUp(ReportCardApiSetUp):
    """Both schools release, because the job's argument is a schema name.

    Grace releases too, and is used below rather than merely built. That is not
    ceremony: each tenant schema has **its own sequences**, so Grace's card and
    Ada's card can carry the same primary key, and a job that ignored its schema
    name would write one school's file into the other's schema while every
    count in these tests still read 1. The assertions are on the child's name.
    """

    def setUp(self):
        super().setUp()
        self.release()
        self.release(self.grace)

    def card_in(self, school):
        child = self.ada if school == self.stmarys else self.ngozi
        with connected_to(school):
            return cards.card_for(child, self.term_of(school, TermName.FIRST.value))


class TheStoredFileTests(TheJobSetUp):
    """What `render_card_pdf` leaves behind when it works."""

    def test_the_job_stores_the_file_against_the_card(self):
        card = self.card_in(self.stmarys)

        returned = render_card_pdf.apply(args=["st_marys", card.pk]).get()

        with connected_to(self.stmarys):
            row = ReleasedCardPdf.objects.get(card_id=card.pk)
            content = bytes(row.content)

        self.assertTrue(content.startswith(b"%PDF-"), content[:16])
        self.assertEqual(row.byte_size, len(content))
        self.assertEqual(row.error, "")
        # The task returns a size rather than the bytes, because there is no
        # result backend and the only reader is the worker log.
        self.assertEqual(returned, len(content))

    def test_running_it_twice_replaces_the_row_rather_than_adding_a_second(self):
        """The idempotence `acks_late` requires, asserted rather than asserted-in-prose.

        A worker killed mid-render hands its message back and another worker
        runs the same job again. If that second run appended, a card would end
        up with two files and nothing to say which one a parent was given —
        and `ReleasedCardPdf.card` being a `OneToOne` means it would not even
        get that far: it would raise, and the redelivery would fail for ever.
        """
        card = self.card_in(self.stmarys)

        render_card_pdf.apply(args=["st_marys", card.pk]).get()
        with connected_to(self.stmarys):
            first = ReleasedCardPdf.objects.get(card_id=card.pk)
            first_pk, first_built = first.pk, first.built_at

        render_card_pdf.apply(args=["st_marys", card.pk]).get()
        with connected_to(self.stmarys):
            rows = list(ReleasedCardPdf.objects.filter(card_id=card.pk))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].pk, first_pk, "The second run made a new row.")
        self.assertTrue(bytes(rows[0].content).startswith(b"%PDF-"))
        # `built_at` is `auto_now`: it records when this file was made, so the
        # rebuild moves it. Not `assertGreater` — two renders can land in the
        # same microsecond on a fast machine and that is not a failure.
        self.assertGreaterEqual(rows[0].built_at, first_built)

    def test_the_schema_argument_decides_which_school_gets_the_file(self):
        """The tenancy claim, made where per-schema sequences make it easy to fake.

        Grace's only card and St Mary's first card are both id 1. A renderer
        that took the schema from whatever the connection was left on would
        satisfy `objects.get()` in the wrong school, so the assertion is on the
        name of the child the file is for.
        """
        theirs = self.card_in(self.grace)

        render_card_pdf.apply(args=["grace", theirs.pk]).get()

        with connected_to(self.grace):
            row = ReleasedCardPdf.objects.get()
            self.assertEqual(row.card.student_name, "Ngozi Ade")
        with connected_to(self.stmarys):
            # Not `exists()` any more: since issue #56 every released card
            # carries a `PENDING` marker, so St Mary's has rows either way.
            # What must not be here is a row a *job* wrote.
            self.assertFalse(
                ReleasedCardPdf.objects.exclude(state=PdfState.PENDING).exists(),
                "Grace's file was written into St Mary's schema.",
            )


class AFailedRenderIsARowTests(TheJobSetUp):
    """A render that dies leaves a reason, in the school it died in.

    The whole point of `schools.tasks.TenantTask` wrapping the handlers a
    subclass brings: Celery's tracer calls `on_failure` *outside* the
    `tenant_context` block `__call__` opens, so this write went to `public`
    before that landed — a `ProgrammingError` naming a missing relation, raised
    from the failure handler, on top of the error somebody actually needed.
    """

    def test_a_render_that_dies_leaves_a_row_saying_why(self):
        card = self.card_in(self.stmarys)

        with patch("results.pdf.render", side_effect=RuntimeError("no fonts")):
            result = render_card_pdf.apply(args=["st_marys", card.pk])

        self.assertTrue(result.failed())
        with connected_to(self.stmarys):
            row = ReleasedCardPdf.objects.get(card_id=card.pk)

        self.assertIsNone(row.content)
        self.assertIsNone(row.byte_size)
        self.assertIn("RuntimeError", row.error)
        self.assertIn("no fonts", row.error)

    def test_the_failure_is_recorded_in_the_school_that_failed(self):
        theirs = self.card_in(self.grace)

        with patch("results.pdf.render", side_effect=RuntimeError("no fonts")):
            render_card_pdf.apply(args=["grace", theirs.pk])

        with connected_to(self.grace):
            row = ReleasedCardPdf.objects.get()
            self.assertEqual(row.card.student_name, "Ngozi Ade")
        with connected_to(self.stmarys):
            self.assertFalse(
                ReleasedCardPdf.objects.exclude(state=PdfState.PENDING).exists(),
                "Grace's failure was recorded in St Mary's schema.",
            )

    def test_a_card_that_rendered_before_stops_claiming_a_file_when_it_fails(self):
        """`update_or_create`, not `create`, and this is what that buys.

        A card rendered last week and failing today must end up saying it has
        no file *now*. A stale success sitting beside a fresh failure is a row
        that answers "is there a file" with yes and "did it work" with no.
        """
        card = self.card_in(self.stmarys)
        render_card_pdf.apply(args=["st_marys", card.pk]).get()

        with patch("results.pdf.render", side_effect=RuntimeError("no fonts")):
            render_card_pdf.apply(args=["st_marys", card.pk])

        with connected_to(self.stmarys):
            rows = list(ReleasedCardPdf.objects.filter(card_id=card.pk))

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].content)
        self.assertIsNone(rows[0].byte_size)
        self.assertIn("no fonts", rows[0].error)

    def test_a_failure_handler_that_itself_dies_does_not_replace_the_real_error(self):
        """The swallow in `on_failure`, which is otherwise invisible.

        If recording the failure raised, the worker log would carry the
        recorder's exception in place of the render's — and the render's is the
        one somebody is trying to read. This asserts the task still fails with
        the error it actually had.
        """
        card = self.card_in(self.stmarys)

        with patch("results.pdf.render", side_effect=RuntimeError("no fonts")):
            with patch(
                "results.tasks._record_the_failure",
                side_effect=ValueError("and the recorder broke too"),
            ):
                result = render_card_pdf.apply(args=["st_marys", card.pk])

        self.assertTrue(result.failed())
        self.assertIsInstance(result.result, RuntimeError)
        self.assertIn("no fonts", str(result.result))


class ACardPdfIsPendingAFileOrAReasonTests(ReportCardApiSetUp):
    """The two check constraints, asserted **by name**.

    A bare `assertRaises(IntegrityError)` cannot tell the constraint under test
    from the several ways of never reaching it — a NOT NULL, a unique violation,
    a foreign key. Postgres checks those first, so the name is the assertion.

    **These write with `update()` where they used to `create()`.** Issue #56
    gave every released card a `PENDING` row inside the release itself, so the
    row is already there when a test here starts, and a `create()` would now be
    refused by the `OneToOne` on `card` before any check constraint was
    consulted — a test that still fails, for a reason it does not name, having
    stopped asserting the thing it was written for. `update()` is also the
    writer that matters: `render_card_pdf` upserts, and the queryset update is
    the path that skips `save()` entirely.

    The constraint gained a third legal shape and lost one it used to refuse:
    the row with neither a file nor a reason, which the old name called "a job
    that reported nothing", is now what a release writes for every card it
    freezes. `test_the_row_a_release_writes_is_the_one_that_used_to_be_refused`
    is that inversion, pinned so it cannot be undone by accident.
    """

    def setUp(self):
        super().setUp()
        self.release()

    def card(self):
        with connected_to(self.stmarys):
            return cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST.value))

    def refuse(self, **fields):
        card = self.card()
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError) as caught:
                with transaction.atomic():
                    ReleasedCardPdf.objects.filter(card=card).update(**fields)
        return str(caught.exception)

    def accept(self, **fields):
        card = self.card()
        with connected_to(self.stmarys):
            ReleasedCardPdf.objects.filter(card=card).update(**fields)
            return ReleasedCardPdf.objects.get(card=card)

    # -- what the state promises about the other two columns -----------------

    def test_a_row_claiming_both_a_file_and_an_error_is_refused(self):
        message = self.refuse(
            state=PdfState.BUILT,
            content=b"%PDF-1.7 pretend",
            byte_size=16,
            error="and it also failed",
        )
        self.assertIn("a_card_pdf_is_pending_a_file_or_a_reason", message)

    def test_a_row_that_says_it_is_built_and_holds_nothing_is_refused(self):
        """The lie the old constraint could not tell, because there was no `state`.

        A partial update — `.update(state=BUILT)` from a job that wrote the
        state and lost the bytes — is a row answering "is there a file" with
        yes and holding none.
        """
        message = self.refuse(state=PdfState.BUILT)
        self.assertIn("a_card_pdf_is_pending_a_file_or_a_reason", message)

    def test_a_row_that_says_it_failed_and_gives_no_reason_is_refused(self):
        message = self.refuse(state=PdfState.FAILED)
        self.assertIn("a_card_pdf_is_pending_a_file_or_a_reason", message)

    def test_a_card_still_owed_a_file_cannot_already_hold_one(self):
        """`PENDING` means *not built yet*, and a row holding bytes is past that.

        This is the one a job that forgot to move the state off `PENDING` would
        write, and it is refused rather than silently leaving the download route
        telling a parent to come back for a file it is sitting on.
        """
        message = self.refuse(content=b"%PDF-1.7 pretend", byte_size=16)
        self.assertIn("a_card_pdf_is_pending_a_file_or_a_reason", message)

    def test_a_card_still_owed_a_file_cannot_already_carry_a_reason(self):
        message = self.refuse(error="it failed")
        self.assertIn("a_card_pdf_is_pending_a_file_or_a_reason", message)

    # -- and what the size promises about the file ---------------------------

    def test_a_file_that_does_not_know_its_own_size_is_refused(self):
        message = self.refuse(state=PdfState.BUILT, content=b"%PDF-1.7 pretend")
        self.assertIn("a_card_pdf_knows_its_own_size", message)

    def test_a_size_without_a_file_is_refused(self):
        message = self.refuse(state=PdfState.FAILED, byte_size=16, error="it failed")
        self.assertIn("a_card_pdf_knows_its_own_size", message)

    def test_a_size_that_is_not_the_size_of_the_file_is_refused(self):
        """`byte_size` is denormalised, so nothing but this constraint holds it
        true. The row below is what a `.update(content=...)` that forgot to
        recompute it leaves behind: a file of one length claiming another."""
        message = self.refuse(
            state=PdfState.BUILT, content=b"%PDF-1.7 pretend", byte_size=9999
        )
        self.assertIn("a_card_pdf_knows_its_own_size", message)

    def test_a_rewrite_that_forgets_the_size_is_refused(self):
        """The path that makes the above more than theoretical. This table is
        deliberately rewritable — that is the argument its model makes — so the
        queryset `update()` that skips `save()` is a real writer, and the
        database has to be the thing that catches it."""
        card = self.card()
        with connected_to(self.stmarys):
            ReleasedCardPdf.objects.filter(card=card).update(
                state=PdfState.BUILT, content=b"12345", byte_size=5
            )
            with self.assertRaises(IntegrityError) as caught:
                with transaction.atomic():
                    ReleasedCardPdf.objects.filter(card=card).update(
                        content=b"a much longer pretend document"
                    )
        self.assertIn("a_card_pdf_knows_its_own_size", str(caught.exception))

    # -- the controls --------------------------------------------------------

    def test_the_control_a_row_that_says_one_thing_is_accepted(self):
        """Without this, every test above passes against a table nothing can write to."""
        built = self.accept(
            state=PdfState.BUILT, content=b"%PDF-1.7 pretend", byte_size=16, error=""
        )
        self.assertEqual(built.error, "")
        self.assertEqual(bytes(built.content[:5]), b"%PDF-")

        failed = self.accept(
            state=PdfState.FAILED, content=None, byte_size=None, error="It failed."
        )
        self.assertIsNone(failed.content)

    def test_the_row_a_release_writes_is_the_one_that_used_to_be_refused(self):
        """The inversion, pinned. This shape was `a_card_pdf_is_a_file_or_a_reason_and_not_both`'s
        headline refusal — *"a job that reported nothing"* — and is now what a
        release writes for every card, before any job has run at all."""
        card = self.card()
        with connected_to(self.stmarys):
            marker = ReleasedCardPdf.objects.get(card=card)

        self.assertEqual(marker.state, PdfState.PENDING)
        self.assertIsNone(marker.content)
        self.assertIsNone(marker.byte_size)
        self.assertEqual(marker.error, "")


class AttendanceOfNoughtTests(ReportCardApiSetUp):
    """Nought days present is a number, and it must not print as "not recorded".

    Attendance is nullable until Phase 2 *and* legitimately nought, so the two
    have to look different on the page — the same rule the assessment grid
    already keeps between a subject that had no such assessment and a child who
    was not marked in one. The template's first draft used truthiness and
    `default`, which print a dash for both.

    The zero is supplied through the payload rather than written onto the row,
    because `ReleasedCard` is append-only by database trigger. That is also the
    honest shape of the test: the defect was in the template and nowhere else.
    """

    def setUp(self):
        super().setUp()
        self.release()

    def html_with(self, **attendance):
        from results.card_api import card_payload

        with connected_to(self.stmarys):
            card = cards.card_for(
                self.ada, self.term_of(self.stmarys, TermName.FIRST.value)
            )
            payload = card_payload(card).model_copy(update=attendance)
            with patch("results.pdf.card_payload", return_value=payload):
                return " ".join(pdf.html_for(card).split())

    def test_a_child_present_on_none_of_the_days_open_is_told_so(self):
        self.assertIn("0 of 60 days", self.html_with(days_present=0, days_open=60))

    def test_an_attendance_nobody_recorded_is_still_a_dash(self):
        """The control. Without it the test above passes against a page that
        prints the raw value for everything, dash included."""
        self.assertIn("— of 60 days", self.html_with(days_present=None, days_open=60))

    def test_a_register_kept_without_a_term_length_still_prints_what_is_known(self):
        """The three columns are independently nullable and no constraint ties
        them together, so `days_present` set with `days_open` null is a row the
        database permits. Gating the whole line on `days_open` throws the
        recorded half away and tells a parent nobody kept a register."""
        html = self.html_with(days_present=52, days_open=None, days_absent=None)
        self.assertIn("52 days present", html)

    def test_the_control_nothing_recorded_at_all_is_a_dash(self):
        """Without this the test above passes against a page that prints
        "None days present" when there is genuinely nothing to say."""
        html = self.html_with(days_present=None, days_open=None, days_absent=None)
        self.assertNotIn("days present", html)
        self.assertIn("Attendance", html)


class TheRevisedBadgeTests(ReportCardApiSetUp):
    """A reissued card has to say so, and the first draft's flag did not exist.

    The template asked for `card.is_revised` when this branch was cut, and
    `ReportCardOut` had no such field — Django resolved it to the
    invalid-variable default and the branch was unreachable, so the badge could
    never print. That is invisible until a second version exists, at which point
    the reprinted card is indistinguishable from the one already in a parent's
    hand, which is the single thing the badge exists to prevent. Task 8 has
    since landed and `is_revised` is now real, on the model and on the payload;
    the template asks for it again, and these two tests are what stands between
    that and the same silence returning.

    Driven through the payload rather than through `revise()`, because what is
    under test is the template. That the payload's `is_revised` follows a real
    revision is task 8's, proven in `test_card_api` and `test_revision` — so
    the override here sets `version` and `is_revised` together, exactly as
    `card_payload()` emits them, rather than moving one and leaving the page
    reading the other.
    """

    def setUp(self):
        super().setUp()
        self.release()

    def html_at_version(self, version):
        from results.card_api import card_payload

        with connected_to(self.stmarys):
            card = cards.card_for(
                self.ada, self.term_of(self.stmarys, TermName.FIRST.value)
            )
            payload = card_payload(card).model_copy(
                update={"version": version, "is_revised": version > 1}
            )
            with patch("results.pdf.card_payload", return_value=payload):
                return " ".join(pdf.html_for(card).split())

    def test_a_reissued_card_says_it_is_revised(self):
        html = self.html_at_version(2)
        self.assertIn("Revised", html)
        self.assertIn("version 2", html)

    def test_the_control_a_first_issue_carries_no_badge(self):
        """Without this the test above passes against a page that says
        "Revised" on every card ever printed."""
        self.assertNotIn("Revised", self.html_at_version(1))


class TwoSubjectsCanShareANameAndNotATotalTests(ReportCardApiSetUp):
    """"Exam" out of 120 and "Exam" out of 100 are two assessments, not one.

    `max_score` is per `(term, subject, name)` — `uniq_assessment_term_subject_name`
    says so — so a school may mark Mathematics out of 120 and English out of 100
    and call both "Exam". Keyed on the name alone they collapse into a single
    column, and two equal marks print side by side as equal performance on the
    document a parent is most likely to take to a teacher, when they are not.

    Mathematics is raised to 120 rather than dropped to 60 for a reason worth
    keeping: the fixture has already marked Ada 88 there, and 88 out of 60 is a
    147% subject and a 110% card average, which `a_card_average_is_a_percentage`
    refuses at release. The differing maximum is what this class is about, and
    it does not need an impossible mark to demonstrate it.
    """

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            Assessment.objects.filter(
                term=self.term_of(self.stmarys, TermName.FIRST.value),
                subject_id=self.subjects_of(self.stmarys)["maths"],
                name="Exam",
            ).update(max_score=120)
        self.release()

    def payload_and_columns(self):
        from results.card_api import card_payload

        with connected_to(self.stmarys):
            card = cards.card_for(
                self.ada, self.term_of(self.stmarys, TermName.FIRST.value)
            )
            payload = card_payload(card)
            return card, payload, pdf._columns(payload)

    def test_the_same_name_out_of_two_totals_is_two_columns(self):
        _, _, columns = self.payload_and_columns()
        exams = [c for c in columns if c["name"] == "Exam"]
        self.assertEqual(
            len(exams), 2, f"Two different totals collapsed into one column: {columns}"
        )
        self.assertEqual({c["max_score"] for c in exams}, {100, 120})

    def test_each_subject_aligns_under_its_own_total(self):
        """The alignment half. A second column is no use if the marks still land
        in the first one."""
        _, payload, columns = self.payload_and_columns()
        rows = pdf._rows(payload, columns)
        keys = [(c["name"], c["max_score"]) for c in columns]

        maths = next(r for r in rows if r["line"].subject_name == "Mathematics")
        english = next(r for r in rows if r["line"].subject_name == "English")

        self.assertIsNotNone(maths["cells"][keys.index(("Exam", 120))])
        self.assertIsNone(maths["cells"][keys.index(("Exam", 100))])
        self.assertIsNotNone(english["cells"][keys.index(("Exam", 100))])
        self.assertIsNone(english["cells"][keys.index(("Exam", 120))])

    def test_the_page_prints_the_total_a_mark_is_out_of(self):
        """What the parent actually sees. A bare 45 under a header reading
        "Exam" does not say whether it was a good one."""
        card, _, _ = self.payload_and_columns()
        with connected_to(self.stmarys):
            html = " ".join(pdf.html_for(card).split())
        self.assertIn("/120", html)
        self.assertIn("/100", html)
