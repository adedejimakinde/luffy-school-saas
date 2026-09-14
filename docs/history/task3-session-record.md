# Task 3 — complete session record (2026-08-29)

Everything produced in the session that finished task 3 and opened PR #44.
Assembled from `git` and `gh`, not retyped.

- Branch: `report-card-snapshot` — three commits on top of `main` at `90794bb`
- PR: https://github.com/adedejimakinde/luffy-school-saas/pull/44 (open, targets `main`, **not merged**)
- New issue: #43
- Full suite on the final commit: **993 tests, OK**, 2969.605s

---

## Contents

1. [Commits](#1-commits) — all three, in full
2. [Diff stat against main](#2-diff-stat-against-main)
3. [PR #44 body](#3-pr-44-body)
4. [PR #44 verification comment](#4-pr-44-verification-comment)
5. [Issue #43 — filed, not fixed](#5-issue-43--filed-not-fixed)
6. [`/code-review high` findings, verbatim](#6-code-review-high-findings-verbatim)
7. [Test runs](#7-test-runs) — every run and every control
8. [Raw logs](#8-raw-logs)
9. [What I reported in the terminal, verbatim](#9-what-i-reported-in-the-terminal-verbatim)
10. [Where this leaves things](#10-where-this-leaves-things)

---

## 1. Commits

### `f582236` Task 3: the card itself, and the row that says it went home

```
Task 3: the card itself, and the row that says it went home

Everything in this app so far freezes one *section* of a report card — the
conduct, the remarks, the session line. This freezes the card, and above all the
row recording that a card went home at all.

## `ReleasedCard` is the artefact, written unconditionally

One row per child on the roster at release, inside the release transaction,
whatever else is or is not true: no marks, no ratings, both conduct groups off
school-wide, nothing decided.

That is a requirement rather than a convenience, and it closes a hole four
commits have now touched. A guard asking *has a card gone home for this child?*
had four places to look and a placement join to fall back on, and the fallback
answers a different question: `ClassPlacement` holds one group per child per
term, so a mid-term move **rewrites** the row and the record of where the child
sat at release is destroyed rather than superseded. Release JSS 1A, move the
child to JSS 3B whose sheet is an untouched draft, and a released remark could
be rewritten — the child who stayed put protected, the child who moved not, on
the same term by the same guard.

`0010` and `0011` fixed that a table at a time. What was left was a **per-school**
hole rather than a per-child one: a school with the conduct section off froze
nothing for anybody, so nothing recorded its releases at all. Issues #31, #33
and #34 each arrived here from a different direction.

**No constraint holds this.** No `CHECK` can say "a row exists for every child on
a roster this transaction has already moved past". It is held by
`cards.freeze_for_release()` and pinned by `TheUnconditionalMarkerTests` with a
control behind it — and the docstrings say so, because a guarantee that lives
only in a test is one that vanishes when the test is deleted for looking
redundant.

## The premise trap, written down where the next reader will hit it

The rule was already known: *a guard on a released artefact keys off the
artefact, not the child's current placement*. The trap sits above the rule and
is what actually caught issue #27's first draft:

> "The marks are not frozen" and "no artefact records the release" are different
> claims, and the first does not imply the second.

The reasoning went: task 3 has not shipped -> nothing freezes the marks -> there
is no artefact to key on -> key on placement. Every step after the second is
sound. `ReleasedTraitRating` had been answering the question all along. The
failure was in the survey, not the logic — a claim about the system arriving
disguised as a claim about the task in hand.

Its next form is already visible and is stated in `docs/cards.md`: *"a snapshot
row exists, therefore a card went home"* is true, but *"content exists,
therefore a card went home"* is not. Guards key on `ReleasedCard`, never on the
presence of content.

## Everything the card prints is copied

Not joined to. Six edits a school makes on an ordinary Tuesday would otherwise
reach backwards into a card in a parent's hand: renaming a subject, renaming an
assessment, renaming the class, replacing the grading scale, correcting a
child's name, renaming the school. `TheCopyTests` performs each one *after*
release and asserts the card did not move — a test that only reads a fresh card
proves nothing about freezing.

`student_name` and `school_name` are the two most easily missed: both come from
`accounts`, a **shared** schema whose rows change for reasons unconnected to
this school.

**The grade letter especially.** `grades.grade_for()` is called at freeze time
and its answer stored; nothing downstream may call it on a frozen percentage.
Two tests hold that, and the second is the one that matters: one replaces the
scale after release and checks the letters did not move, and one asserts that
reading a card issues **no query against `results_gradeband` at all**. A
renderer that re-derived and happened to agree would pass the first.

The scale is read once per release rather than once per child, so a class's
cards agree with each other.

## What is deliberately not frozen

**The class average**, computed on demand. Position is a statement about *this*
child and is fixed at release; the class average is a statistic about the other
forty-four. Freeze it and one child's revision leaves forty-four unrevised cards
asserting a number that disagrees with the revised one — the
school's-screen-versus-card disagreement this phase exists to kill. Both are
staff-only, so nothing about reproducibility is lost. A test asserts the column
does not exist, so the decision cannot be quietly reversed.

**The promotion decision**, read live from the append-only `PromotionDecision`.

## One answer to "did a card go home", not four

`ReleasedTraitRating`, `ReleasedComment` and `ReleasedSessionResult` each gain a
non-null `card` FK, backfilled by `0017`. Four answers to one question is the
condition that produced the bug above.

The backfill **invents cards** for historical `(sheet, student)` pairs, and that
is correct: a frozen rating *is* the record that a card went home for that
child, so the row is not fabricated, it is the fact written where it now
belongs. Those cards carry the sections and nothing else — no marks, no average
— because the marks were never frozen, and reconstructing a past card from
today's live scores is precisely what this snapshot exists to prevent.

## `cards.freeze_for_release()` runs first, and that is structural

`services.release()` calls it ahead of ratings, comments and sessions, because
they hang off the row it writes. The old note there said the order was "the
order they print" so a partial failure would truncate a card rather than hollow
it out; that was never load-bearing — the block is one transaction — and the
first call is now required rather than merely first. The comment says so.

## Rows rather than JSON

About 1,350 score cells per release for a class of forty-five. Deliberate, on
`ReleasedTraitRating`'s existing argument: one table means a card is exactly
"these rows, in this order", a property that can be looked at and asserted
against. The cost is paid on the read path, where `card_lines()` and `cards_on()`
fetch by `card_id` in a bounded number of queries — task 7 renders forty-five of
these in one job.

## Verified

**33 tests** in `results/tests/test_cards.py`; the existing 54 session tests
pass unchanged against the now-required `card` FK.

Two controls on the guarantee that has no constraint behind it:

| control | what stops passing |
| --- | --- |
| the freeze made conditional on the conduct section, as ratings' is | 3 of the 5 marker tests |
| only children with marks get a card | 3 of the 5 marker tests |

Two bugs the runs caught in the tests themselves, both of which read correctly
by eye: `move_student()`'s arguments in the wrong order, and a lazy
`.assessment_scores.first()` evaluated **outside** its `connected_to()` block,
which queries the public schema where the table does not exist. That is the
second time this phase — the module docstring now warns about it.

## Filed, not fixed

**#42** — `Assessment` has no print order, so its `Meta.ordering` sorts papers
alphabetically: "Exam, First CA, Second CA". The freeze orders by creation order
instead, which is closer to right and still a guess. It matters more than it
looks because the order is **frozen**: a wrong guess is frozen too, and fixing
it later will not correct cards already issued.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

### `abd6d2b` The backfill meets the guards it has to write through, and two names on it

```
The backfill meets the guards it has to write through, and two names on it

`0017` fills in `card_id` on rows released before the column existed. That is
an UPDATE, and all three tables it updates refuse UPDATE outright — a
`BEFORE UPDATE OR DELETE` trigger whose whole body is `RAISE EXCEPTION`, since
`0007`, `0009` and `0013`. So the migration could not run at all on any
database that has ever released a card; it would have failed mid-deploy at the
first `bulk_update` with `restrict_violation`. It now suspends the three
triggers for the width of the write and puts them straight back, which is safe
because Postgres DDL is transactional and a migration is one transaction: no
session observes the guards missing, and the only column written is `card_id`,
so no card changes what it says.

An empty database hides every part of this. With nothing released the backfill
finds no pairs and returns before it writes, so a green suite and a clean fresh
install say nothing. The tests release a term and then walk it back to the
pre-`0016` shape — cards linked but unlinkable, and separately no cards at all,
which is what a school that released anything before this branch has.

Two more bugs fell out of testing the invented-card path, both on the header of
the page and neither visible to a test that counts rows:

- `school_name` was written empty, against what the module docstring said.
- `class_group_name` went through `str(sheet.class_group)`. `apps.get_model()`
  in a `RunPython` returns a model rebuilt from migration state, and rebuilt
  models carry fields, not methods, so `ClassGroup.__str__` is not on it and
  every backfilled card would have gone home saying `ClassGroup object (3)`.

That second one is also a flaw the tests had: handing the backfill
`django.apps.apps` makes it agree with itself for a reason production does not
share. They now build the registry from `0017`'s own declared `dependencies`,
which is the one Django passes.

Controls run for all three: removing the suspension reproduces the
`restrict_violation`, and reverting either name fails on the exact string.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

### `e50bf11` Act on the review: three tests that proved nothing, and two columns nothing filled

```
Act on the review: three tests that proved nothing, and two columns nothing filled

`/code-review high` on this branch. Six findings, five fixed here and one filed.

**Three tests in `test_sessions` stopped testing their constraint the moment
`0017` made `card` NOT NULL.** Postgres checks a column's NOT NULL before it
checks a CHECK, so a row built without a card is rejected on `card_id` and never
reaches the constraint the test is named after. All three went on passing.
They now go through one helper that supplies a card and asserts on the
**constraint's name** — `IntegrityError` is what a unique index, a null column
and a foreign key all raise, so `assertRaises(IntegrityError)` alone cannot tell
the constraint under test from the three ways of never reaching it. The same
hardening is applied to `TheConstraintsTests._a_card` and to
`test_a_score_above_its_paper_is_refused`, which built its bad row on an
assessment already frozen onto the card and so was a duplicate `(card,
assessment)` pair as well.

**`TwoSchoolsTests.test_a_card_went_home_is_false_at_the_other_school` never
entered the other school** and never asserted `False`; it released at St Mary's
and asserted `True`, which `TheUnconditionalMarkerTests` already covers. The
function was free to answer `True` everywhere and a release guard keyed on it
would then have refused every school's edits the moment any one school released.
Grace Academy now has a session, a class and a child on its roster, and is asked.

**`released_by_id` was hard-coded to `None`** in `cards._card_for()` while the
field's own docstring said `release()` stamped the actor. Every card would have
gone out with no releaser, permanently — the table is append-only, so an empty
column on it is not a gap that can be closed later. The actor was already in
scope in `services.release()` and is now threaded through.

**`_student_names()` froze `user.full_name` and ignored `Membership.display_name`.**
That field exists because a school may know someone by a different name than the
one on their login, and `Membership.name` prefers it. A school that admitted a
child under an admission name got the login name printed on a card it cannot
edit.

Filed rather than fixed: **#43**, release reads the roster twice and the lock
covers only the `ResultSheet` row, so a placement committed between the two
reads now aborts the whole class's release with a null-column error. The three
comments that claim a card exists for every child point at it.

Controls run for four of the five: reverting each fails on the exact wrong
value, and the three session tests fail with `null value in column "card_id"`,
which is the defect itself.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

## 2. Diff stat against main

```
 docs/cards.md                                      |  194 ++++
 results/cards.py                                   |  411 +++++++
 results/comments.py                                |   15 +
 .../migrations/0016_the_report_card_snapshot.py    |  379 ++++++
 .../0017_every_frozen_row_hangs_off_a_card.py      |  289 +++++
 .../0018_a_frozen_card_is_append_only.py           |  108 ++
 results/models.py                                  |  497 ++++++++
 results/positions.py                               |   17 +
 results/ratings.py                                 |   15 +
 results/services.py                                |   37 +-
 results/sessions.py                                |   15 +
 results/tests/test_cards.py                        | 1201 ++++++++++++++++++++
 results/tests/test_sessions.py                     |  136 ++-
 13 files changed, 3248 insertions(+), 66 deletions(-)
```

---

## 3. PR #44 body

Closes #34. Speaks to #31 and #33, which arrive at the same requirement from
different directions.

## What this is

`ReleasedCard` — one row per child on the roster at release, **unconditionally**,
whatever else is true: no marks, no ratings, both conduct groups switched off,
nothing decided. It is the artefact that says a card went home, and it is the
thing a release guard can finally key on.

The three older frozen tables (`ReleasedTraitRating`, `ReleasedComment`,
`ReleasedSessionResult`) gain a non-null `card` FK, so there is **one** answer to
"did a card go home for this child?" rather than four. Four answers is the
condition that produced #27. Two new content tables, `ReleasedSubjectResult` and
`ReleasedAssessmentScore`, hang off the card and hold the marks — which nothing
froze until now.

`docs/cards.md` carries the full argument. The parts worth reading in a review:

**The premise trap.** "The marks are not frozen" and "no artefact records the
release" are different claims, and the first does not imply the second. #27's
first draft reasoned from one to the other, concluded there was no artefact, and
keyed its guard on `ClassPlacement` — which holds one group per child per term,
so a mid-term move rewrites it and destroys the record of where the child sat at
release. `ReleasedTraitRating` had been answering the question all along. The
rule that falls out: guards key on `ReleasedCard`, never on the presence of
content.

**Copied, not joined.** Every join out of a frozen row goes through something a
school edits on an ordinary Tuesday. The two easiest to miss are `student_name`
and `school_name`, both from `accounts`, a *shared* schema whose rows change for
reasons unconnected to this school.

**The grade letter especially.** `grades.grade_for()` is called once per release
and stored. Nothing downstream may call it on a frozen percentage, or a school
replacing its scale rewrites every card already in a parent's hand while the
percentages beside them stay put. The load-bearing test asserts that reading a
card issues **no query against `results_gradeband` at all** — a values-only test
passes against a renderer that re-derives and happens to agree.

**`class_average` is deliberately not frozen.** Position is a statement about
*this* child and is fixed at release; the class average is a statistic about the
other forty-four, and freezing it leaves every unrevised card contradicting a
revised one. A test asserts the column does not exist, so it cannot be quietly
reintroduced.

## The second commit is three real bugs in `0017`

Testing the backfill properly — which had never been done — turned up three, and
the first was a deploy-stopper.

1. **`0017` could not run at all on any database that has ever released a card.**
   It fills in `card_id`, which is an UPDATE, and all three tables it updates
   refuse UPDATE outright: a `BEFORE UPDATE OR DELETE` trigger whose whole body
   is `RAISE EXCEPTION`, since `0007`, `0009` and `0013`. It would have failed
   mid-deploy at the first `bulk_update` with `restrict_violation`. It now
   suspends the three triggers for the width of the write and puts them straight
   back — safe because Postgres DDL is transactional and a migration is one
   transaction, so no session observes the guards missing, and the only column
   written is `card_id`, so no card changes what it says.

2. **`school_name` was written empty** on every invented card, against what the
   migration's own docstring said it did.

3. **`class_group_name` went through `str(sheet.class_group)`.**
   `apps.get_model()` inside a `RunPython` returns a model rebuilt from migration
   state, and rebuilt models carry **fields, not methods** — `ClassGroup.__str__`
   is not on it. Every backfilled card would have gone home saying
   `ClassGroup object (3)`.

**An empty database hides all three.** With nothing released the backfill finds
no pairs and returns before it writes, so a green suite and a clean fresh install
say nothing at all about it. The tests release a term and then walk it back to
the pre-`0016` shape: `TheBackfillMeetsTheAppendOnlyGuardsTests` for a database
whose cards exist and only need linking, and
`TheBackfillInventsTheMissingCardsTests` for what a school that has released
anything actually has — frozen sections and no cards.

And the flaw underneath bug 3 was in the tests: handing the backfill
`django.apps.apps` makes it agree with itself for a reason production does not
share. They now build the registry from `0017`'s own declared `dependencies`,
which is the one Django passes.

## The third commit is the review acting on itself

`/code-review high` returned six findings. Five are fixed here; one is filed.

**Three tests in `test_sessions` had stopped testing their constraint** the
moment `0017` made `card` NOT NULL. Postgres checks a column's NOT NULL before
it checks a CHECK, so a row built without a card is rejected on `card_id` and
never reaches the constraint the test is named after — and all three went on
passing. They now supply a card and assert on the **constraint's name**, because
`IntegrityError` is what a unique index, a null column and a foreign key all
raise. The same hardening went onto `TheConstraintsTests._a_card` and
`test_a_score_above_its_paper_is_refused`.

**`TwoSchoolsTests.test_a_card_went_home_is_false_at_the_other_school` never
entered the other school**, and never asserted `False`. It released at St Mary's
and asserted `True` — which the unconditional-marker tests already cover. The
function was free to answer `True` everywhere, and a release guard keyed on it
would then refuse every school's edits the moment any one school released a
term. Grace Academy now has a session, a class and a child on its roster, and
gets asked.

**`released_by_id` was hard-coded to `None`** while the field's own docstring
said `release()` stamped the actor. Every card would have gone out with no
releaser on it, permanently — the table is append-only, so that is not a gap
that can be filled in later. The actor was already in scope; it is threaded
through now.

**`_student_names()` ignored `Membership.display_name`**, which exists because a
school may know someone by a different name than the one on their login, and
which `Membership.name` prefers. A school that admitted a child under an
admission name got the login name printed onto a row it cannot edit.

## Verification

- `results.tests.test_cards` and `results.tests.test_sessions`: **100 tests,
  green.**
- Full suite: see the comment below.
- **Controls run for every fix**, because on this branch a passing test has
  already proved nothing twice. Removing the trigger suspension reproduces the
  `restrict_violation` exactly; reverting either backfilled name fails on the
  exact wrong string (`''` and `'ClassGroup object (3)'`); dropping the card
  from the three session rows fails with `null value in column "card_id"`,
  which is the defect itself; and reverting `released_by_id` or the display
  name fails on the value.
- Two schools, and the second one is used rather than built and ignored.

## Known gaps, filed not fixed

- **#43** (new, from the review) — `release()` reads the roster twice and the
  lock covers only the `ResultSheet` row, so a `ClassPlacement` committed
  between the two reads leaves a child the card freeze never saw. That used to
  produce a slightly inconsistent card; with `card_id` NOT NULL it now aborts
  the whole class's release with a null-column error. Aborting is arguably the
  better of the two — a card half-frozen down the middle is worse than one not
  frozen at all — but nothing *names* it, and the real fix is to stop reading
  the roster twice. The three comments claiming a card exists for every child
  point at the issue.
- **#42** — `Assessment` has no explicit print order, which matters more now
  that the order is *frozen* onto the card.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


---

## 4. PR #44 verification comment

## Full suite: 993 tests, green

```
Ran 993 tests in 2969.605s

OK
```

Run on `e50bf11` — the final commit, with the review fixes in. Task 3 had never had a full run before today; an earlier attempt on `abd6d2b` was stopped as stale when the review fixes landed, so this is the first one that covers the branch as it stands.

`makemigrations --check` is clean.

## Controls

Every fix on this branch has a control run behind it, because a passing test on this branch has already proved nothing twice:

| reverted | what the test does |
| --- | --- |
| `0017`'s trigger suspension | 3 errors, `results_releasedtraitrating is append-only; UPDATE is not allowed` — the `restrict_violation` a real deploy would have hit |
| `school_name` / `class_group_name` | fails on `{'school_name': '', 'class_group_name': 'ClassGroup object (3)'}` |
| the card on the 3 session rows | fails with `null value in column "card_id" ... violates not-null constraint` — the constraint under test never reached, which is the defect |
| `released_by_id` | `[None, None] != [25, 25]` |
| `display_name` | `'Babatunde Ade' != 'Tunde Ade'` |

One control did **not** fire, and it is worth recording rather than quietly dropping. Rebuilding `test_a_score_above_its_paper_is_refused` on the assessment already frozen onto the card — the duplicate `(card, assessment)` pair the review flagged — does not change which error comes back: Postgres evaluates a CHECK as the tuple is formed, before it inserts into the unique index, so `a_frozen_score_fits_its_paper` still fires. The duplicate pair would only have mattered with that check constraint deleted. Asserting the constraint's name is what actually closes it; the separate assessment keeps the row bad in one way at a time. The test's docstring says so.

---

## 5. Issue #43 — filed, not fixed

**Release reads the roster twice, so a placement committed between the two aborts the whole release**

Found by review on the task 3 branch (`report-card-snapshot`). Not introduced by it — the second roster read has always been there — but task 3 changes what the race *does*, so it is worth writing down now.

## The two reads

`services.release()` runs its freezes inside one transaction, under a lock taken by `_locked(sheet)`. That lock is on the **`ResultSheet` row**, and on nothing else.

Inside it:

- `cards.freeze_for_release()` reads the roster via `positions.class_results()`;
- `ratings.freeze_for_release()`, `comments.freeze_for_release()` and `sessions.freeze_for_release()` each re-read it via `positions.roster_ids()`.

Postgres runs Django at READ COMMITTED, so **every statement takes a fresh snapshot**. Nothing stops an admin from committing a `ClassPlacement` into that class between the first read and the second. `positions.ClassResults`'s own docstring already concedes the point: "the roster is still a second query".

## What it does now, and what it did before

The section modules look their parent card up with `card_by_student.get(student_id)` — `results/ratings.py:1011`, `results/comments.py:747`, `results/sessions.py:596`. For a child the second read sees and the first did not, that returns `None`, and `card` is NOT NULL as of `0017`.

So the release now **aborts for the whole class** with

```
IntegrityError: null value in column "card_id" violates not-null constraint
```

which is a 500 on a principal's screen that says nothing about what happened. Before task 3 the same race wrote a rating row for a child with no card — inconsistent, but it did not take the other forty-four down with it.

Aborting is arguably the better of the two: a card half-frozen down the middle is worse than one not frozen at all, and the transaction rolls it all back cleanly. The complaint is not the abort, it is that nothing **names** it.

## What would fix it

Two directions, and they are not exclusive:

1. **One roster read.** `cards.freeze_for_release()` already has the roster and writes the card map; passing that map (or the roster it came from) down to the three section freezes removes the second read entirely, and with it the disagreement. This is the real fix, and it is cheap — the three modules already call `cards.cards_by_student(sheet)` to get the same map back.
2. **Name the failure.** Whatever the roster reads do, `card_by_student[student_id]` failing should raise something in `ResultsError` that says the roster moved mid-release and the release should be retried, rather than surfacing as a null-column error.

Related: #30 and #40 are the other two places where a lock covers less than the work done under it.

---

## 6. `/code-review high` findings, verbatim

Six findings. Five fixed in `e50bf11`; one filed as #43.

> I read every hunk, opened the surrounding models/services/positions/grades code for context, ran `makemigrations --check` (clean), and ran the new suite against Postgres: **44 tests, all pass** (256s). The production freeze path is in good shape — I traced the four roster reads, all constraint pairs against what `cards._card_for`/`_subject_line`/`_score_cell` actually write, the `card_for` ordering, the trigger drop/recreate in `0017` (bodies match `0007`/`0009`/`0013` exactly), and `bulk_update(rows, ["card_id"])` (Django's `_forward_fields_map` resolves `attname`, so that is fine). No correctness bug found in the freeze itself.
>
> The real problems are in test coverage that this PR silently disables, plus two smaller code gaps.
>
> ### Findings
>
> - **`results/tests/test_sessions.py:661` — medium.** `test_the_database_still_refuses_an_average_the_arithmetic_dropped` calls `ReleasedSessionResult.objects.create(...)` without `card`, which `0017` has just made NOT NULL. Postgres runs attribute NOT-NULL checks before CHECK constraints, so the row is now rejected on `card_id` and the check constraint the test names is never reached. Delete `a_session_average_has_terms_behind_it` from the model and this test still passes. Same defect at **`results/tests/test_sessions.py:690`** (`test_the_database_still_refuses_an_average_with_nothing_behind_it`) and **`results/tests/test_sessions.py:740`** (`test_the_database_refuses_a_term_that_is_neither_present_nor_explained`). Each needs `card=<a real card for that sheet>` — reachable via `cards.cards_by_student(sheet)` — so the insert gets far enough to hit the constraint under test.
>
> - **`results/tests/test_cards.py:739` — medium.** `TwoSchoolsTests.test_a_card_went_home_is_false_at_the_other_school` never enters `connected_to(self.grace)` and never asserts `False`; its whole body is a `connected_to(self.stmarys)` release plus `assertTrue(cards.a_card_went_home(...))`, duplicating `TheUnconditionalMarkerTests`. The class docstring's claim ("one school's release is not the other's") has no coverage for `a_card_went_home`, and the test would stay green if the function leaked across schemas.
>
> - **`results/tests/test_cards.py:679` — low.** `test_a_score_above_its_paper_is_refused` builds the bad row with `assessment=cell.assessment` on the same `card`, which is a duplicate `(card, assessment)` pair. The row violates both `a_frozen_score_fits_its_paper` and `one_score_cell_per_card`, so removing the check constraint leaves the test green on the unique index. Use a second `Assessment` (or another card) so only the check constraint can fire.
>
> - **`results/cards.py:231` — low.** `released_by_id=None` is hard-coded, and nothing else in the tree ever writes that column (`grep` finds only this line, the field, and the migration). `ReleasedCard`'s own docstring says "`services.release()` stamps the actor", but `_move()` calls `freeze(locked)` with the sheet only — the actor is in scope at `services.py:534` and is never passed down. Every card written from now on has a permanently null releaser, and because the table is append-only it cannot be filled in afterwards. Either thread the actor through `freeze_the_card`/`freeze_for_release`, or drop the claim from the docstring.
>
> - **`results/ratings.py:1011` — low** (same shape at `results/comments.py:747` and `results/sessions.py:596`). `card_by_student.get(student_id)` returns `None` rather than raising for a student the second roster read sees but the first did not. `cards.freeze_for_release()` reads the roster via `positions.class_results()` and each section module re-reads it via `positions.roster_ids()`; under READ COMMITTED every statement inside `_move`'s transaction takes a fresh snapshot, and `_locked()` locks only the `ResultSheet` row, not `ClassPlacement`. An admin committing a placement into that class between the two reads now aborts the entire release with `IntegrityError: null value in column "card_id"` — before this PR the same race produced only a slightly inconsistent card. `positions.ClassResults`'s docstring already concedes "the roster is still a second query". Passing the roster (or the card map) down from `cards.freeze_for_release`, or at minimum indexing with `card_by_student[student_id]`, makes the failure explicit instead of a null FK.
>
> - **`results/cards.py:91` — low.** `_student_names()` freezes `user.full_name` and ignores `Membership.display_name`, which exists precisely because "a school may know a [person] by a different name than the one on their login" and which `Membership.__str__` prefers. `accounts.services.enroll_student()` accepts `display_name`, so a school that admitted a child under a school-specific name gets the login name frozen onto every card — and the card is append-only, so it is correctable only by a revision. (It is consistent with `results/api.py:161`, which is why this is low rather than higher, but those two also fall back to `username` where `full_name` is blank while this falls back to `""`.)
>
> ### Checked and clean
>
> Constraint/writer agreement on all seven check constraints (`grade_for(None) → None` keeps `an_unmarked_subject_line_carries_no_grade` satisfied; `_percentage` returns `None` exactly when `available == 0`, matching both `*_has_marks_behind_it` pairs); `bulk_create` pk population before the line/cell build; no re-release path (`RELEASED ∉ SENDABLE_BACK_FROM`); trigger suspend/restore bodies identical to `0007`/`0009`/`0013`; `card_for`'s explicit `(created_at, id)` then `-version` ordering; no circular import from the new `academics.models.TermName` import in `results/models.py`; `ClassResults` is constructed only by keyword, so the inserted `totals` field breaks nothing; psycopg2 client-side binding means the unbatched 1,350-row `bulk_create` has no parameter-limit exposure.

### One correction to that review

Finding 3 says removing the check constraint "leaves the test green on the unique index". True as stated, but the accompanying implication — that the duplicate pair changes *which* error currently comes back — is wrong: Postgres evaluates a CHECK as the tuple is formed, before it inserts into the unique index, so `a_frozen_score_fits_its_paper` fired either way. A control run confirmed it. Asserting the constraint's name is what actually closes the hole; the separate assessment keeps the row bad in one way at a time.

---

## 7. Test runs

| run | result |
| --- | --- |
| `test_cards` (after the `0017` guard fix) | 37 tests, OK, 112s |
| `test_cards` (after the two name fixes) | 44 tests, OK, 131s |
| `test_cards` + `test_sessions` (after the review fixes) | 100 tests, OK, 433s |
| **full suite on `e50bf11`** | **993 tests, OK, 2969.605s** |
| `makemigrations --check` | clean |

### Controls — every fix reverted, and what the tests then said

| reverted | outcome |
| --- | --- |
| `0017`'s trigger suspension | 3 errors: `results_releasedtraitrating is append-only; UPDATE is not allowed` — the `restrict_violation` a real deploy would have hit |
| `school_name` and `class_group_name` | `[{'school_name': '', 'class_group_name': 'ClassGroup object (…)'}] != [{'school_name': "St Mary's", 'class_group_name': 'JSS 1A'}]` |
| the card on the three session rows | `'a_session_average_has_a_term_behind_it' not found in 'null value in column "card_id" … violates not-null constraint'` — the constraint under test never reached, which is the defect itself |
| `released_by_id` | `[None, None] != [25, 25]` |
| `display_name` | `'Babatunde Ade' != 'Tunde Ade'` |
| the score cell's separate assessment | **did not fire** — see the correction above |

### A note that cost time

The `schools` dependency added to `0017` for `school_name` is satisfied transitively (`accounts.0001_initial` already depends on `schools`), so removing it leaves the tests green. The docstring originally claimed the tests would catch its removal; a control run falsified that and the claim was rewritten rather than left standing.

---

## 8. Raw logs

Written to this session's scratchpad, which is **session-scoped and will not survive**. The summary lines are in section 7; the trimmed tails are copied alongside this file as `task3-logs/`.

---

## 9. What I reported in the terminal, verbatim

The prose written back during the run, reproduced because it does not exist
anywhere else once the scrollback is gone.

### Closing report on the run

> Task 3 is finished and up for review. Here's where it landed.
>
> **PR #44 is open** against `main`: https://github.com/adedejimakinde/luffy-school-saas/pull/44
>
> ## What I did this session
>
> Picked up uncommitted work from the last session — a partial fix to migration `0017` — verified it, and then found three more bugs by testing the backfill properly for the first time.
>
> **`0017` could not have run on any real school's database.** It fills in `card_id`, which is an UPDATE, and all three tables it updates carry a `BEFORE UPDATE OR DELETE ... RAISE EXCEPTION` trigger from `0007`/`0009`/`0013`. It would have failed mid-deploy. An empty test database hides this completely: no released rows means no pairs to link, so the backfill returns before writing and everything is green.
>
> Testing the invented-card path then turned up two more: `school_name` written empty, and `class_group_name` going through `str(sheet.class_group)`. That second one is the interesting one — `apps.get_model()` in a `RunPython` returns a model rebuilt from migration state, and rebuilt models carry **fields, not methods**, so every backfilled card would have said `ClassGroup object (3)`. The tests couldn't have caught it either: they handed the backfill `django.apps.apps`, making it agree with itself for a reason production doesn't share.
>
> **The code review** (`high`) returned six findings. Five fixed, one filed as #43. The sharpest: three tests in `test_sessions` had silently stopped testing their constraint the moment `card` became NOT NULL — Postgres checks a column's NOT NULL before a CHECK, so the row never reached the constraint under test, and all three went on passing. They now assert on the constraint's *name*.
>
> ## Verification
>
> - **Full suite: 993 tests, green** (~50 min, on the final commit). Task 3 had never had a full run before today.
> - **Controls run for every fix.** One of them didn't fire — rebuilding the score-cell test on a duplicate `(card, assessment)` pair doesn't change which error comes back, because Postgres evaluates CHECKs before index insertion. I recorded that in the PR comment and corrected the docstring rather than leaving the claim standing.
>
> ## What needs you
>
> **Merging.** Opening the PR is mine; merging `main` takes your word — that's the rule from the #12–#15 chain. Once you say go, I'll merge, run the ancestry check, close #34, and start task 6.
>
> One thing worth flagging: **#43 is a behaviour change, not just a latent bug.** `release()` reads the roster twice under a lock that only covers the `ResultSheet` row. Before task 3 a placement committed between the two reads produced a slightly inconsistent card; now it aborts the whole class's release with a null-column error. I think aborting is the better of the two — a card half-frozen down the middle is worse than one not frozen — but nothing names it, and the real fix is to stop reading the roster twice. I left it out of this PR as out of scope; tell me if you'd rather it went in before the merge.

---

## 10. Where this leaves things

- **PR #44 is open and not merged.** It targets `main`, the full suite is green on
  its head commit, and the verification comment is posted.
- **Merging needs your word.** After it, the ancestry check
  (`git merge-base --is-ancestor <sha> origin/main`), then close **#34**, then task 6.
- **#43 is open** and deliberately not fixed on this branch.
- Nothing else on this branch is waiting on anybody.
