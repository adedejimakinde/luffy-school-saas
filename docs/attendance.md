# Attendance

Status: draft. Structural decisions settled (D1–D13) against the repository. **A1 is
stated from domain knowledge and not school-confirmed**; A2 and A3 have not been put to
a school and the questions are drafted and waiting to be sent; A4 is settled from this
repository and needs nobody. A4 is settled from this repository and needs nobody. Extends
`docs/results.md` and `docs/tenancy.md`. Supersedes nothing.

Phase 2, weeks 10–13. Note that "Phase 2" is overloaded in older working notes, where
it names the fees and withholding work that is already closed. The forward references
in `results.ReleasedCard`, `report_card.html` and `static/web/html.js` — all three
saying attendance is "nullable until Phase 2" — mean *this*.

## What this is

A school keeps a register. This document settles what a register is in the system, who
may take one, how a term's registers become the three numbers on a report card, and
what happens to those numbers when a card is revised.

It deliberately does not cover: lateness arithmetic, per-subject truancy reporting, or
notifying a parent that a child did not arrive. Those are later and none of them is
blocked by what is decided here.

## Domain assumptions

Written in the form `docs/parent-access.md` established: each is an assumption until a
school confirms it, ✓ marks *one school said yes* and nothing more, and the conditional
clauses stay after confirmation because they are what the next school is checked
against.

### Stated from domain knowledge, not school-confirmed

- **A1. Attendance is marked per day, not per period.** A Nigerian secondary school
  takes one register for a class each day; subject teachers do not each keep one that
  the report card counts. **Stated by the project lead from their own knowledge of
  Nigerian schools, September 2026. Not confirmed by the school**, and the distinction
  matters — this is the same standing as A8–A10 in `docs/parent-access.md`, which are
  researched rather than confirmed, and weaker than the ✓ items there. *If this is
  wrong and subject teachers each mark their own period, attendance needs to know who
  teaches what — and no subject-teacher table exists; `academics.ClassTeacher` is one
  teacher per group per term and is the only teaching assignment in the system. That is
  a prerequisite change, not a detail.*

  A1 arrived **after** slice 1 was built, and D4 and the schema were amended to match
  rather than left carrying structure for a practice nobody has.

### To be put to the school

- **A2. A school keeps more statuses than present and absent — at least late, and
  probably excused — and only some of them count as present on the card.** *Not
  confirmed.* The status list is cheap to extend; **which statuses count toward
  `days_present` is not**, because it is arithmetic on a number a parent reads. A child
  marked late forty times reading "62 of 62 days" is a card that lies by rounding, and
  a child marked excused for a funeral reading as absent is a different lie. The school
  decides, and until it does D11 keeps the minimum.
- **A3. Schools differ enough on A1 and A2 that this has to be configurable.** *Not
  confirmed, and deliberately assumed false until it is.* `ReportCardSettings` earns
  its flags by schools genuinely differing; the repository's own rule is that a knob
  nobody turns should not exist. One school's practice is not evidence of variation —
  it is evidence of one practice.

- **A5. A teacher may need to take the register of a class they are not answerable
  for.** *Not confirmed, and the system currently assumes true by omission.*
  `can_mark_attendance()` is school-wide: any TEACHER at the school may take any
  class's register, with no reference to `ClassTeacher`. Results submission is
  scoped precisely because of issue #25 — "a JSS 1A teacher could submit JSS 3B's
  results and be recorded as the signatory of a class they do not teach" — and
  attendance has the same shape and no equivalent scope.

  It was invisible until there was a screen. Slice 3's register screen has to show a
  teacher a list of classes, and with no scope that list is every class in the
  school. The screen ships the honest list rather than narrowing it, because a
  restriction enforced only by a screen is the defect class this phase keeps finding.

  The case that decides it is ordinary: **a subject teacher covering an absent form
  teacher.** Scope marking to `ClassTeacher` and the cover teacher cannot mark the
  class standing in front of them, and the workaround is a borrowed login — strictly
  worse, because `taken_by_id` then names the wrong person on every row it touches.
  That is the same argument `MARKING_ROLES` already makes for admitting principals
  and administrators.

  Three options, not two: leave it school-wide and say so as a decision rather than
  an omission; scope it with an explicit cover mechanism; or keep the write open and
  make who-marked-what legible, which `Register.taken_by_id` already supports with no
  new authority rule. **Issue #125**, and it wants a pilot-school answer rather than
  a repository one.

### Settled from this repository, and needing no school

- **A4. "No register was taken" is not "the child was absent", and the two must never
  collapse into one number.** ✓ settled. `results.TermAbsence` already made this
  decision for session averages, and made it in these words: collapsing the causes into
  a bare `None` "would make a marking backlog look exactly like a mid-session
  transfer". The same conflation here would report a school's own admin gap as a
  child's truancy, on a card that goes home to that child's parents. D5 is the
  structural consequence and it is not contingent on any school's answer.

### Which decisions survive a wrong assumption

| If this is wrong | These hold | These break |
|---|---|---|
| A1 marked per day | D1–D3, D5–D12 — the register, its keys, the freeze, the revision rule and the app are all indifferent to who marks and how often | **D4**, and D11's actor. The `period` column comes back and the rollup rule is written *with* it, as one change — re-adding is lossless, because under a once-a-day practice every existing row carries the value the column would default to. A subject-teacher table this repository does not have is the expensive half, not the column |
| A2 more statuses | D1–D10 entirely | **D11** only, which is why D11 is the minimum rather than a guess. Adding a status is a `TextChoices` entry and a migration; changing what counts as present is a change to one function, `day_status()` |
| A3 practice varies | all | nothing is built, so nothing breaks. This is the assumption it is cheapest to be wrong about, and only in that direction: shipping the knob first and finding nobody turns it is the expensive mistake |
| A4 unmarked vs absent | — | nothing. A4 is not a claim about schools. If a school genuinely does not care to tell the two apart it can ignore the third number; the system still must not invent one |
| A5 any teacher may mark any class | D1–D12, and the screen — nothing built assumes the wide rule is *right*, only that it is what the route enforces | the class chooser's list, and one test that asserts it is wide and says so. Narrowing is a service-layer change with its own controls, plus a cover mechanism, because the borrowed-login workaround is worse than the gap |

## Decisions

### D1. A register is its own row, and the marks hang off it

Two tables, not one.

`Register` is the fact that somebody took a register: this group, this date, this
period, taken by this person. `AttendanceMark` is one child's entry in it.

One table keyed on `(student, date, period)` cannot tell the difference A4 says must
never be lost. A day with no rows for a child is then ambiguous between "nobody took a
register" and "a register was taken and this child was somehow skipped", and the
ambiguity is unresolvable after the fact. With the register as a row, absence of a
`Register` means nobody marked, and a `Register` with a child missing from it is a
different and detectable fault.

This is also the shape the codebase already uses twice for the same reason:
`ResultSheet` exists before any `Score` hangs off it, and `ReleasedCard` exists before
any `ReleasedSubjectResult` does.

### D2. The register carries the class group, and does not look it up

`academics.ClassPlacement` is **current state, not history**.
`services.move_student()` mutates `class_group` on the existing row and saves it;
`remove_placement()` deletes the row outright; and
`one_class_placement_per_student_per_term` is the constraint that forces that shape.
A child who moves from JSS 1A to JSS 1B in January leaves nothing behind saying where
she sat in November.

So the group is stored on the `Register` row at the moment the register is taken.
Resolving it through `ClassPlacement` at read time would file that child's first-half
attendance under her second-half class, and would do it silently, months later, to a
number already printed on a card.

`ClassPlacement` is still exactly the right read for *whom to show the teacher* when
the register is being taken. It is the wrong read for what a register meant afterwards.

### D3. The term is stored on the register, not derived from the date

A term's dates are `starts_on` and `ends_on`, and **nothing prevents two terms
overlapping**: the constraints on `Term` are that a term ends after it starts, that
the next term begins after this one ends, and that `school_days` fits inside the span.
None of them makes a date resolve to exactly one term. Deriving the term would be a
range query per read that is also not guaranteed to give one answer.

It is stored, and the summary in D6 groups on it.

### D4. Store by period, show by day — and the rollup is one named rule

The roadmap's phrasing, and it is two separable things.

*Storage* is per period because grain cannot be retrofitted onto history. A school
that decides in year two that it wants per-subject truancy cannot recover period-level
detail from day-level rows, whereas rolling periods up to days is arithmetic. The
period is a **small ordinal on the register row, not a foreign key**: nothing in this
repository models a school day, a period, a timetable or a lesson, and this phase does
not build one.

*Display and the card* are per day, which needs a rule, and the rule is a decision
rather than an implementation detail:

> **A day takes the status of the earliest register taken that day.** Later periods
> are stored and do not change the day's verdict.

That is what paper does — the morning register is the day — and it is what makes the
card's number agree with what the form teacher remembers. It lives in one function so
that A1's answer can overturn it cheaply. A child present at assembly and gone by
period five reads as present for that day under this rule, knowingly; the periods that
say otherwise are stored and available to the view in slice 4.

### D5. Three stored fields, because the remainder is a real quantity

`days_present`, `days_absent` and `days_open` are all kept, and `days_absent` is
**not** derived as `open − present`.

Once A4 holds, the three are not redundant. `open − present − absent` is the number of
days the school opened and took no register at all for this child — the school's own
admin gap, and a quantity it is entitled to see rather than have silently folded into
its pupils' absence. Deriving `days_absent` would make that remainder unrepresentable
and would state, of every unmarked day, that the child was away.

`days_open` is `Term.school_days`: the count **the school declares**, already modelled,
already constrained to be at least one and no more than the term's calendar span, and
already documented as not computable from dates because mid-term break, moveable public
holidays and unplanned closures all come out. This phase does not recompute it. It does
have to give it a door — see the slices, and the open question below.

### D6. The summary is an argument to the card freeze, not a fifth freeze module

The three fields are columns on `ReleasedCard`, and `ReleasedCard` is append-only at
two layers: the `save()` guard raising `CardsAreFrozenAtRelease`, and `0018`'s
`BEFORE UPDATE OR DELETE ON results_releasedcard` trigger. **They can only be filled on
the INSERT.**

So attendance does not follow `ratings`, `comments` and `sessions`, which write their
own tables after the cards exist. It follows `positions.ClassResults`: read once at the
top of the locked block in `results.services.release()`, passed *into*
`cards.freeze_for_release()`, consumed by `_card_for()`. That is the shape issue #60
already forced for the same reason — one read, one instant, handed down rather than
asked for twice.

### D7. A revision carries attendance forward from the card it supersedes

`freeze_a_revision()` shares `_card_for()` with the release path, so the default
behaviour would be to recompute attendance from live registers at revision time. That
is wrong, and it is wrong in the quiet way this codebase keeps finding: a March
revision fixing a comment typo would silently restate the attendance numbers a parent
read in December, every value individually legal and nothing objecting.

A revision copies the three fields from the card it supersedes. If attendance itself is
what needs correcting, that is an **explicit input to the revision** — the caller says
so and the audit row records it — not a side effect of fixing something else.

This gets its own control: amend a register after release, revise the card for an
unrelated reason, and assert the revised card's three numbers equal the original's. The
control makes the revision recompute, and exactly that test reddens.

### D8. Marks are mutable; the card is the artefact

No append-only trigger on either new table. A teacher who marks a child absent and then
watches her walk in must be able to fix it, and a register corrected on the day is a
register, not a falsified record. What must not move is the card, and the card does not
move: D6 freezes the numbers into an append-only row and D7 stops a revision from
disturbing them. The snapshot is where immutability belongs, which is the rule
`docs/results.md` already sets for every other section.

### D9. Its own tenant app, `attendance`

Tenant-local, like `academics`, `fees`, `gradebook` and `results`. It gets its own app
on the reasoning `settings.py` already gives for separating those four: different
readers, different schedules. A register is taken every morning by a form teacher and
is stale by lunchtime; a bursar's ledger, a teacher's mark sheet and a published card
are none of those things, and neither should have to migrate because attendance
changed.

`student_membership_id` is a bare `PositiveBigIntegerField`, not a `ForeignKey`, per
the policy in `docs/tenancy.md` that `fees.FeeLedgerEntry`, `gradebook.Score`,
`academics.ClassPlacement` and `academics.ClassTeacher` all follow. Unlike those,
the register service does **not** check the id with
`accounts.students.why_not_a_student_here()`, and that is the decision rather than
an omission: `take_register()` writes only ids that survive intersection with the
roster, and the roster is `ClassPlacement`, whose rows `place_student()` already
checked. An id that is not a student of this school cannot reach a mark, which is a
stronger guarantee than a check, and it is why `not_on_the_roster` is a report
rather than a refusal. (This paragraph used to say the service made the check. The
code never did; `attendance/services.py` says why.) `class_group` and `term` are
real foreign keys, because both are tenant-local.

### D10. Default present, mark the exceptions, submit once

Forty-five students in under thirty seconds is two thirds of a second each, which
rules out a screen where every child is touched. It also rules out the write pattern
this codebase currently has: `gradebook.save_score` is one mark per request — "what a
blur calls" — and forty-five conditional PUTs on a phone is not a register, it is a
network test. **There is no bulk-write endpoint anywhere in this repository yet**;
attendance adds the first one.

So the register opens with the roster present and the teacher taps the absentees. The
payload is the exceptions plus the roster the screen was showing, and the server writes
marks for the roster it reads under the lock. The roster the screen showed and the
roster at write time can differ — a child placed or moved in between — so the request
carries what it was taken against and the response names any drift rather than
silently marking a child nobody looked at, or silently dropping one.

**Sending a register twice amends it twice, unless it carries a `key`.** Harmless
while nothing happens in between; not harmless when a register queued at 8am, whose
answer was lost, is sent again at 4pm after the office corrected it at 10am. The
second copy would put every corrected absence back. With a `key` the first arrival
leaves a `sync.SyncReceipt` in the same transaction as the marks, and the second is
answered with what the first did and writes nothing (`docs/offline.md` D3,
`sync/tests/test_replay.py`).

### D11. The minimum status set, and why it is not a guess

`PRESENT` and `ABSENT`, and nothing else, until A2 comes back.

This is not a prediction that schools keep only two. It is the observation that adding
`LATE` or `EXCUSED` is a `TextChoices` entry and a migration, while **deciding whether
late counts as present is arithmetic on a parent-facing number** — and that decision
cannot be made well by guessing. Shipping four statuses now means shipping a guess
about the card's arithmetic and discovering it was wrong after cards have gone home.

The third state is structural rather than a status: a child with no mark in a register
is unmarked, and a day with no register is unmarked, and D5 keeps the count of them.

### D12. `school_days` gets a service function and a route, and no screen

`Term.school_days` has a column, three constraints and a paragraph of
documentation, and **no writer**: no admin, no form, no route, no service
function. Today it is reachable only from the ORM, which means slice 2 could
compute present and absent perfectly and still print nothing, because
`days_open` would be null on every card.

The door is `academics.services.set_school_days(term, count, by=actor)` plus an
API route, admin-only, with the authority shape the other `academics` services
already use — a `can_*` predicate, a `_require_*` raiser, and a `*_as(actor, …)`
wrapper, so that authority is asked at the school and the write is pinned to the
schema. `PLACEMENT_ROLES` is the nearest precedent and the right shape:
declaring how many days a term taught is an office act, not a teacher's.

**The route deliberately has no page, and nobody should assume one.** There are
no staff screens anywhere in this project yet, and inventing one here would drag
slice 2 into the staff-UI problem slice 3 already has to solve — which is the
same problem, once, rather than twice in two shapes. The screen comes when staff
pages exist. Until then this value is set by a route, and a school that has not
had it set sees the blank card it already sees.

*Since written: the staff sign-in page has landed and this is still true. That
page is a door and a receipt, not a hub — it holds no school's data and has no
screen to hang `school_days` on. The first staff screen is slice 3's register.*

It lands in **slice 2**, with the rest of the work that makes `days_open` mean
something. It is named here rather than in the slice list because it is a
decision about a door, not a step.

### D13. What the card shows, decided once, on the server

The case that settled this is a term where the school declared `school_days` and
nobody ever took a register: present 0, absent 0, every day unmarked. **"Present
0 out of 62 days" is a false accusation against every child in the class.** It is
exactly the failure A4 prevents in the schema, arriving through the renderer
instead — and it would have shipped, because the renderers' whole defence
against "no register was kept" was `days_present === null`, and this slice makes
that column a real count that is never null. The defence stops working precisely
when the data starts existing.

**The rule: the denominator is only ever the days actually marked.** The school's
declared term length is context and never a divisor, because dividing by it
invites subtracting from it and reading the remainder as absence.

| state | when | what both renderers print |
| --- | --- | --- |
| `ABSENT` | all three columns null | nothing — no number, no dash-with-denominator |
| `NOT_RECORDED` | `present + absent == 0` | "Not recorded this term" |
| `PARTIAL` | some marked, some not | "38 present, 2 absent (register kept on 40 of 62 days)" |
| `COMPLETE` | `marked >= school_days` | "Present 58 of 62 days" |

`COMPLETE` is the roadmap's target line, and it is printed **only** when every
declared day was marked — which is what makes the sentence true when it appears.
A child absent on all 62 days of a fully marked term reads "Present 0 of 62
days": `0` is a real measurement and this is the one state in which that string
is honest. The nought-versus-null care the renderers already had does not go
away; it moves from `null` to `marked == 0`, which is the signal that survives
the columns being populated.

A `PARTIAL` term whose school never declared a length prints the counts and no
parenthetical — there is nothing to have kept the register *of*, and gating the
whole line on the denominator would throw the observed half away.

**Neither renderer decides which state it is in.** `card_api.attendance_of()`
answers once and both format. This is true by construction rather than by a test
holding two branches together: `pdf.html_for()` renders from `card_payload()`,
which is the same function that builds `ReportCardOut` for the page. They
diverged once already — the page keyed on `days_present` while the template
keyed on `days_open` — and it was invisible only because the columns were always
null.

## What is configurable, and what is not

**Not configurable, deliberately:** that the school declares `school_days` rather than
the system computing it (already settled by `Term`); that unmarked is distinct from
absent (A4); that a revision carries attendance forward (D7).

**Not configurable yet, pending A3:** which statuses count as present. It lives in one
function so that the cost of being wrong is a function body, not a schema. The rollup
rule used to sit beside it here; under A1 it is a constraint instead, and a constraint
is deliberately not configurable.

**No settings row is added in this phase.** `ReportCardSettings` is where a flag would
go if A3 comes back yes — it is already the per-school singleton for how a school
handles report cards, and one boolean does not earn a third settings table.

## The slices

1. **The register data path.** The two models, their constraints, the migration, the
   service layer, the roster read and the bulk-write endpoint. No page, no card.
   **Built, then amended**: A1 landed after it and took the `period` column and D4's
   rollup rule with it.
2. **The summary and the freeze.** `Term.school_days` gets a writer — D12, a service
   function and a route with no page; the summary
   function; `cards.freeze_for_release()` gains its argument; D7's carry-forward and
   its control. Both rendering defects are fixed here, where they first become
   visible: `static/card/render.js` branches on `days_present` while
   `results/templates/results/report_card.html` branches on `days_open`, so the page
   and the PDF disagree for a card with a term length and no register; and
   `days_absent` is stored, served on `ReportCardOut`, and rendered by neither.
3. **The register screen. Built.** `/register/` on a school's host, in front of the
   endpoints slice 1 built, with `GET /api/attendance/where/` added because the
   register is keyed on `(class_group, term, date)` and the API named none of the
   three. It also settled what the sign-in slice deliberately left open — where a
   member of staff goes after signing in. `SignedInOut.schools` now carries
   `may_take_a_register` and `has_children_here`, each being the **same question
   the surface behind the link asks** rather than a role standing in for one, and
   the landing draws a link per school from them. The guardian flow's link rule
   got its second caller and is `hostHref()` in `static/web/html.js`. The screen
   itself is [register-page.md](register-page.md); where staff come from is
   [sign-in-page.md](sign-in-page.md).
4. **The principal's view. Built.** `/absences/` on a school's host, over
   `GET /api/attendance/absences/?term_id=` (the school's current term when none is
   given) and `PUT /api/attendance/absences/threshold/`. OPEN-2 is answered below.
   The list is every child placed in the term whose absent share of **marked** days
   is at or over the school's threshold, once the child has at least the school's
   floor of marked days, worst first; `attendance/absences.py` holds the rule. It is
   one aggregate over the term's marks (`summary.for_term()`), so a child who moved
   class mid-term is counted across both classes' registers and listed under the
   class she is in now — correctness requirement 2 is about which group *took* a
   register, and this list does not say. The answer carries `registers_taken`, so an
   empty list says either "nobody is absent that often" or "no register has been
   taken this term", never the first when the truth is the second. The landing links
   to it from `may_see_absences`, the same predicate the route asks.

## Correctness requirements

1. **A day with no register is not an absence.** The summary's three numbers must
   satisfy `present + absent ≤ open`, with the shortfall being unmarked days. A test
   asserts the remainder for a term where registers were taken on some days only.
2. **A moved child's history stays where it happened.** Mark a register, move the child
   to another group, and the earlier marks still report under the group that took them.
   The control resolves the group through `ClassPlacement` and this test reddens.
3. **A revised card's attendance is the superseded card's.** D7's control, above.
4. **The frozen numbers do not move when the register does.** Amend a register after
   release; the released card's three fields are unchanged, because the row refuses an
   UPDATE at two layers.
5. **`0` and `null` stay different all the way to the page.** A child present on none
   of the days open reads `0`; a term with no registers reads blank. Both renderers
   already make this distinction and both must still make it, identically, after slice
   2.
6. **A register cannot be taken for a date outside its term.** This one cannot be a
   database constraint — a `CheckConstraint` cannot reference `Term.starts_on` on
   another table — so it is a service-layer refusal with its own name, and the
   documentation says so rather than implying a guarantee the schema does not give.
   The repository has made the opposite mistake before.

## Open questions

- **OPEN-1 is closed.** See D12: a service function and an admin-only route on
  `academics`, no screen, landing in slice 2.
- **OPEN-2 is closed** (decided 2026-09-24). "Too often" is **absent on at least a
  share of the days marked, once a floor of days has been marked** — not a count of
  days, which reads differently in week two and week twelve, and not a share of the
  declared `school_days`, which would count every unmarked day as present (A4 says it
  is neither). The threshold is **the school's own**: `AbsenceSettings`, one row per
  school schema, 10% and 10 marked days until the principal or an administrator
  changes it. The comparison is in integers (`absent × 100 ≥ threshold × marked`), so
  a child exactly on the line is on the list whatever rounding would say. **Who reads
  it:** the principal, the vice principal (academic) and the administrator, for the
  whole school; everybody else gets a flat 404, as for the broadsheet. A class
  teacher's own-class view needs a `ClassTeacher` scope attendance does not have yet
  — issue #125.
- **A5 (raised by slice 3, and it is a *domain* question).** Who may take a class's
  register, and who covers an absent form teacher? Stated in full under Domain
  assumptions above. **Issue #125.**

- **OPEN-3. Does a register need an audit of amendments?** D8 makes marks mutable. A
  register corrected the same morning is ordinary; a register corrected in March for a
  day in November is not, and nothing currently distinguishes them. The card is
  protected either way by D6 and D7, so this is about the school's own trust in its
  register rather than about what a parent sees.
