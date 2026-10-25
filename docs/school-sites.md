# School websites

A design note, nothing built. It plans a real public website for each school on the
school's own address: a page engine built from fixed sections, themes on top of
those sections, an admissions form that feeds the portal, custom domains, and
email sent as the school's own domain.

It starts with what `main` does today (checked read-only at `c2e4915`, 2026-10-24),
because several of the decisions below exist only because of a setting that is
already there. The visual design of the themes is **not** decided here. It has
its own section saying what a separate design round must settle.

The owner answered the note's open questions on 2026-10-24. The answers are
written into the sections they change, and §13 lists them in one place.

Two goals pull against each other: premium Nigerian schools want a site that
looks expensive, and parents open it on a mid-range Android phone over a slow
mobile network. Neither goal is allowed to give way. The engine must not cap
visual quality, and the speed budgets are tests, not hopes.

---

## 1. What main does today

### Tenants and hosts

| Fact | Where |
|---|---|
| A school is `schools.School` (`TenantMixin`), one Postgres schema each. Its address is a `schools.Domain` row (`DomainMixin`, no extra fields): `<slug>.classnode.co`, `is_primary=True`, made in the same transaction as the school by `schools.onboarding.create_school()`. | `schools/models.py`, `schools/onboarding.py` |
| `check_host()` only accepts **one label under `PLATFORM_DOMAIN`**, for two reasons: the session cookie spans `.classnode.co`, and the wildcard certificate covers one level and no deeper. The labels `app www api admin mail static portal public` are reserved. | `schools/onboarding.py` |
| The portal is the public schema's `Domain` row, `app.classnode.co` (`PORTAL_HOST`). It serves `urls_public.py`: the admin, both sign-in doors, invitations, `/platform/`, the blog editor `/write/`. | `settings.py`, `urls_public.py` |
| Classnode's own site, `classnode.co` (`SITE_HOST`), is **not** a `Domain` row. `PlatformTenantMiddleware.no_tenant_found()` sends it to `urls_site.py`. | `schools/middleware.py` |
| `is_primary` matters: after sign-in, `api._schools_of()` sends each person to their school's **primary** `Domain`. A custom domain must therefore never become the primary row (see §7). | `api.py` |
| `TenantMainMiddleware` returns 404 for any host with no `Domain` row. The settings comment calls that table "the real allowlist". | `settings.py` |

### Caddy and TLS

- One wildcard certificate for `classnode.co` and `*.classnode.co`, validated by DNS-01 through Cloudflare (decided 2026-09-23, partly so the list of schools never shows up in Certificate Transparency logs). Caddy 2.11.4 with `caddy-dns/cloudflare` v0.2.4, both pinned.
- Plain `http://` and `www.` go to `https://classnode.co` in one hop. `encode zstd gzip`. `reverse_proxy web:8000`, with **no `trusted_proxies`**: Caddy overwrites `X-Forwarded-For`, which is what makes `TRUSTED_PROXY_COUNT=1` safe.
- **No on-demand TLS and no block for any host outside `classnode.co`.** Today a custom domain cannot get a certificate.

### Django settings that a custom domain runs into

| Setting | Value today | What it means for a custom domain |
|---|---|---|
| `ALLOWED_HOSTS` | `.classnode.co` (derived from `PLATFORM_DOMAIN`) | `stmarys.edu.ng` gets **400 DisallowedHost** before the `Domain` table is even consulted. |
| `SESSION_COOKIE_DOMAIN`, `CSRF_COOKIE_DOMAIN` | `.classnode.co` | A browser rejects a `Set-Cookie` for `.classnode.co` sent from `stmarys.edu.ng`. On a custom domain there is no session and **no CSRF cookie**, so any normal Django POST form fails CSRF there. |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | on (off only with `DEBUG`) | — |
| `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER` | on behind Caddy (`TLS_TERMINATED_BY_PROXY=1`) | — |
| `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS` | 86400, **on** | Django sends this on every host. On a school's apex it would force HTTPS on **every subdomain the school owns** (an old results portal, a mail webmail). It must be narrowed per host (§7). |
| `CSRF_TRUSTED_ORIGINS` | from the environment only | — |
| `X_FRAME_OPTIONS` | `DENY` | — |
| `SECURE_REFERRER_POLICY` | `same-origin` | — |
| Content-Security-Policy | **none on any page** | The public site should be the first to get one (§10). |

### What the school host's root shows now

`schools.views.school_site` renders `schools/templates/schools/site.html`, drawn
by the server with no script and no outside request: the crest (a 128 px PNG
inlined as a `data:` URI by `results.look.for_site()`) or the school's initials,
the report-card colour as `--school` on an inline `style`, the name, the "about"
text, address, phone and contact email (`School.about/address/phone/contact_email`),
a **Check a result** button (`/check/`), a **Parent sign in** link to the portal,
and **Staff sign in** in the footer. The frame is in the 150 KB budget test
(`tests/test_budget.py`, `"/"` pinned at 20 queries).

**Every school host is `noindex` today.** `website/crawlers.py` adds
`X-Robots-Tag: noindex, nofollow` to every response not served on `SITE_HOST`,
`templates/design/head.html` adds the meta tag unless a view sets `indexable`,
and `/robots.txt` on a school host disallows everything except the icons.
WhiteNoise serves Classnode's own favicon at `/favicon.ico` on every host, before
the tenant is resolved, so a school's tab currently shows Classnode's mark.

### Public pages that exist

| Host | Public pages |
|---|---|
| `classnode.co` | `/`, which has the demo-request form, `/privacy/`, `/terms/`, `/blog/…`, `/sitemap.xml`, and nothing else |
| `app.classnode.co` | `/sign-in/`, `/staff-sign-in/`, `/invitations/<token>/`. `/` redirects to the staff door. All `noindex`. |
| `<slug>.classnode.co` | `/` (above) and `/check/`, the result checker, which needs no session. Everything else on the host is the signed-in portal. |

### The school host's path namespace

Everything a school's own host routes today (`urls.py`). The public site has to
share this namespace, so these are the names it **may not take**:

`api/  sw.js  sign-in/  staff-sign-in/  sign-out/  home/  start/  help/  setup/
teaching/  subject-teachers/  promotion/  roll/  staff/  notices/  register/
absences/  marking/  results/  broadsheet/  comments/  ogsera/  fees/  bank/
timetable/  cards/  check/`, plus `static/`, `healthz/`, `robots.txt` and the
icon files in front of the app, and `exam-slips/`, which open PR #298 adds.

Two of these are traps: **`/home/` is the staff dashboard** and **`/register/`
is the attendance register**. So the public "Home" page is `/`, and admissions
must not be called "register".

### The CBT `/sit/` path

**It is not reserved on main.** `docs/cbt.md` puts the exam door at `/sit/` on
the school's own host, with a cookie scoped to `/sit/` and its own small service
worker. That design is on draft PR #278 and has not merged. Open PR #298 (CBT
step 2) adds `/exam-slips/` and nothing at `/sit/`. Today `/sit/` is a 404 that
nothing protects. This note reserves it (§6, PR 1) so that no public page, news
slug or album slug can ever take it. *(Done in PR 1: `schools.paths.RESERVED`
holds `/sit/`, `/website/` and `/applicants/`, each a noindex 404 at the name
and everywhere under it until its work is built.)*

The existing offline worker (`/sw.js`, `sync/worker.js`) is registered with
scope `/` on every school host. It only intercepts navigations to `/marking/`
and `/register/` and requests for `/static/`, so public pages pass straight
through. The public site registers no worker of its own.

### Images and files

- **No file storage is configured.** There is no `MEDIA_ROOT`, and the default `FileSystemStorage` is not used. Every image and PDF is a Postgres `BinaryField`: the crest (`ReportCardSettings.crest`), a child's photo (`academics`), blog images (`blog.BlogImage`, `data` plus a half-width `small`), and released-card PDFs. `results/models.py` records that this is "a decision with a ceiling".
- Each upload is decoded and drawn again, never stored as sent (`results.look.open_picture`). The byte size is checked before opening, the pixel count is read from the header before decoding, EXIF orientation is applied, and the output is a fresh file with no metadata.
  - Crest: PNG/JPEG, at most 1 MB, at most 4096², drawn into a 256 px transparent PNG.
  - Blog image: PNG/JPEG/WebP, at most 10 MB, at most 40 MP, WebP at quality 80, at most 1600 px wide, plus a half-width copy for `srcset`. Served as `image/webp` with `Cache-Control: public, max-age=3600`, and only while its post is published. Keys are random 128-bit hex.
- Pillow is pinned at 13.0.0.
- Static files: WhiteNoise with a hashed, pre-compressed manifest. The fonts are Hanken Grotesk 400 and 700, about 12 KB each as woff2, and a 1.6 KB Noto Sans subset for Hausa's hooked letters, fetched only where one is used.

### Email

- One generic SMTP path. `messaging.smtp.SmtpProvider` (selected by `MESSAGING_EMAIL_PROVIDER`) and the staff-invitation `schools.delivery.EmailChannel` both read `EMAIL_HOST/PORT/HOST_USER/HOST_PASSWORD/USE_TLS`.
- **From is always `DEFAULT_FROM_EMAIL`** (`no-reply@classnode.co`). **Reply-To** is the school's `contact_email` (`messaging` D16).
- **Brevo is not named anywhere in the repository.** `deploy/env/secrets.env.example` lists the SMTP lines as commented "added later", and `docs/messaging.md` still has OPEN-5 ("which provider, under what contract") open. **The server, though, already sends through Brevo** (owner, 2026-10-24): the repository is generic SMTP, and the server's `secrets.env` points it at Brevo's relay. Sending **as the school's own domain** needs new work (§8).

### What the new forms can copy

`website.views.homepage`'s demo form already has a honeypot field (`website`)
whose success is faked, and a per-address hourly limit counted from the saved rows
themselves (`DEMO_REQUESTS_PER_HOUR`), so the limit holds across worker processes.
`accounts.throttling.client_address()` returns the one address Caddy vouches for.
The site's admissions form copies both.

### Roles

`accounts.Role` has `PRINCIPAL` and `ADMIN` (labelled "Administrator"), and
there is no proprietor role. Today the crest and colour may be set by either
(`SETUP_ROLES = {principal, admin}`). The site engine narrows authority to the
principal, with an opt-in for the administrator (§2.4).

---

## 2. The homepage engine

### 2.1 Pages

Six fixed pages, and custom pages a school makes itself (§2.1.1, decided 25
October 2026). The school switches any fixed page on or off except Home, which
is the root and always answers. On every page the school adds, removes and
reorders sections. Fixed pages have fixed addresses, and custom pages live under
one prefix, so a school can never take a path the platform needs.

| Page | Path | Notes |
|---|---|---|
| Home | `/` | Always on: the root must answer. Its sections are the school's to choose. |
| About | `/about/` | |
| Admissions | `/admissions/`, `/admissions/enquire/`, `/admissions/apply/` | §5 |
| News | `/news/`, `/news/<slug>/` | Slug made by the server from the title, `[a-z0-9-]`, unique within the school. |
| Gallery | `/gallery/`, `/gallery/<album-slug>/` | |
| Contact | `/contact/` | |

Also served: `/sitemap.xml`, the school's own `/robots.txt` (§6), and image
renditions under `/media/` (§9).

#### 2.1.1 Custom pages

A school can add pages of its own, such as Boarding, Sports, Clubs, Academics and Alumni.

- **Built from the same safe sections.** A custom page is a title and an ordered list of sections, drawn from the fixed kinds a custom page may hold: hero, text, facts, gallery, the principal's message and the admissions panel. There is no free-form HTML, as everywhere else (§2.2).
- **At most 12 per school, held by Postgres.** Each custom page takes a slot numbered 1 to 12, unique within the school, so a thirteenth cannot be written by any path, however it is written.
- **At `/pages/<slug>/`.** All custom pages share one prefix, so no custom page can clash with a fixed page, a portal path or `/sit/`. The slug is made from the title when the page is created, uses `[a-z0-9-]`, is at most 40 characters and is unique within the school. Renaming the page later does not move its address.
- **Draft, preview and publish exactly like the fixed pages.** It goes into the revision snapshot, and the principal alone publishes it.
- **A menu that updates itself.** The menu is the switched-on pages, fixed and custom, in one order the school sets (`menu_position`), with Home always first. On a phone, links after the fifth go under a "More" menu (a `<details>`, no script). The footer lists them all, and the sitemap includes every switched-on custom page.

### 2.2 Sections

A page is an ordered list of sections. Each section's **kind** comes from a fixed
list. Each section's **data** is a structured record validated against that
kind's schema. No HTML is ever stored: text is plain text, with paragraph
breaks.

| Kind | Data (all text plain) | Allowed on |
|---|---|---|
| `hero` | heading, sub-heading, up to 2 buttons (label + an allowed link), media: one image with a focal point, or one video with a poster (§9) | every page, at most one, always first |
| `crest_motto` | uses the school's crest, plus the motto (up to 120 characters, an optional language tag, an optional translation) and the year founded | Home, About |
| `principal_message` | portrait image, name, title ("Rev. Sr.", "Dr (Mrs)"), message (up to 4,000 characters), signature line | Home, About |
| `facts` | 2–6 items, each a figure plus a label ("98%", "WAEC credit pass in 5 subjects, 2025"), and an optional source note | Home, About, Admissions |
| `news` | count to show (3–6). Draws the latest published posts and holds no copy of them. | Home, News |
| `gallery` | an album and a count, or up to 12 chosen photos | Home, Gallery, About |
| `admissions_cta` | heading, text, button label, session ("2027/2028"), open/closed state, closing date | every page |
| `contact_map` | taken from `School.address/phone/contact_email`, plus WhatsApp number, office hours, map location (latitude/longitude or a maps link) | Contact, Home |
| `text` | heading and body (up to 6,000 characters). The one free-text block, still plain text. | About, Admissions |
| `footer` | site-wide, not per page: links to enabled pages, social links (fixed list of networks, URL checked against that network's host), address line, "Report this page" (§10.3) | every page, always last |

Each kind declares a small set of **layout variant names** that are part of the
engine's vocabulary, not of any theme. For example, `hero` has `image`, `video`,
`split` and `plain`, and `gallery` has `grid` and `strip`. A theme styles every
variant; it never adds data. This is what lets a school switch theme without
losing anything (§3.2).

Validation is server-side, per kind. Limits on length and count are what keep a
theme able to draw every school's content well. A link field accepts an internal
path from the fixed page list, `https:`, `tel:`, `mailto:`, or a `wa.me` link,
and nothing else (§10.2).

### 2.3 Draft, preview, publish

Modelled on the released report card: **the published site is an artefact
written at publish time, not the current state of a table.**

- **Draft.** One editable draft per school: settings, pages, sections, the theme and its options. Saving writes the draft only. Two editors at once: each part saved (the settings row, a page, a section) carries a version number, a save names the version it was based on, and a stale one is refused with a request to reload. No silent overwrite. *(Built in PR 2 as integers rather than `updated_at`, so two saves in the same instant cannot both look current.)*
- **Preview.** `/website/preview/<page>` on the school's classnode host, for whoever may edit. It renders the draft through exactly the same templates as the live site, under a fixed "Preview: not published" bar. It is `noindex`, `Cache-Control: no-store`, and never cached server-side. It can preview the draft **in another theme** without saving the switch.
- **Publish.** One button, the principal's alone (§2.4). It writes an immutable `SiteRevision` row: a JSON snapshot of the whole draft plus the theme, with `published_by`, `published_at`, and a short optional note ("Admissions open for 2027/28"). The public site reads only the latest revision. That is one indexed row, which is also the cache key (§4.4).
- **Log.** Revisions are never deleted, so the publish log is the revision table: who, when, the note, and a diff summary (sections added, removed or changed). The settings page shows the last 20. **Roll back** republishes an older snapshot as a new revision, logged as a rollback by whoever did it. The draft is left as it is: the fix is made there and published in its turn. A draft nobody has touched yet, the six empty pages every school starts with, is nothing to publish.
- **News posts and gallery albums** publish one item at a time (`NewsPost`, `Album`, each with draft/published state and `published_by`/`published_at`), because a school posts news weekly and should not have to republish the whole site to do it. Every publish or unpublish of an item writes a `SitePublishEvent` row (who, when, what, which item), so the single log the principal reads covers both kinds.
- Images referenced by any revision are `PROTECT`ed: an old revision can always be rolled back to with its pictures.

### 2.4 Who may do what

| Act | Principal | Administrator, not delegated | Administrator, delegated | Platform staff |
|---|---|---|---|---|
| Edit draft, preview, mark a draft "Ready for the principal" | yes | no | yes | no |
| Publish, roll back, publish news and albums | yes | no | **no** | no |
| Switch theme, change theme options | yes | no | no | no |
| Turn delegation on or off | yes | no | no | no |
| Connect a custom domain or sender domain | yes | no | no | no |
| Read the publish log | yes | yes | yes | yes, on the handover page |
| Suspend the public site (takedown, §10.3) | no | no | no | yes, logged |

- **Only the principal publishes** (decided 2026-10-24: large schools guard their brand). Delegation lets the administrator edit drafts of pages, news and albums, never publish them. When the administrator marks a draft "Ready for the principal", the principal is emailed a link to its preview. Publishing still takes the principal's own click.
- **Delegation** is a per-school setting that only the principal can change, and every change is logged (`SiteDelegationEvent`: who, when, on/off). Turning it off takes effect on the administrator's next request. It is checked at every write through `roles_at()`, which already scopes to `ACCESS_STATUSES`, never cached in the session.
- A school with no principal membership can edit nothing. The principal must be invited first. This is deliberate: the site speaks for the school.
- Teachers, bursars, the vice principal (academic), parents and students have no access.

---

## 3. Themes

### 3.1 What a theme is

A theme is a directory in the repository (`sites/themes/<key>/`). Adding one
needs **no migration and no engine change**. It contains:

- a manifest: key, display name, which variants it supports for each section kind (it must support all of them, see the contract below), the header styles it offers, its font files, and the `sizes` attribute each variant's images use (§4.2);
- one template per section kind, with a shared base template for `<head>`, the header and the footer;
- one stylesheet (at most 30 KB uncompressed) and at most two woff2 font files (§4.1);
- an optional script, at most 8 KB, for motion only, which the page must not need in order to render (§4.3).

The school's choices live in its draft, not in the theme:

| Option | Source |
|---|---|
| Theme key | the school picks one from the list |
| Colour roles: primary, secondary, accent, surface, text | taken from the crest (below) or entered by hand, each checked for contrast |
| Header style | one of the theme's offered styles: for example a solid bar, transparent over the hero, or crest centred |
| Font pairing | one of the theme's pairings, if it offers more than one |
| Per-section variant | one of the variant names |

**Colours from the crest.** When the crest is uploaded, the server reduces it to
5–6 dominant colours (Pillow `quantize`) and proposes a mapping onto the roles.
The principal accepts it or changes it. Every role pairing a theme uses (text on
surface, text on primary, button label on button) is checked against WCAG AA:
4.5:1 for text, 3:1 for large text and UI edges. A failing colour is darkened or
lightened to the nearest shade that passes, and the screen shows that it was
adjusted. The report-card colour (`ReportCardSettings.colour`, which already
passes 4.5:1 on white) is the default primary.

### 3.2 Switching theme without losing content

Content lives in sections whose data has no theme in it. Switching changes the
draft's theme key only, so preview in the new theme, then publish. **Theme
options are stored per theme key**, so going back to the old theme brings its
header style and colour tweaks back. A variant name the new theme styles
differently still renders, because every theme must render every variant.

### 3.3 The theme contract, as tests

Every theme directory found on disk is run through the same tests. That is what
makes the fourth to tenth themes cheap to add:

1. Every section kind × every variant renders with three fixture schools:
   - "full": every section, long text, 40 photos;
   - "sparse": no photos, no principal portrait, a one-line about;
   - "long": the longest names and mottos in §11.2.
2. The frame budget, image `sizes`, query count and LCP budgets in §4 hold.
3. The screens job checks at 320, 360, 768 and 1280 px plus 200% text: no sideways scroll, targets at least 44 px, contrast passes (§11).
4. Templates contain no `|safe`, no `mark_safe`, no `{% autoescape off %}`, no inline `<script>`, and no reference to another host (§10.2).
5. The fonts cover the glyph list in §11.2.

**Start with one designed theme, with strong options** (decided 25 October
2026, in place of three themes): colours taken from the crest, a choice of
header styles, and a choice of font pairings, so two schools on the same theme
still look clearly their own. The engine stays ready for more: a theme is a
directory and an entry in `schoolsite.themes.THEMES`, with no migration, and
every test above runs on each one. Ten is a ceiling set by CI time and design
review, not by the engine. Each extra theme adds its screenshots and LCP runs to
the screens job, about 3 fixtures × 6 pages × 4 widths.

### 3.4 Visual design: to be decided in a separate design round

This note fixes the engine. It does **not** decide how any theme looks. The
design round must settle:

1. **The designed theme's character, and the reach of its options**: name, mood and two or three reference sites. Then how far its colours, header styles and font pairings may move it, so that two schools on it look clearly their own. One theme for now (decided 25 October 2026).
2. **Type**: for each font pairing the theme offers, a display face and a text face, licensed for self-hosting (OFL or bought outright, with a licence that allows serving to the public on many domains), covering the glyph list in §11.2, subset to the budget in §4.1.
3. **How crest colours map onto the theme's colour roles**, including what happens with a one-colour crest, a crest that is mostly gold or yellow (which fails contrast as text), and a crest with no usable colour.
4. **Header styles** (at least three): how the Sign in button looks and sits, the mobile menu pattern, and the behaviour over a hero image.
5. **Hero treatments**: image, video, split and plain; the scrim rule that keeps text readable over any photograph (§11.1); the crop or focal-point behaviour from 320 to 1920 px.
6. **Every section's look in every variant**, including empty and sparse states, such as a school with no photos at all.
7. **Gallery and lightbox**: grid rhythm, captions, what a tap does on a phone.
8. **The motion language**: what moves, durations and easing, what `prefers-reduced-motion` turns off, all within the limits in §4.3.
9. **The principal's message**: portrait crop, how long text reads, signature.
10. **Photography guidance for schools**: which shots, orientation, light, and how to set a focal point. A premium look depends more on the photos than on the theme.
11. **Mockups of the theme in at least three different option settings, at 320, 360, 768 and 1280 px, and at 200% text**, for two schools: one with professional photos and a short name, one with phone photos and a very long name. Each measured against the §4 budgets before it is approved.

---

## 4. Speed

**Profile used for every budget.** Lighthouse's mobile "Slow 4G":
- 150 ms RTT, 1.6 Mbps down, 750 kbps up;
- 4× CPU slowdown, a mid-range Android.

Added to that is a **stress profile** for poor Nigerian coverage: 400 kbps down, 400 ms RTT.

The VPS is outside Nigeria (`docs/deployment.md`: Contabo or similar), so real
RTT from Lagos is often 120–200 ms before the mobile network adds its own.
Every round trip counts. The rules below are about removing round trips as much
as removing bytes.

### 4.1 Budgets

| Budget | Limit | Enforced by |
|---|---|---|
| LCP, Slow 4G | **≤ 2.5 s**, target 2.0 s | screens job (below) |
| LCP, stress profile | ≤ 4.0 s; first text drawn ≤ 2.0 s | screens job |
| CLS | ≤ 0.05 | screens job |
| INP / total blocking time | ≤ 200 ms / ≤ 150 ms | screens job |
| Frame (HTML, CSS, fonts, any script, before first paint) | ≤ 150 KB **uncompressed** (the existing `test_budget.py` rule) and ≤ 90 KB compressed | `test_budget.py` |
| Fonts | ≤ 2 woff2 files, ≤ 35 KB each, subset; `font-display: swap` with a metric-matched fallback (`size-adjust`) so swapping fonts moves nothing | theme contract |
| Script | none needed to render; any motion script ≤ 8 KB, deferred, a module from `static/` | theme contract; `test_budget.py` "no framework, no CDN" |
| Hero image (the LCP element) | ≤ 120 KB at 828 px wide (phone); ≤ 250 KB at 1920 px | rendition test |
| Home page, phone, before scrolling | ≤ 400 KB total | screens job |
| Home page, phone, scrolled to the end | ≤ 1.2 MB, video excluded | screens job |
| Gallery thumbnail | ≤ 25 KB at 400 px; lightbox image ≤ 200 KB at 1600 px | rendition test |
| Gallery page, before scrolling | ≤ 600 KB | screens job |
| Video | never part of the first load (§9.2) | screens job |
| Server time | cached page ≤ 200 ms p95; uncached ≤ 600 ms; queries per public page pinned and equal at two schools | `test_budget.py` pattern |

**How LCP is measured in CI with no new dependency.** The screens job already
runs Playwright with Chromium. It adds Chrome DevTools Protocol network and CPU
throttling, and reads LCP, CLS and transferred bytes from `PerformanceObserver`
and resource timing. It runs against the fixture schools, for every theme. Each
number is the median of three runs, so noise does not flip the gate.

### 4.2 Images: responsive, modern formats

- Renditions are made once at upload in the Celery worker. Widths are 320, 480, 640, 828, 1080, 1440 and 1920 px, never wider than the source. Each width is made in **AVIF and WebP**, plus a **JPEG** fallback for the old Android browsers and Opera Mini that are common here. Pillow 13 writes all three. PR 5's first test confirms that the pinned wheel's AVIF encoder works on the server image.
- Every `<img>` is a `<picture>` with `srcset` per format and a `sizes` value from the theme manifest for that variant. Width and height are always set, so nothing moves.
- The hero image is preloaded (`<link rel="preload" as="image" imagesrcset imagesizes fetchpriority="high">`) and never lazy. Everything below the first screen is `loading="lazy" decoding="async"`.
- No blurred base64 placeholders, which cost bytes in the HTML. Each image gets its dominant colour, computed at upload, as the background behind it.
- The crest is resized and served as an image URL with a long cache, not inlined as base64 on every page as now. It also becomes the school's favicon via `<link rel="icon">`, which takes precedence over WhiteNoise's `/favicon.ico`.

### 4.3 Beauty within the budget

Nothing here is a limit on what a theme may look like, only on how it gets there:

- **Full-bleed hero images and video.** Yes: the image is the LCP element, preloaded and sized. Video arrives after the page has loaded (§9.2).
- **High-quality galleries.** Yes: renditions up to 1920 px, AVIF first, at most 12 thumbnails before the first scroll, the rest lazy.
- **Custom fonts.** Yes: two families, subset and self-hosted. A third weight or a variable font is allowed if it still fits 2 × 35 KB.
- **Smooth motion.** CSS only, by default: transitions, `@keyframes`, scroll-driven animations where the browser supports them, and otherwise an `IntersectionObserver` script within the 8 KB. Only `transform` and `opacity` are animated, nothing that triggers layout. Everything stops under `prefers-reduced-motion: reduce`. No animation libraries and no scroll hijacking.
- **No third-party script on page load**: no analytics tag, no chat widget, no Google Maps, no YouTube player, no font CDN. Maps and outside videos load only on tap (§9.3).

### 4.4 Caching

- **HTML.** A published page is rendered once per `(schema, revision id, host, path)` and kept in Redis. A new publish is a new key, so there is nothing to invalidate. Response headers: `Cache-Control: public, max-age=60, stale-while-revalidate=600`, plus `ETag`. **Public responses set no cookie and do not read the session.** That needs care: `SchoolAccessMiddleware` touches `request.user` on school hosts, which adds `Vary: Cookie`. PR 3 measures this and lets public site routes through without reading the session.
- **Images.** URLs carry a content hash, so they are served `public, max-age=31536000, immutable`.
- **Static files.** Already hashed and pre-compressed by WhiteNoise. Caddy keeps `encode zstd gzip`.
- **No CDN at launch** (decided 2026-10-24). This matches the "no CDN" rule in `test_budget.py`. Cloudflare's proxy in front of `*.classnode.co` would put a cache in Lagos and remove most of the RTT problem. But it changes the `trusted_proxies` reasoning in the Caddyfile, and it complicates certificates for custom domains. **The question is reopened at the load test after CBT**, with that test's numbers in hand.

---

## 5. Admissions

### 5.1 Forms

Two forms on the public site, both drawn by the server, both working without
script and in Opera Mini:

- **Enquiry** (`/admissions/enquire/`): parent or guardian name, phone (required), email (optional), class sought (from the school's own class levels, JSS 1 to SSS 3 or whatever it has set up), session, preferred contact time, message (up to 1,000 characters).
- **Application** (`/admissions/apply/`): everything in the enquiry, plus the child's full name, date of birth, current school, last class completed, day or boarding (if the school offers both), and the parent's address.
- **Not collected in v1**: photos of the child, documents (birth certificate, past results), medical, religious or ethnic information, NIN. This is data minimisation: each of these can be asked for at interview, on paper, by the school.
- **Later, not in v1** (decided 2026-10-24):
  - **Document uploads** (birth certificate, last result) come in a later PR, through the same decode-and-redraw path as photos (§9.1). They are kept only as long as the application's retention period, and the consent wording gains a line for them.
  - **An application fee** through Paystack comes only after Paystack verification, when the platform can take live payments (Paystack is in test mode only today, `docs/paystack.md`).

The school can turn each form on or off. While admissions are closed, the forms
show the closing message and accept nothing.

### 5.2 Where it lands

- `admissions.Applicant` lives in the school's own schema. Fields:
  - kind (enquiry or application) and the form fields;
  - `consent_version` and `consent_at`;
  - `submitted_host`, the submitting address (for the rate limit), `created_at`;
  - status: new, contacted, invited to the entrance exam, offered, admitted, declined, withdrawn.
- Every status change is an `ApplicantEvent` row (who, when, from, to, note).
- **The portal page is `/applicants/`** on the school's classnode host, for the principal and the administrator. There is no admissions-officer role for now (decided 2026-10-24); it is added if schools ask for it. It shows a list filtered by session, class and status, a detail view, and status changes. A CSV export is logged as an event with the row count.
- **Notification**: an email to the school's `contact_email` by default, or to a separate admissions address if the school sets one on the site settings (decided 2026-10-24). It is sent after commit, and **batched: at most one email per 15 minutes per school**, listing what came in. A flood of submissions never becomes a flood of email.
- **No automatic reply to the address typed into the form.** Otherwise the form could be used to send our mail to anyone. The person sees an on-screen reference number ("ADM-2027-0042") and the school's phone number.
- **Retention**: applicants not admitted are deleted a fixed time after the session starts (the lawyer sets the period; the proposal is 12 months), by a nightly cron job beside the others in `deploy/cron/classnode`. "Admitted" does not create a student in v1. It only marks the row; turning an applicant into an enrolment is a later PR.

### 5.3 Consent wording (draft, on the lawyer list)

Shown above the submit button, with a checkbox that is **not** ticked by default
and is required:

> I am this child's parent or legal guardian. I agree that **{School name}** may
> use the information on this form to consider this application and to contact
> me about it. The school keeps it for no longer than {period} if the child is not
> admitted, and does not share it except with the people who handle admissions.
> Classnode stores it for the school. See the school's privacy notice: {link}.

- The text is versioned, and the version is stored on each row.
- The privacy notice is the school's. Classnode hosts a template the school fills in and publishes as a `text` section, and the form will not switch on until it exists.
- The legal basis and wording are for the lawyer, under the Nigeria Data Protection Act 2023 and the NDPC's GAID 2025 provisions on children's data. The draft follows the `SHOW_LEGAL_TODOS` pattern: TODO notes are visible in development and hidden from the public.

### 5.4 Spam and rate limits

No third-party captcha at launch: no outside script, and no extra page weight on a slow phone.

1. **Honeypot** field, as on the demo form. Success is faked, so a script learns nothing.
2. **Signed form token** (`django.core.signing`): bound to the host and the form, issued when the page is rendered. A submission less than 3 seconds or more than 2 hours after issue is refused. This also replaces CSRF on these two forms (§7.4).
3. **Origin check**: the `Origin` header, when present, must equal the host the form was served from.
4. **Per-address limits**, counted from saved rows: at most 5 per hour per address per school, and at most 200 per day per school from all addresses together. Past either limit the page says "Too many submissions; please call {phone}" with a 429.
5. **Duplicates**: the same phone number and child name within 24 hours updates the earlier row instead of adding a new one.
6. **Field limits**: lengths are capped, URLs in free text are not allowed, and nothing is rendered as a link in the portal.
7. If abuse still gets through, Cloudflare Turnstile (privacy-respecting, light) is the fallback, behind a per-school switch, loaded only on the two form pages. That is a decision for then, not now.

---

## 6. Sign in, the root, and indexing

- **The public site lives at the root of the school's host.** `school_site` is replaced by the engine's Home page. A school that has never published gets today's page, kept as the engine's "not yet published" view, so no school's root goes blank on the day this ships.
- **A clear Sign in button** in every theme's header, on every page. It opens a two-item menu built with `<details>`, so no script is needed:
  - **Parent or guardian** links to `https://app.classnode.co/sign-in/`;
  - **Staff** links to `https://app.classnode.co/staff-sign-in/`.
- **Check a result** stays as a header or hero button on the classnode host. On a custom domain it links to `https://<slug>.classnode.co/check/` (§7.4).
- `/sit/` is not linked from the site. Students reach it from the address on their exam slip. Whether to link it is left to the CBT work.
- **Path reservation (PR 1).** A single list of every path the school host routes that is not a public-site page, including `sit/`, `exam-slips/`, `website/` and `applicants/`. A test fails if any `urls.py` route is neither a public page nor on the list, and the slug makers for news and albums refuse anything that clashes with it. News slugs live under `/news/` and albums under `/gallery/`, so clashes are impossible by construction; the test is the guard against future routes.

**Indexing stays default-deny**, with one allowlist:

| Path on a school host | Indexed? | How |
|---|---|---|
| The published public pages and `/media/…` | **yes** | `CrawlerMiddleware` skips `X-Robots-Tag` only for responses from the site engine's public views, not by path prefix. The engine sets `indexable` for `head.html`. |
| `/website/preview/…` | no | `noindex` header and meta, `no-store` |
| `/sit/…`, `/check/`, `/applicants/` and every portal page | no | as today: header and meta |
| `/robots.txt` | — | allows the public pages, disallows everything else by name (`/sit/`, `/check/`, `/api/`, …), and points to `/sitemap.xml` |

- When a custom domain is active, the public pages on `<slug>.classnode.co` answer with a **301 to the custom domain**, so only one copy is ever indexed. Every page carries `<link rel="canonical">` with the canonical host.
- Each page gets a title, a description and Open Graph tags (the hero as `og:image`, 1200 × 630), and Home gets `EducationalOrganization` JSON-LD built from the school's details, escaped the way `website.views._json_ld` already escapes.
- The site and its forms set **no cookies**, so there is no cookie banner.

---

## 7. Custom domains

### 7.1 What the school does

**A premium add-on** (decided 2026-10-24). The website on the school's classnode
address is included in every plan. A custom domain, and sending email as the
school's own domain (§8), are a paid add-on. Billing is not built. Platform staff
switch the add-on on for a school on the handover page (`School.site_premium`,
public schema, logged with who and when). Without it, `/website/domain/` and
`/website/email/` explain the add-on and accept nothing. The services refuse too,
not just the pages. If the add-on is switched off for a school that has a
domain, the domain moves to **lapsed** (§7.2) and mail falls back to the
platform `From`.

The principal enters the domain (say `stmarys.edu.ng`) on `/website/domain/`. The
page shows exactly three records to add, with copy buttons:

| Record | Name | Value | Why |
|---|---|---|---|
| TXT | `_classnode.stmarys.edu.ng` | `classnode-verify=<random 32 hex>` | proves ownership; the token is new for every claim |
| CNAME | `www.stmarys.edu.ng` | `sites.classnode.co` | routing; `sites.classnode.co` is ours and points at the VPS |
| A (and AAAA if the VPS has IPv6) | `stmarys.edu.ng` (apex) | the VPS address | an apex cannot be a CNAME; providers that support ALIAS/ANAME to `sites.classnode.co` should use that instead |

**`www` is the canonical host. The apex only redirects to it** (decided 2026-10-24). The reason: a
CNAME follows us if the VPS address ever changes, while an apex A record is a
number every school would have to change by hand. Schools whose DNS provider
supports ALIAS can make both follow us.

Many `.edu.ng` and `.com.ng` domains are run by a web agency, not the school. The
page has a "send these to whoever manages your domain" button: a plain-text block
the principal can forward.

### 7.2 Verification and its states

`schools.CustomDomain` is in the **public schema**, because the ask endpoint and
the host router must find it before any tenant is chosen. Fields:
- `school` (FK) and `hostname`, which is unique across the platform;
- `token`, `status`, `created_by`, `verified_at`, `last_checked_at`, `failing_since`, and an event log.

```
pending ──(TXT and routing both seen)──► verified ──(TLS answered)──► active
   │                                       │                            │
   └── 14 days unverified ──► expired      └────(a check fails)─────────┴──► failing ──(7 days)──► lapsed
                                                                              │
                                                                              └─(check passes)─► active
```

- A check is a DNS lookup made through two public resolvers, for example 1.1.1.1 and 8.8.8.8, never the VPS's own. It passes when the TXT token matches and `www` (and the apex, if claimed) resolves to us.
- Checks run every 10 minutes while a domain is `pending`, then daily from the server's cron (`manage.py check_custom_domains`). There is no Celery beat, following `docs/background.md`.
- On **verified**, the app makes one HTTPS request to the domain. That triggers Caddy's certificate issuance, so the first parent is not the one who waits for it. When it answers, the status becomes **active**:
  - a non-primary `Domain` row is created (`is_primary` stays on the classnode host, because `_schools_of()` sends signed-in people to the primary row and a custom domain has no session, §7.4);
  - the classnode public pages begin to 301 to it.
- **What happens when verification lapses:**
  - **failing**: the domain keeps working for a 7-day grace period. The principal is emailed on days 1, 3 and 6.
  - **lapsed**: the ask endpoint refuses, so Caddy will not renew. The `Domain` row is removed, so the host returns 404. The 301s from the classnode host stop, and the site is served at `<slug>.classnode.co` again. The principal is told.
  - Reconnecting needs a **new token**.
- **Takeover protection:**
  - A hostname is unique across the platform.
  - A claim needs that claim's own token, so a school that left the platform with its CNAME still pointing at us cannot have its domain claimed by another school.
  - A domain pointed at our address without a verified claim never gets a certificate.

### 7.3 Caddy: on-demand TLS, approving only verified domains

Added to the Caddyfile (illustration, not the final text):

```
{
	email {$ACME_EMAIL}
	on_demand_tls {
		ask http://web:8000/_caddy/ask
	}
}

# Everything that is not classnode.co or *.classnode.co: custom domains only.
https:// {
	tls {
		on_demand
	}
	@internal path /_caddy/*
	respond @internal 404
	encode zstd gzip
	reverse_proxy web:8000
}
```

- `/_caddy/ask?domain=<host>` is answered by a middleware ahead of the tenant middleware, the same pattern as `schools.health`, and **only over the internal compose network**. The public blocks, the existing ones included, return 404 for `/_caddy/*`, so the internet cannot ask it anything.
- It answers 200 only when `domain` is an exact, lower-cased match of a `CustomDomain` that is `verified`, `active` or `failing`, or the apex or `www` partner of one. Anything under `classnode.co` gets 403 (those use the wildcard). Everything else gets 403.
- It costs one indexed query.
- The more specific `classnode.co, *.classnode.co` block keeps the wildcard certificate. Custom domains get their own per-domain certificates, which do appear in Certificate Transparency logs. That is fine: each school published its own domain.
- **Let's Encrypt limits.** The limits on failed validations per hostname and new orders per account are the reason the ask endpoint must refuse unverified names. Without it, any domain pointed at our address could burn our account's quota.

### 7.4 What Django must change for a custom host

- **`ALLOWED_HOSTS`**: set it to `*` on production again, since the `Domain` table is already the allowlist (the settings comment says so), and add a host-validation middleware that 404s anything matching neither a `Domain` row nor `SITE_HOST`, so the defence-in-depth argument is kept. The alternative is to put every verified domain in the setting at start-up, which goes stale.
- **A custom host serves the public site only.** The host router marks a request that arrived on a custom `Domain` row, and routes it to a public-only URLconf: the site pages, `/media/`, `/robots.txt` and `/sitemap.xml`. Any other path (`/home/`, `/check/`, `/sit/`, `/cards/`, …) answers with a **302 to the same path on `<slug>.classnode.co`**, where the cookies work.
- **No session or CSRF cookie** can exist there. The admissions forms use the signed token in §5.4 instead of CSRF, on every host, which is sound because they authenticate nobody and write only an anonymous applicant row. Nothing else on a custom host accepts POST.
- **HSTS per host**: on a custom host, `max-age` is one day at first and **no `includeSubDomains`** (a school's other subdomains are not ours to force). It never goes to preload.
- `<link rel="canonical">`, the sitemap and Open Graph URLs use the canonical host. `www` and the apex redirect to it (301) at Django, because Caddy cannot know which one the school chose.

### 7.5 The single VPS

- **One machine** serves every school's site, every portal, the result checker and CBT. An admissions-season spike, a viral post or a flood on one school's site slows teachers marking at every school. Mitigations: the HTML cache (§4.4), immutable image caching, the form limits, and video kept off the first load. Later, if needed, a separate gunicorn pool for public pages.
- **The VPS address is in schools' DNS.** Apex A records break if the address changes, and so do `www` records if `sites.classnode.co` is not moved in the same minute. Use a reserved or floating IP if the provider offers one, keep `sites.classnode.co` at a short TTL, and write the address-change runbook before the first custom domain.
- **Caddy's certificates are on the `caddy-data` volume.** If it is lost, every custom domain reissues at once, and past a few hundred domains that hits the per-account order limit. Back `caddy-data` up beside Postgres (`deploy/postgres/backup.sh`'s B2 path).
- **Bandwidth.** Photos and video are the first thing a traffic spike multiplies. Check the provider's transfer allowance against the §4 budgets × expected visits before launch.
- **No redundancy.** A VPS outage takes every school's public face down with its portal, which is more visible than a portal outage alone. This is accepted for the pilot and noted for the hosting decision.

---

## 8. Email as the school's domain, through Brevo

### 8.1 Sending

- **Platform:** one Brevo account, used through its SMTP relay with the existing `EMAIL_*` settings (`smtp-relay.brevo.com`, port 587, TLS, SMTP key in `secrets.env`). Brevo's API is used only to register and check sender domains. Brevo is confirmed as the email provider (owner, 2026-10-24, already live on the server), which closes the email half of OPEN-5.
- **Per message, a `From` chosen per school.** `Outbound` gains a `from_address`, and `SmtpProvider` stops reading `DEFAULT_FROM_EMAIL` directly:
  - the school has a **verified** sender domain: `"St Mary's College" <results@stmarys.edu.ng>`, with Reply-To the school's `contact_email` as today;
  - otherwise: `"St Mary's College via Classnode" <no-reply@classnode.co>`, as today.
- Every send re-reads the domain's status, which is one column on a row it already loads. A domain that has stopped verifying falls back to the platform `From` automatically. Mail never stops; the principal is told.
- **What may be sent: transactional mail only.** Result notices, fee notices, absence alerts and invitations: the existing `messaging` kinds. No newsletters or bulk marketing. The whole platform shares one Brevo sending reputation, and a school's mailing list must not put every other school's result notices at risk.

### 8.2 The records the school adds

On `/website/email/`, next to the domain page, behind the same premium add-on as custom domains (§7.1). The values come from Brevo's API
for that domain and are shown exactly as Brevo returns them:

| Record | Name | Value |
|---|---|---|
| TXT (ownership) | apex | `brevo-code:<value from Brevo>` |
| DKIM | `<selector>._domainkey` (Brevo names the selector or selectors, as TXT or CNAME) | from Brevo |
| SPF | apex TXT | **merged** into the school's existing record, never a second one: e.g. `v=spf1 include:_spf.google.com include:spf.brevo.com ~all`. The page reads the current record and shows the merged result, and warns if it would pass SPF's 10-lookup limit. |
| DMARC | `_dmarc` TXT | if the school has none: `v=DMARC1; p=none; rua=mailto:<school address>`. An existing policy is shown and left alone. |

- DMARC alignment comes from DKIM signing as the school's domain. Gmail's and Yahoo's sender rules (since 2024) require SPF or DKIM plus a DMARC record, which this meets.
- The bounce (Return-Path) domain stays Brevo's.
- Verification is the same state machine as §7.2: pending, verified, failing, lapsed. A failing sender domain falls back to the platform `From` straight away; there is no grace period for mail.
- **Checked before PR 11a starts**, with the answers written into this note: the current Brevo plan's daily sending limit, measured against a results day (every school's result notices on the same afternoon), and whether the plan supports one authenticated sender domain per school, and how many.

### 8.3 Mailboxes: not built

Classnode sends mail; it does not host inboxes. The page carries a short guide:

> **Want staff addresses like bursar@yourschool.edu.ng?** Use Google Workspace
> (schools that qualify can get Google Workspace for Education Fundamentals free)
> or Zoho Mail (has a low-cost plan for small teams). They give you **MX** records
> and an **SPF** include. Add their include to the same SPF line as ours (above).
> Never create a second SPF record. Check each provider's current prices and
> eligibility on their own site.

---

## 9. Images and video

### 9.1 Images

| Rule | Value |
|---|---|
| Accepted | JPEG, PNG, WebP, and HEIC (iPhones) through `pillow-heif`, a new pinned and hashed dependency. Decoded by Pillow only; the file's extension and the browser's MIME type are not trusted. **SVG is refused** everywhere (it can carry script). GIF is refused (use video). |
| Upload size | ≤ 15 MB per photo; ≤ 60 megapixels read from the header before decoding (the existing pattern). Five uploads at once per editor. |
| What is kept | a master re-encoded from the decoded pixels: sRGB, EXIF orientation applied, **all metadata stripped (GPS included)**, at most 3000 px on the long side, JPEG quality 90. The original upload is discarded. |
| Renditions | §4.2: 7 widths × AVIF, WebP and JPEG, made in the Celery worker after commit, on a queue of its own so photo work never delays result PDFs. AVIF quality is tuned so that dark skin tones keep their shadow detail; the design round signs off on the exact quality using real photos of Nigerian pupils. |
| Required with each photo | alt text (publish is refused while any published image lacks it, as `blog.markdown.images_without_alt` already does); a focal point (tap on the image), which every crop uses so faces are not cut off |
| Child-image consent | each upload asks the uploader to confirm: "Parents have agreed to photos of their children being published." The answer is stored on the image. The wording is on the lawyer list. |
| Quota | 2 GB of masters plus renditions per school at first, shown on the media page. |

**Storage.** This is the first feature for which Postgres `BinaryField` is the
wrong home: a gallery school could hold several hundred megabytes, and backups
and the weekly restore test grow with it. **Decided 2026-10-24: the VPS disk for the pilot, backed up nightly to B2. Move to B2 object storage when space or load calls for it.**

- Files on the VPS data volume under `/srv/classnode/media/<schema>/<2-hex>/<content hash>-<width>.<fmt>`.
- **A nightly backup** to B2 runs from `deploy/cron/classnode` beside the database backup. It copies only new files, since names are content hashes and never change. It reports failure the way `deploy/postgres/backup.sh` does, and the weekly restore test checks that a sample of files comes back.
- **When to move to B2**: when the media volume passes 70% full, or when serving media becomes a noticeable share of the server's bandwidth or CPU at the post-CBT load test. Because Django already decides and Caddy only sends, the move changes only where Caddy fetches from. The URLs, the tenant check and the tests stay the same.
- Postgres holds only the rows (`SiteImage`: key, hash, size, focal point, alt text, consent flag, uploader).
- Served by **Django deciding and Caddy sending**:
  1. `/media/<key>-<w>.<fmt>` reaches Django;
  2. Django looks the key up **in the current school's schema**, checks that the image is published or that the requester may preview it, and answers with an internal redirect header (`X-Accel-Redirect`);
  3. Caddy's `reverse_proxy` `handle_response` serves the file from a read-only mount with the immutable cache header.

  So school B's image cannot be served on school A's host, even with its key and hash, and gunicorn never streams the bytes.

### 9.2 Video

- **Self-hosted, only for hero video**: a muted ambient loop. MP4 or MOV up to 100 MB, at most 30 seconds. `ffprobe` checks the container and streams before anything else runs.
- It is transcoded once, in the Celery worker (an `ffmpeg` added to the image), on its own queue with concurrency 1 and `nice`, so it cannot starve the portal. Outputs:
  - 1080p and 720p H.264 MP4 for desktop, ≤ 4 MB / ≤ 2.5 MB;
  - 480p for phones, ≤ 1.2 MB;
  - a poster image made like any photo.
- Audio is stripped.
- **Loading rules**:
  - the poster is the LCP element;
  - the `<video>` gets its `src` only after the `load` event, and only when the screen is ≥ 768 px wide or the theme opts phones in, `navigator.connection.saveData` is not set, and `prefers-reduced-motion` is not `reduce`;
  - otherwise the poster stays.
  - There is always a visible pause control.
- Videos with sound, such as a principal's address or a school tour, are **not hosted**. They are a link to YouTube or Vimeo, drawn as a "click to play" poster, and the player loads only on tap, from `youtube-nocookie.com`. (Decided 2026-10-24.)

### 9.3 Maps

`contact_map` shows the address and an **Open in Maps** link built from a
latitude/longitude. An embedded Google map (an iframe and roughly half a megabyte
of script) loads **only when tapped**, behind a static placeholder. (Decided
2026-10-24.)

---

## 10. Security

### 10.1 Tenant isolation

- **Site content lives in each school's own schema**: drafts, revisions, sections, images, news, albums, applicants, every log. It is isolated by `search_path`, as everything else is (`docs/tenancy.md`, with the connection-per-request rule from issue #115).
- **Shared-schema tables.** Only `CustomDomain` and `SenderDomain`. Each has a `school` FK, and every query from a school's request filters on `request.tenant`, never on an id taken from the request. The rule against tenant-to-shared foreign keys (`docs/tenancy.md`, "option 2") is respected: these are shared-to-tenant FKs on `School`, which is allowed.
- **Cache keys** start with the schema name and include the host. Two schools can never share a cache entry, even with the same revision id.
- **Media** is looked up in the current schema before Caddy is told which file to send (§9.1).
- **Custom host to school**: a custom host resolves only through its own `Domain` row to its own school. The ask endpoint and the router read the same `CustomDomain` row.
- **The editor's authority** is `roles_at(request.school)`, checked at every write, so a principal at school A who is also staff at school B has no authority at B unless B gave it.

### 10.2 XSS and injection

- **No HTML from users, anywhere.** All text is autoescaped. Site templates contain no `|safe`, `mark_safe` or `autoescape off`, and the theme contract test greps for them.
- **Line breaks** go through `linebreaksbr` after escaping (the current `site.html` pattern).
- **Links** come from structured fields only. Allowed: internal paths from the fixed list, and `https:`, `tel:`, `mailto:` and `https://wa.me/`. Refused, server-side: `javascript:`, `data:`, `vbscript:`, protocol-relative `//`, and schemes a parser could misread. External links get `rel="noopener noreferrer"`.
- **Colour values** are six hex digits only, validated as `results.look.clean_colour` does. They are written into a per-page `<style nonce>` block, not an inline `style` attribute, so CSP can refuse inline styles.
- **JSON-LD** is escaped as in `website.views._json_ld`.
- **Content-Security-Policy on public pages**:

  ```
  default-src 'self'; img-src 'self'; media-src 'self'; font-src 'self';
  style-src 'self' 'nonce-…'; script-src 'self'; frame-src 'none';
  form-action 'self'; base-uri 'none'; frame-ancestors 'none'
  ```

  `frame-src` is relaxed to the one maps or video host only on a page where that tap-to-load embed exists.

### 10.3 Abuse and takedown

The worst case is not defacement. It is **a fake "pay fees into this account"
notice** on a real school's site, posted by a compromised account or a rogue
staff member. So:

- **Bank details.** A NUBAN-like 10-digit number in any text field triggers a confirm step on publish ("This page shows a bank account number. Parents may pay into it. Confirm it is the school's.") and is logged with the publish.
- **Report this page.** A footer link on every school site goes to a form on `classnode.co` (the same honeypot and limits) that emails the platform's abuse inbox.
- **Suspension.** Platform staff can suspend a school's public site from the handover page. A neutral holding page is served ("This site is temporarily unavailable. Contact the school on …"), recorded with who, when and why, and the principal is emailed. Content is untouched, and lifting the suspension restores the last revision.
- **Response target** (a proposal for the owner and the lawyer): fraud or child-safety reports acted on within 24 hours, copyright reports within 72 hours.
- **New sign-in and publish alert.** Every publish emails the principal: "Your website was published by {name} at {time}." A stranger's publish is noticed within minutes.

### 10.4 For the lawyer

1. The school-website terms: the school is responsible for its content; Classnode hosts it and may suspend it; the takedown process and its timings.
2. Admissions consent wording (§5.3), the lawful basis for children's data under the NDPA 2023 and GAID 2025, the retention period for applicants who are not admitted, and who is controller and who is processor.
3. Consent for published photos of children (the upload confirmation in §9.1), and what happens when a parent withdraws it.
4. Copyright in photos, video and fonts (the Copyright Act 2022), and notice-and-takedown.
5. Cross-border transfer: the VPS location, Brevo (EU), B2 (US or EU, whichever is chosen).
6. Sending mail as the school's domain: the school's authorisation, and liability for content.
7. The custom-domain terms: what we do when verification lapses, and that the school keeps control of its own DNS.
8. A template privacy notice for schools to adapt, and Classnode's own privacy notice updated to cover applicant data.
9. Whether Classnode needs to register with the NDPC as a data controller or processor of major importance at this volume of children's data.

---

## 11. Accessibility

### 11.1 Every theme, every page

- **320 px**: no horizontal scroll, nothing cut off. The screens job adds 320 to its 360, 768 and 1280 px widths for site pages.
- **200% text** (browser zoom and the font-size setting) loses nothing (WCAG 1.4.4), and content reflows at 320 CSS px (1.4.10). Headings may wrap, but never overflow or overlap the crest.
- **Contrast, WCAG AA**: 4.5:1 for text, 3:1 for large text and UI. This is checked on the colour roles at save (§3.1) and on rendered pages in the screens job.
  - **Text over images**: a scrim (gradient or solid band) whose strength is set so text meets 4.5:1 over **both a pure white and a pure black image**. The theme contract renders the hero over both.
- **Keyboard and focus**: visible focus on every control, a skip link, a menu usable by keyboard, nothing reachable only on hover. Targets are at least 44 px (the existing screens rule).
- **Images**: alt text is required (§9.1); decorative images get empty alt. The crest's alt text is "{School name} crest".
- **Motion**: everything stops under reduced motion; video has a pause button; nothing flashes.
- **Video with speech** is external (§9.2), and the link says if it has captions.
- **Language**: `lang="en-NG"` on the page. The motto carries its own `lang` (`la`, `yo`, `ig`, `ha`, `ar`) and `dir="rtl"` for Arabic.
- **Forms**: labels always visible, errors in words next to the field, no time limit the person can see (the 2-hour token is generous), and phone fields accept `0803…` and `+234 803…`.

### 11.2 Nigerian school content every theme must draw well

The "long" fixture school in the theme contract is built from this list:

- **Long names**: "Federal Government Girls' College, Abuloma, Port Harcourt", "Our Lady of Apostles Catholic Secondary School, Ijebu-Ode", "Ansar-Ud-Deen Comprehensive High School". At 320 px they must wrap well beside or under the crest, never be truncated, never shrink below body size.
- **Mottos in Latin, English, Yoruba, Igbo, Hausa or Arabic**, with a translation line.
- **Glyphs** that every theme font must have (the contract checks the font's character map):
  - Yoruba: `ẹ ọ ṣ Ẹ Ọ Ṣ` with combining grave and acute (`ẹ́ ọ̀`);
  - Igbo: `ị ọ ụ ṅ`;
  - Hausa: `ɓ ɗ ƙ ƴ ʼ` and their capitals;
  - `₦`;
  - curly quotes and `’`.

  Arabic text falls back to a system font, which is acceptable for a short motto.

  **Found in PR 3, fixed after PR 3:** the design system's font, Hanken Grotesk, was subset with none of the letters above but the curly quotes, so a browser drew each in a system font and "Ìmọ̀" read in two typefaces. The font files are now cut to carry them (ṣ and ₦ built from Hanken's own shapes), with a Noto Sans subset for the Hausa hooks, fetched only on a page that has one (`docs/design.md`, "Fonts"). The starter theme has no exception any more: the theme contract requires the glyph list in `tests/glyphs.py` to be covered by the theme's fonts, and `tests/ui/glyphs.test.js` checks the browser draws them with no system font. The portal, the report cards and the slips use the same faces for children's and parents' names.
- **Titles and names**: "Rev. Sr. Dr. (Mrs) Ngozi Okafor-Adeyemi", "Alhaji Mallam …", hyphenated double surnames.
- **School structure**: JSS 1–3 and SSS 1–3 (or Basic 7–12), day and boarding, two-term or three-term sessions written "2026/2027", entrance-exam dates, WAEC, NECO and BECE results as facts with years and sources.
- **Contact details**: `+234` numbers, WhatsApp as the main contact, addresses with landmarks ("Off Ring Road, opposite the Federal Secretariat"), more than one phone number.
- **Faith**: Christian, Islamic and secular schools alike: crests with crosses or crescents, prayer times or chapel in "facts", Arabic in the motto.
- **Photos**: crowded assembly and graduation shots, bright outdoor light with deep shade, and dark skin tones that must not be crushed by compression or lost under a scrim.
- **Sparse content**: a school with only a crest, a name and a phone number must still look intentional, not broken.

---

## 12. The PR breakdown

One PR per step, each cut from `main`, merged before the next starts (the Phase 1
rule). Every access-control test uses **two schools**, never one.

### PR 1: Reserve the paths, and make indexing per route (small)

No visible change except `robots.txt`. **Built.**

- `schools/paths.py` sorts every first segment into `PUBLIC_SITE`, `PORTAL` and `RESERVED`.
- The held names route to `schools.views.reserved`, which is a 404.
- `website.crawlers` lets a response on a school host escape noindex only when all three hold: its view sets `response.indexable = True`, its path is the website's, and the host is not the portal.
- A school host's `robots.txt` names `NEVER_INDEXED` ahead of the closing `Disallow: /`.
- The tests are in `schools/tests/test_paths.py`. When PR 3 opens the website, it drops that last line and marks the website's views. It does not touch the lists.

- The reserved-path list, including `sit/`, and the test that every `urls.py` route is a public page or reserved.
- `CrawlerMiddleware` indexes only responses marked as public-site responses. Nothing is marked yet, so every school host stays `noindex`.
- `robots.txt` on school hosts names the disallowed paths.

Access tests:
- `/sit/` on two school hosts is `noindex` and disallowed in `robots.txt`;
- a route added without being classified fails the test;
- the portal and `classnode.co` are unchanged.

### PR 2: Engine content model, draft, publish, log, delegation (service layer only)

- Models in the tenant schema: `SiteSettings`, `Page`, `Section` (with per-kind validation), `SiteRevision`, `SitePublishEvent`, `SiteDelegationEvent`.
- Services: `save_draft_as`, `mark_ready_as`, `publish_as` (principal only), `rollback_as` (principal only), `set_delegation_as`.
- No page and no public change.

**Built.**
- The app is `schoolsite`, a tenant app.
- `save_draft_as` became one call per part of the draft: `save_page_as`, `add_section_as`, `save_section_as`, `remove_section_as`, `move_sections_as` and `save_footer_as`. There is also `set_theme_as`, the principal's.
- Theme options are held to an allow-list (`schoolsite.themes`): a known theme key, that theme's header styles and font pairings, and the five colour roles as six-digit hex. Text on its surface must reach 4.5:1.
- Revisions and both logs refuse UPDATE and DELETE in the model and by a trigger each.
- **The "Ready for the principal" email moved to PR 4**, together with the preview page it links to (decided 25 October 2026). PR 2 records the ready state and its log row.
- News and gallery sections are checked for shape only; whether the post or album exists is checked in PRs 5 and 6.

Access tests:
- the principal at A can publish at A and gets `NotAllowed` at B;
- an administrator is refused draft edits at A until A's principal delegates, then allowed, then refused again after revocation, without signing out;
- a delegated administrator is refused publish and rollback;
- "Ready for the principal" is recorded in A's log only (its email to A's principal is PR 4's);
- delegation at A gives nothing at B;
- a teacher, bursar, VP academic, parent or student is refused every write;
- a suspended or invited principal is refused;
- a stale version is refused;
- every publish and rollback writes exactly one log row naming the actor.

### PR 3: Public rendering, the starter theme, Sign in, caching, CSP

- The engine renders `/` and the fixed pages from the latest revision in a **starter theme**. This is today's `site.html` look, rebuilt on sections, and it is not the designed theme.
- The "not yet published" fallback, the Sign in menu, indexing switched on for published pages, the sitemap, canonical URLs, CSP, the Redis HTML cache, and no cookies or session reads on public views.
- The theme contract tests and the frame-budget entries.

Access tests:
- A's published page never appears on B's host, with the same path and the same revision id (cache key test);
- a draft is never served publicly;
- public responses carry no `Set-Cookie` and no `Vary: Cookie`;
- portal pages stay `noindex`;
- link fields refuse `javascript:`, `data:` and `//` (one test each);
- templates pass the no-`safe` grep.

**Built.**
- `schoolsite.views` and `schoolsite.render` draw the pages with no request in hand. Before a school's first publish, the root is today's page, still noindex, and nothing else of the site answers.
- The access, blog and session middleware leave a school's public paths alone (`schools.paths.is_public_site_request`). So public pages send no cookie and no `Vary: Cookie`, and a family signed in at another school sees them as anyone would.
- `website.crawlers` indexes a marked response only when it was served for a school.
- A published school's `robots.txt` drops the closing `Disallow: /`, keeps the never-indexed paths named, and points to its sitemap.
- The page cache is its own `sites` alias: Redis database 1 under `SITE_CACHE_URL`, in-process elsewhere. Its key holds the school's schema, revision, what the page shows of the school, the host and the path. A cache that is down gives a slower page, never a broken one.
- The CSP allows the page's one inline style by its hash, and no script.
- As agreed:
  - the hero draws without its picture, and news and gallery draw nothing, until PRs 5 and 6;
  - the contact panel links out to Maps, and the tap-to-load map comes in PR 5;
  - the screens job gained the Slow 4G check (`tests/ui/school_site.test.js`). Locally the published pages paint their largest content in about 0.7 s, with no layout shift, moving about 65 KB.
- `seed_demo` publishes Harbour's site; Sunrise keeps today's page.

### PR 3b: Custom pages and a menu that updates itself

Added on 25 October 2026. Built before PR 4, so the editor is built once, with custom pages in it.

- **The model change.** PR 2's models need an additive change, not a rewrite:
  - `Page` gains `kind` (fixed or custom), `slug`, `slot` (1 to 12, unique) and `menu_position`;
  - `key` becomes empty for a custom page;
  - the constraint `a_page_is_one_of_the_fixed_six` becomes "a fixed page has one of the six keys and no slug or slot; a custom page has a slug and a slot and no key";
  - the revision snapshot gains `kind`, `slug` and `menu_position` per page;
  - `sections.ALLOWED_ON` gains the custom page's kinds (§2.1.1).

  No school can have published before the editor exists, so there is nothing to carry over beyond giving the six fixed rows their kind and menu order.
- **Services:** `create_page_as`, `rename_page_as`, `delete_page_as` (only while the page has never been published, or once it is switched off) and `order_menu_as`.
- **Rendering:** `/pages/<slug>/`, the self-updating menu with its "More" on a phone, the footer and the sitemap. `pages` is added to `schools.paths.PUBLIC_SITE`.
- Adding, removing and reordering sections on any page is already built as services in PR 2 (`add_section_as`, `remove_section_as`, `move_sections_as`). PR 4 gives them their screens.

Access tests:
- only A's editors make, rename, delete or reorder A's pages, and only A's principal publishes them;
- a thirteenth custom page is refused, by the service and by Postgres;
- a custom slug cannot clash with a fixed page or a reserved path, and B's custom page never answers on A's host;
- a custom page switched off, or never published, is a 404, and is in no menu and no sitemap.

### PR 4: The editor and preview in the portal

- `/website/` on the school's classnode host: page list (fixed and custom pages, switch on or off, make, rename, order the menu), section editor (add, remove, reorder, edit), theme options, delegation switch, the "Ready for the principal" button, and the publish log.
- `/website/preview/…`.

Access tests:
- every `/website/` route refuses non-editors with 403 and refuses B's staff on A's host;
- preview is `noindex` and `no-store` and is refused when signed out;
- previewing another theme does not change the draft;
- the delegation switch and the Publish button are refused to the administrator, delegated or not;
- "Ready for the principal" emails A's principal, and only A's, a link to the preview (moved here from PR 2).

### PR 5: Images and the gallery

- The upload pipeline (§9.1), renditions on their own Celery queue, the media volume with its nightly B2 backup and restore check, `/media/` behind Django with Caddy's `X-Accel-Redirect` handling, and quotas.
- Alt text and focal points, the consent confirmation, and the `gallery` section with albums.

Access tests:
- A's image key requested on B's host is 404;
- an unpublished image is 404 when signed out and served in A's preview to A's editor only;
- SVG, GIF, a renamed PDF, a decompression bomb and an oversize file are each refused;
- GPS EXIF is absent from every rendition;
- the quota is per school.

### PR 6: News

`NewsPost` with publish-per-item, the `news` section, `/news/` and `/news/<slug>/`.

Access tests:
- the same matrix as PR 2 for posts (a delegated administrator drafts, only the principal publishes);
- a draft post is 404 publicly;
- a slug that clashes with a reserved path is refused.

### PR 7: The designed theme (after the design round)

One theme for now (decided 25 October 2026), with its colour roles from the crest, its header styles and its font pairings. It is a theme directory plus its fonts, passes the contract, and carries the Nigerian alphabets (§11.2) with no exception. More themes later are each a PR of this shape.

Access tests: none new. The contract runs the PR 3 isolation and escaping tests against the theme.

### PR 8: Hero video (after the design round)

`ffmpeg` in the image, the video queue, the loading rules in §9.2, and the external video facade.

Access tests:
- the same matrix as PR 5 for video;
- a video with an unexpected container or codec is refused;
- a phone-width page load fetches no video bytes.

### PR 9a: Admissions forms and the applicant model

- The two forms, the signed token, the honeypot, per-address and per-school limits, duplicate handling, consent versioning, and the closed state.

Access tests:
- a token minted on A's host is refused on B's host;
- the limits count per school (A's flood does not close B's form);
- a submission on A creates a row in A's schema only;
- no email is sent to the address typed into the form.

### PR 9b: The applicant list in the portal

`/applicants/`, status changes with events, CSV export logged, the batched notification email (to the admissions address if set, otherwise `contact_email`), and the retention job.

Access tests:
- principal and administrator only;
- B's staff get 403 on A's host;
- a teacher or bursar gets 403;
- an export writes an event;
- A's alert goes to A's admissions address or contact email, never B's;
- the retention job deletes only past-period, non-admitted rows, in each school separately.

### PR 10a: Custom domains: claim, verify, state machine (no TLS yet)

`CustomDomain` in the public schema, the premium add-on switch (`School.site_premium`, set by platform staff on the handover page and logged), `/website/domain/`, DNS checks through public resolvers, `check_custom_domains` on cron, and the emails to the principal.

Access tests:
- a school without the add-on is refused a claim by the service, not only by the page;
- only platform staff can switch the add-on, and every switch is logged;
- switching it off at A lapses A's domain and nobody else's;
- only A's principal can claim for A;
- B cannot claim a hostname A holds;
- a claim needs its own token (an old TXT record from a lapsed claim does not verify a new one);
- `classnode.co` names are refused.

### PR 10b: Caddy on-demand TLS, the ask endpoint, host routing

- The Caddyfile block, `/_caddy/ask`, `ALLOWED_HOSTS` with the host-validation middleware, the public-only URLconf with 302s on custom hosts, HSTS without `includeSubDomains` on custom hosts, canonical 301s, and the TLS warm-up request.
- A runbook in `docs/deployment.md`.

Access tests:
- `/_caddy/ask` answers 200 only for verified, active or failing hosts, and 403 for pending, lapsed, unknown and `*.classnode.co` hosts;
- `/_caddy/ask` returns 404 through every public host;
- `/home/`, `/check/` and `/sit/` on A's custom host 302 to A's classnode host, never to B's;
- an unknown host 404s;
- the session and CSRF cookies are never set on a custom host.

### PR 10c: Lapse

failing → lapsed, removal of the `Domain` row, fallback of the 301s, the notifications.

Access tests:
- a lapsed host 404s;
- the ask endpoint refuses it;
- B's domain is unaffected by A's lapse.

### PR 11a: Brevo SMTP, and a per-message From

- Before it starts: the Brevo plan's daily limit and multi-domain support (§8.2), answered in this note.
- Configuration is already live on the server (Brevo).
- `Outbound.from_address`; `SmtpProvider` sends it.
- The platform `From` reads "{School} via Classnode".

Access tests:
- a message for A never carries B's name or Reply-To (two schools sending in one worker run);
- production still refuses the fake provider.

### PR 11b: School sender domains

`SenderDomain`, the Brevo domain API calls, the records page with SPF merge, verification and fallback.

Access tests:
- a school without the premium add-on is refused by the service;
- switching the add-on off at A makes A's very next send use the platform `From`, and leaves B's alone;
- only A's principal adds A's sender domain;
- A's mail never uses B's verified domain;
- a failing domain falls back on the very next send;
- B cannot register a domain A has verified.

---

## 13. Decisions, 2026-10-24

The owner's answers to the open questions in the first version of this note.
Each is written into the section it changes.

| # | Question | Decision | Where |
|---|---|---|---|
| 1 | May a delegated administrator publish? | **No.** Drafts only, plus "Ready for the principal". The principal publishes, because large schools guard their brand. | §2.3, §2.4, PRs 2, 4, 6 |
| 2 | Storage for photos and video | **VPS disk with a nightly B2 backup** for the pilot. Move to B2 when space or load calls for it. | §9.1, PR 5 |
| 3 | Video | **Self-host only short, muted hero loops.** Video with sound comes from YouTube or Vimeo, loaded on tap. | §9.2, PR 8 |
| 4 | Maps | **Address plus "Open in Maps"**, with the map loading only on tap. | §9.3 |
| 5 | CDN now? | **Not yet.** Decided at the load test after CBT. Cloudflare's proxy complicates custom-domain certificates. | §4.4 |
| 6 | `www` as the main address | **Yes.** The apex redirects to it. | §7.1 |
| 7 | Brevo | **Yes, already live on the server.** Check the plan's daily limit and multi-domain support before PR 11a. | §1, §8, PR 11a |
| 8 | Admissions uploads and fee | **Uploads later. The fee only after Paystack verification.** | §5.1 |
| 9 | Admissions alerts | **The school's `contact_email` by default**, with an optional separate admissions address. | §5.2, PR 9b |
| 10 | Admissions officer role | **Not now.** Principal and administrator only; added if schools ask. | §5.2 |
| 11 | Included or add-on | **The website on the classnode address is included.** A custom domain and school-domain email are a **paid premium add-on**. | §7.1, §8.2, PRs 10a, 11b |
| 12 | Several campuses | **Out of scope for now**, added later. | — |

### Decided 25 October 2026

| Decision | Where |
|---|---|
| **The scope widens:** a school switches any fixed page on or off except Home, adds, removes and reorders sections on every page, and makes up to 12 custom pages from the safe section kinds, with a menu that updates itself. | §2.1, §2.1.1, PRs 3b and 4 |
| **One designed theme, with strong options**, instead of three. The engine stays ready for more. | §3.3, §3.4, PR 7 |
| PR 3: the hero draws without its picture, and news and gallery draw nothing, until PRs 5 and 6. | PR 3 |
| PR 3: "Open in Maps" only; the tap-to-load map comes in PR 5. | §9.3, PR 3 |
| PR 3: the Slow 4G largest-paint check is in the screens job now. | §4.1, PR 3 |

**Still to settle before the PR that needs it:**
- the Brevo plan check (before PR 11a);
- Paystack verification (before any application fee);
- the add-on's price, which is a commercial decision and outside this note;
- the visual design round (before PRs 7 and 8).
