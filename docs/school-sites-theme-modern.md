# School website theme: "Modern Campus" (approved design brief)

This is the approved design for the school website theme. It replaces the
starter theme's look and is delivered in two PRs: PR A (the theme) and PR B
(new section kinds), PR B after PR A.

## PR A (theme)

Replace the starter theme look with Modern Campus, keeping it as one theme
with per-school options.

- **Look:** white page, Hanken Grotesk (our cut with the naira sign), bold
  800 headlines, tight letter spacing, radius 20 to 28 px, soft shadows, no
  card borders. Hero headline fluid about 30 px (phone) to 48 px (desktop);
  section headings 28 to 40 px; fact numbers 30 to 40 px. Primary colour from
  the school crest (demo navy #143D8C), warm accent for the main call to
  action (demo #FFD66B), gold detail (#C9A24A), soft tinted panels (#EEF3FC,
  #FFF6DC, #F1F4F9, #E8F6EF), one dark band (#0F1B33). All colours from theme
  options with contrast checks.
- **Sticky header on all sizes:** translucent white with light blur and soft
  shadow (solid fallback), slim (about 12 px padding), crest tile and school
  name; desktop links plus Sign in and Apply now; under about 860 px a menu
  button opens a rounded panel dropping from the sticky bar with the links and
  two big buttons (Sign in, Apply now). Never wrap links. Anchor jumps never
  hide headings under the bar (scroll-margin). Works without JavaScript (menu
  falls back to a plain list).
- **Footer:** compact, "Powered by Classnode" is a link to
  https://classnode.co in the primary colour, bold.
- **Hero:** left panel (admissions pill, headline, intro, two buttons) with
  animated line art behind; right a rounded photo slideshow: 1 to 5 school
  photos, 700 ms crossfade, auto-advance every 4 s, dots to jump, pauses while
  hovered or touched, no visible pause button (owner's decision), no
  auto-advance under prefers-reduced-motion; headline and buttons never move.
  Only slide 1 loads with the page (preloaded, it is the LCP); others
  lazy-load after load and not under Save-Data. Alt text required.
- **Existing sections restyled:** facts (bento cards), principal's message,
  gallery as a mosaic (one tall photo, smaller ones, count tile), admissions
  band, contact. News section shows nothing until the news PR exists.
- **Animated backgrounds (five, each switchable per school):**
  1. hero: three thin concentric orbits rotating slowly in opposite
     directions (about 38 s and 52 s per turn), gold dots riding them with a
     soft glow, the Classnode node triangle drawing once on load;
  2. academics corner: softly bobbing rings, a dashed gold ring with flowing
     dashes, a slow orbiting dot, two twinkling plus marks;
  3. student life dark band: a constellation of gold, yellow and soft-blue
     dots joined by thin dashed lines, two groups drifting (14 s and 18 s
     loops), twinkling dots, flowing dashes, a faint rotating dotted ring;
  4. admissions band: orbits on the right with circling dots and a pulsing
     centre;
  5. contact map placeholder: a dashed route flowing to a pulsing school pin.

  Rules: inline SVG plus CSS only, no libraries, no JavaScript, animate only
  transform, opacity and stroke-dashoffset, low contrast so text always reads,
  aria-hidden, colours from theme options, all stopped under
  prefers-reduced-motion, and paused when off screen if cheap to do.
- **Speed:** everything below the first screen lazy-loads; keep within the
  existing page budgets and the slow-4G LCP check on the full page (hero
  120 KB at 828 px). If the budget can't fit something, tell the owner instead
  of raising the budget.
- **Mobile:** every section stacks to one column, hero text first then
  slideshow, 44 px tap targets; screens tests at 320 px, 390 px, 1280 px and
  with 200% text.

## PR B (new section kinds), after PR A

- **programmes:** 2 to 6 cards: icon from a fixed set, title, text.
- **facilities:** 2 to 8 tiles: icon, title, short line.
- **clubs:** heading, text, up to 16 pills.
- **events:** school-edited list: title, date, time, place; past events drop
  off; homepage shows the next 3.
- **steps:** 2 to 6 numbered steps.

Editor screens for each in the phone-first editor. Homepage order: hero,
facts, principal, academics (programmes), facilities, student life (clubs),
events, news, gallery, admissions steps, admissions band, visit us, footer;
schools can switch any off and reorder.

## Both PRs

Tenant isolation tests with 2 schools (break, confirm red, restore); update
the Harbour and Crestfield demo sites to use the new theme and sections with
sensible demo content; push after each commit, enable auto-merge tied to the
head SHA, stop without polling CI, and list any server steps.

## Engine changes (in the PR where they're needed)

- **PR A:** the hero section stores 1 to 5 slides (picture plus alt text and
  focal point each), replacing the single picture, with existing heroes
  migrated as one-slide slideshows. Theme options gain accent and detail
  colours (validated, with contrast checks) and an on/off switch for each of
  the five animated backgrounds, all stored in the allow-listed theme options,
  never as free markup, and included in published revisions so rollback
  restores them.
- **PR B:** each new section kind (programmes, facilities, clubs, events,
  steps) gets its model fields, server-side validation and limits, which pages
  it is allowed on, inclusion in published revisions and rollback, the public
  rendering, and its editor screen. Events get their own small list (title,
  date, time, place) with the same draft/publish and logging rules as other
  content.
- Existing schools' sites keep working after each deploy with no manual
  steps; write migrations for any data changes.

---

## As built: PR A (1 November 2026)

The owner's answers of 1 November 2026, taken into the build: a slide's
description and focal point are the photo's own; the admissions pill comes from
the page's admissions panel; PR A stores all five animation switches and draws
backgrounds 2 and 3 and the dark band in PR B; the school sets four colours with
the tints worked out; existing schools get every animation on and the demo's
accent, detail and dark colours, keeping their own main colour; and the header's
Sign in keeps its two doors, with Apply now going to Admissions, else Contact.
Decision 9 as changed the same day: the demo photos are generated scenes with no
real children, and the demo copy is plain and specific rather than slogan-like
("A day secondary school in Abeokuta, JSS 1 to SS 3", not a three-beat tagline).
Harbour's and Crestfield's headings, principal's messages and section words are
written that way (`schoolsite/demo.py`, `schools/crestfield/site.py`).

### The engine

- **The theme key.** `starter` became `modern` (`schoolsite.themes`). Migration
  `schoolsite/0005_modern_campus` moves every school's draft: the theme key, its
  options (the school's own main colour kept, the demo's accent `#FFD66B`,
  detail `#C9A24A` and dark `#0F1B33` added, all five animations on), and every
  hero's one `image` into `slides: [{"picture": id}]`. Published revisions are
  never rewritten (their trigger refuses it): `render.theme_of` draws "starter"
  as Modern Campus, `sections.hero_slides` reads an old `image` as one slide, and
  `services.comparable` compares snapshots as they draw, so no school is told it
  has changes to publish, and a rollback to an old revision draws the same.
- **The hero** (`sections._hero`) holds `slides`, 0 to 5, each photo once, or a
  `video`, never both. A photo's alt text and focal point stay on `SitePicture`,
  so it reads and crops the same wherever it is drawn. Publishing still waits
  for every slide's description; taking a photo down takes that slide only.
- **The look** (`themes.clean_options`, `services.set_look_as`, the principal's):
  `colours` gains `detail` and `dark`, and `animations` holds the five switches.
  The checks, run on the palette as it will be drawn (choices plus the theme's
  own): white on the main colour 4.5:1, the dark colour on the accent 4.5:1,
  white on the dark band 4.5:1, the detail on the dark band 3:1, and the text
  4.5:1 on the surface and on each tint. The tints are worked out from the main
  colour and the accent (`themes.palette`: `#EEF3FC`, `#FFF5DC`, `#F1F4F8` for
  the demo; the mint `#E8F6EF` is fixed). Options live in the snapshot, so
  publish and rollback carry them.
- **The page's one style** now names every colour as a custom property
  (`--primary`, `--accent`, `--detail`, `--dark`, `--text`, `--surface`,
  `--tint`, `--warm`, `--mist`, `--mint`); the CSP still allows it by its hash.
  The page cache's generation moved to 3.

### The theme

- `schoolsite/templates/schoolsite/themes/modern/` and `static/schoolsite/modern.css`
  (24 KB of its 30). Hanken Grotesk 400 and a new 800 cut
  (`static/web/fonts/hanken-grotesk-800.woff2`, 12.6 KB, made by `scripts/fonts.py`
  from the reviewed source with the same letters, ṣ and ₦ included). The page
  preloads the 800 and draws nothing at 600 or 700, so a page fetches two Hanken files.
- **Header**: sticky on every size, translucent with a blur where the browser
  has one, solid where not. From 860px the bar holds three pages (five from
  1100px) and "More" for the rest, Sign in (its two doors) and Apply now; under
  860px a Menu button drops a rounded panel with every page and the two big
  buttons. Both are `<details>`: no script needed. Headings and anchored
  sections keep clear of the bar (`scroll-margin-top`).
- **Hero**: the words on the left over the orbit art, the slideshow on the
  right (under the words on a phone). The first photo is a normal `<picture>`,
  preloaded and fetched first; the others are in a `<template>` that the site's
  script (`static/schoolsite/site-app.js`, 7.6 KB of its 8) adds after `load`,
  never with data saver. It crossfades over 700 ms every 4 s, the dots jump, it
  holds while hovered, touched or focused, and never moves by itself under
  reduced motion. A page with one photo runs no script at all.
- **Sections**: facts as a bento of tinted cards, the principal's message as a
  card beside the portrait, the gallery as a mosaic (one tall photo, smaller
  ones, a tile counting the rest that opens the album), the admissions band on
  the main colour with the accent button, and Visit us beside the map
  placeholder. News draws nothing until the news PR.
- **Animated backgrounds** 1 (hero), 4 (admissions band) and 5 (Visit us):
  inline SVG and CSS only, animating `transform`, `opacity` and
  `stroke-dashoffset`, `aria-hidden`, coloured from the palette, still under
  reduced motion, and each in a `content-visibility: auto` box, so the browser
  skips it off screen.
- **Footer**: compact; "Powered by Classnode" links to https://classnode.co in
  the main colour, at 800.

### The editor

- The hero's form chooses one to five of the school's hero photos in order, or
  a video instead, each with a link to its description and focal point on
  Photos and albums.
- **Colours and animations** is a frame of its own, `/website/look/`
  (`static/site-editor/look-app.js`), the principal's: four colour pickers that
  say at once what would not read, by the server's rules, and the five
  switches. The editor's old colour form moved there, which also leaves the
  editor's own frame lighter.

### Measured (development server, uncompressed)

Slow 4G at 360px, median of three: Home 0.94 s to its largest paint, 146 KB
before scrolling; every other page 0.77 to 1.17 s; layout shift at most 0.003.
The hero's photo is still held to 120 KB at 828px by the rendition test.

### Server steps

None beyond the deploy, which runs `migrate_schemas`. To give Crestfield its
slideshow and album, run `manage.py crestfield reset` (it draws its own photos;
no media worker needed). Until then it shows in the new look as it is.
