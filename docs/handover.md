# Handover: 2026-09-28

## Merged

| PR | What |
| --- | --- |
| [#197](https://github.com/adedejimakinde/luffy-school-saas/pull/197) | Shard 4's flaky failures were `tblib` missing, not four unrelated bugs — the parallel test runner was masking one real `test_pdf` failure as four. Installed `tblib`; fixed #193. |
| [#198](https://github.com/adedejimakinde/luffy-school-saas/pull/198) | Phone: report card contrast fix, two-line subject rows, admission number, next-term date, class teacher's remark, conduct/skills ratings, a "Download PDF" button; absences cards to two lines; import cards verified already correct. |
| [#199](https://github.com/adedejimakinde/luffy-school-saas/pull/199) | Payment receipts — `fees.services.record_payment()` emails a receipt itself, no button. `docs/messaging.md` D13. |
| [#200](https://github.com/adedejimakinde/luffy-school-saas/pull/200) | Absence alerts — `attendance.services.take_register()` emails every live guardian of a child marked absent, no button. D14. |
| [#201](https://github.com/adedejimakinde/luffy-school-saas/pull/201) | The proprietor's daily money summary — `manage.py send_daily_money_summary`, run by cron, emails every live administrator once a day. D15. Not a `Notice`: see below. |

All five are on `main`. `claude/eager-knuth-pp98it` is reset to it and carries nothing
of its own right now.

Email receipts, alerts and the daily summary (#199–#201) are the three pieces of "the
next planned build" the session was given after #198: emailed payment receipts, the
proprietor's daily money summary, and absence alerts, each off by default per school,
through the existing provider interface, tested against the fake provider. All three
shipped, each as its own small PR and merged on green, the same way #198 was.

## What's next

Nothing is queued. The three notices above complete the list as given. The natural
next steps, if wanted:

- **A real email provider.** `docs/messaging.md` M5 and M6 are still open — only
  `messaging.fake.FakeProvider` exists. Every message this session added (receipts,
  alerts, the summary) works end to end against it, but nothing has gone out over a
  real SMTP or API provider yet, in dev or in production.
- **A settings screen** for the three new toggles
  (`NoticeSettings.payment_receipts/absence_alerts/daily_money_summary`). Today
  they're only reachable by hand (`NoticeSettings.objects.create(...)` or an admin
  shell) — `notices.services.set_offered_as()` would need extending, and there's no
  page yet that calls it for these three.
- **The cron entry for the daily summary** (`deploy/cron/classnode`, 23:05 UTC) is
  written but unexercised outside this session's test suite — confirm it against the
  real deploy runbook (`docs/deployment.md`) before relying on it in production.

## Open issues

- **A pre-existing flaky test**, found while driving #200's CI, unrelated to any of
  this session's changes:
  `results.tests.test_card_page.ThePageIsAFrameAndNotACardTests.test_the_ids_are_not_checked_and_must_not_be`.
  It normalizes two rendered frames by string-replacing the decimal digits of a real
  id and an invented one with placeholders, then asserts the frames are byte-identical.
  A small auto-incrementing test PK can coincidentally appear as a digit-substring
  inside an unrelated hashed static asset filename (a font's `.woff2`), so the
  replace corrupts one frame's hash but not the other, depending on which PKs the DB
  handed out that run. One re-run passed. Not fixed — it's in `results/`, outside
  every PR this session opened, and fixing the normalization approach itself was
  judged out of scope. Worth a small issue of its own.
- **"The proprietor" was read as `Role.ADMIN`** (school administrator), the closest
  existing role to a school's owner, distinct from the principal who runs the
  academic side. Every live administrator gets the daily summary, not one named
  owner. This was a judgment call, not a confirmed mapping — worth a sentence back
  from the school side if "proprietor" turns out to mean something more specific.
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
