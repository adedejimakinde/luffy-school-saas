# The register page

The first staff surface on this platform. Code: `attendance/views.py`, the
`register/` route in `urls.py`,
`attendance/templates/attendance/register_page.html`, the modules and
stylesheet in `static/register/` with `static/web/` shared, and tests in
`attendance/tests/test_register_page.py`, `attendance/tests/test_api.py`,
`tests/test_pages.py` and `tests/js/register.test.js`. The data path behind it
is [attendance.md](attendance.md); how a member of staff gets here is
[sign-in-page.md](sign-in-page.md).

## Everything before it was family

`/cards/` and the card itself are kept to "the children the caller is a parent
or guardian of" — `card_api._children_of()` says **"Never staff's roster"** in
so many words. That is why the staff landing shipped linking nowhere: there was
no staff destination to link to, and a link to `/cards/` would have answered a
teacher with "No children on this account… ask the school office to add you as
a guardian", which is the school's answer to a question she did not ask.

This page is the first destination that is a staff destination, and adding it
is what let the landing draw a link at all.

## The server sends a frame with no register in it

`register_page()` reads one row — the portal's hostname — and returns. It does
not look up a class, a term or a child, and it does not ask whether the caller
may mark anything, because there is exactly one answer to that and it lives in
`attendance.api._refuse_non_markers()`. A view that rendered the roster
server-side would be a second place asking the authority question, and the day
the two disagreed the wrong one would be the one nobody had tested.

**The shell is public**, like the card page, and for the same reason: a
`login_required` here would redirect, and a redirect on a guessable URL answers
"this school exists and this is its register" to anybody who types it. The
fetch inside the page is what meets the question.

## The portal serves this frame too, and that is the documented answer

`urls_public.py` splats the tenant patterns in, so `/register/` resolves on the
portal exactly as `/cards/` already does. That is not a leak: the frame holds
nothing, and every route it calls begins with `_school_of()`, which raises
`Http404` there because the register tables **do not exist in the public
schema** at all — `docs/tenancy.md`'s whole point.

So the page has a state for that answer rather than a routing rule pretending
the URL is absent. A teacher who opened the sign-in site and typed the path is
told where the work actually is.

## `GET /api/attendance/where/`, because the screen was keyed on nothing

The register is keyed on `(class_group, term, date)` and the API named none of
the three. That is the same gap the card index closed for a family, where both
card routes were keyed on two integers nothing ever handed anybody and the page
shipped openable only by typing them into a URL.

The authority check runs **before either lookup**, which is the order
`gradebook.api` taught this codebase: asking it second would turn the route into
a directory of the school's class groups for anybody signed in there, parents
and students included.

**The term is `Term.is_current`**, the column the school sets, unique by
constraint — the same authority `school_days` comes from. `None` is reported
and the screen says so. A term inferred from today's date would disagree with
the school the first time a term ran late, and the register would be filed
against the wrong one with nothing on the row to say it was a guess.

## Every class is listed, and that is a gap shown honestly

`can_mark_attendance()` is school-wide: any TEACHER at the school may take any
class's register, with no reference to `ClassTeacher`. Results submission is
scoped precisely because of issue #25 — "a JSS 1A teacher could submit JSS 3B's
results and be recorded as the signatory of a class they do not teach" — and
attendance has the same shape and no equivalent scope.

A shorter list here would be a scope the platform does not enforce, drawn as
though it did, which is the restriction-that-looks-enforced this phase keeps
finding. So the screen shows what the route allows, and a test asserts the list
is wide and says it goes red the day the rule narrows.

**Issue #125**, and [attendance.md](attendance.md) **A5** is the domain question
behind it: a subject teacher covering an absent form teacher cannot mark the
class in front of her under a `ClassTeacher` scope, and the workaround is a
borrowed login — strictly worse, because `taken_by_id` then names the wrong
person on every row it touches.

## One submit, and absence is what is tapped

`attendance/api.py` settled the shape and this page is the other half of it. A
marking sheet saves on blur because a teacher tabs through thirty cells over
twenty minutes; a register is the opposite interaction — one screen, a few taps,
one submit, thirty seconds. Forty-five conditional PUTs from a phone in a
corridor is not a register.

So the taps are held in the page's own memory until submit, and `absent_ids` is
what goes over the wire. Everybody else the screen showed is present, which is
why an **empty list is a meaningful submission** rather than an empty one: it
says every child was there.

**`shown_ids` is sent and is not optional here.** The schema allows omitting it
and means "whatever the roster is now" — right for an import, wrong for a phone,
which knows exactly which names it drew. Sending it is what makes the two
reports possible: a child who joined the group while the screen was open comes
back in `appeared`, **unmarked and named**, and an absentee moved out of the
group comes back in `not_on_the_roster`. Neither fails the request, because a
teacher in front of a class should not lose a register over one child the office
moved while she was marking — but a screen told only a count could say neither
sentence.

## Null is not present

`RegisterRowOut.status` is nullable and null means **not marked**, which is a
third answer rather than a synonym for present. An existing register opens
pre-marked from what it says, so a teacher correcting one child does not re-mark
the other twenty-nine, and `taken` is what tells an untaken register from one in
which everybody happens to be unmarked. Truthiness cannot make either
distinction, which is the nought-versus-null care `web/html.js` `numberOrBlank()`
carries on the card.

## The refusals are four answers, not one status

| answer | what happened | what the page says |
| --- | --- | --- |
| 403 | `_refuse_non_markers()` — signed in here, not somebody who marks | a bursar, a vice principal; **no staff-door link**, because she is already signed in with a password and what she lacks is a role only the school can give her |
| 404 | `_school_of()` — this host is not a school's | where the work actually is |
| 401 `session_expired` | the session lapsed | recoverable, and says so |
| 401 otherwise | never signed in | please sign in |
| 409 / 422 | nobody in the group; a date outside the term | the API's own `detail`, which it wrote for a person |

403 and 404 must not collapse: the remedies differ completely, and one sentence
for both is wrong for whichever reader it was not written for. The 409 and the
422 keep their own sentence rather than becoming `broken`, because both are
answers a teacher can act on.

**The sign-out button goes on the states that prove a session**, which is the
platform-wide rule. The 403 qualifies — `_refuse_non_markers()` is reached only
after `session_auth` has identified the caller — and the 404 does not, because
`_school_of()` raises before any authority question and says nothing about the
cookie. The marking screen deliberately has no button beside its submit.

## The way back is on another host

`/staff-sign-in/` is on the portal and this page is on a school's host, so the
link cannot be relative. `schools.hosts.portal_host()` is where the hostname
comes from and states the rule every caller keeps: with no portal domain
configured there is no link, only the sentence, because a dead link is worse
than being told to go back the way you came. The card page and the 403 page
added with issue #122 are the other two callers.
