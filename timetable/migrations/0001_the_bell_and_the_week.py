"""The school's periods, and who teaches what in each of them. T1, decided
2026-09-24; `timetable/models.py` has the reasoning.

**`btree_gist` goes into `public`, by name, and the name is the point.** The
clash rule is an exclusion constraint with `<>` on an integer, which needs the
extension's operator classes. This migration runs once per school, with the
school first on the `search_path`, and a bare `CREATE EXTENSION` installs into
the first schema on the path. The first school migrated would own the
extension; every later school would meet `IF NOT EXISTS`, skip it, and fail to
find the operator classes, because they live in another school's schema — and
dropping that first school would take the extension, and every other school's
constraint, with it. `WITH SCHEMA public` puts it where every school's
`search_path` already looks. Never dropped on reverse: other schools use it.

`periods_do_not_overlap` needs no extension; a `tsrange` is excluded on
natively.
"""

import django.contrib.postgres.constraints
import django.db.models.deletion
import timetable.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("academics", "0004_classteacher"),
        ("gradebook", "0003_where_a_paper_prints"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name="Period",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("starts_at", models.TimeField()),
                ("ends_at", models.TimeField()),
                ("label", models.CharField(blank=True, max_length=32)),
            ],
            options={
                "ordering": ["starts_at"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("ends_at__gt", models.F("starts_at"))),
                        name="a_period_ends_after_it_starts",
                    ),
                    django.contrib.postgres.constraints.ExclusionConstraint(
                        expressions=[
                            (timetable.models.ClockSpan("starts_at", "ends_at"), "&&")
                        ],
                        name="periods_do_not_overlap",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TimetableSlot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "weekday",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "Monday"),
                            (2, "Tuesday"),
                            (3, "Wednesday"),
                            (4, "Thursday"),
                            (5, "Friday"),
                        ]
                    ),
                ),
                (
                    "teacher_membership_id",
                    models.PositiveBigIntegerField(db_index=True),
                ),
                ("set_by_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "class_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="academics.classgroup",
                    ),
                ),
                (
                    "period",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="slots",
                        to="timetable.period",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="gradebook.subject",
                    ),
                ),
                (
                    "term",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="academics.term",
                    ),
                ),
            ],
            options={
                "ordering": ["term", "class_group", "weekday", "period__starts_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("term", "class_group", "weekday", "period"),
                        name="one_lesson_per_class_per_slot",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("weekday__gte", 1), ("weekday__lte", 5)),
                        name="a_weekday_is_a_school_day",
                    ),
                    django.contrib.postgres.constraints.ExclusionConstraint(
                        expressions=[
                            ("term", "="),
                            ("weekday", "="),
                            ("period", "="),
                            ("teacher_membership_id", "="),
                            ("subject", "<>"),
                        ],
                        name="a_teacher_teaches_one_subject_at_a_time",
                    ),
                ],
            },
        ),
    ]
