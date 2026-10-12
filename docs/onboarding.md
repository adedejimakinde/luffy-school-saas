# Guided onboarding

Everybody who signs in should know what to do next. The main case is a school
administrator whose school was just added to Classnode. The code is the
`onboarding` app; the Phase 1 mockups this was built from are in
`docs/mockups/` (screenshots in `docs/mockups/shots/`).

## The administrator's eight steps

| # | Step | Done when (read from the data) | Locked until |
|---|---|---|---|
| 1 | School details | `School.contact_email` is set **and** a crest is uploaded | |
| 2 | Session and term | a term is current | |
| 3 | Classes | an active class exists | |
| 4 | Subjects | an active subject exists | |
| 5 | Invite teachers | a teacher membership is invited or active | |
| 6 | Import students | a student membership is invited or active | a class exists |
| 7 | Fee items (optional) | the current term has a fee schedule line | the term and a class exist |
| 8 | Report card | the current term has a paper (`gradebook.Assessment`) | the term and a subject exist |

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
- **The next step** is the first required step that is not done and not
  locked. Fee items are optional: never the next step, marked Optional in the
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
| `/start/` Start here | the school administrator | welcome, one "Your next step" card with one button, the steps with done, next, to do, locked and optional, "N of 8 done" |
| `/start/<step>/` | the school administrator | what this does, why it matters, what to do in three lines, the action, Next; a locked step says what to finish first and links it |
| `/help/` Help and next steps | every member of staff | tips for the page you came from, your next step (administrator), Classnode support: hello@classnode.co, "We reply within two working days." |
| `/platform/handover/` | platform staff, on the portal | per school: created, administrator invited, signed in once, setup progress, pilot agreement; a welcome message to copy |

Everybody else gets one sentence ("This page is not yours", 403), signed out
gets "Please sign in", and the portal answers the school pages with the
"lives on your school's own address" state. A school's host has no handover
page (404).

"Skip to dashboard" is on Start here and every step page.

## Where people land

- **Only the sign-in landing redirects.** `api._schools_of()` answers
  `start_here: true` for a school where this login is the administrator and
  setup has never been finished. The staff sign-in page then goes straight to
  `/start/` when that is the one school; with several it lists "Start here"
  first. Everybody else keeps the normal landing.
- **`/home/` never redirects.** An unfinished administrator gets the
  next-step card at the top of the dashboard. A principal at a school with no
  students yet sees how far the administrator has got.

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
