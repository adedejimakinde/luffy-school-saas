# Printing a class's report cards

One press of **Print report cards** on the results page makes one PDF for one
class and one term: every child's card, or only the children ticked, each
starting on a new A4 page, in the school's template (Standard or Ogun State).
Each page is drawn by the same renderer as a single card (`results/pdf.py`),
so it looks exactly like the card a family downloads. Code:
`results/class_print.py`, `results/print_api.py`, `build_class_cards` in
`results/tasks.py`, `ClassCardPrint` in `results/models.py` (migration
`0037`), `Kind.CLASS_CARDS` in `files/kinds.py`, and the button in
`static/results/`. Tests: `results/tests/test_class_print.py` and
`tests/js/chain_print_cards.test.js`.

## Released, or a preview

| the class is | each card is | every page |
| --- | --- | --- |
| released | the family's stored file (`ReleasedCardPdf.content`, never the health copy), or rendered from the frozen card if its file is not made yet | as released |
| not released | frozen exactly as a release would freeze it, inside a transaction that is then rolled back | stamped **PREVIEW, NOT RELEASED** |

A preview keeps nothing: no card, no section, no file marker, nothing queued.
The stamp is drawn into each page's own content (three diagonal lines, red, a
third opaque), not added as an annotation or a layer a viewer could hide. Its
words are text in a standard PDF font, so the tests read them from every page.
The filename and the PDF's title also say "preview, not released".

A paper not marked prints as it does on the single card, `-`, never `0`.

## Who

| who | may print |
| --- | --- |
| principal, vice principal (academic), administrator | any class |
| class teacher | their own class, for the term they are its class teacher |
| a subject teacher, bursar, parent, student, anybody else | nothing |

`class_print.may_print()` asks this of `roles_at(school)`, this school's roles
only. It is asked when a job is started, on every status read, and before the
file is sent. The chain row's `may_print_cards` only decides whether to draw
the button.

The class routes answer 403 to somebody with no standing (asked before either
lookup, so that the answer does not say whether a class exists). The job routes
answer a flat 404 to anybody but the person who asked, and to that person once
they can no longer print that class, for example a teacher taken off it.

## Off the request, a card at a time

`POST /api/results/print-cards/<class>/<term>/` writes a `ClassCardPrint` row
and, once that commits, queues `build_class_cards`. The page then asks
`GET /api/results/print-jobs/<job>/` every two seconds, shows "n of N" and a
progress bar, and offers the download when it is ready.

The worker renders one card, writes it to disk, and only then starts the next.
At the end it joins the parts with pikepdf (one bookmark per child) and stamps
a preview. Memory is a card's layout at a time plus the join, never a whole
class of layouts.

**One job per class, not per card** (against `render_card_pdf`), because the
thing kept is one file. The queue's redelivery is handled by a heartbeat
instead: the job writes progress after every card, a second worker handed the
same message after the broker's five-minute visibility timeout finds the
heartbeat fresh and does nothing (`class_print.claim()`, one conditional
`UPDATE`), and a job whose heartbeat has been stale for two minutes is taken
over, by the redelivery or by the next status read (`nudge()`). A job whose
message never reached the broker is asked for again by the status read after a
minute. Pressing the button twice while a job is being made returns that job.

Measured locally (2 CPUs, Postgres 16): a class of 25 took **3.8 s** as a
preview and **4.1 s** released (25 pages, about 340 KiB);
`TwentyFiveCardsTests` prints the numbers on every run.

## Kept for a day, for one person

The file is kept by the upload service (`files.service.keep_made()`): built in
`<FILES_ROOT>/.building/<schema>/`, renamed into the school's own directory,
hashed in chunks, and written down as a private `StoredFile` whose
`uploaded_by_id` is the person who asked. The kind has no `readers`, so the
generic `/files/` route never sends it. `GET /api/results/print-jobs/<job>/pdf/`
sends it through `files.views.send()` (X-Accel-Redirect in production) after
asking who the caller is.

It is refused from the moment it is 24 hours old (410, with a sentence), and
the hourly `check_storage` (`files.service.sweep()`) removes the row and the
bytes. The sweep also removes build directories a killed job left behind. The
nightly media backup (`deploy/media-backup.sh`) leaves both out, so a file kept
for a day is not kept for a year in a snapshot instead.

## The log

The `ClassCardPrint` row is the print log, and it is kept after its file goes:
who asked (id, name and roles, copied), which class and term (names copied),
whether it was a preview or the released cards, how many cards, and when. Each
print also writes an `INFO` line to the school's log.

## Two schools

Every row and file is in the school's own schema and directory, and a job id is
looked up only there. The test that holds the authority half is
`test_a_principal_elsewhere_who_is_a_parent_here_cannot_print`: a principal at
Grace who is a parent at St Mary's passes the middleware on St Mary's host, so
only `may_print()` asking roles *here* stops them. With that line changed to
ask roles at every school, the test fails (202 instead of 403).
