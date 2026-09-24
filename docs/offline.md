# Offline mode for teachers

Status: **reviewed 2026-09-24 — the plan.** S1–S4 are being built; S5–S7 wait until
after the pilot. The decisions taken in review are recorded directly below, and they
override anything later in the document that reads as still open. Extends
`docs/gradebook.md` and `docs/attendance.md`; changes neither's rules.

Everything this document says about the code as it stands was read on `main` at
`ecc36f9` and cites the line it was read from.

## Decision record (review, 2026-09-24)

**Build now, in this order:**

1. **S1**: the register's day in Lagos time (D9), plus the date input the page draws
   and never listens to, plus the two stale-prose findings at the end of this
   document.
2. **S2**: a refused or failed mark is kept on its cell (D5's first paragraph).
3. **S4**: idempotency keys (D3).
4. **S3**: the marks outbox, with one entry per cell, and 423, 422 and 403 final
   (D1, D2, D6, D7).

**Deferred until after the pilot:** S5 (service worker and snapshots), S6 (the
register's base and per-child merge), and S7 (shared handsets). The document stays
the plan for them.

**Correctness requirements 1, 2, 4, 5, 6, 7 and 8 apply to the slices built now.**
Each is a two-school test with a control. Requirement 3 is S6's and waits with it.

| open question | decided |
| --- | --- |
| OPEN-1, the per-child register merge | **Agreed with D4.** Added to the pilot-school questions, issue #155, because a school's answer can still overturn it. |
| OPEN-2, where the idempotency key lives | **A `SyncReceipt` table with a unique key.** |
| OPEN-3, how long unsent work may sit | **Seven days, then flagged, not deleted.** |
| OPEN-4, a "pending on a device" signal | **None in v1.** |
| OPEN-5, taken-at versus arrived-at | **Deferred with S6.** |
| OPEN-6, devices | **Chrome on Android is in scope. Safari gets a clear warning.** |
| OPEN-7, clearing a mark offline | **No.** |

## What this is

A teacher can take the morning register and enter marks while their phone has no
connection. The device keeps what was done, and sends it when the connection comes
back. Where the server has moved on in the meantime — another teacher changed the
mark, the office corrected the register, the sheet was submitted — the teacher is
told, in the words the online screens already use, and nothing is silently lost or
silently overwritten.

It deliberately does **not** cover:

- **Signing in offline.** A device can only hold work for a session that existed
  when it went offline (D7).
- **Anything past the class teacher's desk.** Submitting, checking, approving and
  releasing results, fees, the broadsheet and report cards stay online-only. Each is
  a single decision by a named person over a whole class, and deciding it against a
  stale copy is worse than waiting.
- **Reading other people's data offline** beyond what the teacher's own two screens
  already showed them (D8).
- **A native app.** The two pages are plain JavaScript with no build step
  (`package.json`); this stays a web page.

## Domain assumptions

**Provenance.** None of these has been confirmed by a school. They are the author's
model of how teachers in Nigerian schools work, and each is marked with what breaks
if it is wrong. An assumption remembered as a fact is the failure `220a81e` had to
correct in `docs/parent-access.md`; the survival table below exists so that a wrong
one costs a decision rather than the design.

- **A1. Connectivity drops for minutes to a school day, rarely for longer.** Mobile
  data on the teacher's own phone, dead spots in classroom blocks, data bundles that
  run out mid-week. Offline for a weekend is plausible; offline for weeks is not a
  case this designs for.
- **A2. Teachers use their own Android phones, in Chrome.** Shared handsets exist —
  `docs/parent-access.md` designs a guardian sign-in around one — but a teacher's
  marking and register device is usually personal.
- **A3. One register per class per day is taken by one person**, usually the form
  teacher, in the room, from the names on the screen. Who covers an absent form
  teacher is attendance's A5, still open (issue #125).
- **A4. Marks are entered in bursts, often away from school** — after marking a pile
  of scripts, in the evening. Two people with the same sheet open is still the
  ordinary case online (`docs/gradebook.md:59-75`), so it is the ordinary case for a
  sync too.
- **A5. The office corrects registers during the day** — a late arrival, a child
  sent home — so a register synced at 4pm may meet a correction made at 10am.
- **A6. A lost or shared phone holds child data.** Names, absences and marks. Browser
  storage is protected only by the device's own lock.
- **A7. Phone clocks are wrong often enough to matter.** A day-boundary mistake moves
  an absence onto the wrong day.

### Which decisions survive a wrong assumption

| if this is wrong | still holds | breaks or changes | cost |
| --- | --- | --- | --- |
| A1 (outages last weeks) | D1–D6, D9 | D8's retention rule; the outbox grows past what a teacher can review | a limit and an export, not a redesign |
| A2 (shared handsets are common) | D1–D6 | D7 becomes the main path rather than the edge; D8 needs per-user partitions on one device | UI, and a stronger sign-out |
| A3 (two people take one register) | D1, D3, D5, D7 | D4's per-child merge is exercised constantly rather than rarely | none structurally; OPEN-1 matters more |
| A4 (marking is done at school, online) | all | nothing | offline scores become a small feature |
| A5 (the office never corrects) | all | D4's register half is guarding a case that does not happen | one migration that pays for nothing |
| A6 (devices are school-owned and managed) | all | D8 could keep data longer | none |
| A7 (clocks are reliable) | all | nothing — D9 is still right, just rarely exercised | none |

## Decisions

### D1. The device holds intentions, not a second gradebook

The server stays the only place a mark or an absence is true. Offline, the device
keeps two things and only two:

1. **A snapshot of what it was shown** — the marking sheet (each row's `value` and
   `version`, `gradebook/api.py:421`) and the register roster, as of the last time
   it was online.
2. **An outbox of writes**, each exactly the request the online page would have sent
   at that moment: the same URL, the same body, the same `expected_version`.

Nothing on the device evaluates a rule. Whether a mark is in range, whether the sheet
is open, whether the day is in the term — all of that is still decided by the server
when the write arrives, by the code that decides it today. This is the same reason
`gradebook/tests/test_session_expiry.py:8-17` gives for the server holding no draft
of an unsent mark: "a server-side draft store is a second copy of the gradebook with
none of its rules". A client-side one would be the same copy in a worse place.

**Consequence, stated because it is the whole cost:** a teacher offline gets no
refusal until sync. A mark of 25 out of 20 is accepted by the device and refused
later. The device may *warn* using the snapshot's `max_score` — it already has it —
but the warning is advice and the server's 422 is the answer.

### D2. Coalesce per cell and per register before sending

A teacher who types 15 and corrects it to 17 while offline sent the server nothing
in between; the server should see one write of 17, based on the version the teacher
was shown. So the outbox keeps **one entry per cell** (the latest value, the
original `expected_version`) and **one per register per day** (the latest absent
set, the original base — D4).

Sending both would be wrong rather than wasteful: the second write would carry a
version the first has already moved, and `_is_our_write_arriving_twice()`
(`gradebook/api.py:357`) would not save it, because the value differs. The teacher
would be warned about a conflict with themselves — the "cry wolf" the docstring
there exists to prevent.

### D3. Every queued write carries a key, and the key is the database's

A write whose response is lost is sent again; offline makes that the normal case,
not the rare one. The fees page already solved this: `form_key` is a UUID the page
mints per form, and `a_form_posts_once` is a unique constraint on it
(`fees/models.py:575-581`, the constraint at `:775-779`), because "the unique index is the whole mechanism… two
submissions racing each other both pass any read, and only the index sees them both"
(`fees/services.py:519-556`).

The same shape here, for both writes:

- **Scores** are already replay-safe for the teacher's own repeat
  (`_is_our_write_arriving_twice()`). That rule keys on *value and person*, which is
  right online and fragile offline: a replayed 17 that lands after the teacher has
  since, on another device, entered 18 is refused as a conflict with themselves. A
  key makes "this exact write already landed" a fact rather than an inference.
- **Registers** have no version at all today; resubmitting amends
  (`attendance/services.py:210`). With D4's base added, a replay whose first attempt
  landed would meet its own write as a change since the base. The key is what tells
  the two apart.

Where the key lives was OPEN-2, decided in review: a `SyncReceipt` table with a unique
key. The requirement is that it is enforced by a unique constraint, not by a read —
the lesson `a_form_posts_once` records.

### D4. A register syncs child by child against what the teacher was shown

Today a second submission of a register wins child by child
(`attendance/services.py:257-359`), and the only protection against a stale screen is
`shown_ids`: children who appeared after the screen was drawn are left unmarked and
reported (`services.py:225-233`). That was designed for a screen that is minutes old.
Offline, it can be a day old, and A5 says the office will have corrected it.

**Proposed:** an offline register carries its **base** — the absences the device was
shown when the register was opened — as well as the absences the teacher tapped. On
sync, the server applies only the children whose status **the teacher changed
relative to the base**, and for each of those compares the base with the server's
current mark:

| the teacher changed this child | the server's mark still equals the base | result |
| --- | --- | --- |
| no | — | untouched — the teacher did not decide anything about this child |
| yes | yes | written, exactly as today |
| yes | no | **conflict for this child** — not written, reported by name |

This keeps the office's 10am correction for every child the teacher did not touch,
and refuses to overwrite it for a child both of them touched. It needs no version
column: the base is the version, per child. A register that did not exist when the
device drew the screen has an empty base, and a register created by someone else in
the meantime turns every child the teacher marked absent into a comparison against
that register — which is the behaviour wanted.

The alternative is a whole-register version and a 409 on any change, the way a mark
works. That is simpler and it is wrong for this screen: a whole class's register
refused because the office marked one late arrival present, and a teacher asked to
retake forty-five names to get past it. OPEN-1 asks whether schools agree.

### D5. Conflicts are shown with the words the online screens already use

**Marks.** A queued mark that meets a 409 is drawn exactly as a live conflict is
today — the cell takes the other person's value and version and says "Saved as
{value} by somebody else. Type over it to change it." (`static/marking/app.js:97-109`),
drawn as an alert (`static/marking/states.js:139`). Typing over it is then a deliberate overwrite
with the new version, as it is online.

One thing is added, because offline makes it necessary: **the teacher's own value is
kept and shown beside the conflict** ("you entered 17 offline"). Online, the teacher
typed it seconds ago and remembers it. Offline, they typed it last night. Today the
client keeps no refused value at all — a transport failure replaces the whole sheet
(`static/marking/app.js:118`) and the typed mark is gone — and that has to change before anything
else in this document is built, because it is the online version of the same loss.

**Registers.** A child in conflict under D4 is listed by name on the register page
the next time the teacher opens it, with both answers ("you marked Ada absent; the
office has her present since 10:12"), and the teacher chooses. The existing
"appeared" and "not on the roster" reports (`static/register/states.js:146-154`) are shown the same
way after a deferred sync, instead of on a done screen the teacher has long left.

**Nothing is resolved automatically.** Not by time (A7 makes the device's time
untrustworthy), not by role, and not by "last writer wins". The server already
refuses to guess online; syncing is not a reason to start.

### D6. Locked, refused and forbidden writes are final, not retried

A queued write can meet a state the teacher cannot fix by retrying:

| answer | meaning (today) | what the device does |
| --- | --- | --- |
| **423** | the sheet is submitted, checked, approved or released (`gradebook/api.py:605-611`) | stop; keep the value; say which state and "ask for the sheet to be sent back" in the server's own words (`gradebook/services.py:294`, `:302`) |
| **422** | the value is invalid, or the day is outside the term (`DayOutsideTheTerm`) | stop; keep it; show the server's sentence |
| **403** | the teacher no longer has authority (a suspended membership, a changed role) | stop; keep it; say the write could not be made under their account |
| **409** | a conflict | D5 |
| transport failure, 5xx | not an answer | retry with backoff |

The 423 row is the one that matters, and it is already argued in the code: a locked
sheet is a 423 and not a 409 precisely because "a released term never reopens, so
that client retries for ever" (`gradebook/services.py:102-106`). A sync loop is that
client. Held writes stay on the device until the teacher dismisses them; a send-back
reopens the sheet and the teacher can send them again deliberately.

### D7. No offline sign-in, and a write goes only under the name that made it

The device sends its outbox only under the session of **the user who queued it**. A
teacher offline overnight comes back to an expired session — sessions slide over a
twelve-hour idle window (`settings.py:305-306`) — so the outbox is held, the teacher
signs in, and it sends. Every write is attributed by the server to whoever is signed
in, exactly as online (`updated_by_id`, `marked_by_id`); nothing on the device
asserts an author.

If a **different** person signs in on the device (A2's shared handset), the outbox is
not sent under their name. It is shown to them as "held for Kemi — sign in as Kemi to
send it", and is not readable beyond that line. This is the offline form of the rule
`test_session_expiry.py` pins online: the retry must be the *same person*, whatever
the session.

The CSRF token is fetched on reconnect before the first write; the client already
retries once on `csrf_failed` (`static/web/http.js:81-120`).

### D8. What the device keeps, and for how long

- The snapshot and the outbox are stored per **user and school host**. A teacher at
  two schools has two outboxes, and a write queued for St Mary's is never sent to
  Grace's host — the host is what selects the schema, and a request to the wrong one
  would be refused by the membership check at best.
- Only what the two pages already showed: roster names and ids, marks and versions
  for sheets the teacher opened. No other class, no fees, no contact details.
- **Cleared on sign-out**, snapshot and outbox alike — after warning if the outbox is
  not empty, because clearing it discards work.
- **Unsent work older than seven days is flagged, not deleted.** Deleting a mark a
  teacher entered is the silent loss this document exists to prevent; seven days is
  an assumption (A1), and OPEN-3 asks for the real number.

Storage is IndexedDB. Today nothing in `static/` uses any browser storage — the one
mention is the sign-in page deciding *not* to use `sessionStorage`
(`static/signin/app.js:6`) — so this is the first, and A6 is the risk it accepts.

### D9. The register's day is Lagos's day, fixed before offline exists

`today()` in the register page is `new Date().toISOString().slice(0, 10)`
(`static/register/app.js:31-32`), which is the **UTC** date. Lagos is UTC+1, so between
midnight and 1am the page names yesterday. Online that is an hour nobody takes a
register in. Offline, a register taken at 8am and queued carries whatever day the
device computed — so the date is fixed at the moment of taking, and it has to be the
school's day, not UTC's.

This is a bug today and a slice on its own (S1). The same file draws a date input it
never listens to (`static/register/states.js:35`, `static/register/app.js:125`), so `on` cannot be changed; offline
does not need that fixed, but a teacher entering yesterday's register after an outage
does.

### D10. The shell is cached; the data is not re-fetched offline

A service worker caches the two pages' static files so the marking sheet and the
register open with no connection. The GETs that fill them (the sheet, the roster) are
answered from the last snapshot when offline and marked as such on screen — "as of
yesterday 16:40" — so a teacher knows they are looking at a copy. Online, they are
fetched fresh as today and the snapshot is replaced.

## What is configurable

**Nothing, in the first version.** Offline mode is the same page behaving better
when the network fails; a school has no reason to turn that off, and a toggle would
be a second code path for every write. D8's seven days is the one number a school
might reasonably want to change, and it is OPEN-3 rather than a setting until a school
says so.

## The slices

In order; each is useful on its own and each is its own PR. **S5, S6 and S7 are
deferred until after the pilot** (decision record, above); S1–S4 are built in the order
S1, S2, S4, S3.

- **S1. The register's day in Lagos time (D9).** A bug fix, needed online today.
- **S2. A refused mark is kept, not lost (D5's first paragraph).** Online behaviour:
  a transport failure or a 401 keeps the typed value on the cell. No storage yet.
- **S3. The outbox for marks (D1, D2, D6, D7),** with one entry per cell, sent in
  order on reconnect, stopped by 423/422/403.
- **S4. Idempotency keys (D3),** server side first, with the constraint.
- **S5. The service worker and snapshots (D10, D8).**
- **S6. The register's base and per-child merge (D4),** server side, then the register
  outbox.
- **S7. Shared handsets (D7's second paragraph).**

## Correctness requirements

Each is a test, with two schools, never one.

1. **Replaying is safe.** Any queued write sent twice, with the first response lost,
   leaves the database as if it were sent once — for a mark and for a register.
2. **Nothing overwrites a change the teacher did not see.** A mark changed by someone
   else since the snapshot is a conflict, not a write; a register child changed by
   the office since the base is a conflict for that child only.
3. **Nothing the teacher did not touch is written.** A register synced a day late
   leaves every child the teacher did not change exactly as the server has them.
4. **A locked sheet is never retried.** One 423 and the entry stops; the test counts
   requests.
5. **Only the author sends.** An outbox queued by Kemi is never sent under Tunde's
   session, and the server's `updated_by_id` is always the signed-in user.
6. **A school's outbox reaches only that school.** A teacher at St Mary's and Grace
   with work queued for both sends each to its own host and neither to the other.
7. **The register's day is the day it was taken in Lagos.** A register taken at 00:30
   Lagos time is for that day, not the previous one.
8. **No refused value is lost.** After a 409, 422, 423 or 403 on sync, the teacher's
   value is still on the device and on screen until they dismiss it.

## Open questions

**All seven were decided in review on 2026-09-24.** The decision record at the top is
the answer to each. They are kept here as the reasoning behind those answers.

- **OPEN-1. Is a per-child register merge what schools want (D4)?** The alternative is
  refusing the whole register when anything changed. D4 argues against it; a school
  may prefer "the office's correction always wins" or "the teacher's register always
  wins", and either is simpler than D4 and loses somebody's answer.
- **OPEN-2. Where does the idempotency key live (D3)?** A column on `Score` and
  `Register` keeps one key per row, which a second write to the same row replaces; a
  small `SyncReceipt` table keeps every key and grows. The requirement either way is
  a unique constraint.
- **OPEN-3. How long may unsent work sit on a device (D8)?** Seven days is a guess.
- **OPEN-4. Should the server know that a device is holding work?** It cannot, by
  construction — which means a principal releasing results cannot know a teacher's
  phone holds three marks for the class. D6 makes those marks refuse cleanly after
  submission; whether a school wants a "pending on a device" signal is a product
  question, and it would need the device to phone home.
- **OPEN-5. Does an offline register need to say when it was taken, not only when it
  arrived?** `Register.taken_on` is the day and `updated_at` the arrival. A7 says the
  device's clock cannot be trusted for the record; attendance's OPEN-3 already asks
  whether amendments need an audit, and a register that arrives a day late is the
  same question with a better reason.
- **OPEN-6. Which devices are in scope?** A2 assumes Chrome on Android. Safari clears a
  site's script-written storage, IndexedDB included, after seven days of browser use
  without a visit — which is D8's whole window.
- **OPEN-7. Does a teacher need to clear a mark offline?** The marking page cannot
  clear a mark online today — a blank cell is not sent (`static/marking/app.js:197`) and
  `static/marking/api.js` has no DELETE. Offline should not add a capability the online page lacks; if clearing
  is wanted, it is wanted online first.

## Two things found while reading, not part of this proposal

- `attendance/models.py:209-214` and `docs/attendance.md` D9 say a
  `why_not_a_student_here()` check is made when a mark is written;
  `attendance/services.py:130-138` says there is deliberately no such check. One of
  them is stale.
- `docs/gradebook.md:151` says "Three endpoints"; `gradebook/api.py` has four,
  counting `/where/`.
