# Handover: 2026-09-28

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
