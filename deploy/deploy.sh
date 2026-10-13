#!/usr/bin/env bash
# Deploy one commit: deploy.sh <full 40-character commit SHA>
#
# Runs on the server, from the directory holding compose.yml and
# production.env. The GitHub "deploy" workflow calls it over SSH after checking
# that CI passed on that exact SHA; it can also be run by hand from a shell on
# the server, with the same argument.
#
# Order, and why:
#  0. Log in to ghcr.io from the root-only /root/ghcr-login (private repository).
#  1. Pull the images CI built for this SHA — never a tag like `latest`, which
#     names whatever was pushed last rather than what was tested.
#  2. Migrate with the NEW image while the OLD one is still serving. Additive
#     migrations are safe to run under old code; a migration that is not
#     (dropping or renaming something old code reads) has to ship in two
#     deploys, and docs/deployment.md says how.
#  3. Swap web, worker and caddy.
#  4. Ask /healthz/ inside the container, then through Caddy over HTTPS — the
#     second is the one that proves TLS and the proxy, not just the process.
#  5. Unhealthy: go back to the previous SHA's images. Migrations are NOT
#     undone by that; a migration that broke the old code is a restore from
#     backup (H3), which is why step 2's rule exists.
set -euo pipefail
cd "$(dirname "$0")"

SHA="${1:-}"
if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: deploy.sh <full 40-character commit SHA>" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1091
. ./production.env
set +a
PREVIOUS="$(cat deployed-sha 2>/dev/null || true)"
export CLASSNODE_TAG="$SHA"

# The repository, and so its images on ghcr.io, are private: pulling needs a
# login. The token lives only in root's /root/ghcr-login (line 1 the GitHub
# username, line 2 a classic token with read:packages and nothing else), which
# `deploy` may print through one fixed sudo rule (bootstrap.sh, step 10). The
# login goes into a throwaway Docker config that is deleted when this script
# exits, so no copy of the token is left in deploy's home.
DOCKER_CONFIG="$(mktemp -d)"
export DOCKER_CONFIG
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
if ghcr_login="$(sudo -n /usr/bin/cat /root/ghcr-login 2>/dev/null)" && [ -n "$ghcr_login" ]; then
  { IFS= read -r ghcr_user; IFS= read -r ghcr_token; } <<<"$ghcr_login"
  printf '%s' "$ghcr_token" | docker login ghcr.io -u "$ghcr_user" --password-stdin
  unset ghcr_login ghcr_user ghcr_token
else
  echo "No GHCR login (/root/ghcr-login is missing or unreadable): pulling anonymously, which only works for public images. docs/first-day.md, step 12." >&2
fi

docker compose pull web worker caddy db
docker compose up -d db redis
docker compose run --rm --no-deps web python manage.py migrate_schemas --noinput
docker compose up -d web worker caddy

healthy=0
for _ in $(seq 1 30); do
  if docker compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=3)" \
     && curl -fsS --max-time 5 "https://${PLATFORM_DOMAIN}/healthz/" >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done

if [ "$healthy" != 1 ]; then
  echo "NOT HEALTHY: $SHA did not answer /healthz/ inside the container and through Caddy" >&2
  if [ -n "$PREVIOUS" ]; then
    echo "Rolling web, worker and caddy back to $PREVIOUS. Migrations are not rolled back." >&2
    CLASSNODE_TAG="$PREVIOUS" docker compose up -d web worker caddy
  fi
  exit 1
fi

echo "$SHA" > deployed-sha
echo "DEPLOYED $SHA"
