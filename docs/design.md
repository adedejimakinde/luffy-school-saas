# The design: "One Blue"

Every page draws from one stylesheet, `static/web/design.css`, included through
`templates/design/head.html`. A page's own stylesheet holds its layout and
nothing else: no page declares a colour.

## The rules

- **One brand colour, `#143D8C`**, for buttons, links, the active nav item and
  the logo. Text `#0E1726`, secondary text `#5B6475`, background `#F5F6F8`,
  cards `#FFFFFF`, borders `#E3E6EB`, row dividers `#EEF0F3`. Lighter or darker
  is the same blue mixed (`--brand-tint`, `--brand-strong`; the public site
  mixes its own deeper blues and a wash in `website.css` the same way), not a
  second colour.
- **Three accents, on the public site's icon tiles only**: teal `#0F766E`,
  amber `#B45309`, coral `#C2452D`, each with a white icon at 5:1 or better.
  Never for words.
- **Four gradients and no others**, each of One Blue: the public site's final
  band, One Blue deepening; on its light top band, the faintest blue along the
  hero photo's top edge and a faint glow behind its screens; and the staff
  sign-in's background, One Blue fading into the grey from the top.
  `tests/test_design.py` names them.
- **Status colour only on small labels** (`.label-ok`, `.label-warn`,
  `.label-stop`): green `#16693F` on `#E7F4EC`, amber `#8A5A00` on `#FDF1DC`,
  red `#B42318` on `#FDECEA`. A message is neutral and carries its label
  (`.msg`).
- **Hanken Grotesk**, self-hosted in `static/web/fonts/`, Latin only, 400 and
  700 only, `font-display: swap`, the system stack behind it. It has no naira
  sign, and the system font draws that one glyph. The files are static
  instances cut from the family's variable font (SIL OFL 1.1, `OFL.txt`
  beside them). Its digits are already equal-width, so numbers line up without
  a feature switch; tables still say `tabular-nums` and right-align them
  (`.num`).
- **Two shadows**, `--shadow-1` (resting) and `--shadow-2` (lifted: a card
  under the pointer, the account menu), the text colour thinned. No others.
- **Radii** 10px on buttons and fields, 12px on cards. The dashboard draws its
  controls at 8px (below). **Buttons** are 44px
  tall, and the primary action is 48px.
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
- **Radii:** 12px on cards, 8px on controls.
- **Cards:** a 1px border in `--border`, `--shadow-1` resting, `--shadow-2`
  when a tile is under the pointer. 150ms ease on every change of state, and
  none under `prefers-reduced-motion`.
- **Colour:** white and greys, One Blue for figures that lead and for actions;
  green, amber and red only on status chips, and a chip always carries an
  icon and a word. A change note ("+14 this term", "−2 this week") is
  neutral grey: down is not always bad.
- **Drawings** are inline SVG written by the server (`home/charts.py`): a
  sparkline, a meter and five bars. No chart library, no gradient.
- **On a phone:** tiles two by two, everything else full width, one chip line
  in the header, nothing scrolls sideways, every target 44px.
- **Icons** only the dashboard draws live in `home/templates/home/parts/icons.html`,
  so other pages do not carry them.

