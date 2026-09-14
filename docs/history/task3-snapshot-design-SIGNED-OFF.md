## CI

Still running. The `tests` workflow on the merge commit is at ~8 minutes and `in_progress`; the parallel PR run is at ~11. Nothing has failed — there's just no result yet. I'm watching it in the background and will report the conclusion when it lands rather than infer one. Local evidence stands in the meantime: `main`'s tree is byte-identical to `b1e093b`, which ran 911 tests green.

---

## 1. The premise trap

The rule is *a guard on a released artefact keys off the artefact, not the child's current placement*. The trap sits one level above the rule, in what you survey before applying it:

**"The marks are not frozen" and "no artefact records the release" are different claims, and the first does not imply the second.**

Issue #27's first draft needed to answer *has a card gone home for this child?* in order to refuse a mark write. It reasoned: task 3 hasn't shipped → nothing freezes the marks → there is no released artefact to key on → therefore key on `ClassPlacement`, and defer the moved-child case to #34.

Every step after the second is sound. The second is false. `results_releasedtraitrating` already answered exactly that question — one row per child per visible trait, written inside the release transaction — and `0011` was keying on it one table over. Whether the *marks* were frozen has no bearing on whether the *release* is knowable.

The cost of the wrong premise: the guard read the child's current placement. Release JSS 1A, move the child to JSS 3B whose sheet is an untouched draft, and the write was permitted on a card already in a parent's hand. The child who stayed put was protected; the child who moved was not. Same term, same guard, different answers because they sat in different rooms.

Two things make it a *premise* trap rather than a bug:

- **The failure was in the survey, not the logic.** "If no artefact exists, fall back to placement" is correct reasoning. Nobody checked what release actually writes — a claim about the system that arrived disguised as a claim about the current task.
- **It cannot be recovered afterwards.** `ClassPlacement` holds one group per child per term, so a mid-term move *rewrites* the row. The record of where the child sat at release isn't superseded, it's destroyed. A guard that keys on it isn't reading a stale answer; it's reading a different question.

What remained after the fix was a **per-school** gap rather than a per-child one: a school with the conduct section switched off freezes nothing for anybody, so nothing records its releases at all. That is the hole your unconditional marker closes.

**The form it will take in task 3**, because it recurs rather than being retired: once the snapshot exists, the tempting premise becomes *"a snapshot row exists, therefore a card went home."* That is false for every child whose content is empty — no marks, no ratings, nothing decided. If any guard keys on the presence of *content*, the trap has simply moved. This is the design consequence, and it drives the shape below: the marker is the artefact, content is not, and every guard keys on the marker.

---

## 2. The snapshot's shape

**One parent row per child per release, and everything the card prints hangs off it.**

That single choice pays for itself three times: it makes the marker unconditional by construction, it collapses ratings' two checks into one, and it makes task 8 nearly free — a revision is a new parent row plus new children, with no change to any content table.

### `ReleasedCard` — the artefact

One row per `(sheet, student_membership_id, version)`. Written for **every child on the roster at release, unconditionally** — before any content is frozen, independent of enabled groups, visible traits, or whether a single mark exists.

| group | fields | why |
|---|---|---|
| identity | `sheet` FK PROTECT, `student_membership_id`, `version` (default 1) | the key; `version` here so task 8 needs no content-table migration |
| provenance, copied | `term_id`, `session`, `class_group_id`, `class_group_name`, `school_name`, `student_name` | placement is rewritten by a move; a school renames itself; a child's name gets corrected. All reach a released card through a join unless copied |
| the child's own numbers | `total_scored`, `total_available`, `own_average` | the card's average is the child's own across their subjects |
| staff-only | `position`, `class_average`, `roster_size` | stored, excluded at the serializer |
| attendance | `days_present`, `days_absent`, `days_open` — all nullable | blank on the card until Phase 2 |
| release | `released_at`, `released_by_id`, `created_at` | |

`student_name` and `school_name` are the two most likely to be missed, and both are shared-schema mutable rows reachable from a released card.

### Content tables

| table | grain | carries |
|---|---|---|
| `ReleasedSubjectResult` | one per `(card, subject)` | `subject` FK + copied `subject_name`, `subject_code`, `position`; `total_scored`, `total_available`, `percentage` (null = unmarked, prints blank); `grade_letter`, `grade_remark`; staff-only `subject_position`, `subject_class_average` |
| `ReleasedAssessmentScore` | one per `(card, subject, assessment)` | `assessment` FK + copied `assessment_name`, `max_score`, `position`; `score` (null = unmarked) — the CA/exam breakdown columns |
| `ReleasedTraitRating`, `ReleasedComment`, `ReleasedSessionResult` | already shipped | gain a `card` FK |

A row is written for every subject and every assessment **including the unmarked ones**, on `ReleasedTraitRating`'s existing argument: the frozen thing is the *line*, and "this column existed and was blank" is something the card has to go on saying.

### Retargeting the three shipped tables

I'd add a non-null `card` FK to each and backfill. Their existing key is `(sheet, student_membership_id)` — exactly `ReleasedCard`'s unique key — so the backfill is: insert a card for every distinct pair across the three tables, then set the FK. Cards invented for historical releases are correct, not fabricated: a card did go home.

I'm recommending rather than assuming, because it is three shipped tables, three triggers and a data migration inside task 3. The cheaper alternative is to leave them keyed as they are and let `ReleasedCard` stand alongside — but then "did a card go home" has four answers instead of one, which is the condition that produced the bug in part 1.

### What is deliberately *not* frozen

**The promotion decision.** It is read live from `PromotionDecision`, which is append-only and already freezes its own inputs at decision time. Two reasons: a decision usually does not exist at release, and the objection that drives freezing everything else — later config edits reaching backwards — cannot apply to a table nothing edits.

### Where immutability is enforced

| layer | mechanism | catches |
|---|---|---|
| model | `save()` refuses when `pk is not None and not _state.adding`; `delete()` always refuses | the developer, with a sentence |
| database | one trigger per table, on `UPDATE` and `DELETE`, **not** `INSERT` | `psql`, imports, bulk `.update()` — none of which touch a model method |
| database | check constraints for internal agreement: a null percentage carries no grade letter; percentages within 0–100; `scored <= available`; a score within its `max_score` | rows the code could never write but an import can |
| database | unique per grain: `(sheet, student, version)`, `(card, subject)`, `(card, assessment)` | a second opinion about one line |

Same pattern as `0007`/`0010`/`0014`. Note the trigger must not fire on `INSERT` — `0013` gets this right and the reason is that these tables are written once by the code that owns them.

**The unconditional-ness is not a constraint — it is a code property**, so it needs a test that a school with every group disabled and no marks still gets one card row per child, plus a control that removes the unconditional write and shows the test failing. That is the one guarantee no trigger can hold.

### Ordering inside the release transaction

`cards.freeze_for_release()` runs **first**, before ratings, comments and sessions, because it writes the parent row the others hang off. This inverts the current "in the order they print" comment in `results/services.release()`, which will need to say so.

### Which row is "the card"

Two ways there can be more than one, and they compose:

- **Two sheets, same term** — release JSS 1A, move the child, release JSS 3B. Task 9 settled this: the **earliest** wins.
- **Two versions, same sheet** — task 8. The **highest version** wins.

So: earliest `(created_at, id)` among version-1 rows for the term, then the highest version of that sheet. Ordered explicitly, never left to `Meta.ordering`, and the tie broken on `id` — the exact shape that produced two tests passing against broken code in task 9.

---

## Three things you should see before I build

1. **`class_average` contradicts a settled decision.** Your list says denormalise it; the 2026-08-22 decision says *"compute on demand, do NOT store it in the snapshot"*, because a stored copy is a fact about 45 other children that a later revision can contradict. I'm taking your newer instruction — and I think it's the better call, because that objection applies identically to `position`, which you chose to freeze. Freezing both is at least consistent. Flagging it so the reversal is deliberate.

2. **No grading scale exists.** Nothing in the codebase maps a percentage to a letter. `grade_letter`/`grade_remark` need a per-school `GradeBand` model (bounds, letter, remark, order, with constraints that bands neither overlap nor leave gaps across 0–100) built inside task 3. Not on your settled list, and it's real work.

3. **Row volume.** A 45-child class with 10 subjects and 3 assessments each writes ~1,350 assessment rows + 450 subject rows + ~500 rating rows ≈ 2,300 rows per release, all in one transaction. Postgres won't care, but it makes task 7's 45-card PDF run depend on reading a card in a bounded number of queries — so the read path is prefetch-by-card-id from the start, not a per-line lookup. The alternative, collapsing the assessment breakdown into JSON on the subject row, saves the rows and costs the property `ReleasedTraitRating` explicitly bought: that a card is exactly "these rows, in this order". I'd keep the rows.

Waiting on your sign-off. Nothing written yet, and I'll report the CI conclusion as soon as it lands.
