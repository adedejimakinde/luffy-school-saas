# Deployment

How Classnode runs in production, and how a release gets there. The files are
in `deploy/`; the images are built by CI. Decided 2026-09-23 (the hosting
proposal): one Hetzner server, Docker Compose, a wildcard certificate validated
through Cloudflare DNS, no connection pooler, WAL-G backups to Backblaze B2 with
a weekly automatic restore test, Sentry (EU) for errors, and deploys by a manual
button.

**Status: nothing is provisioned.** No domain is registered and no paid account
exists yet. Everything in this document that needs one is marked **[needs …]**.

## The shape

```
internet ──443──▶ caddy ──http──▶ web (gunicorn) ──▶ db (Postgres 15)
                   │                  worker (Celery) ─┘      redis
                   └─ one wildcard certificate: PLATFORM_DOMAIN and *.PLATFORM_DOMAIN
```

- **One domain setting.** `PLATFORM_DOMAIN` in `deploy/production.env` is the
  only place the domain is named (planned value: `classnode.africa`). Django
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
| `/etc/classnode/secrets.env` (server, mode 600) | `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, SMTP credentials **[needs email provider]**, `SENTRY_DSN` **[needs Sentry, H3]**, WAL-G/B2 keys **[needs B2, H3]** | **never** |
| `/etc/classnode/caddy.env` (server, mode 600) | `CLOUDFLARE_API_TOKEN` **[needs Cloudflare]**, `ACME_EMAIL` | **never** |
| `/etc/classnode/backup.env` (server, mode 600; optional until B2 exists) | `WALG_S3_PREFIX`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT`, `AWS_REGION` **[needs B2]**, `WALG_LIBSODIUM_KEY` (the backup encryption key — **also in your password manager**), `BACKUP_HEARTBEAT_URL` **[needs Sentry]** | **never** |
| GitHub repository secrets | `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` **[needs the server]** | **never** |

Keep a copy of every secret in a password manager. A secret that exists only on
the server is lost with it — for the backup encryption key (H3), that means the
backups are lost too.

## Images

CI (`.github/workflows/tests.yml`, job `image`) builds two images after the
suite passes, and tags both with the commit's full SHA:

- `ghcr.io/adedejimakinde/luffy-school-saas:<sha>` — the application, which
  `web` and `worker` both run.
- `ghcr.io/adedejimakinde/luffy-school-saas/caddy:<sha>` — Caddy with the
  Cloudflare DNS module.

Before pushing, the job renders a PDF inside the application image, runs
`check --deploy` inside it under `production.env`, validates the Caddyfile and
validates the compose file. It pushes from `main` only.

## Deploying

1. Pick the commit: a full SHA on `main` whose CI passed.
2. Run the **deploy** workflow (Actions → deploy → Run workflow) with that SHA.
   **[needs the server and the three deploy secrets]** It refuses a SHA that is
   not on main, or on which `test` and `image` did not both pass, and then
   runs `/opt/classnode/deploy.sh <sha>` on the server over SSH.
3. `deploy.sh` pulls the two images, migrates with the new image while the old
   one serves, swaps `web`, `worker` and `caddy`, and asks `/healthz/` inside
   the container and then through Caddy over HTTPS. Unhealthy: it puts the
   previous SHA's images back and exits non-zero.

Deploy after school hours: the web process restarts for a few seconds.

**Migrations are not rolled back.** A migration that old code cannot run
against — dropping or renaming something it reads — ships in two deploys: the
first stops using the thing, the second removes it. A deploy that breaks that
rule is recovered by restoring the database (H3), not by rolling back images.

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
  `nightly-backup` heartbeat either way.
- **Encrypted before upload** with `WALG_LIBSODIUM_KEY`. Keep that key in a
  password manager as well as on the server: without it the backups are noise.

**[needs B2]** for all of it; until then the nightly job fails loudly by design.

## The weekly restore test

`deploy/restore-check.sh` (Sunday 02:00 UTC): recovers the latest backup into
a throwaway `restore-db`, waits for recovery to finish, then runs
`manage.py verify_restore` against it — every school has its schema, `public`
has every shared migration, every school's schema has every tenant migration
(`schools/restore_check.py`). It tears the throwaway database and its volume
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
  step there needs an account; see "What each step needs" below.

## What each step needs

| step | needs |
|---|---|
| H1, H2, H3 as code, tests and CI | nothing — no account and no domain |
| First CI push of images to GHCR | nothing new (GitHub's own token) |
| Provisioning the server | Hetzner project, your SSH public key, your admin IPs |
| DNS records and the first certificate | the domain registered, the zone on Cloudflare, a DNS-edit token for that zone |
| Emailing invitations (until then `create_school` prints the link to hand over) | a transactional email provider, and SPF/DKIM/DMARC on the domain |
| The first backup and restore drill | B2 bucket and key, a backup encryption key held offline |
| Error reports, and the backup and restore heartbeats | Sentry (EU) project, its DSN, and two cron monitors (`nightly-backup`, `restore-check`) |
| Real children's data | your confirmation on data residency (NDPA, OPEN-9) |
