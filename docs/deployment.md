# Deployment

How Classnode runs in production, and how a release gets there. The files are
in `deploy/`; the images are built by CI. Decided 2026-09-23 (the hosting
proposal): one server (any Ubuntu 24.04 VPS, Contabo or similar), Docker Compose, a wildcard certificate validated
through Cloudflare DNS, no connection pooler, WAL-G backups to Backblaze B2 with
a weekly automatic restore test, Sentry (EU) for errors, and deploys by a manual
button.

**Status: nothing is provisioned.** No domain is registered and no paid account
exists yet. Everything in this document that needs one is marked **[needs …]**.

## The shape

```
internet ──443──▶ caddy ──http──▶ web (gunicorn) ──▶ db (Postgres 15)
                   │  │               worker (Celery) ─┤      redis
                   │  │               media (Celery, -Q media) ─┘
                   │  └─ reads /srv/classnode/media (read-only), only when web says so
                   └─ one wildcard certificate: PLATFORM_DOMAIN and *.PLATFORM_DOMAIN
```

- **One domain setting.** `PLATFORM_DOMAIN` in `deploy/production.env` is the
  only place the domain is named (`classnode.co`). Django
  derives the session cookie's domain, the allowed hosts and the default From
  address from it, and Caddy derives its certificate and site addresses from
  it. Every school is `<slug>.PLATFORM_DOMAIN`: the session cookie spans the
  portal and every school, so a school cannot bring a domain of its own.
- **TLS ends at Caddy.** Django is told so by `TLS_TERMINATED_BY_PROXY=1`, which
  turns on the proxy header, the HTTPS redirect and HSTS together
  (`settings.py`, "Behind the TLS proxy"). `TRUSTED_PROXY_COUNT=1` makes the
  sign-in throttle count the client and not Caddy.
- **No connection pooler, ever in transaction mode** — `docs/tenancy.md`, "The
  connection rule".
- **`/healthz/`** answers on every host, ahead of tenancy and of the HTTPS
  redirect: 200 when the database answers, 503 when it does not.

## Configuration and secrets

| where | what | in the repo? |
|---|---|---|
| `deploy/production.env` | everything not secret: the domain, the proxy switches, service names | yes |
| `/etc/classnode/secrets.env` (server, mode 600) | `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, SMTP credentials (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `MESSAGING_EMAIL_PROVIDER=messaging.smtp.SmtpProvider` — `docs/messaging.md` M10; for SMS `MESSAGING_PHONE_PROVIDER=messaging.termii.TermiiProvider`, `TERMII_API_KEY`, `TERMII_SENDER_ID` — M11), `SENTRY_DSN` **[needs Sentry, H3]**, WAL-G/B2 keys **[needs B2, H3]** | **never** |
| `/etc/classnode/caddy.env` (server, mode 600) | `CLOUDFLARE_API_TOKEN` **[needs Cloudflare]**, `ACME_EMAIL` | **never** |
| `/etc/classnode/backup.env` (server, mode 600; optional until B2 exists) | `WALG_S3_PREFIX`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT`, `AWS_REGION` **[needs B2]**, `WALG_LIBSODIUM_KEY` (the backup encryption key — **also in your password manager**), `BACKUP_HEARTBEAT_URL` **[needs Sentry]** | **never** |
| GitHub repository secrets | `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` **[needs the server]** | **never** |

**Hosts and origins are read from the environment, and default to the domain.**
`DJANGO_ALLOWED_HOSTS` (comma-separated; default `.PLATFORM_DOMAIN`, the domain
and every subdomain) and `DJANGO_CSRF_TRUSTED_ORIGINS` (comma-separated full
origins, `https://…`; default **none**). Neither is secret, so either goes in
`deploy/production.env` if a deployment needs it. The CSRF list is empty on
purpose: the platform never posts across hosts (`docs/sign-in-page.md`), so the
same-origin check is the whole rule and an extra origin needs a reason.

**The repository is private.** The server reads it with a read-only GitHub deploy
key of its own (`/home/deploy/.ssh/classnode_repo`, origin `git@github.com:...`), so
the deploy button's `git fetch` works without a password. The images on `ghcr.io` are
private too: `deploy.sh` logs in from the root-only `/root/ghcr-login` for each deploy
and keeps no copy. The setup, and renewing the token that expires, are
`docs/first-day.md` steps 6 and 12. CI needs nothing extra: the workflows use the
run's own `GITHUB_TOKEN` (`contents: read`, `packages: write`) to check out and push.

**One layout on the server.** The repository is cloned to `/opt/classnode`, so the
deploy files are in `/opt/classnode/deploy/`, and that is the directory every
command runs from: `deploy.sh`, `restore-check.sh`, the cron jobs
(`deploy/cron/classnode`) and the deploy workflow's SSH command all use it.
`deployed-sha` is written there too. `tests/test_deployment.py` fails when a path
on the server stops matching the repository.

Keep a copy of every secret in a password manager. A secret that exists only on
the server is lost with it — for the backup encryption key (H3), that means the
backups are lost too.

## Images

CI (`.github/workflows/tests.yml`, job `image`) builds the images alongside the
suite, and on `main` pushes them as `candidate-<sha>`. Once the suite has passed
on that commit, job `publish` gives them the commit's full SHA as their tag,
without rebuilding them:

- `ghcr.io/adedejimakinde/luffy-school-saas:<sha>` — the application, which
  `web` and `worker` both run.
- `ghcr.io/adedejimakinde/luffy-school-saas/caddy:<sha>` — Caddy with the
  Cloudflare DNS module.

Before pushing, the job renders a PDF inside the application image, runs
`check --deploy` inside it under `production.env`, validates the Caddyfile and
validates the compose file. It pushes from `main` only, and nothing deploys a
`candidate-` tag.

**Caddy is built only when `deploy/caddy` changed** (`scripts/caddy-image.sh`).
The build downloads about two hundred Go modules and checks them against
sum.golang.org, and run 525 on `main` failed there (a reset from the checksum
server) on a commit that touched nothing under `deploy/`. For every other commit
the job pulls the `caddy:<sha>` published for the last commit that changed
`deploy/caddy`, which is built from exactly the files now in the directory, and
renames it. A commit that changes `deploy/caddy` has no such image and is built,
so a Dockerfile change is still built on its pull request. There is no retry: a
build that fails fails the job.

## Deploying

1. Pick the commit: a full SHA on `main` whose CI passed.
2. Run the **deploy** workflow (Actions → deploy → Run workflow) with that SHA.
   **[needs the server and the three deploy secrets]** It refuses a SHA that is
   not on main, or on which `test`, `image` and `publish` did not all pass. It
   then moves the server's checkout at `/opt/classnode` to exactly that SHA
   (`git fetch origin main`, `git checkout --detach <sha>`, then asks git that
   `HEAD` is the SHA; it refuses a checkout with local edits), so that
   `compose.yml` and `deploy.sh` are the release's own, and runs
   `/opt/classnode/deploy/deploy.sh <sha>` on the server over SSH. If the deploy
   fails it puts the checkout back on `deployed-sha`, the commit still running.
   **A rollback is never silent:** the run is named `deploy <sha>`; before the
   checkout moves, a SHA that does not contain the one in `deployed-sha` (an
   older commit, or one git cannot place) is refused unless the **rollback**
   box is ticked; and the last step reads `deployed-sha` back, puts the SHA
   asked for and the SHA running in the run's summary, and fails the run when
   they differ. Decided 2026-10-18, after two green runs deployed a week-old SHA
   (`docs/handover.md`).
3. `deploy.sh` pulls the two images, migrates with the new image while the old
   one serves, swaps `web`, `worker` and `caddy`, and asks `/healthz/` inside
   the container and then through Caddy over HTTPS. Unhealthy: it puts the
   previous SHA's images back and exits non-zero.

Deploy after school hours: the web process restarts for a few seconds.

**Migrations are not rolled back.** A migration that old code cannot run
against — dropping or renaming something it reads — ships in two deploys: the
first stops using the thing, the second removes it. A deploy that breaks that
rule is recovered by restoring the database (H3), not by rolling back images.

## Postgres settings

`deploy/postgres/settings.sh` is the one place every Postgres in this repository
takes its server settings from: production's database (`entrypoint.sh`), the
weekly restore test's (`restore-serve.sh`), the suite's and the screens job's in
CI (`.github/actions/test-database`), and the development compose file, which
repeats the number. Today it holds one:

- **`max_locks_per_transaction = 512`** (Postgres's default is 64). Postgres keeps
  every lock in one pool of `max_locks_per_transaction x (max_connections +
  max_prepared_transactions)` slots, 6,400 by default. **Making a school is one
  transaction** that holds a lock on every table and index it creates until it
  ends: about 1,350 for `School.save()` (CREATE SCHEMA and every migration inside
  `create_school`'s transaction; 69 tables, 222 indexes), and about 1,700 for the
  suite's clone of the template. That is a fifth of the default pool for one
  school in production, and it is what failed CI: four parallel workers each
  holding a few schools used the pool up and the next lock request anywhere
  failed with `out of shared memory`. 512 makes the pool 51,200, about thirty
  schools at once. The cost is some tens of megabytes of shared memory.
  `schools/tests/test_lock_budget.py` measures the locks a school holds, on
  whatever database the suite runs against, and fails with the setting to raise
  when the suite's worst case at once (four workers, three schools each, a
  quarter to spare) stops fitting: add tables until it does and it says so
  before CI turns flaky.

**Applying it to production needs a Postgres restart, and the next deploy does it
with no manual step.** The setting is read when the server starts, so a running
server cannot take it (`pg_reload_conf()` does not help). It is passed as an
argument to `postgres` by `entrypoint.sh`, which is part of the `db` image, and
`compose.yml` names that image by the commit being deployed
(`postgres:${CLASSNODE_TAG}`), so `docker compose up -d db` in `deploy.sh` step 2
recreates the container, and the new one starts with the argument. The database
is unavailable for the few seconds that takes, before step 2's migration runs and
while the old `web` is still serving, so deploy after school hours, as above.
Existing data is untouched: the setting lives in the command line, not in the
data directory.

After the first deploy that carries it, check, on the server, in
`/opt/classnode/deploy`:

```
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SHOW max_locks_per_transaction"'
```

It must print `512`. If it prints `64` the container was not recreated; run
`docker compose up -d --force-recreate db` (the same few seconds, out of hours)
and ask again. Do not set it with `ALTER SYSTEM` or by editing `postgresql.conf`
in the data directory: the argument overrides both, and a second place to
change is how the two come to disagree.

**A backup is restored with at least the limit of the server that made it.**
Postgres refuses to recover WAL written by a server that had a higher limit than
the recovering one. `restore-serve.sh` takes the same settings for that reason;
a restore by hand onto another Postgres must start it with the same
`max_locks_per_transaction` (backups made under 64 restore under 512 without
change).

CI proves it at three points, all by asking the running server and not the file:
the `test-database` action prints the live values (and puts them in the run's
summary) and fails the job if one differs; the `image` job's
`deploy/postgres/test-backup.sh` starts the production image and fails if it did
not start with them; and the suite checks the database it runs on.

## Migration order

The order of everything that changes the schema, so it is never reasoned out at a
shell on a deploy night.

1. **A deploy** runs `migrate_schemas --noinput` (`deploy/deploy.sh`, step 2),
   with the **new** image, **before** `web`, `worker` and `caddy` are swapped:
   the old code keeps serving while it runs. `migrate_schemas` does `public`
   first (the shared apps), then every school's schema, one after another.
   Public first, because every request reads it before it knows which school it
   is for. A migration can only be additive for this to be safe (see
   "Deploying" above).
2. **A migration that fails** stops the deploy there (`set -e`): nothing has been
   swapped, the old code is still serving, and the schemas already done stay
   done. Fix the cause and run `deploy.sh` again for the same SHA; every
   migration is recorded per schema, so what ran is not run twice. `/healthz/`
   answers 200 throughout, so it will not tell you a school is behind:
   `docker compose run --rm --no-deps web python manage.py verify_restore` does
   (it lists every school and migration that is missing).
3. **The first deploy ever** has no tables at all: `deploy.sh` migrates
   `public` (there are no schools to do), and only then does onboarding start,
   in the order above: `setup_portal`, `createsuperuser`, `create_school`.
   `create_school` builds and migrates its own schema, so nothing is run by
   hand for a new school, and it never runs before the first deploy.
4. **A restore** brings back the migrations that were recorded when the backup
   was taken. Deploy the commit that was running then, or a later one: its
   `migrate_schemas` brings every schema forward. `verify_restore` is the
   question to ask first.

## Onboarding: the portal, then each school

Both are commands run in a shell on the server
(`docker compose run --rm web python manage.py …`), never from the admin:
making a school builds and migrates a Postgres schema, which does not belong
inside a web request.

1. `setup_portal` — the portal answers on `PORTAL_HOST`, which is
   `app.PLATFORM_DOMAIN` unless set otherwise. Safe to re-run.
2. `createsuperuser` — the platform operator. Platform staff act across
   schools; a school's own administrator never is one.
3. `create_school <slug> "<name>" --admin-email … --operator <username>` —
   builds the school's schema, gives it `<slug>.PLATFORM_DOMAIN`, and invites
   its first administrator. **With an email provider**, the invitation is
   emailed. **Without one** (decided 2026-09-24) nothing is sent: the command
   prints the accept link for the operator to hand to the administrator. The
   link makes whoever opens it that school's administrator until it is used or
   expires, so it goes to that person and nowhere else. With no accept page to
   link to, the whole school is refused — there would be nothing to hand over.

Every host is one label under `PLATFORM_DOMAIN` (`schools/onboarding.py`,
`check_host`): under it, because the session cookie spans them all; one label,
because the wildcard certificate covers nothing deeper. `app`, `www`, `api`,
`admin`, `mail`, `static`, `portal`, `public` and the portal's own label are
reserved.

The invitation link lands on `/invitations/<token>/` on the portal
(`INVITATION_ACCEPT_URL`, derived from `PORTAL_HOST`). The page takes a
password if the invitee has none, and ends at the staff sign-in door.

## Backups

**Continuous WAL archiving to B2, plus a nightly base backup** (decided
2026-09-23), so the database restores to any moment in the last week, losing
at most the minute `archive_timeout` allows. `deploy/postgres/` is the image:
Postgres 15 (Debian) with WAL-G pinned by version and checksum.

- **Archiving is off until B2 is configured.** `classnode-postgres` turns it on
  only when `WALG_S3_PREFIX` is set — an archive command that cannot succeed
  makes Postgres keep every WAL segment until the disk fills.
- **Nightly** (`deploy/cron/classnode`, 00:30 UTC): `classnode-backup` fails if
  the archiver has started failing, then pushes a base backup and applies
  retention — 7 nightly, 4 weekly, 12 monthly (`deploy/postgres/retention.py`,
  tested in `tests/test_backup_retention.py`). It checks in to the
  `nightly-backup` heartbeat either way. Cron runs it as plain
  `docker compose exec -T db classnode-backup`, as root, and the script hands itself
  to the `postgres` user; CI runs exactly that against a real Postgres container
  (`deploy/postgres/test-backup.sh`).
- **A failed or missing backup is reported by the heartbeat and by nothing else**:
  cron mails nobody and the log file is read by nobody. So `BACKUP_HEARTBEAT_URL`
  is set in practice, with the Sentry monitor's schedule (`30 0 * * *` UTC) and its
  alert going to two people (`docs/first-day.md`, steps 24 and 26). A run that
  fails inside the script checks in `error`; one that never reaches the script (the
  container is down, the tag file is wrong) checks in nothing, and the monitor alerts
  on the missed check-in.
- **Encrypted before upload** with `WALG_LIBSODIUM_KEY`. Keep that key in a
  password manager as well as on the server: without it the backups are noise.

**[needs B2]** for all of it; until then the nightly job fails loudly by design.

## Uploaded files

Every upload (crests, photos, signatures, website pictures, documents, the
hero loop) goes through one service, `files` (docs/school-sites.md §9). The
bytes are **on the server's data volume, never in Postgres**:

- **Where**: `/srv/classnode/media` on the host, `/srv/media` in the
  containers (`FILES_ROOT`). One directory per school's schema, then the key.
  `web`, `worker` and `media` write to it as the app's user (uid 10001, which
  `deploy/deploy.sh` makes sure of on every deploy); Caddy mounts it read-only.
- **Processing**: on the `media` Celery queue, served by the `media` service,
  one job at a time at low priority. The upload screen answers at once and
  says "being prepared" until the job is done.
- **Sending**: Django decides who may have a file (the school's own schema,
  public or the school's office only) and answers with `X-Accel-Redirect`;
  Caddy's `handle_response` sends it. Gunicorn never streams a file.
- **Quota**: 1 GB per school by default, changed per school on the platform
  page (`/platform/`, "Storage"), which also shows each school's total.
- **The disk**: `manage.py check_storage` runs hourly (`deploy/cron/classnode`),
  writes a line to `/var/log/classnode-storage.log`, and past **70%** emails
  `OPS_ALERT_EMAIL` (hello@ the platform's domain) once a day; past **90%**
  uploads are refused and it emails every hour.
- **Alerts** go by email through the ordinary email settings, and are printed
  to the cron log. Sentry is optional here: `DISK_HEARTBEAT_URL` and
  `MEDIA_BACKUP_HEARTBEAT_URL` in `backup.env`, if set, get `ok`/`error`
  check-ins for a cron monitor later.

### The files' backup

**restic, encrypted, to the same B2 bucket and prefix as the database**, under
`media/` (`s3:<AWS_ENDPOINT>/<bucket>/classnode/media`), so a B2 key limited to
`classnode/` covers it. `deploy/media-backup.sh` in the `media-backup` service
(compose profile `backup`):

- **Nightly, 01:45 UTC**: `backup` sends what is new (file names never change,
  so that is only the day's uploads) and keeps 14 daily, 8 weekly and 12
  monthly snapshots. Log: `/var/log/classnode-media-backup.log`.
- **Weekly, Sunday 03:30 UTC**: `check` prunes, checks 2% of the repository's
  data, and restores ten random files older than two days, comparing each with
  the disk.
- **Setting it up, and whenever the key or prefix changes**: `test` makes the
  repository if there is none, backs up one new file, restores it and compares
  it byte for byte. A wrong key, endpoint, prefix or password fails here, at once.
- **Encrypted** with `MEDIA_RESTIC_PASSWORD` in `backup.env`
  (`deploy/init-env.sh media-backup` adds a generated one to a `backup.env` made
  before this existed). Keep it in the password manager beside
  `WALG_LIBSODIUM_KEY`: without it the backup is noise.
- **A failure is emailed** to `OPS_ALERT_EMAIL` and written to the log.

To restore everything onto a new server (after `deploy/bootstrap.sh` and the
env files):

```
cd /opt/classnode/deploy
docker compose --profile backup run --rm --no-deps -v /srv/classnode/media:/restore media-backup restore /restore
```

It reads the repository and password from `backup.env`, and puts every file of
the latest snapshot back where it was, under `/srv/classnode/media`.

### Moving the files that were in Postgres

Crests, children's photos and the blog's pictures were kept in database
columns before the service existed. `manage.py move_files_to_disk` copies
them through the same processing: a dry run by default, `--apply` to do it,
`--rollback --apply` to copy the current files back into the columns (so the
previous release shows the same thing) and remove them. The columns are left
in place until a later release drops them, after a backup cycle.

## The weekly restore test

`deploy/restore-check.sh` (Sunday 02:00 UTC): recovers the latest backup into
a throwaway `restore-db`, waits for recovery to finish, then runs
`manage.py verify_restore` against it — every school has its schema, `public`
has every shared migration, every school's schema has every tenant migration,
and one school's tables hold the rows the live database held just before the
restore began, give or take the last minute's writes (`schools/restore_check.py`;
`RESTORE_CHECK_SCHOOL=<slug>` picks the school, else the first by slug). The
commands to run it, and to restore for real, are in `docs/demo-server.md`,
section 7. It tears the throwaway database and its volume
down whatever happened. The verdict checks in to Sentry's `restore-check`
monitor; a restore that never becomes ready never checks in, and the monitor
alerts on the silence. **[needs B2 and Sentry]**

Before launch, once B2 exists: a **timed full restore onto a fresh server**, by
hand, following this document. That time is the recovery time.

## Error reports

Sentry, EU region, **only when `SENTRY_DSN` is set** (settings.py). Personal
data, stack-frame locals and request bodies are never sent. `schools/errors.py`
drops cookies, query strings and most headers, scrubs invitation tokens out of
every URL (the address is a credential), drops SQL breadcrumbs (their
parameters are children's names), and tags every report with the school.
**[needs Sentry]**

## Still to come

- **The launch session** — provisioning the server, DNS, secrets, the first
  deploy, a timed full restore drill, and onboarding the first school. Every
  step there needs an account; see "What each step needs" below. The
  walkthrough, for a non-technical owner on Windows, is `docs/first-day.md`;
  `deploy/bootstrap.sh` (safe to re-run) and `deploy/init-env.sh` are its scripts.

## What each step needs

| step | needs |
|---|---|
| H1, H2, H3 as code, tests and CI | nothing — no account and no domain |
| First CI push of images to GHCR | nothing new (GitHub's own token); the three packages must be private and list this repository under Manage Actions access with Write |
| The server downloading the code and images (private repository) | a read-only deploy key added in GitHub, and a classic token with `read:packages` that **expires** (`docs/first-day.md` steps 6 and 12) |
| Provisioning the server | the VPS account (any Ubuntu 24.04 VPS, Contabo or similar), your SSH public key, your admin IPs |
| DNS records and the first certificate | the domain registered, the zone on Cloudflare, a DNS-edit token for that zone |
| Emailing invitations (until then `create_school` prints the link to hand over) | a transactional email provider, and SPF/DKIM/DMARC on the domain |
| The first backup and restore drill | B2 bucket and key, a backup encryption key held offline |
| Error reports, and the backup and restore heartbeats | Sentry (EU) project, its DSN, and two cron monitors (`nightly-backup`, `restore-check`) |
| Real children's data | your confirmation on data residency (NDPA, OPEN-9) |
