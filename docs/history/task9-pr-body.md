# Task 9: the three-term view and promotion status

Branch `three-term-view`, commits `b1409a3` and `b1e093b`, off `main` at
`a1884a1`. **This PR has not been opened yet** — no `gh` in the devcontainer.

Closes task 9. The full reasoning is in the commit message; this is the summary.

## What lands

| | |
| --- | --- |
| `SessionSettings` | per-school averaging mode, weights, pass mark. Weights null in EQUAL mode; sum to 100 in WEIGHTED, enforced by check constraint |
| `TermAbsence` | why a term contributed nothing: `NOT_ENROLLED`, `UNMARKED`, `NO_TERM` |
| `ReleasedSessionResult` | the frozen session line, written at third-term release, append-only |
| `PromotionDecision` | append-only decision log; latest row wins; no current-status column |
| `results/sessions.py` | configuration, the three-term read, the freeze, the promotion path |
| migrations `0012`, `0013`, `0014` | schema, then the append-only triggers and the settings seed, then the review fix below |
| `docs/sessions.md` | the page |

`positions._round()` became public `round_percentage()` — one rounding authority
for every percentage in the app.

## The decisions this implements

Settled with the user before any code (see `phase-1-results-decisions` memory):

- session average school-configurable, default straight mean; weights sum to 100
- a missing term **renormalises**, never scores zero
- the weighting that produced an average is recorded
- promotion is a **computed suggestion plus a recorded decision**; the card
  prints the recorded one only; `recorded` is never auto-filled; undecided is
  the absence of a row; decisions are append-only rows
- the suggestion is **stored at decision time**, not recomputed
- the session average is frozen as an artefact at third-term release
- an absent term records **why**, and the reason is staff-only

## Verification

54 tests in `results/tests/test_sessions.py`. Two schools throughout, and the
second is used rather than built and ignored.

The two-term renormalisation is proved under both conventions with the numbers,
as the settled decision required:

    sat second and third, scoring 70 and 80
    equal      -> 50/50   -> 75.00
    20/20/60   -> 25/75   -> 77.50
    as a zero  -> 62.00, which would suggest REPEATED at a 70 pass mark

## Found in review, and fixed here (`b1e093b`)

**A third-term release failed outright when the school's weighting counted a
term at nothing.** Not a wrong number — an `IntegrityError` out of
`bulk_create()` inside the release transaction, so the principal could not
release the class at all.

`0/0/100` is a legal weighting: `_require_a_weighting()` allows it, and
`docs/sessions.md` documents it as a school counting only the third term. Take a
child on that school's third-term roster whose third term nobody marked:

    first   60.00, absence ''        second  70.00, absence ''
    third   null,  absence 'unmarked'
    session average  null — no proportion of nothing is a hundred

The two terms sat carry averages and so cannot claim an absence reason, and
`the_first_term_is_present_or_explained` demands a weight beside an average —
while `a_session_average_has_a_term_behind_it` demanded that a null average
carry no weights at all. There was no row the code could write.

The live read was right and tested; the freeze was the path nobody walked. The
existing zero-weight test used a child who left early, who is never on a
third-term roster and so never reaches `freeze_for_release()`.

The fix: a term the school counts for nothing was sat, marked, and **weighted
nought** — a different fact from "there was no term here", which is what a null
weight beside an absence reason says. `_weigh()` records the `0.00`, and
migration `0014` asks whether a term carried weight *above zero* rather than
whether any weight is recorded. The schema already accepted a `0.00` weight
beside an average whenever another term carried weight (`0/40/60` always froze
`first_weight_used = 0.00`); the all-zero case was the one path spelling the
same fact a second way.

Both directions of the constraint are kept, and the `IS NOT NULL` tests in it
are load-bearing: `weight_used > 0` is NULL for a null column and a CHECK that
evaluates to NULL **passes**, so the obvious phrasing would let through the one
row the constraint exists to refuse.

Three controls against `b1409a3`, each run:

| reverted | fails on |
| --- | --- |
| `sessions.py` | `the_first_term_is_present_or_explained` |
| `models.py` + `0014` | `a_session_average_has_a_term_behind_it` |
| the `IS NOT NULL` tests | nothing — the average with no weighting behind it is accepted |

## Found in self-review

A child can collect **two** frozen session lines: release JSS 1A, move the child
to JSS 3B, release JSS 3B. "A child is on exactly one third-term roster" is true
at any instant and false over time. Both rows stand; the card is the first, on
the same rule `0010`, `0011` and issue #27 turn on.

The test for it was worthless twice before it worked, and both are written down
in the commit message: the behavioural pair passes with the ordering removed
(Postgres returns a fresh pair in insertion order), and the captured-SQL test
that replaced it passed against an unordered query because `QuerySet.first()`
adds an ORDER BY on the pk and `created_at` is in every SELECT list. It asserts
on the ORDER BY clause alone now and the control fails as it should.

## Deliberately not in this PR

**The read API.** `results/api.py` has one broadsheet route; the session view
and the promotion sheet are not on it. That PR is where the staff-only rules get
enforced at the serializer — the absence reasons and the promotion suggestion,
the same way position already is.
