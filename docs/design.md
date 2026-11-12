# The design: "One Blue"

Every page draws from one stylesheet, `static/web/design.css`, included through
`templates/design/head.html`. A page's own stylesheet holds its layout and
nothing else: no page declares a colour.

## The rules

- **One brand colour, `#143D8C`**, for buttons, links, the active nav item and
  the logo; on a school's own host, the school's colour instead where it reads
  on white (below, "School branding"). Text `#0E1726`, secondary text `#5B6475`
  (5.9:1 on white, 5.3:1 on the page), the portal's page `#EEF2F8` under white
  cards `#FFFFFF`, a hovered row or disabled field `#F5F6F8`, borders `#E3E6EB`
  (fields and tables, never a card's edge), row dividers `#EEF0F3`. Lighter or darker
  is the same blue mixed (`--brand-tint`, `--brand-strong`; the public site
  mixes its own deeper blues and a wash in `website.css` the same way), not a
  second colour.
- **Three accents, on the public site's icon tiles only**: teal `#0F766E`,
  amber `#B45309`, coral `#C2452D`, each with a white icon at 5:1 or better.
  Never for words.
- **Five gradients and no others**, each of One Blue: the public site's final
  band, One Blue deepening; on its light top band, the faintest blue along the
  hero photo's top edge and a faint glow behind its screens; the staff
  sign-in's background, One Blue fading into the grey from the top; and the
  blog's tab row on a phone (`static/write/write.css`), a mask rather than a
  colour, fading its last 32px so a tab past the edge reads as more to scroll
  to. `tests/test_design.py` names them.
- **Colour only with meaning.** Green is good, amber is waiting or slightly
  down, red only a real problem, navy the brand and the primary action. Status
  colour sits on small pills (`.pill-ok`, `.label-ok` and the rest): green
  `#16693F` on `#E7F4EC`, amber `#8A5A00` on `#FDF1DC`, red `#B42318` on
  `#FDECEA`. A pill carries a dot or an arrow, never colour alone and never an
  emoji. One more: **the light amber card** (`.card-action`, `#FFF7E8`) for
  anything waiting on the reader. A message is neutral and carries its label
  (`.msg`).
- **Hanken Grotesk**, self-hosted in `static/web/fonts/`, 400 and 700 in
  `design.css`, and 800 for hero figures only in a stylesheet that ships that
  face itself (`static/home/dashboard.css`, the school websites'
  `static/schoolsite/modern.css`: the one cut, `hanken-grotesk-800.woff2`), so
  no other page is asked for it. No light weight anywhere. Was 400 and 700 only,
  `font-display: swap`, the system stack behind it. The files carry Latin and
  the letters a Nigerian name is written with: Yoruba's ẹ ọ ṣ and Igbo's ị ụ
  ṅ (both cases), the combining tone marks and underdots, and the naira sign.
  Hanken has no ṣ and no ₦ of its own, so `scripts/fonts.py` builds them from
  its own shapes (the s with its own underdot, the N crossed by two bars cut
  from its equals sign); nothing is borrowed. The files are static instances
  cut from the family's variable font (SIL OFL 1.1, `OFL.txt` beside them);
  `python scripts/fonts.py HankenGrotesk.ttf NotoSans.ttf` cuts them again,
  and refuses any source whose SHA-256 is not the one reviewed.
  The cut keeps each file's one-line `prep` table: a TrueType font with no
  instructions at all is auto-hinted by FreeType, which on a machine with
  medium or full hinting rounds every advance and made bold text 1.6% wider
  (the Ogun card's health table, 294px at 360px with no width to spare,
  overflowed by 4px on CI). `tests/test_design.py` holds the files to it.
- **Noto Sans, for Hausa's hooked letters only** (`noto-sans-hausa-{400,700}.woff2`,
  1.5 KB each, SIL OFL 1.1, `OFL-noto-sans.txt`): Ɓ ɗ Ɗ Ƙ ƙ Ƴ ƴ and ǹ, which
  Hanken has no drawing of. Its `@font-face` has a `unicode-range` of those
  letters, so a page without one never fetches it, and it is scaled
  (`size-adjust`) and given Hanken's ascent and descent so its letters sit in
  the line at Hanken's size. The stack is `"Hanken Grotesk", "Noto Sans",
  system-ui, ...`: a system font draws no letter of a Nigerian name or amount.
  The report cards load the same faces, with DejaVu Sans last; the slips are
  DejaVu Sans alone, which has every one of these letters.
  `tests/glyphs.py` lists the names and amounts, `tests/test_design.py` holds
  the ranges to the files, `results/tests/test_fonts_in_pdfs.py` reads the
  fonts out of the PDFs, and `tests/ui/glyphs.test.js` asks Chromium which
  fonts it drew them with (`CSS.getPlatformFontsForNode`) and photographs them
  into the `screens` artifact. Its digits are already equal-width, so numbers
  line up without a feature switch; tables still say `tabular-nums` and
  right-align them (`.num`).
- **Cards have no border.** White on the blue-grey page, with `--shadow-1`
  resting and `--shadow-2` lifted (a card under the pointer, the account menu,
  the floating tab bar), each a tight edge shadow and one wide faint lift of the
  text colour thinned. A hairline border comes back only under
  `forced-colors`, where shadows are not drawn. The header has a hairline
  shadow (`--hairline`) instead of a rule.
- **Radii** 12px on buttons and fields, 16px on cards, 20px on the hero card,
  the doors' card and the tab bar. **Buttons** are 44px tall, and the primary
  action is 48px. A press scales a control to 98% for 150ms; nothing moves
  under `prefers-reduced-motion`.
- **Spacing** is 4, 8, 12, 16, 20, 24 and 32 (`--sp-4` to `--sp-32`), with more
  space between groups than inside them.
- **Labels** over a figure or a group are `.eyebrow`: 12px, 700, uppercase,
  spaced, in the secondary grey. Table headings take the same look from 640px
  up and stay 15px on a phone.
- **List rows** (`.list-rows > li > a.list-row`): a tinted icon tile, a bold title over a
  muted line, a pill, a chevron, and dividers inset to where the text starts.
- **Loading** is a skeleton: each page's `.state-loading` sentence, muted, over
  the pulsing shape of a card, until its module's first answer.
- **Icons** are inline stroke SVG (`<svg class="icon">`), drawn here: no icon
  pack, no emoji. The defs live once in `templates/design/icons.html`
  (a `<symbol>` sprite, invisible on its own) and a page includes it wherever
  it draws its first `<use href="#i-…">` — not from `design/head.html`,
  which is head-only content; an `<svg>` there would end the page's implicit
  `<head>` early. Grown page by page as pages restyle.
- **The logo is the one mark that is filled, not stroked**: `#i-brand-mark`
  (`.logo-mark`, not `.icon`) — a rounded blue square, three white dots joined
  by a triangle — beside the lowercase wordmark `classnode`. Every other icon
  stays plain stroke.
- **No em dashes or en dashes in rendered UI copy.** A colon, a comma or a full stop
  instead. Code comments and docstrings are prose and keep writing however
  they already do — this is about what a reader sees on the page. No
  exceptions, and that includes an en dash in a range and a dash standing for
  "nothing to show": the placeholder is a plain hyphen (the broadsheet's
  `DASH`, a session table's default), and a time range is written `08:00-08:40`.

## Widths

Mobile first, checked at 360, 768 and 1280.

- Below 1024px the staff sidebar is a slide-out (a `popover`, opened from the
  top bar's menu button). Below 640px staff pages also get a bottom tab bar
  with the role's four main screens.
- The sidebar and the tab bar are built from the signed-in login's roles at
  this school (`menu.py`, `{% shell_open %}` and `{% shell_close %}`), never
  written per page. Each link carries the role set its own page's API gates on,
  so no link leads to a refusal; `tests/test_menu.py` checks that against the
  real routes, both ways.
- **The top bar** names the school on a desk and shows the logo where the
  sidebar is folded away, with the account menu (name, roles, Sign out) at its
  right. The school is named only to a member of it, and the pages the
  offline worker keeps on a shared phone (`/marking/`, `/register/`) name
  nobody: their account menu is a person icon and Sign out.
- **The tab bar floats**: a white bar 12px clear of the screen's edges and the
  phone's safe area, 20px corners, the lifted shadow, and a soft pill of the
  brand colour behind the current tab's icon. The page's foot padding is the
  bar's height plus 16px and the shell's is the 12px gap, so the last item of
  every list page ends 16px above the bar (`tests/ui/sweep1.test.js`).
- **The tab bar is the role's main screens**: Home first for every staff role;
  Fees for the principal and the bursar (the bursar has three tabs), Broadsheets
  for the vice principal.
- **Class and level names never break across a line**: `JSS 1`, `SS 3`,
  `JSS 1C`. Templates use `{% load typography %}` and `|nobreak`; Python that
  builds a sentence uses `typography.keep_together()`.
- **The sidebar** is 240px, its labels 15px, and every link has an icon of its
  own.
- **Below 640px every list table is a stack of cards, one per row**
  (`table.stack`): the row's name or number heads the card, each other cell is
  a "label  value" line from its `data-label`, and a row's problems or buttons
  close the card. A list that is already a `ul` (the roll, results, staff) is
  the same card (`.stack-list`). In the markup: `td.stack-head` is the card's
  first line (what the row is, with a status label pushed right), `td.stack-full`
  a block under the lines (problems, a note, the row's buttons), `td.stack-hide`
  says again what the head said and is left out, and an empty labelled cell is
  left out rather than a label beside nothing. A table clipped at "Full name"
  with the rest in a sideways scroller is a table nobody on a phone reads to the
  end, which is why this exists.
- **Three tables keep scrolling sideways on a phone**, because their columns
  are the point: the broadsheet, the timetable and the marking sheet. They sit
  in a `.wide` scroller with the first column fixed (the broadsheet fixes the
  name too) and a "Swipe for more" cue above. `tests/ui/screens.test.js`
  fails any other table wider than a 360px screen. The page itself never
  scrolls sideways, and no scroller has a minimum height.
- Forms and side panels (`.split`) stack into one column on a phone.
- Touch targets are at least 44px. Body text on a phone is never under 15px.

## School branding

On a school's own host the portal wears the school, not Classnode
(`schools/brand.py`; tests `schools/tests/test_brand.py`, two schools):

- **The header and the sidebar** show the school's crest and its **short name**
  where the Classnode mark was (`School.short_name`, set under Setup, "Your
  school's web page"; blank means the name before its first comma, so
  "Crestfield College, Abeokuta South" reads "Crestfield College"). It wraps to
  two lines rather than cut off, at 320px too. The full name stays on the
  sign-in page and on printed documents. With no crest, its initials in a tile of the brand colour.
- **The browser tab's icon** is the crest (the upload service's 128px PNG).
  With none, Classnode's icons stay.
- **The brand colour** is the primary colour of the school's website look
  settings, only when it reads on white at 4.5:1; otherwise navy. It replaces
  `--brand` alone, so green, amber and red mean the same at every school.
- **"Powered by Classnode"**, small, under Help in the menu, and under the
  card on a door served on the school's host.
- **Who sees it**: a member of the school on its host, and anybody at a door on
  a school's host. A frame served to a stranger names no school, as the shell
  always did. The doors are on the portal in production, which keeps Classnode's
  own look; on a school's host they exist in the single-host demo.
- **What it costs**: one statement and its search path per page drawn for a
  member, never cached across requests, so no cache key can carry one school's
  crest to another's host (`tests/test_budget.py` pins it).

## The picker

Every `<select>` in the portal opens one picker (`static/web/picker.js`,
`static/web/picker.css`), never the phone's grey system menu.

- **On a desk every list, and on a phone a short one (six options or fewer),
  opens as a menu against the field**, the field's width or 240px: a white
  card, 12px corners, the lifted shadow,
  rows 44px on a desk and 48px under a finger, a blue check and bold text on
  the chosen row, 120ms. It opens under the field, or over it when its rows fit
  there and not under it, so every row shows without scrolling where the screen
  has room. The field's own label names it.
- **On a phone a longer list is a sheet** from the foot of the screen: white,
  16px top corners, a drag handle, the field's label as a 16px title, a Close
  button, 48px rows of 16px text, over the text colour thinned to 20%. It is as
  tall as its rows and never taller than 70% of the screen, with nothing under
  the last row but the phone's own safe area. It slides up in 220ms. A swipe
  down on its head, Close, the backdrop, Escape or the back gesture closes it.
- **A row can carry a line under it**, from its option's `data-description`:
  15px, muted, regular weight. The option is named by its label and described
  by the line, so a screen reader says "Teacher" and then what a teacher does.
  The staff invite uses it for roles (`accounts.models.ROLE_DESCRIPTIONS`,
  each line held to the role sets that grant it by
  `accounts/tests/test_role_descriptions.py`). The system menu shows labels
  only.
- **More than eight options gets a search box** that filters as you type,
  ignoring case, accents and extra spaces, and says how many match. On a desk
  it takes the keys at once; on a phone it waits to be tapped, so the keyboard
  does not cover the list before anybody asked for it.
- **Groups** are the select's own `<optgroup>`s, drawn as headings.
  `classOptions()` in `web/classes.js` groups a long list of classes by level
  (the roll's two class pickers).
- **The keys** are a select's: Enter, Space, the arrows or a letter open it;
  the arrows, Page Up and Down, Home and End move; a letter jumps to the next
  row starting with it; Enter or Space chooses; Escape and Tab close without
  choosing. Focus goes back to the field, and the row the keys are on carries a
  2px One Blue ring.
- **Screen readers** hear a listbox named by the field's label, with
  `aria-activedescendant` on whichever of the list and the search box has
  focus, options marked selected or unavailable, and groups named by their
  heading.
- **The `<select>` stays the field.** It is what its label names, what the
  form submits, what a required field's message points at and what a disabled
  field is; the picker only takes over its opening, writes the choice back,
  and fires `input` and `change`, so a page's own listeners are unchanged.
  `picker.css` draws the select itself (white, a rule, a chevron, red when it
  is invalid, grey when it is disabled), so a page with no script, or whose
  script failed, shows the same field opening the system menu.
- **It is an enhancement.** Each page loads it with `import()` beside its own
  module, so a picker that fails to load leaves the page drawn and each select
  opening the system menu, and `web/classes.js` does not import it.
- **Only the pages that draw a select carry it.** `tests/test_pages.py` fails a
  page whose modules draw a `<select` and do not start the picker on its root,
  and `tests/test_budget.py` a page that loads the module without its
  stylesheet. The chevron is `web/chevron.svg`, in `--muted`.
- There is no dark mode in this design; under `forced-colors` the select is
  the system's own and the picker's ring is `Highlight`.

`tests/ui/picker.test.js` opens it on a phone and a desk, photographs it, walks
its keys, and checks that every page with a select still sends what was
chosen, at two schools.

## Dates

Every date is day first. Shown: "8 Nov 2026" (`dayFirst()` in `web/html.js`),
never `11/08/2026`; stored values stay `yyyy-mm-dd`. Entered: `web/dates.js`
turns each `<input type="date">` (and `datetime-local`, which adds a time box)
into **one line** and a calendar sheet, and the native input stays the field
(name, value, `required`, `min`, `max`), drawn out of sight; the browser's own
box would show `mm/dd/yyyy` on a phone set to US English, and `lang` does not
change that. There are no selects for a date.

- **The line** is a button: "Today, Thu 12 Nov" (Today, Yesterday and Tomorrow
  are said; any other day is "Wed 4 Nov 2026"), with a calendar icon. "Today"
  is the school's day (`data-time-zone`, else Lagos), as the register's is.
- **Chips.** `data-dates="recent"` adds "Today" and "Yesterday" chips under the
  line, for a date near today: the register's day and a payment's date. A chip
  outside `min`/`max` is greyed out.
- **The sheet** is a branded bottom sheet on a phone (the picker's handle,
  title and close button; swipe-free, Escape or the backdrop closes it) and a
  popover under the field on a desk. It is a month calendar, Monday first:
  the chosen day is navy, today is ringed, month arrows move on. A field with
  `min`/`max` (the register's, bound to the current term; a payment's, up to
  today) greys out the days outside it: they are `aria-disabled` and cannot be
  chosen, and an arrow that would leave the range is disabled too. There is no
  year list.
- **Date of birth** (`data-dates="birth"`) is the one field that needs other
  years: Year (newest first), then Month, then Day, with the year and month
  above the days to go back to.
- **Keyboard and screen readers.** The sheet is a modal dialog named for the
  field; the days are a `grid` of buttons with their full date as the name,
  `aria-selected` on the chosen one and `aria-current="date"` on today. Arrows
  move by a day or a week, Home and End to the week's ends, PageUp and
  PageDown by a month (with Shift, a year), Enter and Space choose, Escape
  closes and gives focus back to the line. Days are 44px tall and the sheet
  fits 320px and 200% text.
- A page that draws a date field loads `web/dates.js` and `web/dates.css`
  (`docs/module-notes.md` says where the long comments of the shared modules
  went, to keep every page under 150 KB). Without them the native input shows.

## Fees list and setup

- **The fees list** is `.list-rows` in ONE white card: the class in bold, "25
  children" muted under it, the amount collected with a bar and "% collected"
  (or "Not billed") at the right, and a chevron. Each row is the button that
  opens the class, as before. `GET /api/fees/classes/` carries `collected_kobo`
  and `billed_kobo` per class, reckoned as the dashboard does.
- **Setup** is stacked cards, one per section (`.setup-card`, `setup/cards.css`),
  each under its own heading, 16px apart. Forms are unchanged.

## What holds it

- `tests/test_design.py`: the palette is the whole palette and lives in one
  file. It also checks that the three gradients are the only ones, and for emoji and icon packs, the font's two
  weights, and that every page includes the head.
- `tests/test_budget.py`: every page stays under 150 KB with its fonts and
  modules, uses no CDN and no package, and keeps a pinned query count.
- `tests/ui/screens.test.js`: every page in Chromium at the three widths. It
  checks sideways scrolling, target sizes and phone text sizes, and
  photographs each page. CI's `screens` job runs it against the demo and
  uploads the photographs as the `screens` artifact.
  `tests/ui/specimen.html` is where the shell and the parts no page uses yet
  are drawn and measured.

To run the screens locally, do what the `screens` job does: seed the demo
under `PLATFORM_DOMAIN=classnode.test` with `DJANGO_DEBUG=1` (`seed_demo`, then
`seed_ui`), serve it on port 8000, install `playwright` outside the repository's
dependencies, then run `npm run screens`. The photographs go to `SCREENS_OUT`
(default `screens/`).

The files in `tests/ui/` run side by side, one process each, against that one
demo, so **no two of them share a class**: `seed_ui` gives each file that writes
a class and children of its own in Sunrise (UI Offline, UI Marking Clear, UI
Marking Focus, UI Import, UI Teaching), `screens.test.js` keeps `seed_demo`'s
JSS 1A and JSS 1B, and every file names its class and its paper rather than
tapping "the first". `schools/tests/test_seed_demo.py` (`SeedUiTests`) fails if
two files name the same class. Before this, `offline.test.js` failed now and
then: `roll_import_gap.test.js` admitted three children into the class whose
register it was taking on a phone, between the phone's copy and the send, and
the register was held for review.

## Order of work

1. The tokens, the shared parts, and the shell (this file's first change).
2. The pages by role, one change each: sign-in and parent; teacher;
   principal and vice principal; bursar; admin.
3. The report card PDF last. It leads with the school's crest and colour,
   with Classnode only as a small footer, and shows no class position or class
   average.

## The dashboard

`/home/`, every staff role's first screen (`docs/dashboard.md` says what is on
it and who sees what). Its stylesheet, `static/home/dashboard.css`, opens with
its own tokens, and nothing in it uses a size, a gap or a radius that is not
one of them:

- **Type:** six sizes and no more: 12px (small uppercase labels), 13px
  (chips), 15px (secondary lines), 16px (body and card titles), 20px (the
  greeting on a phone) and 28px (KPI figures; the greeting on a desk). Every
  figure is tabular.
- **Space:** an 8px scale (8, 16, 24, 32), with 4px as its half step.
- **Radii:** design.css's: 16px on cards, 20px on the hero, 12px on controls.
- **Cards:** no border, `--shadow-1` resting, `--shadow-2` when a tile is under
  the pointer. 150ms ease on every change of state, and none under
  `prefers-reduced-motion`.
- **Figures that lead** (the hero's amount, the stat cards') are 800, tight and
  tabular; the face is declared at the top of `dashboard.css`.
- **Colour:** white and greys, One Blue for figures that lead and for actions;
  green, amber and red only on status chips, and a chip always carries an
  icon and a word. A change note ("+14 this term", "−2 this week") is
  neutral grey: down is not always bad.
- **Drawings** are inline SVG written by the server (`home/charts.py`): a
  sparkline, a meter and five bars. No chart library, no gradient.
- **On a phone:** the hero full width with Outstanding and Expected side by
  side, the stat cards three across (label and figure; the line under each is
  kept for a screen reader), one chip line in the header, nothing scrolls
  sideways, every target 44px.
- **Icons** only the dashboard draws live in `home/templates/home/parts/icons.html`,
  so other pages do not carry them.


## design.css, part by part

The notes that used to sit beside the rules in `static/web/design.css`, moved here because that file goes to every phone on every page and `tests/test_budget.py` counts its comments in each page's 150 KB. Each is keyed by the selector it explains.

- **`(the rule below)`**: The blue, lighter and darker, for hover, the active nav item and bars. Mixed from the one colour rather than named as another.
- **`(the rule below)`**: A field's edge has to be visible against white (3:1), which --border is not. It is the secondary text colour, thinned.
- **`(the rule below)`**: Resting and lifted, each a tight edge and a wide faint lift: the text colour, thinned. A card has no border; the edge shadow is its edge.
- **`body > main`**: A page without the app shell — the sign-in doors, the card, and every staff page until its role is restyled — is one white card on the grey. Each page's stylesheet gives it a width; this gives it everything else.
- **`button, .btn`**: Every button is at least a finger tall. The plain one is white with a rule; a form's submit is the page's primary action and is the blue. Inline-block rather than flex, so a page's full-width, left-aligned list buttons (the register's names, the marking sheet's classes) keep their alignment.
- **`button.signout, button.again, .btn-quiet`**: The quiet ones: sign out, try again. Not what the reader came to do, so they do not compete with what is — but still a whole target.
- **`.switch-door`**: The way back from the wrong door: `signin.js` and `staff-signin.js` each carry one, to the other. Quiet and last in the form, because a stranger who opened the right door never reads this far.
- **`input[type="file"]`**: A file field's "Choose file" is the secondary button: white, a rule, a finger tall. The rest of the input is the name of the chosen file. Shared by the crest on Setup and the roll import.
- **`:is(.label-ok, .label-warn, .label-stop, .label-brand, .pill):not(:has(.icon))::before`**: A pill says its meaning with a dot or an arrow, never colour alone and never an emoji: a status label without an icon of its own gets the dot.
- **`.eyebrow`**: The small uppercase label over a figure or a group. 12px, bold, spaced, in the secondary grey (5.9:1 on white, 5.3:1 on the page).
- **`.scroll, .grid-scroll, .table-scroll`**: A table wider than its card scrolls sideways **inside** it; the page never does. The first column — the child, the class, the day — stays put while the numbers move under it, so a row can still be read at 360px.
- **`.swipe-cue`**: Below 640px a list table (`table.stack`) is a stack of cards, one per row, each cell a "label  value" line from its `data-label`; `.stack-list` is the same for a `ul`. `stack-head` heads the card, `stack-full` is a block under it, `stack-hide` is left out. Only `.wide` tables scroll sideways. The whole rule, and why, is `docs/design.md`'s ("Widths").
- **`(the rule below)`**: No gap between the parts of a value ("13" and "/20"); the label keeps its distance with its own padding.
- **`table.stack td > small`**: A value's second line (a term under a charge, a teller number under a method) stays a second line, under the first.
- **`.msg`**: A message is neutral: white, a rule, the sentence in body text. What kind of message it is rides on a small label at its start — `<div class="msg"> <span class="label label-stop">Not saved</span> <p>…</p></div>` — so status colour stays on labels, where the rules put it.
- **`.list-rows`**: `<ul class="list-rows">` in a card: each `li > a.list-row` is a tinted icon tile, a bold title over a muted line, whatever the row ends with (a pill), and a chevron. The dividers start where the text does. `.list-row-icon.tone-warn` and the rest tint the tile by meaning.
- **`.state-loading`**: Every page's first state, `<p class="state state-loading">Loading…</p>`, until its module's first fetch answers: the sentence, muted, over the shape of a card, so a slow connection shows a page arriving and not a bare line.
- **`.brand-bar`**: Sign-in, the card index, a report card, the checker: pages with no shell. `.logo` is the shell's own mark, reused, and not a link: these pages have nowhere to send a reader back to (`results/views.py`).
- **`body.has-shell`**: A white sidebar, a white top bar, the work on the grey. Below 1024px the sidebar is a `popover` from the menu button: light dismiss, Escape and focus return with no script, and shown above the page where unsupported.
- **`.logo-mark`**: `i-brand-mark`, not a generic stroke `.icon`: it is drawn filled, in the square-and-`.logo`'s own colour plus white, not stroked in `currentColor` alone — see `templates/design/icons.html`.
- **`.nav .nav-button`**: Sign out is a form's button, drawn as one more nav item: not the page's primary action, so none of a submit button's blue.
- **`.sidebar .nav-links`**: Sign out sits at the foot of the sidebar and never scrolls out of it: the links above it take the height that is left and scroll inside themselves. A phone held in landscape is shorter than a principal's list of links, and a Sign out below the fold is one nobody finds on a shared handset. The padding and negative margin keep a focused link's ring inside the box that clips it.
- **`.shell::before`**: The sidebar is a screen tall and stays put; this is the white column behind it, so a long page does not run out of sidebar below the fold.
- **`body.has-tabbar .content`**: The bar's own height: the last control clears it. The gap under the floating bar, and the phone's safe area, are the shell's foot.
- **`@font-face`**: Noto Sans draws only the Hausa hooks Hanken has no drawing of (`scripts/fonts.py`).
- **`(the rule below)`**: The portal's page: a soft blue-grey the white cards stand on.
- **`(the rule below)`**: A card asking the reader to act: the lightest amber.
- **`(the rule below)`**: The spacing scale. More space between groups than inside them.
- **`(the rule below)`**: the phone tab bar's height; the page's foot padding is the same
- **`(the rule below)`**: the floating bar's distance from the screen's edges
- **`(the rule below)`**: The header's hairline, under it rather than a border.
- **`button:not(:disabled):active, .btn:active, .press:active`**: A press is felt, not seen as a jump: a touch smaller while held.
- **`.field`**: A labelled field, one above the other: `<label class="field">Name <input></label>`.
- **`.figure`**: A figure that leads: big, tight, every digit the same width.
- **`.card-action`**: A card that asks the reader to do something: the lightest amber.
- **`a.card`**: A card that is a link: lifts under the pointer, gives a little when pressed.
- **`thead th`**: A column's name is a label, from a tablet up; on a phone it stays 15px.
- **`table.stack tr > td:only-child`**: A row with no head (a form opened under the row it acts on) starts clean.
- **`table.stack tfoot tr`**: A total is one line: what it totals, and the figure.
- **`table.stack :is(th, td):first-child`**: Out of the scroller's sticky column: a card has no column to pin.
- **`.problem`**: The notes pages already draw, until each is moved onto `.msg`.
- **`.empty-card`**: An empty list (`emptyState()` in `web/html.js`): what is missing, one button.
- **`.door-foot`**: Under a door's card: "Powered by Classnode" on a school's own host.
- **`.crest`**: The school's crest; its initials on the school's own ground until one is uploaded.
- **`.crest:has(img)`**: A crest is drawn whole, on white: a shield is not cropped to a square.
- **`.logo-school`**: The school's crest and name where Classnode's mark is on the portal.
- **`.nav .powered-by`**: "Powered by Classnode", under Help on a school's own host: small and quiet.
- **`.sidebar .nav-help`**: Help and next steps, above Sign out inside the same rule.
- **`.setup-chip`**: The administrator's setup chip (`onboarding`): a 36px pill, a 44px target.
- **`(the rule below)`**: White, a little see-through over what scrolls under it, and a hairline.
- **`.split`**: Two columns on a desktop — the work and a side panel — one on a phone.
- **`.sidebar[popover]`**: Below 1024px: the sidebar slides out, and the bar grows a menu button.
- **`(the rule below)`**: The visible height, so a phone's own toolbar does not cover the foot.
- **`.sidebar,`**: Out of the popover and into the page: always there, never on top.
- **`.tabbar`**: Below 640px staff pages also get a tab bar: the role's four main screens.
- **`.tabbar`**: A floating bar, clear of the screen's edges, the lifted shadow under it.
- **`.tabbar .icon`**: The tab you are on: a soft pill of the brand colour behind its icon.
- **`.card, body > main, .empty-card, .tabbar, .account-menu, .topbar,`**: With no shadows to draw them, the cards and bars get a hairline.
