Found while building task 7 (`results/pdf.py`, `results/tasks.py`, `ReleasedCardPdf`).

Task 7 as specified is "the PDF; measure 45 cards, report the seconds" — a renderer, a background job, and a table to keep the file in. All three are built and tested. **Nothing calls any of them.**

- `services.release()` does not enqueue `render_card_pdf`, so a released class produces no files.
- `results/card_api.py` serves the card as JSON and has no route that returns the file, so even a card whose PDF exists cannot be fetched by the family it was made for.

The feature is machinery with no way in and no way out. That is deliberate for the task 7 PR — both halves are decisions with consequences that should not be made inside a rendering PR — but it means no school can use this until they land.

## The hole that matters most: there is no rebuild path

**This is the part that produces silent missing files in production, and it is why this is `must-fix-before-pilot` rather than backlog.**

Whatever enqueues the render will do it once, at release. If that enqueue does not happen — a Redis that is down, a worker that never comes back, a job lost between the two — then:

- the card is released, correct, and readable as JSON;
- `ReleasedCardPdf` has **no row at all** for it — not a row saying "failed", *no row*, because the only thing that writes a failure row is a job that actually ran;
- nothing sweeps, nothing retries, nothing reports;
- and the first person to find out is a parent who cannot open their child's report card, weeks later.

A failed render is visible: `RenderACard.on_failure` writes the reason into the school's own table. **A render that was never attempted is indistinguishable from one that has not been asked for yet.** The absence of a row is the normal state before release and the failure state after it, and nothing on the platform can tell those apart.

So whatever else is chosen below, this issue is not closed without **one** of:

- a sweep that finds released cards with no `ReleasedCardPdf` row and enqueues them (needs a "released more than N minutes ago" clause, or it races the batch it is meant to backstop);
- a management command a school's operator can run for a class or a term;
- a render-on-demand fallback on the download route, which makes the queue an optimisation rather than a dependency;
- or a row written *at release time* in a "not built yet" state, so that "no file" and "no attempt" stop being the same observation. This is the cheapest and probably the right one: it makes the gap queryable, which none of the others do on their own. It needs a third state on the `a_card_pdf_is_a_file_or_a_reason_and_not_both` constraint.

## The way in: who enqueues, and when

The obvious call site is `services.release()`, inside `freeze_the_card()`, which already holds the `card_by_student` map.

It must be `transaction.on_commit`, not a bare `.delay()`. A worker is a different process on a different connection: a job sent before the release commits can be picked up and find no card, and under READ COMMITTED it will not see one until the transaction lands. That failure is indistinguishable from a real one and would write a `ReleasedCardPdf` error row for a card that is about to be perfectly fine.

And the enqueue must not be able to fail the release. `on_commit` callbacks run *after* the commit, so an exception there — a Redis that is down — propagates to the caller after the release has already happened: the principal sees a 500 and the cards went home anyway. Catch per card and log. Which lands straight back on the paragraph above: the release stands, the files do not exist, and nothing knows.

## The way out: what a family fetches

`GET /api/results/cards/{student_membership_id}/{term_id}/pdf/` alongside the JSON route, reusing `_require_may_read()` — the authority question is already answered there, including the flat 404 that keeps the route from being an existence oracle.

The open question is what it does when there is no file yet:

- **202 and a "still being prepared" body.** Honest, and useless if the job never ran — it says "come back later" for ever.
- **Render synchronously and store it.** One card is a few hundred milliseconds, and it makes the queue an optimisation rather than a dependency — but it puts WeasyPrint in the request path, which is what moving the render to a worker was meant to avoid.
- **Enqueue on the GET and answer 202.** Self-healing and idempotent, but it makes a read queue work, and it still fails silently when the broker is the thing that is down.

Not chosen here.

## Related

`ReleasedCardPdf` keeps the bytes in a Postgres column, because this platform configures no object storage and no `MEDIA_ROOT`. That fits a school — tens of KB a card, a couple of MB a class — and does not fit a platform of a thousand schools keeping every year for ever. It is the row to move first when object storage arrives.
