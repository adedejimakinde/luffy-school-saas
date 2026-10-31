#!/usr/bin/env bash
# The uploaded files' backup to Backblaze B2: restic, encrypted, incremental.
# Run inside the `media-backup` service (deploy/compose.yml), which has the
# files read-only at /srv/media and /etc/classnode/backup.env's settings:
#
#   docker compose --profile backup run --rm --no-deps media-backup          # nightly (cron)
#   docker compose --profile backup run --rm --no-deps media-backup test     # the setup check
#   docker compose --profile backup run --rm --no-deps media-backup check    # weekly (cron)
#
# - backup  every file under /srv/media except the incoming uploads, into the
#           repository; then forgets snapshots past 14 daily, 8 weekly and
#           12 monthly. Names never change once written (`files.storage`), so
#           each night sends only what is new.
# - test    the first-day check: makes the repository if there is none, backs
#           up ONE new file, restores it and compares it byte for byte, then
#           forgets that snapshot. A wrong key, prefix, endpoint or password
#           fails here, at once, not on the first night it matters.
# - check   the weekly restore test: prunes, checks a random 2% of the
#           repository's data, and restores ten files older than two days,
#           comparing each with the one on disk.
# - restore <dir>  every file of the latest snapshot into <dir>, for a new
#           server (docs/deployment.md, "Uploaded files").
#
# **Where it goes**: the same bucket and prefix as the database's WAL-G
# backups, under media/, so a B2 key limited to that prefix (classnode/) covers
# both: WALG_S3_PREFIX=s3://<bucket>/classnode makes
#   s3:<AWS_ENDPOINT>/<bucket>/classnode/media
# MEDIA_RESTIC_REPOSITORY overrides that (CI uses a local directory).
#
# **Encrypted** with MEDIA_RESTIC_PASSWORD (backup.env; `deploy/init-env.sh
# media-backup` adds one). Without it the backup is noise: keep a copy in the
# password manager beside WALG_LIBSODIUM_KEY.
#
# **A failure is never quiet**: it is printed to the cron log, and emailed to
# hello@classnode.co through the app's own email path (`manage.py
# send_ops_alert`). MEDIA_BACKUP_HEARTBEAT_URL, if set, gets ok/error check-ins
# (for a Sentry cron monitor later; optional).
set -uo pipefail

APP="${CLASSNODE_APP:-/app}"
FILES="${FILES_ROOT:-/srv/media}"
what="${1:-backup}"
log="$(mktemp)"
trap 'rm -f "$log"' EXIT

say() { printf '%s media-backup %s: %s\n' "$(date -u +%FT%TZ)" "$what" "$*"; }

beat() {
  if [ -n "${MEDIA_BACKUP_HEARTBEAT_URL:-}" ]; then
    python -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1] + '?status=' + sys.argv[2], timeout=10)" \
      "$MEDIA_BACKUP_HEARTBEAT_URL" "$1" >/dev/null 2>&1 || true
  fi
}

fail() {
  say "FAILED: $*"
  {
    echo "The media backup ($what) failed on the server: $*"
    echo
    echo "The last of what restic said:"
    tail -n 30 "$log"
    echo
    echo "Repository: ${RESTIC_REPOSITORY:-not set}"
    echo "Log: /var/log/classnode-media-backup.log. Runbook: docs/deployment.md, 'Uploaded files'."
  } | python "$APP/manage.py" send_ops_alert "Media backup FAILED: $what" \
        || say "and the alert email could not be sent either; this log is the only record"
  beat error
  exit 1
}

# Every restic call's output goes to the log as well as the cron log, so the
# alert can quote it.
r() { restic "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }

# -- where, and with what -------------------------------------------------------

if [ -n "${MEDIA_RESTIC_REPOSITORY:-}" ]; then
  RESTIC_REPOSITORY="$MEDIA_RESTIC_REPOSITORY"
elif [ -n "${WALG_S3_PREFIX:-}" ] && [ "${WALG_S3_PREFIX}" != CHANGE_ME ]; then
  [ -n "${AWS_ENDPOINT:-}" ] || fail "AWS_ENDPOINT is not set in backup.env"
  RESTIC_REPOSITORY="s3:${AWS_ENDPOINT%/}/${WALG_S3_PREFIX#s3://}/media"
else
  RESTIC_REPOSITORY=""
  fail "there is nowhere to back up to: WALG_S3_PREFIX is not set (backup.env; docs/first-day.md, the backup step)"
fi
export RESTIC_REPOSITORY
[ -n "${MEDIA_RESTIC_PASSWORD:-}" ] && [ "${MEDIA_RESTIC_PASSWORD}" != GENERATE ] \
  || fail "MEDIA_RESTIC_PASSWORD is not set in backup.env (deploy/init-env.sh media-backup adds one)"
export RESTIC_PASSWORD="$MEDIA_RESTIC_PASSWORD"
export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
export RESTIC_HOST=classnode

repository_exists() { r cat config >/dev/null; }

# -- the three jobs -------------------------------------------------------------

backup() {
  [ -d "$FILES" ] || fail "$FILES does not exist in the container"
  repository_exists || fail "the repository cannot be opened (wrong key, prefix, endpoint or password; or 'test' was never run to make it)"
  r backup "$FILES" --tag media --exclude "$FILES/.incoming" --exclude '.part-*' --exclude "$FILES/.disk-alert-sent" \
    || fail "restic backup did not finish"
  r forget --tag media --keep-daily 14 --keep-weekly 8 --keep-monthly 12 || fail "restic forget did not finish"
  say "OK: $(find "$FILES" -type f -not -path "$FILES/.incoming/*" | wc -l) files are in the latest snapshot"
  beat ok
}

test_one_file() {
  if ! repository_exists; then
    say "no repository at $RESTIC_REPOSITORY yet; making it"
    r init || fail "restic could not make the repository (check the B2 key may write to this prefix)"
  fi
  local work probe restored
  work="$(mktemp -d)"
  probe="$work/probe/classnode-media-backup-probe.txt"
  mkdir -p "$work/probe" "$work/restored"
  head -c 4096 /dev/urandom | base64 > "$probe"
  r backup "$work/probe" --tag probe || fail "the probe file could not be backed up"
  r restore latest --tag probe --target "$work/restored" || fail "the probe file could not be restored"
  restored="$(find "$work/restored" -type f -name classnode-media-backup-probe.txt -print -quit)"
  [ -n "$restored" ] && cmp -s "$probe" "$restored" || fail "the restored probe file is not the one backed up"
  r forget --tag probe --keep-last 0 >/dev/null 2>&1 || r forget --tag probe latest >/dev/null 2>&1 || true
  rm -rf "$work"
  say "OK: one file was backed up to $RESTIC_REPOSITORY and restored byte for byte"
  beat ok
}

check() {
  repository_exists || fail "the repository cannot be opened"
  r prune || fail "restic prune did not finish"
  r check --read-data-subset=2% || fail "restic check found a problem in the repository"
  local work sample=0 bad=0
  work="$(mktemp -d)"
  while IFS= read -r -d '' file; do
    sample=$((sample + 1))
    if ! r dump --tag media latest "$file" > "$work/one"; then
      bad=$((bad + 1)); say "could not restore $file"; continue
    fi
    cmp -s "$file" "$work/one" || { bad=$((bad + 1)); say "restored copy differs: $file"; }
  done < <(find "$FILES" -type f -mtime +1 -not -path "$FILES/.incoming/*" -not -name '.*' -print0 | shuf -z -n 10)
  rm -rf "$work"
  [ "$bad" = 0 ] || fail "$bad of $sample sampled files did not come back identical"
  say "OK: repository checked; $sample sampled files restored identically"
  beat ok
}

restore_all() {
  local target="${2:-/restore}"
  [ -d "$target" ] && [ -w "$target" ] || fail "$target is not a writable directory (mount the new server's files directory there)"
  repository_exists || fail "the repository cannot be opened"
  r restore "latest:$FILES" --tag media --target "$target" || fail "restic restore did not finish"
  say "OK: the latest snapshot's files are in $target ($(find "$target" -type f | wc -l) files)"
}

case "$what" in
  backup) backup ;;
  test) test_one_file ;;
  check) check ;;
  restore) restore_all "$@" ;;
  *) echo "usage: media-backup.sh [backup | test | check | restore <dir>]" >&2; exit 2 ;;
esac
