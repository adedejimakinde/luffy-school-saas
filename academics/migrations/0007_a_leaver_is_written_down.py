"""A child taken off the roll is written down, once. Audit finding G-16.

`Departure` is the record of an absence (`docs/operating-rules.md` rule 8): who
decided a child left, on which day, why, and which classes they were taken out
of. Append-only in the database, as the other records of a decision are: a
trigger refuses UPDATE and DELETE, and a check refuses a blank reason.
"""

from django.db import migrations, models

FUNCTION = """
CREATE OR REPLACE FUNCTION academics_a_departure_is_written_once() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'academics_departure is append-only; % is not allowed. A child taken off '
        'the roll was taken off on that day for that reason; a child who comes '
        'back is admitted again.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER academics_departures_are_append_only
BEFORE UPDATE OR DELETE ON academics_departure
FOR EACH ROW EXECUTE FUNCTION academics_a_departure_is_written_once();
"""

DROP = "DROP TRIGGER IF EXISTS academics_departures_are_append_only ON academics_departure;"


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0006_a_placement_says_when_the_child_joined_the_class"),
    ]

    operations = [
        migrations.CreateModel(
            name="Departure",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("student_membership_id", models.PositiveBigIntegerField(db_index=True)),
                ("left_on", models.DateField()),
                ("reason", models.TextField()),
                ("decided_by_id", models.PositiveBigIntegerField()),
                ("student_name", models.CharField(max_length=255)),
                ("classes_left", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("reason", ""), _negated=True),
                        name="a_departure_gives_a_reason",
                    )
                ],
            },
        ),
        migrations.RunSQL(sql=FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP),
    ]
