# The public site: classnode.co

Classnode's own homepage, for a school that is not a customer yet. It lives on
the bare platform domain (`SITE_HOST`, which is `PLATFORM_DOMAIN` unless set),
and `www.` and plain HTTP are sent to `https://` and the bare domain in one hop
(Caddy, and `website/crawlers.py` for any that reach the app). `/privacy/`,
`/terms/`, the blog (`/blog/`, its posts and their pictures: `docs/blog.md`)
and `/sitemap.xml` are on it too, and nothing else is.

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

Seven sections in order: the hero, four benefits (the first of them the
report sheet), how it works, the price beside the demo form, six questions, a
final call to action, and the footer.

- **Only the hero has an eyebrow** (its small blue line over the headline); no
  other section has one. **Headlines are not all centred**: the benefits'
  headline, "How it works" and the questions start at the left
  (`.section-head-start`), the questions' headline beside the list on a desk;
  each benefit's heading sits beside its picture; the price and the final band
  stay centred. **No word sits alone on a line**: every heading, question and
  short line (the notes under the hero and the sheet, the price's line, the
  final band's) is balanced, longer copy wraps "pretty", and no heading has a
  `<br>`. Tests hold all three (`loneWords` measures it at every width).
- **Sizes** (the owner's rules, fintech sizes rather than a template's, held
  by `the homepage's sizes` in the browser at 360 x 800, 375 x 812 and 1280 x
  800; the viewport is `width=device-width, initial-scale=1`): section
  headlines at most 24px at 360px, 24 to 28px on a phone and 32 to 40px on a
  desk (`h2` is `clamp(24px, 14.4px + 2.4vw, 40px)`), other headings at most
  28px and 40px (`h3` 20px at 360px); the hero headline at most 30px at 360px,
  30 to 36px on a phone and 48 to 56px on a desk (`clamp(30px, 18px + 3.33vw,
  56px)`), line height 1.1; body copy 15 to 16px
  on a phone and 16 to 17px on a desk (`--copy-lg`, the lead and the larger
  copy, is 16px and 17px from 768px; `--copy-note`, the notes under the hero,
  the slider and the sheet and the form's labels, 15px and 16px); small
  labels 13 to 14px (`--label-sm`, 13px); buttons 44 to 48px tall with 15 to
  16px words and 8 to 10px corners, the hero's two 44px tall and side by side
  on a phone from 360px, stacked below it; sections 56px top and bottom on a
  phone and 104px from 768px, the benefit rows 64px and 88px; cards 20px in on
  a phone and 24px from 640px (`--card-pad`) and 14px round, the benefit
  rows' icon tiles 36px on a phone and 56px from 640px, each step's number
  28px on its title's line on a phone; photos 16px round; content at most 1160px
  wide; two font weights (400 and 700) in every section and no long centred
  paragraph. On a 375 x 812 phone the first screen holds the headline, its
  subline, the main buttons and the top of the screens; the hero
  is tighter below 640px to make the room. Not held to them: the price figure
  (64px, a figure rather than a heading), the slider's own controls and its
  address bar (the slider is kept as it is), the drawings' own paddings (the
  report sheet, the roles, the register phone and the floating cards are
  pictures of the product) and the footer (its text is 13 to 14px, its own spec).
  Measured at 360px before this pass: the hero 33px, section headlines 28px,
  body 16px, buttons 48px and full width, cards and steps 24px in, the step
  number 44px above its title, benefit tiles 56px.
- **The slider's register screen gives the slider no height** on a desk
  (`contain: size` on `.slide-phone`): it takes the height of the other
  screens. Before, its picture had none until it loaded, a second after the
  page, and the slider stood twice as tall until then, pushing the desk's
  headline below the fold and then snapping back. Its phone is exactly as tall
  as the screens (one grid row, `minmax(0, 1fr)`): it was sized by its image's
  `sizes` and ran past the slider, over the caption at 768px.
- **From 768px the hero is two columns**, the words at the left and the
  picture at the right, even columns to 1024px and 5 to 7 from there. From
  640px the screens start below the principal's shoulders, so no frame covers
  her face; no frame covers a word of the page (the headline, the lead, the
  buttons, the price line or the slider's controls); and the
  "Fees collected" card shows on every screen at every width, clear of her
  face, the screen and every word. `heroEverywhere` holds it on every screen
  at 320, 360, 375, 414, 640, 768, 900, 1024, 1280 and 1920px.
- **On a phone (below 640px) every screen is a phone screen in the register's
  phone frame**, one size (`min(250px, 72%)` wide, the shape of a 390 x 844
  phone), at the left, and no screen has the browser frame; from 640px the
  desk keeps its frames. The screens start 38% of the column down, below the
  principal's shoulders, so her face is never under the phone, and the
  "Fees collected" card shows on every screen, to the left of her and above
  the phone, clear of her face and of every word on the screen. `heroOnAPhone` in `tests/ui/screens.test.js` holds all
  of it on every screen at 320, 375 and 414px.

- **The words say what the product does and promise no outcome we cannot
  show.** Kept as the owner gave them: the price (the first term free, then ₦1,500 per student, per term,
  no setup fee; changed from ₦2,500 on 26 October 2026), the call-back time (**two working days**) and the contact
  address (hello@classnode.co). The footer, the same on every page of the site
  (homepage, privacy notice, terms, the blog), is short and calm: the logo
  with one line under it (School management for Nigerian secondary schools.),
  two groups of links with small grey uppercase labels that run inline and
  wrap (Product: Features, Pricing, Blog, Book a demo; Sign in: Staff sign in,
  Parent sign in), a thin rule, and one bottom line: the legal line, the only
  place the company is named (© 2026 Classnode Edtech Limited · RC 9926572),
  and beside it Privacy, Terms and hello@classnode.co in small text. No
  address; the registered address waits for the lawyer. Every link is 44px
  tall by its own padding (32px from 900px). On a phone it is left-aligned and
  about 330px tall, with 16px between the line under the logo and the first
  label and 12px between the groups (`tests/ui/screens.test.js` holds it to
  340, 350 under 375px); from 900px the logo and the two groups share one row and
  the bottom line is a single line, about 150px.
  `website/tests/test_homepage.py` holds the page to that copy and to the
  writing rules: no en or em dash, no exclamation mark, no sentence starting
  "Imagine", none of the banned words, and **no question mark outside the six
  questions** (native `<details>`, each one ending in its question mark).
- **No invented proof.** No testimonial, school logo or customer count. A
  `<section class="proof" hidden>` is kept for real quotes and logos, each with
  the school's written permission, and is empty until then.
- **TODO notes** on the privacy notice and the terms are drawn only when `SHOW_LEGAL_TODOS` is on (off by
  default; on with `DJANGO_DEBUG=1` and in the legal tests). Every open one is listed in `docs/handover.md`.
  While `website.views.LEGAL_IN_DRAFT` is set, the two pages say so in one line at the top, are `noindex`
  and are not in the sitemap; `website/tests/test_legal.py` holds all three, and that no page the site serves
  has "TODO" in it.
- **The header is sticky.** It stays at the top while the page scrolls and
  takes its own 72px in the flow (`--head`), in the top band's colour, so the
  band runs on under it and it never covers the page: the hero's and a legal
  title's padding stop below it, and `scroll-padding-top` keeps a link to a
  section (`/#features`, a legal contents list) and the pinned report sheet
  clear of it. A hairline and a soft shadow appear once the page has scrolled
  (`is-scrolled`, set by the one inline script, outside the block a page
  overrides). On a phone the bar is the logo and the menu button, as ever;
  "Book a demo" is in the menu, a panel the width of the screen hung from the
  header. From 1024px the nav carries the button. `tests/ui/screens.test.js` (`siteHeader`)
  holds all of it at every width.
- **One Blue, with more of it** (`docs/design.md`): the top band (the header
  and the hero, or a legal page's title) is light, the 5% wash of One Blue
  (the owner's choice of three, 12 October 2026), with ink headings, One Blue
  for the headline's last words ("all in one place."), the eyebrow, the
  buttons and the product's frames, and a faint One Blue glow behind the
  screens, under the photo so it is never a halo. The photo sits in a frame:
  20px round, a 1px white edge, a soft blue shadow and the faintest blue on the
  whiteboard along its top edge, gone before her hair begins; nothing touches
  her face or skin;
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
  into `static/website/shots/`. Each screen's description names the school as
  a demo (the line under the slider that said so was taken out by the owner,
  12 October 2026). They were taken with the
  clock at Thursday 15 October 2026 (`SHOTS_NOW` in the script's header says
  how), so every screen names the day one way, "Thu 15 Oct", the register's
  date included (`dayText` in `static/register/states.js`, no longer ISO). The
  showcase's logins are a title and a surname ("Mr Oyelaran"), so each
  avatar's letters are the greeted name's: MO beside "Good morning, Mr
  Oyelaran", where "Mr Segun Oyelaran" drew MS. The desk's home still prints
  the day in full in its own header ("Thursday 15 October"). The school has one
  code, CFC: admission numbers `CFC/001` and the learner ID `CFC-2013-0001`.
  The term declares its 61 school days (`set_school_days`), so the report
  sheet's "Times school opened" is a number, never a dash. The home's
  attendance tile prints no change line when the day matches the week before
  it to a tenth of a point ("0 pts" read as a figure).
- **The floating cards carry the screens' own figures** (₦48.6m, 93.8% today,
  a ₦120,700 payment), never rounder ones; a test counts them. A card's figure
  counts up from 0 only once some of it is on screen; until then it shows its
  real figure, so none ever sits at 0.0%.
  Retaking the screens is a reason to check them: 93.8% was a Thursday's.
- **The report sheet** is the first benefit, in place of the small report
  card it replaced: a large Ogun State sheet beside "Report cards that add up
  by themselves", in HTML (a real table, read by its caption). It is Sunrise
  Demo Academy's (`seed_demo`, the development demo, not the showcase): Tolu
  Adeyemi, SUN/019, JSS 1B, first term 2026/2027, the school's three subjects
  and the class teacher's and principal's remarks every JSS 1B card carries.
  The line under its words says Sunrise is a demo school. **The marks are
  made-up demo figures** on the Ogun split (CA 30, exam 70), not Sunrise's
  database (Sunrise prints the Standard card). Each row adds up and the
  summary is the rows' sum (221 of 300, 73.67%); a test holds the sums. **No
  grade**: the Ogun sheet Classnode prints (`static/card/ogun.js`) has no
  grade column, so the drawing has none either. Its summary does print the
  class position when the school prints positions ("4th of 45"), so the
  drawing's summary carries one, "2nd of 10", stamped in. The words beside it
  say the sheet is the one the Ministry asks for: the printed sheet carries the
  ministry's name, and what OGSERA asks a school for is its own spreadsheet
  (`results/ogsera.py`), so the homepage no longer names OGSERA for the sheet.
- **The photos** are three the owner supplied, cut to their spaces as WebP
  under 60 KB each, with their sizes set: a principal at her desk (the hero), a
  bursar at a laptop (fees) and a teacher with a phone (the register). No photo
  shows a child's face. Their sources and licences are recorded below.
- **Drawings** are inline SVG: the Classnode mark grown into a network of
  nodes and lines behind the hero's picture (under 5 KB, inside the picture's
  column above the slider's controls, so never behind a word), a still copy
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
  - the report sheet fills in on its own scroll timeline: per subject the CA
    and the exam are written in, then the weighted average counts up to their
    sum on a lit pad, larger and in One Blue (a registered `--n`, drawn by a
    counter over the figure in the markup): the longest step, the moment the
    section is for; then the marks obtained, the percentage, the class
    position stamped in, and the two remarks. On a desk at least 900px wide and 920px tall (the sheet, with its Affective and
    Psychomotor block, is about 830px) the sheet is
    pinned while the page scrolls 160vh past it; elsewhere it fills as it rises
    up the screen. Every step ends on the still sheet (the stamp at -4deg), so
    under reduced motion, or in a browser without scroll timelines
    (`@supports (animation-timeline: view())`), it is drawn complete and not
    pinned;
  - the Affective and Psychomotor block under the marks is drawn complete and
    not scroll-written: the Ogun sheet's six lines for each, ticked in the
    column of a made-up 1 to 5 rating, with the sheet's key;
  - the cards' figures count up once as they come into view.
- **One script, inline**: closing the phone menu on every page, plus the
  slider (under 2 KB) and the counting figures (under 1 KB) on the homepage.
  No library and nothing from another host.
- **Weight**: a phone fetches about 360 KB uncompressed with every image
  counted at 2x, the deferred screens and the lazy photos too (under the
  400 KB budget a test holds), and less over the wire.

## The pricing page and "Coming soon"

`/pricing/` (`website.views.pricing`, `website/features.py`) shows the price, then
everything it includes in groups (results and report cards; registers, fees and
notices; staff and exams; the school online; safe and separate), then a separate
**Premium add-on** group (a custom domain for the school website, and sending
results and notices from the school's own email domain) priced "Contact us". No
mailboxes are promised.

Each feature was checked against `main` on 26 October 2026. Not on `main`, so
labelled "Coming soon": the school website (public pages render, but there is no
editor, so a school cannot yet publish one: `docs/school-sites.md` PR 4), the
three CBT items (CBT stops at exam PINs: `docs/cbt.md` steps 3 to 6), and both
premium items (custom domains and sender domains, PRs 10 and 11).

**One setting per label**, on by default, read on every request:
`COMING_SOON_SCHOOL_WEBSITE`, `COMING_SOON_CBT_SCHOOL_TESTS`,
`COMING_SOON_CBT_UTME_PRACTICE`, `COMING_SOON_CBT_WASSCE_PRACTICE`,
`COMING_SOON_CUSTOM_DOMAIN` and `COMING_SOON_SENDER_DOMAIN`. When a feature
ships, set its variable to `0` in `deploy/production.env` and deploy: the label
goes and nothing else changes. No code change.

## Search engines and shared links

The site is the only thing on the platform a search engine is asked to index.

- **Noindex everywhere else, by default.** `website/crawlers.py` adds
  `X-Robots-Tag: noindex, nofollow` to every response on every host but
  `SITE_HOST`: the portal (`app.`), its sign-in pages, `/platform/`, every
  school's host, demo schools and test schools alike, and a host nobody owns.
  `templates/design/head.html` writes the same meta tag unless the view sets
  `indexable`, which only `website.views.site_page` does; the 403 page carries
  it itself. `/healthz/` answers above all of this and marks itself. A school's
  own website (`docs/school-sites.md`) will be the one exception: on a school's
  host the header is left off only a response its view marks, on one of the
  website's paths (`schools.paths.PUBLIC_SITE`), and never on the portal. No
  view marks one yet.
- **robots.txt** is answered on every host by the same middleware: on the site
  it allows everything and names `/sitemap.xml`; on the portal it disallows
  everything but the icons below; on every other host it says the same, and
  first names each path a school's host never lets in (`schools.paths.NEVER_INDEXED`:
  `/sit/`, `/check/`, the sign-in pages and every portal page).
- **The icon beside a search result** (Google showed a grey globe before, 18
  October 2026) is the header's mark, white nodes on a One Blue rounded
  square, drawn by `scripts/favicons.py` into `webroot/`: `/favicon.ico` (16,
  32 and 48 inside), `/favicon.svg`, `/apple-touch-icon.png` (180, square to
  the edge for iOS to round), and `/icon-192.png` and `/icon-512.png` named in
  `/site.webmanifest`. WhiteNoise serves that directory at the root of every
  host (`WHITENOISE_ROOT`), above the tenant middleware, so each is a 200 with
  its image type on the site, the portal and every school, never a redirect;
  the addresses are fixed, not hashed. `templates/design/head.html` names them
  on every page.
- **Each page's own title and description** are `website.views.PAGES` (a blog
  post's are its own SEO title and description): titles 60 characters or
  fewer, so a result shows them whole, descriptions under 155. The homepage's
  is "Classnode: School software for Nigerian schools", the name first (the
  owner's, 18 October 2026; the one before, 68 characters, was cut off). The
  sitemap lists the same pages, and each names its own canonical address,
  `https://` and the bare domain with no query.
- **The price is written "The first term is free, then ₦1,500 per student, per
  term. No setup fee."**, with its comma, in the description, the share card's
  and the structured data's words (`website.views.PRICE`), as the page writes
  it. The structured data's `price` fields stay bare numbers (`0` for the first
  term, `1500` after it): schema.org asks for that, and a comma would read as a
  decimal point. Classnode's price is on the homepage (hero line and price
  card), the pricing page, the terms (`#price`), every page's meta and share
  descriptions that carry `PRICE`, the structured data, and the tests that hold
  them (`website/tests/test_pricing.py`). It is not any school's fee.
- **Structured data, on the homepage and each blog post only.** On a post it
  is an Article (`docs/blog.md`). On the homepage: Organization (Classnode Edtech
  Limited, its logo `https://classnode.co/icon-512.png`, `hello@classnode.co`,
  no address), SoftwareApplication (EducationalApplication, a free first term
  then ₦1,500 per student per term) and FAQPage. The FAQ on the page and in the data are drawn from one list,
  `website.views.FAQ`. No ratings and no reviews: there are none to stand
  behind.
- **The share card.** Open Graph and a large Twitter card on every page, with
  `static/website/share.png` (1200 x 630, One Blue, the logo and the
  headline), drawn by `scripts/share_image.html`.
- **Measured** with Lighthouse 12.8 mobile, 3 runs each against a local server
  with `DEBUG` off (12 October 2026): performance 99 on the homepage and 100 on
  the privacy notice and the terms, SEO 100 on all three.

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
  (question marks in the FAQ only), the one eyebrow and the left-aligned
  headlines, the headings with no forced breaks, the Ministry's line, the
  hidden proof section, the floating figures, the report sheet's sums, its
  stamped class position and no grade, its description and its scroll
  timeline, the form and its inbox, the phone's 400 KB budget, photos under
  60 KB, images sized, described and lazy below the hero, the one inline
  script and its sizes, motion only inside `no-preference`, and the contrast
  of every word on every blue.
- `website/tests/test_seo.py`: noindex in the header and the page on a school's
  host and the portal and not on the site, robots.txt on each, the sitemap,
  canonical addresses and the one-hop redirects, titles and descriptions, the
  price's comma, the icons on every host and in every page's head, the
  share card and its image, the structured data against the visible FAQ, one
  h1 with no skipped heading, every image described and every public page
  linked from every other.
- `schools/tests/test_seed_demo.py` `ShowcaseTests`: the showcase's figures,
  the ones the homepage prints.
- `tests/ui/screens.test.js`: the homepage, the privacy notice and the terms at 320, 360, 375, 390, 414, 768, 1024, 1280
  and 1920, photographed finished and held to the layout above; the sizes
  above (`the homepage's sizes`); and its motion
  (`the homepage's motion`) on a fake clock: the 5 seconds, the 600ms fade, the
  hover, keyboard, touch and Pause holds, nothing moving under reduced motion,
  only the floating cards, the network's dots and the dot grids looping,
  every figure counting to the screens' own, and the report sheet empty as it
  arrives, part filled halfway and complete at the end (desk and phone), and
  complete and unpinned under reduced motion.
