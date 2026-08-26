"""Two tables that record what happened, guarded so they cannot record otherwise.

`0012` created them; this is the half that makes them mean anything. Both are
append-only, and both are enforced twice — `save()` and `delete()` refuse, which
is the error a developer sees, and these triggers refuse, which is the error a
`psql` session, a data import or a bulk `.update()` runs into. None of those go
near a model method, and every one of them is a real way a school's data gets
edited in anger.

The two tables are append-only for **different reasons**, and the refusal
messages say so rather than sharing one sentence:

- `results_releasedsessionresult` is a **frozen card**. Its rows say what a
  parent was handed, and the rule is the one `0007` and `0009` already state for
  the conduct section and the remarks: a released card keeps saying what it
  said, and correcting it is a revision, which makes a new version.
- `results_promotiondecision` is an **audit log**. Its rows say who decided what
  about a child's year, and more than one row per child per session is the
  feature — a principal changing their mind writes a second row and both stand.
  Editing one in place would silently forget that the decision was ever
  different, which is precisely what an appeal from a parent turns on.

Both fire on UPDATE and DELETE and **not** on INSERT, unlike
`results_ratings_stop_at_release`. That trigger guards a *live* table where a
late insert is a real hazard; these two are written once by the code that owns
them, and refusing INSERT would refuse the write that creates the row.

## No placement join, and nothing to reconstruct

Worth stating because the last four migrations in this app were all about
getting a placement join right: neither trigger has one. Both tables key on
`(student_membership_id, session)` or on the sheet directly, and a session is a
string the row carries rather than a fact about where a child sits — so there is
no live row here whose change could move the answer, and no
`academics_classplacement` to be caught reading. That is a property of the
tables, not a shortcut taken here.
"""

from django.db import migrations

FROZEN_FUNCTION = """
CREATE OR REPLACE FUNCTION results_frozen_sessions_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_releasedsessionresult is append-only; % is not allowed. '
        'A released card has to keep saying what it said — correct it with a '
        'revision, which makes a new version.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

FROZEN_TRIGGER = """
CREATE TRIGGER results_frozen_sessions_append_only
BEFORE UPDATE OR DELETE ON results_releasedsessionresult
FOR EACH ROW EXECUTE FUNCTION results_frozen_sessions_are_append_only();
"""

DECISION_FUNCTION = """
CREATE OR REPLACE FUNCTION results_promotion_decisions_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_promotiondecision is append-only; % is not allowed. Record a '
        'new decision instead — both stand, and the later one is what holds.',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

DECISION_TRIGGER = """
CREATE TRIGGER results_promotion_decisions_append_only
BEFORE UPDATE OR DELETE ON results_promotiondecision
FOR EACH ROW EXECUTE FUNCTION results_promotion_decisions_are_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS results_frozen_sessions_append_only ON results_releasedsessionresult;
DROP FUNCTION IF EXISTS results_frozen_sessions_are_append_only();
DROP TRIGGER IF EXISTS results_promotion_decisions_append_only ON results_promotiondecision;
DROP FUNCTION IF EXISTS results_promotion_decisions_are_append_only();
"""


def seed_the_settings_row(apps, schema_editor):
    """One `SessionSettings` row per schema, at its defaults.

    `sessions.settings()` falls back to an unsaved default where the row is
    missing, exactly as `ratings.settings()` does — so this is a convenience
    rather than a load-bearing seed, and a schema created around this migration
    still reads correctly. It exists so that a school's settings are a row an
    administrator can find and edit rather than something that springs into
    existence the first time somebody saves.
    """
    apps.get_model("results", "SessionSettings").objects.get_or_create(pk=1)


def unseed(apps, schema_editor):
    apps.get_model("results", "SessionSettings").objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0012_three_term_view_and_promotion"),
    ]

    operations = [
        migrations.RunSQL(sql=FROZEN_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=FROZEN_TRIGGER, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=DECISION_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=DECISION_TRIGGER, reverse_sql=DROP),
        migrations.RunPython(seed_the_settings_row, unseed),
    ]
