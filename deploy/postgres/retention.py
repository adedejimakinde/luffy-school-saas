"""Which base backups to keep: 7 nightly, 4 weekly, 12 monthly.

Run by `classnode-backup` after each `wal-g backup-push`. Standard library only:
it runs in the database image, which has Python 3 and nothing else of ours.

WAL-G deletes by count (`delete retain FULL 7`), and keeps any backup marked
**permanent** whatever the count. So the policy is carried by marks:

- **Weekly:** the first backup of each ISO week, for the last 4 weeks.
- **Monthly:** the first backup of each calendar month, for the last 12 months.
- Those are marked permanent; a permanent backup that has aged out of both is
  unmarked; then `delete retain FULL 7` keeps the 7 newest of the rest.

`plan()` is the whole decision and is a pure function, tested in
`tests/test_backup_retention.py` without WAL-G or B2.
"""

import datetime as dt
import json
import subprocess
import sys

NIGHTLY = 7
WEEKS = 4
MONTHS = 12


def _started(backup):
    stamp = backup.get("start_time") or backup.get("time")
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def keepers(backups, today):
    """Names of the backups the weekly and monthly rules keep."""
    ordered = sorted(backups, key=_started)
    first_of_week, first_of_month = {}, {}
    for backup in ordered:
        day = _started(backup).date()
        first_of_week.setdefault(day.isocalendar()[:2], backup)
        first_of_month.setdefault((day.year, day.month), backup)

    oldest_week = today - dt.timedelta(weeks=WEEKS)
    month_index = today.year * 12 + today.month - 1
    keep = set()
    for backup in first_of_week.values():
        if _started(backup).date() > oldest_week:
            keep.add(backup["backup_name"])
    for (year, month), backup in first_of_month.items():
        if month_index - (year * 12 + month - 1) < MONTHS:
            keep.add(backup["backup_name"])
    return keep


def plan(backups, today):
    """`(to_mark_permanent, to_unmark)` — sorted lists of backup names."""
    keep = keepers(backups, today)
    permanent = {b["backup_name"] for b in backups if b.get("is_permanent")}
    return sorted(keep - permanent), sorted(permanent - keep)


def _walg(*args):
    return subprocess.run(["wal-g", *args], check=True, capture_output=True, text=True).stdout


def main():
    listed = json.loads(_walg("backup-list", "--json", "--detail") or "[]")
    to_mark, to_unmark = plan(listed, dt.datetime.now(dt.timezone.utc).date())
    for name in to_mark:
        _walg("backup-mark", name)
    for name in to_unmark:
        _walg("backup-mark", "-i", name)
    _walg("delete", "retain", "FULL", str(NIGHTLY), "--confirm")
    print(f"retention: marked {len(to_mark)}, unmarked {len(to_unmark)}, kept {NIGHTLY} nightly")


if __name__ == "__main__":
    sys.exit(main())
