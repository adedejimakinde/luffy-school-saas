"""Which base backups WAL-G keeps: 7 nightly, 4 weekly, 12 monthly.

`deploy/postgres/retention.py` runs inside the database image with the standard
library only, so it is loaded here by path. `plan()` is the whole decision —
what to mark permanent and what to unmark — and WAL-G's `delete retain FULL 7`
does the rest, keeping every permanent backup whatever the count.
"""

import datetime as dt
import importlib.util
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

_spec = importlib.util.spec_from_file_location(
    "retention", Path(settings.BASE_DIR) / "deploy" / "postgres" / "retention.py"
)
retention = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(retention)


def nightly(start, days, permanent=()):
    """One backup a night at 01:30 UTC for `days` nights ending on `start`."""
    backups = []
    for n in range(days):
        day = start - dt.timedelta(days=n)
        name = f"base_{day:%Y%m%d}"
        backups.append(
            {
                "backup_name": name,
                "start_time": f"{day:%Y-%m-%d}T01:30:00.000000Z",
                "is_permanent": name in permanent,
            }
        )
    return backups


class RetentionTests(SimpleTestCase):
    TODAY = dt.date(2026, 9, 24)  # a Thursday

    def test_a_year_of_nightlies_keeps_four_weeks_and_twelve_months(self):
        keep = retention.keepers(nightly(self.TODAY, 400), self.TODAY)

        monthly = {n for n in keep if n.endswith("01")}
        self.assertEqual(len(monthly), 12)
        self.assertIn("base_20260901", keep)
        self.assertIn("base_20251001", keep)
        self.assertNotIn("base_20250901", keep, "a thirteenth month was kept")
        # Weekly: the first backup of each of the last four ISO weeks.
        for monday in ("base_20260921", "base_20260914", "base_20260907"):
            with self.subTest(week=monday):
                self.assertIn(monday, keep)
        self.assertNotIn("base_20260817", keep, "a fifth week back was kept")

    def test_marks_what_it_keeps_and_unmarks_what_aged_out(self):
        backups = nightly(self.TODAY, 400, permanent={"base_20250901", "base_20260901"})

        to_mark, to_unmark = retention.plan(backups, self.TODAY)

        self.assertIn("base_20250901", to_unmark)
        self.assertNotIn("base_20260901", to_mark, "already permanent, marked again")
        self.assertIn("base_20251001", to_mark)

    def test_a_missed_night_moves_the_weekly_keeper_to_the_next_backup(self):
        """The first backup of the week is kept, not "Monday's" — so a failed
        Monday backup does not leave the week with nothing."""
        backups = [b for b in nightly(self.TODAY, 30) if b["backup_name"] != "base_20260921"]

        self.assertIn("base_20260922", retention.keepers(backups, self.TODAY))

    def test_no_backups_is_nothing_to_do(self):
        self.assertEqual(retention.plan([], self.TODAY), ([], []))
