# Classnode audit, part 2: averages, Ogun card, attendance, CBT banks, fees, transfers

Date: 12 November 2026. Read against `main` at `c2d4b99` (#340).
Findings only. No application code, test, workflow or setting was changed.

Part 1 is `docs/audit/2026-11-security-and-correctness.md`. This part covers the
areas its section 4 said were only skimmed. Findings here are numbered G-01
onwards so they cannot be confused with part 1's F-01 to F-16, and nothing in
part 1 is repeated.

How this was done: the code was read, not run. No test was executed and no
school was created, so every "how to reproduce" is a set of steps or a test
idea that follows from the code path named, not an observed failure. Where a
path could not be followed to the end it says **Needs checking** and what would
settle it. Line numbers are those of `c2d4b99`.

Section 3 says what was traced and found sound. Section 4 says what was still
not read, so silence is not taken for a clean bill.

## 1. Summary

| ID | Title | Severity | Area | File |
| --- | --- | --- | --- | --- |
| G-01 | Moving to a new term empties every class: nothing carries the rosters forward | High | Term change, rosters | `academics/api.py`, `academics/services.py` |
| G-02 | The session line is built from live marks and part-marked subjects, so it can disagree with the term cards and with the card it is printed on | High | Session averages | `results/sessions.py`, `results/positions.py` |
| G-03 | Releasing one class's CBT scores gives out the answers while other classes have still to sit the same paper | High | CBT, answers | `cbt/release.py` |
| G-04 | Promotion moves children with no reference to results or to the principal's decision, and the decision, the weighting and the pass mark have no screen or route | Medium | Promotion | `academics/promotion.py`, `results/sessions.py` |
| G-05 | Graduating or "leaving" a child at promotion locks the family out of the final report card | Medium | Promotion, parent access | `accounts/services.py`, `academics/promotion.py` |
| G-06 | The Ogun card's promotion line is worked out from next term's class, read live | Medium | Ogun card | `results/ogun_card.py` |
| G-07 | On the Ogun card a subject with no paper named "Exam" has no weighted average, no annual score and is left out of the summary | Medium | Ogun card | `results/ogun_card.py` |
| G-08 | The Ogun card's percentage and annual score are not the figures the position and the Standard card use | Medium | Ogun card, rounding | `results/ogun_card.py` |
| G-09 | Choosing the Ogun template while a class is waiting for approval or release changes the conduct section and the position on its cards | Medium | Ogun card, approval chain | `results/ogun.py`, `results/ratings.py` |
| G-10 | A register can be taken, changed or discarded for any term at any time, including after the cards are released | Medium | Attendance | `attendance/api.py`, `attendance/services.py` |
| G-11 | Attendance counts marks, not days: a child who changed class can be counted twice for one day, and a back-filled register uses today's class list | Medium | Attendance | `attendance/summary.py`, `attendance/services.py` |
| G-12 | The dashboard's "outstanding" is this term only; the fee book, reminders and withholding use the whole account | Medium | Fees | `home/facts.py`, `fees/api.py` |
| G-13 | A child moved to another class mid-term stays on the old class's bill and is never charged a line added later | Medium | Fees | `fees/schedules.py` |
| G-14 | Admission numbers are not unique: one-at-a-time admission does not check, nothing in the database does, and the doors match without case | Medium | Roll, IDs | `accounts/enrolment_api.py`, `accounts/models.py` |
| G-15 | A roll file without admission numbers, sent twice, admits every child twice | Medium | Roll import | `accounts/bulk.py` |
| G-16 | There is no way to take a child off the roll mid-session, and the transfer handshake has no route | Medium | Transfers | `accounts/transfers.py`, `accounts/enrolment_api.py` |
| G-17 | Question banks are per subject and class "level", and level defaults to 0, so one bank can span every year group | Low | CBT banks | `cbt/access.py`, `academics/api.py` |
| G-18 | The Ogun card prints attendance with no "not marked" figure, and nothing stops present exceeding the days the school opened | Low | Attendance, Ogun card | `results/ogun_card.py`, `attendance/services.py` |
| G-19 | An absence alert goes out on a mis-tap and for a register entered days late | Low | Attendance, messaging | `notices/absence_alerts.py` |
| G-20 | Small figures: dashboard naira rounding, the Ogun trait total, re-choosing Ogun replaces unmarked papers | Low | Rounding, Ogun | `home/dashboard.py`, `results/ogun_card.py`, `results/ogun.py` |
| G-21 | CBT roles to confirm: the principal approves their own test; classes can be changed after approval | Low | CBT roles | `cbt/setting.py` |

No finding is rated Critical. Nothing was found in these areas that lets one
school read or change another school's data, lets a teacher read a bank outside
the subjects they teach, or sends an answer key to a student's device before
release.

## 2. Findings

### G-01. Moving to a new term empties every class (High)

**What is wrong.** A child's class is a row per term (`ClassPlacement`).
`academics/services.py:385` `carry_forward_placements()` exists to copy one
term's rosters into the next, and `docs/classes.md:100` says that without it
"the first day of every term is a school with no rosters". Nothing calls it.
A search of the whole repository finds the definition and one comment
(`fees/schedules.py:244`); there is no route, no management command and no
button.

`PUT /api/academics/terms/{id}/current/` (`academics/api.py:361-389`) makes the
term current and carries the subject teachers forward
(`gradebook.assignments.carry_forward`), and nothing else. The roll then reads
this term's placements only (`accounts/enrolment_api.py:213-228`), so every
child shows with no class. Until each child is placed again by hand, one at a
time (`enrolment_api.py:334-380`):

- registers refuse with "Nobody is placed in JSS 1A" (`attendance/services.py:250-255`);
- marking sheets, broadsheets and positions have no children;
- a bill applied to a class charges nobody (`fees/schedules.py:186`), and fee
  reminders choose children by this term's placement (`notices/reminders.py:104-108`);
- CBT tests have an audience of classes with no students.

The roll import cannot be used to put them back: it refuses any admission
number already on the roll (`accounts/bulk.py:606-615`), and a file without
admission numbers would admit every child a second time (G-15).

The first-to-second and second-to-third term changes are the ordinary case; the
third-to-first change is covered by promotion only if promotion is run first
(G-04).

**How to reproduce.** One school with a class of three in first term. Create
second term, `PUT .../current/`. `GET /api/enrolment/roll/`: every child's
`class_group` is null. `PUT` a register for the class: 409.

**Who is harmed.** Every school, on the first day of every term: the office has
to re-place the whole school by hand before any teacher can work.

**Smallest safe fix.** In `set_current_term` (the API route, inside its
transaction, beside `assignments.carry_forward`), call
`services.carry_forward_placements(was, term, by=request.user)` when the new
term is in the same session as the old one. It already skips children who have
left and children already placed, and running it twice does nothing. Leave the
third-to-first change to promotion.

### G-02. The session line is built from live marks and part-marked subjects (High)

**What is wrong.** At a third-term release `results/sessions.py:594-677`
freezes each child's three term averages and the session average. Three
things about where those numbers come from:

1. **A different average from the one on the card.** The card's own average is
   `card_averages`, over whole subjects only (`results/cards.py:544`,
   `results/positions.py:447-456`). The session line takes `averages`, which
   includes subjects with a paper unmarked (`sessions.py:427` for the term being
   released, `:429` through `overall_percentages()` for the others;
   `positions.py:303-306` says "partial ones included"). For any child with one
   paper unmarked in one subject, the third-term card prints one average at the
   top and a different "third term" figure in the session line beneath it.
2. **First and second term are recomputed, not read from their cards.**
   `sessions.py:403-431` reads live placements and live marks for the two
   earlier terms. The cards that went home for those terms are frozen
   (`ReleasedCard`), and the session line does not use them. So the "first term"
   figure on the third-term card can differ from the average on the first-term
   card, for the reason in point 1, and for any child whose earlier term was
   read under a different rule.
3. **A term that was never released still counts.** Nothing asks whether the
   earlier term's sheet reached release. A first term left in draft, or sent
   back and never finished, is averaged in with whatever marks it holds.

The session average decides the promotion suggestion (`sessions.py:775-797`),
so these are not display differences only.

**How to reproduce (test idea).** One class, two children, two subjects, two
papers each, all three terms. Leave one paper unmarked for child A in the
third term. Release all three terms (confirming the unmarked count). Assert
`ReleasedSessionResult.third_average != ReleasedCard.own_average` for child A.
Second test: leave the first term in draft; assert `first_average` is not null
on the third-term line.

**Who is harmed.** A child whose card shows two different third-term averages,
and a parent comparing the first-term card with the year's summary. A child
near the pass mark can be suggested "repeated" on a figure no card ever showed.

**Smallest safe fix.** For the term being released, read
`results.card_averages` instead of `results.averages` at `sessions.py:427`. For
the two earlier terms, read the average off the child's released card for that
term (`cards.card_for(student, term)`, as `ogun_card._other_terms()` already
does at `results/ogun_card.py:164-182`) and record a term with no released card
as absent with its own reason. This changes a stated rule
(`positions.py:303-306`), so it needs the owner's word first.

### G-03. Releasing one class's CBT scores gives out the answers while others still sit (High)

**What is wrong.** A test has one paper (`TestItem`, copied when it is sent for
approval, `cbt/setting.py:258-274`) and may be set for several classes
(`TestAudience`). Scores are released **per class**
(`cbt/release.py:100-118`). `why_not_releasable()` (`release.py:57-66`) asks
only about the class being released: nobody in it is mid-attempt, its own
sitting is closed, somebody in it has sat. It does not ask whether the test is
still open to another class, or whether a retake has been granted.

Release shows each student of that class their whole paper with, for every
question, the right option and the explanation (`release.py:69-93`), and their
parents the same.

So: JSS 2A sits on Monday, its teacher closes its sitting and releases. JSS 2B
sits the same paper on Tuesday. Every 2A student holds the answer key
overnight.

**How to reproduce (test idea).** A published test with two classes in its
audience and a window of two days. One student of class A submits; close A's
sitting; `release_as(teacher, school, test, class_A)`. Assert it succeeds while
`sitting.sitting_open(test, class_B)` is true, and that the released
corrections for A's student carry `right_letter` for every item.

**Who is harmed.** Honest students in the class that sits second, and the CA
mark the score is scaled into (`cbt/ca.py`).

**Smallest safe fix.** In `why_not_releasable()`, also refuse while any other
class in the test's audience has an open sitting or the test's `closes_at` has
not passed, with the sentence "JSS 2B has not finished sitting this test".
If a school needs early scores, release the score without the corrections
until the test is closed for every class.

### G-04. Promotion ignores results and the principal's decision (Medium)

**What is wrong.** There are two separate things called promotion and they do
not meet.

- `results/sessions.py:852-896` `decide()` records that a child is promoted,
  repeated, on trial or withdrawn. It is the principal's alone
  (`DECIDING_ROLES`, `:144`), keeps the suggestion and the average beside the
  decision, and is what the Standard card prints (`results/card_api.py:1284-1304`).
  **Nothing calls it.** `decide_as`, `use_a_weighting_as`, `use_a_straight_mean_as`
  and `set_pass_mark_as` (`sessions.py:948-966`) have no route and no page. So
  no school can record a decision, the Standard card never prints one, every
  school averages its terms equally and the pass mark is 50 for everybody.
- `academics/promotion.py:245-340` `promote()` is what actually moves children.
  It is open to the principal **or the administrator** (`:343-350`,
  `PLACEMENT_ROLES`). It reads no result: not whether the third term is
  released, not the session average, not a `PromotionDecision`. The page starts
  with every child set to "promote" (`academics/promotion_api.py:37`).

So an administrator can make any child repeat, or mark any child as leaving or
graduated, with no reason recorded and without the principal. Graduating and
leaving end the enrolment and cannot be undone from the screen
(`promotion.py:338-339`, `docs/classes.md`). A child the principal would have
held back is promoted by default unless somebody changes the row by hand.

Promotion is also possible only while the third term is still current
(`promotion.py:163-180`). If the office makes the new session's first term
current first, promotion answers "The school is in First term" for good, and
the only way left is to place every child by hand (G-01).

**How to reproduce.** As an administrator in a third term with next session's
first term created: `POST /api/academics/promotion/` with one child set to
`repeat` and one to `leave`. Both succeed with no results released.

**Who is harmed.** A child moved, held back or removed on one person's say
with nothing on record; a principal who believes the decision is theirs.

**Smallest safe fix.** Decide which is the rule. If promotion follows the
principal's decision: give `decide_as` a route and have `promote()` refuse a
choice that disagrees with a recorded decision. If the office page is the
decision: have `promote()` write a `PromotionDecision` per child with who
confirmed it, and make "leave" and "graduate" the principal's. Either way,
have `set_current_term` warn when leaving a third term with nobody promoted.

### G-05. Graduating or "leaving" a child locks the family out of the final card (Medium)

**What is wrong.** Promotion ends the enrolment of every child who graduates
or leaves (`academics/promotion.py:338-339`), through
`accounts/services.py:399-452` `release_student()`. That ends the child's
membership and, for a guardian with no other child still at the school, ends
the guardian's parent membership too (`services.py:363-383`).

A signed-in user with no active membership at the school is refused on every
page that is not a door (part 1, section 3; `accounts/middleware.py:125-145`).
So from the moment promotion is confirmed, the SS 3 leavers and their parents
cannot sign in to read the third-term card, the fee account or a receipt. The
guardian link itself is kept (`card_api.py:881`), but the request never gets
that far.

Promotion has to be run before the new session starts (G-04), which is exactly
when families are reading final results. The result checker PIN is a way in
until the next session starts (`results/checker.py`), for schools that print
slips.

**Needs checking.** Sign in as the parent of a graduated only child and open
`/api/results/cards/`. Expected from the code: refused by the middleware.

**Who is harmed.** Every graduating family, and any family whose child leaves
owing fees: they can no longer see what they owe or pay online against it.

**Smallest safe fix.** Let an ended student or parent membership keep read-only
access to released cards and the fee account for a set period (a term), by
checking for a recently ended membership at the card and fee read routes. Until
then, say on the promotion confirm step that graduates' families lose access at
once, and offer result-checker slips for the leaving class.

### G-06. The Ogun card's promotion line is worked out from next term's class, read live (Medium)

**What is wrong.** `results/ogun_card.py:192-218` decides the line on a
third-term Ogun card by looking up the child's placement in the first term of
the next session:

- same class as the card: "Not promoted, to repeat JSS 2A";
- any other class: "Promoted to …".

It is read live every time the card is opened. Consequences:

- A child placed in next term's first term by hand or by a future
  carry-forward (G-01's fix, if applied across sessions) into the same class
  reads "Not promoted" on a card that has already gone home.
- A child who repeats the year in the other arm (JSS 2A to JSS 2B) reads
  "Promoted to JSS 2B". So does a child moved down a class.
- A child moved between classes in October changes last session's card.
- The stored PDF is rendered at release (`ogun_card.py:12-13`), which is before
  promotion, so it has no line, while the page shows one. The two copies of the
  same card disagree.
- With no placement it falls back to `PromotionDecision`, which nothing can
  write (G-04). A child who graduates or leaves has no placement and no
  decision, so the final card says nothing.

The released broadsheet uses the same function (`results/broadsheet.py:266-267`).

**How to reproduce (test idea).** Release a third-term Ogun card for a child in
JSS 2A. Place the child in JSS 2B for next session's first term. Assert
`sheet_for(card, …)["promotion"] == "Promoted to JSS 2B"`.

**Who is harmed.** A family told in writing that a child was not promoted, or
was, when no such decision was made.

**Smallest safe fix.** Compare class **levels**, not ids, so the same level is
"to repeat" and a higher level is "promoted". Better: write the outcome once,
when promotion is confirmed (G-04's `PromotionDecision` per child), and print
only that.

### G-07. On the Ogun card a subject with no paper named "Exam" is left out (Medium)

**What is wrong.** `results/ogun_card.py:126-144` `_is_complete()` treats a
subject as complete only if it has a paper whose name is exactly "Exam"
(any case) **and** at least one other paper. Otherwise the subject's Weighted
Average, 1st/2nd/3rd term scores and Annual Score print "-" (`:273`, `:281-292`)
and it is left out of marks obtainable, marks obtained and percentage
(`:147-161`), under the note "Not counted: N subjects with a paper not yet
marked", which is not true of it.

A school that had marks in when it chose the Ogun template keeps its own papers
(`results/ogun.py:175-178`, reported as "kept"). If those are named
"Examination", "Exams", "CA" and "Test", every subject on every card is a
column of dashes, with a class position still printed beside an empty summary.
The module's own heading says the opposite: "a school whose papers differ still
gets its CA and exam split" (`ogun_card.py:24-26`).

**How to reproduce (test idea).** Subject with papers "CA" (40) and
"Examination" (60), all marked. Choose Ogun, release. Assert
`sheet["summary"]["percentage"] is None` and `left_out == 1`.

**Who is harmed.** Whole schools that switch template mid-year: released cards
with no totals, and a release cannot be undone.

**Smallest safe fix.** Treat a subject as complete when `line.is_complete` is
true (every paper marked), whatever the papers are called; use the "Exam" name
only to split the two rows, and when no paper is so named show the total in the
Weighted Average row and leave the split blank. Until then, have
`set_template_as` list the kept subjects whose papers have no "Exam".

### G-08. The Ogun card's percentage and annual score are not the figures the position uses (Medium)

**What is wrong.** Three differences between the Ogun sheet and the rest of
the system, for the same frozen card.

1. **Percentage.** The summary's percentage is marks obtained over marks
   obtainable (`ogun_card.py:150-155`). The class position printed next to it
   is ranked on the mean of the subject percentages
   (`results/positions.py:413-417`). They are the same number only when every
   subject is out of the same total. With kept papers of different totals, two
   children can be printed with the higher percentage in the lower position.
2. **Rounding.** `ogun_card.py:155` and `:189` call `quantize()` with no
   rounding mode, which is round-half-even. Everything else rounds half up
   through `positions.round_percentage()`, and `positions.py:116-128` explains
   at length why. Eight subjects totalling 561 give 70.125: the Standard card
   and the ranking say 70.13, the Ogun summary says 70.12. An annual score of
   two terms at 70.02 and 70.03 is 70.02 here and 70.03 by the house rule.
3. **Annual score.** The Ogun annual score per subject is a straight mean of
   the terms that have a released card and a complete subject
   (`ogun_card.py:164-189`). The Standard card's session line is a mean of live
   term averages under the school's weighting (G-02). The two layouts therefore
   describe the same child's year from different data, and a term whose card
   was never released silently drops out of the Ogun figure: the "annual" score
   is then one term's score under an annual label.

**How to reproduce (test idea).** Card with eight complete subjects, each out
of 100, totalling 561. Assert `sheet["summary"]["percentage"] == "70.13"`; it
is "70.12" today.

**Who is harmed.** A parent comparing two children's cards, or the card with
the broadsheet.

**Smallest safe fix.** Use `positions.round_percentage()` at both `quantize`
calls. Print the card's own frozen average (`ReleasedCard.own_average`) as the
percentage, or label the present figure "Marks %" so it is not read as the
ranked average. Show "-" for the annual score unless every term the child was
enrolled for has a score, or say how many terms it covers.

### G-09. Choosing the Ogun template mid-chain changes cards waiting for release (Medium)

**What is wrong.** `ogun.apply_assessments` was checked for the case in the
brief and is sound: it replaces papers only for a subject with no mark anywhere
in the term (`results/ogun.py:165-186`), so it cannot add a paper to a subject
a locked class was marked in (part 1, F-02).

The rest of the same act is not guarded. `set_template_as`
(`ogun.py:256-286`) and `apply_traits` (`:192-226`), at any time:

- switch both conduct sections on;
- hide every trait the sheet does not print, rated or not;
- add the sheet's traits the school did not have;
- turn the class position on (`:273`).

Conduct ratings are locked once a class is submitted
(`results/ratings.py:643-647`), and release freezes the section from the trait
list as it stands at that moment (`ratings.py:1118-1125`). So for a class
already submitted, checked or approved, choosing Ogun removes rated lines from
the cards about to be released, adds lines nobody can now rate (they print
blank), and prints a position the school had switched off. What is released is
not what was approved.

**Needs checking.** Whether the ordinary conduct settings (hide a trait, switch
a section off) are refused mid-chain; `ratings.py` was read for the freeze and
the lock, not for every settings function. If they are not, this is the same
finding with a wider door.

**How to reproduce (test idea).** School on the Standard list with ratings
entered; submit, check, approve one class. `set_template_as(principal, school,
"ogun")`. Release. Assert the released traits are the sheet's twelve, and that
the ones just added have null scores.

**Who is harmed.** A class whose conduct section goes home half blank, with no
way to correct a released card short of revising each one.

**Smallest safe fix.** In `set_template_as`, refuse while any `ResultSheet` of
the current term is submitted, checked or approved, naming the classes, with
the sentence F-01 and F-02 already use.

### G-10. A register can be written for any term at any time (Medium)

**What is wrong.** `PUT /api/attendance/classes/{class}/terms/{term}/{date}/`
(`attendance/api.py:386-432`) takes the term from the URL and checks two
things: the caller may mark at this school, and the date is inside that term
(`attendance/services.py:163-168`). It does not look at the class's
`ResultSheet`. `discard_register` (`services.py:472-494`) is the same.

- **After release.** A released card's attendance is frozen
  (`results/cards.py:340-355`), so the card does not move, but the register
  behind it can be amended or deleted for ever. The register and the card then
  disagree, and a later revision that passes new attendance will read the
  changed figures.
- **Between approval and release.** Attendance is read at release
  (`attendance/summary.py:58`), not at approval, so a register changed in
  between changes what goes on the card after the principal approved it.
- **By anybody who teaches.** Any teacher may write any class's register. That
  part is known (issue #125, `api.py:186-193`); with no time limit it means any
  teacher can rewrite last term's attendance for any class.
- **A late offline register after the term has changed** is filed against the
  term it was drawn for, with that term's roster, and is accepted, which is
  right. If it is sent without a `base` (an old page), it overwrites whatever
  the office corrected since (`services.py:272-273`); with a `key` and a `base`
  the second arrival is answered from its receipt and merged child by child,
  which was checked and is sound (section 3).

**How to reproduce (test idea).** Release a class. `PUT` a register for a date
in that term marking a child absent. Assert 200, and that
`summary.for_term()` now differs from `ReleasedCard.days_absent`.

**Who is harmed.** A parent who disputes an attendance figure: the school's
register no longer supports the card it issued.

**Smallest safe fix.** In `take_register` and `discard_register`, refuse when
the class's sheet for that term is not open for writing
(`results.services.is_open_for_writing`), as marks and ratings already do.
A correction after release then goes through a revision, with a reason.

### G-11. Attendance counts marks, not days (Medium)

**What is wrong.** A card's days present and absent are counts of
`AttendanceMark` rows across every register in the term, whichever class took
it (`attendance/summary.py:81-90`). The only uniqueness is one mark per child
per register and one register per class per day
(`attendance/models.py:174-177`, `:241-244`). Nothing says one mark per child
per **day**.

A register is always taken against the class list as it is now
(`attendance/services.py:171-178`, `:250`), for whatever date is asked.

- A child marked in JSS 1A on Monday morning and moved to JSS 1B that day is
  on 1B's register for Monday too: two marks, one day.
- A teacher who back-fills or corrects last week's register for JSS 1B marks
  every child now in 1B, including one who was in 1A last week and already has
  1A's marks for those days. That child gains a second "present" for each day.
  `summary.py:71-75` assumes the two classes marked different days.
- The reverse: a child who has left a class is dropped from any amendment of
  its old registers, which is right, but a child added today is marked present
  on days before they arrived.

The totals can exceed the number of days the school opened. The Standard card
hides that (`results/card_api.py:462-466` clamps); the Ogun card prints it
(G-18).

**How to reproduce (test idea).** Child in class A; take A's register for day
D. Move the child to B. Take B's register for day D. Assert
`summary.for_term(term, [child])[child].present == 2`.

**Who is harmed.** A child whose card shows more days present than the term
had, or absences on days they were at school in another room.

**Smallest safe fix.** Count distinct `register__taken_on` per child and status
in `summary.for_term()`, taking absent over present only if the school says so
(today any rule is better than a double count; "latest mark wins" matches how a
correction works). And when a register is taken for a past date, leave
unmarked any child whose placement was made after that date
(`ClassPlacement.updated_at`), naming them in the answer as `appeared` already
does.

### G-12. The dashboard's "outstanding" is this term only; the fee book uses the whole account (Medium)

**What is wrong.** Four places answer "who owes, and how much", from two
different sums.

- **Dashboard** (`home/facts.py:247-270`): entries of the **current term**
  only, summed per child, counting children whose term sum is above zero. Its
  card says "N students owe fees for this term" and links to the fee book
  (`home/dashboard.py:531-534`, `:595-596`).
- **Fee book, class page** (`fees/api.py:410-415`): each child's balance over
  **every term**, shown under a term's heading.
- **Reminders** (`notices/reminders.py:64-76`) and **withholding**
  (`results/withholding.py:301-328`): the whole account, deliberately.

So a child with ₦20,000 unpaid from last term who has paid this term in full
owes nothing on the dashboard, ₦20,000 in the fee book, and gets a reminder.
A child ₦20,000 in credit from last term and charged ₦20,000 this term owes on
the dashboard and nothing in the fee book. The principal's headline and the
bursar's list cannot be reconciled.

Two smaller gaps in the same comparison:

- The fee book's class totals count only children placed in a class that term
  (`fees/api.py:326-344`). The dashboard counts every entry of the term. A
  payment for a child with no class this term (not yet placed, or every child
  after a term change, G-01; a Paystack payment lands on the current term,
  `fees/webhook.py:176`) is in the dashboard's "collected" and in no class's.
- A part payment of last term's arrears made today is filed under the current
  term, so "collected this term" can pass 100% of "billed this term"
  (`dashboard.py:523-525`; the bar is capped, the text is not).

Kobo are whole integers throughout both sums; no rounding difference was found
between them.

**How to reproduce (test idea).** One child: charge 20,000 in term 1, nothing
paid. Make term 2 current, charge 10,000, pay 10,000 in term 2. Assert the
dashboard's `owing.n == 0` while `GET /api/fees/classes/{id}/?term_id=2` shows
`balance_kobo == 2_000_000`.

**Who is harmed.** A principal reading "nobody owes" while the bursar chases
arrears; a family reminded about a debt the dashboard does not show.

**Smallest safe fix.** Decide the one meaning and say it on the card. The
smallest change: compute the dashboard's `owing` from whole-account balances
of children placed this term (the rule reminders already use) and label it
"outstanding, all terms". Keep "collected" and "billed" as this term's, and
add an "unplaced" row to the fee book so its classes add up to the dashboard.

### G-13. A child moved to another class mid-term stays on the old class's bill (Medium)

**What is wrong.** A bill belongs to a class and a term. Applying it charges
the children on that class's roster now (`fees/schedules.py:186`), and skips a
child "already charged this term by another class's bill"
(`:262-275`, reported as `billed_elsewhere`).

For a child charged in SS 1 Arts and then moved to SS 1 Science:

- Science's bill never charges them, though its lines may differ (a laboratory
  levy).
- Arts's bill no longer reaches them, because they are not on its roster. Any
  line added to either bill later in the term (a second instalment, an exam
  fee) is charged to neither. The child is silently under-billed.

The summary does name the skipped children (`billed_elsewhere`), so a bursar
who reads it can act: reverse the old class's charges, then apply the new
bill, which then charges them (`:271` excludes reversed charges). Nothing
prompts for that at the moment of the move, and `move_student`
(`academics/services.py:314-360`) does not look at fees.

A child admitted after a bill was applied is likewise not charged until
somebody presses Apply again.

**How to reproduce (test idea).** Apply class A's bill. Move one child to B.
Add a line to A's bill and to B's bill; apply both. Assert the child has
neither new charge.

**Who is harmed.** The school (fees not billed), and later the family, when
the gap is found and billed at once.

**Smallest safe fix.** When applying a bill, charge a new line to every child
who holds an un-reversed charge from **this** bill, on the roster or not. And
have the roll's move answer say "this child has been billed in SS 1 Arts this
term" when that is so.

### G-14. Admission numbers are not unique (Medium)

**What is wrong.** A child's admission number is `Membership.reference`. It has
an index and no unique constraint (`accounts/models.py:486`, `:515`).

- The roll import checks it is free, case-sensitively (`accounts/bulk.py:602-617`).
- Admitting one child from the roll page does **not** check at all
  (`accounts/enrolment_api.py:286-294`, `accounts/services.py:541-572`).
- A transfer carries the old school's number into the new school if the new
  school gives none (`accounts/services.py:501`), without looking for a clash.
- Two imports at the same moment both pass the check.

Every door that takes an admission number matches it without case
(`cbt/sitting.py:308`, `cbt/pins.py:302`, `results/checker.py:357`). So
"jss/014" and "JSS/014" pass the import as two numbers and are one number at
the doors.

With two children on one number: a no-PIN test opens for neither
(`cbt/sitting.py:304-311` wants exactly one); PIN doors still work because the
PIN picks the child; exam slips, broadsheets and the fee book show two children
under one number; the generated sign-in handle `SLUG/number` goes to the first
and the second gets `SLUG/n` (`bulk.py:545-554`).

The import refuses a number held by a child who has left, so a number is not
handed to a second child that way. The single admission would allow it.

**How to reproduce.** `POST /api/enrolment/roll/` twice with different
usernames and the same `reference`. Both answer 201.

**Who is harmed.** Two children whose records are told apart only by name; a
student shut out of a practice test.

**Smallest safe fix.** In `enroll_student()`, refuse a non-blank reference
already held at that school by another student, compared without case; and add
a partial unique index on `(school, lower(reference))` for student rows with a
non-blank reference, after checking no existing rows collide.

### G-15. A roll file without admission numbers, sent twice, admits every child twice (Medium)

**What is wrong.** `accounts/bulk.py:557-705` checks each row for a name, a
class, a free username, a free admission number and a free learner ID.
`reference`, `username` and `learner_id` are all optional
(`bulk.py:108-117`). A file with only names and classes passes every time it
is sent, and each time creates a new login and a new enrolment for every row
with a generated handle (`:533-554`).

The import route takes no idempotency key (`accounts/enrolment_api.py:665-683`),
unlike a payment or a register. A double press, a retry after a slow answer, or
an office that uploads the same file after "did it work?" doubles the roll.
Nothing warns that a child of the same name is already in the same class.
There is no way to remove the duplicates (G-16).

**How to reproduce.** Upload a two-row CSV with `full_name,class_group` twice.
The roll has four children.

**Who is harmed.** The office, and every list built from the roll: class size,
positions "of N", bills applied to the class (each duplicate is charged).

**Smallest safe fix.** In `check()`, report a row whose name already exists in
the same class this term as a problem ("already on the roll in JSS 1A; give an
admission number if this is a different child"). Give the import route the
same once-only key the payment form has.

### G-16. No way to take a child off the roll mid-session; the transfer handshake has no route (Medium)

**What is wrong.** `accounts/transfers.py` (request, accept, decline, withdraw)
and `accounts/services.py:456-521` `transfer_student()` are complete and
tested, and nothing calls them: no route, no page, no command. The only callers
of `release_student()` are promotion (`academics/promotion.py:339`) and the
onboarding reset (`onboarding/again.py:297`). The roll API has admit, place,
import, guardians and details (`accounts/enrolment_api.py`), and no "left".

So in the product today:

- A child who leaves in October stays on the roll and in the class until the
  end-of-session promotion. They are counted in the class size, listed as
  "left out" or unmarked at every release, charged by every bill applied to the
  class, and sent fee reminders.
- A child moving between two Classnode schools is admitted at the second as a
  new person with a new login. Nothing is carried and nothing links the two
  records. That is safe for isolation, and it means a parent has two unrelated
  children in the system.

Read as designed, for when it is wired up, the transfer was checked for what it
carries across:

- **Carried:** the same login, the child's display name, the guardians and
  what the sending school typed about each guardian (name and contact,
  `services.py:505-515`; documented as deliberate at `:473-475`), and the
  sending school's admission number if the receiving school gives none
  (`:501`; see G-14).
- **Not carried:** class, marks, cards, attendance, fees, date of birth,
  learner ID, photo, health record. Each lives in the sending school's own
  schema and stays there. The child arrives with no class.
- No path was found by which the receiving school reads the sending school's
  rows, or the reverse.

**Who is harmed.** Classes whose size and "left out" lists are wrong for most
of a year; a leaver's family billed and reminded.

**Smallest safe fix.** A "has left" action on the roll for the principal and
the administrator that calls `release_student()` with a date, refused while
the child's class is in the approval chain (as F-01), and that keeps the
family's read access for a period (G-05). Wire the transfer handshake
separately; before it is, make `transfer_student()` require the receiving
school's own admission number.

### G-17. Question banks are per subject and level, and level defaults to 0 (Low)

**What is wrong.** A teacher reads and writes the bank of each subject they
teach, at the **level** of each class they teach it to
(`cbt/access.py:197-205`). A class's level is a number the office types when
creating the class, and it defaults to 0 (`academics/api.py:237`,
`static/setup/states.js:239`).

A school that leaves the level at 0 for every class has one bank per subject
for the whole school. The JSS 1 Mathematics teacher then reads, edits and
retires every question the SS 3 Mathematics teacher wrote, answers included,
and can set a JSS 1 test from them; `setting._checked` accepts it because the
levels match (`cbt/setting.py:150-155`).

This is teachers reading teachers, within one subject, so the exposure is
small. It also breaks promotion's suggestions (`promotion.py:133-149` uses
level to find the class above).

**Smallest safe fix.** Require a level when a class is created, suggest it
from the class's name, and show on the bank page which classes share the bank.

### G-18. The Ogun card prints attendance with no "not marked" figure (Low)

**What is wrong.** The Ogun sheet prints three numbers side by side: times
school opened, times present, times absent (`results/ogun_card.py:322`,
`:352-354`; `report_card_ogun.html:130`). "Opened" is what the school declared
for the term (`Term.school_days`); the other two are counts of register marks.
The Standard card adds "not marked" so the three add up
(`results/card_api.py:462`). The Ogun card does not, so a class whose teacher
took the register on 40 of 60 days prints 60, 38, 2 and a parent reads 20 days
unaccounted for.

Nothing ties the two sources together:

- A register is accepted for any date inside the term: a Saturday, a public
  holiday, mid-term break, or a date that has not come yet
  (`attendance/services.py:163-168`). There is no calendar of holidays.
- So a class can hold more registers than the declared days, and present can
  exceed opened (also by G-11).
- If nobody has declared the term's days, "opened" is blank and the other two
  still print.
- Terms may overlap in dates (`attendance/models.py:83-88` says so), and a
  register is found by class and date alone (`services.py:181-183`,
  `:367-371`), so on an overlapping date the marks go to whichever term's
  register was created first.

**Needs checking with a school.** The paper Ogun sheet counts "times school
opened" in sessions (morning and afternoon), so about twice the days. Whether
schools expect days or sessions here is a question for a school, not the code.

**Smallest safe fix.** On the Ogun card, print absent as "opened minus present"
only when every day was marked, otherwise add the Standard card's "not marked"
beside it. Refuse a register dated in the future. At release, list any class
whose registers number more than the declared days.

### G-19. An absence alert goes out on a mis-tap and for a late register (Low)

**What is wrong.** `take_register()` writes an absence alert for every child
the submission marks absent, in the same transaction, and queues the email
(`attendance/services.py:274-281`, `notices/absence_alerts.py:100-126`). There
is one alert per register and child, ever.

- A teacher who taps the wrong child, submits, and corrects it a minute later
  has already told that family their child was absent. Nothing withdraws or
  follows up the first message. A notice held for quiet hours is not checked
  against the register again before it is sent: the send task sets
  `changed = False` for an absence alert (`notices/tasks.py:89-95`), where a
  fee reminder re-reads the balance (`:96-106`).
- A register entered a week late, or an offline register that arrives days
  later, sends "absent on Monday 2 November" on the day it arrives.

**Smallest safe fix.** At send time, read the mark again and drop the notice
if the child is no longer marked absent (the pattern fee reminders already use
for a changed balance, `notices/reminders.py:13-16`). Do not alert for a
register dated more than a day or two back.

### G-20. Small figures (Low)

- **Dashboard naira.** `home/dashboard.py:69-71` formats with
  `round(kobo / 100)`: floating point, and Python's round-half-even, so
  ₦1,250.50 shows as ₦1,250 and ₦1,251.50 as ₦1,252. The fee book formats kobo
  exactly (`static/fees/money.js`). A whole-naira figure on a dashboard is
  fine; it should round the same way every time (`(kobo + 50) // 100`).
- **Ogun trait total.** `results/ogun_card.py:312-319` prints "Total 12 of 30"
  where 30 is five times the number of lines, rated or not, and 5 is written
  in rather than read from the school's scale. A child rated on three of six
  lines looks like a child rated low on six.
- **Re-choosing Ogun.** "Choosing Ogun again applies the presets again"
  (`results/ogun.py:260-262`). A subject whose teacher set up their own papers
  for the term and has not yet entered a mark has them deleted and replaced by
  the sheet's four (`:181-185`). It is reported, and nothing entered is lost,
  but the teacher is not the one who pressed the button. The delete would also
  fail with a server error if a CBT transfer still points at one of those
  papers (`cbt/models.py:1022`, `on_delete=PROTECT`) after its marks were
  cleared. **Needs checking:** whether clearing a mark sent from CBT leaves the
  transfer row.

### G-21. CBT roles to confirm (Low)

These are how the code behaves. Each may be intended.

- **The principal approves their own test.** A principal may set any test
  (`cbt/access.py:226`) and approve any test (`cbt/setting.py:303-305`);
  nothing requires the approver to be somebody other than the setter. The
  results chain does forbid one person signing two steps.
- **Classes can be added to or removed from a test after it is approved**, by
  its teacher, while it is published (`cbt/setting.py:340-362`). Each change is
  logged with who and when. A class added after another has sat gets a paper
  the first class has already seen (see G-03).
- **A teacher whose own child is in a class they teach** reads that class's
  bank and tests. Nothing in the code could know; it is a matter for the
  school's own rules.

## 3. Checked and found sound

Traced through the code named; no fault found.

**Session averages**

- A term the child was not enrolled for, or was enrolled for and not marked,
  is left out and the weights of the terms sat are scaled back up to 100; it is
  never counted as nought (`results/sessions.py:433-450`, `:549-570`). The
  reason is kept per term (not enrolled, unmarked, no such term) for staff and
  is not served to a parent (`results/card_api.py:1266-1281`).
- A child who joined mid-session is averaged over the terms they had. A child
  who was in a different class in an earlier term is read from that class
  (`sessions.py:423-431`).
- The average is computed from exact ratios and rounded once, half up, by the
  same function as every other percentage (`sessions.py:564-566`). The stored
  weights are rounded separately and made to total exactly 100
  (`:474-519`). A weighting must be three non-negative numbers totalling 100,
  in the service and in the database (`:192-221`).
- A school that weights every term a child sat at nought gives that child no
  session average and no suggestion, not a nought (`:553-562`).
- The suggestion is "promoted" at or above the pass mark and "repeated" below
  it, and never anything else; a child with no average gets none
  (`:775-797`). A decision, once one can be recorded, keeps the average and
  the pass mark that produced the suggestion, and is append-only (`:852-896`).
- The frozen session line is written once per release inside the release's
  transaction, from the same roster read as the cards (`:594-677`), and a
  child released twice keeps the first (`:680-732`).

**Promotion mechanics**

- Nothing moves until confirmed, and then every class moves or none does, in
  one transaction under a lock on the term (`academics/promotion.py:252-257`).
- The plan must name exactly the classes and children the school has now; a
  child who joined or left since the page was drawn refuses the whole plan
  (`:266-287`). A class cannot be promoted into itself or into a class that is
  not active (`:296-301`).
- A child already placed in next session's first term refuses the whole
  promotion rather than being overwritten (`:316-323`), so it cannot run twice.
- Only a principal or an administrator of this school reaches either route,
  asked before any table is read (`academics/promotion_api.py:91-93`,
  `promotion.py:343-350`).

**Ogun card**

- `apply_assessments` replaces papers only for a subject with no mark in the
  term, under a lock that a mark being entered also takes, so it cannot add a
  paper to a subject a class in the chain was marked in
  (`results/ogun.py:165-186`).
- A card's layout is the one it was released under, not the school's current
  template (`results/ogun_card.py:81-90`); the rating key printed is the
  card's own (`:358`).
- Continuous assessment, exam and weighted average for a subject come from the
  frozen card's own lines; a half with a paper unmarked is a dash, not a
  partial sum (`:105-123`).
- The first- and second-term scores on a third-term card come from the
  child's released cards for those terms, by subject id, complete subjects
  only (`:164-182`).
- Class teacher's and principal's remarks, attendance, traits and "next term
  begins" are read from the same payload as the Standard card
  (`results/card_api.py:1466-1482`), so the two layouts cannot differ on them.
- The health record is not in the payload every reader gets
  (`ogun_card.py:15-18`).

**Attendance**

- One register per class per day, held by the database; a second submission
  amends it under a row lock (`attendance/models.py:174-177`,
  `attendance/services.py:357-390`).
- An offline register sent twice with its key is answered from the first
  arrival's receipt and changes nothing (`attendance/api.py:420-430`). With a
  base, a late register writes only the children the teacher changed, only if
  the school still has what the teacher was shown, and reports the rest as a
  conflict for the teacher to settle (`services.py:292-354`).
- A child who joined the class after the screen was drawn is left unmarked and
  named; an absentee no longer in the class is not written
  (`services.py:257-265`). No id a caller sends can reach a mark unless it is
  on this school's roster.
- A day with no register is not an absence, and a child with no mark is not
  absent (`attendance/summary.py:19-21`).
- The card's three attendance figures are copied at release from one read and
  a revision carries them forward unchanged (`results/cards.py:340-390`).
- A parent, student or bursar is refused before any class or term is looked up
  (`attendance/api.py:238-254`).

**CBT question banks**

- Every bank and question route asks for the role first, then the reach, and
  answers "not here" and "not yours" alike (`cbt/bank_api.py:295-299`,
  `cbt/banks.py:207-224`). A teacher reaches only the subjects and levels they
  are assigned this term; the vice principal reads all and writes none; a login
  holding the administrator role reads no bank, no question and no test's
  questions, whatever else it holds (`cbt/access.py:120-128`, `:214-216`,
  `bank_api.py:785-791`).
- A test's questions are copied when it is sent for approval and the copy is
  what is approved, sat and marked; editing or retiring a bank question does
  not reach it, and sending it back discards the copy
  (`cbt/setting.py:258-300`, `:318-320`).
- Editing a question is refused over a version somebody else saved since, a
  used question is retired not deleted (`cbt/banks.py:230-279`).
- The "try it as a student" preview is built by the same function as the paper
  a device gets, with no answer in it (`bank_api.py:894-913`).
- A question's picture is served only to a login that reads a bank or a test
  naming it, or to its uploader before it is saved (`bank_api.py:494-529`).
- No export of a bank or a test exists: no CSV, spreadsheet or PDF route in
  `cbt/` other than exam slips. No `logger` or `print` call in `cbt/` writes a
  question or a key. The sitting log has no item, option, answer or score in
  it (`cbt/sittings.py:259`), and the administrator sees released scores only
  (`cbt/access.py:346-348`).
- An exam officer's grant adds printing slips, extra time and retakes and
  nothing about banks (`cbt/access.py:120-128`).

**Fees**

- A bill applied twice charges once per child and line; two bills in one term
  cannot both charge a child; a child whose membership has ended is skipped
  and counted (`fees/schedules.py:236-290`).
- A standing concession discounts a child once per term whichever bill posts
  it, and a revoked one posts no more (`schedules.py:330-382`,
  `fees/billing.py:231-260`). Granting from one form twice grants once
  (`billing.py:193-228`).
- The dashboard and the fee book reckon a reversal the same way: as the kind
  it undoes (`home/facts.py:244-253`, `fees/api.py:333-336`). Both sum whole
  kobo in the database; neither divides before summing.
- A part payment is an ordinary payment; the balance is the plain sum of the
  child's entries, and credit is a real state (`fees/models.py:465-477`).
- A Paystack payment for a child who has left is still recorded
  (`fees/webhook.py:171-175`).
- Reminders read the ledger again at send time and drop a child whose balance
  changed (`notices/reminders.py:13-16`).

**Roll import and transfers**

- A file is checked whole and written whole in one transaction; every bad row
  is reported by its line (`accounts/bulk.py:708-735`).
- A class is matched by name among this school's active classes, so a wrong
  name is a refused row, not a wrong class (`bulk.py:619-632`).
- A username in use anywhere is refused without saying where
  (`bulk.py:590-596`); a learner ID is checked within this school only.
- Dates of birth are read day first and never guessed month first; a
  spreadsheet's own date cells are read as dates (`academics/details.py:106-134`,
  `bulk.py:276-279`).
- The file is bounded before it is opened (2 MB, 20 MB unpacked, 2,000 rows)
  and formulas are read as their saved values (`bulk.py:136-143`, `:283-296`).
- A transfer needs a signature from each school and one person cannot give
  both; one open request per child, held by the database
  (`accounts/transfers.py:108-116`, `:153-182`).
- A student has one live enrolment across the platform, held by the database
  (`accounts/models.py:506-510`).

## 4. Not covered, or only skimmed

- **Guardian matching across schools** (`accounts/guardian_contacts.py`): the
  import links a guardian by phone or email to an existing login. That the
  receiving school learns nothing about that person from another school was
  read in the import's own report (`bulk.py:801-820`) and not in
  `link_by_contact_as()` itself.
- **Conduct settings and remarks** (`results/ratings.py` settings functions,
  `results/comments.py`): read for the freeze and the lock only (see G-09's
  "needs checking").
- **CBT marking, sittings, retakes and extra time** beyond what G-03 needed;
  the item analysis page; `cbt/demo.py`.
- **OGSERA export** (`results/ogsera.py`): not opened.
- **Fee schedules' concurrency notes, virtual accounts, unmatched payments
  and placing them** (`fees/virtual.py`, `fees/placing.py`), the daily money
  summary, and receipts.
- **The dashboard's attendance and results tiles** (`home/dashboard.py`,
  `home/summary.py`): only the money card was compared with its source.
- **The term-change effects on CBT** (a test whose term stops being current)
  and on exam PINs.
- **The browser side** of every page named here: the findings are about what
  the server accepts and returns.
- **The test suite**: not run, and not read for gaps.
