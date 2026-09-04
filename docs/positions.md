# Position in class, and who is allowed to see it

Two numbers a Nigerian report card is judged on — a child's position in the
class and their position in each subject — plus the two averages that are easy
to confuse with each other. `results/positions.py` computes them;
`results/api.py` decides who may look.

## The unit is the class roster for the term

A position is *out of something*, and the something is
`academics.ClassPlacement` for that `(class_group, term)`. Not "everybody with a
mark in this subject", which would rank a JSS 1A child against JSS 1B; not the
session, because a child who moves from 1A to 1B in January has to be ranked
among the children they were actually taught with.

This is why `ClassGroup` and `ClassPlacement` were built first. Before them
there was no denominator.

## Dense ranking

    scores   88  74  74  61
    dense     1   2   2   3      <- what this does
    standard  1   2   2   4      <- what it deliberately does not do

A tie does not consume the position below it. Standard Nigerian practice, and
the practical argument is the tie at the top: a class where eleven children draw
first would otherwise print "12th" on a card where nobody is ahead of the child
holding it.

Hardcoded for now. It may reasonably become a per-school setting, and
`dense_positions()` is the single place it is decided — a school switching to
standard competition ranking changes one function and no caller.

## Ties are an equality test, so the type matters

Positions are decided by two children having **the same** score, and that makes
this one of the few places where `Decimal` versus `float` changes a number
somebody reads. Float equality on a computed percentage turns on the last bit;
the visible symptom is two children printed with identical percentages and
different positions, which no teacher can explain to a parent.

So percentages are `Decimal`, and **ranking compares the value as printed** —
quantised to two places *before* anything is sorted. Ranking on the unrounded
value and printing the rounded one is the same bug wearing a different hat:
75.004 and 74.996 both print as 75.00 and would be given different positions.

`45/60` and `15/20` are both `75.00` by different arithmetic, and there is a
test that they share a position.

### The rounding mode is stated, not inherited

`Decimal.quantize(PLACES)` with no `rounding=` does not mean "round normally".
It reads `decimal.getcontext().rounding`, whose default is `ROUND_HALF_EVEN` —
banker's rounding, where **74.505 goes down to 74.50** and 75.505 goes down to
75.50. That is not what a Nigerian report card does, it cannot be explained to a
parent standing at a grade boundary, and because ties are decided on the
quantised value it silently decides *positions* as well as printed numbers.

Two further reasons it could not be left implicit:

- the context is **thread-local and mutable**. Any library in the process
  calling `decimal.setcontext()` would change every percentage and every
  position on the platform, with no change to this code and no test failing
  anywhere near the cause;
- a module whose whole argument is that this number is exact cannot outsource
  the last step of computing it to ambient state.

So `ROUNDING = ROUND_HALF_UP` is named once, `_round()` is the only function
that quantises, and there is a test that forces the context to `ROUND_DOWN` and
asserts the answer does not move.

### Naming the rounding mode was not enough

The first version of this stopped there, and said in a comment that the module
no longer depended on ambient state. It still did. **A context carries a
precision as well as a rounding mode**, and `prec` is thread-local and mutable
in exactly the same way. Set it low and two things break, in order:

- the **divisions** lose their significant digits first. At `prec=3`,
  `6101 × 100 / 10000` comes back `61.0` rather than `61.01`, so the percentage
  is already wrong before any rounding decision is reached;
- `quantize()` then raises **`InvalidOperation`**, because 74.51 needs four
  digits and only three are allowed. That is not a wrong number on a card, it is
  a 500 on every broadsheet on the platform, caused by a library the results
  code has never heard of.

So the whole calculation runs in `CONTEXT = Context(prec=28, rounding=ROUNDING)`
rather than in whatever the caller left set. 28 digits is CPython's own default,
so this changes no number that was ever printed — what it removes is somebody
else's ability to change them. The control is in the table below and it fails
with `decimal.InvalidOperation`, which is the point: the guarantee the docs
claimed and the guarantee the test pinned were not the same guarantee until
this landed.

## "Not marked" is not zero, in the arithmetic as well as the table

`gradebook` keeps the distinction by having no `Score` row at all. This module
has to keep it in the ranking:

- a child with no marks in a subject has **no position** in it, not the last one;
- a child with no marks at all has no overall position and no average;
- an unmarked child does **not** drag the class average down.

Ranking them last is a specific lie — it says the school assessed them and they
scored nothing. A child off sick for the term, or one who joined in week ten,
would be printed bottom of the class on a card that goes home.

The control run for this is in the table below and is worth reading: the naive
"treat missing as zero" fix moves a class average from 80.00 to 40.00.

## Two averages, and they are different questions

**The child's own average** is the mean of their subject percentages. It is what
a report card shows and what class position is ranked on.

There are two defensible readings of "average across their subjects" and they
disagree:

|  | Maths 10/10 | English 40/80 | result |
| --- | --- | --- | --- |
| mean of subject percentages | 100% | 50% | **75.0%** ← this |
| total scored ÷ total available | | | 55.6% (50/90) |

The first is what the phrase means on a Nigerian card, and it is the one that
does not let a subject with a large `max_score` quietly outweigh the rest of the
term. The second is a weighted average pretending not to be one.

**The class average** is the mean of those, across the class. It is
**computed on demand and never stored**, and the asymmetry with position is the
point:

| | frozen at release? | why |
| --- | --- | --- |
| position | **yes** (task 3) | it depends on everyone else's scores *at that moment* and cannot be recomputed later without changing |
| class average | **no**, recomputed | a stored copy is a fact about forty-five other children, and a later revision to any one of them leaves a released card carrying a number that disagrees with the rows it claims to summarise |

## Position is staff-only, and that is a rule about payloads

> Nigerian secondary schools do not print position on report cards. Parents and
> students see the cumulative average only. Schools use it internally.

Visible to **teachers, the academic vice principal, principals and school
administrators**. Not to parents, not to students — and not to a bursar, who
keeps the books. The class average is staff-only on the same reasoning.

Enforced at the **router**, which is the earliest point available, because the
failure mode is not a template. Omitting a field from a card while the JSON
still carries it is the same leak with an extra step, and the way that happens
is a family-facing view reusing a schema written for staff. There is no schema
in `results/api.py` a family-facing route could reuse.

Refusals are a **flat 404**, not a 403, on the reasoning `gradebook.api`'s
`ExistenceOracleTests` settled: a parent who could tell "you may not read this"
from "no such class" could map the school's whole class list by walking ids.
Both answers are the same bytes, and the authority check runs before the class
or term is looked up so the refusal cannot depend on whether they exist.

Two refusals come from **other layers**, and the tests say so rather than
implying this view is the only gate:

- an **unauthenticated** caller gets 401 from the router's `session_auth`, which
  answers before the view. No oracle either — it comes back whether or not the
  class exists.
- **another school's principal** gets 403 from `SchoolAccessMiddleware`, at the
  door, before routing.

### What is not yet proven

The decision says position must be absent from the parent card and the
unauthenticated result-checker payload. **Neither surface exists**, so today the
rule holds by there being no family-facing payload at all — a weaker guarantee
than it sounds, and one that becomes false the moment either lands. Tracked as
[issue #21](https://github.com/adedejimakinde/luffy-school-saas/issues/21),
which carries what has to be true when they do. Building a placeholder now would
mean building it against live tables, which task 6 is explicitly forbidden from
doing.

## Live marks before release, the snapshot after

**An unreleased term reads live `Score` rows**, and there is a test asserting a
new mark changes a rank immediately. It has to: a teacher who could not see
their own marking on this page would be reading a stale sheet all term.

**A released term is served from the frozen cards.** This section used to end
"once task 3 lands, a released term must be served from the snapshot instead",
and the endpoint's own docstring made the same promise. Task 3 shipped in #44
and the switch was not made, which is
[issue #55](https://github.com/adedejimakinde/luffy-school-saas/issues/55): the
two rankings then drifted apart in production shape, because marks lock at
release but the **roster does not**. A child placed into a released term (#31)
made this page rank forty-six children while all forty-five frozen cards still
said forty-five, and nothing in the data said which page was current.

### The page derives its ranks; it does not read the frozen ones

For a released term, `current_rank` is `dense_positions()` over the cards'
frozen `own_average` values, and `class_average` is `mean_percentage()` over
those same numbers. Both are therefore facts about the rows being displayed.

**It is deliberately not `ReleasedCard.position`.** That field records where the
child came *at that card's own freeze*, and a revision re-freezes one card
against the class as it reads at that later moment. Read forty-five such numbers
off forty-five cards and one page can show two children at rank three, or nobody
second — the numbers were never computed against one roster.
`TheRevisedChildTests` asserts a page rank and a stored `position` disagreeing,
with both values written out, because they are two correct answers to two
different questions.

### The field is named `current_rank`, not `position`

The response used to call it `position`, which made three meanings of that word
in one codebase — the rank in the class, the rank in a subject
(`subject_position`), and *where a line prints*
(`ReleasedSubjectResult.position`). The broadsheet's fields are now
`current_rank` and `current_subject_rank`, and `from_snapshot` says which of the
two questions above the page answered. Nothing in the repository consumed the
old names; a released page and a live one are otherwise the same shape saying
different things, which is what `from_snapshot` exists to prevent.

## One read of the marks for the whole page

The first version of the broadsheet asked the database separately for every
number a row needs: the roster, then each subject's percentages, then each
subject's positions, then the averages, then the class average. Twelve subjects
and forty-five children came to fifty-odd round trips for one page.

The cost is the smaller half. **The correctness is the point.** `gradebook`
saves one mark per cell-blur, so a teacher marking while a HOD reads the
broadsheet is the ordinary case, not a race worth discounting. Under
`READ COMMITTED` each of those queries sees a different moment, so a single mark
landing between the percentage read and the position read produces a row showing
`88.00` in **1st** place above a row showing `91.00` — the same "identical
percentages, different positions" failure this module was written to prevent,
arriving by a route the `Decimal` argument does not cover.

`positions.class_results()` now does one roster read and one aggregate read, and
derives everything else in Python, so every number on the page comes from one
instant. The observable proxy in the tests is the query count: a page whose cost
does not grow with the number of subjects is a page that is not re-reading per
subject. Two subjects and eight subjects are asserted to cost the same, stated
as a comparison rather than a fixed number so an unrelated query elsewhere does
not fail the test while the per-subject loop coming back still does.

**The residue is stated rather than papered over.** The roster is a second
query, so a child placed between the two reads appears on the sheet with no
marks and renders blank. Closing even that would need `REPEATABLE READ`, which
cannot be set inside the transaction `TestCase` wraps every test in.

### The columns are the subjects the class was marked in

Drawn from the marks, not from `Subject.objects.all()`. The subject table is per
school and deliberately keeps retired subjects — `Subject.is_active` reads *"a
subject no longer taught. Kept, because old scores name it"* — so ranging over
all of them puts an all-blank Technical Drawing column on a class that has not
been taught it for three sessions, beside every subject the school teaches to
any other year group. The aggregate already knows which subjects have marks.

Ordering is `Subject.Meta.ordering`, which is `["name"]`, so the columns stay
alphabetical rather than falling into primary-key order.

## The roster is bare integers, so the name lookup is narrow

`ClassPlacement.student_membership_id` points into the shared `public` membership
table with **no foreign key and no database integrity** — the policy
`docs/tenancy.md` settles for every cross-schema reference in this project, and
the one `fees.FeeLedgerEntry` and `gradebook.Score` already follow.
`academics.services.place_student()` checks the id names a student of this
school, but that check runs **at write time and is the only thing standing
there**. A row that arrived another way — a bad import, a data migration, a hand
edit — carries whatever id it was given.

So the broadsheet must not assume its own roster. `_named()` looks memberships up
scoped to this school and to `Role.STUDENT`, on the reasoning
`gradebook.api._student_here()` sets out: a membership at another school is *not
found* rather than found and then trusted. Looked up unscoped, one such row puts
another school's child's **real name** on this school's sheet — a cross-tenant
disclosure produced by a read, from a view behaving correctly in every other
respect. The control below shows the payload it produces.

The row is rendered **blank, not dropped**. It is still on the roster and still
wrong, and a sheet that hides it hides the corruption too; a dash is the same
answer an unmarked child gets, and it is one a school can see and ask about.

## Control experiments

The method as ever: break one thing deliberately, re-run, read the failure.

| Broken | Result | What it proved |
| --- | --- | --- |
| dense ranking → standard competition ranking | `{1: 1, 2: 2, 3: 2, 4: 4} != {1: 1, 2: 2, 3: 2, 4: 3}` | the tie rule is actually asserted, not assumed |
| `_percentage(0, 0)` returns `Decimal(0)` instead of `None` | only **one** of four "not marked" tests failed | the first control was in the wrong place — `overall_percentages()` never calls it for a child with no rows at all. A passing control is information too. |
| unmarked children given an average of `0` in `overall_percentages()` | three tests fail; the class average moves **80.00 → 40.00** | the plausible wrong version *is* caught, and the cost of getting it wrong is a number on every card in the class |
| `Role.PARENT` added to `POSITION_VIEWING_ROLES` | parent gets `200` with the rank and `"class_average": "74.50"` in the body | the visibility rule is enforced where the tests say it is |
| the released-term branch removed, so a released term keeps reading live marks | `FAILED (failures=10)` | every claim in this PR rests on that one dispatch; nothing else in the module compensates for it |
| `current_rank` read off `ReleasedCard.position` instead of `dense_positions()` over the frozen averages | `FAILED (failures=2)`, both in `TheRevisedChildTests` | the derivation is what those two tests pin. The other eight pass either way, because a class frozen together agrees with itself — which is why the revised child is the case that had to be written |
| `class_average` recomputed by `class_results()` from live marks | `FAILED (failures=1)` | the number beside the rows is the mean *of* the rows, not a second answer that happens to sit next to them |
| the columns taken from `Subject.objects` instead of the cards' frozen lines | **`OK`. 28 tests, nothing broke.** After the missing tests: `FAILED (failures=2)` | the whole subject half of a released page was documented and asserted nowhere, so `TheColumnsAreTheFrozenSubjectLinesTests` had to be written before this control could say anything. Issue #55 |
| `current_subject_rank` read off `ReleasedSubjectResult.subject_position` | `FAILED (failures=1)` | the per-subject rank is derived for the same reason `current_rank` is, and now has the revised-child case to prove it |

**Two rows here passed, and both times the pass was the finding.** The
`_percentage(0, 0)` control broke three tests fewer than it should have, which
said nothing about the code and everything about where the control was aimed —
the naive-zero bug lives in the aggregation, not in the percentage helper. The
`Subject.objects` control broke nothing at all, because the columns, their
frozen names, their print order and `current_subject_rank` were carried by
docstrings and by no test: the same failure this endpoint's own docstring had
already committed, one paragraph up. An unasserted docstring is an open
question, not a description.

A control that fails to break anything is a result, not a formality.

### The self-review round

Four more, run against the three fixes above. Two of them landed; the other two
passed, and both times the passing control was the finding.

| Broken | Result | What it proved |
| --- | --- | --- |
| `_round()` quantises with a bare `.quantize(PLACES)`, inheriting the context | **4 of 4** rounding tests fail, every one `Decimal('74.50') != Decimal('74.51')` | the rounding mode is asserted rather than commented, including the test that forces the context to `ROUND_DOWN` |
| subject positions re-read the marks, once per subject | `10 != 2` on eight subjects, and the growth test `10 != 4` | the one-read property is pinned by query count, and the per-subject loop cannot come back unnoticed |
| `class_average()` re-derives the mean itself with a bare `.quantize(PLACES)` | **passed — 4 tests, OK** | the test was aimed one level too low. Re-aimed, the same break fails it `74.50 != 74.51` |
| columns come from `Subject.objects` instead of from the marks | unit test fails `[1, 2, 3] != [1]` — but **all 16 API tests passed** | the unit was pinned and the payload was not. A new API test now fails the same break with `[2, 1, 3] != [1]` |

**Row three is the naive-zero lesson again, one level up.** A class average is
the mean of the children's *already-rounded* averages, so a single child
averaging 74.505 has it quantised to 74.51 before the class mean is taken: the
mean is then 74.51 exactly and both ways of computing it agree, however either
one rounds. The test asserted a real property of a case that could not exhibit
the bug. It takes **two** children — 74.50 and 74.51, mean 74.505 — to put the
half at the level `class_average()` rounds at.

**Row four says where a test lives matters as much as what it asserts.** The
break was caught by the positions unit test and by nothing in the API module,
which meant the thing a school actually receives — the JSON — was unpinned. The
column list is a property of the payload, so it is now asserted on the payload.

Both are the same shape as the naive-zero row above, and worth the repetition:
a control that fails to break anything has found something, and what it has
found is in the test.

### The code-review round

Two more, from the review of the branch. Both were low severity and both were
worth fixing, because each is a failure only a second school or a second thread
can produce.

| Broken | Result | What it proved |
| --- | --- | --- |
| `_named()` looks memberships up unscoped again | the response body carries `"student_membership_id": 20, "student": "Chika C"` — Grace Academy's child, named on St Mary's sheet | the narrow lookup is what stops a corrupt roster row becoming a cross-tenant disclosure, and the assertion is on the bytes rather than on a flag |
| the arithmetic runs in the ambient context again | `decimal.InvalidOperation` at `prec=3` | the exposure was a 500 on every broadsheet, not a wrong number, and the old comment claimed a guarantee no test held it to |

The second is the more instructive. The comment already said the module did not
depend on ambient state; it was true of the rounding mode and false of the
precision, and nothing failed, because the test varied only the half the comment
had got right. A claim in a docstring is not pinned until a control tries the
part of it nobody thought about.

## `.order_by()` on the aggregate, again

`_subject_totals()` clears ordering before `.values().annotate()`, and it is
load-bearing. `Score.Meta.ordering` is `["assessment", "student_membership_id"]`,
and Django appends ordering columns to the `GROUP BY` — so without it the rows
come back grouped by assessment as well, which is one row per mark and a "total"
that is just the mark. `gradebook.api._totals_for_everyone()` carries the same
note. Same bug, third app.
