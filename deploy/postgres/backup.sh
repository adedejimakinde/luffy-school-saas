#!/usr/bin/env bash
# The nightly base backup, then retention. Run inside the db container:
#   docker compose exec -T db classnode-backup
# (deploy/cron/classnode schedules it). Run it exactly like that: it switches to
# the postgres user and picks its database from the container's environment
# itself, so it needs no `-u`, no PGUSER and no PGDATABASE.
#
# Continuous WAL archiving covers the time between two of these; together they
# restore to any moment in the nightly window.
#
# **It also fails when archiving has quietly stopped.** A base backup can
# succeed every night while `archive_command` has been failing since Tuesday,
# and then the restore stops at Tuesday. So the archiver's own counters are
# asked first, and a failure newer than the last success fails the run.
#
# Reports to a heartbeat (BACKUP_HEARTBEAT_URL — Sentry's cron check-in URL for
# the `nightly-backup` monitor) on success and on failure, so a backup that
# fails *or never runs* raises an alert rather than a silence.
set -euo pipefail

# **Always runs as `postgres`, whoever calls it.** `docker compose exec` enters
# the container as root, and neither psql nor WAL-G has a role to connect as
# there: `FATAL: role "root" does not exist`, every night, with the plain
# command in cron. So a root caller is handed to the postgres user (gosu is in
# the image; the environment, with its WALG_* and AWS_* settings, carries over),
# and the connection defaults below come from the container's own environment.
if [ "$(id -u)" = 0 ]; then
  exec gosu postgres "$0" "$@"
fi

beat() {
  if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
    curl -fsS --max-time 10 "${BACKUP_HEARTBEAT_URL}?status=$1" >/dev/null || true
  fi
}
# Set before the checks below, so a missing setting is reported like any other
# failure. (`: "${VAR:?}"` would end the script without running this.)
trap 'beat error' ERR

# WALG_FILE_PREFIX is a directory standing in for the bucket: CI's backup test
# (deploy/postgres/test-backup.sh) uses it. The server uses B2.
if [ -z "${WALG_S3_PREFIX:-}${WALG_FILE_PREFIX:-}" ]; then
  echo "classnode-backup: WALG_S3_PREFIX is not set; there is nowhere to back up to" >&2
  false
fi
export PGUSER="${PGUSER:-${POSTGRES_USER:-}}"
export PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-}}"
if [ -z "$PGUSER" ] || [ -z "$PGDATABASE" ]; then
  echo "classnode-backup: POSTGRES_USER and POSTGRES_DB are not set; there is no database to connect to" >&2
  false
fi

stalled=$(psql -tAc \
  "SELECT coalesce(last_failed_time > coalesce(last_archived_time, 'epoch'), false) FROM pg_stat_archiver")
if [ "$stalled" = "t" ]; then
  echo "classnode-backup: WAL archiving is failing (pg_stat_archiver); see the db logs" >&2
  false
fi

wal-g backup-push "$PGDATA"
python3 /usr/local/lib/classnode/retention.py
beat ok
echo "classnode-backup: done"
