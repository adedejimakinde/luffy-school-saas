# The public site: classnode.co

Classnode's own homepage, for a school that is not a customer yet. It lives on
the bare platform domain (`SITE_HOST`, which is `PLATFORM_DOMAIN` unless set),
and `www.` is the same site (django-tenants drops `www.` before it looks a host
up). `/privacy/` and `/terms/` are on it too, and nothing else is.

## Where it answers, and where it does not

- **Not a `Domain` row and not a school.** A row for the bare domain would make
  it the portal, with the admin and both sign-in doors on it.
  `schools.middleware.PlatformTenantMiddleware` (django-tenants' own middleware,
  plus this one host) sends it to `urls_site.py`, which routes the homepage and
  nothing else. Every other host is resolved exactly as before, and an unknown
  one is still a 404.
- **The doors stay on the portal.** "Staff sign in" and "Parent sign in" link to
  `//app.<domain>/staff-sign-in/` and `/sign-in/` (`schools.hosts.portal_host()`).
- `/healthz/` answers here as on every host: it is answered before any of this.
- **Deploying it needs nothing new.** The apex A record and the certificate
  already cover the bare domain (`docs/demo-server.md`); `migrate_schemas` adds
  the one table.

## The privacy notice and the terms

`website/templates/website/privacy.html` and `terms.html`, both drawn inside
`legal.html`: the homepage's header and footer, one reading column, and a
contents list at the top that matches the sections in order.

- **Plain words for a parent**: short sentences (a test refuses one past 30
  words), and the same writing rules as the homepage.
- **The school is the controller and Classnode is the processor**, said in
  those words near the top of the privacy notice. Classnode is the controller
  only for demo bookings and its own security records.
- **The NDPA basics, one section each**: what is collected, why, the legal
  basis, where it is stored, who it is shared with (the school, the email
  provider, Termii, Paystack, and the hosts), how long it is kept, children's
  data and consent through the school, rights, complaints, contact.
- **Every legal claim carries a visible `TODO: lawyer`**, and every fact still
  to be filled in (RC number, registered address, server location, email provider,
  periods, dates, invoicing) a `TODO` of its own. Nothing here is legal advice
  until the lawyer has been through it.
- The facts stated are the system's own: the VPS host (any Ubuntu 24.04 VPS, Contabo or similar), Backblaze B2 backups kept up
  to 12 months, Sentry (EU) with personal data removed, Termii for SMS,
  Paystack, payments that are reversed and never edited, one schema per school.

## The demo request form

`website.DemoRequest`, in the public schema (the school has no schema yet).
A plain form post, CSRF-checked, that works with no script.

- **Saved first, then emailed** to the demo inbox, `DEMO_REQUEST_INBOX`
  (`hello@` the platform's domain unless set: hello@classnode.co in production), and to every active platform staff login
  with an email address (`website/notify.py`), after the row commits. A send that fails
  is logged and the row stays: the admin (on the portal) lists every request,
  read only.
- **Honeypot**: a field named `website`, off screen and out of the tab order. A
  post that fills it is answered exactly like a real one and nothing is saved
  or sent.
- **Rate limit**: `DEMO_REQUESTS_PER_HOUR` (5) per network address, counted
  from the saved rows, so it holds across worker processes. The address is
  `accounts.throttling.client_address()`'s. Over the limit is a 429.
- The two refusals (a field missing or wrong, too many requests) each show one
  plain sentence above the form (`.refused`). Neither makes a claim.

## The page

Seven sections in order: the hero, four benefits, how it works, the price
beside the demo form, six questions, a final call to action, and the footer.

- **The words say what the product does and promise no outcome we cannot
  show.** Kept as the owner gave them: the price (₦2,500 per student, per term,
  no setup fee), the call-back time (**two working days**), the footer
  (Classnode. Nigeria.) and the contact address (hello@classnode.co).
  `website/tests/test_homepage.py` holds the page to that copy and to the
  writing rules: no en or em dash, no exclamation mark, no sentence starting
  "Imagine", none of the banned words, and **no question mark outside the six
  questions** (native `<details>`, each one ending in its question mark).
- **No invented proof.** No testimonial, school logo or customer count. A
  `<section class="proof" hidden>` is kept for real quotes and logos, each with
  the school's written permission, and is empty until then.
- **TODO notes** on the privacy notice and the terms are drawn only when `SHOW_LEGAL_TODOS` is on (off by
  default; on with `DJANGO_DEBUG=1` and in the legal tests). Every open one is listed in `docs/handover.md`.
- **One Blue, with more of it** (`docs/design.md`): the top band (the header
  and the hero, or a legal page's title) is One Blue deepening toward the ink;
  the four benefit rows alternate white and a 5% wash of blue; "How it works"
  sits on One Blue with white step cards; the price is white on a blue band;
  the final band is One Blue again and the footer the deepest blue. Words on
  every blue are 4.5:1 or better, worked out from the tokens by a test. Icon
  tiles are One Blue, teal, amber or coral, white icons on each (5:1 or
  better), and those three accents are used for nothing else.
- **The slider's screens are real screens of a demo school**: the showcase,
  `manage.py load_demo --showcase` (`schools/showcase.py`), Crestfield Demo
  College, 612 students, ₦48.6m of ₦71.2m collected, seven classes checked and
  waiting on the principal, about 94% in each day, on the Ogun State template.
  Four screens, each at a desk's shape and a phone's: the principal's home, the
  strong student's Ogun State report sheet, the register on a teacher's phone
  (in a phone frame, not the browser frame), and the bursar's fee collection.
  `scripts/site_shots.mjs` takes them **on a weekday** (a weekend home says
  there are no registers on a weekend) and `scripts/site_shots.py` cuts them
  into `static/website/shots/`. The page says under the slider that the school
  is a demo and every name and figure is made up.
- **The floating cards carry the screens' own figures** (₦48.6m, 93.8% today,
  seven classes, a ₦120,700 payment), never rounder ones; a test counts them.
  Retaking the screens is a reason to check them: 93.8% was a Thursday's.
- **The photos** are three the owner supplied, cut to their spaces as WebP
  under 60 KB each, with their sizes set: a principal at her desk (the hero), a
  bursar at a laptop (fees) and a teacher with a phone (the register). No photo
  shows a child's face. Their sources and licences are recorded below.
- **Drawings** are inline SVG: the Classnode mark grown into a network of
  nodes and lines behind the hero's picture (under 5 KB, never behind the
  words: the right half on a desk, under the picture on a phone), a still copy
  of it either side of the final band on a desk, and the product parts the
  benefit rows draw in CSS (the report sheet, the register, the roles), each
  read by its description.
- **Motion**, all of it inside `prefers-reduced-motion: no-preference`:
  - the slider: a new screen every 5 seconds, a 600ms crossfade, held while the
    pointer is over it, while keyboard focus is inside it and for two seconds
    after a touch, and stopped by its own Pause button; dots jump to a screen.
    Screens 2 to 4 are fetched only after the page has loaded. Under reduced
    motion it does not move and the Pause button is not drawn; without the
    script the first screen shows and no controls are drawn;
  - the network: lines draw in once, then the nodes breathe;
  - the floating cards drift 5px up and down, each on its own 4.4 to 5.8
    second loop; the dot grids drift one tile, slowly;
  - sections fade and rise as they scroll in (CSS scroll-driven animation,
    staggered across a row; a browser without it shows them finished);
  - the cards' figures count up once as they come into view.
- **One script, inline**: closing the phone menu on every page, plus the
  slider (under 2 KB) and the counting figures (under 1 KB) on the homepage.
  No library and nothing from another host.
- **Weight**: a phone fetches about 350 KB uncompressed with every image
  counted at 2x, the deferred screens and the lazy photos too (under the
  400 KB budget a test holds), and less over the wire.

### Photo sources and licences

| photo | where | source | licence |
| --- | --- | --- | --- |
| `photos/principal-*.webp` | hero | supplied by the owner, 11 October 2026 | to be confirmed by the owner before launch |
| `photos/bursar-*.webp` | fees row | supplied by the owner, 11 October 2026 | to be confirmed by the owner before launch |
| `photos/teacher-*.webp` | register row | supplied by the owner, 11 October 2026 | to be confirmed by the owner before launch |

## What holds it

- `website/tests/test_legal.py`: the two pages answer on the site host only,
  contents match sections, the NDPA topics and the controller and processor
  are there, the TODOs are there, the writing rules and sentence length hold.
- `website/tests/test_homepage.py`: the hosts, the copy and the writing rules
  (question marks in the FAQ only), the hidden proof section, the floating
  figures, the form and its inbox, the phone's 400 KB budget, photos under
  60 KB, images sized, described and lazy below the hero, the one inline
  script and its sizes, motion only inside `no-preference`, and the contrast
  of every word on every blue.
- `schools/tests/test_seed_demo.py` `ShowcaseTests`: the showcase's figures,
  the ones the homepage prints.
- `tests/ui/screens.test.js`: the homepage, the privacy notice and the terms at 320, 360, 390, 414, 768, 1024, 1280
  and 1920, photographed finished and held to the layout above; and its motion
  (`the homepage's motion`) on a fake clock: the 5 seconds, the 600ms fade, the
  hover, keyboard, touch and Pause holds, nothing moving under reduced motion,
  only the floating cards, the network's dots and the dot grids looping, and
  every figure counting to the screens' own.
