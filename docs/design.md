# The design: "One Blue"

Every page draws from one stylesheet, `static/web/design.css`, included through
`templates/design/head.html`. A page's own stylesheet holds its layout and
nothing else: no page declares a colour.

## The rules

- **One brand colour, `#143D8C`**, for buttons, links, the active nav item and
  the logo. Text `#0E1726`, secondary text `#5B6475`, background `#F5F6F8`,
  cards `#FFFFFF`, borders `#E3E6EB`, row dividers `#EEF0F3`. No other accent,
  no gradients. Lighter or darker is the same blue mixed (`--brand-tint`,
  `--brand-strong`), not a second colour.
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
- **Radii** 10px on buttons and fields, 12px on cards. **Buttons** are 44px
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
- **No em dashes in rendered UI copy.** A colon, a comma or a full stop
  instead. Code comments and docstrings are prose and keep writing however
  they already do — this is about what a reader sees on the page. The one
  exception is an em dash used as a placeholder for "nothing to show" (the
  broadsheet's `DASH`, a session table's default) — that is data, not a
  sentence, and stays.

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
- Stat cards run four across on a desktop, two on a tablet, one on a phone.
- A wide table scrolls sideways inside its card (`.scroll`, `.table-scroll`),
  with its first column fixed. The page itself never scrolls sideways.
- Forms and side panels (`.split`) stack into one column on a phone.
- Touch targets are at least 44px. Body text on a phone is never under 15px.

## What holds it

- `tests/test_design.py`: the palette is the whole palette and lives in one
  file. It also checks for gradients, emoji and icon packs, the font's two
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
under `PLATFORM_DOMAIN=classnode.test` with `DJANGO_DEBUG=1`, serve it on port
8000, install `playwright` outside the repository's dependencies, then run
`npm run screens`. The photographs go to `SCREENS_OUT` (default `screens/`).

## Order of work

1. The tokens, the shared parts, and the shell (this file's first change).
2. The pages by role, one change each: sign-in and parent; teacher;
   principal and vice principal; bursar; admin.
3. The report card PDF last. It leads with the school's crest and colour,
   with Classnode only as a small footer, and shows no class position or class
   average.
