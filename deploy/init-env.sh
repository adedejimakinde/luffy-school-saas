#!/usr/bin/env bash
# Create the server's env files from the templates in deploy/env/, without a
# secret ever appearing on the screen, in your shell history or in a process list.
#
#   init-env.sh            creates /etc/classnode/secrets.env and caddy.env
#   init-env.sh backup     creates /etc/classnode/backup.env (do this when you have B2)
#   init-env.sh --check    says which files are ready; prints names, never values
#
# Run as root on the server. **Safe to re-run: it never touches a file that
# exists** — a second run on a configured server changes nothing, so it cannot
# replace the database password with a new one the database does not know.
#
# Each GENERATE in a template becomes a random value, made inside awk and
# written straight to the file. Each CHANGE_ME is yours to type, in an editor
# on the server (nano /etc/classnode/caddy.env); --check refuses while any is left.
# Files are root:deploy mode 640: `docker compose` reads them as `deploy`.
set -euo pipefail

ETC=/etc/classnode
HERE="$(cd "$(dirname "$0")" && pwd)"
TEMPLATES="$HERE/env"

die() { printf 'STOPPED: %s\n' "$*" >&2; exit 1; }

# make NAME — NAME.env from NAME.env.example, unless NAME.env exists.
make() {
  local name=$1 dest="$ETC/$1.env" tmp
  if [ -e "$dest" ]; then
    echo "$name.env: already exists, left exactly as it is"
    return 0
  fi
  [ -d "$ETC" ] || die "$ETC does not exist; run deploy/bootstrap.sh first."
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  awk '
    /^[A-Z0-9_]+=GENERATE$/ {
      key = substr($0, 1, index($0, "=") - 1)
      cmd = "openssl rand -hex " (key == "DJANGO_SECRET_KEY" ? 48 : 32)
      cmd | getline value
      close(cmd)
      if (value == "") { print "openssl produced nothing" > "/dev/stderr"; exit 1 }
      print key "=" value
      next
    }
    { print }
  ' "$TEMPLATES/$name.env.example" > "$tmp"
  install -m 640 -o root -g deploy "$tmp" "$dest"
  echo "$name.env: created at $dest"
}

# value FILE KEY — the value, for the checks below only; never printed.
value() { grep -E "^$2=" "$1" | tail -n 1 | cut -d= -f2-; }

problems=0
problem() { printf '  NOT READY: %s\n' "$*"; problems=$((problems + 1)); }

check_file() {
  local name=$1 file="$ETC/$1.env" perms
  echo "$name.env"
  if [ ! -f "$file" ]; then
    problem "$file does not exist"
    return
  fi
  perms="$(stat -c '%a %U:%G' "$file")"
  [ "$perms" = "640 root:deploy" ] || problem "permissions are '$perms', not '640 root:deploy' (fix: chown root:deploy $file && chmod 640 $file)"
  if grep -qE '=(CHANGE_ME|GENERATE)$' "$file"; then
    problem "still has a placeholder on: $(grep -E '=(CHANGE_ME|GENERATE)$' "$file" | cut -d= -f1 | tr '\n' ' ')"
  fi
}

check() {
  check_file secrets
  [ -z "$(value "$ETC/secrets.env" DJANGO_SECRET_KEY 2>/dev/null)" ] && problem "DJANGO_SECRET_KEY is empty"
  [ -z "$(value "$ETC/secrets.env" POSTGRES_PASSWORD 2>/dev/null)" ] && problem "POSTGRES_PASSWORD is empty"
  if grep -qE '^DEMO_SERVER=' "$ETC/secrets.env" 2>/dev/null; then
    problem "DEMO_SERVER is set; it must never be on a server with real schools"
  fi
  check_file caddy
  local token email
  token="$(value "$ETC/caddy.env" CLOUDFLARE_API_TOKEN 2>/dev/null || true)"
  email="$(value "$ETC/caddy.env" ACME_EMAIL 2>/dev/null || true)"
  if [ -n "$token" ] && [ "$token" != CHANGE_ME ]; then
    # Caddy's Cloudflare module refuses anything else (the CI image job notes it).
    [[ "$token" =~ ^(cfut_|cfat_) || "$token" =~ ^[A-Za-z0-9_-]{35,50}$ ]] \
      || problem "CLOUDFLARE_API_TOKEN does not look like an API token (is it the Global API Key, or has it a space or quote around it?)"
  fi
  if [ -n "$email" ] && [ "$email" != CHANGE_ME ]; then
    [[ "$email" =~ ^[^@\ ]+@[^@\ ]+\.[^@\ ]+$ ]] || problem "ACME_EMAIL is not an email address"
  fi
  if [ -f "$ETC/backup.env" ]; then
    check_file backup
    local prefix
    prefix="$(value "$ETC/backup.env" WALG_S3_PREFIX 2>/dev/null || true)"
    if [ "$prefix" != CHANGE_ME ] && [[ "$prefix" != s3://* ]]; then
      problem "WALG_S3_PREFIX should start s3://"
    fi
  else
    echo "backup.env"
    echo "  (not created yet; fine until the backup step)"
  fi
  if [ "$problems" = 0 ]; then
    echo "All the files that exist are ready."
  else
    echo "$problems thing(s) to fix."
    return 1
  fi
}

[ "$(id -u)" = 0 ] || die "run this as root."
case "${1:-}" in
  "") make secrets; make caddy ;;
  backup) make backup ;;
  --check) check ;;
  *) die "usage: init-env.sh [backup | --check]" ;;
esac
