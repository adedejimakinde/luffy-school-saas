#!/usr/bin/env bash
# Runs the nightly backup the way cron does, against a real Postgres container
# built from the production image, with WAL-G pointed at a local directory
# instead of B2:
#
#   deploy/postgres/test-backup.sh <image>
#
# **Why it exists.** `classnode-backup` was only ever run by hand as the
# postgres user, so for weeks nothing noticed that cron's plain
# `docker compose exec -T db classnode-backup` enters the container as root,
# which has no Postgres role: `FATAL: role "root" does not exist`. `docker exec`
# below is that same entry — root, no `-u`, no PGUSER, no PGDATABASE.
#
# It asks three things, and the heartbeat is a local listener so that "reports
# to Sentry" is checked as well as "backs up":
#   1. the plain command, as root, succeeds, leaves a base backup in the target
#      and checks in `ok`;
#   2. the other commands the runbook runs as root (psql with -U and -d) work;
#   3. a backup that fails — the target cannot be written, or there is none —
#      exits non-zero and checks in `error`.
#
# CI runs it in the `image` job (.github/workflows/tests.yml). It needs Docker
# and python3, and nothing from B2.
set -euo pipefail

image="${1:?usage: test-backup.sh <image>}"
name="classnode-backup-test-$$"
work="$(mktemp -d)"
beats="$work/beats.log"
server=""

cleanup() {
  docker rm -f -v "$name" >/dev/null 2>&1 || true
  if [ -n "$server" ]; then kill "$server" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  echo "--- container log" >&2
  docker logs "$name" 2>&1 | tail -n 40 >&2 || true
  echo "--- check-ins received" >&2
  cat "$beats" >&2 || true
  exit 1
}

# The heartbeat: Sentry's check-in URL stands in as a listener on the runner
# that writes down every path it is asked for.
cat > "$work/listener.py" <<'PY'
import http.server
import sys


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        with open(sys.argv[2], "a") as f:
            f.write(self.path + "\n")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("0.0.0.0", 0), Handler)
with open(sys.argv[1], "w") as f:
    f.write(str(server.server_port))
server.serve_forever()
PY
: > "$beats"
python3 "$work/listener.py" "$work/port" "$beats" &
server=$!
for _ in $(seq 50); do [ -s "$work/port" ] && break; sleep 0.1; done
[ -s "$work/port" ] || fail "the heartbeat listener did not start"

# Settings as production's env files give them, except the target: a directory
# (a tmpfs everyone may write, as the postgres user is not known to the runner)
# in place of the bucket, so no credentials are needed. The key is a real one,
# because production's backups are encrypted and the encryption is part of what
# has to work.
docker run -d --name "$name" \
  --add-host=host.docker.internal:host-gateway \
  --mount type=tmpfs,destination=/walg-store,tmpfs-mode=1777 \
  -e POSTGRES_USER=classnode \
  -e POSTGRES_DB=classnode \
  -e POSTGRES_PASSWORD="ci-only-$(openssl rand -hex 8)" \
  -e WALG_FILE_PREFIX=/walg-store \
  -e WALG_LIBSODIUM_KEY="$(openssl rand -hex 32)" \
  -e WALG_LIBSODIUM_KEY_TRANSFORM=hex \
  -e BACKUP_HEARTBEAT_URL="http://host.docker.internal:$(cat "$work/port")/checkin" \
  "$image" >/dev/null

# `pg_isready -h 127.0.0.1`: while the image initialises the cluster, a first
# server listens on the socket only. The TCP port is the real one.
ready=0
for _ in $(seq 90); do
  if docker exec "$name" pg_isready -h 127.0.0.1 -U classnode -d classnode -q 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || fail "Postgres did not become ready"
# (Into a variable first: `grep -q` quits early, and under pipefail that fails
# the pipe's writer.)
log="$(docker logs "$name" 2>&1)"
case "$log" in
  *"classnode-postgres: archiving WAL to"*) ;;
  *) fail "WAL archiving was not switched on" ;;
esac

# Something in the database to back up, so the backup is not of an empty one.
docker exec -u postgres "$name" psql -U classnode -d classnode -qc \
  "CREATE TABLE t AS SELECT generate_series(1, 1000) AS n"

# 1. The plain command, as root: no -u, no PGUSER, no PGDATABASE.
[ "$(docker exec "$name" id -u)" = 0 ] || fail "the test is not running as root"
out="$(docker exec "$name" classnode-backup 2>&1)" || fail "classnode-backup as root failed:
$out"
case "$out" in
  *"classnode-backup: done"*) ;;
  *) fail "classnode-backup as root did not end 'done':
$out" ;;
esac
grep -q '^/checkin?status=ok$' "$beats" || fail "a good backup did not check in ok"
listed="$(docker exec -u postgres "$name" wal-g backup-list)"
case "$listed" in
  *base_*) ;;
  *) fail "the target holds no base backup:
$listed" ;;
esac

# 2. What the runbook runs as root in the container: psql names its user and
# database, so it needs no role called root. (first-day.md steps 25 and 28,
# deploy/restore-check.sh.)
docker exec "$name" sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT archived_count FROM pg_stat_archiver"' >/dev/null \
  || fail "the runbook's psql, as root, failed"
docker exec "$name" sh -c \
  'test "$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT NOT pg_is_in_recovery()")" = t' \
  || fail "the runbook's recovery check, as root, failed"

# 3. Failures are loud. An unwritable target: the backup fails, and says so.
: > "$beats"
if out="$(docker exec -e WALG_FILE_PREFIX=/nonexistent/store "$name" classnode-backup 2>&1)"; then
  fail "a backup to an unwritable target exited 0:
$out"
fi
grep -q '^/checkin?status=error$' "$beats" || fail "an unwritable target did not check in error"
if grep -q 'status=ok' "$beats"; then fail "a failed backup also checked in ok"; fi

# ... and no target at all, which stops before any command that could fail.
: > "$beats"
if out="$(docker exec -e WALG_FILE_PREFIX= -e WALG_S3_PREFIX= "$name" classnode-backup 2>&1)"; then
  fail "a backup with nowhere to back up to exited 0:
$out"
fi
grep -q '^/checkin?status=error$' "$beats" || fail "a missing target did not check in error"

echo "test-backup: the plain command works as root, and a failure checks in error"
