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

## The staff door: one step, and a landing that links where it can

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

### Where it sends them

The guardian flow ends by going somewhere: one school and it redirects, more
than one and it asks which. The staff flow ends by naming the schools this
login may act at **and linking each to what that school actually offers it.**

Until slice 3 it linked nowhere, and that was a decision rather than an
omission. `/cards/` was the only page a school's host served, and it is a
*family* surface even for staff: `card_api._children_of()` says "Never staff's
roster". A teacher sent there read "No children on this account… ask the school
office to add you as a guardian" — the school's answer to a question she did not
ask. And the payload could not tell the two apart, because `SchoolOut` carried
slug, name and host and nothing about what was behind them.

Both halves have changed. `/register/` is a staff destination —
[register-page.md](register-page.md) — and `SchoolOut` carries two booleans:

| field | the question it asks | why not a role |
| --- | --- | --- |
| `may_take_a_register` | `attendance.services.can_mark_attendance()` — `roles_at(school) & MARKING_ROLES` | a bursar and a vice principal (academic) are staff and do not mark, so "is staff" sends them to a 403 |
| `has_children_here` | `card_api._children_of()`'s predicate — `role=STUDENT` and (`user=actor` or `guardianships__guardian=actor`) | a PARENT membership with no `Guardianship` rows stands for nobody, and the page would answer "No children on this account" |

Each is **the same question the surface behind the link asks**, which is the
whole reason neither is a role. Four queries for the whole payload regardless
of how many schools: both tables are in SHARED_APPS, so each boolean is one
`school_id` set and a membership test.

That `/cards/` really serves this to a member of staff on a password session is
**proved rather than assumed** —
`results.tests.test_card_api.AStaffParentOnAPasswordSessionIsServedHerOwnChild`,
written before the field was added, with a staff-member-without-guardianship
control beside it so the positive result is about guardianship and not about a
roster.

**There is no auto-redirect, ever.** The guardian flow redirects on one school
because `/cards/` is the only thing a guardian does; a principal signing in has
many reasons to be there, and the landing is a hub from the day it has two
destinations.

**One school is one row, whatever is held there.** Multiple `Membership` rows
per (user, school) are expected and correct, so the capability is the union: a
bursar who also teaches gets the register link, and a teacher who is also a
parent gets both on the one school. The landing answers "where can I go", not
"what am I called".

Three ways a school ends up with no link, and they are three different
sentences: no host at all (a deployment fault), a host and nothing this login
may do there yet (a bursar, a vice principal), and the null-host case
`hostHref()` now handles for both pages. A school named with nothing after it
would read as a page that failed to load.

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

Operating rule 5: each claim was broken deliberately and the failures read.
**Serially — never `--parallel`.** A control reddens tests that fail inside a
transaction by construction, and those failures cannot be pickled back to the
parent: the pool dies and the run reports `EXIT=1` with *no* `OK`/`FAILED` line.
That is a crash, not a red, and four of slice 3's controls were nearly written
up as reds on the strength of it. `_refuse_non_markers() refuses nobody` is the
one that crashed; run serially it names eight tests.

Three rows are worth reading rather than counting. The third is where the first aim of
a control changed nothing — a result about the claim rather than a formality.
The `handler403`-dropped-from-`urls_public.py` row is the second: nothing in the
suite reddened until a test was written for it, because every other test here
runs on a school's host and the portal's fallback to Django's default handler is
invisible from there. The third is the landing pair — see it below.

| what was broken | what failed | what that says |
| --- | --- | --- |
| ~~the staff landing links each school to `//host/cards/`~~ | ~~`the landing links nowhere at all`~~ | **retired by slice 3.** The no-link rule was right while `/cards/` was the only destination; it is replaced by `each school is linked to what it offers this login, and to nothing else`, whose fixture is asymmetric so a renderer drawing both links everywhere reddens |
| `card/states.js` links back to `/` again | 4 tests, including the card page's sign-out round trip | the dead link is held by the states *and* by the flow that now reaches them on purpose |
| `if (!button.dataset.guardian) return undefined;` removed from the guardian click handler | **nothing** | the branches above it return first, so the guard is the second line and not the first — the comment claiming otherwise was wrong and is corrected. Re-aimed: dropping the sign-out branch's `return` leaves the suite green *because of* the guard, dropping both reddens `a sign-out tap is not posted as a guardian pick`, and deleting the branch reddens it and the failure test beside it |
| `sessionEnded()` returns true for every answer | 6 tests across all four pages | the asymmetry is what every page's "did not claim it did" assertion rests on, and it is asserted once per page rather than once |
| `provesASession()` returns true for every answer | `the sign-out button is drawn only on answers that prove a session` | the five-way split is a rule with a test on it |
| the 120-second threshold in `waitInWords()` moved | `too many tries says how long to wait, in a unit a person reads` — **twice, in two files** | the wait arithmetic really is one rule read by both doors. A copy per page would have reddened one |
| `esc()` dropped from the staff landing | 2 tests | a school name typed into the admin cannot execute in a teacher's browser |
| `card_page()` stops rendering `portal_host` | `test_the_frame_names_the_portal_so_the_401_state_can_offer_a_way_back`, 1 of the 2 | the pair is doing its job: the empty-domain test passes for a view that never sets the variable, and the test above it is what refuses that. Same pair the index page already has |
| the staff page mounted in `urls.py` as well | `test_a_schools_own_host_does_not` | portal-only is routing, and the routing is asserted |
| the PARENT narrowing dropped from `User.roles_at()` | `test_a_code_session_is_refused_there` and the known-limit test beside it | the escalation class really is about the credential and not about a missing membership |
| `NoMembershipHere.a_password_fixes_it` set to True | `the other refusal offers no password door` **and** `the two refusals are told apart by type not by wording` | the remedy really is keyed on which refusal fired. Both halves redden together, which is the point: the page's behaviour and the class attribute it reads are one claim, not two |
| the 403 links the door by path — `href="/staff-sign-in/"` | `the refusal names the password door by its full url`, alone | the hostname is load-bearing and not decoration. A path-only link resolves against the school's host she was refused on, which is a 404; the test's negative assertion is what refuses it |
| `refused()` prints `str(exception)` for every `PermissionDenied` | `a plain permission denied prints no detail` **and** `a foreign exception carrying the flag gets no remedy` | the narrowing to our own refusal types is a rule with a test on it, not a habit — and both halves of it, the sentence and the remedy, fail together because they read the same `isinstance` |
| the remedy read off the exception **by name** — `getattr(exception, "a_password_fixes_it", False)` | `a foreign exception carrying the flag gets no remedy`, alone | an attribute name is not a type. This was the shipped shape until the control for it was written: nothing reachable carries that name today, so the looseness was invisible, and the impostor exception in the test is what makes it visible |
| `handler403` dropped from `urls_public.py` | `both urlconfs resolve the same 403 handler`, alone | **the row worth reading.** Nothing else in the suite notices: the middleware never refuses anybody on the portal, so every other test here runs on a school's host and passes with the portal on Django's default handler. The test was written because the control found nothing without it |
| `handler403` removed entirely | 5 failures across 4 tests — the resolver test once per `subTest`, plus the sentence, the full URL and the other refusal | the page is reached through the wiring and not by accident |
| the payload claims every school is markable | 4, incl. `one login gets a different answer at each school` and `the code door does not` — **and no JS test at all** | see the row below: this half cannot reach the landing |
| **`landed()` draws the register link regardless of the boolean** | `each school is linked to what it offers this login, and to nothing else` **and** `a school offering this login nothing is named and says so` | **the row worth reading.** The landing is a pure renderer fed a payload and never calls `can_mark_attendance()`, so breaking the server-side predicate can only redden API tests. One control could not have made this claim; it takes two, and the second is what says the link is keyed on the boolean rather than on `host` or on nothing |
| the booleans answered for the login, not per school | `one login gets a different answer at each school` **and** `a staff parent is told which school her child is at` | the tenancy control, confirmed on **both** booleans — the failure a single-tenant fixture structurally cannot catch |
| `user.schools()` scoped to `LIVE_STATUSES` | `a suspended teacher has no school to be asked about`, alone | the access/live distinction is what keeps a held-but-not-actable school off the landing |
| `_refuse_non_markers()` refuses nobody | 8, including `a parent cannot tell a real class from an invented one` and `…a real term…` | the gate is the gate — and the two oracle tests say the authority-before-lookup *ordering* is load-bearing, not merely tidy |
| the code door stops narrowing the payload | `the code door does not`, alone | a six-digit code cannot be told it may take a register. Found by a control rather than by review, and fixed in `71d9ffc` |

## What is not here

**Still no staff home page.** The landing is a hub of *links*, not a dashboard:
it says who signed in, at which schools, and what each one offers this login —
and stops. It holds no school's data, which is what keeps it a page the portal
can serve at all.

**No `next=` parameter.** Nothing links into either sign-in page yet, so a
redirect target neither could have been given is a knob nobody turns. When slice
3's register screen needs "sign in and come back here", the allow-list that makes
it safe is already in the response: the host has to be one of the hosts
`SignedInOut` just named for that user, which is an allow-list derived from the
answer rather than from a settings list.

**The 403 page has landed — issue #122 is closed.** It was listed here as the
gap: `SchoolAccessMiddleware` refuses a code-opened session that reaches a
school where the guardian holds no PARENT role, with a sentence written for the
person it refuses, `settings.GUARDIAN_SESSION_AGE` rests thirty days on that
narrowing and ends "She gets her staff powers again by signing in with her
password" — and with no `403.html` in the repository Django's default handler
rendered `ERROR_PAGE_TEMPLATE` with empty `details`, so she saw "403 Forbidden"
and read none of it.

What closing it turned on is that this handler answers **two** refusals with
**different remedies**: this one is a password away from what she is asking for,
and "You do not have access to this school" is not. So the remedy travels with
the exception's *type* — `accounts/refusals.py`, two `PermissionDenied`
subclasses and an `a_password_fixes_it` class attribute — rather than being
recovered from prose a template matched on. `accounts.views.refused()` is the
handler, named as `handler403` in `urls.py` and re-exported from
`urls_public.py` because `django_tenants` swaps the urlconf per schema.

**The link carries the portal's hostname, and that is the load-bearing half.**
`/staff-sign-in/` exists on the portal and nowhere else, while this page renders
on a school's host — so a path-only `href` would resolve against the school's
host and hand her a 404 from the screen whose job is telling her how to get
back in. It is the dead `<a href="/">` the card page shipped, which is why
`schools.hosts.portal_host()` was lifted out of `results.views` to serve both.
The test asserts the full `//host/path`, because an assertion on the path alone
would have called the 404 a pass.

**No "resend my code" timer.** The API throttles by value as typed and answers
429 with `Retry-After`; the page prints the wait in minutes or seconds and
leaves it to the reader to try again.
