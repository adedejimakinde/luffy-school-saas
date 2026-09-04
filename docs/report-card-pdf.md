# The report card as a file

Task 7, and then issue #56, which gave it a way in and a way out. Code:
`results/pdf.py`, `results/tasks.py`, `results/renders.py`,
`report_card_pdf()` in `results/card_api.py`,
`results/templates/results/report_card.html`, `ReleasedCardPdf` and `PdfState`
in `results/models.py`, migrations `0021_the_rendered_card` and
`0022_a_card_owes_a_file_from_the_moment_it_is_released`, tests in
`results/tests/test_pdf.py` and `results/tests/test_renders.py`. The queue
underneath it is [background.md](background.md).

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
silence, and the check constraint refuses the three lies the states can tell: a
row that says it is built and holds nothing, one that says it failed and gives
no reason, and one that says a file is still owed while carrying either.

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
worker can take half the class. The cost would be forty-five messages per
release instead of one, which Redis does not notice.

Forty-five messages per release, published one per card by
`renders.mark_and_enqueue()`. That was [issue #56][56], and what it took is the
next three sections.

[56]: https://github.com/adedejimakinde/luffy-school-saas/issues/56

## The marker is written at release, before anything is rendered

The half of #56 that produces silent missing files was never the failed render.
A failure was always visible — `on_failure` writes the reason into the school's
own table. It was the render **nobody ever asked for**: a Redis that was down, a
worker that never came back, a message lost between the two. `ReleasedCardPdf`
would then have no row at all, and *no row* is also the normal state of a card
before it is released. The absence could not be interrogated, and the first
person to find out was a parent, weeks later, who could not open their child's
report card.

So `renders.mark_and_enqueue()` writes a `PENDING` row for every card **inside
the transaction that freezes it**, and asks for the render only after that
transaction commits. A school's database now says "this card owes a file" from
the moment the card exists. `PdfState` argues why there are three states and not
four: a `QUEUED` written by the enqueuer and cleared by the worker would say
whether a job is in flight, and a worker that died between the two would strand
a card in it for ever — because the recovery path for a lost job is exactly "a
download of a `PENDING` card asks again", and a fourth state switches that path
off for the cards that need it most.

Both card-writing paths call it: `services.release()` for a class and
`revision.revise()` for one child. The second is not an afterthought — it is the
only path by which a child placed into a term after it was released
([revision.md](revision.md), issue #31) gets a card at all, so marking at
release alone would leave hers the one card on the platform with no marker and
no file.

Migration `0022` gives every card released before all this a `PENDING` row too,
per schema, so the invariant holds on real data rather than only on data written
from today. Without that backfill the download route would need a "no row"
branch for ever, and `ReleasedCardPdf`'s own docstring — *every released card
has a row* — would be false everywhere it mattered.

## `transaction.on_commit`, and a publish that cannot fail the release

A worker is a different process on a different connection. A message published
before the release commits can be picked up immediately, and under READ
COMMITTED that worker sees no card: it raises, `on_failure` writes a `FAILED`
row saying the card does not exist, and the card is fine three milliseconds
later. The failure is indistinguishable from a real one and it is permanent,
because nothing retries a `FAILED` card. So the publish is registered with
`transaction.on_commit` and a bare `.delay()` here is a bug rather than a style.

And `on_commit` callbacks run *after* the commit, which means an exception in
one reaches the caller with the release already durable — a 500 for a principal
whose cards have gone home. Every publish is caught per card and logged, and
`retry=False` keeps a dead broker from holding the request open through Celery's
three retries per card, forty-five times over, to arrive at the same place.

What makes swallowing that exception defensible is the marker: the row is still
there afterwards, saying the file is owed, and the next download asks again.

## The way out, and what it does when there is no file yet

`GET /api/results/cards/{student_membership_id}/{term_id}/pdf/` asks the
identical authority question as the JSON route beside it — the same four calls
in the same order — because a PDF of a card you may read is not a second
permission, and two answers to one question is one answer nobody tested. Every
refusal is that route's flat 404, including "no card for this term", so adding
four characters to a URL cannot turn it into an existence oracle.

A card whose file exists is served as `application/pdf`, named for the child,
the term and the session rather than a primary key, and carrying its version
when there is more than one.

A card whose file does not exist yet is a **202** with the state and a sentence,
and the two states need different sentences: `PENDING` is told to come back,
`FAILED` is told to ask the school. The exception text is deliberately not in
the body — it is a Python class and message written for whoever debugs the
render, and a parent reading `TemplateSyntaxError` learns nothing they can act
on. Nothing renders in the request: WeasyPrint takes a few hundred milliseconds
a card and results week is every parent of a class arriving at once, which is
what moving the render to a worker was for.

The 202 path also **asks again**, which is the recovery for a job that never
reached a worker, driven by the person who actually wants the file rather than
by a sweep nobody wrote. `renders.enqueue_if_pending()` holds the debounce that
keeps that from being a stampede: a card asked for within `RE_ENQUEUE_AFTER` (a
minute, longer than a render) is left alone. **The debounce is a conditional
`UPDATE`, not an `if`** — two requests arriving together would both read
`PENDING` and both enqueue, but Postgres re-evaluates the `WHERE` clause against
the newer row version, so exactly one of the two updates matches and one job is
queued. The check and the claim are one statement.

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

`ACardPdfIsPendingAFileOrAReasonTests` asserts both check constraints **by
name**. A bare `IntegrityError` cannot tell the constraint under test from the
several ways of never reaching it, and Postgres evaluates NOT NULL and
uniqueness first. Those tests write with `update()` rather than `create()`,
because since #56 the row already exists when they start and a `create()` would
be refused by the `OneToOne` before any check constraint was consulted. One of
them is an inversion pinned on purpose: the row with neither a file nor a
reason, which the old constraint's headline case called "a job that reported
nothing", is now what a release writes for every card it freezes.

`results/tests/test_renders.py` covers the way in and the way out: that a
release marks every card in the school that released and no other, that no
released card anywhere is left without a marker, that nothing is published
before the release commits and the message names the schema and one card, that a
broker refusing connections leaves the release standing and the markers
`PENDING` with a line per card in the log, that a `BUILT` or `FAILED` card is
never re-queued, that two callers reading the same stale row enqueue once, and
that the route serves bytes, 202s with a state, and refuses exactly as the JSON
route does. Two schools throughout, because a publish naming the wrong school
still satisfies a count of one.
