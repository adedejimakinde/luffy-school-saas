"""What "absent too often" means at this school: OPEN-2, decided 2026-09-24.

One row per school schema, held there by the `id = 1` check rather than by
convention, because two rows would be two answers to one question. A school
that never sets it has no row, and `AbsenceSettings.load()` answers with the
defaults — 10% of the days marked, once 10 have been — so the list works on the
day a school arrives rather than after somebody configures it.
"""


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0001_the_register"),
    ]

    operations = [
        migrations.CreateModel(
            name="AbsenceSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, primary_key=True, serialize=False
                    ),
                ),
                (
                    "threshold_percent",
                    models.PositiveSmallIntegerField(
                        default=10,
                        help_text="Absent on at least this share of the days marked.",
                    ),
                ),
                (
                    "min_marked_days",
                    models.PositiveSmallIntegerField(
                        default=10,
                        help_text="Only once at least this many days have been marked.",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)),
                        name="absence_settings_is_one_row",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("threshold_percent__gte", 1),
                            ("threshold_percent__lte", 100),
                        ),
                        name="absence_threshold_is_a_percentage",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("min_marked_days__gte", 1)),
                        name="absence_floor_is_at_least_one_day",
                    ),
                ],
            },
        ),
    ]
