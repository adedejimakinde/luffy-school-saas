---
name: luffy-withholding-recovered
description: "Phase 2 withholding: PR #83 MERGED as 818a82d, CI green; corrected controls posted as a #83 comment (ten failures, the revision red, 202!=403); local amend d2e03a1 discarded"
metadata:
  type: project
---

## The situation (2026-09-06)

Phase 2's withholding half was found **already implemented and uncommitted** in
`/home/vscode/worktrees/withholding` (branch `withholding`, at main's head
`441efb9`, **zero commits**). ~930 lines: `results/withholding.py` (294),
`results/migrations/0023_a_card_can_be_held_back.py` (182), plus edits to
`results/models.py`, `results/card_api.py`, `api.py`. Provenance unknown — not
written in the session that found it.

**The user's ruling on it:** do not write tests until the implementation has
been checked against `docs/fee-schedule-and-withholding.md` point by point,
because *"writing tests against unverified code produces tests that document the
code rather than the design — which is how a divergence gets frozen in."* Keep
that rule for any recovered work.

## Verification result — all five of the user's checks passed

Verified by enumeration and by evidence, not by re-reading the code's own
docstrings (which are extensive and would happily confirm themselves):

1. **`freeze_for_release()` untouched.** Four of them exist (`sessions.py:594`,
   `ratings.py:1021`, `comments.py:742`, `cards.py:194`); none of those files is
   in the diff. `grep withhold` across `cards/services/sessions/ratings/
   comments/renders` → **no hits**. Coupling runs one way only.
2. **One shared helper, both routes.** `_require_servable()` defined once at
   `card_api.py:473`, called at `:686` (`report_card`) and `:850`
   (`report_card_pdf`), same position in the same sequence. On the PDF route the
   gate is line 58 of the function and `marker_for()` is line 60 — **gate above
   the marker**, as the design requires.
3. **`_may_read()` returns `Optional[CardClaim]`**, `FAMILY_CLAIMS =
   {SELF, GUARDIAN}`, gate is `if claim not in FAMILY_CLAIMS: return`.
4. **Balance never gates.** `_balance_now()` has exactly ONE caller — `_record()`,
   on the write path. `is_withheld()` reads the switch, then the decision row,
   and never the books.
5. **Keyed `(child, term)`.** No FK or reference to `ReleasedCard` anywhere on
   `WithholdingDecision`.

`makemigrations --check` → `No changes detected`.

## Three divergences found — all documentation-level, none behavioural

1. **`WithheldOut.detail` vs the design's `message`.** The design's field list is
   `school_name, contact, message`; the code emits `detail`. `detail` matches
   django-ninja's convention for every other error body, so it is arguably the
   better name — **but it is a divergence and the user has not ruled on it.**
   The test deliberately asserts the *substance* (a human-readable sentence
   carrying the contact) under whichever key the body uses, rather than pinning
   either name and freezing the drift.
2. **`_require_servable()`'s docstring is missing the "only door" promise.** The
   design (test 4e's note) says explicitly that the narrower coverage promise —
   *this helper is the only door, and a new way to put card content in a
   family's hands is a change to this design rather than an addition to it* —
   **belongs in that docstring rather than in a test name.** It is absent from
   the whole tree. Currently carried only in the test class docstring.
3. **`results/withholding.py`'s first line references `docs/withholding.md`,
   which does not exist.** The design says that rename happens when this ships.
   Either rename the doc or fix the reference before merge.

## The collision the recovered work left behind

Adding `BURSAR` to `CARD_VIEWING_ROLES` (ruled, and correct) **broke
`test_card_api.py::test_a_bursar_may_not`**, which asserted 404. The recovered
implementation changed the documented behaviour and left the test documenting it
untouched — it went red on the first combined run. Rewritten as `test_a_bursar_may`
(200) plus a new `test_the_bursar_widening_did_not_reach_positions` asserting
`BURSAR not in results.api.POSITION_VIEWING_ROLES`, which is the half of the
ruling that actually needs guarding.

**Lesson: run the neighbouring test file, not just the new one.** The new tests
were all green while an existing file was red.

## Two of my own tests were wrong, and the code was right

Both worth remembering because both came from reading the design without reading
what the codebase already does:

- **"A stranger gets 404" is only true of a stranger the *endpoint* refuses.**
  `SchoolAccessMiddleware` refuses any authenticated caller with **no active
  membership at the host's school** with a **403, before any view runs**.
  `test_card_api.py` documents and pins this. So there are two populations:
  members with no claim (classmate, another child's guardian) → endpoint's flat
  404; non-members (stranger, another school's principal) → middleware's 403.
  The property the fee gate actually owes is that **neither is ever told the card
  is withheld** — asserted on the response bytes, since the status code alone
  cannot distinguish the middleware's 403 from the fee gate's.
- **A release writes the PDF marker `PENDING`, before any job has run.** Asserting
  `BUILT` after release pins the worker's timing, not the design's property. The
  right assertion is *sameness*: the withheld child's marker state equals a
  served child's on the same release.

## How it got there (historical — superseded by the MERGED section below)

- **`results/tests/test_withholding.py`, 1081 lines, 51 tests** across 16
  classes — the design owes **eleven** tests (`1, 2, 3, 4, 4b, 4c, 4d, 4e, 5, 6,
  7`), not ten, and all eleven have a class, plus five more.
- **Baseline green:** `test_withholding` + `test_card_api` + `test_ratings`,
  serial — `Ran 164 tests in 523.477s`, `OK`, `EXIT=0`. `test_ratings` is in
  there because it is the third file touching `ReportCardSettings`.
- **BOTH CONTROL RUNS ARE DONE.**
  1. Freeze: `cards.freeze_for_release()` made to skip a withheld child →
     `TheFeeDoorDoesNotTouchTheFreeze` **RED, 3/3** (`Items in the second set`,
     `unexpectedly None`, `0 != 2`) → revert → **GREEN** `Ran 3 tests, OK`.
  2. Bypass: gate fitted to `report_card()` alone → **RED, 9 failures out of 19,
     every one the PDF surface and `surface='json'` count exactly 0** → revert →
     **GREEN** `Ran 19 tests in 81.267s, OK`. `NobodyWithoutAClaim...` and
     `NoCardMeans404NotA403` stayed green throughout, correctly.
  - **Design test 4e earned itself**: the router enumeration named the ungated
    surface *by its path* without being told which route to look at.
- **COMMITTED as the single reviewable commit: `afb5a62`** on `withholding`,
  parent `441efb9` = main, tree clean, 7 files +2039/−22. **Not pushed, no PR.**
  Message carries the verification, the three divergences and both control runs.
- Full `results` app suite still not run to completion locally; CI will.

## The three divergences were ruled on and closed (2026-09-07)

1. `detail` kept over the design's `message` — every other error body in
   `api.py` is django-ninja's `{"detail": ...}`. **The doc was amended**, and it
   now records the ruling.
2. The "only door" promise **moved into `_require_servable()`'s docstring**,
   where design test 4e places it. The test now points at it.
3. **`docs/fee-schedule-and-withholding.md` renamed to `docs/withholding.md`**,
   git-tracked as a rename, "not built" notice stripped, both `PR79-FINDINGS.md`
   references repointed. `docs/fees.md` never linked to it — the link runs one
   way only, withholding -> fees.

## The review pass found six real findings — all fixed

`/code-review high 83`, launched after `EnterWorktree` so cwd was the worktree.
All six verified against the cited code before changing anything.

1. **MEDIUM, and the one that mattered: `_record()` skipped
   `why_not_a_student_here()`.** That rule is asked before every bare-id write
   in `fees.services`, `gradebook.services`, `academics.services`,
   `results.comments`, `results.sessions`, `results.ratings` — withholding was
   the one module that skipped it. Worse here because the table is append-only
   in three places: a decision against the wrong child cannot be corrected, only
   masked by a `lifted` row, and same-school-wrong-child silently holds a paid
   family's card.
2. `_balance_now()` could never return `None` — `balance()` ends `... or 0`, so
   the nullable audit column recorded a fictional zero. Now `None` for an empty
   ledger, `0` only when the books really say zero.
3. Step fragments did not fit `_require_authority()`'s template
   `"{actor} may not {step} results at {school}."` — live gibberish: *"may not
   withhold a report card at results at St Mary's"*. Now `"withhold"` /
   `"release withheld"`, matching `"revise"` and `"open a sheet for"`.
4. `set_policy()` let a raw `IntegrityError` escape. 5. `withhold()` raised a
   bare `ValueError`. Both now `WithholdingError(ResultsError)`.
6. Read path took a `Term` **or its id**, write path only a `Term`.

**LESSON: `assertRaises(Exception)` is why 4 and 5 survived a green suite.** It
cannot tell a sentence from a 500 — `IntegrityError` and `ValueError` both
satisfy it. Always assert the type.

**The fixes were controlled too**, because those tests were written against code
written moments earlier: revert `results/withholding.py`, keep the new tests →
`Ran 22 tests, FAILED (failures=5, errors=12)`. 17/22 red; the 5 green ones
assert things already true. Every finding has a test that bites.

## Where it stands — MERGED (2026-09-07)

- **PR #83 is MERGED.** Merge commit **`818a82d`** at 08:18:58Z, head `3ef728f`,
  one commit, parent `441efb9`. **Ancestry verified**: `3ef728f` confirmed an
  ancestor of `origin/main`. `main` in `/workspace` is at `818a82d`, tree clean.
- **CI run `34099951480` on the merge commit `818a82d` is `success`** — the full
  suite, green on main with withholding in it. Runs on `3ef728f` (`34082278645`)
  and pre-fix `abbff35` (`34080372205`) were also success.
- **`Ran 182 tests in 621.092s, OK, EXIT=0`** (test_withholding + test_card_api
  + test_ratings). 69 tests in test_withholding.

### The corrected control evidence lives in a comment on #83, not the PR body

The body's control runs were measured **before** the six review findings changed
`results/withholding.py` and `results/card_api.py`, so both were re-run against
the tree that actually merged and posted as a comment (08:30:45Z). A control run
is a statement about the code it was run against — when a review changes that
code, the controls in the body are stale and must be re-run and re-posted.
**Control outputs belong with the PR**, and after a merge a PR comment is their
home.

Control 2 was widened from the 19-test slice to all 69 tests in the module so
that *"the JSON route stays green"* is measured rather than assumed. **Ten
failures, every one the PDF surface**, versus nine in the narrow run. What the
wider scope bought:

- **`test_a_new_version_is_still_withheld` (surface='pdf')** — design test 7,
  **missed entirely by the narrow run**, which never reached the class. A
  revision of a withheld card served over `/pdf/`: the decision is keyed
  `(child, term)` precisely so reissuing cannot launder it, and a one-route gate
  hands the laundered copy over anyway.
- **`202 != 403` is the failure wearing its real clothes.** The ungated route
  does not hand the family the file — it hands them the *render state*. A family
  refused the JSON card learns from `/pdf/` that a card exists and is being built
  for them. The bypass **leaks before it ever serves**, which is worse than the
  404 this design already rejects, because it promises a document never coming.
- Design test 4e failed twice: it named the ungated surface *by its path*, then
  also failed its own count `1 != 2`, because `drove` increments *after* the
  status assertion inside the `subTest`. Redundant rather than wrong, and the
  redundancy falls on the safe side.

### The local amend was discarded — do not go looking for `d2e03a1`

A message-only amend `d2e03a1` was made **after** the merge, leaving `withholding`
diverged from `origin/withholding` with a **byte-identical tree** (both
`e8919a4597c7534c71739c99347619cc2516b2b6`). Reset to `origin/withholding` at
08:30:51; branch and remote are both `3ef728f`, worktree clean. **A diverged local
branch whose tree matches the remote is a trap for the next session** — it reads
as unpushed work when nothing is unpushed.

## Running the suite here

`scripts/run-tests.sh <labels> --noinput`, with
`DJANGO_SECRET_KEY` set (settings refuses to start without it unless
`DJANGO_DEBUG=1`). **`--noinput` matters**: a killed run leaves `test_luffy_db`
behind and the prompt dies as `EOFError` with `RESULT=<none>`.
**`--parallel` hides real errors** as `TypeError: cannot pickle 'traceback'
object` — re-run serially to see the actual failure.

See [[luffy-open-work-state]], [[luffy-snapshot-architecture]],
[[luffy-release-marker-requirement]], [[luffy-test-suite-runtime]],
[[no-claude-attribution-on-github]], [[luffy-phase-1-workflow]].
