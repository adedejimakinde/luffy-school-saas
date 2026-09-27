"""The result checker's PINs, one digest per slip printed. `docs/messaging.md` D11.

Append-only at both layers, like every other record in this app: a new slip is
a new row, and the newest row is the live PIN, so nothing here is ever updated.
The trigger's sentence carries the table and the operation, so a test can name
it rather than accepting any refusal (#89).
"""

import django.db.models.deletion
from django.db import migrations, models


FUNCTION = """
CREATE OR REPLACE FUNCTION results_checker_pins_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_checkerpin is append-only; % is not allowed. Print a new slip '
        'instead, which stops the old PIN opening anything.',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER results_checker_pins_append_only
BEFORE UPDATE OR DELETE ON results_checkerpin
FOR EACH ROW EXECUTE FUNCTION results_checker_pins_are_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS results_checker_pins_append_only ON results_checkerpin;
DROP FUNCTION IF EXISTS results_checker_pins_are_append_only();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0004_classteacher"),
        ("results", "0025_a_release_says_its_check_finished"),
    ]

    operations = [
        migrations.CreateModel(
            name="CheckerPin",
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
                ("student_membership_id", models.PositiveBigIntegerField()),
                ("pin_hash", models.CharField(max_length=64)),
                ("minted_by_id", models.PositiveBigIntegerField()),
                ("minted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "term",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="checker_pins",
                        to="academics.term",
                    ),
                ),
            ],
            options={
                "ordering": ["student_membership_id", "term_id", "id"],
                "indexes": [
                    models.Index(
                        fields=["student_membership_id", "term", "-id"],
                        name="checker_pin_newest_first",
                    )
                ],
            },
        ),
        migrations.RunSQL(sql=FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP),
    ]
