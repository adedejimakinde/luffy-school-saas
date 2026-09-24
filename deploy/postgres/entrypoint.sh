#!/usr/bin/env bash
# Start Postgres, archiving WAL to B2 **only once B2 is configured**.
#
# Archiving that cannot succeed is worse than none: Postgres keeps every WAL
# segment an `archive_command` has not accepted, so a command that always fails
# fills the disk and then stops the database. Until WALG_S3_PREFIX is set (in
# /etc/classnode/backup.env), archive_mode stays off and the logs say so.
set -euo pipefail

args=(-c wal_level=replica)
if [ -n "${WALG_S3_PREFIX:-}" ]; then
  # 60 seconds: at most a minute of marks is ever unarchived.
  args+=(-c archive_mode=on -c "archive_command=wal-g wal-push %p" -c archive_timeout=60)
  echo "classnode-postgres: archiving WAL to ${WALG_S3_PREFIX}" >&2
else
  args+=(-c archive_mode=off)
  echo "classnode-postgres: WALG_S3_PREFIX is not set; WAL is NOT being archived" >&2
fi

exec docker-entrypoint.sh postgres "${args[@]}" "$@"
