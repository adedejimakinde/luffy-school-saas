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

## Still to come

- **H2** — the invitation accept page (without it no invited teacher can
  join) and a `create_school` command for onboarding.
- **H3** — WAL-G to B2, the weekly automatic restore test, and Sentry.
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
| Sending the first invitation | a transactional email provider, and SPF/DKIM/DMARC on the domain |
| The first backup and restore drill | B2 bucket and key, a backup encryption key held offline |
| Error reports | Sentry (EU) project and its DSN |
| Real children's data | your confirmation on data residency (NDPA, OPEN-9) |
