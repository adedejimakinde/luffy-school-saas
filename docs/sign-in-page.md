# The sign-in page

How a guardian gets in. Code: `accounts/views.py`, the `sign-in/` route in
`urls_public.py`, `accounts/templates/accounts/sign_in.html`, the modules and
stylesheet in `static/signin/` with `static/web/` shared, and tests in
`accounts/tests/test_sign_in_page.py` (the shell),
`accounts/tests/test_cross_host_session.py` (the cookie) and
`tests/js/signin.test.js` (the flow). The routes behind it are `guardian_code()`
and `guardian_session()` in `api.py`; the rules they enforce are
[parent-access.md](parent-access.md). Where it sends people is
[report-card-page.md](report-card-page.md).

## One door, on one hostname

Mounted in `urls_public.py` and not in `urls.py`, so it exists on the portal and
nowhere else — matching the routes it calls, which both begin with
`api._portal_only()`. A sign-in page on a school's host would be a form that
submits into a 404, and a school's host refuses anybody without an active
membership *there*, which is the opposite of what a door needs. A parent with
children at two schools signs in once.

The frame holds nothing: no account, no child, no school, and the view reads
nothing from the database. It is served to whoever opens the URL, because the
page is what asks for the code that creates a session.

## Four steps, because the API has four answers

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

`CSRF_COOKIE_DOMAIN` follows `SESSION_COOKIE_DOMAIN` and neither was touched,
because **no POST in this change crosses hosts**: the sign-in page posts from
the portal to the portal's own routes, and the pages on a school's host only
read. `CSRF_TRUSTED_ORIGINS` is therefore untouched as well. The one POST a
school's host will plausibly grow is sign-out, and that posts to that school's
own `/api/logout/` — same host, no setting. A future cross-host POST would need
the widening and would deserve an argument rather than a quiet setting change.

## The token is not read out of `document.cookie`

It would work today and it is the wrong shape: it depends on
`CSRF_COOKIE_HTTPONLY` staying false, which is a setting somebody can harden on
a Friday, and it puts knowledge of the cookie's name in the browser. The API has
a route whose whole purpose is answering this.

## What is not here

**No staff sign-in page.** `POST /api/login/` is identifier-and-password and is
what staff use; it has no page. This change serves the guardian flow because
the reachability gap it closes is a parent's.

**No sign-out.** See [report-card-page.md](report-card-page.md) — the button
belongs on the pages a signed-in parent is looking at, and posts same-host.

**No "resend my code" timer.** The API throttles by value as typed and answers
429 with `Retry-After`; the page prints the wait in minutes or seconds and
leaves it to the reader to try again.
