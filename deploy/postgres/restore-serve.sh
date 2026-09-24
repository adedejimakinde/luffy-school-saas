#!/usr/bin/env bash
# The weekly restore test's database: recover the latest backup from B2 into an
# empty data directory, replay WAL to the end, and serve it.
#
# Run as the `restore-db` service (profile `restore`), never against the live
# volume: its data directory is a throwaway volume, it archives nothing, and it
# listens only on the compose network.
set -euo pipefail
: "${WALG_S3_PREFIX:?WALG_S3_PREFIX is not set; there is nothing to restore from}"

export PGDATA=/var/lib/postgresql/restore
rm -rf "$PGDATA"
mkdir -p "$PGDATA"
chown postgres:postgres "$PGDATA"
chmod 0700 "$PGDATA"

gosu postgres wal-g backup-fetch "$PGDATA" LATEST
gosu postgres touch "$PGDATA/recovery.signal"

# Replay every archived segment, then become a normal read-write server so the
# check can connect and ask its questions.
exec gosu postgres postgres \
  -c archive_mode=off \
  -c "restore_command=wal-g wal-fetch %f %p" \
  -c recovery_target_action=promote
