# Classnode audit, part 1: security, privacy and data correctness

Date: 12 November 2026. Read against `main` at `95a751d` (#336).
Findings only. No application code, test, workflow or setting was changed.

How this was done: the code was read, not run. No test was executed and no
school was created, so every "how to reproduce" below is a set of steps or a
test idea that follows from the code path named, not an observed failure.
Where a path could not be followed to the end it says **Needs checking** and
what would settle it. Line numbers are those of `95a751d`.

**Status.** The audit itself changed no code. Fixes are recorded here as they
land: the Status column in the summary, and a **Status** line under the
finding saying what was done and what was left.

Not everything was read to the same depth. Section 3 says what was traced and
found sound; section 4 says what was only skimmed or not opened, so nobody
takes silence here for a clean bill.

## 1. Summary

| ID | Title | Severity | Area | File | Status |
| --- | --- | --- | --- | --- | --- |
| F-01 | A class's roster can change after its results are submitted, checked or approved | High | Correctness, approval chain | `accounts/enrolment_api.py`, `academics/services.py` | Fixed in PR #340 |
| F-02 | A paper added mid-chain makes a whole subject "incomplete" for classes already locked | High | Correctness, totals and positions | `gradebook/curriculum.py`, `results/positions.py` | Fixed in PR #340 |
| F-03 | A child who does not take a subject is "not ranked", and papers are school-wide, not per class | High | Correctness, subjects taken | `results/positions.py` | Open |
| F-04 | Children's data has no retention period, no erasure route and several open legal items | High | Data protection (NDPA) | `website/templates/website/privacy.html`, `accounts/deletion.py` | Open |
| F-05 | Results can be submitted, approved and released with papers unmarked and nothing says so | Medium | Correctness, approval chain | `results/services.py`, `results/chain_api.py` | Fixed in PR #340 |
| F-06 | "This card has gone home" is asked of the conduct rows, so a school with conduct off loses the lock after a class move | Medium | Changing released results | `gradebook/services.py`, `cbt/ca.py` | Fixed in PR #340 |
| F-07 | The time an offline CBT answer was chosen is taken from the device | Medium | CBT, deadline | `cbt/sitting.py` | Open |
| F-08 | A test set without the exam PIN is opened by an admission number alone | Medium | CBT, students seeing others' work | `cbt/sitting.py`, `cbt/release.py` | Open |
| F-09 | Wrong-PIN limits are keyed on the victim's admission number, so a classmate can lock a student out of the exam door | Medium | Authentication, throttling | `cbt/sitting.py`, `results/checker.py`, `accounts/signin.py` | Open |
| F-10 | Signed-in pages have no Content-Security-Policy and escaping is by hand; one value is not escaped | Medium | XSS | `static/web/html.js`, `static/signin/app.js` | Open |
| F-11 | Report card and fee answers carry no `Cache-Control: no-store` | Low | Privacy, shared computers | `results/card_api.py` | Open |
| F-12 | Result-checker PINs are stored as a plain SHA-256 | Low | Secrets at rest | `results/checker.py` | Open |
| F-13 | After one card is revised, its position and class size can disagree with the rest of the class | Low | Correctness, revisions | `results/revision.py` | Open |
| F-14 | A mark can land just after a class is submitted, when the sheet row did not exist yet | Low | Correctness, locking | `results/services.py`, `gradebook/services.py` | Open |
| F-15 | Offline copies of a marking sheet or register are shown to whoever opens the phone | Low | Privacy, shared devices | `static/web/snapshots.js` | Open |
| F-16 | Roles to confirm: every teacher and the bursar read every child's released card; the administrator writes the fee books | Low | Roles | `results/card_api.py`, `fees/authority.py` | Open |

No finding is rated Critical. Nothing was found that lets one school read or
change another school's data, lets a parent open another family's child, or
lets a student see an answer key before release.

## 2. Findings

### F-01. A class's roster can change after its results are submitted, checked or approved (High)

**Status.** Fixed in PR #340. `academics.services.place_student()`,
`move_student()`, `remove_placement()`, `carry_forward_placements()` and
`academics.promotion.promote()` refuse with `ResultsInTheChain` while the sheet
of a class being joined or left is submitted, checked or approved, under the
sheet's row lock: "JSS 2A's results are waiting for approval. Send them back
first to change the class." The roll routes (place, move, admit, import) answer
422 with that sentence. A send-back opens the class again. A released class is
as before. Tests: `results/tests/test_chain_guards.py`. Not closed: a class
with no sheet row yet has nothing to lock, the same narrow race as F-14.

**What is wrong.** Marks are locked once a sheet leaves draft, but the list of
children the sheet is about is not. `PUT /api/enrolment/roll/{id}/class/`
places or moves a child in the current term with no look at either class's
`ResultSheet` (`accounts/enrolment_api.py:338-366`, which calls
`academics/services.py:191` `place_student` and `:243` `move_student`; neither
reads a sheet). Admitting a child with a class (`enrolment_api.py:260-300`) and
the roll import (`accounts/bulk.py:754`) are the same.

Release does not use what was approved. It recomputes from the live roster at
that moment: `results/services.py:789`
`positions.class_results(locked.class_group, locked.term)`, and
`results/positions.py:400` reads `ClassPlacement` afresh. So positions, the
class average and "of N" on every card are whatever the roster is at release,
not what the vice principal checked and the principal approved.

**How to reproduce (test idea).** Two schools, as the project's tests require.
In one: class of three with marks, submit, check, approve. As the
administrator, move the top child to another class (or place a new child with
no marks in the approved class). Release. Assert the released positions and
`roster_size` differ from `class_results()` taken at approval, and that the new
child has a released card with no marks.

**Who could be harmed.** Every child in the class: a position printed on a
released card that nobody approved. An administrator (not the principal) can
cause it, by accident on a busy day or on purpose.

**Smallest safe fix.** In `place_student`, `move_student` and
`remove_placement`, refuse while the sheet of the class being left or joined is
not open for writing (`results.services.is_open_for_writing(sheet_for(...))`),
with the sentence the marks lock already uses ("ask for the sheet to be sent
back"). A released class is the separate case F-06 covers.

### F-02. A paper added mid-chain makes a whole subject "incomplete" for classes already locked (High)

**Status.** Fixed in PR #340. `create_paper_as()` and `delete_paper_as()`
refuse while a class that has a mark in the subject this term is submitted,
checked or approved, naming the class: "JSS 2A's results are waiting for
approval. Send them back first to add a paper to Mathematics." The teaching
route answers 422. "A subject in a class" is read off the marks, as
`class_results()` reads it, so a class with no mark in the subject does not
refuse; a released class does not refuse either, its cards being frozen.
`results.ogun.apply_assessments()` was left alone: it replaces papers only for
a subject with no marks at all. Tests: `results/tests/test_chain_guards.py`.

**What is wrong.** A principal or administrator can add a paper to a subject in
the current term at any time (`gradebook/curriculum.py:149-163`,
`create_paper_as`). It checks the name is free and nothing else: not whether
any class's sheet is submitted, checked or approved.

A subject is "whole" for a child only when the child has a mark in every paper
of that subject for the term: `results/positions.py:252-258` counts the papers,
and `:418` requires `marked >= papers`. A subject that is not whole prints no
total and no grade (`results/card_api.py:1144-1148`) and the child is not
ranked (`positions.py:431-435`).

So adding "Project" to Mathematics while JSS 2A is approved makes Mathematics
incomplete for every child in JSS 2A. The new paper cannot be marked, because
the sheet is locked (`gradebook/services.py:285-311`). Releasing then freezes
cards with no Mathematics total and every child "not ranked"
(`results/cards.py:558-579`).

**How to reproduce (test idea).** Class with every paper marked; submit, check,
approve. Add a paper to one of its subjects. Release. Assert every
`ReleasedSubjectResult` for that subject has `is_complete=False` and every
`ReleasedCard.position` is null.

**Who could be harmed.** A whole class, on cards that have gone to parents.
A released card cannot have a mark corrected afterwards (the refusal text at
`gradebook/services.py:203-208` says so), so the only remedy is revising every
card after a send-back that release has made impossible.

**Smallest safe fix.** In `create_paper_as` (and `delete_paper_as`), refuse
while any `ResultSheet` for the term is past draft, naming the classes.
A stronger version is F-03's.

### F-03. A child who does not take a subject is "not ranked", and papers are school-wide, not per class (High, known rule)

**What is wrong.** There is no record of which subjects a child takes.
`results/positions.py:431-435` ranks only a child who is whole in **every
subject anybody in the class has a mark in**. `docs/positions.md:131` states
this and calls it "the first thing to look at".

Two ordinary cases follow from it:

- One class where some children take CRS and others IRS, or SS classes with
  electives: nobody is whole in both, so **no child in the class is ranked**.
- A paper belongs to a term and a subject, not to a class
  (`gradebook/models.py:107-112`, unique on term, subject, name). If the junior
  classes have a "Practical" paper in Basic Science and a senior class is also
  marked in a subject of that name, the senior children can never be whole in
  it. The count at `positions.py:252-258` is over the whole school.

**How to reproduce (test idea).** One class, two children, subjects A and B,
all papers marked for child 1 in A and child 2 in B only. Assert
`class_results().positions == {}`.

**Who could be harmed.** Whole classes print "not ranked" (or no position),
and the school has no way to fix it short of marking children in subjects they
do not take.

**Smallest safe fix.** Needs a decision from the school side first. The
smallest code change that removes the worst case: treat a subject as taken by a
child only if the child has at least one mark in it, and rank children who are
whole in every subject *they* have a mark in. That changes the stated rule, so
it is the owner's call, not a patch. Per-class papers are a larger change.

### F-04. Children's data has no retention period, no erasure route and several open legal items (High, data protection)

**What is stored.** For each child: name, admission number, class history,
sex, date of birth, learner ID, photo (`academics/models.py:432-470`), marks,
attendance, conduct ratings, teachers' remarks, a health record of height and
weight per term (`results/health.py`), fee ledger, exam answers and a per-seat
event log (`cbt/models.py`), and guardians' names, phone numbers and emails
(`accounts/models.py:554-592`, `:1353`).

**What is wrong or undecided.**

- **Kept for ever.** Nothing deletes or anonymises a child's records when the
  child or the school leaves. `privacy.html:114` has the open note "set how
  long records are kept after a school leaves".
- **No erasure route.** `accounts/deletion.py:326` `hard_delete_user()` exists
  but nothing calls it (no view, no command), and by its own docstring it
  refuses while any school's schema still refers to the person. A school's rows
  refer to a child by a bare `student_membership_id`, so there is no function
  that removes a child from one school's schema. An NDPA erasure request has to
  be done by hand in SQL.
- **Backups.** Media backups keep monthly copies for 12 months
  (`deploy/media-backup.sh:107`); a deleted child stays in them that long.
  Reasonable, but it has to be said in the notice (`privacy.html:116` is still
  a TODO).
- **Leaves Nigeria.** Backups go to Backblaze B2 (EU) and error reports to
  Sentry (EU) (`privacy.html:93-94`); the basis for transfer under Part VIII of
  the NDPA is an open TODO. SMS goes to Termii, payments and each child's
  made-up customer record to Paystack (`settings.py:777`).
- **Open before a real school signs:** the data processing agreement with each
  school (`privacy.html:31`), the Data Protection Officer (`:160`), parental
  consent under section 31 (`:125`), whether height and weight are sensitive
  personal data (`:132`), the time limit for answering a request (`:146`).

**What is sound here** (so it is not re-audited): Sentry is set to send no
personal data, no request bodies and no local variables
(`settings.py:987-998`); backups are encrypted before they leave the server;
sign-in codes and reset tokens are stored hashed and sealed in transit to the
worker; the password reset log keeps a digest of what was typed, not the text
(`accounts/password_reset.py:199-208`). It does keep the caller's IP address
with no expiry (`PasswordResetLog`, append-only), which belongs in the
retention decision.

**Who could be harmed.** Children and parents (data kept with no end date);
Classnode and each school (a complaint to the NDPC with no DPA, DPO or
retention rule to point at).

**Smallest safe fix.** Not code first: settle the retention period, the DPA
and the transfer basis. Then one management command that removes one child's
rows from one school's schema and writes an audit line, and a dated purge of
`PasswordResetLog`, `SignInAttempts` and the CBT event log.

### F-05. Results can be submitted, approved and released with papers unmarked and nothing says so (Medium)

**Status.** Fixed in PR #340. `submit`, `check` and `approve` count the
class's unmarked papers per subject under the sheet's lock
(`results/unmarked.py`) and refuse with `UnmarkedPapers` unless the caller
sends that count back; the routes answer 428 with the count per subject, and
the page shows it with "Submit anyway", "Check anyway" or "Approve anyway".
The count is written on the step's row,
`ResultSheetTransition.unmarked_papers` (migration `results/0039`). A subject
nobody in the class has a mark in is not counted, for F-03's reason. `release`
was not changed. Tests: `results/tests/test_chain_guards.py`,
`tests/js/chain.test.js`.

**What is wrong.** `submit`, `check`, `approve` and `release`
(`results/services.py:633-816`) check who is asking and the sheet's state.
None looks at whether every child has every mark. The only check at release is
who has no card at all (`results/omissions.py:63-141`). `results/chain_api.py`
reports "left out" (no card) and has no count of unmarked papers.

A child with one paper unmarked gets no total and no grade in that subject and
is "not ranked" (`docs/positions.md:111`). That is the documented rule for a
child who missed a paper, but the same thing happens when a teacher simply has
not finished, and the chain treats both alike.

**How to reproduce (test idea).** Class of two, one child missing one mark.
Submit, check, approve, release as the right people. Assert all four succeed
and the chain API's answers never mention the missing mark.

**Needs checking.** The broadsheet preview does show blanks, so a careful
principal can see it. What would confirm the gap matters in practice: open the
results page as a class teacher and as a principal with one mark missing and
see whether any screen counts or names it before the button is pressed.

**Who could be harmed.** A child whose teacher forgot one cell: released as
"not ranked" with a subject blank, and marks cannot be changed after release.

**Smallest safe fix.** Have the chain's list (`chain_api.py:344-362`) carry,
per sheet, the number of children with an unmarked paper (it is
`len(roster) - len(results.whole_students)` from one `class_results()` call),
and have `submit` refuse or ask for confirmation when it is not zero.

### F-06. "This card has gone home" is asked of the conduct rows, so a school with conduct off loses the lock after a class move (Medium, partly known as issue #34)

**Status.** Fixed in PR #340, in the service. Both lookups now ask
`results.cards.a_card_went_home()`. Tests:
`gradebook/tests/test_release_guard.py`, where the test that asserted the gap
is replaced by one that asserts the lock. **Still open:** the database trigger
`gradebook_scores_stop_at_release` (`gradebook/0002`) asks
`results_releasedtraitrating` in the same way, so a write that goes round the
service (an import, a shell) for a moved child at a school with conduct off is
still accepted. Re-keying it is a migration and was outside the two-line fix.

**What is wrong.** The guard that stops a mark changing after release has two
halves. One asks whether the child's **current** class's sheet is open
(`gradebook/services.py:281-287`). The other asks whether a card went home, and
asks it of `ReleasedTraitRating` (`gradebook/services.py:192-196`; the same in
`cbt/ca.py:81` for Send to CA). `results/ratings.py:1119-1126` writes no such
rows when the school has no conduct group switched on. The docstring at
`gradebook/services.py:176-185` records this gap and points to issue #34.

Since then `ReleasedCard` exists for every released child, and
`results/cards.py:642` `a_card_went_home()` answers the question for every
school. The two guards above were not moved to it.

**How to reproduce (test idea).** School with every trait group off. Release
JSS 1A for the current term. Move one child to JSS 1B (draft). As a teacher,
`PUT` a different mark for that child on a current-term paper. Assert it is
accepted today; it should be `MarksLocked`. Repeat through
`cbt.ca.send_as` with "replace".

**Who could be harmed.** The family's card is frozen and does not change, so
the released card stays right. What goes wrong is the record behind it: the
gradebook, JSS 1B's broadsheet and any later revision of the card now disagree
with what the parent holds, and JSS 1B's positions count marks the child was
already released on.

**Smallest safe fix.** Replace both `ReleasedTraitRating` lookups with
`results.cards.a_card_went_home(membership, assessment.term)`. Two lines; the
existing tests for the conduct-on case should pass unchanged.

### F-07. The time an offline CBT answer was chosen is taken from the device (Medium)

**What is wrong.** `cbt/sitting.py:589-601` (`_when`) reads `chosen_at` from the
request and only caps it at the server's "now". `:634-641` then refuses an
answer only if that claimed time is after the deadline, or if it arrives after
the deadline plus the test's late window. So any answer that arrives inside the
late window with a `chosen_at` before the deadline is counted, whenever it was
really chosen.

The paper stays on the device, so a student who keeps the page open (or sets
the device clock back, or edits the queued request) can go on answering after
time is up and have every answer accepted, for as long as the late window
(`test.late_window` minutes).

`_wins` (`:604-610`) uses the same claimed time to decide which of two seats'
answers counts, so a replaced seat can also win by claiming a later time.

**How to reproduce (test idea).** Start an attempt with a 10-minute duration
and a 5-minute late window. With the clock moved to deadline + 3 minutes, call
`sync` with an answer whose `chosen_at` is deadline - 1 second. Assert it is
accepted with no refusal.

**Who could be harmed.** Honest students in the same test, and the CA mark the
score is scaled into. This is partly inherent to sitting offline through a
power cut; the point is that the late window is in effect extra time for a
student who knows.

**Smallest safe fix.** Keep the rule, bound it: accept a pre-deadline
`chosen_at` after the deadline only if the session was not seen by the server
in that gap (`AttemptSession.last_seen_at` is already kept, `:681-691`). A seat
that was online and heartbeating at the deadline has no offline answers to
deliver late. And show the count of answers received after the deadline beside
the score on the results page so the teacher can judge.

### F-08. A test set without the exam PIN is opened by an admission number alone (Medium)

**What is wrong.** When `test.require_pin` is false, `cbt/sitting.py:322-325`
proves a student with `_student_without_pin` (`:304-311`): the test code, which
the whole room is told, and an admission number, which is on every class list
and usually runs in sequence. `cbt/release.py:208` opens released scores and
the per-question corrections on the same proof.

So one student can start (and use up) another's only attempt, sit it badly for
them, or after release read another student's score and which questions they
got wrong.

**What bounds it.** Scores from a no-PIN test never go to a CA column
(`cbt/ca.py:46`, `:217-218`), so report cards are not reachable this way. The
teacher's results page shows the seat and a "not me" event.

**How to reproduce.** Set and publish a test with the PIN switched off. At
`/sit/`, type the code and a classmate's admission number. The door opens in
their name.

**Who could be harmed.** The student impersonated; any student whose test
score is read by a classmate.

**Smallest safe fix.** Keep no-PIN tests for practice, but require the PIN on
`/test-scores/api/open/` always (the student has a slip), and say on the test's
settings, where the PIN is switched off, that anybody with the class list can
sit as anybody.

### F-09. Wrong-PIN limits are keyed on the victim's admission number, so a classmate can lock a student out (Medium)

**What is wrong.** The exam door counts failures per admission number and
refuses **before** checking the proof once the count is reached
(`cbt/sitting.py:379-387`): ten wrong tries in fifteen minutes
(`settings.py:592`) and the right PIN is refused too. Ten tries with a
classmate's number and any PIN, from any phone on the school's host, and that
classmate cannot sign in to the test for up to a quarter of an hour. The
counter is cleared only by a correct sign-in (`:388`), which the lockout
prevents.

The same shape, with less at stake, is at the result checker
(`results/checker.py:326-335`) and the password door
(`accounts/signin.py:145-152`, ten per identifier): the page says "Nothing has
been locked", but for the window the right password is refused as well.

**How to reproduce.** Post ten wrong PINs for one admission number to
`/sit/api/door/`. Post the right one. It answers 429.

**Who could be harmed.** A student kept out of a timed test; a teacher kept
out of marking by anybody who knows their email address.

**Smallest safe fix.** At the exam door, when the admission-number bucket is
full, still check the proof and let a correct code and PIN through (count only
the wrong ones); the per-address bucket remains the brake on guessing. An
officer's "end the wait" on the sitting screen would also do.

### F-10. Signed-in pages have no Content-Security-Policy and escaping is by hand (Medium)

**What is wrong.** Every staff and parent screen is drawn in the browser by
template strings set with `innerHTML` (for example `static/marking/app.js:426`,
`static/card/app.js:65`), and each value is escaped by an explicit call to
`esc()` (`static/web/html.js`). There is no automatic escaping. A
Content-Security-Policy is sent only on a school's public website
(`schoolsite/views.py:128`) and on served files (`files/views.py:60`). The
signed-in pages send none, so one missed `esc()` on a name, a remark or a CBT
question would run a script with the session of whoever opens the page, a
principal included.

A pattern search found one value not escaped:
`static/signin/app.js:129` writes `school.name` straight into the page. A
school's name is set by platform staff only, so this is not reachable by a
school today.

**Needs checking.** The search matched simple `${a.b}` shapes only. What would
confirm coverage: a test that feeds every API a child's name and a remark of
`<img src=x onerror=...>` and asserts the rendered HTML of each `states.js`
contains it escaped; several `*.test.js` files already do this for their own
page.

**Who could be harmed.** Any user, if a second gap exists; the session cookie
is `HttpOnly`, but the script could act as the user.

**Smallest safe fix.** Escape `school.name` at `signin/app.js:129`. Then send
`Content-Security-Policy: default-src 'self'; script-src 'self'; object-src
'none'; base-uri 'none'` on the app pages. They load only their own modules and
an import map, so the import map needs a hash or a nonce; start with
`Content-Security-Policy-Report-Only`.

### F-11. Report card and fee answers carry no `Cache-Control: no-store` (Low)

**What is wrong.** The JSON answers under `/api/` (a child's card, the roll,
the fee account) and the family's copy of the card PDF are sent with no
`Cache-Control` header. `results/card_api.py:1611-1617` sets
`private, no-store` only for the copy with the health record. The sign-in,
reset and exam pages do set it.

Nothing in front of the app caches (Caddy is a plain reverse proxy and every
answer has `Vary: Cookie`), and the service worker does not keep `/api/`
(`sync/worker.js:44`). The exposure is a browser's own cache and "back" button
on a shared computer, which is exactly where the result checker is used.

**Smallest safe fix.** One middleware, or a ninja response hook, that adds
`Cache-Control: private, no-store` to every `/api/` answer that has not set its
own.

### F-12. Result-checker PINs are stored as a plain SHA-256 (Low)

**What is wrong.** `results/checker.py:257` stores `hash_token(pin)`, an unkeyed
SHA-256 of twelve digits. Exam PINs are stored under an HMAC with a server key
precisely so that a copy of the database cannot be searched
(`cbt/pins.py:89-92`, `settings.py:44-56`). Twelve digits is 10^12 hashes,
which is hours on one graphics card.

A copy of the database already holds the cards the PINs open, so the gain to a
thief is small: the PINs would let them open cards through the front door
without the theft showing.

**Smallest safe fix.** Hash new checker PINs with the same keyed digest as exam
PINs (school, child, term, PIN). Old slips keep working if the lookup tries
both for one session.

### F-13. After one card is revised, its position and class size can disagree with the rest of the class (Low)

**What is wrong.** `results/revision.py:165` recomputes
`positions.class_results()` from the live roster and freezes a new version for
one child. The other children's cards keep the position and `roster_size`
frozen at release. If the roster changed after release (F-01, F-06), the
revised card can say "3rd of 31" beside classmates' "of 30", or share a place
that the frozen cards give to somebody else. `results/api.py:494-520` already
documents that the broadsheet's rank is recomputed and is "not
`ReleasedCard.position`".

**Needs checking.** Whether a revision is ever expected to move a position,
given marks cannot change after release. If not, carry the position and class
size forward from the superseded card, as attendance already is
(`results/cards.py:359-390`).

### F-14. A mark can land just after a class is submitted, when the sheet row did not exist yet (Low)

**What is wrong.** `results/services.py:262-293` `locked_sheet_for` takes a row
lock on the `ResultSheet`, and returns `None`, holding nothing, when the class
has no sheet yet. A mark being saved at that instant passes the "open" check
(`gradebook/services.py:285-287`), and can commit after another request creates
the sheet (`services.py:629`) and submits it. The mark then sits in a submitted
sheet without the class teacher having seen it.

Narrow: it needs the first-ever open-and-submit of a class to overlap one cell
save. Reviewers still see the final marks before approval.

**Smallest safe fix.** Have the marking path create the sheet row
(`get_or_create`) before locking it, so there is always a row to lock.

### F-15. Offline copies of a marking sheet or register are shown to whoever opens the phone (Low)

**What is wrong.** The marking and register pages keep a copy of the last
answer in the browser's IndexedDB (`static/web/snapshots.js`, used by
`static/marking/app.js` and `static/register/app.js`). With no connection and
no way to ask who is signed in, `snapshots.js:148-152` shows the last person's
copy. Signing out clears it; a session that simply expired does not.

A class's names and marks on a teacher's own phone is a small exposure, and it
is the price of working offline. Recorded so it is a decision, not a surprise.

**Needs checking.** Leave a signed-in marking page, wait past the twelve-hour
session, go offline, reopen: is the sheet shown? If so, consider dropping
copies older than the session length.

### F-16. Roles to confirm (Low)

These are how the code behaves. Each may be intended; none is written down as
a decision that I could find.

- **Every teacher and the bursar can open every child's released card and
  PDF**, in any class (`results/card_api.py:148-156`, `:881`). A subject
  teacher is not limited to the classes they teach, though marking is
  (`gradebook/services.py:680-699`).
- **The administrator has full write on the fee books**: payments, discounts
  and reversals (`fees/authority.py:17`). The vice principal can read them
  (`:18`).
- **A member of staff who is also a parent** reads their own child's card as
  staff, so a card withheld for fees is not withheld from them
  (`card_api.py:878-885`; the settings comment at `settings.py:669-677` shows
  this is deliberate for password sessions).
- **Platform staff** pass every school's host with no roles
  (`accounts/middleware.py:142`). Every API read checked asks for a role, so
  they see pages but not data; they can revise a card
  (`results/revision.py:232-239`).

## 3. Checked and found sound

Traced through the code named; no fault found.

**Tenant isolation**

- A request's school comes from the host through `schools.Domain`; an unknown
  host is a 404 before any view (`schools/middleware.py`). School tables do not
  exist in the public schema, so a query from the portal errors instead of
  returning rows.
- A signed-in user with no active membership at the host's school is refused on
  every path that is not a door (`accounts/middleware.py:125-145`). What they
  may do is re-derived from the host on each request, never from the session.
- Every API that takes a child's ID also filters by the host's school
  (`card_api.py:841-846`, `enrolment_api.py:357`, `:787-795`) before any
  permission check.
- Files: a stored file is looked up in the current schema only, the row's
  schema is compared again before sending, and the path on disk is built from
  schema, key and a checked variant name (`files/views.py:40-45`,
  `files/storage.py:28-30`, `:65-68`). The proxy hands files over only on the
  app's `X-Accel-Redirect`. A crest, a class's PDF or a question picture of
  another school cannot be named from this school's host.
- Class print and broadsheet files are served only to the person who asked for
  them, while they still may print that class, and for 24 hours
  (`results/print_api.py:147-199`).
- Celery: every school task takes the schema name as its first argument and
  refuses to run without a real school (`schools/tasks.py:238-319`); the three
  platform tasks set the public schema themselves. No connection pooler
  (`settings.py:872`).
- Caches: the default cache is per-process memory and holds no school data that
  I found; the `sites` Redis cache is for published public pages.
  **Needs checking:** that every `sites` cache key includes the school
  (`schoolsite/services.py` was not read line by line).
- Service workers: one per origin, so per school. `/api/` is never cached; the
  worker keeps page frames with no data in them and clears on sign-out
  (`sync/worker.js:39-55`, `:81-83`). The exam worker is scoped to `/sit/`.
- Paystack: the webhook is signed, the transaction is verified with Paystack
  again, and the school is chosen from the receiving account number, not from
  anything in the request (`fees/webhook.py:89-142`).

**Authentication and sessions**

- Sign-in answers the same for a wrong password, an unknown identifier and a
  member of another school, and spends a password hash either way
  (`accounts/backends.py`, `accounts/signin.py:149-152`).
- Throttling is counted in Postgres per identifier and per address, and the
  address is taken from the one proxy hop the deployment trusts
  (`accounts/throttling.py:99-134`, `deploy/production.env`).
- The Django admin is on the portal host only and its sign-in goes through the
  same throttle (`accounts/forms.py`, `accounts/tests/test_admin_door.py`).
- A school-door session lives in a `__Host-` cookie and is refused on any other
  school's host (`schools/session_store.py:38-52`). Cookies are `Secure` and
  `HttpOnly`; HSTS and the HTTPS redirect are on in production.
- Forgot password: a 32-byte token stored hashed, 30 minutes, single use, older
  links cancelled, bound to the host it was asked from, the same sentence for
  every outcome, limited per account and per address
  (`accounts/password_reset.py:230-365`). Changing the password ends other
  sessions, because Django checks the session's password hash. Platform staff
  and blog accounts cannot be reset this way.
- Invitations: the link goes to the address already on the account, never to
  one typed by the inviter (`schools/delivery.py:153-177`), is refused on
  another school's host (`api.py:1196-1198`), and sets a password only for an
  account that has none.
- CSRF: every session-authenticated API route checks the token
  (`accounts/session.py:68-75`); sign-in and the guardian code routes check it
  by hand. The exam API is exempt and uses a `SameSite=Strict` cookie scoped to
  `/sit/`. No open redirect was found: "back" targets are fixed lists
  (`accounts/password_views.py:45-54`, `blog/write_views.py:101`).
- Parents: a card is opened only by the child, a guardian linked to that child,
  or staff (`card_api.py:849-887`). A guardian link made by typing a contact is
  not live until that guardian answers a code sent by this school
  (`accounts/guardian_contacts.py:340-353`, `:906-907`). A session opened by a
  one-time code holds the parent role only (`accounts/models.py:355-356`).
- Result checker: twelve-digit PIN per child and term, ten wrong tries per
  admission number and fifty per address a quarter hour, one sentence for every
  failure, dead once the next session starts (`results/checker.py:317-392`).
  A withheld card is withheld from a PIN too (`card_api.py:1770`).
- Exam PINs: eight digits under a keyed HMAC bound to school, child and term
  (`cbt/pins.py:89-92`); reprinting cancels the old one.

**Answer keys and other students' work**

- The paper sent to a device has no key and no explanation
  (`cbt/paper.py:22`, `:40-74`). A question's picture is served only to a live
  sitting of a test that contains it (`cbt/sit_views.py:286-306`).
- A parent's session is refused at the exam API (`cbt/sit_views.py:163-164`).

**Changing released results and locked records**

- A sheet moves one step at a time under a row lock, nobody signs two steps of
  one cycle, and a released sheet moves nowhere (`results/services.py:525-601`).
- A released card is a frozen copy of names, marks, totals, grades, position,
  attendance and remarks (`results/cards.py:399-474`); the family's page, the
  PDF, the whole-class print and the released broadsheet all read that copy
  (`results/class_print.py:141-162`, `results/api.py:494-520`,
  `results/broadsheet.py:344`), so they agree with each other. A later change
  to a grade band, a subject's name or the template does not reach it.
- Changing what a paper is out of, or removing it, is refused once it has a
  mark (`gradebook/curriculum.py:177-191`). A mark above the paper's maximum,
  a negative one or a half mark is refused (`gradebook/services.py:314-326`).
- Two people saving one cell: the second is told, not overwritten
  (`gradebook/services.py:420-491`).
- Fee ledger entries are append-only; a mistake is reversed by a new entry.

**Totals, grades, positions, rounding**

- Percentages are exact decimals rounded half-up to two places; an average is
  the mean of the rounded subject percentages (`results/positions.py:156-198`).
- Ties share a place and the next place follows on (1, 1, 2), the rule recorded
  in `docs/claude-memory/phase-1-results-decisions.md`
  (`positions.py:521-534`).
- A grade is the highest band whose minimum the percentage reaches, on the
  unrounded two-place figure; a scale must start at 0 and may not repeat a
  minimum or a letter (`results/grades.py:107-218`). Note for the school: 69.50
  is below a band that starts at 70.

**CBT marking and CA**

- A score is the sum of marks for answers that match the key after any key
  corrections, taken from the latest attempt (`cbt/marking.py:54-120`).
- Scaling into CA is integer round-half-up (`cbt/marking.py:123-125`).
- Send to CA writes through the gradebook's own function, so the marks lock,
  the subject-teacher rule and the version check all apply; a hand mark is
  replaced only on "replace" with a second confirmation, and a mark that
  changed since the preview is not overwritten (`cbt/ca.py:235-306`).
- An answer sent twice is recorded once (`cbt/sitting.py:622-624`); an answer
  after submit or after the late window is refused and logged
  (`:634-641`, `:713-717`).

**Fees**

- Money is whole kobo in integers end to end; the naira a person types is
  parsed on the server and refused, not rounded (`fees/api.py:22-23`,
  `fees/services.py:330-342`). The page formats kobo as text without floating
  point (`static/fees/money.js`).
- A payment form or a Paystack reference posts once however often it is sent
  (`fees/services.py:541-595`, `fees/webhook.py:60-61`, `:179-193`).

**Uploads, exports, XSS, secrets**

- Uploads are checked by content, re-encoded by the server and served with
  `nosniff` and a sandbox policy; PDFs and spreadsheets download as attachments
  (`files/service.py:155-180`, `files/views.py:57-63`). No SVG or HTML is
  accepted.
- The Excel broadsheet writes every name as text, so a name beginning with "="
  is not a formula (`results/broadsheet_files.py:284-303`).
- Server templates escape by default; the only `|safe` values are import maps
  built from static paths, the platform's own FAQ, and blog HTML that has been
  through the `nh3` sanitiser (`blog/markdown.py:93-98`). A school website's
  links must be `https` and embeds must be YouTube or Vimeo
  (`schoolsite/sections.py:105`, `:201`).
- No secret is in the repository: settings read every key from the environment
  and refuse to start without `DJANGO_SECRET_KEY` (`settings.py:34-42`);
  `docs/handover.md:103` records a history scan. `DEBUG` is off unless asked
  for, and the code-showing outbox is routed only under `DEBUG`
  (`urls_public.py:77-80`). The app container does not run as root
  (`Dockerfile:74-75`). Redis and Postgres are not published outside the
  compose network.

## 4. Not covered, or only skimmed

Say so plainly: these were not traced line by line, and a clean section 3 does
not cover them.

- **Attendance** (`attendance/`): the register, who may mark, and how days
  present reach the card. Only the card side was read.
- **Promotion and the end of a session** (`academics/promotion.py`,
  `results/sessions.py`): session averages across three terms, a child who
  joined mid-session, promotion decisions. Not traced. Given
  `docs/claude-memory/luffy-session-arithmetic.md` records past bugs here, this
  deserves its own pass.
- **Term changes**: `set_current_term` and carry-forward of placements and
  subject teachers were read (`academics/services.py:301-389`, `:488-510`) but
  not what each module does with a term that stops being current mid-work
  (papers and placements are tied to "the current term").
- **Ogun report card and OGSERA export** (`results/ogun.py`,
  `results/ogun_card.py`, `results/ogsera.py`): whether the Ogun layout's
  figures equal the Standard card's for the same frozen card. Both read the
  same payload (`card_api.py:1477-1482`), which is why section 3 says the
  prints agree, but the Ogun arithmetic itself was not checked.
- **Remarks and conduct ratings** (`results/comments.py`,
  `results/ratings.py`): who may write, and their own locks.
- **CBT question banks and test setting** (`cbt/access.py`, `cbt/bank_api.py`,
  `cbt/setting.py`, `cbt/sittings.py`): which teacher can read which bank and
  its answers, approval of a test, retakes, extra time, the exam officer's
  powers.
- **Transfers between schools** (`accounts/transfers.py`), **roll import**
  (`accounts/bulk.py`), **student details** (`academics/details.py`).
- **Fee schedules, concessions, reminders and the dashboard totals**
  (`fees/schedules.py`, `fees/billing.py`, `home/dashboard.py`,
  `notices/`): the ledger core was read; that the dashboard's sums equal the
  ledger's was not checked.
- **School website editor API and picture handling** (`schoolsite/api.py`,
  `schoolsite/pictures.py`, `schoolsite/services.py`), and the **blog's**
  writer workflow.
- **Messaging providers** (`messaging/`, Termii, the email provider): what
  text leaves the platform and whether a child's name is in it.
- **PDF rendering** (`results/pdf.py`, `files/pdf.py`): whether WeasyPrint can
  be made to fetch a URL from user text. User text is escaped in the templates
  read, but the fetcher settings were not checked.
- **Deploy scripts** beyond the cron table, compose ports and backup
  retention; the GitHub workflows; database backup retention
  (`deploy/postgres/retention.py`).
- **The test suite**: not run, and not read for gaps.
