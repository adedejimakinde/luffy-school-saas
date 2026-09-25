# Messaging: codes, result notices, fee reminders and the result checker

Status: **reviewed 2026-09-25 — the plan.** M1–M4 are being built, in order,
against the fake provider; M5 and M6 wait for a real provider. The decisions taken
in review are recorded directly below, and they override anything later in the
document that reads as still open.

How the platform reaches a family: the sign-in and verification codes guardians
already need (code delivery), a notice that a report card is ready, a fee reminder
from the bursar, and a result checker for a family with no account. It is built behind one provider interface with a fake
provider for tests and development, so a real SMS, WhatsApp or email provider plugs
in later with no change to the four. Choosing that provider is parent-access's
OPEN-5 and stays open here.

Extends `docs/parent-access.md`, which left messaging out ("Those are later",
`docs/parent-access.md:30`), and `docs/withholding.md`, whose gate every family
message goes through. Changes neither's rules, except where D10 asks for one to be
overturned, and says so.

Everything this document says about the code as it stands was read on `main` at
`46fe366` and cites the line it was read from.

## Decision record (review, 2026-09-25)

**Build now, in this order, against the fake provider:** M1 code delivery, M2 result
notices, M3 fee reminders, M4 the result checker. **Waiting for a real provider:** M5
(delivery reports) and M6 (the provider itself).

**Built:** M1, code delivery (#167). Where it departs from the text below, it says so
there: the chooser offers each guardian once by construction rather than by a fold
(D8), the code is sealed with Fernet from `cryptography` (D6), and `messaging.W001`
is silenced in `settings.py` until a real phone provider is named (D2, M6).

**"PR D" is renamed "code delivery"** (M1), so it no longer shares a letter with the
parent-access series' PR D, merged in #110. The code comments that say "PR D" for it
are renamed in M1.

| question | decided |
| --- | --- |
| OPEN-M1, the amount on a fee reminder | **Yes, the amount is stated, and only to a live, verified channel.** A pending or dormant channel gets no amount, because it gets no reminder at all, and a test says so (requirement 14). |
| D9, result notices as a step after release | **Agreed.** |
| D7, quiet hours | **Changed: held, not refused.** A school-originated message asked for between 20:00 and 07:00, Lagos time, is held and sent at 07:00. Codes are exempt, because a code held until morning would be dead fifteen minutes into its wait. |
| D5 and D6, after the commit, at most once, codes encrypted on the broker | **Agreed.** |
| D11, the result checker | **Agreed.** The PIN is printed in groups of four, and wrong attempts are rate-limited per admission number as well as per address. |

**What holding overnight brings with it: a scheduler.** `docs/background.md` has
"No `beat`, no scheduler", because nothing was periodic. Releasing held messages at
07:00 is periodic. A Celery ETA task cannot do it on this broker: it is redelivered
every `visibility_timeout` (300 seconds) until its time comes, which is about 150
copies of each held task by morning. So M2 adds `celery beat`, running one sweep a
minute that queues the held messages whose time has come. The sweep is safe to run
twice, because every send is claimed first (D5). `docs/background.md` changes with
it.

## What this is

Four things, in the order they are needed:

1. **Code delivery.** Codes are minted today and sent nowhere. The raw code
   `request_sign_in_code()` returns is discarded
   (`accounts/guardian_signin.py:289`), so outside the test suite no guardian can
   verify a channel or sign in. Code delivery sends the codes, with #111's
   decisions.
2. **Result notices.** When a class's cards are released, each family is told the
   card is ready and where to read it. The notice itself carries no results.
3. **Fee reminders.** The bursar tells the families of children who owe that they
   owe.
4. **The no-account result checker.** A family with no verified channel reads the
   card on the school's site with the child's admission number and a PIN from a slip
   that went home with the paper card. Nothing is sent. It belongs here because it
   is the other half of the same question: how a family learns the results.

It deliberately does **not** cover:

- **Choosing, contracting or paying a provider.** That is OPEN-5, and a pricing
  question. Nothing here depends on the answer.
- **Free-text messages from a school.** No broadcast box. Every message is one of a
  closed list of kinds with fixed wording (D3).
- **Replies, or anything inbound** other than a provider's delivery report (D12).
- **Scheduled or automatic sends.** There is no scheduler on this platform
  (`docs/background.md`, "No `beat`"). Every school-originated message is somebody
  pressing a button.
- **Staff invitations.** They stay on `schools/delivery.py`, which already has this
  shape. Folding them in is a later tidy-up, not part of this work.
- **Payment.** A reminder can say what is owed; it cannot take the money.

## Domain assumptions

**Provenance.** None of these has been confirmed by a school. Two lean on what
parent-access and #111 recorded from the one school consulted, and each of those is
marked. The rest are the author's model or public sources, and each is marked with
what breaks if it is wrong.

- **M1. Families read SMS, and many prefer WhatsApp.** SMS reaches every phone;
  WhatsApp is cheaper per message and more read, but a business sending on it needs
  the recipient's opt-in and pre-approved message templates. Researched, not
  confirmed.
- **M2. A message is read on a shared handset, and on a lock screen.** Parent-access
  designs a sign-in around one phone held by two parents, and a child often holds
  the phone. Whatever is in a message body is read by whoever holds the phone.
- **M3. Schools message families today, by hand.** A bulk-SMS account or a WhatsApp
  broadcast from the bursar's own phone, typed per term. Assumed; it is why the
  wording in D3 is short and plain rather than designed.
- **M4. The paper card still goes home.** Parent-access A5, **confirmed by one
  school, September 2026.** A slip with a PIN can travel with it.
- **M5. Result-checker PINs are a familiar practice.** National exam results are
  read with a PIN from a scratch card, and many schools' portals copy that shape.
  Researched, not confirmed for any school on this platform.
- **M6. A guardian may hold a live email and a live phone.** #111, **reported by
  one school, September 2026**, and decided there. A reminder or notice has to pick
  one.
- **M7. SMS in Nigeria is sent through a registered sender ID, and numbers on the
  do-not-disturb register can lose promotional traffic.** Transactional routes exist
  for this. Researched, not confirmed; it is the provider's problem and OPEN-5's,
  and it is why kinds are a closed list (D3).

### Which decisions survive a wrong assumption

| if this is wrong | what breaks | what survives |
| --- | --- | --- |
| M1 (families use neither) | nothing is read; the checker (D11) and the paper card still work | every decision; a provider is a setting |
| M2 (phones are private) | nothing; the notices are only barer than they need be | every decision |
| M3 (schools do not message today) | the wording in D3 may need a school's voice | the kinds, the seam, the recording |
| M4 (no paper card) | the checker needs another way to hand out a PIN | the checker itself; the PIN could go with the notice for a verified channel, which D11 argues against |
| M5 (PINs unfamiliar) | the checker needs explaining on the slip | the checker |
| M6 (one channel per guardian) | nothing; D4's choice never arises | everything |
| M7 (no such rules) | nothing; the closed list is still right for WhatsApp | everything |

## Decisions

### D1. One provider seam, per contact channel type, chosen in settings

A provider is anything with:

```
check_configured()          raise NotConfigured if this deploy cannot send at all
send(outbound) -> Accepted  raise Refused (permanent: not a subscriber, bad address)
                            or Unavailable (transient: timeout, provider down)
```

and `outbound` carries the channel type, the address, the **kind**, the kind's
parameters, and our own reference for the message. `Accepted` carries the
provider's reference. Not an ABC, so a test double can be a plain object with a
`send`: the same rule `schools/delivery.py:70` gives for `Channel`.

**The seam is per `ContactChannel` type, not per technology.** Settings map `EMAIL`
and `PHONE` to a dotted path each, the way `INVITATION_CHANNEL` does
(`settings.py:479`). Whether a phone message goes by SMS, by WhatsApp, or by
WhatsApp with SMS as fallback is decided inside the phone provider. OPEN-5 is then
answered by writing one class, and nothing that sends a message changes.

**The provider gets the kind and its parameters, not only rendered text.** SMS and
email send text, which we render (D3). WhatsApp sends a pre-approved template by
name with parameters, which our renderer cannot produce. So a WhatsApp adapter maps
the kind to its template and never sees our text.

**Two failures, not one**, for `schools/delivery.py:37` and `:52`'s reason: a
refused address is something a school can fix by checking a number with a family,
and an unavailable provider is nobody's business but the operator's. Both are
recorded (D6), and they are shown to different people.

### D2. The fake provider is the only one built, and production refuses it

`FakeProvider` records every message it is given in a `public` table and sends
nothing. Tests assert on that table. In development, a page at `/dev/outbox/`,
served only when `DEBUG` is on, lists the messages newest first, **codes
included**. That is how a developer signs in as a guardian without a phone.

It can fail on purpose. A short list of reserved addresses (a phone number ending
`0000` is refused, `0001` is unavailable, and the same for two email addresses) makes
every failure path testable without a network, and the list is in the class's
docstring.

**Production refuses it, by a system check, not a convention.** `messaging.E001`
fails a deploy where either channel type is mapped to the fake while `DEBUG` is off,
the way `accounts.E002` already refuses a session longer than the dormancy window.
The fake's table holds raw codes by design, so a production deploy on the fake
would be storing every guardian's sign-in code in a table and showing it on a page.
With nothing configured, `check_configured()` raises and sends are refused with
a sentence. `messaging.W001` warns when no phone provider is configured at all,
because guardians then cannot sign in.

**So the test suite does not get the fake from deploy settings.** CI deliberately
runs with `DEBUG` off, the way production does (`.github/workflows/tests.yml:75`),
and a fake in its settings would trip `E001` before a test ran. The suite switches
the fake on per test, the way it already substitutes a recorder for
`INVITATION_CHANNEL`. A test that forgets meets `NotConfigured`, which is loud.

### D3. A closed list of kinds, with fixed wording

| kind | sent by | to | carries |
| --- | --- | --- | --- |
| channel check | a school admin (door one) | a channel the school has just typed | the school's name, the code |
| sign-in code | the guardian (door two) | the channel they typed | the code |
| reactivation | a school admin (door three) | a dormant phone | the school's name, the code |
| school answer | a school admin (the fourth door, #135) | a guardian's proved channel | the school's name, the code |
| result notice | the principal (D9) | each live guardian of the child | school, child, term, where to read it |
| fee reminder | the bursar (D10) | each live guardian who receives invoices | school, child, term, the amount owed |

**No free text from a school.** A text box would make the platform a bulk sender
for whatever a school types, with no template a WhatsApp provider could have
approved, and no review of what it discloses on a shared handset (M2).

**The wording is ours, in code, and each kind was read for what it gives away on a
lock screen.** No mark, grade, average, position or remark is in any of them. A
notice says a card exists and where to read it, and reading it needs a sign-in or a
PIN.

**Counted in segments, not messages.** An SMS is 160 GSM-7 characters. One
character outside that alphabet makes the whole message UCS-2, at 70 characters a
segment, and costs roughly two to three times as much. `₦` is outside it, and so are
many Yoruba and Igbo diacritics a school may have in a child's name as it holds it
(`Membership.display_name`). So SMS says `NGN`, and the renderer reports segments,
which is what budgets (D7) count.

English only in v1. OPEN-M6.

### D4. Only a verified, live, non-dormant channel receives anything

The only message an unverified channel ever receives is its own channel check,
which is door one's whole purpose. Everything else goes only to a channel that is:

- **verified and not revoked** (`GuardianContact.is_live`);
- **not a dormant phone**, by the same `is_dormant()` the sign-in door uses. A
  number that has not signed in for 180 days may already belong to somebody else,
  and a result notice names a child. D9's argument for codes in
  `docs/parent-access.md` applies with more force to a message that says whose child
  it is;
- **of a guardian live at the sending school.** Membership `ACTIVE` as `PARENT`
  there. A link still waiting for this school's answer (#135) gets nothing from it.

**With two live channels (M6), one message, never two.** The phone if it passes the
rules above, otherwise the email. That follows how the school consulted says it
reaches families. Email-first would be cheaper, which is OPEN-M4.

### D5. Sent after the commit, off the request, and at most once

**The act and the send are two things.** The principal's "tell families" and the
bursar's "send reminders" write their notice rows in the act's transaction, and the
send is queued after the commit. This is `results/renders.py`'s pattern and its
reason: a provider must never be able to fail or roll back a decision somebody made.

**At most once, not at least once.** `docs/background.md` sets `acks_late` and
reject-on-worker-lost, so a task can run twice, and a task that is not idempotent
must say so. A send is not idempotent: a second SMS costs money and reaches a
parent twice. So the worker **claims** a message (an attempt row, unique per message)
in its own transaction before calling the provider. A second run finds the claim and
does nothing. A worker that dies between the claim and the provider's answer leaves
a claim with no outcome, and that is shown to the school as "not known whether it
arrived". It is **never resent automatically.** A code is no different, and a
guardian who got nothing asks again.

**The provider is never called on the sign-in door's request.** A call to a provider
takes hundreds of milliseconds, and it only happens for a number that is on a
guardian record. If it ran on the request, response time would say which numbers are
guardians: the oracle `accounts/guardian_signin.py`'s whole design refuses, reopened
through the clock. So every send is queued, including codes.

### D6. What is recorded, and the one thing never recorded

**A notice or reminder is an append-only row in the school's own schema**, with the
text as it was sent (rule 2: what went out is frozen), the recipient as bare ids
into the shared guardian tables (the way every per-child column in `results` is a
bare id), the channel type, and who pressed the button. Attempt rows record the
claim, the provider's reference, and the outcome. Tenant tables, so a school's
messages go with the school when it leaves, which is the deletion path OPEN-9 says
must work.

**A code is never in any record.** `_mint_code()` says the raw code "exists in memory
for as long as it takes a delivery channel to put it in an SMS or an email"
(`accounts/guardian_contacts.py:575`). Two things this design would otherwise break,
and how it keeps them:

- **No message body is stored for a code kind.** `GuardianContactCode` is already
  the send log (`accounts/guardian_contacts.py:451`). A shared, append-only delivery
  row beside it records the outcome and the provider's reference, and no text.
- **The queue is storage too.** A code put in a Celery message in the clear sits in
  Redis, and Redis may write it to disk. So a code crosses the broker **encrypted**
  (as built: Fernet, from `cryptography`, `messaging/seal.py`),
  with a key the web and worker processes derive from settings, and it expires with
  the code. The broker holds ciphertext for a few seconds, and nothing that reads it
  later can use it.

The fake provider's table is the one place a raw code is written, and D2 is why that
is acceptable.

### D7. Budgets, and hours

**Codes keep the limits they have**: five per channel and two hundred per school
an hour (`accounts/guardian_contacts.py:451`, OPEN-3).

**School-originated messages get a daily cap per school, counted in segments**, as
a fold over attempt rows, the way the code limits fold over code rows. **A batch is
checked whole before anything is queued.** One that would cross the cap is refused
in full, with a sentence saying how many segments it needs and how many are left
today. A half-sent batch leaves a bursar asking which families got it, and nothing
on the page could answer.

**Quiet hours: school-originated messages go between 07:00 and 20:00, Lagos time.**
*(Changed in review: held, not refused.)* A batch asked for outside those hours is
written as it would be at noon, and its messages are **held until 07:00**. The
button says so before it is pressed: "These will be sent at 07:00." A periodic sweep
queues them at 07:00 (see the decision record for why that needs `celery beat`). The
cap is checked against the day a message will go out, counting what is already held
for that day. Codes are exempt, because the guardian is asking right now and a code
lasts fifteen minutes.

### D8. Code delivery, carrying #111

Code delivery is the first user of the seam and builds it (M1 in the slices below). Four
doors send a code, and each delivers the code its `_mint_code()` returned, after
the commit, through the provider for its channel type:

- door one, `request_verification_as()`: a school admin proving a channel it typed;
- door two, `request_sign_in_code()`: a guardian signing in;
- door three, `request_reactivation_as()`: a school admin reactivating a dormant
  phone;
- **the fourth door, new: a school asking an already-verified guardian to answer
  it** (#135). Today `tests/guardians.py:61` stands in for it and calls
  `activate_guardian_links()` by fiat. Code delivery is the door that sends that school's
  own code to the proved channel, and answering it is what calls that function.

**#111, as decided on 2026-09-24**, is in code delivery because every one of its answers is a
rule about sending:

- `one_live_contact_per_guardian` becomes one live contact per guardian **per
  channel type**, and `record_contact()`'s refusal changes to match;
- the code goes to **the channel the guardian typed**. `_live_contacts_for()` keeps
  the typed value and mints against the matching row, never "the oldest eligible
  row", and nothing is sent twice;
- dormancy stays per channel, so a dormant phone gets no code while a live email
  still does;
- one guardian with two channels is never asked to choose between two copies of
  themselves. *(As built: by construction, not by a fold. The sign-in door matches
  the typed value's own rows, and a guardian holds one live row of a type, so a
  guardian can be offered only once. A de-duplication step would be a branch no
  control could turn red.)*
- the PR C guardians panel can record both channels. D9 and D11 in parent-access,
  `GuardianAccount.live_contact()` and `OneLiveChannelTests` are rewritten to match.

**What a school-facing door shows.** Doors one, three and four were pressed by an
admin, who is told the outcome when it is known: sent, refused by the provider
("that number could not be reached — check it with the family"), or not known. Door
two tells the guardian nothing beyond `CODE_REQUESTED`, whatever happened.

### D9. Result notices: a step after release, not part of it

**"Tell families" is its own button on the released row**, for the principal
(`RELEASING_ROLES`), and pressing it again sends nothing new. A notice is unique per
card and recipient channel. Not sent by `release()` itself, for four reasons:

- **Withholding is decided per card, and can come after release.** A notice sent at
  release could tell a family a card is ready an hour before the bursar withholds
  it. Sent later, it reads the withholding gate at the moment it is sent.
- **Hours.** A principal who releases at nine in the evening would message every
  family at nine in the evening (D7).
- **Cost is a decision.** The button says how many messages it will send before it
  sends them.
- **Release stays what it is.** One transaction that must not depend on anything
  outside the database. #164 just made its one post-freeze step something that can
  stop it, and a provider should not be a second.

**What a notice says:** the school's name and the child's name as frozen on the card
(rule 2), the term, and the school's address to read it at. Nothing else (D3).

**A withheld card's notice says the school is holding it, and who to call.** It is
the sentence and the contact `WithheldOut` already gives a signed-in guardian
(`docs/withholding.md`, "What the 403 carries"), with the word "fees" left out. The
gate says a card is held; it does not publish why, and a lock screen is more public
than a signed-in page.

**Every live guardian of the child** gets one, one channel each (D4). Parent-access
A1, confirmed by one school: both parents deal with the school.

**A child with no card gets no notice.** The release's own record of children left
without a card (#164) is the principal's list, and that is who acts on it.

### D10. Fee reminders: the bursar's act, to whoever receives invoices

From the bursar's fees page: pick a term and a class, or the whole school, and see a
preview: which children, which guardians, how many messages and segments. Then send.

- **To the guardians whose link says `receives_invoices`** (`accounts/models.py:535`).
  The column exists, defaults to true, and is carried across a transfer
  (`accounts/services.py:510`), but nothing reads it yet. This would be its first
  reader.
- **Only children who owe**, by the ledger's own fold, read when the batch is sent.
  Each reminder row records the balance it states, so a later dispute is about a
  number the platform can produce.
- **At most one reminder per child every seven days**, a setting, folded over the
  reminder rows. A bursar pressing twice in a morning sends once.
- **One message per child.** A family with three children gets three. Combining
  them is OPEN-M9.

**The reminder states the amount (decided in review, OPEN-M1).** This overturns
`docs/withholding.md`'s ruling that balances are staff-only "in this phase"
(`results/card_api.py:564`), for the reminder and nowhere else. That ruling's worry
was "a family will dispute a number the bursar has not reconciled". Here, the number
is one the bursar chose to send, having seen it in the preview, and it is frozen on
the row. **It goes only to a live, verified channel**, which D4 already requires of
every message. A pending or dormant channel gets no reminder, so it gets no amount,
and requirement 14 tests exactly that.

### D11. The no-account result checker

**A public page on the school's own host.** The child's admission number
(`Membership.reference`) and a PIN open that child's card for one term, and nothing
else. No session, no cookie, and no account. Every check is asked again from
scratch.

**The answer is the family card payload, byte for byte.** `results/card_api.py`
already builds it from the frozen tables and "does not branch on who is asking", so
the checker is a third reader of the same payload behind **the same gate in the same
order** (`docs/withholding.md`, "The order, which is the security property"). A
withheld card answers with `WithheldOut`. This is also the surface #21 names: "an
unauthenticated result-checker response contain[s] no position field at all". That
test is owed here, with `class_average`.

**The PIN.** Minted per released card, in a batch the principal or an admin asks for
after release, and printed on slips: a PDF of the class, one slip per child, with
the name, the admission number and the PIN. It is shown once and stored hashed, as
codes and invitation tokens are. Re-minting a lost slip revokes the old PIN. It lasts
until the end of the session unless revoked.

**Twelve digits, not six.** A sign-in code lives fifteen minutes and dies after five
wrong guesses. A PIN lives for months and is meant to be used more than once, so it
cannot be capped per PIN without locking out the family holding it. The space does
the work instead (10¹² against 10⁶), printed in three groups of four.

**One answer for every failure.** An unknown admission number, a wrong PIN, a
revoked PIN, and another child's PIN all get the same status and body. **Wrong
attempts are rate-limited per admission number, and per address** (decided in
review), in a scope of their own. After too many in a window, the next attempt waits,
and the wait ends by itself. That is `accounts/throttling.py`'s shape, and
`guardian_signin`'s reason for keeping its buckets apart. An admission number is on
the child's exercise books, so a lock that somebody had to lift would be a weapon
against the family, and a wait is not.

**Why paper, and never a message.** The checker is for families with no verified
channel. Sending a PIN to a number the school typed but nobody proved is sending a
child's results to whoever holds that number, which is D9's reason for verifying a
channel at all. A family with a verified channel does not need a PIN: the notice
points them at sign-in.

**Not decided here:** whether a school may sell PINs, the way scratch cards are sold.
That is a business question and a payment feature (OPEN-M5). The checker works the
same either way.

### D12. A failed delivery is the signal OPEN-2 is missing

Parent-access OPEN-2 records that a school learns a number is dead only when a
message fails, and that "there is not even a place a failure signal could arrive".
D5's attempt rows are that place. A provider that refuses an address, or later
reports it undelivered, writes an attempt row, and **the guardians panel shows the
channel's last outcome**: "the last message to this number did not arrive." That
covers codes, notices and reminders.

The refusal half comes with M1, because `Refused` is raised by `send()`. The
delivery-report half (a webhook from the provider, authenticated by its signature,
resolving the school from our reference and never from the host) needs a real
provider to report anything, and it is slice M5.

## What is configurable

**Per deploy (environment):** the provider per channel type (D1); the daily
per-school segment cap (D7); the reminder interval (D10). Each is a setting with its
argument written at the constant, as OPEN-3's and OPEN-4's were.

**Per school:** whether result notices and fee reminders are offered at all, both
**off by default**, for withholding's reason: a school that has never heard of this
must see no trace of it, and must not start sending messages the day it ships.

**Not configurable, deliberately:** the wording (D3), who may receive (D4), at most
once (D5), and nothing about results in a message body (D9). Each is a rule about
what reaches a family's phone, and a switch would be a second branch nobody tests.

## The slices

One PR each, to `main`, in order:

1. **M1: code delivery, with the seam and the fake.** D1, D2, D5 and D6 for codes,
   D8 with #111, and D12's refusal half. The first real use, so the seam is shaped
   by a caller, not ahead of one.
2. **M2: result notices.** The notice and attempt tables, "Tell families" on the
   chain page, budgets and hours (D7), holding overnight with the `celery beat`
   sweep, and D9.
3. **M3: fee reminders.** On the bursar's page, on M2's tables. D10, with the
   amount.
4. **M4: the result checker.** D11. It sends nothing, so it depends on none of the
   above, and can be built in any order after M1's review. The slips reuse WeasyPrint.
5. **M5: delivery reports.** D12's second half, with the first real provider.
6. **M6: the first real provider**, once OPEN-5 is answered. One class per channel
   type, and `messaging.E001` stops refusing the deploy.

## Correctness requirements

Each is a two-school test with a control that goes red when the guard is removed,
per `docs/parent-access.md`'s requirements and the standing rule.

1. **A raw code is never at rest.** No table holds it, the broker message does not
   carry it in the clear, and no log line contains it. The only exception is the fake
   provider's table, under `DEBUG`.
2. **Production refuses the fake.** `messaging.E001`, tested as a check.
3. **The sign-in door never calls a provider on the request.** A known number and an
   unknown one leave the request having made the same number of provider calls:
   none.
4. **#111's five tests**, as listed on the issue: two live channels held, a second
   phone refused, the code to the typed channel only, a dormant phone skipped while
   the email is not, and the chooser only for two guardians on one handset.
5. **Nothing reaches an unverified, revoked or dormant channel, or a guardian not
   live at the sending school.** Including a guardian live at Grace and waiting at
   St Mary's, who gets nothing from St Mary's.
6. **At most once.** A send task run twice calls the provider once, and a claim with
   no outcome is never resent.
7. **No results in a message.** Every kind is rendered against a card that has marks,
   an average, a position, grades and remarks, and none of them is in the text.
8. **The checker's payload has no `position` and no `class_average` field at all**,
   asserted on the raw bytes (#21's idiom).
9. **Withholding holds at send time and in the checker**, in the gate's order.
10. **Each school's messages stay its own.** A guardian with a child at each school
    receives each school's notice naming only that school's child. A St Mary's PIN
    opens nothing on Grace's host.
11. **A batch over its cap is refused whole**, before anything is queued.
12. **The checker's one refusal** is identical across its four failures, and is
    counted, never locked.
13. **"Tell families" twice sends each notice once.**
14. **A pending or dormant channel gets no amount** (decided in review). A fee
    reminder reaches no unverified channel, no link still waiting for the school,
    and no dormant phone. The test uses a guardian holding one of each beside a live
    email, and asserts the amount appears only in the email's text.
15. **Held overnight, sent at 07:00, once.** A batch asked for at 21:00 Lagos time
    sends nothing before 07:00 and everything at 07:00, and the sweep run twice
    sends each message once. At two schools, one of which asks at noon.

## Open questions

- ~~**OPEN-M1. Does a fee reminder state the amount?**~~ **Closed in review: yes,
  and only to a live, verified channel.** See D10.
- **OPEN-M2 = parent-access OPEN-5. Which provider, and which route.** SMS, WhatsApp,
  or WhatsApp with SMS fallback; sender ID registration; the transactional route for
  numbers on the do-not-disturb register. Needed by M6, and by nothing before it.
- **OPEN-M3. Who pays for a message.** The school per message, a bundle, or the
  platform within a cap. It decides whether D7's cap is a cost control or a bill.
- **OPEN-M4. Phone or email first**, for a guardian with both. Phone matches how the
  school consulted works; email costs nothing per message.
- **OPEN-M5. Checker PINs: free slips only, or may a school sell them?** And whether
  a session is the right lifetime.
- **OPEN-M6. Languages.** English only in v1. Yoruba, Hausa, Igbo and Pidgin are each
  a second template per kind, and for WhatsApp a second approval.
- **OPEN-M7. A revised card** (task 8). Does a family hear about a revision? Not in
  v1.
- **OPEN-M8. Consent and opting out.** Codes and notices are service messages about
  a child the school is responsible for. A fee reminder is closer to marketing in some
  readings, and WhatsApp needs opt-in regardless. With parent-access OPEN-9 (NDPA).
- **OPEN-M9. One reminder per family** instead of per child. It is cheaper, but a
  row would be about several ledgers.

## Found while reading, not part of this proposal

1. **The sign-in page says a code was sent, and none ever is.** `CODE_REQUESTED`
   (`accounts/guardian_signin.py:111`) tells every caller "a code has been sent to
   it", and `request_code()` is documented as "Send a sign-in code"
   (`accounts/guardian_signin.py:255`). The raw code it mints is discarded at `:289`.
   It is right as a neutral answer, and not true of anything the platform does. Code
   delivery makes it true. Until then, guardians can only sign in inside the test suite, which
   takes the raw code from the return value.
2. **"PR D" names two different pull requests.** `docs/parent-access.md:568` ("The
   parent-scoped half of that is enforced as of PR D") means the parent-access
   series' PR D, merged in #110 as `8ad3a4b`. #111, `docs/parent-access.md:220`,
   `accounts/enrolment_api.py:624`, `accounts/services.py:342` and
   `tests/guardians.py:61` mean the screens series' next one, guardian code delivery,
   which is this document's M1. The `:568` sentence should name #110. **Resolved in
   review:** the new one is called "code delivery", and M1 renames the code comments
   that call it PR D.
3. **`Guardianship.receives_invoices` is written and never read**
   (`accounts/models.py:535`). D10 would be its first reader. It is worth one question
   to a school whether "receives invoices" means the guardian who should get a fee
   reminder, or the one who gets the paper invoice, which may not be the same person.
