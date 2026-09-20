# The report card page

The pages a family opens. Code: `results/views.py`, the two `cards/` routes in
`urls.py`, `results/templates/results/card_page.html` and `card_index.html`,
the modules and stylesheets in `static/card/`, `static/index/` and
`static/web/`, the import map in `pages.py`, the static settings in
`settings.py`, `whitenoise` in `requirements.txt`, and tests in
`results/tests/test_card_page.py`, `results/tests/test_card_index_page.py`,
`tests/test_pages.py` and `tests/js/`. Signing in is
[sign-in-page.md](sign-in-page.md). The payload it renders is
[parent-access.md](parent-access.md) and [cards.md](cards.md); the same card as
a file is [report-card-pdf.md](report-card-pdf.md).

## The server sends a frame with no card in it

`card_page()` takes two integers out of the URL, puts them in a `data-`
attribute and returns. It does not look the child up, does not check the term
exists, and does not ask whether the caller may read anything — because there is
exactly one answer to "may this person read this card" and it lives in
`card_api._require_may_read()` and `_require_servable()`. A view that rendered
the card server-side would be a second place asking that question, and the day
the two disagreed the wrong one would be the one nobody had tested. That is the
same argument `card_api` makes for one payload assembly rather than two, and
that `report-card-pdf.md` makes for the file.

Two consequences follow, and both are deliberate.

**The shell is public.** An anonymous visitor gets the frame, the frame asks the
API, the API answers 401, and the page renders its "please sign in" state.
`login_required` here would also turn the URL into an oracle — a redirect for a
stranger and a page for a parent tells the stranger the URL is real.

**The ids are not validated.** `<int:...>` is the whole of it. A shell that
404'd for a membership id that does not exist would answer "does this child
exist" by itself, in front of an API whose flat 404 exists to refuse exactly
that question. The tests assert the two frames are byte-identical once each
one's own ids are substituted out.

The page's title is "Report card" and not the child's name, for the same reason:
the document is served before anybody is authenticated, and a tab title, a
bookmark and a browser's history all keep it.

## It is served from the school's own host, for the cookie

The page is mounted in `urls.py`, the tenant urlconf, so it is on
`st-marys.example.com` beside the API it calls. A frame served from the portal
calling a school's host would be a cross-site request and the session cookie
that authenticates a parent would not be sent with the fetch. Same host, same
cookie, no CORS and no preflight.

`urls_public.py` reuses `urls.py`'s patterns wholesale — "a route added there
cannot go missing here" — so the page is mounted on the portal as well. That is
a dead frame rather than a leak: the shell carries no card either way, and the
API on the public schema has no card to answer with, so the page settles in its
"no report card here" state. `ThePortalServesAFrameThatCannotWorkTests` pins
that rather than leaving it to be discovered.

## The client renders and computes nothing

`card_payload()` sends `columns` — the header in print order — and, on each
subject line, `cells`, already aligned to those columns with `null` where the
subject has no such paper. `render.js` walks the two lists in the order given.
It does not sort, group, match or pad.

That is the third time this decision has been made and the reasoning has not
changed. The alignment used to live in the PDF renderer; PR #117 moved it into
`card_payload()` so the page and the file could not disagree. Having the browser
derive its own columns would have put a third copy of the rule in the layer with
the least coverage, and the day it disagreed with the PDF a parent would hold
two documents that print the same mark under different headings.

The cost is that `cells` is a second view of `assessments` in one payload — a
few hundred bytes, and a thing that could drift. What stops it drifting is that
one function fills both from one `card_rows()` call, and
`TheAlignedCellsAgreeWithTheAssessmentsTests` asserts every non-null entry is
the very cell from `assessments` whose column it sits under, that nothing is
dropped, and that every row is exactly as long as the header.

### Three things that must not print the same

| on the page | means |
| --- | --- |
| `·` in a cell | this subject has no such paper at all |
| `—` in a cell | the child was not marked in it |
| `0 of 60 days` | present on none of the days the school was open |

The same table is in `report-card-pdf.md`, because the file and the page have to
agree. A `null` entry in `cells` is the first; an entry whose `score` is null is
the second. The third is why attendance is tested for `null` rather than for
truth: it is nullable until Phase 2 *and* legitimately nought, and a dash where
a zero belongs tells a parent nobody kept a register when in fact their child
was never there.

A percentage is printed exactly as it arrived. It is a string because it is a
`Decimal` all the way down the server, and `Number(...).toFixed(1)` in the
browser would round the one figure a parent is most likely to check with a
calculator.

## The four states, and why they are pure functions

A card is one outcome. The others are: the school is holding this card (403,
with the contact), there is no card here (404), the session has ended (401 with
`code: session_expired`), and nobody is signed in (401 without it). The API
distinguishes the last two on purpose — `accounts/session.py` — and collapsing
them here would throw that away.

Every one of them is a function from an API body to a string, in `states.js`,
which is what makes them testable with `node --test` and no browser. They are
the paths nobody demos, and "written once, never seen again, quietly wrong" is
the normal fate of a refusal page.

Three rules they follow:

- **The withheld state prints the contact as its own line.** That field is the
  entire reason `ReportCardSettings.withholding_contact` is constrained
  non-empty: a refusal that sends a parent nowhere is the dead end the
  withholding design exists to avoid. It is not linkified, because `contact` is
  free text a school typed — a number, an address, "the bursar's office,
  mornings" — and guessing a scheme produces `tel:the bursar's office` on the
  page a parent is meant to act on.
- **The 404 state does not guess.** One flat 404 covers "no such child", "no
  card released" and "not yours", so the page says what is true of all three and
  points at the school office.
- **The broken state does not print the error.** A parent reading
  `SyntaxError: Unexpected token <` learns nothing they can act on. Same
  argument as the PDF's 202.

## Escaping is a rule with a test on it

These modules build strings and the page assigns them to `innerHTML`, so every
interpolated value goes through `esc()`. `school_name`, `student_name`, a
subject name and every remark are typed by a school into the admin: a remark
reading `<img src=x onerror=...>` would otherwise execute in the browser of the
parent reading it. A Django template escapes by default; a hand-built string has
no default, which is why the escape is named and tested rather than habitual.

Building DOM nodes and setting `textContent` would escape by construction and
was the alternative. It was not taken because it makes every renderer need a DOM
to run, and there is no DOM in `node --test` without adding a dependency and a
build step to a page whose premise is having neither.

## One static tree, because two pages share an escape rule

The assets started per-app, under `results/static/results/card/`, on the
argument that an asset belongs to the app whose page loads it the way its
template does. The sign-in page broke that argument twice over and
`settings.STATICFILES_DIRS` now names a project-level `static/` tree:

1. **Two pages share `esc()`.** Two copies of an HTML escaper is two places to
   fix an XSS, and one of them gets missed.
2. **Per-app static makes the URL space and the disk layout diverge.** The
   finders merge every app's `static/` into one `/static/`, so a relative
   `import` that is correct in a browser resolves to nothing on disk — and
   `node --test` has no finders. The premise of these pages is ES modules with
   no build step, and that premise only holds while one relative path means the
   same thing in both places.

So the tree mirrors what is served: `static/web/` for what every page shares,
and `static/card/`, `static/index/`, `static/signin/` for each page's own.
`tests/test_pages.py` walks the `import` graph from each entry point and refuses
a page whose map has a hole in it, or a module on disk that no page lists.

## WhiteNoise, and the two traps in serving assets from Django

**The middleware sits above the tenant middleware.** A stylesheet is not a
school's — it is the same bytes on thirty hostnames — so resolving a tenant to
serve one would mean a query and a `search_path` set per asset, on requests that
touch no school's data. Placed above `TenantMainMiddleware`, `/static/...` is
answered before anything asks which school this is.

**The hashed manifest is conditioned on DEBUG, and CI collects.**
`CompressedManifestStaticFilesStorage` renames every file to include a hash of
its contents, which is what makes a far-future cache header safe. It also
refuses to serve any file that is not in the manifest, and the manifest is
written by `collectstatic` — which a `runserver` and a test run have not run. So
the storage is plain under `DEBUG` and hashed otherwise, **and CI runs
`collectstatic` before the suite**, because CI deliberately runs with DEBUG off:
without that step every `{% static %}` in the template raises `Missing
staticfiles manifest entry` during the tests and the failure reads like a broken
template.

### `collectstatic` does not rewrite `import` statements

This is the one that would have shipped silently. `collectstatic` rewrites
`{% static %}` in templates and `url()` in stylesheets. It does not touch
JavaScript, so the hashed `app.<hash>.js` still contains `from "./api.js"`,
which the browser resolves to the **unhashed** copy. That copy is served, so
nothing looks broken — and the entry point is cache-busted while the four
modules behind it are not. A deploy can then pair a new entry point with an old
module out of the browser's own cache, and the symptom is a page that is wrong
for one person and fine for everyone else.

The fix is an import map, built by the view from `{% static %}` and declared
before the module script: keys are the URLs the relative imports resolve to,
values are what the storage resolves them to. Under the plain storage key and
value are identical and the map is a no-op, which is correct where nothing is
hashed. `TheImportMapCoversEveryModuleTests` reads the `import` statements out
of the source and refuses a module the map does not cover, so adding a fifth
module without listing it fails a test rather than losing its cache-busting on
the next deploy.

## The index, which is what makes a card reachable

`/cards/` on the school's host, listing every child this caller stands for and
each of their cards. It exists because both card routes are keyed on
`(student_membership_id, term_id)` and nothing this API said to a family ever
carried either number — so the card page shipped openable only by typing two
integers into a URL. An earlier version of this file called that "a deliberate
scope line and the obvious next one", and this is that next one.

Same shape as the card page: a shell with no list in it, a renderer that walks
what the API sends, and its own states. Two of those states are worth naming.

**A withheld card is listed and marked, never hidden.** `is_withheld` comes back
true for a card the school is holding over fees, and the row is rendered with a
mark and a link that still goes to the card page — where the 403 explains itself
and names who to contact. Hiding it would defeat what withholding is *for*: a
school holds a card back to start a conversation, and a card that never appears
starts none. What makes listing it safe is that the index carries no card
content at all: `ListedCardOut` has no slot for a mark, an average, a remark or
a rating.

**Two silences, told apart because they send a parent to different people.** No
children on the account is the school office's business — a guardianship nobody
recorded. Children with no released cards is nobody's fault and needs no action,
so it does not read like a problem.

Its 401 state has to link back to sign-in, which lives on the portal, so the
link cannot be relative. `api._portal_only()` settles that the *API* will not
say where the portal is — a client knows where it signed in, and having the
server answer would put the same fact in two places. So the view reads it from
the one authority there is, the `Domain` row for the public schema, and renders
it into the frame. Where no such row exists the state says its sentence without
a link, because a dead link is worse than being told to go back the way you
came.

## What is not here

**There is no print button and no PDF link.** The browser's own print command
uses `print.css`; the stored file has its own route and its own authority check.

**There is no dark mode.** A report card is a document with a paper form:
`print.css` is that form, and a second appearance would be one more thing to
keep in agreement with it for no gain to the person reading it.
