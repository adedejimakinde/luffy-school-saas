# The sign-in pages

How a guardian gets in, how a member of staff gets in, and how either gets out.
Code: `accounts/views.py`, the `sign-in/` and `staff-sign-in/` routes in
`urls_public.py`, `accounts/templates/accounts/sign_in.html` and
`staff_sign_in.html`, the modules and stylesheets in `static/signin/` and
`static/staff-signin/` with `static/web/` shared, and tests in
`accounts/tests/test_sign_in_page.py` and
`accounts/tests/test_staff_sign_in_page.py` (the shells),
`accounts/tests/test_cross_host_session.py` (the cookie) and
`tests/js/signin.test.js`, `tests/js/staff_signin.test.js` and
`tests/js/signout.test.js` (the flows). The routes behind them are
`guardian_code()`, `guardian_session()`, `sign_in()` and `sign_out()` in
`api.py`; the rules they enforce are [parent-access.md](parent-access.md) and
`accounts/signin.py`. Where the guardian page sends people is
[report-card-page.md](report-card-page.md).

## Two doors, on one hostname

Both are mounted in `urls_public.py` and not in `urls.py`, so they exist on the
portal and nowhere else — matching the routes they call, which all begin with
`api._portal_only()`. A sign-in page on a school's host would be a form that
submits into a 404, and a school's host refuses anybody without an active
membership *there*, which is the opposite of what a door needs. A parent with
children at two schools signs in once, and so does a teacher who is also a
parent somewhere else.

**Two routes and two documents, not one page with a flag.** The flows share no
step: a guardian signs in with a code on a channel the school verified and there
is no password field, while staff send an identifier and a password in one
request and there is nothing to keep between requests. A page whose form
depended on a query parameter would also be a page nobody could link to.

Both frames hold nothing: no account, no child, no school, and neither view
reads anything from the database. Both are served to whoever opens the URL,
because a page that asks for the credential that creates a session cannot
require one.

## The guardian door: four steps, because the API has four answers

There is no password step and cannot be one: a guardian signs in with a code on
a channel the school verified.

1. **The number.** `POST /api/guardian/code/`. The page does **not** say "we
   have sent you a code", and neither does the API — `guardian_code` answers
   identically for every value typed, so that a stranger cannot learn whose
   number is on a guardian record by watching the reply. A page that promised
   delivery would put that oracle back.
2. **The code.** `POST /api/guardian/session/`.
3. **Whose card is this?** The 202. One handset in a household is the normal
   case this platform is for, and the code proves the *handset*, not the person:
   two guardians on one number are two different sets of children. So the route
   answers 202 with the guardians to choose between, nobody is signed in yet,
   and the pick goes back to the same route **carrying the same code**. Dropping
   the code at that step is the bug that leaves a family stuck half-way in,
   holding a spent code — which is why a test arms exactly that and watches it
   fail.
4. **Where to.** One school and the page goes straight to that school's host.
   More than one and it asks which, on the portal, because that is the only host
   that can see all of them. `SignedInOut.schools` carries each school's primary
   host, so the page never guesses a hostname. A school with no primary domain
   is named but not linked.

Nothing is remembered anywhere but the page's own memory for the life of the
page. Deliberately not `sessionStorage`: a code left in a browser's storage on
a shared handset is a code the next person to pick up the phone can replay.

## The staff door: one step, and a landing that links nowhere

`POST /api/login/` takes an identifier and a password and answers one of four
ways — a session, a session with no school on it, one refusal, or a throttle.
**One identifier field and not three**, which is `SignInIn`'s decision rather
than the page's: asking somebody to first classify what they are about to type
is asking them to know something about our schema.

The refusal is one sentence for all four failures — no account, wrong password,
deactivated account, two accounts matching one identifier — and the page does not
improve on it. Splitting them is how a sign-in route becomes an
account-existence oracle, and a page that guessed which had happened would hand
back the oracle `accounts/signin.py` gives up.

**"Staff" is what the page is for, not what the route checks.** `/api/login/`
resolves any identifier `User.matching_identifier()` knows, so a student with a
password can sign in here too. The page is framed for staff because staff are
who needed a door and had none.

### Where it sends them, which is nowhere

The guardian flow ends by going somewhere: one school and it redirects, more
than one and it asks which. The staff flow ends by naming the schools this login
may act at, **without a link on any of them**, and that is the decision this
page turns on rather than an omission.

`/cards/` is the only page a school's host serves, and it is a *family* surface
even for staff: `card_api._children_of()` says "Never staff's roster" and answers
with the children the caller is a parent or guardian of, "which for most of them
is none". A teacher sent there reads "No children on this account… ask the school
office to add you as a guardian" — the school's answer to a question she did not
ask. Redirecting her is wrong for that reason, and a link labelled "Report cards"
is the same wrong answer with a tap in between.

**And the payload cannot tell the two apart.** `SignedInOut.schools` is
`SchoolOut` — slug, name, host — built from `user.schools()`, a distinct `School`
query carrying no role and no guardianship. The field it looks like it wants is
`roles`, and that is not the question either: `_children_of()` is `role=STUDENT`
and (`user=actor` or `guardianships__guardian=actor`), so a PARENT membership with
no `Guardianship` rows stands for nobody, and a link keyed on the role would be
keyed on the near-enough thing — rule 1's defect class. The honest field is a
per-school boolean off that same query, answerable from the public schema since
`Membership` and `Guardianship` are both in `SHARED_APPS`, and it is an API change
with its own tests rather than something to smuggle in behind a label.

So: no link is better than a link to the wrong answer. Slice 3 of
[attendance.md](attendance.md) gives this page its first destination that is a
staff destination — the register — and that is when a link rule gets a second
caller and is worth lifting into `static/web/`.

### Signed in with no school is a success, not a refusal

`user.schools()` is scoped to `ACCESS_STATUSES`, which is ACTIVE alone, so a
**suspended** member of staff and an **invited** one who never accepted both
authenticate perfectly and land on an empty list. Reading that as a failure
would tell them their password was wrong. The state names the invitation,
because for one of those two that is the whole answer and it is something she
can act on without ringing anybody.

## Signing out

`POST /api/logout/`, from every page where somebody is signed in: both family
pages on a school's host, the staff landing on the portal, and the two guardian
states that stop with a live session on the page. One rule, everywhere, rather
than a judgement made per page.

It posts to **the host the page is already on** — `/api/logout/` is mounted in
`urls.py`, which both urlconfs serve — so the portal's own route answers the
staff page and a school's own route answers the family pages. No POST on this
platform crosses hosts, which is what keeps `CSRF_TRUSTED_ORIGINS` untouched.
The route is authenticated on purpose, which is what puts it behind ninja's CSRF
check: an unauthenticated logout is a route any other origin can aim at a
signed-in teacher's browser to throw away the session they are marking with.

`logout()` flushes the session rather than forgetting the user, and the cookie
is scoped to a domain covering the portal and every school host, so **signing
out on one host ends the session on both**. A button that ended one of several
sessions would be worse than no button.

**The asymmetry in what counts as signed out is the whole of `sessionEnded()`.**
A 200 ends it, and so does a 401 — a caller whose session had already gone asks
to be signed out and is told nobody is signed in, which is a true answer to the
question. Everything else does not, including a 500 and a dead transport,
because the two wrong answers are not symmetrical: telling somebody they are
still signed in when they are not costs a tap, and telling somebody they are
signed out while the session is live is a shared handset passed to the next
person with the cards still open. So the uncertain cases keep the page as it was
and say what to do instead — close the browser, which is an action a reader can
take without us.

What is signed out is **not** `session_expired`. Signing out on purpose deletes
the cookie as well as the session, so nothing lapsed and nothing is recoverable
by trying again; `docs/membership.md` draws exactly that line, and the family
pages render the "please sign in" state rather than the "your session ended" one.

## The session has to cross two hosts, and that is proved rather than assumed

Sign-in happens on the portal; the cards are on a school's host. So the cookie
minted by the first request has to be sent with the second, and if it is not,
**every part of the flow still looks like it worked** — 200, a cookie, a
redirect — and the parent arrives unauthenticated.
`accounts.checks.session_cookie_spans_every_host` (`accounts.E001`,
`deploy=True`) refuses a deployment without `SESSION_COOKIE_DOMAIN` for exactly
that reason.

**The obvious test of this is a false green.** Django's test client is not a
browser and does not scope cookies: it keeps one jar and sends it with whatever
`HTTP_HOST` you pass. So "sign in on the portal, then GET the school host"
passes whether or not a browser would have sent that cookie.
`test_the_round_trip_proves_nothing` is kept in the suite as the control that
says so — it asserts the round trip succeeds *while* the cookie it used is one a
browser would never have sent.

What a browser uses is the `Domain` attribute on `Set-Cookie`, under RFC 6265's
domain-match rule. That is what the tests assert, in both directions: with the
setting, the domain covers the portal and the school host; without it, the
cookie is host-only and the school host would never see it. The rule itself is
written out in the test rather than implied, and arming it to always-yes reddens
the negative case — so the assertion is load-bearing rather than decorative.

Scoping is necessary and not sufficient: a school's host also has
`SchoolAccessMiddleware` in front of it, which refuses anybody without an active
membership there. So the flow is only proved end to end by asking the index for
real, which one test does.

## No CSRF setting was changed, and that was checked rather than assumed

The sign-in routes check CSRF by hand — they are the routes a caller uses before
it has a session — and want the token from `GET /api/csrf/` in `X-CSRFToken`.
`static/web/http.js` fetches it once, reuses it, and on a 403 with
`code: "csrf_failed"` fetches a fresh one and retries **once**: not until it
works, because a loop against a route that refuses everything is a page that
hammers the server while telling the reader nothing.

`CSRF_COOKIE_DOMAIN` follows `SESSION_COOKIE_DOMAIN` and neither has been
touched, because **no POST on this platform crosses hosts**: each sign-in page
posts to its own host's routes, and sign-out posts to whichever host the page is
already on. `CSRF_TRUSTED_ORIGINS` is therefore untouched as well.

That last sentence was a prediction when this file was first written — "the one
POST a school's host will plausibly grow is sign-out, and that posts to that
school's own `/api/logout/` — same host, no setting" — and sign-out has now
landed exactly there. It is recorded as confirmed rather than deleted, because a
prediction that came true is the cheapest evidence there is that the reasoning
behind it was sound. A future cross-host POST would still need the widening and
would still deserve an argument rather than a quiet setting change.

## The token is not read out of `document.cookie`

It would work today and it is the wrong shape: it depends on
`CSRF_COOKIE_HTTPONLY` staying false, which is a setting somebody can harden on
a Friday, and it puts knowledge of the cookie's name in the browser. The API has
a route whose whole purpose is answering this.

## The controls

Operating rule 5: each claim was broken deliberately and the failures read. The
row worth reading is the third, where the first aim of a control changed nothing
— which is a result about the claim rather than a formality.

| what was broken | what failed | what that says |
| --- | --- | --- |
| the staff landing links each school to `//host/cards/` | `the landing links nowhere at all`, alone | the no-link rule is asserted, not merely the shape of markup that happens to have no `<a>` in it |
| `card/states.js` links back to `/` again | 4 tests, including the card page's sign-out round trip | the dead link is held by the states *and* by the flow that now reaches them on purpose |
| `if (!button.dataset.guardian) return undefined;` removed from the guardian click handler | **nothing** | the branches above it return first, so the guard is the second line and not the first — the comment claiming otherwise was wrong and is corrected. Re-aimed: dropping the sign-out branch's `return` leaves the suite green *because of* the guard, dropping both reddens `a sign-out tap is not posted as a guardian pick`, and deleting the branch reddens it and the failure test beside it |
| `sessionEnded()` returns true for every answer | 6 tests across all four pages | the asymmetry is what every page's "did not claim it did" assertion rests on, and it is asserted once per page rather than once |
| `provesASession()` returns true for every answer | `the sign-out button is drawn only on answers that prove a session` | the five-way split is a rule with a test on it |
| the 120-second threshold in `waitInWords()` moved | `too many tries says how long to wait, in a unit a person reads` — **twice, in two files** | the wait arithmetic really is one rule read by both doors. A copy per page would have reddened one |
| `esc()` dropped from the staff landing | 2 tests | a school name typed into the admin cannot execute in a teacher's browser |
| `card_page()` stops rendering `portal_host` | `test_the_frame_names_the_portal_so_the_401_state_can_offer_a_way_back`, 1 of the 2 | the pair is doing its job: the empty-domain test passes for a view that never sets the variable, and the test above it is what refuses that. Same pair the index page already has |
| the staff page mounted in `urls.py` as well | `test_a_schools_own_host_does_not` | portal-only is routing, and the routing is asserted |
| the PARENT narrowing dropped from `User.roles_at()` | `test_a_code_session_is_refused_there` and the known-limit test beside it | the escalation class really is about the credential and not about a missing membership |

## What is not here

**No staff home page.** The staff landing is a receipt, not a hub: it says who
signed in and at which schools, and stops. There are no staff screens on this
platform yet and inventing one here would be the staff-UI problem
[attendance.md](attendance.md) D12 already declined to solve twice.

**No `next=` parameter.** Nothing links into either sign-in page yet, so a
redirect target neither could have been given is a knob nobody turns. When slice
3's register screen needs "sign in and come back here", the allow-list that makes
it safe is already in the response: the host has to be one of the hosts
`SignedInOut` just named for that user, which is an allow-list derived from the
answer rather than from a settings list.

**No 403 page, so the escalation refusal still reaches nobody.**
`SchoolAccessMiddleware` refuses a code-opened session that reaches a school
where the guardian holds no PARENT role, with a sentence written for the person
it refuses, and `settings.GUARDIAN_SESSION_AGE` rests thirty days on that
narrowing and ends "She gets her staff powers again by signing in with her
password." **The page that sentence names now exists.** What does not is any way
for her to read the sentence: there is no `403.html` in this repository, so
Django's default handler renders `ERROR_PAGE_TEMPLATE` with empty `details` and
she sees "403 Forbidden". Closing that is a platform-wide surface — the same
handler answers "You do not have access to this school", a different refusal
with a different remedy — and it wants a distinguishable exception rather than a
template branching on a message string. **Issue #122**, and
`TheEscalationRefusalHasSomewhereToPointTests` holds the limit as a test that
goes red the day it closes.

**No "resend my code" timer.** The API throttles by value as typed and answers
429 with `Retry-After`; the page prints the wait in minutes or seconds and
leaves it to the reader to try again.
