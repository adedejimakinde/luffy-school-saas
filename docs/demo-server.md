# The demo server: classnode.co

A throwaway server that holds the two fictional demo schools and nothing real,
so people can click through Classnode. One Hetzner CX23 (Ubuntu 24.04), DNS on
Cloudflare, the same compose stack as production (`deploy/compose.yml`,
`docs/deployment.md`). When it is up:

| address | what |
|---|---|
| `https://app.classnode.co/` | the portal: staff sign in at `/staff-sign-in/` |
| `https://sunrise-demo.classnode.co/` | Sunrise Demo Academy's public page |
| `https://harbour-demo.classnode.co/` | Harbour Demo College's public page |

The server runs the same `deploy/deploy.sh` as production: the domain is
`classnode.co` in `deploy/production.env`, so nothing is overridden.

**Status: written, not yet run on a real server.** Every command below is from
the repository's own files; the Cloudflare token scope and the Docker install are
from the tools' documentation and have not been exercised here. The first run is
the test: if a step is wrong, fix this file in the same change.

**What a demo server is not.** No backups (no B2, so WAL archiving stays off; section 7
is how to turn them on, and how to restore, for a server that has B2), no
error reports, no email, no SMS. Do not put a real child's name on it. It is
rebuilt, not repaired (last section).

## 0. What you need before you start

- The server's public IPv4 address (and IPv6, if you want it).
- `classnode.co` registered, with its zone on Cloudflare.
- A GitHub token with `read:packages` only, for the server to pull our images
  (step 2 says how to make it and where it goes).
- A commit SHA on `main` that **includes `load_demo`** and whose CI `publish` job
  passed (Actions, the commit's checks). The images are tagged with that full
  40-character SHA and nothing else (`docs/deployment.md`, "Images").

## 1. Cloudflare

### DNS records (zone `classnode.co`)

| type | name | content | proxy |
|---|---|---|---|
| A | `classnode.co` (the apex, `@`) | the server's IPv4 | **DNS only** (grey cloud) |
| A | `app` | the server's IPv4 | **DNS only** |
| A | `*` | the server's IPv4 | **DNS only** |
| AAAA | `@`, `app`, `*` | the server's IPv6 (optional) | **DNS only** |

The `*` record covers `sunrise-demo` and `harbour-demo`, and any school added
later. Leave the cloud grey: Caddy holds the wildcard certificate itself, and an
orange cloud would put Cloudflare's certificate and proxy in front of it. The apex
record is there because the public homepage answers on it (`docs/website.md`) and `deploy.sh` checks `https://classnode.co/healthz/` through
Caddy (the certificate covers the apex too), and `app` is listed apart from `*`
because it is the one name the portal must answer on.

### The API token Caddy needs

Caddy proves it owns the wildcard by writing a `_acme-challenge` TXT record
(DNS-01), so it needs to edit DNS, and to look the zone up.

Cloudflare dashboard, My Profile, API Tokens, Create Token, **Create Custom
Token**:

- Permissions: **Zone, DNS, Edit** and **Zone, Zone, Read**.
- Zone Resources: **Include, Specific zone, `classnode.co`**.
- Nothing else: no account permissions, no other zones, no expiry you would
  forget about (set one if you like and note the date).

Copy the token once; it goes in `caddy.env` below and nowhere else.

## 2. The server

As root on the fresh server.

```bash
# Updates, a firewall that lets in SSH, HTTP and HTTPS (443 also over UDP: HTTP/3).
apt-get update && apt-get -y upgrade
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
ufw --force enable

# Docker Engine and the compose plugin, from Docker's own apt repository.
apt-get -y install ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin

# The deploy files, at the commit you are running.
git clone https://github.com/adedejimakinde/luffy-school-saas.git /opt/classnode
cd /opt/classnode && git checkout <the full commit SHA>

# Where the data and the secrets live (compose's defaults).
mkdir -p /srv/classnode/postgres /srv/classnode/redis /etc/classnode
chmod 700 /etc/classnode
```

### How the server pulls our images from GHCR

CI publishes the images to `ghcr.io/adedejimakinde/luffy-school-saas` (and
`/caddy`, `/postgres`), and a package is private until someone makes it public.
The server signs in to GHCR **once**, with a token that can do nothing else:

1. On GitHub, as an account that can read this repository (its packages inherit
   that access): Settings, Developer settings, Personal access tokens, **Tokens
   (classic)**, Generate new token (classic). Fine-grained tokens do not cover
   packages.
2. Tick **`read:packages` and nothing else** (not `repo`, not `write:packages`).
   Give it an expiry and put the date somewhere you will see it: when it lapses
   every pull fails with `denied` until a new one is logged in.
3. On the server, as root, once (the token is read from the pipe, so it is not in
   shell history or the process list):

   ```bash
   read -r -s -p "GitHub token: " GHCR_TOKEN; echo
   echo "$GHCR_TOKEN" | docker login ghcr.io -u <that account's GitHub username> --password-stdin
   unset GHCR_TOKEN
   ```

Docker keeps the result in `/root/.docker/config.json`, which is the token in a
reversible form: it is root's file, so use the token for nothing else and do not
copy it into `secrets.env`, `caddy.env` or any compose file. Nothing else is
needed: `docker compose pull` (inside `deploy.sh`) uses it from then on. To
revoke, delete the token on GitHub and `docker logout ghcr.io`.

(Docker published ports bypass `ufw`'s rules; only 80 and 443 are published, and
the database and Redis publish nothing, so this is fine. Do not add ports to the
compose file.)

## 3. The env values

The domain, `PLATFORM_DOMAIN=classnode.co`, is already in the committed
`deploy/production.env`; only the secrets are written on the server.

Make the two secrets once and keep them in a password manager:

```bash
openssl rand -base64 48 | tr -d '\n'   # DJANGO_SECRET_KEY
openssl rand -base64 32 | tr -d '\n'   # POSTGRES_PASSWORD (any characters but = and spaces are fine)
```

`/etc/classnode/secrets.env` (mode 600):

```
DJANGO_SECRET_KEY=<first value>
POSTGRES_PASSWORD=<second value>
DEMO_SERVER=1
```

`/etc/classnode/caddy.env` (mode 600):

```
CLOUDFLARE_API_TOKEN=<the token from step 1>
ACME_EMAIL=<an address you read>
```

```bash
chmod 600 /etc/classnode/secrets.env /etc/classnode/caddy.env
```

Everything else comes from `production.env` as committed (`TLS_TERMINATED_BY_PROXY=1`,
`TRUSTED_PROXY_COUNT=1`, the service names, `TIME_ZONE`). Leave `PAYSTACK_*`,
`MESSAGING_*`, `SENTRY_DSN` and the email settings unset: with no phone provider
nothing can send an SMS, which is what a demo wants.

`DEMO_SERVER=1` is what lets `load_demo` run. **Never set it anywhere that holds
real data.** The demo password is *not* in either file: you type it in step 5.

## 4. Deploy

Exactly as production does it (`docs/deployment.md`, "Deploying"): `deploy.sh`
pulls the images for the SHA, starts the database and Redis, migrates, starts web,
worker and Caddy, and checks `/healthz/` inside the container and then through
Caddy over HTTPS at `https://classnode.co/healthz/`.

```bash
/opt/classnode/deploy/deploy.sh <the full commit SHA>
```

It ends with `DEPLOYED <sha>`. The first time, Caddy has to get the wildcard
certificate from Let's Encrypt through Cloudflare, which can take longer than the
script waits (about a minute): if it says `NOT HEALTHY` and
`docker compose logs caddy` shows the certificate still being obtained, wait for
`certificate obtained`, then run the same command again (it is safe to repeat). A
real error in that log is step 1 (the token, the records).

Every `docker compose` command after this needs the tag in its shell:

```bash
cd /opt/classnode/deploy && export CLASSNODE_TAG=$(cat deployed-sha)
```

## 5. Make the portal and load the demo

```bash
# The portal answers on app.classnode.co. Safe to re-run.
docker compose run --rm web python manage.py setup_portal

# The demo schools. Type the password without it landing in shell history; at
# least 12 characters, and it is not stored anywhere on the server.
read -r -s -p "Demo password: " LOAD_DEMO_PASSWORD; echo
export LOAD_DEMO_PASSWORD
docker compose run --rm -e LOAD_DEMO_PASSWORD web python manage.py load_demo
unset LOAD_DEMO_PASSWORD
```

`load_demo` (`schools/management/commands/load_demo.py`) loads the same two
fictional schools as `seed_demo`: 20 children each, a term of marks, registers,
timetable and fees, a released result sheet, and one login per role. It:

- **refuses unless `DEMO_SERVER=1`** is in the container's environment;
- **refuses without `LOAD_DEMO_PASSWORD`** (12 characters or more): there is no
  default, and it never takes the password as an argument or prints it;
- messages no family and stores no phone number, so it needs no message provider;
- refuses to run a second time (to start again, see the last section).

It prints each school's address and every username (`sunrise.admin`,
`sunrise.principal`, `sunrise.vp`, `sunrise.teacher`, `sunrise.bursar`,
`sunrise.english`, `sunrise.science`, `sunrise.parent`, and the same with
`harbour.`). Each takes the password you typed.

Optional: `docker compose run --rm web python manage.py createsuperuser` makes a
platform operator, who can open `/platform/` on the portal.

## 6. Check it

- `https://sunrise-demo.classnode.co/` shows the school's page, with "Staff sign
  in" at the bottom.
- That link, or `https://app.classnode.co/staff-sign-in/`, takes `sunrise.admin`
  and the demo password, and lands on the school's home.
- `https://app.classnode.co/` over plain `http://` redirects to HTTPS.

**The demo parent cannot sign in.** Parents sign in with a code sent to their
phone, and the demo has no provider and no phone on file. Show the parent's side
from the staff logins (a released card is on JSS 1B's class page).

## 7. Backups and restore (only once there is a B2 bucket)

The demo needs none of this. A server that will hold real data does, and these are
its commands, all run from `/opt/classnode/deploy` with the tag in the shell
(step 4). What was run: the pinned WAL-G (the `Dockerfile`'s version and checksum)
took a base backup, archived WAL, and restored to the last archived write, against
a throwaway Postgres with file storage in place of B2. **Not run:** anything in
Docker, or against B2.

**Turn it on.** `/etc/classnode/backup.env` (mode 600), from a B2 bucket and an
application key limited to it:

```
WALG_S3_PREFIX=s3://<bucket>/classnode
AWS_ACCESS_KEY_ID=<B2 key id>
AWS_SECRET_ACCESS_KEY=<B2 application key>
AWS_ENDPOINT=https://s3.<region>.backblazeb2.com
AWS_REGION=<region>
WALG_LIBSODIUM_KEY=<openssl rand -hex 32>
WALG_LIBSODIUM_KEY_TRANSFORM=hex
BACKUP_HEARTBEAT_URL=<Sentry cron check-in URL for nightly-backup, optional>
```

Keep `WALG_LIBSODIUM_KEY` in a password manager too: without it the backups are
noise. Then recreate the database container, which is when archiving starts
(a few seconds of downtime: do it after school hours), and check it:

```bash
docker compose up -d --force-recreate db
docker compose logs db | grep classnode-postgres     # "archiving WAL to s3://..."
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT archived_count, failed_count, last_failed_time FROM pg_stat_archiver"'
```

**Back up** (the cron job does this nightly; run it by hand once to see it work),
and look at what is there:

```bash
docker compose exec -T db classnode-backup           # ends "classnode-backup: done"
docker compose exec -T db wal-g backup-list
cp /opt/classnode/deploy/cron/classnode /etc/cron.d/classnode   # the schedule, once
```

`classnode-backup` refuses to run when the WAL archiver has been failing, pushes a
base backup, and prunes to 7 nightly, 4 weekly and 12 monthly.

**Restore drill** (weekly by cron; run it by hand once before relying on it). It
counts one school's rows on the live database, recovers the latest backup into a
throwaway database, and requires that school's tables to hold those rows and every
school to have its schema and migrations. `RESTORE_CHECK_SCHOOL=<slug>` picks the
school (else the first by slug). The live database is not touched.

```bash
/opt/classnode/deploy/restore-check.sh               # prints "The restore is whole: ..." and the school's counts
```

**Restore for real** (the database is lost or wrong). On the server, stack stopped,
the old data kept aside. `LATEST` can be a backup name from `wal-g backup-list`;
without a recovery target the WAL is replayed to the end of what was archived.

```bash
cd /opt/classnode/deploy && export CLASSNODE_TAG=$(cat deployed-sha)
docker compose stop web worker caddy db
mv /srv/classnode/postgres /srv/classnode/postgres.old
install -d -m 700 -o 999 -g 999 /srv/classnode/postgres
docker compose run --rm --no-deps --entrypoint sh db -c "
  gosu postgres wal-g backup-fetch \"\$PGDATA\" LATEST &&
  gosu postgres touch \"\$PGDATA/recovery.signal\" &&
  echo \"restore_command = 'wal-g wal-fetch %f %p'\" >> \"\$PGDATA/postgresql.auto.conf\" &&
  echo \"recovery_target_action = 'promote'\" >> \"\$PGDATA/postgresql.auto.conf\""
docker compose up -d db
docker compose exec -T db sh -c 'until [ "$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT NOT pg_is_in_recovery()")" = t ]; do sleep 5; done'
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER SYSTEM RESET restore_command" -c "ALTER SYSTEM RESET recovery_target_action"'
docker compose run --rm --no-deps web python manage.py verify_restore
docker compose up -d web worker caddy
```

On a fresh server, do steps 2 and 3 first (the clone, Docker, the env files, the
GHCR login) and `docker compose pull`, then these. `verify_restore` ends the
restore: it must say `The restore is whole`. The time from the first command to
there is the recovery time (`docs/deployment.md`: time it once, by hand, before
launch).

## Updating and starting over

A new version: `cd /opt/classnode && git fetch && git checkout <the new SHA>`, then
`deploy/deploy.sh <the new SHA>`. The demo data stays.

Starting over (the data is disposable):

```bash
cd /opt/classnode/deploy && export CLASSNODE_TAG=$(cat deployed-sha)
docker compose down
rm -rf /srv/classnode/postgres /srv/classnode/redis && mkdir -p /srv/classnode/postgres /srv/classnode/redis
```

then `deploy.sh <sha>` again (step 4), then step 5. The certificate is kept in the `caddy-data` volume, so
this does not ask Let's Encrypt for a new one.

## If it does not come up

- **Caddy cannot get the certificate**: `docker compose logs caddy`. A 403 or
  "zone not found" is the token's scope or zone (step 1); "no such host" is a
  missing `*` record. Let's Encrypt rate-limits repeated failures, so fix the
  cause before restarting in a loop.
- **`docker compose` says set CLASSNODE_TAG**: the export is per shell (step 4).
- **`manifest unknown` or `denied` on pull**: `denied` is the GHCR login missing
  or its token expired (step 2); `manifest unknown` is a SHA whose images are not
  published (its `publish` job did not pass).
- **`load_demo` says "only runs on a demo server"**: `DEMO_SERVER=1` is not in
  `secrets.env`, or the file was edited after the container was created; `run`
  reads it fresh, so check the file.
- **A school's page says the host is not allowed**: the name is not under
  `PLATFORM_DOMAIN`; `docker compose run --rm --no-deps web printenv PLATFORM_DOMAIN`
  should say `classnode.co`.
