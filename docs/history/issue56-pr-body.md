Closes #56.

Task 7 built a renderer, a job and a table to keep the file in, and **nothing
called any of them**. This is the way in and the way out — and, in between, the
part the issue said it would not close without: a released card that owes a file
now says so, in a row, from the moment it is released.

## The hole, which was never the failed render

A render that *failed* was always visible: `RenderACard.on_failure` writes the
reason into the school's own table. A render **nobody ever asked for** was not.
A Redis that was down, a worker that never came back, a message lost between the
two, and `ReleasedCardPdf` would have no row at all — which is also the ordinary
state of a card before it is released. The absence could not be interrogated,
nothing swept, nothing retried, and the first person to find out was a parent
who could not open their child's report card weeks later.

So `results/renders.py`'s `mark_and_enqueue()` writes a `PENDING` row for every
card **inside the transaction that freezes it**, and asks for the renders only
after that transaction commits.

`PdfState` is three states and deliberately not four. A `QUEUED` written by the
enqueuer and cleared by the worker would say whether a job is in flight — and a
worker that died between the two would strand that card in it for ever, because
the recovery path for a lost job is exactly "a download of a `PENDING` card asks
again" and a fourth state switches that path off for the cards that need it
most. The cost is that `PENDING` cannot tell "queued a second ago" from "queued
never"; `last_enqueued_at` and the debounce it drives are what stop that costing
anything.

## The way in

`services.release()` marks the class; `revision.revise()` marks the one card it
writes. The second is not symmetry for its own sake — it is the only path by
which a child placed into a term after it was released (#31) gets a card at all,
so marking at release alone would leave hers the one card on the platform with
no marker and no render.

Both call the same helper, and it is `transaction.on_commit` rather than a bare
`.delay()` for a reason that is a bug and not a style: a worker is another
process on another connection, so a message published before the release commits
can be picked up while READ COMMITTED still shows that worker no card. It would
write a `FAILED` row saying the card does not exist, permanently, for a card that
is fine three milliseconds later.

And `on_commit` callbacks run *after* the commit, so an exception in one reaches
the caller with the release already durable — a 500 for a principal whose cards
have gone home. Every publish is caught per card and logged; `retry=False` keeps
a dead broker from holding the request open through three Celery retries per
card, forty-five times over, to arrive at the same place. Swallowing that
exception is only defensible because the `PENDING` row survives it: the work is
recorded as owed rather than lost, and the next download asks again.

## The way out

`GET /api/results/cards/{student_membership_id}/{term_id}/pdf/` asks the
identical authority question as the JSON route beside it — the same four calls in
the same order — because a PDF of a card you may read is not a second permission,
and two answers to one question is one answer nobody tested. Every refusal is
that route's flat 404, including "no card for this term", so four characters on
the end of a URL cannot turn it into an existence oracle.

- **Built** → the bytes, `application/pdf`, named for the child, the term and the
  session, carrying the version when there is more than one.
- **Pending** → 202, a state and a sentence saying come back — and the card is
  asked for again, which is the recovery for a job that never reached a worker,
  driven by the person who actually wants the file rather than by a sweep nobody
  wrote.
- **Failed** → 202, a sentence saying ask the school, and **no** re-queue: what a
  failed render needs is a person reading the reason, not a retry loop driven by
  a parent hitting reload against a template that cannot render.

The exception text is not in the body. It is a Python class and message written
for whoever debugs the render, and a parent reading `TemplateSyntaxError` learns
nothing they can act on — absent for staff too, because this module does not vary
a payload by who is asking.

Nothing renders in the request. WeasyPrint takes a few hundred milliseconds a
card and results week is every parent of a class arriving at once, which is what
moving the render to a worker was for.

## The debounce, which is a conditional UPDATE and not an `if`

The download enqueues on `PENDING`, and `PENDING` is also the state of every card
in the school for the minute after a release. Without a window, results week
turns one release into a job per refresh per card. `RE_ENQUEUE_AFTER` is a
minute — longer than a render, short enough that a parent reloading is what
recovers a lost job.

Two requests arriving together would both read `PENDING` and both find the window
open. The claim is therefore made by the `UPDATE` itself: Postgres re-evaluates a
`WHERE` clause against the newer row version when it unblocks, so exactly one of
two concurrent updates matches and the other reports zero rows. `TwoDownloadsAtOnceTests`
proves that with two real threads on two real connections, because a `TestCase`
is one transaction and two "connections" inside it are one.

## The migration, and the answer to the question the issue left open

`0022` drops the old constraint, adds `state` and `last_enqueued_at`, names the
state of every row that already exists (`BUILT` where there are bytes, `FAILED`
where there is a reason — the dropped constraint permitted no third shape), and
then **backfills a `PENDING` row for every released card that has none**, one
`INSERT … SELECT` per schema. Without that backfill the invariant would hold only
on databases written from today, and the download route would carry a "no row"
branch for ever. Reversing it deletes those markers, because the old constraint
refuses a row with neither a file nor a reason — which is exactly what a marker
is.

The check constraint is now per state and refuses the three lies the states can
tell: `BUILT` with no bytes, `FAILED` with no reason, `PENDING` already carrying
either.

## What this changes about existing tests

`test_a_row_that_is_neither_a_file_nor_a_reason_is_refused` **inverts**. The row
it refused by name — *"a job that reported nothing at all"* — is now what a
release writes for every card it freezes. It is replaced by
`test_the_row_a_release_writes_is_the_one_that_used_to_be_refused`, which pins
the inversion so it cannot be undone by accident, and by four tests for the lies
the new constraint refuses instead.

Those constraint tests also write with `update()` where they used to `create()`:
the row exists before the test starts now, so a `create()` would be refused by
the `OneToOne` on `card` before any check constraint was consulted — a test that
still fails, for a reason it does not name.

Two tenancy assertions in `test_pdf.py` moved from "no row in the other school"
to "no row a *job* wrote in the other school", for the same reason.

## A stale docstring, corrected where it was filed

`cards.cards_on()` said "task 7's PDF job walks a whole class". Task 7 renders
one card per job — `acks_late` and a 300-second `visibility_timeout` are why —
and this enqueuer does not call `cards_on()` either: it takes ids straight off
`card_by_student`, which is already one card per child, rather than prefetching
every line and cell of forty-five cards to throw them away. So the function still
has no caller, which its docstring now says, and it is kept for the
`DISTINCT ON (student_membership_id) … ORDER BY version DESC` rule that any
future batch reader needs and that is easy to get wrong.

## Tests

`results/tests/test_renders.py`, two schools throughout — a publish naming the
wrong school still satisfies a count of one:

- a release marks every card in the school that released and no other, and no
  released card anywhere is left without a marker;
- a revision owes a file of its own, version 2 beside version 1;
- nothing is published before the release commits, and the message names the
  schema and one card;
- a broker refusing connections leaves the release standing, the markers
  `PENDING`, and one line per card in the log; one card failing to publish does
  not stop the rest;
- `BUILT` and `FAILED` are never re-queued; two callers holding the same stale
  read enqueue once; asking moves the window;
- a card that lost its marker gets one and a `WARNING` naming it, and the control
  that a card which has one keeps it — including its file;
- the route serves bytes with the right name, 202s with the right state, hides
  the exception text from staff and parent alike, refuses exactly as the JSON
  route does, and serves Grace's card in Grace.
