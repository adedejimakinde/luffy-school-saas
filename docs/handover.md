# Where I stopped: 2026-09-29, Paystack PR 1 open, not merged

**Paystack, test mode only.** Money goes straight to each school's own bank account;
Classnode never holds it. Two PRs were asked for; only the first exists.

| PR | State |
| --- | --- |
| [#216](https://github.com/adedejimakinde/luffy-school-saas/pull/216) | Merged on green: the school's public page in the screens test (360/768/1280), and the platform admin's invitation texted through the phone provider when they have only a phone number (falls back to handing the link over if there is no provider or it refuses). |
| [#217](https://github.com/adedejimakinde/luffy-school-saas/pull/217) | **PR 1 (steps 1 and 4), open, waiting for review. Do not merge without the owner.** |

**PR 2 (steps 2 and 3) has not been started, by instruction: not until the owner says.**

## What PR 1 holds
`docs/paystack.md` is the description. In short: `/bank/` and `/api/fees/bank/`
(resolve the account name, confirm it, resolve again and compare, then a Paystack
subaccount with 0% for the platform **and a split with the subaccount as fee bearer**);
`fees.SchoolBank`, append-only; `fees/paystack.py`, a stdlib client that refuses any key
not starting `sk_test_`; the mocked Paystack, `fees/tests/paystack_fake.py`.

## Before PR 1 merges
- **Nothing was checked against Paystack.** Its docs were blocked from the sandbox; the
  endpoints and fields (`/bank`, `/bank/resolve`, `/subaccount`, `/split`) are from memory.
  One real test-mode call each should confirm them, especially the split's
  `bearer_type`/`bearer_subaccount`, which is what makes the school bear the fees.
- The append-only trigger on `SchoolBank` has a test but **no break-and-confirm-red**
  (it needs a migration edit). The name check, the 0% share, the fee bearer and the
  `sk_test_` check each did.
- CI on #217 was not seen by the time this was written.

## For PR 2
- The virtual account per student needs the stored `split_code` (and `subaccount_code`)
  so the fee bearer holds for it too. Confirm how Paystack takes them on a dedicated account.
- The webhook's mock tests (forged signature, replay, failed verification) belong there.
  The key is `PAYSTACK_WEBHOOK_SECRET`, defaulting to the secret key.
- Local test setup as in "Open issues" below; add `pip install --ignore-installed
  cryptography -r requirements.txt` and re-run `collectstatic` after adding static files.

---

# Handover: 2026-09-29 (second session)

## Merged

| PR | What |
| --- | --- |
| [#212](https://github.com/adedejimakinde/luffy-school-saas/pull/212) | Promotion: a third choice, **Leaving**, beside promote and repeat, for a child of any class. It ends the enrolment (`release_student()`) inside the same all-or-nothing confirm, gives them no placement, and is counted as `left`, not `graduated` (`POST /api/academics/promotion/` now answers `left`). No stored reason: the membership row is "ended" either way. `docs/classes.md`. Two-school tests. |
| [#213](https://github.com/adedejimakinde/luffy-school-saas/pull/213) | Platform admin screen: `/platform/` on the portal address, `GET`/`POST /api/platform/schools/` (`schools/platform_api.py`). Lists every school with its live student count; adds a school through `create_school()`, which now takes `admin_phone` as well as `admin_email` (the command gains `--admin-phone`). Platform staff only: school staff get 403, signed-out 401, a school's own address 404. Two-school tests. |
| [#214](https://github.com/adedejimakinde/luffy-school-saas/pull/214) | A public page for each school at the root of its own address (`schools/views.school_site`, template `schools/site.html`, `static/site/site.css`): crest and colour, name, about, address, phone, contact email, and "Check a result" / "Parent sign in". About, address and phone are edited on the setup page (`PUT /api/academics/public-page/`, new `School.about/address/phone`, migration 0005). No script, no outside request, under 150 KB. Two-school tests. |

Each was its own PR, merged on green. #212's first run had shard 2 fail on a Docker Hub
pull timeout before any test ran; it was re-run once and passed. This handover is a
fourth, docs-only PR.

## Things worth knowing

- **Adding a school by phone only sends nothing.** The only invitation channel is
  email, so an administrator given only a phone number (or any administrator when no
  email provider is configured) gets no message: the API answers with the accept link
  once (`emailed: false`, `link_to_hand_over`) and the screen shows it for the operator
  to pass on. The link makes whoever opens it the school's administrator. Sending it by
  SMS through the Termii provider would be the natural next step.
- **Creating a school in a web request is slow** (a real schema and migrations, a few
  seconds). The onboarding docs kept it at a shell for that reason; the platform screen
  is a deliberate exception. If the proxy timeout is short, this is where it will show.
- **"Leaving" is not recorded anywhere.** Left and graduated end the same way, so
  nothing afterwards can tell them apart; only the confirmation screen and the API answer
  do. A `reason` on the ended membership would fix that if anyone needs it.
- **The public page is refused to a person signed in at another school** (the existing
  403 page), as the result checker already is: `SchoolAccessMiddleware` refuses any
  signed-in person with no role there. A parent who is signed in on the portal and
  follows a link to a second school's page would see that, not the page.
- **The school phone is new.** The public page needed one and the school had none, so
  it was added to the setup form beside about and address. It is shown as a `tel:` link.
- **Crest on the public page** is the stored 256px crest shrunk to 128px on each view
  (`results.look.for_site`); nothing is cached.
- Nothing here was seen in a real browser; the pages are tested through their HTML and
  their JS renderers only.

## What's next

- Everything in the previous handover's "What's next" and "Open issues" still stands
  (Termii against the real service, `messaging.W001`, the SMTP provider, the daily-summary
  cron, promotion on a real school, the contact-email banner).
- The `/platform/` page has no link from anywhere: a platform user opens it by address
  after signing in at the staff door.
- The platform list has no paging or search; fine for tens of schools.

---

# Previous handover: 2026-09-29 (first session)

## Merged

| PR | What |
| --- | --- |
| [#208](https://github.com/adedejimakinde/luffy-school-saas/pull/208) | Admin home: until the school sets a contact email, a banner "Add your school's contact email so parents' replies reach you" linking to `/setup/#contact-email`. `GET /api/home/` gains `needs_contact_email` (no address **and** a login that may set one, so the vice principal is never sent to a page that refuses them). Closes the last "What's next" item of the previous handover. |
| [#209](https://github.com/adedejimakinde/luffy-school-saas/pull/209) | `messaging.termii.TermiiProvider`: SMS on Termii's DND/transactional route, API key and sender ID from `TERMII_API_KEY` / `TERMII_SENDER_ID` (plus optional `TERMII_BASE_URL`, `TERMII_TIMEOUT`). Selected only by `MESSAGING_PHONE_PROVIDER=messaging.termii.TermiiProvider`; `FakeProvider` stays the development default. Stdlib `urllib`, no new dependency. 21 tests against a mocked `urlopen`, including failures and a refused sender ID. `docs/messaging.md` M11. |
| [#210](https://github.com/adedejimakinde/luffy-school-saas/pull/210) | End-of-session promotion: page `/promotion/`, API `GET`/`POST /api/academics/promotion/`, rules in `academics/promotion.py`, described in `docs/classes.md`. Every child listed with promote/repeat (default promote); nothing moves until the second, confirming button; one transaction, all or nothing. Two-school tests. |

All three are on `main`, each its own PR merged on green (all four test shards, `screens`,
`image` and the aggregate `test`). This handover is a fourth, docs-only PR.

## How promotion works, in short

- A promotion is a set of `ClassPlacement`s in **next session's first term** (placements
  are per term): the next class for a child who passes, the same class for one who
  repeats. The top class (nothing above it by `level`) **graduates**, which is
  `release_student()`: the membership ends and is kept as history. That part is
  irreversible from the screen, and the confirm step says so.
- It needs the current term to be a **third** term and next session's first term to
  **already exist** (opened on Setup). Otherwise the page says what to do instead.
- Destinations are suggested from `ClassGroup.level` (same arm letter when several
  arms share the next level; nothing suggested when that is ambiguous, and the plan is
  refused until the office picks). The office can change any of them.
- The plan must name **every** class and child the school has now; a stale plan is a
  409 and nothing moves. A child already placed in that first term refuses the whole
  promotion. Authority is `PLACEMENT_ROLES` (principal, administrator).

## What's next

Nothing is queued from this session's list. Things worth doing, roughly in order:

- **Check Termii against the real service.** The Termii docs site was blocked from this
  session's sandbox, so the request shape and the success reply come from a search
  summary of the docs, and the **error-reply mapping is my assumption**, not captured
  from Termii: HTTP status plus keywords in `message` decide `Refused` (the number)
  versus `Unavailable` (everything else, including a refused sender ID). It is written
  conservatively, but one real failing call (an unwhitelisted sender ID, a bad number)
  should confirm it. Also confirm the default base URL, `https://api.ng.termii.com`,
  against the account's own. Termii also needs the sender ID **whitelisted for DND**.
- **`messaging.W001` is still silenced** in `settings.py`. Remove the silencing in the
  same change that names the phone provider in `deploy/production.env`, which this PR
  did not do (nobody has chosen to deploy Termii yet). OPEN-5, the contract and
  provider choice, is still the business question.
- **The SMTP provider** (#205) and **the daily-summary cron entry** are still
  unexercised outside tests; see the previous handover's notes, unchanged.
- **Promotion has not been used on a real school.** In particular: a school that runs
  a class with no level set (`level` defaults to 0) will get odd suggestions, and
  there is no undo. A follow-up could be a "promotion log" row so the office can see
  what was done and when.
- **A child who is leaving rather than graduating** is now a choice on the promotion
  screen (#212); this item is done.

## Open issues

- **Local test setup, for whoever comes next.** This sandbox needed Postgres and Redis
  started by hand, a `luffy_admin` role/`luffy_db` database, the env vars in
  `.github/workflows/tests.yml`, and `python manage.py collectstatic --noinput` before
  page tests pass (without it, they fail with "Missing staticfiles manifest entry").
  Test-database creation takes about two minutes per run; the full suite was left to CI.
- **The contact-email banner has one line of copy and no dismiss.** It disappears only
  once an address is saved. Deliberate (the previous handover's point was that nothing
  prompted schools), but a school that wants no `Reply-To` sees it forever.
- **The earlier handover's open issues stand** (proprietor read as `Role.ADMIN`,
  `MoneySummarySent` not append-only, no Redis in the sandbox, `docs/messaging.md`
  numbering: it now runs to D17 and M11).

---

# Previous handover: 2026-09-28

## Merged

| PR | What |
| --- | --- |
| [#197](https://github.com/adedejimakinde/luffy-school-saas/pull/197) | Shard 4's flaky failures were `tblib` missing, not four unrelated bugs — the parallel test runner was masking one real `test_pdf` failure as four. Installed `tblib`; fixed #193. |
| [#198](https://github.com/adedejimakinde/luffy-school-saas/pull/198) | Phone: report card contrast fix, two-line subject rows, admission number, next-term date, class teacher's remark, conduct/skills ratings, a "Download PDF" button; absences cards to two lines; import cards verified already correct. |
| [#199](https://github.com/adedejimakinde/luffy-school-saas/pull/199) | Payment receipts — `fees.services.record_payment()` emails a receipt itself, no button. `docs/messaging.md` D13. |
| [#200](https://github.com/adedejimakinde/luffy-school-saas/pull/200) | Absence alerts — `attendance.services.take_register()` emails every live guardian of a child marked absent, no button. D14. |
| [#201](https://github.com/adedejimakinde/luffy-school-saas/pull/201) | The proprietor's daily money summary — `manage.py send_daily_money_summary`, run by cron, emails every live administrator once a day. D15. Not a `Notice`: see below. |
| [#203](https://github.com/adedejimakinde/luffy-school-saas/pull/203) | A settings screen, `/notices/settings/` — the three switches from #199–#201 (`payment_receipts`, `absence_alerts`, `daily_money_summary`), reachable at last. The daily money summary no longer goes to every administrator: the school now picks its own recipients from its live staff list, nobody by default, reachability re-read at send time. `docs/messaging.md` D16, superseding D15's "every live administrator" reading. |
| [#204](https://github.com/adedejimakinde/luffy-school-saas/pull/204) | Every email this platform sends on a school's behalf — codes, result notices, fee reminders, payment receipts, absence alerts, the daily money summary, staff invitations — now carries the school's own contact email as `Reply-To`. New field `schools.School.contact_email`, set from the setup page. `docs/messaging.md` D17. |
| [#205](https://github.com/adedejimakinde/luffy-school-saas/pull/205) | A real email provider — `messaging.smtp.SmtpProvider`, plain SMTP behind the existing `messaging.providers` seam, opt-in via `MESSAGING_EMAIL_PROVIDER=messaging.smtp.SmtpProvider`. `FakeProvider` stays the default in dev and in the test suite. `docs/messaging.md` M10 — the email half of M6; a phone/SMS provider and OPEN-5's provider/contract choice are still open. |
| [#206](https://github.com/adedejimakinde/luffy-school-saas/pull/206) | Fixed the flaky `test_the_ids_are_not_checked_and_must_not_be` (see "Open issues" in the previous handover) — the id-normalization now targets the two `data-*-id` attributes by name instead of matching bare digits anywhere in the page, so it can no longer collide with a hashed static asset filename. |

All eight are on `main`.

#203–#206 were this session's own build, each its own PR merged on green, in the order
given: the settings screen, Reply-To, the SMTP provider, and the flaky-test fix. #203
merged first and cleanly; #204 and #205 were both branched before #203 merged, so both
needed a `docs/messaging.md` renumbering once #203 landed (#204's D16 became D17; #205's
build record entry didn't collide). #204's branch was updated with a merge commit from
`main` (not a rebase — a branch already pushed and open as a PR), re-tested in full, and
pushed before merging. #205 and #206 merged cleanly with no conflict. All four went
through their own local test cycle (Python suite, `npm test`, `makemigrations --check`,
`collectstatic`) both before opening and, for #204, again after the merge commit.

## What's next

Nothing is queued from this session's list. The natural next steps, if wanted:

- **A phone/SMS provider**, and OPEN-5's business question (which provider, under what
  contract). #205 built the email half of M6 only; `messaging.W001` is still silenced
  because no phone provider exists.
- **The SMTP provider is unexercised against a real mail server.** #205's tests run
  against `django.core.mail`'s `locmem` backend and mocked `smtplib` failures — nobody
  has pointed `MESSAGING_EMAIL_PROVIDER=messaging.smtp.SmtpProvider` at a real SMTP
  host yet, in dev or in production. Worth a manual check against a real (or
  Mailhog-style test) mail server before a deploy relies on it.
- **The cron entry for the daily summary** (`deploy/cron/classnode`, 23:05 UTC) is
  written but unexercised outside this session's test suite — confirm it against the
  real deploy runbook (`docs/deployment.md`) before relying on it in production. Still
  true after #203: the summary's recipient list is now school-chosen rather than every
  administrator, but the cron entry itself is unchanged.
- **No school has set a contact email yet** (#204's `School.contact_email`, blank by
  default) — the setup page offers it, but nothing prompts an existing school to fill
  it in, so `Reply-To` stays absent on every message until an office visits
  `/setup/#contact-email`.

## Open issues

- **"The proprietor" was read as `Role.ADMIN`** (school administrator), the closest
  existing role to a school's owner, distinct from the principal who runs the
  academic side. #203 narrowed who actually gets the daily summary (the school's own
  pick, from its live staff, defaulting to nobody), but the underlying "proprietor ==
  administrator" reading is unchanged and still a judgment call, not a confirmed
  mapping — worth a sentence back from the school side if "proprietor" turns out to
  mean something more specific.
- **`MoneySummarySent` is a plain log, not append-only** the way `Notice` and its
  claim/outcome tables are (no database trigger refusing `UPDATE`/`DELETE`). Deliberate
  — it's a send log, not a financial record or a decision made against a guardian's
  channel — but it's a real asymmetry with the rest of `notices`, documented in the
  model's own docstring and in `docs/messaging.md` D15.
- **This sandbox has no Redis**, so nothing here was exercised through a live Celery
  worker end to end; every test calls `send_notice.apply()` directly or mocks
  `apply_async`. Not a code issue — the same gap noted for #198's "Download PDF"
  button — but worth knowing if the next session reaches for a real broker to check
  something.
- **`docs/messaging.md`'s D-numbers and M-numbers now run to D17 and M10** across two
  sessions' worth of parallel PRs merged in quick succession. Renumbering a decision
  record after the fact worked cleanly here because the sections are additive and
  narrow, but a future session queuing several doc-touching PRs at once should expect
  the same and budget for it rather than being surprised by a `dirty` mergeable state.
