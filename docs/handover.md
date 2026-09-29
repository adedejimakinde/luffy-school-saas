# Handover: 2026-09-29

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
- **A child who is leaving rather than graduating** must be released first (they are
  then not listed). There is no "left the school" choice on the promotion screen.

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
