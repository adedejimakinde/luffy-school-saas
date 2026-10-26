# Guided onboarding

Everybody who signs in should know what to do next. The main case is a school
administrator whose school was just added to Classnode. The code is the
`onboarding` app; the Phase 1 mockups this was built from are in
`docs/mockups/` (screenshots in `docs/mockups/shots/`).

## The administrator's eight steps

| # | Step | Done when (read from the data) | Hint while missing | Who does it |
|---|---|---|---|---|
| 1 | School details | the contact email is set **or** put off, **and** a crest is uploaded **or** put off | | principal, administrator |
| 2 | Session and term | a term is current | | principal, administrator |
| 3 | Classes | an active class exists | | principal, administrator |
| 4 | Subjects | an active subject exists | | principal, administrator |
| 5 | Invite teachers | a teacher membership is invited or active | | administrator |
| 6 | Import students | a student membership is invited or active | a class | administrator |
| 7 | Fee items (optional) | the current term has a fee schedule line | a current term and a class | bursar, administrator |
| 8 | Report card | the current term has a paper (`gradebook.Assessment`) | a current term and a subject | principal, administrator |

**Any order, nothing locked** (since a tester added later-stage items first
and the locks and fixed "next" confused her). Each step is judged on its own
data, so a step done out of order is done. Every step page opens and carries
its own action; a step that goes better after another shows a "Good to know"
hint linking it, never a lock. A step the viewer cannot do (a principal on
"Invite teachers") says who does it instead of offering a button that would
be refused.

The term step used to say "Save. It becomes the current term", which was not
true: opening a term never makes it current (`academics.api.create_term`). It
now says to tap **Make current**, and while a term is saved but none is
current the step's status says exactly that.

Then **Take your first register** is the celebration on Start here, with a
pointer to the dashboard.

- **Nothing is ticked by hand.** `onboarding.progress.read()` is one
  `SELECT json_build_object(...)` over the school's own tables, in the school's
  own schema (`schema_context` when asked from the portal). Delete the last
  class and "Add your classes" is undone again.
- **Not cached.** The dashboard's per-school cache keeps its five minutes for
  the figures, but a step must show done the moment it is, the same reason
  `home.facts.load()` already gives for a school with no students. The cost is
  one statement per page for an administrator whose setup is unfinished, and
  none for anybody else (`for_request()` keeps it on the request, so the chip
  and the page share one read).
- **Finished is written down once.** `School.setup_completed_at` records the
  first time every required step held. After that the chip is gone and sign-in
  never sends the administrator to Start here again, even if a step comes
  undone later, and no query is spent on it. Start here itself still reads the
  steps, so what it shows is always true.
- **The next step** is the first required step that is not done. Fee items are optional: never the next step, marked Optional in the
  list, and the step pages' Next buttons still pass through them ("Skip for
  now").
- **The existing pieces are reused, not copied.** The step pages explain and
  link to where the work is done (`/setup/#terms`, `#classes`,
  `#contact-email`, `#report-card`; `/teaching/#subjects`, `#papers`;
  `/staff/`; `/roll/import/`; `/fees/`). The dashboard's old "Set up your
  school" checklist is gone: the dashboard shows the next-step card instead.

## Pages and who sees them

| Page | Who | Notes |
|---|---|---|
| `/start/` Start here | the administrator and the principal | welcome, one "Your next step" card with one button, the steps with done, next, to do and optional, "N of 8 done", what was put off, the last five setup changes, and Start again (principal) |
| `/start/<step>/` | the administrator and the principal | what this does, why it matters, what to do in three lines, the action (or who does it), a hint when another step would help first, Next |
| `/start/again/` Start again | the principal | what will be cleared and what stays, and the typed confirmation |
| `/help/` Help and next steps | every member of staff | tips for the page you came from, your next step (administrator), Classnode support: hello@classnode.co, "We reply within two working days." |
| `/platform/handover/` | platform staff, on the portal | per school: created, administrator invited, signed in once, setup progress, pilot agreement; a welcome message to copy |

Everybody else gets one sentence ("This page is not yours", 403), signed out
gets "Please sign in", and the portal answers the school pages with the
"lives on your school's own address" state. A school's host has no handover
page (404).

"Skip to dashboard" is on Start here and every step page.

## Add later: the contact email and the crest

Neither is needed for security. The contact email is the school's `Reply-To`
on mail Classnode sends for it and the address on its public page; nobody signs
in with it, and there is no account recovery that uses it. The crest heads the
report card, which prints the school's initials without one. So step 1 offers
**Add later** beside each (`onboarding.later.put_off_as()`, the principal or
the administrator, logged). `School.contact_email_later_at` and
`crest_later_at` record it; the step counts as done once each is given or put
off. Start here then shows "You chose to add these later" with a link to each,
and the dashboard's to-do list keeps "Add your school's contact email" and
"Add your school's crest" until each is given.

## Start again

`/start/again/`, `onboarding.again`. For a school that tried things out and
wants a clean page.

- **The principal only**, by active membership. Not the administrator, not
  platform staff.
- **Only while there are no real records**: no marks (nor report card comments
  or ratings), no register, no fees charged, paid, excused or given an account
  number, and no released results. The page says which one stops it, and
  nothing is cleared.
- **Clears** terms, classes, students on the roll (their membership ended as a
  transfer ends it, their details here removed), subjects and papers, fee
  items, class and subject teachers, class places and the timetable.
- **Never touches** the school or its details, any member of staff or their
  account, staff invitations, the report card's choices, or the setup log. A
  term or class a permanent record names (who taught what, printed exam PINs)
  stays, and the page says why.
- **Typed confirmation**: the school's name. The page carries a fingerprint of
  the plan it listed; if anything changed before the button was pressed,
  nothing is cleared and the page asks to check the list again.
- One transaction, logged inside it with who and when.

## The setup log

`audit.models.Change`, one table in each school's own schema: who (id, name
and roles, copied at the time), when, what kind of item, which one, a sentence,
and what it was and became. Written inside the transaction of the change it
records (`audit.log.record()`). **Append-only twice**: the model refuses a
second save and any delete, and a trigger refuses UPDATE and DELETE from
anywhere (`audit/migrations/0002_a_change_is_never_rewritten`). Today it
records the contact email, the crest, "Add later" and Start again; classes,
terms, students and staff follow in the next two pull requests. Start here
shows the last five.

## Where people land

- **Only the sign-in landing redirects.** `api._schools_of()` answers
  `start_here: true` for a school where this login is the administrator
  (`progress.LEAD_ROLES`) and setup has never been finished. The principal may
  open every step but is not sent there. The staff sign-in page then goes straight to
  `/start/` when that is the one school; with several it lists "Start here"
  first. Everybody else keeps the normal landing.
- **`/home/` never redirects.** An unfinished administrator gets the
  next-step card at the top of the dashboard. A principal at a school with no
  students yet sees how far the administrator has got, with a link to the
  setup steps.

## The setup chip

"Setup N of 8" in the top bar, linking to Start here: for the administrator
only, only until setup is first finished, and never on `/marking/` or
`/register/`, the pages the offline worker keeps on a shared phone, which name
nobody (`menu.shell_open`).

## First days for everybody else

- **Teacher** (dashboard): take a register, enter marks. Nothing about fees.
- **Bursar** (dashboard): set up fees, record a payment.
- **Parent** (`/cards/`): a welcome naming each of their own children
  (`card_api._children_of()`), "See the report card" only for a card released
  to families and not being held, and fees only as the page already shows them
  (where to pay, never a balance).

A card goes when that person has done what it asks (a register they took, a
mark they recorded, a payment they recorded; for the bursar, fee items this
term) or fourteen days after their first sign-in, whichever comes first.
`User.first_signed_in_at` is written once, on the first sign-in
(`onboarding.signals`). There is no hide button.

The invitation email and the accepted-invitation page end with what happens
next, by role; the administrator's names Start here and step 1.

## Empty states

Classes (`/setup/`), students (`/roll/`), teachers (`/staff/`), fees
(`/fees/`), the register and marks each have an empty state with one button,
or, for somebody who cannot do it, a sentence saying who does
(`emptyState()` in `static/web/html.js`). **An empty state is only drawn from
a successful answer with no rows.** A failed, refused or offline fetch has its
own states, and the register and marks never call a copy kept on the phone
"empty" (`tests/js/empty_states.test.js`). The roll before any class exists
says "Add your classes first" and links that step.

The service worker's `CACHE_GENERATION` was bumped (2) so a phone drops the
old register and marking modules.

## The pilot agreement

The one handover check no table can know. Platform staff record the date the
signed copy came back; who recorded it and when are kept with it. A future
date is refused by `record_pilot_agreement()` and again by the
`pilot_agreement_is_not_signed_after_it_was_recorded` constraint (the date may
not be after the Lagos day it was recorded), and
`pilot_agreement_is_recorded_whole` keeps the three fields together.

## The welcome message

"Hello" and the administrator's name, then three numbered lines ending at step
1, and support. Never "Good morning", and **never an invitation link**: the
message is copied and forwarded, and an invitation link is a credential.
