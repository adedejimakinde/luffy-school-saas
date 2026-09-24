"""A concession is never edited or deleted, and neither is its revocation.

Decided 2026-09-24 with issue #75. The flag goes — a revocation row is now the
only answer to "is this concession still granted" — and so does `updated_at`,
which a row that is never updated does not need. A form key arrives so that a
double click on "Grant" grants once.

The triggers are `0002`'s shape for the ledger, and for the ledger's reason:
`save()` and `delete()` refusing is what a developer sees, and this is what a
`psql` session, a data import or a bulk `.update()` runs into. Row-level,
UPDATE and DELETE, not TRUNCATE — `0002` says why.
"""

from django.db import migrations, models

FUNCTION = """
CREATE OR REPLACE FUNCTION fees_concession_is_fixed() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        '% is never edited or deleted; % is not allowed. '
        'Revoke the concession with a reason, and grant a new one if it should '
        'continue on different terms.', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGERS = """
CREATE TRIGGER fees_concession_fixed
BEFORE UPDATE OR DELETE ON fees_feeconcession
FOR EACH ROW EXECUTE FUNCTION fees_concession_is_fixed();

CREATE TRIGGER fees_concession_revocation_fixed
BEFORE UPDATE OR DELETE ON fees_feeconcessionrevocation
FOR EACH ROW EXECUTE FUNCTION fees_concession_is_fixed();
"""

DROP_TRIGGERS = """
DROP TRIGGER IF EXISTS fees_concession_revocation_fixed ON fees_feeconcessionrevocation;
DROP TRIGGER IF EXISTS fees_concession_fixed ON fees_feeconcession;
"""
DROP_FUNCTION = "DROP FUNCTION IF EXISTS fees_concession_is_fixed();"


class Migration(migrations.Migration):

    dependencies = [
        ("fees", "0005_a_revocation_says_who_and_why"),
    ]

    operations = [
        migrations.RemoveField(model_name="feeconcession", name="is_active"),
        migrations.RemoveField(model_name="feeconcession", name="updated_at"),
        migrations.AddField(
            model_name="feeconcession",
            name="form_key",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddConstraint(
            model_name="feeconcession",
            constraint=models.UniqueConstraint(
                condition=models.Q(("form_key__isnull", False)),
                fields=("form_key",),
                name="a_concession_form_grants_once",
            ),
        ),
        migrations.RunSQL(sql=FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=TRIGGERS, reverse_sql=DROP_TRIGGERS),
    ]
