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
- The facts stated are the system's own: Hetzner, Backblaze B2 backups kept up
  to 12 months, Sentry (EU) with personal data removed, Termii for SMS,
  Paystack, payments that are reversed and never edited, one schema per school.

## The demo request form

`website.DemoRequest`, in the public schema (the school has no schema yet).
A plain form post, CSRF-checked, that works with no script.

- **Saved first, then emailed** to every active platform staff login with an
  email address (`website/notify.py`), after the row commits. A send that fails
  is logged and the row stays: the admin (on the portal) lists every request,
  read only.
- **Honeypot**: a field named `website`, off screen and out of the tab order. A
  post that fills it is answered exactly like a real one and nothing is saved
  or sent.
- **Rate limit**: `DEMO_REQUESTS_PER_HOUR` (5) per network address, counted
  from the saved rows, so it holds across worker processes. The address is
  `accounts.throttling.client_address()`'s. Over the limit is a 429.
- The two refusals (a field missing or wrong, too many requests) show a visible
  **TODO** for their wording: no copy was given for them, so none was written.

## The page

- **The words are the copy as given, word for word**: the price (₦2,500 per
  student, per term, no setup fee), the call-back time (one working day), the
  footer (Classnode. Nigeria.) and the contact address (hello@classnode.co)
  included. The two form refusals are still visible `TODO`s: no wording was
  given for them. `website/tests/test_homepage.py` holds the page to that copy
  and to the writing rules: no en or em dash, no exclamation or question mark,
  no sentence starting "Imagine", none of the banned words.
- **One Blue** (`docs/design.md`): the tokens from `design.css`, Hanken
  Grotesk, no gradient. The one dark band is the fees section, on the ink. It
  is the one thing that runs edge to edge; everything else stops at 1200px.
- **Screenshots** are real screens of a school having a good day: the
  showcase school, `manage.py load_demo --showcase` (`schools/showcase.py`, demo
  data only, on a demo server). A strong student's card (about 78%, A1 to B3,
  attendance and both remarks), a healthy marks sheet, a home with every
  register in, results released and nothing flagged, and a released
  broadsheet. `scripts/site_shots.mjs` takes them and `scripts/site_shots.py`
  cuts them to size into `static/website/shots/`, as WebP with their sizes set.
  Their `alt` is empty: the words beside each say what it shows.
  - **Load a fresh showcase before each capture.** SS 1A's register for today
    is left untaken on purpose: the script photographs its teacher about to
    take it, then submits it on the page, so the home it photographs next has
    every register in. On a second run the script stops and says so.
  - Laptop shots are taken 1000px tall and cut just under the last whole menu
    item, so no item is cut in half and Sign out is not in the picture
    (1280 by 919).
  - The home says "2 of 3" released: SS 1A is the open class the marks sheet is
    taken from, since a released class's marks sheet is locked. It raises no
    row on the home: a class with no sheet is waiting on nobody.
- **Drawings** are inline SVG built from the mark's shapes (rounded square,
  nodes, lines), styled from the tokens, under 15 KB together: the logo, which
  draws itself once on load (nodes, then lines, 1 second); the results, fees
  and bad-network flows, which play once when scrolled into view (results sits
  under its words, as fees sits in its band; the fees one runs top to bottom on
  a phone; bad network is a phone holding queued marks, then the cloud with a
  tick once they are sent); and the still pattern behind the hero, at 2.5%, a contrast
  of about 1.04:1.
- **Motion** is the slides (every 6 seconds, a 400ms crossfade, held on hover,
  focus or a touch), the fade-up of each section, and the drawings. All of it
  plays once, and all of it is off under `prefers-reduced-motion`: then the
  slides change only from their dots, with no fade, and everything is drawn
  finished. Without the script the page reads in full, on its first slide.
- **Weight**: under 400 KB with every image counted, lazy ones too (about
  250 KB today, the drawings about 3 KB). One module, `static/website/site.js`, no imports, nothing from
  another host.

## What holds it

- `website/tests/test_legal.py`: the two pages answer on the site host only,
  contents match sections, the NDPA topics and the controller and processor
  are there, the TODOs are there, the writing rules and sentence length hold.
- `website/tests/test_homepage.py`: the hosts, the copy and the writing rules,
  the form, the 400 KB and 15 KB budgets, that no motion sits outside
  `no-preference` and nothing loops, and the pattern's contrast, worked out
  from the stylesheet.
- `tests/ui/screens.test.js`: the homepage, the privacy notice and the terms at 320, 360, 390, 414, 768, 1024, 1280
  and 1920, photographed finished, and held to the layout above; and its motion
  (`the homepage's motion`) on a fake clock: the 6 seconds, the 400ms fade, the
  three holds, nothing moving under reduced motion, every animation once.
