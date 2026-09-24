#!/usr/bin/env bash
# The weekly restore test (decided 2026-09-23). Run on the server from the
# directory holding compose.yml; deploy/cron/classnode schedules it.
#
# 1. Start `restore-db`: the latest base backup from B2, WAL replayed to the
#    end, in a throwaway volume.
# 2. Wait until recovery has finished and it is a normal server.
# 3. Ask the application whether it is whole: `manage.py verify_restore`,
#    pointed at it. That reports to Sentry's `restore-check` monitor either way.
# 4. Tear the throwaway database and its volume down, whatever happened.
#
# A restore that never becomes ready never reaches step 3, so nothing checks
# in — and the monitor alerts on the missed check-in. Silence is a failure.
set -euo pipefail
cd "$(dirname "$0")"
set -a
# shellcheck disable=SC1091
. ./production.env
set +a
export CLASSNODE_TAG
CLASSNODE_TAG="$(cat deployed-sha)"

# Only the throwaway service and its own volume. Never `down -v`: that would
# take the certificate's volume (caddy-data) with it. The project is named
# `classnode` in compose.yml, so its volume is `classnode_restore-data`.
cleanup() {
  docker compose --profile restore rm -sfv restore-db >/dev/null 2>&1 || true
  docker volume rm classnode_restore-data >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose --profile restore up -d restore-db

ready=0
for _ in $(seq 1 360); do   # up to an hour of WAL replay
  if [ "$(docker compose exec -T restore-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc 'SELECT NOT pg_is_in_recovery()' 2>/dev/null || true)" = "t" ]; then
    ready=1
    break
  fi
  sleep 10
done
if [ "$ready" != 1 ]; then
  echo "RESTORE FAILED: the recovered database never finished recovery" >&2
  exit 1
fi

docker compose run --rm --no-deps -e POSTGRES_HOST=restore-db web python manage.py verify_restore
