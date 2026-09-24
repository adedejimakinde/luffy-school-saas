"""A release writes down the children it left without a card. Issue #47.

`ReleaseOmission` is the record `docs/operating-rules.md` rule 8 asks of a
decision that produces an absence: a child placed into a class while its release
ran is not on the roster the freeze read, gets no card, and until now left no
trace. The row is written after the release commits, by `results.omissions`; see
the model for why the read is a fresh one and outside the lock.

Append-only at both layers, like every other record in this app. The trigger's
sentence carries the table and the operation, so a test can name it rather than
accepting any refusal (#89).
"""

import django.db.models.deletion
from django.db import migrations, models


FUNCTION = """
CREATE OR REPLACE FUNCTION results_release_omissions_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_releaseomission is append-only; % is not allowed. It says who a '
        'release left without a card, and it has to go on saying it.',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER results_release_omissions_append_only
BEFORE UPDATE OR DELETE ON results_releaseomission
FOR EACH ROW EXECUTE FUNCTION results_release_omissions_are_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS results_release_omissions_append_only ON results_releaseomission;
DROP FUNCTION IF EXISTS results_release_omissions_are_append_only();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0023_a_card_can_be_held_back"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReleaseOmission",
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
                ("student_name", models.CharField(blank=True, max_length=255)),
                ("student_reference", models.CharField(blank=True, max_length=64)),
                ("noticed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sheet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="omissions",
                        to="results.resultsheet",
                    ),
                ),
            ],
            options={
                "ordering": ["sheet_id", "student_name", "student_membership_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("sheet", "student_membership_id"),
                        name="a_release_omits_a_child_once",
                    )
                ],
            },
        ),
        migrations.RunSQL(sql=FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP),
    ]
