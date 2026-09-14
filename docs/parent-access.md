# Parent access

Status: draft. Structural decisions settled (D1–D11). Domain input **obtained from one
school, September 2026**, which confirmed A1–A7 as written — see the provenance note
below for what one school does and does not settle. Supersedes nothing. Extends
`docs/membership.md`.

**Blocker check: done and clear.** The cross-schema FK concern that gated this phase
has been verified as not applying — see D5. No tenant app holds a relation into a
shared app; `Guardianship` is shared-to-shared. Nothing blocks implementation.

**No longer outstanding:** this used to say the `Guardianship.clean()` enforcement gap
should land first — both of the model's stated rules unreachable on the `save()` path
and held only by a duplicate copy in `link_guardian()`. Issue #91 closed that: `save()`
calls `full_clean()`, and the duplicate is gone. #96's first slice then put both rules
behind `accounts_guardianship_rules`, a trigger, so `bulk_create()` and
`QuerySet.update()` are refused too. What remains open under #96 is the path that
writes no guardianship row at all — a role change on the membership underneath a live
link.

The point the old sentence was making still applies to D10, and applies twice now:
parent onboarding adds construction sites, and as of this revision there are two of
them. Both go through the same action for exactly that reason.

## What this is

Guardians need to reach their children's report cards and fee state. This document
settles what a guardian *is* in the system, how one authenticates, and what one sees.

It deliberately does not cover: parent-initiated payment, or messaging. Those are
later. Cross-school guardian identity is **not** deferred — see D5; it already works.

## Domain assumptions

**Provenance.** One school has been consulted — **September 2026** — and confirmed
A1–A7 **as written**. Before that, nothing in this section was a school telling us what
they do; it was the author's model of Nigerian school practice or drawn from public
sources. That is no longer the state of it, and the warning that used to stand here has
been replaced rather than softened.

**One school is not thirty, and the difference is the whole caveat.** What a single
consultation buys is that these are no longer *invented*: each of A1–A7 is now at least
one real school's practice, described by people who run it. What it does not buy is
that they are *general*. A confirmation from one school cannot distinguish "this is how
Nigerian schools work" from "this is how this school works", and those two readings
diverge exactly where it would be most expensive — a state school versus a private one,
day versus boarding, a school with a functioning bursary versus one without. The second
school consulted is the one that will start telling them apart.

Two consequences that are not rhetorical:

- **The "which decisions survive a wrong assumption" table below stays.** It is not
  leftover scaffolding from the unverified period. n=1 is the regime where that table
  earns the most, because a single school is precisely how a local practice gets
  mistaken for a universal one.
- **Do not re-describe A1–A7 as facts.** They are confirmed observations with a named
  source and a date, which is a different and weaker claim, and the failure mode this
  project has already been bitten by elsewhere is an assumption that gets remembered as
  a fact. Record the next school's answers next to these rather than in place of them.

A8–A10 are **researched, and were not part of this confirmation.** They still carry
their own weight and are still not any specific school's practice.

### Assumed, then confirmed by one school (September 2026)

Every item below was written as an assumption and is now **confirmed as written** by
the one school consulted. ✓ marks that confirmation and nothing more — read it as *one
school does this*, not as *schools do this*. The conditional clauses are kept rather
than deleted: they are what the next school's answer will be checked against.

- **A1. Both parents deal with the school.** Access is not a single "the parent"
  account. ✓ confirmed.
- **A2. A child living with an aunt or grandparent means that adult becomes a
  guardian.** Guardianship follows the household, not the birth certificate.
  ✓ confirmed.
- **A3. The school holds a current phone number** for the parent who pays fees.
  ✓ confirmed — and see D10: this school collects it on the admission form, which is
  *where* the number comes from and was not known when A3 was written. Still the
  load-bearing one: D3 originally rested on the number being verified and live, and a
  confirmation that the school holds one is not a guarantee that it still reaches
  anybody. D9 is what makes that cheap to be wrong about.
- **A4. Each guardian has their own number.** A number identifies one person.
  ✓ confirmed. *If this turns out to be false at another school, sign-in needs a
  disambiguation step.*
- **A5. The paper report card still goes home.** Classnode adds speed, history and
  durability, not first access. ✓ confirmed. *If false elsewhere, parent access becomes
  critical rather than convenient, and the failure modes get much more expensive.*
- **A6. The child sees everything, fees included.** Withholding is a lever: the child
  is meant to know so they press their parents to pay. ✓ confirmed.
- **A7. Students have real credentials** and will sit online exams on them.
  ✓ confirmed.

### Researched (public sources, not school-specific)

- **A8. Class arms are not stable between sessions.** Nigerian schools expand and
  contract streams with enrolment — a year group running six arms (A–F) one session
  may run four (A–D) the next. Arms are a staffing and capacity artefact, not a fixed
  structure.
- **A9. Students are streamed at SSS level** into science/humanities,
  technical/commercial, or teacher education, taking a core set plus electives that
  vary by what the school can resource. Two children in the same year group may hold
  different subject sets.
- **A10. PTA levy is a real, distinct, parent-facing charge** in most Nigerian schools,
  separate from school fees and often collected under separate authority.

### Which decisions survive a wrong assumption

| If this is wrong | These hold | These break |
|---|---|---|
| A1 both parents | D1, D2, D6, D8 | nothing structural |
| A2 household guardianship | all | nothing structural — it changes who a school is willing to enter as a guardian, not what the system models. `Relationship` already carries GUARDIAN and OTHER |
| A3 school holds a number | D1, D2, D6, D8 | D3 channel choice only — D9 absorbs it |
| A4 own numbers | most | sign-in needs disambiguation |
| A5 paper card goes home | all | risk appetite, not structure |
| A6 child sees fees | all, D1 included — its four bullets each stand without A6 | D2's claim that exam surfaces are the *only* divergence between a guardian and a student session. Hiding fees from a student is a second divergence axis, and D2 currently says there is none |
| A7 students sit exams on their credential | D2, D3, D5, D6, D7, D8, D9, D10, D11, and D1 on its other three bullets | **D4**, entirely — it exists only to justify a separate mechanism — and D1's exam-credential bullet. **D3** is untouched: a verified channel plus a one-time code does not depend on exams existing. So what falls is D4, the case for a *second* mechanism, and not D3, the shape of the first |
| A8 class arms are not stable | all. D6's conclusion rests on A9 and on the released-artefact precedent independently | one of D6's two instability arguments. Keying to the student is still correct if arms are stable — it is merely less obviously forced |
| A9 SSS streaming | all. D6's conclusion rests on A8 and on the released-artefact precedent independently | D6's streaming argument and its "different subject set" bullet. The JSS3 → SSS1 boundary survives either way: promotion is not streaming |
| A10 PTA levy is distinct | D1–D6, D8–D11 | D7 entirely — with no distinct parent-facing levy there is nothing for two settings to configure. Cheap to be wrong about, because both settings default off: a school without a levy leaves them off and sees nothing |

The last three rows are the researched assumptions. They are listed anyway, because D6
and D7 rest on them and a table that omits the load-bearing ones is the table telling
you they are facts.

**This table survived the confirmation deliberately.** The obvious move on hearing a
school say "yes, all seven" is to delete it; that would be the same mistake as reading
one school as thirty. Every row is still the answer to "what breaks if the *next*
school says no", and it is now more useful than before rather than less — n=1 is where
a local practice most easily passes for a universal one.

The point of D9 (channel-agnostic verification) is to make A3 and A4 cheap to be wrong
about.

## Decisions

### D1. A guardian is a person, not a shared child login

A guardian authenticates as themselves. They do not sign in as the child.

The reasoning is not privacy, and it does not rest on A6. Each of the four below
holds whether or not the child sees fee state:

- **The student credential is an exam credential.** A shared login puts an
  exam-taking credential on two or three adults' phones. That is an integrity
  problem, and it surfaces the first time a parent has a live session during a test.
- **Two parents, separately revocable.** One shared password cannot be withdrawn from
  one parent without withdrawing it from both. Schools end up in the middle of
  separations with no mechanism.
- **One guardian, several children.** A parent with three children in the school
  should hold one credential, not three.
- **The fee ledger must name a person.** "The account paid" is not an audit trail
  when a payment is disputed.

### D2. There is no parent portal

A guardian credential resolves to the child's dashboard. Same screens, same numbers,
one source of truth. A guardian holding several children gets a chooser and nothing
else.

A second portal would duplicate every result and fee view and give the same number two
places to disagree. It is also the local norm and the local norm is wrong here: the
prevailing pattern (see UNSS Nsukka and similar) hangs a parent account off an email
address collected on an admission form, which is both the wrong channel and a field
that goes stale.

The only divergence between a guardian session and a student session is that **exam
surfaces do not render for a guardian.**

### D3. Authentication is a verified contact channel plus a one-time code

No password for guardians.

- Passwords for infrequent use become forgotten passwords, which become support load
  on a school secretary. A guardian opens this a handful of times a term.
- It disposes of the deferred invitation flow. The first code sent to a verified
  channel *is* the invitation. No emailed token, no accept-and-set-password page, no
  `create_user(username, None)` placeholder.

The channel is a field, not a hardcoded assumption. See D9.

**Reuse, do not reinvent:** phone normalisation must go through the existing E.164
handling and `matching_identifier()` from PR #2. Codes must be stored hashed,
following the same pattern as the staff invitation tokens in PR #5. Neither is a new
problem.

#### Why the channel cannot simply be "phone"

Nigerian operators churn numbers after a total of 360 days of inactivity (180 days
without a revenue-generating event, then a further 180) and reassign them to new
subscribers. The documented consequence is that new users inherit messages intended
for the previous owner, including financial alerts; the NCC is building TIRMS
specifically because mobile numbers now function as digital identities and
per-sector controls leave gaps.

Applied here: a guardian stops using a line, a year passes, the number is reassigned,
and the new holder can request a code and reach a child's report cards, arrears and
comments. There is no password in the way, because D3 removed it.

**A reassignable resource cannot be the durable identity key.** Email is not churned
and reassigned, which makes it the better anchor where it exists. But whether schools
hold usable guardian *emails* is still unverified — A3's September 2026 confirmation
was about phone numbers, and the admission form in D10 is where those come from. So the
design must not depend on the answer.

### D9. The contact channel is verified in-band, and its type is a field

A guardian record holds a **contact channel** — email or phone — with a type, a value,
and a verified flag. The channel is entered by a school admin (D10) and is **not
trusted because a school typed it.** Classnode sends a verification to the channel and
the guardian link does not go live until it comes back.

This is the one decision that makes A3 and A4 cheap to be wrong about. If schools turn
out to hold good emails, email is the identity. If they only hold numbers, phone works.
No rewrite either way.

**Where the channel is a phone number, a dormancy rule applies:** the guardian link is
suspended after **180 days without a successful authentication**, requiring school-side
reactivation before any further code is sent. This finishes ahead of the telco's clock
— a number is not even eligible for churning until 360 days — and never touches an
active guardian, since three terms a year means a natural sign-in roughly every four
months and the longest natural gap (the long vacation) is about two.

Where the channel is email, no dormancy rule is needed.

**Never auto-create a guardian from an inbound contact.** A channel the school does not
hold gets nothing: no account creation, no enumeration, and no "we have sent you a
code" for an unknown value. Combined with the dormancy rule, a recycled number reaching
a suspended link hits a school-mediated step where a human can notice the person is not
who the record says.

**Give the guardian record a stable opaque identifier at creation** — not the channel
value, not the row pk. This is not cross-school identity (D5 still stands). It costs
nothing now and is the difference between "merge two guardian records across schemas"
being hard and being impossible when portable records arrive.

### D10. A school admin creates the guardian record — standalone, and from the admission form

Create guardian, attach to child, enter contact channel.

**Two entry points, one record.** The standalone admin action is the primitive. The
admission form is the second way in, and it creates **the same guardian record, through
the same code path, with the same verification step** — not a parallel one.

**What changed.** This decision used to rule admission out, on the grounds that no
admission flow had been observed and anything built inside one would be a guess about a
process we did not know. That reasoning was sound and its premise has expired: the
school consulted in September 2026 **collects guardian details on the admission form**.
It is where the phone number in A3 actually comes from. Building only the standalone
action would now mean a school typing the same guardian twice — once on paper at
admission, once again into Classnode — which is how a system starts being worked around.

**The standalone action stays the primitive, and is not merely the first half of
admission.** Admission happens once, at the start; guardianship changes during the
session, and those are exactly the cases a form fired at intake cannot reach:

- a child already enrolled whose aunt becomes guardian mid-session
- a second parent added later
- a guardian replaced after a separation
- a guardian attached to a *second* child, who was admitted in a different year

So the ordering is: build the standalone action, then have admission call it. Admission
is an entry point to it, not a copy of it, and not its owner.

**Both routes converge on one guardian record with one verification step.** Stated
plainly because it is the thing most likely to drift once there are two doors. The
guardian is one row with one opaque identifier (D9), reached by one action. The
contact channel is verified in-band exactly once per channel, by the same mechanism,
whichever door it came through — a guardian entered at admission is **not** trusted
more than one entered mid-session, and admission does not get a shortcut past
verification because the details arrived on a form the school printed. Two entry points
with two verification stories would be two guardian records wearing one name, and the
divergence would surface as a parent who cannot sign in with details the school is
certain it holds.

One guardian, one child, one action. Attaching a second child is the same action again.
No bulk import, no CSV, not yet.

Guardians never self-register. An admission form filled in by a parent is not
self-registration: it is a school admin entering what the form says, under the school's
authority, through the action above.

### D11. Contact changes are clerical; relationship changes are authority

**Changing a contact channel:** any school admin may do it, and the change goes through
the same verification the original did. No permissions hierarchy — a hierarchy would
encode school politics that have not been observed, and get them wrong in a way that
makes staff work around the system. Verification is the real safeguard: it matters less
who typed the new value than that the person holding it must prove control before the
link works.

Mechanically: new channel entered → old binding revoked immediately → link suspended
until the new channel verifies. Old and new both recorded as **append-only rows, never
a mutated column**, per the operating rules. That yields an audit trail answering "who
changed this and when" without having had to predict who would be allowed to.

**Changing the relationship** — removing a guardian, attaching a new one — is not
clerical. It is an authority decision in the same category as card withholding, and
belongs to whoever the school designates. Do not collapse the two.

### D4. Student authentication stays password-based and separate

Different threat model, different mechanism, deliberately. A credential that sits an
invigilated exam wants a secret the student owns and can be held accountable for. A
credential a parent uses three times a term wants a code and a long session. There is
no reason to force one shape onto both.

### D5. Guardian identity is already cross-school. Nothing to defer.

**This decision was reversed after verification. The original text argued for scoping
guardian identity per school to avoid the cross-schema FK blocker. That reasoning was
void, and it argued against something PR #1 had already solved deliberately.**

One `User` is one person across every Classnode school. `Guardianship.student` points
at the child's **STUDENT `Membership`**, not their `User`, and that single FK pins both
the child and the school they attend. The model docstring states the consequence
outright: a parent with three children at two schools has three `Guardianship` rows and
two PARENT memberships.

Portable guardian identity is therefore not a later phase. It is the existing shape.

#### The cross-schema FK blocker does not apply, and is discharged generally

Verified by sweep across `academics`, `fees`, `gradebook` and `results`:

- **Zero** `ForeignKey`, `OneToOneField` or `ManyToManyField` fields in any tenant app
  target a model in `accounts`, `schools` or `django.contrib.auth`.
- Every relation target in those apps' 33 migration files resolves inside the tenant
  apps. `grep` for `AUTH_USER_MODEL` and `contenttypes` over those migration dirs
  returns nothing.
- `Guardianship` itself is in `accounts`, which is in `SHARED_APPS` only. Both its FKs
  (`guardian` → `User`, `student` → `Membership`) are shared-to-shared. No schema is
  crossed, so `PROTECT` behaves normally.

What stands in place of cross-schema relations is a deliberate, documented policy:
bare `PositiveBigIntegerField` ids into `accounts.Membership` and `accounts.User`,
settled in `docs/tenancy.md` and applied consistently in `ClassPlacement`,
`ClassTeacher`, `Score`, `FeeConcession`, `FeeLedgerEntry`, the results approval-step
actor and `WithholdingDecision`. The reasoning is stated correctly at
`gradebook/models.py:208` — `on_delete` resolves against whichever schema the
connection is on, so `PROTECT` does not protect and `CASCADE` cascades one school's
rows only.

**The blocker is resolved by avoidance, and the avoidance is enforced by convention.**
It should no longer be carried as a live unresolved risk. What it *does* impose is a
standing rule: any new tenant-side model must follow the bare-id policy rather than
adding an FK to a shared model. Parent onboarding adds no tenant-side models, so it is
unaffected.

**Remaining caution:** the policy is convention, not a constraint. Nothing mechanically
stops a future model from adding the FK. If that protection is wanted, it is a separate
piece of work — a migration-time or CI check — not part of this phase.

### D6. Guardianship keys to the student, never to class, arm or stream

A guardian stands for a child, not for a position in a class list.

This follows from A8 and A9. A guardian link resolved through `ClassGroup` or
`ClassPlacement` breaks when a year group drops from six arms to four, and breaks
again when the child is streamed into science at SSS1. It is the same rule already
documented for released artefacts — guards key off the artefact, not the child's
current placement — applied to guardianship.

Concretely, guardian access must survive:

- a change of arm within the same year group
- promotion between year groups
- **the JSS3 → SSS1 boundary**, which is the common case and easy to miss because it
  looks like a school change and is not one
- streaming into a different subject set

### D7. PTA levy is school-configurable, in two independent settings

Whether the levy is collected through the school office, through a PTA treasurer, or
not at all is a school decision, not a platform decision. This matches the existing
pattern for affective/psychomotor traits, session-average weighting and card
withholding.

Two settings, deliberately separate:

1. **Whether PTA levy appears as a fee line at all.** Defaults off.
2. **Whether an unpaid levy counts toward the arrears that trigger card withholding.**
   Defaults off, independently of the above.

These come apart in practice. A school may want the levy tracked and visible to
guardians without letting it withhold a child's report card, on the reasoning that the
school did not set the charge and the PTA has no authority over results. Collapsing
the two into one switch would force a policy the school has not chosen.

Guardians see the levy in the same view as school fees when it is enabled.

### D8. Extend `Guardianship`, do not replace it

PR #1 already models the relationship: this adult stands for this child. What is
missing is the credential, not the relationship. Add authentication alongside, keep
the existing membership and role plumbing intact.

## Open questions

Each of these needs a school-side answer before implementation.

- ~~**OPEN-1. Who creates the guardian record?**~~ Closed by D10, and **revisited
  September 2026** as that note asked: the school consulted collects guardian details
  on the admission form, so D10 now carries admission as a second entry point onto the
  same record. The standalone action stays the primitive.
- ~~**OPEN-2. What happens when contact details change?**~~ Closed by D11, decided
  without school input. **Still not revisited.** A school is now available and this is
  the question that was not put to them, so the note that used to say "revisit once a
  school is available" has been answered for D10 and not for this. Ask it next.
- **OPEN-9. Data protection.** Classnode will hold guardian contact details and
  children's academic records across many schools. Under the NDPA the schools are
  controllers and Classnode is a processor, implying lawful basis, retention limits,
  subject access, breach notification, and contract terms with each school. None of
  this exists in the repo. Minimum viable: a retention and deletion policy, a data
  processing clause in the school contract, and a deletion path that actually works
  when a school leaves. **The deletion path is correctness-critical** — data deletion
  is on the standing list — so it gets a real test with 2+ tenants, not a description.
- **OPEN-3. Code lifecycle.** Length, expiry window, retry limit, lockout behaviour,
  rate limiting per number and per school. Related to #17 (throttle sweep).
- **OPEN-4. Session duration.** Long sessions reduce SMS cost materially, since every
  code is a metered send under the current pricing model. How long is acceptable on a
  device that may be shared or lost?
- **OPEN-5. Delivery channel.** SMS, WhatsApp, or both with fallback. Cost and
  reliability differ; this is partly a pricing decision.
- **OPEN-6. Revocation.** Who can revoke a guardian's access, and does revocation
  survive the child changing class or school?
- **OPEN-7. End of relationship.** What happens to guardian access when a student
  transfers out or graduates. Interacts with the transfer handshake in PR #7. Note
  this is genuinely the *end* of the relationship — in-school transitions including
  JSS3 → SSS1 are covered by D6 and are not an end.
- **OPEN-8. PTA levy authority.** D7 settles the shape but not who administers it. If
  a school enables the levy, does a school admin manage those lines, or does the
  design need a PTA-side actor? Adding a role is a larger change than adding a
  setting; prefer the setting unless the school side insists otherwise.

## Correctness requirements

This phase touches authentication and reaches the fee ledger, so it falls under the
standing rule: behaviour is proven with runnable tests, not explained.

- Every guard gets a control run that goes red when the guard is removed. A test that
  stays green with the fix reverted proves nothing.
- Controls must aim at the branch the test actually routes through, not the branch its
  name implies. Two authority branches need two controls.
- All isolation and identity tests run with **2+ tenants**. Single-tenant tests are
  blind to this entire failure class.
- Assertions pin identity, not "something was raised" — per #89, and note that
  substring assertions on refusal messages are unreliable where several messages share
  wording.
