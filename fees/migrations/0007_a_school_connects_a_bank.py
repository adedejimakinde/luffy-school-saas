"""Where a school's fees settle: one row per connection, never edited.

The trigger is `0006`'s shape for the ledger's reason: `save()` and `delete()`
refusing is what a developer sees, and this is what a `psql` session or a bulk
`.update()` runs into. Row-level, UPDATE and DELETE, not TRUNCATE.
"""

import django.utils.timezone
from django.db import migrations, models

FUNCTION = """
CREATE OR REPLACE FUNCTION fees_bank_is_fixed() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        '% is never edited or deleted; % is not allowed. '
        'Connect the new account instead: the latest row is the current one.',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER fees_bank_fixed
BEFORE UPDATE OR DELETE ON fees_schoolbank
FOR EACH ROW EXECUTE FUNCTION fees_bank_is_fixed();
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS fees_bank_fixed ON fees_schoolbank;"
DROP_FUNCTION = "DROP FUNCTION IF EXISTS fees_bank_is_fixed();"


class Migration(migrations.Migration):

    dependencies = [
        ("fees", "0006_a_concession_is_never_edited"),
    ]

    operations = [
        migrations.CreateModel(
            name="SchoolBank",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bank_code", models.CharField(max_length=20)),
                ("bank_name", models.CharField(max_length=120)),
                ("account_number", models.CharField(max_length=10)),
                ("account_name", models.CharField(max_length=255)),
                ("subaccount_code", models.CharField(max_length=64)),
                ("split_code", models.CharField(max_length=64)),
                ("connected_by_id", models.PositiveBigIntegerField(help_text="accounts.User id.")),
                ("connected_by_name", models.CharField(max_length=255)),
                ("connected_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"ordering": ["-id"]},
        ),
        migrations.AddConstraint(
            model_name="schoolbank",
            constraint=models.CheckConstraint(
                condition=models.Q(("account_number__regex", "^[0-9]{10}$")),
                name="a_bank_account_is_ten_digits",
            ),
        ),
        migrations.RunSQL(sql=FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
