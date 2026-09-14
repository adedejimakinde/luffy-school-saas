---
name: phase-1-results-decisions
description: "Settled decisions for Phase 1 (results and report cards) on luffy-school-saas — ranking, revision authority, attendance, infra"
metadata: 
  node_type: memory
  type: project
  originSessionId: aef5da7e-0170-4c81-b5f2-338b9abb8f0e
  modified: 2026-08-23T17:02:26.627Z
---

Decisions the user settled on 2026-08-22 for Phase 1 (results and report cards), before the code implementing them existed. Each lands in its own task's docs and PR.

- **Position (task 2) is STAFF-ONLY and must never reach a parent or student.** Nigerian secondary schools do not print position on report cards; parents and students see cumulative average only. Still compute and freeze position in the snapshot (schools use it internally), but it must not appear on the report card (web or PDF) **or in any parent-/student-facing API response, including the unauthenticated result-checker payload**. Exclude it **at the serializer, not just the template** — omitting it from the card while leaving it in the JSON is the same leak. Visible to teachers, HODs, principals, school admins. Pin with a test asserting a parent-scoped response and an unauthenticated result-checker response contain **no position field at all**.
- **Ties (task 2): dense ranking.** Two students tied at 3rd means the next is **4th, not 5th** — a tie does not consume the following position. Standard Nigerian practice. **Hardcode it for now**, but assume it may become a per-school setting eventually; note that in docs.
- **The card's average (task 3) is the student's OWN overall average across their subjects — not a class average.** Freeze that.
- **Class-wide average: compute on demand, do NOT store it in the snapshot.** It is staff-only, like position. Rationale the user accepted: a stored copy is a fact about 45 other children that later revisions can contradict, so a released card would carry a number disagreeing with the rows it summarises. Position *is* frozen, because it depends on everyone else's scores at the moment of release and cannot be recomputed later without changing.
- **Revision authority (task 8): the principal only.** Plus platform staff via a separate, explicitly-audited path using the `requested_by == answered_by` pattern from the transfer handshake. A teacher or HOD must **not** be able to change a result a parent already holds — release is the principal's act, so revision is too. A revision records who triggered it and when; both versions stay.
- **Attendance in the snapshot (task 3): nullable until Phase 2.** Render **blank** on the card rather than faking a number or blocking release on it.
- **Infra (before task 7): Celery, Redis and WeasyPrint get their own PR** adding them to `requirements.txt` and `docker-compose.yml`. They are absent today.

Settled 2026-08-23, for task 9 (three-term view and promotion status):

- **Session average is school-configurable, defaulting to a straight mean (equal weights).** Both conventions — equal, and weighted 20/20/60 — are real in Nigerian schools, and the number decides promotions, so it must not be hardcoded. **Weights must sum to 100; a config that does not is rejected.**
- **A session missing a term (mid-session transfer, PR #7) RENORMALISES the remaining weights to sum to 100.** An absent term is *not* treated as a zero — a student must not be penalised for a term they were not enrolled to sit. Prove with a test covering the two-term case under **both** equal and 20/20/60 weights, showing the numbers.
- **A session average records the weighting that produced it.** A school changing its weights next session must not alter a past session's average — the same freezing rule as task 4's traits and task 5's comments.

Settled 2026-08-26, for task 9's **promotion status** (the half the earlier
session-average decisions did not cover):

- **A computed suggestion AND a recorded decision, kept apart.** The school
  configures a pass mark; the system computes `suggested`; a principal records
  `recorded`, and `recorded` is what prints.
- **The card prints `recorded` only.** Never `suggested`, never the gap between
  them. Staff-only, the same rule as position — exclude it **at the serializer**,
  not just the template.
- **`recorded` is never auto-filled from `suggested`.** An un-decided student is
  un-decided: a distinct state, not a defaulted PROMOTED. A principal who
  reviews nothing must not silently promote a school.
- **Log-only, append-only.** Each decision is a row carrying its own
  `decided_by`/`decided_at`; the latest row wins; **no denormalised
  current-status column**. No row at all means undecided. A principal changing a
  decision keeps both rows.
- **`suggested` is stored as it stood at decision time**, together with the
  session average and the weights that produced it — not recomputed on read.
  The gap between suggested and recorded is *evidence of an override*, and a
  recomputed suggestion makes the same row read as agreement or override
  depending on when it is asked. A weights change would otherwise invent
  overrides no principal performed. The "a mark was wrong" counter-case belongs
  to task 8: a revision makes a new version, so it makes a new decision row.

- **The session average is frozen as an artefact at third-term release, inside
  the release transaction** — like `ReleasedTraitRating`. Computing it live
  loses to the revision case: a first-term revision would silently change a
  session average already printed on a card. The promotion decision row cannot
  be the source, because a school may release third-term cards before promotions
  are decided.

- **A term with no average renormalises whatever the reason** — "not enrolled"
  and "enrolled but unmarked" get identical arithmetic. Zero is refused because
  it invents a failing grade the child never earned and would drive a wrong
  REPEAT suggestion.
- **But the artefact records *why* a term is absent, distinctly.** The two
  causes mean different things: "enrolled but unmarked" is a school that failed
  to enter marks, and staff need to see a data-entry gap rather than a transfer.
  Store the cause, not just the `None`. **Never print the reason on a parent
  card** — staff view only.

Settled 2026-08-24, for [issue #27](https://github.com/adedejimakinde/luffy-school-saas/issues/27)
(a mark can still be changed after submit/check/approve/release):

- **Its own PR, after task 5 and before task 9. Not folded into task 3.** A frozen
  snapshot and a write-guard on live tables are different mechanisms, and bundling them
  means task 3's review cannot tell which one is actually holding.
- **Dependency direction: a late import inside the function**, the precedent
  `results.services.release()` already sets for `ratings`. Not a new `results/chain.py`.
- **Lock strength: `FOR UPDATE`.** Do not drop to raw SQL for `FOR SHARE` on a predicted
  contention problem; if mark entry is slow in the pilot there will be a real number.
- **Order within the PR: the trigger half first, then the service half.** The trigger
  alone closes the path that reaches parents.

Earlier in the same phase the user chose: add `ClassGroup` + `Enrolment` (built as `ClassPlacement`), a per-term attendance summary record, and Redis as the Celery broker.

**Why:** these are product/domain calls, not implementation details, and several are unguessable from the code.

**How to apply:** follow them without re-asking. See [[luffy-phase-1-workflow]] for the merge discipline they run under.

Settled 2026-08-29, signing off the **task 3 snapshot design**:

- **`class_average` is NOT frozen — computed on demand.** The user reversed
  their own newer instruction to freeze it, and the reasoning must go in the
  model docstring so it is not re-litigated: *position is a statement about THIS
  child and the roadmap locks it at release; `class_average` is a statistic
  about the other 44.* Freeze it and one child's revision leaves 44 unrevised
  cards asserting a number that disagrees with the revised one — the
  school's-screen-vs-card disagreement this whole phase exists to kill. Both are
  staff-only and neither prints on a parent card, so nothing about
  reproducibility is lost. **Position frozen, class average computed.**
- **`GradeBand` is its own small PR immediately BEFORE task 3**, not inside it.
  It is school config, the same class as trait lists, and the snapshot PR should
  not also carry a config model with its own coverage constraints. Per-school;
  bands neither overlap nor leave gaps across 0–100; explicit ordering. Seed a
  documented default and flag in the PR body that the user will confirm the band
  *values* — seed data is cheap to change, schema is not. **Do not block on them
  for the numbers.**
- **Keep the rows; do not collapse the assessment breakdown to JSON.** A card is
  exactly these rows in this order. Read path is prefetch-by-card-id from the
  start.
- Approved as proposed: retarget all three shipped frozen tables with a non-null
  `card` FK plus backfill (one answer to "did a card go home", not four — four
  is the condition that produced the PR #35 bug); "the card" is the earliest
  `(created_at, id)` among version-1 rows, then the highest version, ordered
  explicitly and never by `Meta.ordering`; `PromotionDecision` read live;
  `cards.freeze_for_release()` runs first and the ordering comment in
  `results/services.release()` is updated; triggers on UPDATE/DELETE only.
- **The unconditional-write test is the one guarantee no trigger can hold** — it
  needs a control run that shows it failing.
