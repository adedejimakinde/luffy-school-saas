# CBT: computer-based tests

Status: **Phase 1, design only.** No feature code. The screens are in
[`docs/mockups/cbt/`](mockups/cbt/index.html), each at 375 and 1280 px in
`docs/mockups/cbt/shots/`. The owner's decisions of 20 October 2026 are folded in
below and summarised next. No question is open.

## Decisions

| topic | decided |
| --- | --- |
| Power cuts | A student whose computer switches off signs in again, on the same or another computer, and continues with the time left. See "Power cuts and resuming". |
| Extra time | A teacher of the test, an exam officer or the administrator can give one student extra minutes, with a reason. Logged. |
| Names | "UTME-style practice" and "WASSCE-style objectives". See "Names and claims". |
| Sign-in | Option B: test code, admission number, exam PIN. Option A only as a per-test switch, only for tests that cannot send scores to CA, enforced on the server. Option C later. |
| Cross-subject practice | UTME-style practice is set by the principal, who can name exam officers. Naming one is a permission, and it is logged. |
| Vice principal | Sees banks and results. |
| Administrator | Runs sittings, not content. Can print PIN slips, open and close sittings, change a test code, give extra time with a reason, and see the sitting log. Cannot see or edit banks, or see a test's questions before it opens. Sees scores only after release. See "The administrator". |
| Late window | Default 2 minutes, at most 5. |
| Release | Final, like results. Undoing it uses a restore action with a reason. |
| Marking sheet | Narrowed by subject-teacher assignments once a school has made some. Until then today's behaviour stands and the principal sees a prompt. |
| PIN slips | The principal, an exam officer or the administrator prints them per class as a PDF. Printing again cancels the old PINs. Logged. |

### Phase 2 order

One PR per step, each cut from `main`.

0. Demo slug guard.
1. Subject-teacher assignment.
2. Student exam PIN and slips.
3. Question bank and tests.
4. Test screen, with offline and power-cut resume.
5. Marking, send to CA and release.
6. UTME-style and WASSCE-style modes.

Two layers on one engine:

1. **School CBT.** Teachers write multiple-choice questions into a bank per subject
   and class level, set timed tests for their classes, the computer marks them, and
   the teacher can send scores into a CA column. Scores reach report cards only
   through the existing results chain.
2. **Exam modes.** UTME-style practice and WASSCE-style objectives are the same test
   with a different format and screen. Every number in a format is a setting.

Questions are the school's. Nothing from JAMB, WAEC or NECO is seeded, scraped or
copied, and production holds no question a school did not write (or, later, one a
licensed provider supplies after the platform turns it on).

## What exists today that this leans on

Read on `main` at `9062dde`.

| fact | where | what it means for CBT |
| --- | --- | --- |
| A CA column is an `Assessment` (term, subject, `max_score`); a mark is a `Score`, written through `set_score_as()` with the version the writer was shown | `gradebook/models.py`, `docs/gradebook.md` | Send to CA is a caller of `set_score_as()`, never a second write path. A submitted or released class already refuses. |
| "Not marked yet" and "scored zero" are different facts: no row means not marked | `docs/gradebook.md` | A student who did not sit gets **no** CA mark, never a zero. |
| **Teachers are not assigned to subjects.** Any teacher may mark any paper; the one assignment is the class teacher | `docs/teaching.md` | "Teachers see only their own subjects and classes" needs a new assignment. It is Phase 2 step 1. |
| **Students cannot sign in.** A student account is made with `create_user(username, None)`: no usable password, and no flow sets one. There is no password reset for anyone | `accounts/services.py:559`, `docs/membership.md` | Students need a door. See "Student sign-in". |
| The student credential is an exam credential; exam surfaces never render for a guardian | `docs/parent-access.md` D1, D2, D4 | A parent's session never reaches a test screen. |
| The result checker opens a card with an admission number and a PIN from a paper slip: PINs stored as digests, one refusal for every failure, counted and never locked | `results/checker.py` | The recommended student door is the same pattern. |
| The teacher outbox and `SyncReceipt` idempotency keys; the service worker is deferred for teachers | `docs/offline.md` S3, S4, S5 | The test page reuses the outbox idea and needs its own small service worker from day one. |
| `seed_demo` runs only with `DEBUG`; `load_demo` only with `DEMO_SERVER=1` and refuses if a real school exists | `schools/management/commands/` | Demo questions go only through these. **Gap, closed by Phase 2 step 0:** nothing stopped `create_school()` making `sunrise-demo` in production. |

## Names and claims

The two modes are called **UTME-style practice** and **WASSCE-style objectives**.
Where the app says where a default came from, it says **"Defaults based on the
published UTME format"**, and does not name a body's manual or paper.

- No JAMB or WAEC logo, name in a heading, or wording that suggests the app is an
  official, approved or endorsed practice. A practice score is shown as a practice
  score and never as a result or a prediction.
- Nothing written or copied from any exam body's questions.
- The mockups follow this: the test screen's top band is Classnode's, and nothing
  on it imitates a centre's branding.

## Formats: every number is a setting

| | default | where it came from (for maintainers, not shown in the app) |
| --- | --- | --- |
| UTME-style | Use of English 60 questions (everyone), three other subjects 40 each, 180 in all, options A to D, **2 hours** on one timer | The 2026 UTME format as the exam body published it for its officials, read in October 2026. Re-read each year. |
| WASSCE-style | One subject per paper, its own timer, A to D. Mathematics: 50 questions, 90 minutes. Other subjects: 50 questions, 60 minutes, as **school defaults to check** | Mathematics from widely copied syllabus text, not confirmed against the exam body. The printed paper decides the time in a real exam. |

Defaults live in one constants module with their source and date, and are copied
into an `ExamFormat` row per school and subject that the school edits (screens 4b,
4c). Nothing in code reads a count or a duration from anywhere else.

## Data model

A new tenant app, `cbt`, plus one table in `academics`. Each "never changes" is a
trigger named for its rule (operating rule 3); each act that produces nothing when
it says no writes a row (rule 8).

### Who teaches what

`academics.SubjectTeacher(term, class_group, subject, teacher_membership)`, unique
on the first three. A teacher's banks are the (subject, level) pairs they hold this
term; their classes are the class groups.

**It also narrows the marking sheet, but only once a school has made
assignments.** Today any teacher may mark any paper (`can_enter_marks`). From the
first `SubjectTeacher` row a school makes in a term, a teacher can enter marks only
for the subjects and classes assigned to them; the principal and the administrator
still enter marks for any. Until a school has made any, nothing changes and the
principal sees a prompt on Home and on `/teaching/`: "Say who teaches what. Until
you do, any teacher can mark any subject, and tests cannot be set." The prompt goes
once the first assignment exists. A school half-assigned is a real state, so the
prompt also lists subjects and classes that still have nobody. This is a change to
the gradebook's authority check, so it carries controls (below).

### Exam officers

`ExamOfficerGrant(membership, kind, by, at, note)`, where kind is `named` or `ended`, append-only:
the principal names a teacher, the vice principal or **the administrator** with a
`named` row, and ends it with an `ended` row; the latest row decides. Both are logged
with who and when. An exam officer can:
set cross-subject UTME-style practice, print PIN slips, give extra time, and allow
a retake. Nothing else: not release, not send to CA, not see another teacher's bank.

**An administrator named exam officer has exactly these exam officer rights, on top of
what the role has.** Being named does not open banks to them: an exam officer's
banks are "their own, as a teacher", and an administrator has none.

### The administrator

The administrator runs the school's sittings and does not touch their content
(decided 20 October 2026).

| | |
| --- | --- |
| **Can** | print PIN slips (below); open and close sittings; change a test's code; give one student extra time with a reason, logged; see the sitting log: who started, dropped off and submitted, and when |
| **Cannot** | see or edit question banks; see a test's questions before the test opens |
| **Scores** | sees CBT scores only after release, the same moment a student does |
| **Not included** | anything done with a score, such as send to CA and release, which stay with the teacher and the principal as above |

How the can-do items work:

- **Open and close a sitting.** A sitting is a test being open to a class. The test
  has its own window (`opens_at`, `closes_at`); opening or closing a sitting early by
  hand writes `SittingControl(test, class_group, kind, by, at, reason)`, append-only,
  where kind is `opened` or `closed`, and the latest row decides whether students of
  that class can start. Closing never discards answers: an attempt in progress goes
  on to its own deadline unless the close says to end it, and that is logged too.
  The test window is not rewritten, so the record of what was planned survives.
- **Change a test code.** Replaces the digest and writes `TestCodeChange(test, by,
  at)`, never the code itself. A student already inside an attempt is not signed out
  (the code is a gate to start and to resume, not to continue); a student who must
  sign in again after a power cut needs the new one.
- **The sitting log** is the log on screen 7 without the answers: events and times
  per student, `extra_time` and `replaced` included, but no score, no item, no chosen
  option. A teacher's or the principal's view is screen 7 as drawn; the
  administrator's is its Students table alone.
- **Questions before the test opens.** The administrator never sees a bank, and never
  sees the questions of a test that has not opened: not in the preview, not in a
  results page, not in a PIN slip. Draft and published-but-not-yet-open tests show
  the administrator their title, class, window, size and code state only.

### Banks and questions

| table | key columns | rules |
| --- | --- | --- |
| `QuestionBank` | subject, level | unique (subject, level). Seen by its subject's teachers at that level and the principal. |
| `Question` | bank, stem, image, image_alt, explanation, topic, option_count (4 or 5), correct_index, version, retired_at, source (`school` / `provider`), provider_slug, provider_ref, derived_from (provider, ref) | CHECK `correct_index < option_count`. A provider question refuses UPDATE (trigger); only the platform's removal deletes it. Used questions are retired, not deleted. |
| `QuestionOption` | question, position, text, image | `position < option_count`. |

### Tests

| table | key columns | rules |
| --- | --- | --- |
| `Test` | title, kind (`class` / `utme_style` / `wassce_style`), term, state (`draft` / `published` / `closed`), opens_at, closes_at, duration, late_window, shuffle_questions, shuffle_options, can_go_back, grid, calculator, require_pin, code_digest, created_by | The test code is stored as a digest, like a checker PIN. |
| `TestSection` | test, subject, question_count, position | One for a class test or a WASSCE-style paper; English plus the subjects offered for UTME-style practice. |
| `TestAudience` | test, class_group | Who may see and sit it. Every change after publishing writes `TestAudienceChange` (who, when, added/removed): access is the area this guards. |
| `UtmeSubjects` | test, student, three subjects | A student with none cannot start (screen 4b). |
| `TestItem` | test, section, position, stem, options (text and image per option), correct_index, explanation, attribution, origin question and version | **Copied at publish** (rule 2): a bank edit never reaches a published test. Trigger `a_published_item_is_frozen`. A wrong key is fixed by a `KeyCorrection` row (item, old, new, by, reason), never by an edit, and only before release. |
| `ExamFormat` | kind, subject, question_count, duration, source | The settings above. |

### Sitting

| table | key columns | rules |
| --- | --- | --- |
| `Attempt` | test, student_membership_id, number, started_at, deadline, submitted_at, ended_by (`student` / `clock` / `teacher`), item_order, option_orders | Times are the **server's**. `deadline = min(started_at + duration + extra, closes_at + extra)`, where `extra` is the sum of the attempt's `TimeExtension` rows. Unique (test, student, number); a second number needs a `RetakeGrant`. |
| `AttemptSession` | attempt, device_token_digest, signed_in_at, ended_at, ended_by (`student` / `replaced` / `submit` / `clock`), sync_offset | One row per computer that holds the attempt. At most one row per attempt with `ended_at` null (partial unique index). |
| `TimeExtension` | attempt (or test and student before they start), minutes, reason, granted_by, at | Append-only. Reason is required. |
| `RetakeGrant` | test, student, granted_by, reason, at | Append-only. |
| `AnswerEvent` | attempt, session, item, chosen (original option index, or none for cleared), client_seq, chosen_at (server time as the device estimated it), received_at, accepted, refusal, superseded_by | Append-only. Unique (session, client_seq) is the idempotency key. The answer for an item is the accepted event with the latest `chosen_at`. An event that loses is kept, with `superseded_by` set by a new row, never an update. |
| `AttemptEvent` | attempt, kind (`start`, `not_me`, `disconnect`, `reconnect`, `resume`, `replaced`, `submit`, `clock_submit`, `late_refused`, `extra_time`), at, said_by (`server` / `device`), detail | Append-only. The log on screen 7. |

**No score is stored** while a test is live: it is computed from answers and keys on
read, as `total_for()` does for marks. It is frozen at release.

### Release and CA

| table | key columns | rules |
| --- | --- | --- |
| `TestRelease` | test, class_group, released_by, at | **Final, like a results release.** The frozen scores never change. |
| `TestReleaseRestore` | release, restored_by, reason, at | Append-only. **Undoing a release is a restore with a reason**, by the principal only. It hides the scores from students and parents again and shows the teacher why. The frozen rows are not deleted or edited; a later release serves them again, or a key correction (before a re-release) makes new frozen rows at the next version. A restore never touches a CA mark already sent. |
| `ReleasedTestScore` | release, student_membership_id, student_name, test_title, subject_name, score, out_of, section scores | Append-only, names copied (rules 1, 2). The only thing a student or parent score page reads. |
| `CaTransfer` | test, assessment, rule (scale, rounding), existing (`keep` / `replace`), by, at | One per send. |
| `CaTransferLine` | transfer, student, test score, mark, outcome (`written`, `kept`, `not_sat`, `locked`, `changed_meanwhile`), previous value | Append-only. Four of five outcomes write nothing to the gradebook, so the line is their only record (rule 8). |

## How scores reach CA

1. The teacher picks a CA column: an `Assessment` of the test's subject and term,
   for classes the teacher teaches (screen 8a).
2. Each mark is `round_half_up(score / out_of x max_score)`, a whole number because
   `Score.value` is one.
3. A preview reads every affected `Score` and its version. Nothing is written.
4. On confirm (8b), for each student who sat, `set_score_as()` with the version from
   the preview:
   - **did not sit:** no call, line `not_sat`. No zero.
   - **has a mark, keep:** no call, line `kept`.
   - **has a mark, replace:** written with the preview's version; a mark typed since
     the preview raises `ScoreChangedMeanwhile` and the line says so. Nothing is
     overwritten that the teacher was not shown.
   - **class submitted or released:** the gradebook's own refusal, line `locked`,
     and the screen says who to ask.
5. From there the marks are ordinary marks. They reach a report card only when the
   class's sheet is submitted, checked, approved and released, and the card is frozen
   by `results`. CBT never writes a `results` table.

Sending again with "keep" writes only the new ones, so a teacher who sends before
SS 2B's sheet is sent back can send again after.

## Student sign-in

Decided: **option B**, test code plus admission number plus exam PIN. The options
considered, kept so the reasoning can be checked:

| | how | for | against |
| --- | --- | --- | --- |
| **A. Test code + admission number** | The teacher reads out a six-letter code when the sitting starts; the student types it and their admission number | Simplest. Nothing to print or remember. | Admission numbers are written on exercise books (`checker.py` says as much). Anyone in the room who hears the code can start another student's attempt, use up their one attempt, or sit as them. Only the invigilator stands in the way. |
| **B. A + exam PIN from a slip (chosen)** | As A, plus an 8-digit PIN printed once a term on a slip per student, like the checker's | Knowing a number is no longer enough. Reuses `checker.py`: digests, one refusal, counted never locked. No password, no reset flow: a lost slip is reprinted and the old PIN stops working. | A slip to print and hand out each term. A student who shares their slip shares their tests. |
| **C. Student passwords** (`parent-access.md` D4) | A password the student sets | The durable answer, and what home practice needs. | Nothing exists: no first-password flow for students, no password reset for anybody, young students have no email or phone to reset through. |
| **D. Teacher admits each seat** | The teacher signs in on each computer and picks the student | Strongest in the room. | Forty sign-ins per sitting, and a teacher's session left on a lab computer. |

- **Option A is a per-test switch, and only for tests that cannot send scores to
  CA.** Turning the exam PIN off sets `Test.require_pin = false` and
  `Test.may_send_to_ca = false` together, and a check constraint refuses the
  combination `require_pin = false` with `may_send_to_ca = true`. The send-to-CA
  service checks the flag itself, so a hand-edited request or a later code path
  cannot get round the screen. Turning the PIN back on is allowed until the first
  attempt starts; after that the test's sign-in cannot change. A released score from
  a test without a PIN can be seen by the student and the parent but never reaches a
  CA column. (Screen 4a shows the switch and says so.)
- **Option C later**, when home practice is wanted.
- The door is `/sit/` on the school's own host, like the checker, because it makes no
  account session. What it makes is a cookie scoped to `/sit/` and to one attempt; no
  other route accepts it, and it ends at submit.
- The test code is the first gate: wrong code, wrong number and wrong PIN all get one
  sentence (the checker's oracle rule). Throttled per admission number and per
  address.
- Eight digits, not the checker's twelve, because a PIN only works behind a test
  code that is live for one sitting. If that does not survive review, twelve costs
  only typing.
- "Is this you?" (5b) comes before the clock. "This is not me" ends it and logs
  `not_me`.
- A guardian session never reaches `/sit/` (D2).

### Exam PINs and slips

`ExamPin(student_membership_id, class_group, term, digest, issued_by, issued_at,
cancelled_at, cancelled_by_print)`. **The principal, an exam officer or the
administrator prints slips per class, as a PDF**, through the same rendering path as checker slips
(`results/pdf.py`). Printing for a class again **cancels every earlier PIN for that
class** in the same transaction and writes `PinSlipPrint(class_group, printed_by, at,
count, cancelled_count)`. Reprinting for one student (a lost slip) cancels only that
student's. PINs are shown once, on the PDF, and kept only as digests. This matches
today's checker slips, which the principal and the administrator both print.

## Offline

The test keeps going without a network; the server stays the timekeeper.

- **At start** the server writes the `Attempt` and returns the whole paper in this
  student's order, options shuffled, images included. **No keys and no
  explanations** ever reach the device. With it come `deadline` and the server's
  `now`; the device counts down from the difference on its monotonic clock, never
  its wall clock.
- **Each choice** goes to IndexedDB first, then to the server with a `client_seq`.
  The outbox resends until acknowledged; the unique key makes a resend harmless
  (`docs/offline.md` S3, S4).
- **A small service worker** keeps the `/sit/` page itself, so a reload with no
  network reopens the attempt from IndexedDB. Teachers' pages deferred theirs (S5);
  this page needs one from the start, and only this page.
- **Disconnects** are logged twice: the server notes a gap in the page's 20-second
  heartbeat, and the device reports its offline spans when it is back. Each event says
  who said it.
- **At zero** the device stops taking answers and sends what it holds. The server
  accepts an answer only if it arrives by `deadline + late_window` **and** the device
  says it was saved before time. Later than that it is refused and logged
  (`late_refused`), shown to the teacher (screen 7) and never counted. The server
  closes the attempt at `deadline + late_window` whatever the device does.
- **The honest limit:** inside the window the server trusts the device's word that
  an answer was chosen in time. A student who pulls the cable gains at most the
  window. It defaults to **2 minutes, goes up to 5**, and 0 turns it off.
- **Shared computers:** the local copy is deleted once the server acknowledges the
  submit, and on "This is not me". Copy on screen 6e says so. A copy that cannot be
  sent stays until it can; the server refuses it if it is late.
- Chrome on Android and desktop Chrome are in scope; Safari gets the warning
  `docs/offline.md` OPEN-6 already decided.

## Power cuts and resuming

A school computer will switch off in the middle of a test. The student must not lose
the attempt, and must not gain time or a second copy of it.

- **Signing in again continues the same attempt.** The student goes through `/sit/`
  with the same test code, admission number and PIN, on the same computer or another.
  The server finds the open attempt, writes `resume`, and sends back the whole paper
  in the same order, the answers it holds, and the time left. The clock never
  stopped: `deadline` is unchanged, so the power cut costs the student the minutes it
  lasted. A teacher can give those back with extra time (below).
- **Only one computer holds the attempt at a time** (`AttemptSession`, one open row
  per attempt). Signing in on a second computer ends the first, writes `replaced`
  with both computers' tokens, and the first, if it comes back, is told it has been
  replaced and shows a plain screen saying so. The log says which seat and when. No
  question is asked of the student: whoever has the PIN holds the attempt.
- **Answers still on the first computer** are sent if it comes back on, in the
  ordinary way, with their `chosen_at`. The server keeps **every** answer event and
  decides which one counts: **an answer replaces another only if it was chosen
  later.** `chosen_at` is the device's estimate of server time: its sync offset taken
  at sign-in plus its own monotonic clock, never its wall clock. Both events stay in
  the log, the loser marked `superseded_by` the winner, so a teacher reading screen 7
  can see "Q12: B at 08:21 on seat 4, then C at 08:26 on seat 9 (counted)".
- **Honest limits.** Two computers' estimates can differ by the error in their
  syncs, in practice a second or two over a school's network. For two answers that
  close the later `received_at` decides, and the log says the tie was settled that
  way. A replaced computer's answers are still refused after `deadline +
  late_window`, like any other.
- **After submit** the attempt is closed: signing in again opens nothing.
- **A student who is replaced does not lose their place**; a student who is
  impersonated has their attempt held by someone else, which is why the PIN is part
  of sign-in.

## Extra time

A teacher of the test, an exam officer or the administrator can give one student extra
minutes with a reason (screen 7, per student). It is a `TimeExtension` row and an `extra_time`
event, visible in the log with who gave it and why. It moves that student's
`deadline` and, if needed, their close time; nobody else's. It can be given before the
student starts, while they are sitting (their timer grows on the next sync) or after
a power cut. A student cannot be given time after their attempt is submitted or closed
by the clock: that is a retake.

## Integrity

- Question order and option order are shuffled per student, from a seed stored on
  the attempt. Marking compares original option indexes, never letters.
- One attempt. A retake is a `RetakeGrant` for a named student with a reason.
- Start, disconnect, reconnect and submit times, by the server's clock.
- **No browser lockdown is claimed**, anywhere. Screen 4a says to supervise the room.

## Who sees what

| | banks and questions | tests | answers and scores |
| --- | --- | --- | --- |
| Teacher | Banks for subjects and levels they teach | Tests for their subjects and classes | Their classes' attempts; send to CA; release |
| Student | Never a bank | Only a test their class is in, while open, through `/sit/` | Their own score and corrections, after release |
| Parent | Never | Never | Their own child's released scores; no questions, no answers, no class average |
| Vice principal | All banks (read) | All tests (read) | All attempts and results (read); not release, not send to CA |
| Principal | All | All | All; release and restore; sets cross-subject practice; names exam officers |
| Exam officer (a teacher or the vice principal the principal names) | Their own, as a teacher | Cross-subject practice and, for extra time, PIN slips and retakes, any test in the school | No scores beyond what their role already shows |
| Administrator | **None** | Title, class, window, size and code state; never the questions before the test opens. Opens and closes sittings, changes the code | The sitting log from the start; **scores only after release**. Prints PIN slips; gives extra time |
| Platform staff | None of a school's content (as `gradebook` excludes them) | None | None; they run provider removal |

Tenant isolation as everywhere else: every table above lives in the school's schema;
the provider tables below are the only shared ones, and they hold no school data.

## External question banks (designed, off)

A licensed provider (for example ALOC or a similar API) could be plugged in later.
**Nothing is built and nothing calls out in this feature**; screen 10 and 1b are the
design. School-written questions work without any of it.

### Shared tables (public schema)

| table | key columns |
| --- | --- |
| `QuestionProvider` | slug, name, base_url, status (`off` by default, `on`, `ended`), licence_ref, licence_ends, licence_confirmed_by (platform staff), licence_confirmed_at, storage (`live_only` / `test_copy` / `cache`), test_copy_days, copies_survive_licence, attribution_text, rate_per_minute, terms_url |
| `ProviderStatusChange` | provider, from, to, by, at, reason. Append-only. |
| `ProviderSchool` | provider, school, granted_by, at, ended_at. Which schools the licence covers. |
| `ProviderQuestionCache` | provider, external_id, normalised payload, fetched_at. Rows only while `storage = cache`. |
| `ProviderRemovalRun`, `ProviderRemovalLine` | when a licence ends: per school, how many bank rows, cached rows and test item texts were removed. Deletion is an absence; this is its record. |

### Rules

- **Only platform staff turn a provider on**, per provider, for chosen schools, and
  only with a licence reference and the "I have seen the signed licence" box, which
  stamps name and date. No route on a school's host writes any of these tables.
- **Storage follows the licence:**
  - `live_only`: nothing kept. Teachers can preview; a question cannot go in a test or
    be copied, because a test must work when the provider is down.
  - `test_copy`: nothing in banks; the text is copied into `TestItem` at publish, as
    any question is, and removed `test_copy_days` after the test closes. Scores stay.
  - `cache`: fetched once into the shared cache and shown read-only in the bank tab.
- **Read-only for schools.** "Copy to my bank" makes a school `Question` the school
  can edit, with `derived_from` kept for attribution and for removal.
- **Attribution** text shows under the question for teachers and students.
- **When a licence ends:** one platform action removes the provider's rows from every
  school, empties the cache, removes item text from closed tests, and removes or lists
  derived copies according to `copies_survive_licence`. Scores stay.
- **Outages:** five-second timeout, a rate bucket in Postgres (as
  `accounts.throttling`), and after repeated failures the provider is treated as down
  for a few minutes. Teachers see the plain message on screen 1b. A published test
  never calls a provider: its questions were fixed at publish.
- **Connector shape:** one interface, `search(subject, level, topic, page)` and
  `get(ids)`, returning the same shape as a school question (stem, 4 or 5 options,
  correct index, explanation, images, attribution). Each provider is an adapter.

### Never seeded

No migration and no production command writes a question. A test will assert that
`cbt` migrations contain no question data and that the provider table is empty after
migrating. For local development only, `seed_demo` can write a provider called
"Local sample (fake)" with ten questions we wrote, labelled as such, into the demo
schools.

## Demo data

- Demo questions are written by us, labelled as demo, and loaded only by `seed_demo`
  and `load_demo`, into `sunrise-demo` and `harbour-demo` only. The loader refuses
  any other slug.
- **The guard is Phase 2 step 0** and has its own PR: a demo slug (`sunrise-demo`,
  `harbour-demo`, `showcase-demo`, and any slug ending `-demo` or starting `demo-`)
  cannot be created unless `DEBUG` is on or `DEMO_SERVER=1`, and a production server
  refuses to start while one exists. The demo server runs with `DEBUG` off and
  `DEMO_SERVER=1`, which `deploy/init-env.sh` already refuses on a production
  `secrets.env`.

## Controls owed in Phase 2

Operating rule 5: break it, watch the named test go red, restore. Every row runs with
two schools, at least two tests each, sharing ids where they can.

| area | claim | the break |
| --- | --- | --- |
| results | Send to CA writes only through `set_score_as()`, so a submitted or released class refuses | write `Score` directly |
| results | A student who did not sit gets no mark | write a zero |
| results | "Keep" never overwrites; "replace" never overwrites a mark typed after the preview | ignore the policy; pass `ANY_VERSION` |
| results | An answer arriving after `deadline + late_window` is not counted | drop the deadline check |
| results | A key correction re-marks every attempt, and none after release | skip the re-mark; allow it after release |
| release | No score or correction reaches a student before release | drop the release check on the student page |
| release | A parent sees only their own child's released scores | drop the guardianship filter |
| release | A released score never changes | drop the trigger on `ReleasedTestScore` |
| release | The paper sent to a device carries no keys or explanations | add `correct_index` to the payload |
| access | A teacher sees only their own banks, tests and classes | drop the `SubjectTeacher` filter |
| access | Removing a class from a test stops its students starting it, and is logged | skip the audience check |
| access | Wrong code, wrong number, wrong PIN and someone else's PIN get one refusal, throttled | return different sentences; skip the throttle |
| access | The `/sit/` cookie opens one attempt and no other route | accept it on a staff route |
| access | Only platform staff turn a provider on; a provider question is read-only | drop the staff check; drop the trigger |
| access | A second computer's sign-in ends the first, and only one holds the attempt | drop the single-holder index; skip ending the first |
| access | Of two answers, the one chosen later counts, and both are kept | take the later-received; delete the loser |
| access | Extra time is given only by a teacher of the test, an exam officer or the administrator, with a reason, and logged | allow any teacher; allow an empty reason |
| access | The administrator cannot read or write a bank, nor read a test's questions before it opens | drop the role check on the bank routes; serve the paper to the administrator's preview |
| access | The administrator sees a score only after release, and the sitting log carries no answers | serve the results page to the administrator; add the chosen option to the log view |
| access | Opening or closing a sitting, and changing a code, are logged; a close does not discard an attempt in progress | skip the `SittingControl` row; delete answers on close |
| access | A test with the PIN off cannot send to CA, checked by the server | drop the check in the send service |
| access | Only the principal names exam officers; an exam officer cannot release or send to CA | let an exam officer release |
| access | Printing slips again cancels the old PINs; the old PIN then fails | skip the cancel |
| access | Once a school has subject assignments, a teacher cannot enter marks outside theirs; before that, they can | drop the narrowing; narrow with none |
| release | A restore needs a reason and the principal, and hides scores from students and parents | allow an empty reason; skip the hide |
| tenant isolation | An attempt, answer or score at one school is never readable at the other, with equal ids | drop the schema scoping in a query |
| tenant isolation | A test code at one school opens nothing at the other | look the code up across schools |
| tenant isolation | Send to CA cannot name another school's assessment | look the assessment up by id alone |

Everything else (layout, wording, the calculator, timers on screen) gets ordinary
tests.

## Left for later

- Student passwords, and practice at home (option C).
- Letting a student see their attempt on a second screen to compare seats.
- A live sitting screen for the invigilator: who is in, who dropped, reset a seat.
- Theory and essay questions, more than one correct answer, part marks.
- Maths typesetting beyond powers and subscripts; audio for listening questions.
- Importing a school's own questions from Word or a spreadsheet.
- A NECO-style mode: one more `ExamFormat`, same engine as WASSCE-style objectives.
- Difficulty and discrimination statistics across terms.
- The live provider connector.
- Proctoring or lockdown: not planned, and never claimed.

## Open questions

None. The administrator's CBT access was decided on 20 October 2026 (see "The
administrator").

## Settled in interpretation, to check

- "Restore control" for a release is read as a principal-only **restore action with a
  reason** (`TestReleaseRestore`), not as the build's break-and-restore test
  procedure. Say if it meant something else.
- An exam officer is a permission held by a teacher or the vice principal, not a new
  role, so a membership keeps one role per school.
- Retakes: the test's teacher or an exam officer, with a reason, as extra time. The
  administrator gives extra time but is not listed for retakes unless named an exam
  officer.
- "Open and close sittings" is read as opening or closing a test to a class by hand,
  inside or beyond its planned window, logged, and never discarding an attempt in
  progress. Say if it meant something narrower.
- "Cannot see a test's questions before the test opens" is read literally: after a
  test has opened the administrator may see its questions, read-only, as published.
  If it meant never, that is one more route to close.

## Notes on the mockups

- They link the real `static/web/design.css`; `cbt.css` uses its tokens and the
  dashboard's scale and declares no colour.
- The sign-in door reuses the staff sign-in's One Blue fading into the grey: no new
  gradient.
- The test screen's top band is solid One Blue, and nothing on it imitates a centre's
  branding. The flagged mark on the number grid
  is a small amber corner, always beside the legend and in the cell's label.
- Screen 7 is a teacher's view. The administrator's is its Students table without
  scores or answers, until release. The mockups do not draw it separately.
- Every question shown was written for the mockups. Names and numbers are invented.
- Built at 375 and 1280 px; the test screen moves Previous, Flag and Next to a bar at
  the foot of a phone.
