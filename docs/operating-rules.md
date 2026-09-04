# Operating rules

What Phase 1 established about writing code in this repository, for whoever
touches `results` — or builds the fee ledger — next.

This is **not a changelog.** Each rule is stated as a rule, followed by the
reason it exists and the one concrete thing that taught it. The instance is
included so you can check whether the rule still applies rather than obeying it
on faith: if the code it points at has changed, the rule is due a re-read.

The rules are ordered by how expensive it is to get them wrong, worst first.
The first four are about the data. The last three are about how you know any of
it is true, and they are the ones most likely to be skipped.

---

## 1. A guard on a released artefact keys off the artefact, not current placement

> "Has a card gone home for this child?" is a question about a **row that was
> written**. It is not a question about where the child sits today.

A child moves class. She is placed into JSS 3B. Every guard that asks "is this
child's work still editable?" by looking up her *current* `ClassPlacement` now
answers about JSS 3B — and cheerfully permits a write against the JSS 1A card
that was released and printed last term. The placement moved; the artefact did
not. The artefact is what the parent is holding.

So the check is: **does a frozen row exist for this child and this term?**
`results_releasedtraitrating` answers it — one row per child per visible trait,
written by `ratings.freeze_for_release()` inside the release transaction. The
placement question, if it is asked at all, is asked *second*.

**What taught it.** `_require_this_card_has_not_gone_home()` originally keyed on
`ClassPlacement`, justified in its own commit message with "nothing freezes marks
until task 3". Two claims had been conflated: nothing freezes the *marks* — true
— but whether the release is **knowable** never depended on the marks, and
migration `0011` was already keying on the ratings table one table over. Release
JSS 1A, move the child, and the write was accepted at both the service and the
trigger. See `f2d682b`, and issues #33, #34 and #31 for the residue.

**The residue is real and is not closed.** `freeze_for_release()` returns early
when no trait group is enabled, so a school with the conduct section switched off
freezes nothing for anybody and the artefact check finds nothing to trip on.
That is a **per-school** gap, not a per-child one, and it is what issue #34 and
issue #52 are about. If you add a new released artefact, this is the first
question to ask of it: *is there a row that exists unconditionally?*

---

## 2. Content is copied at write time, never joined to

A frozen row stores the **text**, not a foreign key to wherever the text lives
now. `ReleasedCard` carries `student_name`, `school_name` and
`class_group_name`; `ReleasedSubjectResult` carries `subject_name`;
`ReleasedTraitRating` carries `trait_name`.

This looks like denormalisation and is not. The card is a **record of what was
sent**, and a school renames things: a subject is retired, a class is
restructured, a child's name is corrected. Every one of those is a legitimate
edit to live data, and not one of them may reach a page that has already gone
home. A card that joined to `Subject` would silently relabel itself years later.

Two corollaries that are easy to miss:

- **The copy must come from the right field.** `_student_names()` froze
  `user.full_name` and ignored `Membership.display_name` — the field that exists
  precisely because a school may know a child by an admission name rather than
  the one on the login. Schools that used it got the wrong name printed on a
  card they cannot edit. Found in review of the snapshot branch (`e50bf11`).
- **Anything derived from the copies must also come from the copies.** A page
  served from the snapshot computes its ranks and its class average over the
  frozen values on the rows it is displaying — never by re-reading live marks and
  never by reading a rank off a card. See rule 6's entry on the broadsheet, and
  `docs/positions.md`.

---

## 3. Immutability lives in the database, not in a docstring

If a row must never change, a **trigger or a constraint** must refuse the change.
A docstring saying "append-only" stops nobody: not a management command, not a
shell session, not the next service that grows a second write path.

The pattern in this repository is a migration named for the rule it enforces, so
`git log` on the migrations directory reads as the list of invariants:

| migration | the rule |
| --- | --- |
| `gradebook/0002_a_released_mark_stays_released` | a `Score` for a released term refuses INSERT, UPDATE and DELETE |
| `results/0013_a_session_line_and_a_decision_are_append_only` | session lines and promotion decisions are written once |
| `results/0017_every_frozen_row_hangs_off_a_card` | no frozen row without its card |
| `results/0018_a_frozen_card_is_append_only` | the card itself |

A refusal that lives only in a service is a refusal that one `objects.update()`
walks past. A refusal in the database arrives as `IntegrityError` from anywhere,
including from a test that was trying to stage a fixture — which is a feature,
not a nuisance, and is why test staging in this repo sometimes has to delete in
dependency order.

**The corollary for services:** when the database refuses something the service
also checks, the two must agree about *which* number or limit. Read the limit off
the field (`MAX_LETTER`, `MAX_REMARK`, `MAX_TRAIT_NAME`) rather than restating it,
so there is one answer and not two that drift.

**And a service check is not automatically also a constraint.** `_require_a_scale()`
claimed "every check here is also a database constraint except the last". It held
in one direction only: the *table* refused three things the *service* did not, and
each arrived as a raw `DataError`/`IntegrityError` from inside `set_scale()`'s own
`atomic()` — **outside `ResultsError`** — so every `except ResultsError` missed it
and the caller got a 500 with a poisoned transaction (`5e7abc1`).

---

## 4. An audit is append-only rows, never mutable columns

Already argued in full in `docs/results.md` under *"The audit is rows, not
columns"*; repeated here because it generalises past the approval chain and the
fee ledger will face the identical temptation.

The obvious design for "who submitted this?" is a `submitted_by` column. It
survives exactly until the first send-back: the teacher resubmits, the column is
overwritten, and the sheet has silently forgotten that it was ever refused, by
whom, and why. **A system whose promise is "here is what happened" cannot have a
memory that edits itself.**

`ResultSheetTransition` carries `from_state` as well as `to_state`, even though
the previous row's `to_state` implies it. That redundancy is deliberate: it is
what lets `nothing_moves_out_of_released` be a check constraint on *this row*
rather than a rule that has to walk the log. **A constraint that needs no context
is one no future query can get wrong.**

For the ledger: a balance is a fold over rows, not a column somebody increments.

---

## 5. If a control leaves a test green, that test is not testing what its name says

The method: **break the thing deliberately, re-run, and read the failure.** A
test suite that passes tells you nothing on its own — you have not learned that
the tests would catch the bug, only that they do not currently fire.

Every substantial change in this phase records its controls in a table
(`docs/positions.md` has the longest). The table has three columns: what was
broken, what failed, and what that says.

**A control that breaks nothing is a result, not a formality.** It has told you
that the claim you were about to ship is unasserted. Two instances, and both
times the pass was the finding:

- `_percentage(0, 0)` returning `Decimal(0)` instead of `None` failed **one** of
  four "not marked" tests. The control was aimed wrong: the naive-zero bug lives
  in the aggregation, not in the percentage helper.
- Replacing the frozen subject columns with `Subject.objects` broke **nothing**,
  across 28 tests. The entire subject half of a released broadsheet — frozen
  column names, print order, per-subject rank — was carried by docstrings and
  asserted nowhere. `TheColumnsAreTheFrozenSubjectLinesTests` exists because of
  that green run, and the control now fails twice. (Arrives with **PR #72**; if
  you cannot find that class, #72 has not merged yet.)

### The three ways a green test is lying

1. **It never reaches the constraint it names.** Postgres checks a column's NOT
   NULL before it checks a CHECK, so once `0017` made `card` NOT NULL, three
   tests in `test_sessions` built rows that were rejected on `card_id` and never
   reached the constraint they were named after. All three went on passing.
   `assertRaises(IntegrityError)` cannot tell the constraint under test from the
   three other ways of never getting there — **assert on the constraint's name.**
2. **It compares something to itself.**
   `assertEqual(app.conf.broker_url, settings.CELERY_BROKER_URL)` stayed green
   with `config_from_object` deleted.
3. **It passes for a reason unrelated to its subject.** A test using
   `position=-1` to check a type guard passed with the type guard disabled,
   because the *range* check caught it. Widening the guard would have hidden
   that; the claim got its own test instead.

**Skips are the silent version of all three.** A test that skips when no broker
answers goes green on a CI run where the broker failed to start. Under `CI`, it
fails instead. `scripts/run-tests.sh` refuses the same silence one level up: a
run that exits 0 without ever printing `OK` or `FAILED` is reported as a failure,
because a run that executed nothing must not be indistinguishable from one that
passed.

---

## 6. A docstring is not a test — an unasserted claim is an open question

Prose in this repository is unusually load-bearing, which makes this the rule
most specific to it. Docstrings here carry design reasoning, and that is worth
keeping. But **a claim is only true because something enforces it**, and prose
enforces nothing.

Three failure modes, in ascending order of cost:

- **The claim was never true.** `results.services.__all__` listed `sheet_for`,
  which that module does not define. Not inert: it raises `AttributeError` on
  `from results.services import *`, at import time (`aae4872`).
- **The claim went stale.** See the table in rule 7 — all ten of them.
- **The claim was a promise to a user.** Six refusal messages — `MarksLocked`
  twice, `RatingsLocked` twice, `CommentsLocked` twice — each ended "correcting
  one is a revision rather than an edit". True of the shape and false of the
  outcome: there was no revision that could carry the correction. Six places told
  a teacher to go and do something impossible (`e604c48`, issue #54).

**The technique that works** is to pin the limit as a test rather than a note.
`WhatARevisionCannotFixTests` asserts that all three inputs refuse a write after
release, that none of the six messages promises a revision will fix it, and that
a revision reproduces every mark, rating and remark exactly. **Those tests go red
the day issue #54 is closed, which is the point of them** — the note would have
been quietly wrong instead.

When you write a claim you cannot yet assert, the honest move is an issue, not a
paragraph. Prose that describes future work should name the issue number, so
that closing the issue has a way to find the prose.

---

## 7. Ten claims that went stale this phase, and how each was found

The list is the argument for rule 6. None of these was a subtle bug; every one
was a sentence somebody had written down, that stopped being true, and that
nothing in the suite would have contradicted. What differs is **how each was
caught** — which is the reusable part.

| # | The claim | How it was found |
| --- | --- | --- |
| 1 | `broadsheet()`: "there is no frozen snapshot yet — that is task 3 — and once there is, a released term must be served from it". Task 3 shipped in #44; the switch was never made, and `docs/positions.md` and `docs/sessions.md` carried the condition too | **Reading the docstring against the code at the moment of touching it.** The docstring named its own successor; nobody re-read it when the successor landed. Three places, one stale condition — issue #55, **PR #72** |
| 2 | Six refusal messages: "correcting one is a revision rather than an edit" | **Asking whether the feature being built delivers what existing user-facing messages already promise.** Building the revision path is what revealed it could not carry a mark |
| 3 | `results.services.__all__` names `sheet_for` | **Mechanical audit of a declaration against definitions**, then *demonstrated* on a two-line module rather than argued from the docs. The other three `results` modules were audited the same way |
| 4 | `TenantTask`: "no `School` row carries the schema name `public`" | **Searching the codebase for a counterexample to the premise.** Four of its own test modules build `School(schema_name="public")`. The guard's test passed only because `TenantTaskTests` was the one class that never built a portal |
| 5 | "Nothing freezes marks until task 3", used to justify keying a release guard on `ClassPlacement` | **Code review of the PR (`/code-review`), which separated two conflated claims** — marks frozen vs. release knowable. Migration `0011` was already keying on the artefact one table over |
| 6 | Three `test_sessions` tests named for a constraint they no longer reached, after `0017` made `card` NOT NULL | **`/code-review high`.** No behaviour changed and nothing failed; the tests kept passing while testing nothing |
| 7 | `ReleasedCard.released_by`'s docstring: "`release()` stamps the actor", while `cards._card_for()` hard-coded `released_by_id=None` | **Reading a field's docstring against its single writer.** The table is append-only, so every card would have gone out with no releaser, permanently |
| 8 | `_require_a_scale()`: "every check here is also a database constraint except the last" | **Testing the claim in both directions.** It held one way; the table refused three things the service did not, each arriving outside `ResultsError` as a 500 |
| 9 | Five places describing a per-test `migrate_schemas`, after the suite moved to cloning a template | **Grepping for the claim's *argument*, not its keyword.** Four were corrected together because they sat near the `--parallel` comment where the change was visible; the fifth was fifty lines away in `tests.yml`'s `services:` block, making a different argument, and was missed on the first pass |
| 10 | "Every tenant test now clones instead of migrating" | **Measuring instead of trusting.** `test_card_api.py` was still migrating two schools per test across thirty tests, because its fixture was a `_school()` method rather than one of the fourteen module-level `make_school()` copies the change had gone looking for. 195.8s → 119.0s once fixed; three `TransactionTestCase` modules still migrate by design, and the docstrings now name them |

### What the ten have in common

Read them together and the discovery methods collapse into four, worth running
deliberately rather than hoping to stumble into:

1. **Read the prose against the code it describes, at the moment you touch it.**
   Items 1, 3, 7. The cheapest of the four and the one most often skipped,
   because the prose is usually right and reading it feels like it costs nothing
   to skip.
2. **Look for a counterexample to the premise, in this codebase.** Items 4, 5.
   Premises about what "never happens" are worth one `grep` each. Twice the
   counterexample was in the project's own test fixtures.
3. **Test the claim in both directions, and measure rather than assume.**
   Items 8, 10. "X implies Y" is half a claim.
4. **Search for the *argument*, not the keyword.** Item 9. A stale claim
   restated in different words, far from the change, is the one that survives the
   sweep — and the fifth copy was found only because somebody went looking for a
   fifth.

Item 2 is the one that fits none of them, and it is the most expensive kind:
prose that is a **promise to a user**. It went stale in six places at once and no
audit of the code would have caught it, because the code was correct — it was the
sentence describing the code's *future* that was false. The only defence found
for that one is a test that goes red when the promise becomes keepable.

---

## Before you open a PR

The short form of everything above, as the checklist actually used this phase:

- [ ] Does any guard I touched key off **current placement** where it should key
      off a released artefact? (Rule 1)
- [ ] Does any frozen row **join** to something a school can rename? (Rule 2)
- [ ] Is every "never changes" I rely on enforced by a **trigger or constraint**?
      (Rule 3)
- [ ] Did I add a **mutable column** where the history matters? (Rule 4)
- [ ] Have I **broken each claim deliberately** and watched the right tests fail —
      and did any control leave the suite green? (Rule 5)
- [ ] Is there a claim in a docstring, a refusal message, or a doc that **nothing
      asserts**? (Rule 6)
- [ ] Did this change make any existing prose **stale**, anywhere — including
      fifty lines away, making a different argument? (Rule 7, item 9)

Then the process rules, which are not about code:

- One PR per task, cut from `main` and merged to `main`. **Never stack branches**
  — a chain of PRs each merged into its own base reaches `main` never, which is
  how #12–#15 were lost.
- After a merge, verify with `git merge-base --is-ancestor <sha> origin/main`. A
  "merged" badge is a different claim from reachability.
- Prove behaviour with a runnable test, run it, and show the output. **Two
  tenants, never one** — a surprising share of the defects above are invisible
  with a single school.
- Track anything found-but-not-fixed in a **GitHub issue**, not in prose. This
  whole document is the argument for that sentence.
