# Module notes

Long comments that used to head the shared page modules, moved here because every
page ships those files and `tests/test_budget.py` counts their comments in its
150 KB (the same move `docs/design.md`, "design.css, part by part", made for the
stylesheet). The code keeps a one-line summary.

## `web/html.js`

- **Escaping.** These modules build strings for `innerHTML`, so **every
  interpolated value goes through `esc()`**. Names and remarks are typed by a
  school, and a remark reading `<img src=x onerror=...>` would otherwise run in
  a parent's browser. Strings rather than DOM nodes keep the renderers pure
  functions that `node --test` can check with no DOM, no dependency and no build
  step.
- **`dayFirst(iso)`.** A stored day (`2026-11-08`) as a reader says it, day
  first: "8 Nov 2026". Never `11/08/2026`, which half the school would read the
  other way round. Anything that is not a real day comes back as it was, so
  nothing is hidden.
- **`keepTogether(text)`.** `typography.py`'s rule for a module: the spaces
  inside a class name ("JSS 1A"), a date ("Fri 20 Nov", "20 Nov 2026") and an
  exam PIN ("0105 7149") become non-breaking (U+00A0), so a 320px phone with
  its font turned up wraps the sentence around them and never inside them
  (`docs/phone-width-sweep.md`). A whole weekday ("Monday") may still end a line
  before its date. For words a person reads only: never a value a form sends
  back or an attribute a script matches. `dayFirst()` returns its date held the
  same way.
- **`numberOrBlank`.** A number that may legitimately be nought, rendered
  without lying about it: `0` and `null` are different answers (present on no
  day, versus no register kept), and `value || fallback` would print the
  fallback for both.
- **`waitInWords`.** Shared because both sign-in doors answer 429 with the same
  `retry_after` and must round it the same way: whole minutes once seconds read
  as false precision, and `""` when none was sent.
- **`hostHref`.** Scheme-relative (`//host/path`): every caller links to a host
  other than its own, so a bare path would 404, and a fixed `https://` is wrong
  in development. `""` for a school with no host, and each caller says what to
  show instead. `pathOnly` (the API's `path_only`, the single-host demo) is the
  path alone. The host is a school's typing, so it is escaped here.
- **`emptyState`.** Drawn only from a successful answer with no rows: a failed
  fetch has its own states.

## `web/http.js`

- The CSRF token comes from `GET /api/csrf/`, not from `document.cookie`:
  reading the cookie depends on `CSRF_COOKIE_HTTPONLY` staying false and puts the
  cookie's name in the browser. It is fetched once and reused; a 403 with
  `code: "csrf_failed"` means it is stale, so the write fetches a fresh one and
  retries **once**, not until it works.
- `getJson` throws only if the transport does: an HTTP refusal is an answer the
  caller has something to say about.
- `same-origin` credentials send the session cookie and keep every POST on its
  own host, so `CSRF_TRUSTED_ORIGINS` is never widened.
- `putJson` is the register write, a PUT because there is one register per group
  per day (`attendance/api.py`). It shares `sendJson()` so the retry-once rule
  has one copy.

## `web/portal-app.js`

The installed app's page script, loaded by the menu's shell (`docs/pwa.md`): ask
for the portal's worker, and run the "Install app" button. It imports nothing,
so it needs no place in a page's import map. Sign-out is the worker's
(`sync/worker.js`). Nothing here lists or unregisters workers or touches a
cache: `/sit/` keeps its own. Android raises `beforeinstallprompt`; iPhone has no
such event, so the button opens the how-to instead. Opened from the home screen,
neither shows.

## `tests/states.js`

- Before `import { esc } from "../web/html.js";`:

  Every screen the Tests page can show, as a pure function of what the school sent.
  
  Strings rather than DOM, for `exam-slips/states.js`' reason: `node --test` can assert
  each one with no browser. Every interpolated value goes through `esc()`: a question is
  plain text a teacher typed, and it is shown as text, never as markup.
  
  What is **not** here is any authority question. A button is drawn only where the
  school's answer says this login may press it (`may_write`, `may_approve`, ...), and
  every route refuses anybody else on the server. The administrator's list has no
  question in it because the school sends none.


## `tests/app.js`

- Before `import * as api from "./api.js";`:

  Tests: question banks, setting a test, and the principal's approval.
  
  One page, routed by its hash so the browser's Back works and a link can be shared:
  `#` the tests, `#banks`, `#bank/<subject>/<level>`, `#question/<subject>/<level>/<id|new>`,
  `#new-test`, `#test/<id>`, `#edit-test/<id>`, `#preview/<id>`, `#sitting/<id>`. Each view asks the
  school afresh, so what is drawn is the school's own answer, and every write redraws
  from what the write answered.


## `tests/api.js`

- Before `import { csrfToken, getJson, postJson } from "../web/http.js";`:

  The fetches the Tests page makes: banks and their questions, a question's picture,
  tests and the chain that approves them, and the preview of a paper.
  
  Every write answers with the thing written, so the page redraws from the school's
  own answer. A refusal is one of `REFUSAL` for the page, or a sentence (`rejected`)
  the form says beside itself.


## `fees/app.js`

- Before `import {`:

  Fees: the classes for a term, a class's balances, one child's account, a
  payment, an undo and a receipt; and (B2) each class's bill, charging the
  class, and a child's concessions.
  
  `?student=` opens an account and `?receipt=` a receipt directly, which is
  how a reprint is reached from a bookmark.
  
  **The form key.** Each payment form and each discount form drawn gets a
  fresh key (`crypto.randomUUID()`), sent with what was typed. The server
  records one entry per key, so a double click is one payment or one discount.
  When the answer is lost — the connection dropped after the request left —
  the page keeps the key and what was typed, and says so: sending it again
  cannot record it twice. A concession's grant form works the same way.
  
  **A bill is redrawn from the server's answer** after every change, because
  each bill write answers with the bill as it now stands.

- Before `export function classAccountsNote(result) {`:

  What one press of "Create accounts for this class" did, in words: how many were made,
  how many already had one, each failure by name with its sentence, and how many are
  left. `tone` is "done" only when nothing failed and nothing stopped it.

- Before `const billWrite = async (answer, { draftField, draft, done, lost }) =>`:

  A bill write: the answer is the bill, drawn as it comes back. A lost
  answer keeps what was typed and says, in `lost`, why sending again is
  safe for that write.
  
  **A 404 here is a line that is no longer there** — another bursar removed
  it, or this page's own removal landed and its answer did not. The bill is
  read again rather than the page turned into "not something you can
  open": if the refusal is real, that read gets it too.

- Before `const keys = { payment: newKey(), discount: newKey(), conces`:

  One key per form, because each form is its own write: a payment, a
  discount and a concession sent under one key would be refused as a
  reused form.

- Before `const [answer, notSent] = await Promise.all([`:

  The reminders that went nowhere are listed under the classes (D10, as
  decided). Asked beside the books, and a failure there leaves the books.

- Before `land(answer.ok && !concessions.ok ? concessions : answer, (b`:

  One refusal for both: the routes ask the same question of the same
  person, so the first read's answer stands for the pair.

- Before `const keyed = async (intent, draft, send, { done, again, dra`:

  A write made under a form key: a payment or a discount. Success mints the
  next key; a lost answer keeps it, and what was typed, so sending again is
  safe; a sentence from the server keeps what was typed and shows it.

- Before `again: "We could not tell whether that payment was saved. Se`:

  The request may have landed. Same key, same payment: sending it
  again records it once whichever way the first one went.

- Before `const scope = {`:

  Asks first (docs/messaging.md D10): the preview writes nothing, and
  nothing is sent until "Send them".


## `fees/states.js`

- Before `import { dayFirst, emptyState, esc } from "../web/html.js";`:

  Every screen the fees page can show, as a pure function of API bodies.
  
  **Each form names its intent** in a hidden field, and `app.js` dispatches on
  that rather than on which fields a form happens to have: a payment and a
  discount both have an amount, and a discount and a reversal both have a
  reason.
  
  **Every number is the server's**, in kobo, and `money.js` is the only thing
  that turns one into naira. A balance is said in words — "owes", "in
  credit", "nothing owed" — never left to a minus sign.
  
  **A receipt says what the entry recorded**, and says across its face when
  the payment has since been undone.
  
  **A bill is a template (B2).** Beside every line it says how many children
  that line has charged, because changing the line does not change them, and
  a line that has charged anybody cannot be removed. Charging the class says
  what it did, including who it did not charge and why.
  
  **A revoked concession stays on the account**, with who revoked it, when
  and why — issue #75. Nothing about a concession is ever edited.

- Before `function remindingBox(reminding) {`:

  The question "Remind families" asks before it sends anything: the server's
  preview, which children, who will be sent it, and how many messages. The
  amounts are the whole account, as the class page shows them. With nothing to
  send there is nothing to confirm, only a box to close.

- Before `function paymentForm(body, { termId, today, draft = {} }) {`:

  `draft` is what was last submitted, drawn back in when the answer was not a
  success — so a bursar corrects one field rather than typing the payment
  again, and a retry after a lost answer resends the same payment under the
  same form key.

- Before `function discountForm(body, { termId, draft = {} }) {`:

  A discount given by hand, for one term, with its reason. Behind a button
  rather than always open beside the payment form: waiving money is rarer
  than taking it, and a form a bursar tabs into by accident is how it would
  happen by mistake. `draft` as for a payment.

- Before `function classRow(c) {`:

  One class as a list row: name over "25 children", what has been collected
  with a bar and its share at the right, and a chevron. A button, so the page's
  one click handler opens the class as it always did.

- Before `const owes = c.owing`:

  What the class owes, all terms (audit G-12), on a line of its own: the
  sub-line stays the count alone.

- Before `export function outstandingLine(body = {}) {`:

  "Outstanding (all terms)" and "of which this term", the figures the dashboard
  shows (`fees.outstanding`, audit G-12): the whole account of each child placed
  this term who owes. Nothing when nobody owes.

- Before `function notSentSection(notSent, mayRemind, reminding) {`:

  Reminders that went nowhere because the account moved before they were
  sent (decided 2026-09-25): the amount they would have stated was no longer
  true. Listed so the bursar can send again, with the account as it stands.



## `fees/api.js`

- Before `import { deleteJson, getJson, postJson, putJson } from "../web/http.js`:

  The fetches the fees page makes, and what each answer means.
  
  **A 404 is one answer here, on purpose.** Every read refuses a reader who
  may not see the books with a flat 404 — the same as for a child or an entry
  that does not exist — so the page says "not something you can open" for
  both and never guesses which. A 403 is different: it goes only to somebody
  who reads the books and may not write to them, and its sentence is shown.

- Before `async function write(url, payload, fetchImpl, send = postJso`:

  A write. 201 is posted; **200 is "this form had already posted"**, which is
  success too — the payment is in the books once. 403, 409 and 422 carry a
  sentence for the person and keep the page where it is.

- Before `export const makeClassAccounts = ({ classId, termId = null, `:

  Make the missing accounts for a class: a batch at a time, so the answer says how many
  were made, how many already had one, each failure by name, and how many are left.
  409 (no bank yet) and 422 (no term) carry a sentence.

- Before `export const makeAccount = ({ studentId, fetchImpl = fetch }`:

  Make the child's dedicated account. 409 (no bank yet), 422 and 503 (Paystack) carry a sentence.

- The `-- B2: bills and concessions` divider:

  Every bill write answers with the bill as it
  now stands, so the page draws what the server holds rather than patching.

- The `-- fee reminders` divider (docs/messaging.md D10):

  The preview writes nothing; the
  press answers with what it did. A 403 or a 422 is a sentence on the page.


## `fees/money.js`

- Before `/** "₦1,500,050.00" for 150005000 kobo. The magnitude only; see `signe`:

  Kobo, as a person reads naira. Never through a float.
  
  The API sends whole kobo as integers, and this formats them by cutting the
  digit string — the last two digits are kobo — so there is no division
  anywhere for binary floating point to get wrong. The sign is never dropped
  silently: a balance is said in words ("owes", "in credit") because a minus
  sign on a phone screen is the character most easily missed, and a family in
  credit being chased for money is the mistake this page must not make.


## `tests/states.js`

- Before `export function questionForm(bank, q, { detail = "", values = null, co`:

  The question form. `q` is the saved question being edited, or null for a new one;
  `values` is what the form holds now, when it is drawn again mid-edit (a picture
  added, a fifth option asked for), so nothing typed is lost.


## `tests/app.js`


## `tests/api.js`

- Before `export async function uploadPicture({ subjectId, level, file, fetchImp`:

  A picture for a question, as multipart. Not `postJson()`, because the body is a file;
  the CSRF rule is `web/http.js`'s all the same, with one retry on a stale token.


## `tests/states.js`


## `tests/app.js`


## `tests/api.js`

## `setup/states.js`

- **`conductSettings()`.** The affective and psychomotor sections: a switch, a
  trait list and the 1 to 5 scale's words. The principal's and the
  administrator's, and only theirs: the server sends this block to nobody else.

  **Off hides, it does not delete.** The switch's sentence says so, because the
  question a principal has is whether the ratings are gone. And every sentence
  about a card already sent says it keeps what it showed: that is the promise
  the whole section is built on, and the screen is where it is made.

  A trait is never deleted, only hidden: a hidden one stays in the list, muted,
  with a button to show it again, because ratings and released cards still name
  it.


## `fees/fees.css`

- Before `main { max-width: 60rem; }`:

  Fees. Tables that scroll sideways on a phone, and a receipt that prints on
  its own: the chrome is hidden on paper.
  
  Colours, type, controls, tables and labels are `web/design.css`'s; this is
  the layout.

- Before `.class-card { padding: var(--sp-8) var(--sp-16); margin: var`:

  The classes: list rows (design.css's .list-rows) in ONE card; a row is a button that opens the class.

- Before `.class-card { container-type: inline-size; }`:

  A card too narrow for the class's words and its amounts side by side (a
  small phone, large text): the amounts go under the words, never over them.

- Before `.reminding { margin: 0.75rem 0; padding: 0.75rem 1rem; borde`:

  Fee reminders (docs/messaging.md D10): the question before sending, and the
  ones the account moved under.


## `fees/log-app.js`

- Before `import { esc } from "../web/html.js";`:

  The fee log page (`/fees/log/`): a term's entries, newest typed first, or
  with `?reversals=1` its reversals, fifty to a page. It draws with the fees
  page's own entry table (`states.entryTable`), so a reversed payment reads the
  same here as on the child's account: marked Reversed, with the reason, who
  and when. It reads only; nothing on it changes the books. A child's name
  links to their account on `/fees/`.
