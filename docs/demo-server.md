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

**Status: written, not yet run on a real server.** Every command below is from
the repository's own files; the Cloudflare token scope and the Docker install are
from the tools' documentation and have not been exercised here. The first run is
the test: if a step is wrong, fix this file in the same change.

**What a demo server is not.** No backups (no B2, so WAL archiving stays off), no
error reports, no email, no SMS. Do not put a real child's name on it. It is
rebuilt, not repaired (last section).

## 0. What you need before you start

- The server's public IPv4 address (and IPv6, if you want it).
- `classnode.co` registered, with its zone on Cloudflare.
- A GitHub personal access token with `read:packages` (classic): the images are
  in GHCR and a package is private until someone makes it public.
- A commit SHA on `main` that **includes `load_demo`** and whose CI `publish` job
  passed (Actions, the commit's checks). The images are tagged with that full
  40-character SHA and nothing else (`docs/deployment.md`, "Images").

## 1. Cloudflare

### DNS records (zone `classnode.co`)

| type | name | content | proxy |
|---|---|---|---|
| A | `app` | the server's IPv4 | **DNS only** (grey cloud) |
| A | `*` | the server's IPv4 | **DNS only** |
| AAAA | `app`, `*` | the server's IPv6 (optional) | **DNS only** |

The `*` record covers `sunrise-demo` and `harbour-demo`, and any school added
later. Leave the cloud grey: Caddy holds the wildcard certificate itself, and an
orange cloud would put Cloudflare's certificate and proxy in front of it. Nothing
is needed at the apex (`classnode.co`) for the demo, and `app` is only listed
apart from `*` because it is the one name the portal must answer on.

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

# Sign in to GHCR so the images can be pulled (the token needs read:packages).
echo "<the GitHub token>" | docker login ghcr.io -u adedejimakinde --password-stdin

# The deploy files, at the commit you are running.
git clone https://github.com/adedejimakinde/luffy-school-saas.git /opt/classnode
cd /opt/classnode && git checkout <the full commit SHA>

# Where the data and the secrets live (compose's defaults).
mkdir -p /srv/classnode/postgres /srv/classnode/redis /etc/classnode
chmod 700 /etc/classnode
```

(Docker published ports bypass `ufw`'s rules; only 80 and 443 are published, and
the database and Redis publish nothing, so this is fine. Do not add ports to the
compose file.)

## 3. The env values

`deploy/production.env` names `classnode.africa`. The demo overrides it **on the
server**, without editing the committed file: in compose, a later `env_file`
wins, and `secrets.env` (for web, worker and db) and `caddy.env` (for Caddy) both
come after `production.env`.

Make the two secrets once and keep them in a password manager:

```bash
openssl rand -base64 48 | tr -d '\n'   # DJANGO_SECRET_KEY
openssl rand -base64 32 | tr -d '\n'   # POSTGRES_PASSWORD (any characters but = and spaces are fine)
```

`/etc/classnode/secrets.env` (mode 600):

```
PLATFORM_DOMAIN=classnode.co
DJANGO_SECRET_KEY=<first value>
POSTGRES_PASSWORD=<second value>
DEMO_SERVER=1
```

`/etc/classnode/caddy.env` (mode 600):

```
PLATFORM_DOMAIN=classnode.co
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

## 4. Start the stack and prepare the database

Not `deploy/deploy.sh`: it reads `production.env` for the health check and would
test `classnode.africa`. These are its steps by hand. From `/opt/classnode/deploy`:

```bash
cd /opt/classnode/deploy
export CLASSNODE_TAG=<the full commit SHA>

docker compose pull web worker caddy db
docker compose up -d db redis
docker compose run --rm --no-deps web python manage.py migrate_schemas --noinput
docker compose up -d web worker caddy
```

Check that the override took, and that the first certificate arrived (Caddy asks
Let's Encrypt for the wildcard through Cloudflare; the first time takes a minute
or two):

```bash
docker compose run --rm --no-deps web printenv PLATFORM_DOMAIN     # classnode.co
docker compose logs caddy | grep -i -E "certificate obtained|error"
curl -fsS https://app.classnode.co/healthz/                        # 200
```

`export CLASSNODE_TAG` lasts for this shell only; every later `docker compose`
command needs it again.

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

## Updating and starting over

A new version: check out the new SHA in `/opt/classnode`, `export CLASSNODE_TAG`,
and run the four commands of step 4. The demo data stays.

Starting over (the data is disposable):

```bash
cd /opt/classnode/deploy && export CLASSNODE_TAG=<sha>
docker compose down
rm -rf /srv/classnode/postgres /srv/classnode/redis && mkdir -p /srv/classnode/postgres /srv/classnode/redis
```

then step 4, then step 5. The certificate is kept in the `caddy-data` volume, so
this does not ask Let's Encrypt for a new one.

## If it does not come up

- **Caddy cannot get the certificate**: `docker compose logs caddy`. A 403 or
  "zone not found" is the token's scope or zone (step 1); "no such host" is a
  missing `*` record. Let's Encrypt rate-limits repeated failures, so fix the
  cause before restarting in a loop.
- **`docker compose` says set CLASSNODE_TAG**: the export is per shell.
- **`manifest unknown` or `denied` on pull**: the SHA's images are not published
  (its `publish` job did not pass), or the GHCR login is missing or expired.
- **`load_demo` says "only runs on a demo server"**: `DEMO_SERVER=1` is not in
  `secrets.env`, or the file was edited after the container was created; `run`
  reads it fresh, so check the file.
- **A school's page says the host is not allowed**: the name is not under
  `PLATFORM_DOMAIN`. Confirm step 4's `printenv` shows `classnode.co`.
