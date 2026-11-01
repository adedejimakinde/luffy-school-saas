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
