# Where I stopped: 2026-10-10 (later), the first real run of the bootstrap found a silent stop

The first real run of `docs/first-day.md` on the Contabo server stopped at `deploy/bootstrap.sh` line 164 with no reason, after `ssh_port=22` had been set correctly. The line was `sshd -T | awk '$1 == "port" {print $2; exit}'`: awk leaves at the first match, `sshd -T` is killed by SIGPIPE if it still has more than a pipe's buffer (64 KB) to write, and `set -o pipefail` makes that a failed pipeline, so `set -e` stopped the script.

**What changed.** (1) The port is read from a variable (`sshd_settings="$(sshd -T)"`, then an awk with no `exit` over a here-string); a failing `sshd -T` and an sshd that names no port each now stop with a sentence. (2) Every other pipe in `deploy/` was read: none else pipes into a reader that can leave early. `grep -i`, `tail`, `cut`, `tr` and awk without `exit` read to the end; `grep -q` is only ever used on a file, not a pipe; the awk in `init-env.sh` reads one line of `openssl rand -hex` (under 100 bytes, which fits in a pipe, so it cannot be cut off). (3) The `STOPPED` line now carries the line number, the command that failed (`BASH_COMMAND`) and its exit code. `docs/first-day.md` step 6 says so.

**Tests.** `tests/test_first_day.py` (38 tests, 9 new). One runs the script's own step 1 against a stand-in `sshd` that prints `port 22` first and then 4,000 more lines (about 200 KB): red on the old script (`STOPPED at line 164`, no reason), green on the new. Others cover a port that is not 22, an `sshd` that fails, one that names no port, the `STOPPED` text, and a scan that fails if any script under `deploy/` pipes into `head`, `read`, `grep -q/-m`, `sed ...q` or an awk with `exit`.

**Not verified.** Not re-run on Contabo. The stand-in is a script, not the real `sshd`.

**Rule for the next script.** Capture a command's output in a variable before filtering it with anything that can stop early.

# Where I stopped: 2026-10-10, the deploy button moves the server's checkout

The gap found at the end of the first-day runbook is closed. `deploy.sh` pulls the images for its SHA argument but reads `compose.yml` (and its own text) from the server's checkout at `/opt/classnode`; the workflow never moved that checkout, so a release that changed either ran with the old ones and still went green.

**What changed.** `.github/workflows/deploy.yml` now has three steps where there was one: *Set up SSH* (the key and `known_hosts`, as before), *Check out the SHA on the server*, then *Deploy over SSH* (unchanged). The checkout step sends a short script over SSH: refuse if the checkout has local edits to tracked files (a hand-edited `compose.yml` would otherwise survive the checkout and be deployed), `git fetch origin main`, `git checkout --detach <sha>`, then ask git that `HEAD` is the SHA. Never `git pull` or a branch name, so a `main` that has moved on cannot change what is released. A fourth step, *Put the checkout back on what is running*, runs only after a failure and only if the checkout step ran: it checks out `deploy/deployed-sha` (written only on a successful deploy), so the files on the server match the images still serving. It is `continue-on-error`, so it cannot turn a red run green or hide why it was red. `docs/first-day.md` step 16 no longer has the manual workaround (step 15's by-hand checkout stays: the first deploy precedes the button), and `docs/deployment.md` "Deploying" says what the button does.

**Test.** `tests/test_deploy_workflow.py` (20 tests). Structure: the checkout step exists, comes before the step that runs `deploy.sh`, no earlier step runs `deploy.sh`, it fetches then checks out `$sha` itself, it contains no `git pull`, `checkout main`, `reset --hard` or `--force`, and it asks `git rev-parse HEAD`. Behaviour: the step's own script is lifted out of the workflow and run against a real origin and clone with `/opt/classnode` pointed at a temporary directory. It proves the new `deploy.sh` is the one that runs, the exact SHA is used when `main` has moved on, an older release can be checked out, running twice changes nothing, a SHA that is not on `main` or does not exist moves nothing, local edits are refused and left intact (both to a file the release changes and to one it does not), the untracked `deployed-sha` is not counted as an edit, and the put-back works and does nothing before the first deploy. **Controls run (broken, seen red, restored):** the `git checkout` line removed, `git pull` in its place, the `rev-parse` check disabled, the local-edits check disabled, the deploy step moved ahead of the checkout, and the whole step deleted. The local-edits control was first **not** caught: the test edited a file the release also changes, which git refuses by itself; it now edits a file identical in both commits, which only the status check can catch.

**Not verified.** Nothing ran on GitHub or against the server: the YAML parses and its heredoc terminators end at column 0, and the script runs locally against real git, but the first real run of the workflow is the test. `actionlint` reports only an `info` note on the existing CI-gate step's `jq` quoting, not on these steps.

## Decisions (from this change)
- **Local edits make the button refuse**, rather than overwrite or carry them silently. A server that has been edited by hand is surprising enough to stop for. The way out is `git -C /opt/classnode status` as `deploy`, then undo or commit the edit elsewhere.
- **The put-back step is extra** to what was asked. Without it a failed deploy would leave the checkout on the new commit while the old images run, a mismatch this change would have introduced (the cron jobs read `compose.yml` from that checkout). It is one step and is tested.
- **`git fetch origin main`, not `origin`**: the workflow already refuses a SHA not on `main`, and the server side does not widen that.


# Where I stopped: 2026-10-09 (second session), the first-day runbook

`docs/first-day.md` is the founder's walkthrough from a fresh Contabo Ubuntu 24.04 VPS (169.58.181.9) to a school that can sign in: 29 numbered steps in PowerShell and `nano`, each with what it does, how to confirm it, and an **Undo**, in the order asked for: first root login; `deploy/bootstrap.sh`; the key check in a second window; the SSH lock; `secrets.env`, `caddy.env` and `backup.env`; the first deploy; `create_school`; the uptime monitor; the timed restore drill. It ends with a lock-out section that uses Contabo's VNC console, and a table of where things live. This closes the "nothing creates the `deploy` user" item under "Only you" below.

**New files.** `deploy/bootstrap.sh`, `deploy/init-env.sh`, `deploy/env/{secrets,caddy,backup}.env.example`, `tests/test_first_day.py` (29 tests). No application code changed.

**Verified (run here).** Both scripts pass `bash -n` and `shellcheck`. `bootstrap.sh` ran twice against a stand-in server (a real sshd and real files, `apt-get`, `ufw`, `systemctl`, `curl` and `git` stubbed): the second run changed no file and added no key. `--lock-ssh` was run with "no" (nothing changed), with "yes" (sshd reported `passwordauthentication no` even with a `50-cloud-init.conf` that says yes), with no key in root's `authorized_keys` (refused), and against an earlier-sorting file that overrides it (took itself back off); `--unlock-ssh` restored it; a private key in the public-key slot is refused. `init-env.sh` created the files at 640 root:deploy with a 96-character and a 64-character hex value, never printed one, and a second run left them alone; `--check` named a leftover placeholder. The tests were run, and five controls were seen red and restored: an extra `ufw allow`, the no-overwrite guard removed, a secret assigned in a code block, the SSH lock moved into the ordinary run, a literal password in a template.

**Not verified.** Anything on Contabo, in Docker, or against Cloudflare, GHCR or Backblaze. The Docker install, the `restore-for-real` commands (copied from `docs/demo-server.md` section 7, which has the same status), `docker login ghcr.io` as `deploy`, `docker compose` reading `/etc/classnode` as `deploy`, and the deploy button's SSH hop have never run. The Contabo VNC steps come from Contabo's help pages (linked in the doc), not from a panel.

## Decisions (from this session)
- **The deploy key's private half goes into a GitHub secret.** The instruction was to paste secrets only into files on the server; `DEPLOY_SSH_KEY` has to be in GitHub because that is where the workflow reads it. The runbook says so up front and puts it on the clipboard from a file, never on screen. Everything else is a file on the server. The one other secret typed at a prompt is the platform operator's password (`createsuperuser`).
- **Root keeps key login** (`PermitRootLogin prohibit-password`); passwords are off for everyone. There is no separate sudo user. The `deploy` key is `restrict`ed (no terminal, forwarding or agent).
- **Automatic reboot at 03:30 UTC (04:30 Lagos)** after a security update that needs one; Docker's own packages are not auto-upgraded. Turn off with `Automatic-Reboot "false"` in `/etc/apt/apt.conf.d/52classnode-unattended`.
- **443/udp is allowed** beside 22, 80 and 443/tcp (HTTP/3, as the compose file publishes it). The test pins the exact set.
- **Secrets are hex from `openssl rand`**, so no character needs quoting in a compose `env_file`.
- **`backup.env` is created only at the backup step**, not with the others: while `WALG_S3_PREFIX` is set the database archives, and a placeholder prefix would make it fail.

## Found, not fixed
- ~~**The deploy button does not move the checkout.**~~ **Fixed 2026-10-10**, see the section above: the workflow checks out the SHA on the server before `deploy.sh` runs.
- **No command removes a school.** A wrong slug on day one is undone by wiping the empty database (step 15); later it needs a developer.
- **GHCR login may be unnecessary** if the packages are public. The runbook has it, as `docs/demo-server.md` does; check on the first pull.
- **Drill B is in place, on the same server.** `docs/deployment.md` asks for a timed restore onto a **fresh** server before real children's data; step 28 says what it does not prove and how to do the fresh version (Contabo reinstall, then the runbook again). The times it produces are for the founder to send back here.

## Only you (from this session)
- Everything in `docs/first-day.md`: it is the list. The accounts it needs are the same as under "Only you" below, plus a VNC viewer on your PC and an uptime-monitoring account.
- Send the two drill times back so they go in this file.


# Where I stopped: 2026-10-09, the pre-deployment readiness check

Eleven things checked before the first real deploy. Nothing was added that is not a fix for a failure; the fixes are two PRs. **Verified** means run here (settings under `deploy/production.env`, the tests, and WAL-G against a throwaway Postgres 16 with file storage in place of B2); the CI `image` job covers the built image, the Caddyfile and WAL-G in the database image. There is no Docker daemon in the session, so nothing was run in a container.

| # | Check | Result | Notes |
|---|---|---|---|
| 1 | `DEBUG` off in production settings | **Pass** | Defaults off; `production.env` does not set it; `check --deploy --fail-level WARNING` is clean under it (CI runs it in the suite and again inside the built image). Not verifiable: the server's `secrets.env`; a `DJANGO_DEBUG=1` there would only be caught by the next CI run, not on the server. |
| 2 | Every DEMO mode refuses to start with `DEBUG` off | **Fail, by design; `load_demo` now has a second lock** | `DEMO_SINGLE_HOST=1` with `DEBUG` off raises `ImproperlyConfigured` at import (tested in a subprocess); `seed_demo` refuses without `DEBUG`. `DEMO_SERVER=1` does not: it is what the demo server runs with, with `DEBUG` off, and it only unlocks `load_demo` (which also needs `LOAD_DEMO_PASSWORD` and refuses a second run). A start-up refusal would stop the demo server. See "Only you" below. |
| 3 | No secrets in the repo or images | **Was fail, now pass** | No key, token, DSN or private key in the tree or in all 561 commits (only test fixtures and a build-time placeholder). Fail: `dump.rdb`, a Redis snapshot of queued task arguments, was tracked and `COPY . .` put it in the image; `.dockerignore` also did not exclude `.env`. Fixed in [#252](https://github.com/adedejimakinde/luffy-school-saas/pull/252), with tests. The file is still in git history (task arguments for the demo school, no keys). The image itself was not inspected (no Docker here). |
| 4 | `ALLOWED_HOSTS` and CSRF trusted origins from the environment | **Was fail, now pass** | `ALLOWED_HOSTS` read `DJANGO_ALLOWED_HOSTS`. CSRF origins were set only for the demo; now `DJANGO_CSRF_TRUSTED_ORIGINS`, empty by default ([#252](https://github.com/adedejimakinde/luffy-school-saas/pull/252)). |
| 5 | Secure cookies and HTTPS redirect on | **Pass** | Under `production.env`: session and CSRF cookies `Secure`, `SECURE_SSL_REDIRECT` on, HSTS 86400 s with subdomains (a day on purpose; move to a year after a renewal has been seen). A plain-HTTP request gets a 301 and a forwarded HTTPS one is served (tested). Not verifiable: behaviour through the real Caddy. |
| 6 | WAL-G backup and restore commands documented and runnable from `docs/demo-server.md` | **Was fail, now pass on the commands; B2 and Docker not verifiable** | The file said the demo has no backups and had no commands. Section 7 now has `backup.env`, enabling archiving, `classnode-backup`, `wal-g backup-list`, the cron install, the drill, and a restore. Run here: the pinned WAL-G (checksum matches the `Dockerfile`) took a base backup, archived WAL, and restored to the last archived write, using the same `restore_command` sequence as the doc. Not run: Docker, B2, the doc's `docker compose` wrappers. |
| 7 | Restore drill restores into a scratch database and checks one school's row counts | **Was partial, now pass** | It already restored into a throwaway `restore-db` and checked schemas and migrations only. Now `restore-check.sh` takes one school's per-table counts from the live database first and `verify_restore --expect-counts` requires the restored school to hold them (a table may be short by the larger of 10 rows or 1%). Ran the whole pipeline here: two schools, a base backup, rows written after it, WAL-G restore, `--print-counts` live, `--expect-counts` on the restore (passes; fails naming the table when the counts are wrong). |
| 8 | Sentry DSN from the environment | **Pass** | `SENTRY_DSN`; off when unset; personal data, locals and bodies never sent; `tests/test_error_reports` passes. Not verifiable: a DSN, the two cron monitors. |
| 9 | Health check endpoint for an uptime monitor | **Pass** | `/healthz/`: 200 `ok` or 503 when Postgres does not answer; any host; ahead of tenancy and the HTTPS redirect; `no-store`. Point the monitor at `https://classnode.co/healthz/`. It does not see Redis or the worker. |
| 10 | `migrate_schemas` run order documented | **Was partial, now pass** | `deploy.sh` said when, not in what order. `docs/deployment.md` "Migration order": `public` first, then each school; before the swap; what a failure leaves; the first deploy before onboarding; a restore. |
| 11 | Caddy wildcard certificate setup documented | **Pass** | `deploy/caddy/Caddyfile`, `docs/demo-server.md` step 1 (records, token scope) and step 4 (the first-issue wait), `docs/deployment.md`. CI validates the Caddyfile. Not verifiable: an issuance. |

**One more thing found:** the cron file, `deploy.yml` and `docs/deployment.md` used `/opt/classnode/deploy.sh`, `/opt/classnode/restore-check.sh` and `cd /opt/classnode`; the clone in `docs/demo-server.md` puts them in `/opt/classnode/deploy/`. The nightly backup, the weekly restore test and the deploy button would each have failed. All use `/opt/classnode/deploy` now, with a test ([#252](https://github.com/adedejimakinde/luffy-school-saas/pull/252)).

## Decisions (from this check)
- **`load_demo` refuses when a real school exists.** Any school whose slug is not `sunrise-demo`, `harbour-demo` or `showcase-demo` stops it, with those slugs named in the error, in both the normal and `--showcase` modes. `DEMO_SERVER=1` is no longer the only thing between a production database and fake children. The showcase slug is allowed because it is a demo school the same command makes and the docs say it sits beside the other two. Two tests in `schools/tests/test_seed_demo.py` (`LoadDemoTests`). **Controls run (broken, seen red, restored):** with the guard never called, the refusal test fails (`CommandError not raised`); with the showcase slug dropped from the allowed set, the allow test fails. The allow test covers the three slugs (showcase first, then the two); only the showcase slug was broken in the control.
- **Hosting is "any Ubuntu 24.04 VPS (Contabo or similar)"**, not Hetzner, in `docs/`, and now in `deploy/compose.yml` (comments) and the privacy notice, which names no provider and no country. In its place `#stored` carries a legal TODO (shown only with `SHOW_LEGAL_TODOS`): state the hosting provider and where the server is once it is chosen, with the basis for the transfer. The "Who we share it with" list now names only Backblaze and Sentry; add the host there too when it is chosen.
- **`dump.rdb` is untracked** (removed in #252; `*.rdb` is in `.gitignore`). Nothing to do.
- **History is not rewritten.** The hook that re-authors commits stays declined; `main` is untouched.

## Only you

- **Never put `DEMO_SERVER` in production's `secrets.env`.** It is the demo server's switch (row 2). As a second lock, `load_demo` now refuses when the database holds any school that is not a demo school (decided; see "Decisions" below).
- **Accounts and keys:** any Ubuntu 24.04 VPS (Contabo or similar); the domain and its Cloudflare zone; the Cloudflare DNS token; a Backblaze B2 bucket and an application key limited to it; `WALG_LIBSODIUM_KEY` (kept offline too); a Sentry (EU) project, its DSN and two cron monitors (`nightly-backup`, `restore-check`); a transactional email provider with SPF/DKIM/DMARC; a GHCR `read:packages` token for the server.
- **GitHub:** the `production` environment and the three secrets `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`. `deploy.yml` logs in as `deploy@` on the server; nothing creates that user or says what it may run (it needs Docker and `/opt/classnode`).
- **On the server:** `secrets.env`, `caddy.env`, `backup.env`; `cp deploy/cron/classnode /etc/cron.d/classnode`; the uptime monitor on `/healthz/`.
- **Before real children's data:** the timed full restore onto a fresh server (`docs/demo-server.md` section 7), your confirmation on data residency (NDPA, OPEN-9), the lawyer's TODOs below, and raising HSTS from a day to a year after a renewal.
- **History:** older commits on `main` carry `Co-authored-by: Claude` and `Claude-Session:` trailers. This session's commits and PRs carry none. Removing the old ones means rewriting `main`, which I did not do.


# Where I stopped: 2026-10-06, the phone polish pass

A short pass over what a phone shows. Everything here is layout or one setting; no data or API changed.

- **Mobile sizing (#250, merged).** The public site's phone measure: 28px headline, 16px body, 22px section headings, 16px page padding, sections 40 to 56px apart, a hero shorter than the screen. `tests/ui/screens.test.js` now runs the site pages at 390px as well and fails on any of these.
- **Marks entry (`/marking/`).** Every mark box is 5rem wide and right-aligned, and the running total beside it is a fixed 4.75rem column, so the boxes' right edges stay on one line whether the mark is 1, 2 or 3 digits. (The total column used to be `auto`, which slid each row's box by the width of its total.)
- **Homepage on a phone.** Below 840px the two laptop screens (the broadsheet and the proprietor's home) are phone-sized crops of the same screens, in a phone frame: `broadsheet-phone.webp` and `home-phone.webp`, cut by `scripts/site_shots.py` (`CROPS`) from the laptop WebP files. A `<picture>` serves one or the other, so a phone downloads only its crop. Desktop is unchanged.
- **Pricing card.** The "Pricing" label above the heading is gone (the heading is now the `h2`), and "No setup fee." is one unbreakable phrase, so it never leaves a word alone on a line.
- **Principal home, Today.** A row with no time no longer carries an empty `<time>` that held the time column open; it starts at the left, as the timed rows' times do.
- **Tab bar.** `--tabbar` (61px: the links' 60px and the rule above them) is one token: the page's bottom padding is exactly it plus the phone's safe area, which is the bar's whole height, so the last control is never under the bar (it used to be the bar plus 24px, so the last button now sits right against the bar's edge). The layout test at 390px covers register, marks, remarks and timetable, at 844 and 640px tall: the last control ends above the bar, and the padding equals the bar. `.sticky-actions` (unused today) is not given a bar offset: nothing uses it, and the CSS budget has no room for rules nothing needs (see below).
- **Legal TODO notes.** `SHOW_LEGAL_TODOS` (settings.py) draws the TODO boxes on the privacy notice and the terms. Off by default, so a public visitor sees neither the boxes nor the word. On when `DJANGO_DEBUG=1` (development and the demo, including the CI screens job), switched on by the legal tests for themselves, and `SHOW_LEGAL_TODOS=1` turns it on anywhere. Off, a note that stood in the middle of a sentence would leave the sentence short, so each note now sits in a sentence of its own and the public page simply leaves the fact out. These pages are still not ready for the public until the list below is done: "we will change the date below" points at a date that is not there yet. `website/views.py` strips the notes from the rendered page.

## Every open TODO (62 on the legal pages)

Turn `SHOW_LEGAL_TODOS=1` on to see each one in place. "lawyer" is the lawyer's to settle, "owner" is the owner's. The first line of each is the section's id and heading.

**Privacy notice (`/privacy/`)**

1. `#who`, Who we are: TODO: RC number.
2. `#who`, Who we are: TODO: registered address.
3. `#who`, Who we are: TODO: lawyer.
4. `#roles`, The school decides. We process.: TODO: lawyer.
5. `#roles`, The school decides. We process.: TODO: lawyer to draft the agreement and confirm it exists before launch.
6. `#roles`, The school decides. We process.: TODO: lawyer.
7. `#why`, Why we use it: TODO: lawyer.
8. `#basis`, Our legal basis: TODO: lawyer to state the bases under section 25 of the NDPA.
9. `#basis`, Our legal basis: TODO: lawyer.
10. `#basis`, Our legal basis: TODO: lawyer.
11. `#basis`, Our legal basis: TODO: lawyer.
12. `#stored`, Where it is stored: TODO: B2 region.
13. `#stored`, Where it is stored: TODO: lawyer. State the hosting provider and where the server is once it is chosen, and the basis for the transfer (the notice names no provider until then).
14. `#stored`, Where it is stored: TODO: lawyer to state the basis for transfer under Part VIII of the NDPA, and any filing it needs.
15. `#shared`, Who we share it with: TODO: name.
16. `#shared`, Who we share it with: TODO: lawyer.
17. `#shared`, Who we share it with: TODO: lawyer.
18. `#shared`, Who we share it with: TODO: lawyer to confirm each agreement.
19. `#kept`, How long we keep it: TODO: lawyer and owner to set how long records are kept after a school leaves.
20. `#kept`, How long we keep it: TODO: lawyer.
21. `#kept`, How long we keep it: TODO: confirm once backups are running.
22. `#kept`, How long we keep it: TODO: how long demo bookings are kept.
23. `#children`, Children's data and parents' consent: TODO: lawyer to confirm what section 31 of the NDPA requires and how the school records consent.
24. `#children`, Children's data and parents' consent: TODO: lawyer.
25. `#children`, Children's data and parents' consent: TODO: lawyer to confirm this is sensitive personal data under the NDPA and what more the school must do.
26. `#rights`, Your rights: TODO: lawyer to confirm this list.
27. `#rights`, Your rights: TODO: lawyer to state the time.
28. `#rights`, Your rights: TODO: lawyer.
29. `#complain`, How to complain: TODO: lawyer to add the Commission's current contact details.
30. `#contact`, Contact us: TODO: registered address, for post.
31. `#contact`, Contact us: TODO: Data Protection Officer, by name, or whether one is required.
32. `#changes`, Changes to this notice: TODO: lawyer.
33. `#changes`, Changes to this notice: TODO: date. Write "Last updated" in front of it.

**Terms (`/terms/`)**

1. `#about`, About these terms: TODO: RC number.
2. `#about`, About these terms: TODO: lawyer.
3. `#about`, About these terms: TODO: lawyer.
4. `#service`, What Classnode does: TODO: lawyer and owner to set the notice period.
5. `#accounts`, Signing in: TODO: lawyer.
6. `#school`, What the school is responsible for: TODO: lawyer.
7. `#school`, What the school is responsible for: TODO: lawyer.
8. `#fees`, Fees and payments: TODO: lawyer.
9. `#fees`, Fees and payments: TODO: lawyer and owner to confirm.
10. `#fees`, Fees and payments: TODO: lawyer.
11. `#price`, Our price: TODO: when invoices are sent and when they must be paid.
12. `#price`, Our price: TODO: lawyer and owner to set the steps and notice.
13. `#price`, Our price: TODO: owner to confirm.
14. `#use`, Using the service properly: TODO: lawyer.
15. `#data`, The school's data: TODO: lawyer.
16. `#data`, The school's data: TODO: owner to confirm what format, and how long it takes.
17. `#data`, The school's data: TODO: hours, within which we will tell it.
18. `#data`, The school's data: TODO: lawyer to match the NDPA breach rules.
19. `#availability`, When the service is not available: TODO: lawyer and owner to decide whether to promise an uptime figure.
20. `#liability`, Our responsibility: TODO: lawyer to write what Classnode is and is not responsible for, and any limit on it, in plain words.
21. `#ending`, Ending the service: TODO: lawyer and owner to set notice.
22. `#ending`, Ending the service: TODO: period within which we delete them.
23. `#ending`, Ending the service: TODO: lawyer.
24. `#ending`, Ending the service: TODO: lawyer.
25. `#law`, The law that applies: TODO: lawyer.
26. `#law`, The law that applies: TODO: lawyer to set what happens next, and where.
27. `#law`, The law that applies: TODO: lawyer.
28. `#law`, The law that applies: TODO: date. Write "Last updated" in front of it.
29. `#contact`, Contact us: TODO: registered address, for post.

## The 150 KB budget

`/marking/` is the heaviest page: 153,350 bytes on `main` against a 153,600 limit, so about 250 bytes of room. This pass nets +81 bytes there (the marks and tab bar rules), so about 170 are left. Anything added to `design.css` or `marking.css` needs to take something out.

## Not verified

- The Django suite's other jobs and the whole screens run are CI's to say; I ran the website tests, the JS tests and the new 390px tests locally.
- The crops are cut from the existing laptop shots, not retaken, so the home crop shows the demo school's numbers.

---

# Where I stopped: 2026-10-05 (seventh session), the pilot QA's follow-ups: clearing a mark, the office's teaching screens, the import's email gap

You answered the two open decisions from the pilot run: **step 2, build the screens; step 6, keep reusable
PINs (D11 stays).** Then three items, one PR each, merged on green CI gated on the head SHA.

| PR | State |
| --- | --- |
| [#246](https://github.com/adedejimakinde/luffy-school-saas/pull/246) | **Merged on green:** emptying a mark box takes the stored mark back (online and queued offline); a redraw no longer saves a half-typed number. |
| [#247](https://github.com/adedejimakinde/luffy-school-saas/pull/247) | **Merged on green:** `/teaching/`, the office's screen for subjects, this term's papers and class teachers. |
| [#248](https://github.com/adedejimakinde/luffy-school-saas/pull/248) | **Merged on green:** after an import, the children whose guardian has no email, listed and downloadable. |

## 1. Clearing a mark (#246)
- **What was wrong:** the page ignored an emptied box (`DELETE` existed server-side and was never called), so the box
  looked cleared while the school kept the mark. Now an emptied box that holds a mark is a `DELETE` with the version it was
  drawn with; it is queued as an outbox entry whose value is `""`, so it also works offline and across a reload. No stored
  mark means nothing is sent; a resent `DELETE` is a 200 that changes nothing. `docs/offline.md` OPEN-7 is settled.
- **Found on the way, and worth knowing:** putting focus back after a redraw (#244) made the browser blur the replaced box,
  and the blur handler saved what was typed so far ("4" of "44"). A random-timing stress run (10 sheets) had 1 bad before the
  guard and 0 after; `tests/ui/marking_focus.test.js` now delays the school's answers and requires one write per mark.
- **The page budget:** `/marking/` had 21 bytes spare. The code added about 770 bytes, so comments in `marking/*.js` were
  shortened first (no behaviour). It is about 230 bytes under its old size; `/marking/` and `/register/` (which loads the
  same outbox) are still the tightest pages. Expect the next change there to need the same trim.
- Tests: browser (`tests/ui/marking_clear.test.js`, online and offline), JS, two school tests (clear, resend, retype; another
  school's child is a flat 404 and nobody's mark moves).

## 2. `/teaching/` (#247)
`docs/teaching.md` has all of it. One page under Office ("Subjects"), principal and administrator only, reusing the setup
page's look. Class teachers (one select per class, for the current term), subjects (add, edit, no longer taught, remove) and
this term's papers (add, edit, remove). A paper's "out of" cannot change, nor the paper be removed, once anyone has a mark in
it; a subject that has had papers is retired, never removed. Every route asks who is asking first.
- **Control run (broken, red, restored):** `curriculum.can_shape` was made to admit a teacher; `WhoMayOpenIt` went red; passes
  restored.
- **Not done, on purpose:** papers belong to one term and are made for the **current term only**. When a school opens next term
  (standard card) its papers must be added again; there is no "copy last term's papers" (the Ogun template does set them at
  term creation). Teachers are not assigned to subjects: any teacher may mark any paper, as before. No reordering of papers
  (they print in the order added).
- Tests: `gradebook/tests/test_teaching.py` (25, including two schools whose first subject, paper and class share an id),
  JS, a browser flow in which a teacher then finds the administrator's paper, and the layout screens.

## 3. The import's email gap (#248)
`docs/roll-import.md`. After an import the done screen lists children whose guardian this school has no email for ("No
guardian was given" or "A phone number only") and offers a CSV (BOM, quoted, formula-safe) built in the page.
- Judged only on **what this school may know**: a guardian with an email at another school who has not answered this one is
  still listed (otherwise the report would say which numbers belong to a parent with an email elsewhere).
- **Only the batch just imported**, and only on that screen: there is no later "who has no email" report on the roll, and the
  list is not stored. Download it before leaving the page. A roll-wide report would be the next small step if wanted.

## Not verified
- All of it ran against the demo, a local Postgres and Redis and Chromium at 360px with touch, not a real handset, host or
  provider. The soft keyboard dropping is inferred from focus loss.
- `tests/ui/roll_import_gap.test.js` adds three children to JSS 1A in the demo database on each run (admission numbers from
  the clock); the other UI files do not depend on the class's size.
- Nothing here touched Paystack, hosting or domains.

---

# Where I stopped: 2026-10-05 (sixth session), the first-school pilot flow run end to end on the demo school

You asked for the term-1 flow of a first school, run as a school would: Sunrise Demo Academy from `seed_demo`, in a real
browser (Chromium) at 360px and at 1280px, a local Postgres and Redis, a Celery worker, the fake message provider. Nothing
was run against a real host, a real SMS or email provider, Paystack, or a domain.

| # | Step | Result |
| --- | --- | --- |
| 1 | Import 60 children from the Excel template | **Pass.** Three bad rows (no name, a class that does not exist, a duplicate admission number) refused the whole file, each named by its row and column, and nothing was written, also when the bad file was sent straight to the admit route. The clean file admitted 60 into JSS 2A and 2B, siblings sharing one guardian, leading zeros kept (`P0001`). Text dates (`04/07/2014`), `M`/`F`, an existing admission number or learner's ID, a contact with no name, a bad phone number and Yoruba names with dotted letters were all read or refused in words. |
| 2 | Create classes and subjects, assign teachers | **Fail, not built.** Classes are created on the setup page and staff are invited and accept from the staff page (both pass). There is **no page or route to create a subject, to create an assessment (the First CA and Exam papers), or to assign a class teacher.** `seed_demo` and the shell are the only ways. Any teacher may take any register and mark any assessment, so "assigning" a subject teacher does not exist either; a class teacher only decides who may submit a class's results. I did the assignment from the shell (`academics.services.assign_class_teacher`), as an operator would. Building these is a feature, so I did not. **Your decision.** |
| 3 | Teacher on a phone: register, then CA and exam marks, then the same offline | **Pass after two fixes (#243, #244).** Register taken (27 present, 3 absent). 30 marks per paper online. Offline: 30 marks per paper queued in IndexedDB, kept across an offline reload, sent when the connection came back (also with the page left open, no reload), one row per child, version 1, every value as typed; a mark typed twice and one changed and changed back arrived once. |
| 4 | Release, then report cards (normal and Ogun) | **Pass.** Submit, check, approve and release by the teacher, vice principal and principal at 360px. All 30 cards of JSS 2A match totals and grades computed from the score rows independently (grade key A1 to F9). Position is absent on every card released with the setting off, and present on every card released after it was turned on (dense ranking: a tie does not use up the next place, as `docs/positions.md` says). The Ogun card renders at 360px and 1280px with the sheet's boxes and totals. The PDF carries the same totals, no position where it was off, and names with dotted letters (DejaVu behind Hanken). |
| 5 | Parent on a phone with a code | **Pass.** An imported guardian was sent a code from the roll, signed in at 360px, and saw only their child (a parent of two siblings sees both). Every other child's card and PDF is a flat 404, every office route a 403, and the other school's host refuses the session. Attendance shows on the card. |
| 6 | Result checker: a PIN works once, then is used up | **Differs from the brief, by design.** A slip's PIN opens that child's card **every time** until the session ends, and the slip says so ("the PIN works until next session starts"); `results/checker.py` and `docs/messaging.md` D11 argue why (a family returns to it). Wrong, another child's and replaced PINs are refused with one sentence. I did not make it single-use: that reverses a documented decision. **Your decision.** |
| 7 | Absence alert and receipt emails | **Pass.** With both switched on in Notices: one absence alert to the guardian's verified email for the right child and date (not sent twice when the same register is submitted again), and one receipt (`SUNRISE-DEMO-000056`) when the bursar recorded ₦25,000. "Tell families" sent one text per child to live guardians only. |

## Pull requests

| PR | State |
| --- | --- |
| [#242](https://github.com/adedejimakinde/luffy-school-saas/pull/242) | **Merged on green, gated on its head SHA:** the OGSERA filler took a paper by name alone, so an Exam out of 60 went under "Exam (70)". Papers now need the sheet's maximum as well. Two school tests. |
| [#243](https://github.com/adedejimakinde/luffy-school-saas/pull/243) | **Merged on green, gated on its head SHA:** a half mark (12.5) showed the teacher "[object Object]"; it is now a sentence. Four tests. |
| [#244](https://github.com/adedejimakinde/luffy-school-saas/pull/244) | **Merged on green, gated on its head SHA:** typing marks down a column on a phone lost every second mark, and fast typing could save "1" for "11": the sheet was redrawn from the blur and took the box just tapped. A real-browser test types down a column. |

No fix touched results release, tenant isolation or access, so no controls were run.

## Not verified, or worth knowing

- **Not run on a real host, with real SMS or email, or on a real handset.** "Phone" is Chromium at 360px with touch; the soft keyboard dropping was seen as lost focus, not on a device.
- **A school that adopts the Ogun template after marking** keeps its marked papers (`Exam` out of 60), as the presets promise, so the filler now reports them as not entered. The school should choose the template at setup, before marking.
- **Absence alerts and receipts are email only** (D13). An imported guardian has a phone and nothing else, so neither reaches them until the office adds an email to a live guardian and the guardian signs in with it once. The roll offers this only for a live guardian.
- **A term's school days are not set** on a new school, so a card says "0 present, 1 absent" with no "of N" until the office sets the term's length.
- **Clearing a mark on the marking page does nothing**: an emptied box is ignored by design (`DELETE` is the only way to unmark and the page does not call it). The box looks empty while the school still holds the mark, until the next redraw. Wiring it costs page weight, and `/marking/` is a few hundred bytes from the 150 KB budget. Your decision.
- **Tapping a box that already has a mark puts the caret at the end**, so typing appends to it. Not changed.
- The release confirmation on a phone opens below the buttons, off screen until scrolled to.
- `dump.rdb` in the repository root is a Redis snapshot and was overwritten by a local Redis run; it was restored, not committed.
- Local setup used: Postgres 16, Redis, `celery -A celery_app worker`, `DEMO_SINGLE_HOST=1` for the parent redirect (without it the sign-in redirect drops `:8000`, which only matters locally).

---

# Where I stopped: 2026-10-04 (fifth session), the Ogun State template, all six parts merged

You asked for the Ogun State template (the MOEST/OGSERA report sheet), one PR per part, merged on green, except part 5,
which stops for your review with screenshots. Part 6 (the OGSERA filler) and the part 5 additions came mid-session.
**`docs/ogun-template.md` is the description of all six parts**, each with its tests and controls table.

| PR | State |
| --- | --- |
| [#235](https://github.com/adedejimakinde/luffy-school-saas/pull/235) | **Merged on green:** part 1, the child's learner's ID (unique per school when present), sex, date of birth and passport photo (`academics.StudentDetails`); the roll import's three new optional columns; the school's LGA in setup. |
| [#236](https://github.com/adedejimakinde/luffy-school-saas/pull/236) | **Merged on green:** part 2, the template chooser in setup (`ReportCardSettings.template`) and its one-click presets: the four papers, the twelve traits, the 1 to 5 scale. |
| [#237](https://github.com/adedejimakinde/luffy-school-saas/pull/237) | **Merged on green:** part 3, physical development and health (`results.HealthRecord`), seen by four people; the privacy notice's "Health records". |
| [#238](https://github.com/adedejimakinde/luffy-school-saas/pull/238) | **Merged on green:** part 4, marks obtainable, obtained and percentage on every card; class position as a school setting, off by default, on with the Ogun template. |
| [#239](https://github.com/adedejimakinde/luffy-school-saas/pull/239) | **Merged on green:** part 6, `/ogsera/`, filling the OGSERA Excel template from Classnode's marks. |
| [#240](https://github.com/adedejimakinde/luffy-school-saas/pull/240) | **Merged after your review:** the Ogun State card on the PDF and the parent's page; school code; SSS departments; third-term rows and the promotion box. Review screenshots on the branch `ogun-card-screens` (never merged). |
| [#241](https://github.com/adedejimakinde/luffy-school-saas/pull/241) | **Merged on green:** the ministry's heading on the Ogun card is a school setting, off by default; without it the card leads with the school's crest, name, LGA and code. |

## The rules each part keeps
- **Presets never overwrite.** Choosing Ogun replaces a subject's papers only while none of them has a mark (row locks,
  `Score` PROTECT behind them), and never hides a trait someone has rated. It applies to the current and future terms;
  a term opened later on an Ogun school gets the papers at creation (`ogun.after_term_opened`).
- **Health is four people's.** The class teacher records; the class teacher, principal, administrator and the child's
  guardians (only once that term's card is released) read; every refusal is a 404. It is never in the card payload,
  broadsheet, class list, export or the result checker. After release a trigger stops edits (`HealthLocked`).
- **Position is frozen per card** (`ReleasedCard.position_printed`) so the page and the stored PDF agree. With the
  setting off no payload carries a position, as before (the raw-bytes tests still hold).
- **Ogun card, two PDFs.** When the child has a health record, release stores an ordinary copy (a note where the table
  would be) and `health_content`, served only to the four. Its decisions are in the part 5 PR, for you to answer.
- **OGSERA:** the mapping is per school (`OgseraMapping`, in the school's schema); rows are matched to the chosen
  class by learner's ID; a cell with a value or formula is kept unless "Replace existing values" is ticked; the
  download is refused while any row is unmatched or has no ID.

## Migrations
`academics` 0005, `schools` 0007 (LGA) and 0008 (school code, part 5), `results` 0028 to 0031 (merged) and
0032 (part 5, the PDF's health copy), `gradebook` 0004 (a subject's department, part 5).

## Not done or not verified
- **Part 5's "Decisions for you"** (#240: senior means a class name starting SS/SSS; the page turns the grid on its
  side; details and promotion are read live; the ordinary copy's note) were merged as written.
- **Not checked against a real OGSERA file.** The filler is tested with a made-up template of the same shape (title
  block, header on row 5, a formula, validation, a second sheet). The first real file may name its headings
  differently; the mapping screen is how a school copes, and nothing is filled until the check screen is clean.
- **The reference sheet was read from your description and the field list**, not overlaid on a scan. Spacing and
  font sizes on the PDF are mine.
- **No mark entry screen for the Ogun papers was changed:** they are ordinary papers, entered on the marking page.
- **Health entry** sits on the comments page (class teacher), fetched separately; there is no class-wide health
  screen, on purpose (it would be a class list of health data).
- **`tests/ui/offline.test.js` flaked once** in the `screens` job on #239 ("no copy of a sheet is left", 2 !== 0),
  in code none of these PRs touch; it passed 3/3 locally and on one re-run. Worth watching.
- The OGSERA page is the newest entry in `tests/test_budget.py`; the card page grew by `card/ogun.js` and is within
  budget.

---

# Where I stopped: 2026-10-03 (fourth session), single-host demo fixed, offline S5 to S7 merged

Each PR merged on green or after your review, then this docs-only one (#234).

| PR | State |
| --- | --- |
| [#229](https://github.com/adedejimakinde/luffy-school-saas/pull/229) | **Merged on green:** the development-only single-host demo (`DEBUG` on and `DEMO_SINGLE_HOST=1`): the two sign-in pages and the three sign-in API routes also answer on a school's own host. Settings refuse the flag with `DEBUG` off. README "Run the demo in a Codespace". |
| [#230](https://github.com/adedejimakinde/luffy-school-saas/pull/230) | **Merged after your review:** offline S5, the service worker (`/sw.js`) and per-person copies of what the pages were shown. |
| [#231](https://github.com/adedejimakinde/luffy-school-saas/pull/231) | **Merged on green:** the Codespace sign-in redirected to `http://localhost/...`. `USE_X_FORWARDED_HOST` in demo mode, `path_only` links after sign-in, sign-out to `/staff-sign-in/`. |
| [#232](https://github.com/adedejimakinde/luffy-school-saas/pull/232) | **Merged after your review:** offline S6, the register's base, the per-child merge, the registers outbox. |
| [#233](https://github.com/adedejimakinde/luffy-school-saas/pull/233) | **Merged on green:** offline S7, a phone two people share ("Held for Kemi"). |

`docs/offline.md` has "S5 as built", "S6 as built" and "S7 as built" with the choices that were mine.

## Single host demo
`schools/demo.py` is the one question (`single_host()`: `DEBUG` and the flag). `api._door_host_only()` relaxes only the
three sign-in routes; the platform API stays portal-only. In demo mode `SchoolOut.path_only` is true and `hostHref()`
returns the path. **Not run in a real Codespace**: that the forwarder sends `X-Forwarded-Host` is inferred from the bug.

## Offline, in short
- **Worker:** `sync/worker.js` served by `sync/views.py` with a derived file list; never touches `/api/`.
- **Copies:** `static/web/snapshots.js`, IndexedDB, per host and person; offered only when the server cannot be reached.
  Deleted for the previous person when another opens the host online.
- **Outboxes:** marks (`marking/outbox.js`) and registers (`register/outbox.js`), both in `static/web/store.js`'s database
  (`luffy-marks-outbox`, a name that predates the registers and stays). Names: `<host> <user>`, `<host> <user> register`,
  `<host> <user> who`.
- **Register merge:** `attendance.services.take_register(base=...)` under the register's lock; conflicts are the
  teacher's to answer (`Keep the school's` / `Use mine`). A register with no marks is removed; one with marks never is.
- **Shared phone:** `heldElsewhere()` says whose work is held, never what it is; no button discards another's work.
- `GET /api/{gradebook,attendance}/where/` now return `user_id` and `full_name` (the caller's own).

## Tests and controls
Node 689+ (`tests/js/`), new: `snapshots`, `service_worker`, `marking_offline`, `register_offline`, `register_outbox`,
`shared_handset`, fakes `fake_register_school.js` and `memory_snapshots.js`. Python: `sync/tests/test_service_worker.py`,
`attendance/tests/test_register_merge.py`, `test_where_names_the_caller.py`, `accounts/tests/test_single_host_demo*.py`.
**`tests/ui/offline.test.js` runs in the `screens` job** in a real Chromium (it needs `channel: "chromium"`; the headless
shell ignores the secure-origin flag). Controls were run for each slice (break, see red, restore).

## Not done or not verified
- **No real Android phone, no real Codespace, no production (hashed static names) browser run.**
- **The marking page is at ~153 KB of its 153.6 KB budget** (`tests/test_budget.py`). Anything added there has to be paid
  for. Several long docstrings were shortened to fit; the long reasoning is in `docs/offline.md`.
- **A phone offline cannot know who holds it.** Sign-out on the marking and register pages clears; a sign-out from
  another page does not, until one of these pages sees "signed out" online. Documented as S5 decision 2 and S7 decision 2.
- OPEN-5 (taken-at versus arrived-at for a queued register) is still open; OPEN-3's seven days flags, never deletes.
- Local runs need Postgres and Redis started by hand (`pg_ctlcluster 16 main start`, `redis-server --daemonize yes`);
  they stop when the sandbox restarts. Use `--noinput` on `manage.py test` when a test database was left behind.
- The branch names of earlier sessions' screenshot branches may still need deleting from GitHub's Branches page.

---

# Where I stopped: 2026-10-03 (third session), public homepage and legal pages merged

Two PRs, each merged on green after review, then this docs-only one.

| PR | State |
| --- | --- |
| [#226](https://github.com/adedejimakinde/luffy-school-saas/pull/226) | **Merged:** the public homepage on the bare domain (`classnode.co`), the demo request form, and `load_demo --showcase`. |
| [#227](https://github.com/adedejimakinde/luffy-school-saas/pull/227) | **Merged:** `/privacy/` and `/terms/` on the same host. |

`docs/website.md` is the description of both.

## Where the site answers (#226)
`SITE_HOST` (defaults to `PLATFORM_DOMAIN`; `www.` is the same site). `schools/middleware.py`
(`PlatformTenantMiddleware`, replacing django-tenants' middleware in `settings.MIDDLEWARE`) sends that one host
to `urls_site.py`: the homepage, `/privacy/`, `/terms/`, nothing else. **Not a `Domain` row**, on purpose: a row
would make it the portal, with the admin and both sign-in doors on it. Every other host resolves as before.
Deploying needs nothing new: the apex A record and the certificate already cover it; `migrate_schemas` adds
`website.DemoRequest` (public schema).

## Demo requests
Saved, then emailed after commit to every active platform staff login with an email (`website/notify.py`); a
failed send is logged and the row stays; the portal admin lists them read only. Honeypot field `website`
(answered like a real request, nothing saved). `DEMO_REQUESTS_PER_HOUR` (5) per address, counted from the
rows: a 429 past it. The two refusals still show visible TODOs for their wording (none was given).

## The showcase (`load_demo --showcase`, `schools/showcase.py`)
Crestfield College, demo data only, same guards as `load_demo` (`DEMO_SERVER=1`, `LOAD_DEMO_PASSWORD`). A good
day: a strong student's card (77.67%, A1/B2, attendance, both remarks), JSS 2A and 2B released, SS 1A open with
healthy first-CA marks and no sheet, every register in, nothing waiting or flagged. `ShowcaseTests` holds it.
`scripts/site_shots.mjs` takes the homepage screenshots from it, and **needs a freshly loaded showcase each
run**: SS 1A's register for today is left untaken so it can be photographed and then submitted on the page.
The home therefore reads "2 of 3" released (a released class's marks sheet is locked, so the marks shot comes
from the open class).

## Copy and what is still TODO
Homepage copy is the user's, word for word, with the price (₦2,500 per student, per term, no setup fee), "one
working day", "Classnode. Nigeria." and hello@classnode.co. Legal pages: company Classnode, contact
hello@classnode.co. **Still visible TODOs:** the RC number, the registered address, every "TODO: lawyer", the
server location, B2 region, email provider, retention periods, DPO, breach notice, invoicing, dates, and the
"Our responsibility" section.

## Tests
`website/tests/` (homepage and legal: hosts, copy and writing rules, form, 400 KB and 15 KB budgets, motion
rules, pattern contrast, contents, NDPA sections, sentence length). `tests/ui/screens.test.js` photographs the
three pages at 320, 360, 390, 414, 768, 1024, 1280 and 1920 and checks the slides on a fake clock.
`tests/test_design.py` follows `{% extends %}` and skips `parts/`; `tests/test_pages.py` counts the site's
one module (no imports, no import map). Controls were run for each (break, see red, restore).

## Not done or not verified
- **The branch `ccr-e8075f91-3aiv4s-screens` (review screenshots only) could not be deleted from the
  session**: the proxy refuses branch deletion (git and API, 403). Delete it from GitHub's Branches page.
- No email was really sent; nothing has run on a server.
- #227 was rebuilt on main after #226 was squashed: a merge of main with the legal branch's tree kept as is
  (same tree CI passed on). Its first run on that head then failed `screens` on the **fees** page (the class
  drawn, its account button not yet), which neither PR touched: a race in the test's drill-down. Fixed in
  #227: each step now waits up to five seconds for its target and still fails when it never comes (control
  run). Merged on green.

---

# Where I stopped: 2026-10-03 (second session), demo server prep merged; nothing run on a server yet

Two PRs, each merged on green, then this docs-only one.

| PR | State |
| --- | --- |
| [#222](https://github.com/adedejimakinde/luffy-school-saas/pull/222) | **Merged:** a small "Staff sign in" link in a footer on each school's public page, to `//<portal host>/staff-sign-in/` (shown only when a portal host exists, like "Parent sign in"). |
| [#223](https://github.com/adedejimakinde/luffy-school-saas/pull/223) | **Merged:** `manage.py load_demo` and `docs/demo-server.md`. |

## Staff sign in link (#222)
`schools/templates/schools/site.html` (`<footer>`), `static/site/site.css`. **The first push failed the `screens`
job**: that test fails any touch target under 44px tall and any phone text under 15px, and the link was
13.6px text with a short box. The footer link is now 16px text in a 44px-tall box. The job's log showed only
server output, not the assertion, so that diagnosis is from the test's rules, confirmed by the re-run going green.

## load_demo (#223)
`schools/management/commands/load_demo.py`, a subclass of `seed_demo`'s command (its `_school()` and data are
shared, not copied; `seed_demo` gained `check_allowed()`, `seed()`, `password_line()` and a `tell_families`
switch, nothing else). Works with `DEBUG` off. Refuses unless `DEMO_SERVER=1`. The password is only
`LOAD_DEMO_PASSWORD` (12+ characters; no default, no argument, never printed). It **messages no family and stores
no parent phone number**: with `DEBUG` off there is no fake provider (`messaging.E001`) and a real one must never
be handed that number. So **the demo parent cannot sign in** (parents sign in by a phone code); the doc says to
show the parent's side from the staff logins. Refuses to run twice. **Controls run (broken, seen red, restored):**
the `DEMO_SERVER` guard, the password guard (and the 12-character floor), and no-families/no-phone.

## docs/demo-server.md
Fresh Ubuntu 24.04 VPS to `app.classnode.co`, `sunrise-demo.classnode.co` and `harbour-demo.classnode.co`:
Cloudflare records (A `app` and A `*`, both **DNS only**), the token (Zone:DNS:Edit + Zone:Zone:Read on the
`classnode.co` zone only), Docker install, `secrets.env` / `caddy.env`, and the compose commands by hand.

## Not verified: nothing here has run on a real server
- **No server, no Cloudflare, no Docker install was touched.** The token scope and the Docker apt steps are from
  those tools' documentation. The first real run is the test; fix the doc in the same change.
- **Superseded by the domain PR:** `deploy/production.env` now says `classnode.co`, and `docs/demo-server.md`
  uses `deploy.sh` and has the GHCR login steps. The two caveats below on the override and `deploy.sh` no longer apply.
- **`PLATFORM_DOMAIN` is overridden on the server, not in the repo.** `deploy/production.env` still says
  `classnode.africa`; the doc relies on a later `env_file` winning (`secrets.env` for web/worker/db, `caddy.env` for
  Caddy) and has a `printenv` check. If compose does not behave that way, the fix is a server-side edit of
  `production.env`.
- **`deploy/deploy.sh` is not used** for the demo: it sources `production.env` and health-checks
  `classnode.africa`. The doc has its steps by hand. If the demo is to be deployed by the workflow, the script
  needs to take its domain from somewhere the override reaches.
- **GHCR images may be private.** The doc has a `docker login ghcr.io` (token with `read:packages`); the SHA run
  must include `load_demo` (#223's merge commit or later) and have a passed `publish` job.
- No backups, email, SMS or error reports on the demo, by design.

---

# Where I stopped: 2026-10-03, placing unmatched payments (#220) merged; "Create accounts for this class" in review

**Paystack, test mode only.** Money goes straight to each school's own bank account;
Classnode never holds it. Nothing further is queued after this PR.

| PR | State |
| --- | --- |
| [#216](https://github.com/adedejimakinde/luffy-school-saas/pull/216) | Merged: the school's public page in the screens test; platform admin invitation by SMS. |
| [#217](https://github.com/adedejimakinde/luffy-school-saas/pull/217)–[#219](https://github.com/adedejimakinde/luffy-school-saas/pull/219) | Merged: bank connection, bank paging, virtual accounts and the webhook (the webhook verifies with `PAYSTACK_SECRET_KEY`; no separate secret). |
| [#220](https://github.com/adedejimakinde/luffy-school-saas/pull/220) | **Merged on green:** the bursar places an unmatched payment on a child; platform staff see the unrouted list. |
| This PR | **"Create accounts for this class"** on the class page. Merges on green. |

## Placing an unmatched payment (#220)
`fees/placing.py`, `POST /api/fees/virtual/unmatched/{payment_id}/placement/`. The bursar picks the
class and child on `/bank/`, then confirms the amount and reference, which must equal the payment's
(`NotWhatYouConfirmed` otherwise). It posts through `record_payment_once()` with the same
`form_key` the webhook uses for that reference, so it can never post twice (not even if the webhook
is replayed: a placed payment answers "duplicate"). `fees.UnmatchedPlacement` (append-only, trigger
in migration 0009) records who placed it, on which child. Placing the same payment on a second child
is refused (`AlreadyPlaced`); asking again for the same child returns the first placement. Platform
staff: `GET /api/platform/unrouted/` and a list on the platform page (read only; platform staff only).

## Create accounts for this class (this PR)
`POST /api/fees/virtual/classes/{class_group_id}/` with `{term_id}`; `fees.virtual.ensure_for_class`.
It calls the same idempotent `ensure()` as the child's page, one child at a time, each in its own
transaction. Children who already have an account are skipped and counted. It answers
`{made, skipped, failed[{student_membership_id, student, detail}], remaining, stopped}`. A refusal for
one child is reported by name and the rest go on; if Paystack is unreachable or unset the batch stops
(`stopped`, untried children in `remaining`). 409 with no school bank, 422 with no term, 403 for
anyone but the bursar/administrator. The class page offers the button only to a writer at a school
with a bank while some child has none (`may_make_accounts`, `accounts_missing`).
**Controls run (broken, seen red, restored):** the failure isolation, the Paystack-down stop, the
batch cap, the bank check, the writer check, who is offered the button, and `ensure()` returning the
existing account (against `test_virtual`'s own test: in the class test the pre-skip also covers
it, so breaking `ensure()` alone stays green there by design: two layers).

## Not done
- **At most 20 accounts per press** (`CLASS_BATCH`): each is two Paystack calls inside a web request.
  The note says how many are left; press again. Nothing runs in the background.
- The button works for the term the class page is on; there is no term picker beyond that page's.
- No way to resolve an unrouted payment: platform staff can only see the list. An unmatched
  payment with no current term cannot be placed until a term is current.

## What changed at review (#219)
1. The webhook reads the account number and customer code from Paystack's verify reply, falling
   back one field at a time to the signed event (`webhook._field()`); never guessed.
2. No separate webhook secret: `PAYSTACK_SECRET_KEY` signs and verifies.

## What PR 2 holds
`docs/paystack.md` describes it. A dedicated virtual account per child
(`fees.VirtualAccount`, made against the school's split; `POST /api/fees/virtual/students/{id}/`),
shown on the bursar's account page, the parent's page (`GET /api/fees/virtual/mine/`) and in
fee reminders and receipts (` Pay into: Wema Bank 1234567890, Ada Bello.`). The webhook
(`POST /api/paystack/webhook/`, portal host only, `fees/webhook.py`): HMAC-SHA512 signature, then
Paystack's own verify, then the account number routed to a school (`schools.PaystackRoute`, public)
and matched to a child, then `record_payment_once()` once per reference. A payment that cannot be
placed is never guessed: it goes to `fees.UnmatchedPayment` (shown to the bursar on `/bank/`) or,
if no school owns the account, `schools.UnroutedPayment`.

**Controls run (broken, seen red, restored):** the signature check, Paystack's status, the
amount comparison, once-per-reference, the customer check, the route lookup, the replay of an
unmatched reference, and the append-only trigger on the two new tenant tables. At review, also:
no fallback to the event's fields, the event's fields winning over the verify reply, and a live
key being accepted for the signature.

## Unverified (PR 2)
- **Not called against the real Paystack.** The dedicated-account and transaction-verify calls
  are from memory. Where the receiving account number (`authorization.receiver_bank_account_number`)
  and the customer code (`customer.customer_code`) sit is why the webhook falls back to the signed
  event's own fields; if Paystack puts them in neither place under those names, a payment is listed
  as unmatched or unrouted and never placed. `PAYSTACK_DVA_BANK` defaults to `wema-bank`; test mode
  is believed to want `test-bank`. The dedicated account is made with `split_code` only (not
  `subaccount`), so the school bears the fees: confirm Paystack accepts that on a dedicated account.
- `PaystackRoute` and `UnroutedPayment` (public schema) have no append-only trigger.
- The webhook URL still has to be set in Paystack's dashboard (test mode) to the portal's
  `/api/paystack/webhook/`, and `PAYSTACK_SECRET_KEY` put in `secrets.env` (it is the only
  Paystack secret: there is no webhook secret to set).

## What PR 1 holds
`docs/paystack.md` is the description. In short: `/bank/` and `/api/fees/bank/`
(resolve the account name, confirm it, resolve again and compare, then a Paystack
subaccount with 0% for the platform **and a split with the subaccount as fee bearer**);
`fees.SchoolBank`, append-only; `fees/paystack.py`, a stdlib client that refuses any key
not starting `sk_test_`; the mocked Paystack, `fees/tests/paystack_fake.py`.

## Still unverified (PR 1)
- Paystack's bank list and account resolve were checked against its docs at review; the
  subaccount calls, the split and `percentage_charge` 0 too. None has been called for real.
- Every PR 1 control (name check, 0% share, fee bearer, `sk_test_`, `bank_code`, paging, the
  append-only trigger) was broken, seen red and restored.

## Local test setup
Add `pip install --ignore-installed cryptography -r requirements.txt` and re-run
`collectstatic` after adding static files. Postgres and Redis stop when the sandbox
restarts: check `pg_isready` before trusting a test run that printed no result line. A new
migration needs a fresh test database (no `--keepdb`). The full suite is CI's job (this
session ran fees, notices, messaging and the page, menu, budget and design tests: 513 pass).

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
