"""A recorded payment is corrected only by an exact reversal, and Postgres holds it.

`0002` already refuses `UPDATE` and `DELETE` on every ledger row, so a recorded
payment cannot be edited or removed by anything: the app, the admin, a shell, a
data import or `psql`. What it did not hold is the other half of the rule, the
correction itself. A reversal is a new row, an `INSERT`, and the rules that make
it a correction rather than a second, quieter edit lived only in Python
(`FeeLedgerEntry.clean()` and `services.reverse_entry()`). A raw insert could
post a "reversal" of a different amount, against a different child or term, of
another reversal, with no reason and no person. Each of those is a way to move a
balance while appearing to correct a mistake.

So:

- **Two check constraints**, `a_reversal_says_why` (a reason that is not blank)
  and `a_reversal_says_who` (the person who made it). The rows already in the
  books pass both: every reversal so far came through `services.undo()`, which
  required a reason, and through the route, which always named the person.
- **An insert trigger**, `fees_reversal_is_exact`, refusing a reversal that is
  not the exact opposite of the entry it names: the same child, the same term,
  the opposite amount, and an entry that is not itself a reversal. "At most
  once" is already the unique index `an_entry_is_reversed_at_most_once`.
- **`0002`'s guard, installed again.** `DROP TRIGGER IF EXISTS` and
  `CREATE TRIGGER`, with the function replaced by the same body, so a schema
  whose guard was dropped by hand gets it back. Nothing a reversal needs is
  carved out of it: a reversal changes no column of the entry it undoes.

**Every school, including the next one.** Everything here is created
unqualified, so it lands in the schema `migrate_schemas` is migrating, which is
the school's own. A new school's schema is migrated from `0001` when it is
created (`School.auto_create_schema`), so it gets these the same way. The
trigger function reads the target row through `TG_TABLE_SCHEMA`, never through
the `search_path`, so it can only ever compare against a row in the same school.

Reversed, the constraints and the insert trigger go; `0002`'s guard stays, since
`0002` installed it.
"""

from django.db import migrations, models

REVERSAL_FUNCTION = r"""
CREATE OR REPLACE FUNCTION fees_reversal_is_exact() RETURNS trigger AS $$
DECLARE
    target_kind text;
    target_amount bigint;
    target_student bigint;
    target_term bigint;
BEGIN
    EXECUTE format(
        'SELECT kind, amount_kobo, student_membership_id, term_id FROM %I.%I WHERE id = $1',
        TG_TABLE_SCHEMA, TG_TABLE_NAME
    )
    INTO target_kind, target_amount, target_student, target_term
    USING NEW.reverses_id;

    -- `EXECUTE` does not set `FOUND`, so the row's absence is read from the
    -- value: `kind` is never null on a row that exists.
    IF target_kind IS NULL THEN
        -- No such entry: the foreign key refuses it, with its own message.
        RETURN NEW;
    END IF;
    IF target_kind = 'reversal' THEN
        RAISE EXCEPTION
            'A reversal cannot itself be reversed. Reverse the original entry.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.amount_kobo IS DISTINCT FROM -target_amount
       OR NEW.student_membership_id IS DISTINCT FROM target_student
       OR NEW.term_id IS DISTINCT FROM target_term THEN
        RAISE EXCEPTION
            'A reversal must undo its entry exactly: the same child, the same term '
            'and the opposite amount.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

REVERSAL_TRIGGER = """
CREATE TRIGGER fees_reversal_is_exact
BEFORE INSERT ON fees_feeledgerentry
FOR EACH ROW WHEN (NEW.kind = 'reversal')
EXECUTE FUNCTION fees_reversal_is_exact();
"""

DROP_REVERSAL_TRIGGER = "DROP TRIGGER IF EXISTS fees_reversal_is_exact ON fees_feeledgerentry;"
DROP_REVERSAL_FUNCTION = "DROP FUNCTION IF EXISTS fees_reversal_is_exact();"

#: `0002`'s function and trigger, word for word, installed again.
APPEND_ONLY_AGAIN = """
CREATE OR REPLACE FUNCTION fees_ledger_is_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'fees_feeledgerentry is append-only; % is not allowed. '
        'Post a reversal naming the entry instead.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS fees_ledger_append_only ON fees_feeledgerentry;
CREATE TRIGGER fees_ledger_append_only
BEFORE UPDATE OR DELETE ON fees_feeledgerentry
FOR EACH ROW EXECUTE FUNCTION fees_ledger_is_append_only();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0008_a_term_says_the_day_its_attendance_is_counted_to"),
        ("fees", "0009_an_unmatched_payment_is_placed_once"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="feeledgerentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("kind", "reversal"), _negated=True),
                    ("narration__regex", "\\S"),
                    _connector="OR",
                ),
                name="a_reversal_says_why",
            ),
        ),
        migrations.AddConstraint(
            model_name="feeledgerentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("kind", "reversal"), _negated=True),
                    ("recorded_by_id__isnull", False),
                    _connector="OR",
                ),
                name="a_reversal_says_who",
            ),
        ),
        migrations.RunSQL(sql=REVERSAL_FUNCTION, reverse_sql=DROP_REVERSAL_FUNCTION),
        migrations.RunSQL(sql=REVERSAL_TRIGGER, reverse_sql=DROP_REVERSAL_TRIGGER),
        migrations.RunSQL(sql=APPEND_ONLY_AGAIN, reverse_sql=migrations.RunSQL.noop),
    ]
