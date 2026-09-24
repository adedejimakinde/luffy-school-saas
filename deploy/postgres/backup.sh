#!/usr/bin/env bash
# The nightly base backup, then retention. Run inside the db container:
#   docker compose exec -T db classnode-backup
# (deploy/cron/classnode schedules it). Continuous WAL archiving covers the time
# between two of these; together they restore to any moment in the nightly
# window.
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
: "${WALG_S3_PREFIX:?WALG_S3_PREFIX is not set; there is nowhere to back up to}"

beat() {
  if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
    curl -fsS --max-time 10 "${BACKUP_HEARTBEAT_URL}?status=$1" >/dev/null || true
  fi
}
trap 'beat error' ERR

stalled=$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT coalesce(last_failed_time > coalesce(last_archived_time, 'epoch'), false) FROM pg_stat_archiver")
if [ "$stalled" = "t" ]; then
  echo "classnode-backup: WAL archiving is failing (pg_stat_archiver); see the db logs" >&2
  false
fi

wal-g backup-push "$PGDATA"
python3 /usr/local/lib/classnode/retention.py
beat ok
echo "classnode-backup: done"
