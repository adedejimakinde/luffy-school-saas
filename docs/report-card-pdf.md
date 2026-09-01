# The report card as a file

Task 7. Code: `results/pdf.py`, `results/tasks.py`,
`results/templates/results/report_card.html`, `ReleasedCardPdf` in
`results/models.py`, migration `0019_the_rendered_card`, tests in
`results/tests/test_pdf.py`. The queue underneath it is
[background.md](background.md).

## Built from the family payload, never from the row

`card_api.card_payload()` was extracted from the view that served the page so
that the page and the file are assembled **once**. That is not tidiness. Every
staff-only exclusion this phase argued for — `position`, `roster_size`,
`subject_position`, the term-absence reasons, the promotion *suggestion* — is
held by there being **no slot for them in `ReportCardOut`**, and a second
assembly is a second place for a slot to appear.

A template handed a `ReleasedCard` would have all five in scope, and the only
thing between them and a printed page would be a developer remembering. The
tests assert both halves: that the numbers are absent from the rendered HTML,
and — the structural claim — that the object the template is given has no
attribute to print them from.

## The columns are the union of assessment names

An `Assessment` belongs to a subject, so two subjects in one term need not have
the same ones. A header row taken from the first subject would label
Mathematics' columns and print English's marks underneath them. `_columns()`
takes the ordered union; `_rows()` aligns every line against it.

A subject with no such assessment gets `None`, which prints as a gap — a
different thing from a cell whose `score` is null, which is an assessment the
child was not marked in and prints as a dash. Two absences meaning different
things must not look the same on a page somebody will ask a teacher about.

The order is the frozen print order, which within a subject is **creation
order** — the freeze orders by `(subject name, assessment id)` and deliberately
not by `Assessment.Meta.ordering`, which ends in `name`. It is still a guess,
because `Assessment` has no explicit print order. That is **issue #42**, and
this is the surface that makes it must-fix-before-release: it is where the wrong
order becomes visible to a parent.

Across subjects the header is first-seen order, so where two subjects disagree
about the order of names they share, the first subject read wins. One row of
columns cannot honour two orders at once, and #42 is what settles it.

Columns are keyed on `(name, max_score)`, not on the name alone, and the header
carries the maximum. `Assessment.max_score` is per `(term, subject, name)`, so
Mathematics' Exam out of 60 and English's Exam out of 100 are different
assessments; collapsed into one column, 45 and 45 read as equal performance and
are not. The subject total prints its denominator for the same reason.

## `ReleasedCardPdf` is a cache, and is deliberately not append-only

Every other frozen table in `results` refuses a second write, because it holds
what a card **said**. This one holds a *rendering* of a card whose every number
already refuses to move, so a re-render after a stylesheet fix can change a
layout and cannot change a figure. Making it append-only would only mean a typo
in the CSS could never be corrected.

The bytes live in a Postgres column. This platform configures no object storage
and no `MEDIA_ROOT`, and a schema-per-school layout would need a per-tenant path
convention invented to go with them; a column comes with tenant isolation,
transactional writes and backups already solved. A card is tens of kilobytes and
a class a couple of megabytes, so it fits — but it does not scale to a thousand
schools keeping every year for ever, and this is the row to move first.

A failed render writes the **reason** into the same row rather than leaving
silence, and a constraint refuses a row claiming both a file and an error.

## The failure handler is the first real user of `TenantTask`'s handler wrapping

`RenderACard.on_failure` writes that failure into the school's own table.
Celery's tracer calls that handler *outside* the `with tenant_context(...)`
block `__call__` opens, so before [background.md](background.md)'s wrapping
landed it would have run on `public` — a `ProgrammingError` naming a missing
relation, raised from the failure handler, on top of the real error somebody
actually needed. Its body is the first line that runs, before any `super()`
call, which is exactly the placement a base-class override could not protect.

## One job per card, not one job per class

`docs/cards.md` said "task 7 renders forty-five of these in one Celery job",
written before the job existed. It is one job **per card**, and the reversal is
worth the paragraph.

`acks_late` and `task_reject_on_worker_lost` mean a worker killed on the
forty-fourth card hands the message back and another worker runs it again. Under
a per-class job that is forty-four re-renders to reach the one that was lost.
And `visibility_timeout` is 300 seconds — the interval after which kombu decides
a message was never handled and gives it to somebody else — so a per-class job
has to finish inside it or be redelivered *alongside itself*. Forty-five cards
at the measured rate fits today, with no margin to speak of for a school with
more subjects, more children or a slower machine.

Per card, redelivery costs one render, the timeout is never close, and a second
worker can take half the class. The cost is forty-five messages per release
instead of one, which Redis does not notice.

## Idempotent, because `acks_late` requires it

`settings.py` states the rule: a worker killed mid-render hands the message back
and another worker runs it again, so a task that is not safe to run twice has to
say so. This one is safe and not by luck — it renders a frozen snapshot, and the
write is an upsert keyed on the card.

## The measurement

`FortyFiveCardsTests` builds a Nigerian class of forty-five, releases it, and
renders every card, printing the seconds. The number is **printed, not
asserted**: a wall-clock threshold in a test suite goes red on a busy runner and
teaches everyone to ignore it. What is asserted is that all forty-five render,
and that no two files are identical — a renderer that ignored its argument would
be fast and wrong.

## Two absences, and a third that is a number

The page has to keep three things apart that a careless template prints
identically:

| on the page | means |
| --- | --- |
| `·` in an assessment cell | this subject has no such assessment at all |
| `—` in an assessment cell | the child was not marked in it |
| `0 of 60 days` | present on none of the days the school was open |

The last one is why the attendance cell tests `is not None` and filters with
`default_if_none` rather than `default`: attendance is nullable until Phase 2
**and** legitimately nought, and truthiness cannot tell those apart. Nought
versus null is a mistake this codebase has made before, in the session
averaging, and a dash where a zero belongs is a parent being told nobody kept a
register when in fact their child was never there.

## What the tests cover beyond the rendering

`TheStoredFileTests` and `AFailedRenderIsARowTests` are about the job rather
than the renderer: that the file lands in the school named by the **message**
and not the schema the connection was left on — asserted on the child's name,
because per-schema sequences let both schools' cards carry id 1 — that a second
run replaces the row rather than adding one, that a render which dies leaves a
reason, and that a failure handler which itself dies does not replace the real
error with its own.

`ACardPdfIsAFileOrAReasonTests` asserts both check constraints **by name**. A
bare `IntegrityError` cannot tell the constraint under test from the several
ways of never reaching it, and Postgres evaluates NOT NULL and uniqueness first.
