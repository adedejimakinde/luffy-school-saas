Task 7. WeasyPrint renders `card_api.card_payload()` through a Django template.

**Measured, as asked: 45 cards in 3.27–3.36s — 73–75 ms/card, 9.8 KiB/card, 442 KiB for the class.** Two runs. The bar was 90 seconds.

## Built from the family payload, never from the row

`position`, `roster_size`, `subject_position`, task 9's term-absence reasons and the promotion *suggestion* are absent from `ReportCardOut`, so the template cannot leak one by forgetting. A renderer handed the `ReleasedCard` row would have all five in scope with nothing but care between them and the paper — the arrangement issue #21 exists to refuse.

`card_payload()` was therefore **extracted** from the view rather than copied: two assemblies of "what a card says" is two places for a slot to appear, and they drift the first time one is edited. The tests assert both halves — that the numbers are absent from the rendered HTML, and that the object the template is given has no attribute to print them from.

## The columns are the union, not the first subject's

An `Assessment` belongs to a subject, so two subjects in one term need not share one. A header taken from the first would label Mathematics' columns and print English's marks under them. `_columns()` takes the ordered union, `_rows()` aligns every line to it.

The union is keyed on **`(name, max_score)`**, not on the display name — `max_score` is per `(term, subject, name)`, so Mathematics' "Exam" out of 120 and English's "Exam" out of 100 are two different assessments. Collapsed into one column headed "Exam", two equal marks print as equal performance and are not. The header carries the maximum and the subject total prints its denominator, for the same reason.

Print order is the frozen order, which is **#42** and this is the surface where a parent sees it. It is *not* alphabetical — the module docstring and `docs/report-card-pdf.md` both said it was until the review, and `cards._assessments_for()` says the opposite in as many words: it orders by `(subject name, id)` precisely *because* `Assessment.Meta.ordering` ends in `name`. Whoever fixes #42 would have started from a false premise.

## Three absences a careless page prints identically

| on the page | means |
| --- | --- |
| `·` in a cell | this subject has no such assessment at all |
| `—` in a cell | the child was not marked in it |
| `0 of 60 days` | present on none of the days the school was open |

The attendance cell tested truthiness and filtered with `default`, so the third printed as the second — a parent told nobody kept a register for a child who was never there. `is not None` and `default_if_none` now, with a control. Nought versus null is a mistake this codebase has made before, in the session averaging.

## One job per card, reversing what `docs/cards.md` expected

That file said a release renders "forty-five of these in one Celery job", written before there was a job. `acks_late` with `task_reject_on_worker_lost` hands a killed worker's message to another worker, so a per-class job would re-render forty-four finished cards to reach the one that was lost; and `visibility_timeout` is 300 seconds, so a per-class job risks redelivery *alongside itself*. Per card, redelivery costs one render and the timeout is never close. `docs/cards.md` corrected rather than left to disagree.

## The failure handler is the first real user of `TenantTask`'s wrapping

Celery's tracer calls `on_failure` outside the `tenant_context` block `__call__` opens, so before that wrapping landed this write went to `public` — a `ProgrammingError` naming a missing relation, raised from the failure handler, on top of the error somebody actually needed. It swallows its own exceptions for the same reason, and a test proves the task still fails with the render's error rather than the recorder's.

## `ReleasedCardPdf` is deliberately not append-only

The one table in `results` that is not. It holds a *rendering* of a card whose every number already refuses to move, so a re-render can change a layout and cannot change a figure; making it append-only would only mean a typo in the stylesheet could never be corrected. Its bytes live in a Postgres column because this platform configures no object storage and no `MEDIA_ROOT` — which fits a school and does not fit a thousand of them, and is the row to move first when object storage arrives.

## Tests

**32 in `test_pdf`, plus task 8's `NoIndexIsBuiltTwiceTests` — 34 together, OK, exit 0, under `--parallel 4` as CI runs it.** Then 71 more (`test_revision`, `test_card_api`) for the two classes the rebase conflict touched, OK, exit 0.

The job half had none before this branch was reviewed against itself:

- the file lands in the school named by the **message**, not the schema the connection was left on — asserted on the child's name, because per-schema sequences give both schools' cards id 1;
- a second run replaces the row rather than adding one, which `acks_late` requires;
- a render that dies leaves a **reason**, in the school that failed;
- a failure handler that itself dies does not replace the real error with its own;
- both check constraints, asserted **by name**, because a bare `IntegrityError` cannot tell the constraint under test from the several ways of never reaching it;
- every name reaches the template as text, not markup — `<script>Ada</script>` renders `&lt;script&gt;`.

## Found and not fixed

- **#56** (`must-fix-before-pilot`) — nothing enqueues the job and no route serves the file. The part that matters: a release that never enqueued is **indistinguishable** from one not yet released, because the absence of a row is both the normal state before release and the failure state after it. A failed render writes a reason; a render never attempted writes nothing.
- **#58** — `connected_to()` always lands back on `public`, so it does not nest, and a lazy `ReleasedCard` rendered outside its context dies on a missing relation three frames away. Three tests here hit it. Worked around locally; the helper is imported across the repo and is left for its own PR.
- **#42** — assessment print order is frozen and this is the surface where a parent sees it. The claim that it is *alphabetical* was wrong and is corrected here; the issue is unchanged, its premise is not.

## The review round, and then the rebase onto task 8

**Six findings from `/code-review high`, all confirmed against the code before being acted on** — commit 2. The one worth naming here: `card.is_revised` was on no schema, so Django resolved it to the invalid-variable default and the "Revised" badge could **never print**. Invisible until a second version exists, at which point the reprinted card is indistinguishable from the one already in a parent's hand — the single thing the badge exists to prevent. Also: the assessment column key above; the false alphabetical claim; attendance gated on `days_open` alone, so `days_present=52, days_open=None` printed a bare dash; `a_card_pdf_knows_its_own_size` checking only that `byte_size` was *set*, not that it was *true*, now compared against `Length("content")` with the `IS NOT NULL` kept beside it because a null CHECK counts as satisfied; and an `or "unknown error"` that could never fire.

**Then task 8 merged first, and commit 3 is what that costs** — both halves the migration docstring predicted:

- `0019_the_rendered_card` is now **`0021_the_rendered_card`, depending on `0020_no_index_is_built_twice`**. Renamed, not merged — a merge migration would leave two files claiming one number in every clone that had already fetched them. Nothing was applied anywhere under the old number. `makemigrations --check --dry-run`: no changes; the graph resolves linearly 0018 → 0021.
- `results/models.py` conflicted only because both branches appended a class to it. `CardRevision` and `ReleasedCardPdf` are unrelated tables that landed on the same line; both kept unchanged.
- **The badge reads `card.is_revised` again, and this time the field exists.** `version > 1` was the right fix against the old base and the wrong one against this base: task 8 added `ReleasedCard.is_revised` and put it on `ReportCardOut`, calling it "the only source of that word". The comment left beside that line became false the moment task 8 landed — the same false-premise trap the review commit was written to close. `html_at_version()` now moves `version` and `is_revised` together, as `card_payload()` emits them; a test that overrode only `version` would have gone quietly green against a page that never printed.

Noted on **#56** rather than fixed here: `cards.cards_on()` has no caller anywhere, and its docstring says "task 7's PDF job walks a whole class" — it does not, it renders one card per job. The walk is the missing enqueuer, and whoever writes it should not inherit the premise that a batch *reader* implies a batch *job*.

