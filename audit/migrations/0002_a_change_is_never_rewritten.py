"""Make "the setup log is append-only" a rule Postgres holds, not one Python asks for.

`Change.save()` and `.delete()` already refuse; this is what a `psql` session,
a bulk `.update()` or a service written in a hurry runs into. Created
unqualified, so each school's schema gets its own function and trigger during
`migrate_schemas`, as `fees/migrations/0002_ledger_is_append_only` does, and
for its reason it fires per row on UPDATE and DELETE and not on TRUNCATE.
"""

from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION audit_change_is_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_change is append-only; % is not allowed. '
        'Write a new row that says what happened instead.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER audit_change_append_only
BEFORE UPDATE OR DELETE ON audit_change
FOR EACH ROW EXECUTE FUNCTION audit_change_is_append_only();
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS audit_change_append_only ON audit_change;"
DROP_FUNCTION = "DROP FUNCTION IF EXISTS audit_change_is_append_only();"


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_the_setup_log"),
    ]

    operations = [
        migrations.RunSQL(sql=FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
