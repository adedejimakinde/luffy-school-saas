"""Make `Guardianship.clean()`'s two rules something Postgres holds.

Issue #96, first slice. `save()` asks `clean()`, so every per-instance ORM write
is covered — and that is exactly the set of paths `bulk_create()` and
`QuerySet.update()` are not in. Both compile straight to SQL without
instantiating the model, so neither has ever asked either rule. These tests
recorded that as a known limit; this migration closes the half of it that lives
on this table.

## Why not a CheckConstraint

Both rules are **cross-table** — each compares a column on `accounts_guardianship`
against a column on the `accounts_membership` row it points at. Checked against
this project's own Django and Postgres rather than assumed, and recorded at
length in `Guardianship.clean()`:

    CheckConstraint(condition=Q(student__role=Role.STUDENT))
    -> FieldError: Joined field references are not permitted in this query

    ALTER TABLE ... CHECK ((SELECT role FROM accounts_membership ...) = 'student')
    -> NotSupportedError: cannot use subquery in check constraint

A row-level trigger is what is left, and it is how this codebase already
enforces the append-only tables.

## The first trigger in a SHARED app, and it is a different shape

Every other trigger in this repo — `fees_ledger_append_only`,
`results_release_is_final`, the eight frozen-table guards, the three
`*_stop_at_release` — lives in a TENANT app. Those are created unqualified
during each school's `migrate_schemas`, so each school gets its own copy in its
own schema and dropping a school takes its trigger with it.

`accounts` is in `SHARED_APPS` only. This runs once, against `public`, and the
one trigger it creates guards **every school's rows at once** — because
`accounts_guardianship` is one table in `public` for the whole platform, the
same reason `uniq_guardianship_guardian_student` is one index over all of them.
A reader who knows the tenant-app pattern should not assume this follows it.

## ERRCODE, and why it is load-bearing

`restrict_violation` is SQLSTATE 23001, in the integrity-constraint-violation
class, which Django surfaces as `IntegrityError`. Every `RAISE EXCEPTION` in
this repo's migrations carries it, and `tests/refusals.py`'s `assertRefusedBy`
depends on it: raised with the default `P0001` this would arrive as
`InternalError` instead and no test could pin it as a constraint refusal.

Each message opens with a stable rule identifier —
`guardianship_student_must_be_a_student`, `guardianship_guardian_is_not_the_student`
— because a trigger has no constraint name for Postgres to report, and issue #89
is about assertions that cannot tell one refusal from another. Those two tokens
are what tests match on; the prose after them is free to be rewritten.

## Deliberately not here

**`BEFORE INSERT OR UPDATE`, not `DELETE`.** Deleting a guardianship breaks
neither rule.

**Nothing on `accounts_membership`.** The third path in #96 — changing the role
of a membership a guardianship already points at — invalidates a link without
writing to this table at all, so no trigger here can see it. Closing it needs a
guard on `accounts_membership` protecting an invariant owned by
`accounts_guardianship`, which is a shape this repository has nowhere. That is a
different table, a different precedent, and its own review. It stays open in
#96.

**A missing membership row is not this trigger's refusal.** If the `SELECT`
finds nothing the trigger returns and lets the foreign key answer, which is the
constraint that actually owns referential integrity. Without the `NOT FOUND`
branch a deferred-FK insert would be refused here first, reporting a missing row
as a role violation.
"""

from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION accounts_guardianship_rules() RETURNS trigger AS $$
DECLARE
    student_role text;
    student_user_id bigint;
BEGIN
    SELECT role, user_id INTO student_role, student_user_id
    FROM accounts_membership
    WHERE id = NEW.student_id;

    IF NOT FOUND THEN
        -- No membership row to judge against. The foreign key owns that
        -- refusal; reporting it here would dress it up as a role violation.
        RETURN NEW;
    END IF;

    IF student_role <> 'student' THEN
        RAISE EXCEPTION
            'guardianship_student_must_be_a_student: a guardianship must point '
            'at a STUDENT membership; membership % is %.',
            NEW.student_id, student_role
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF NEW.guardian_id = student_user_id THEN
        RAISE EXCEPTION
            'guardianship_guardian_is_not_the_student: a student cannot be '
            'their own guardian; user % is both.', NEW.guardian_id
            USING ERRCODE = 'restrict_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER accounts_guardianship_rules
BEFORE INSERT OR UPDATE ON accounts_guardianship
FOR EACH ROW EXECUTE FUNCTION accounts_guardianship_rules();
"""

DROP_TRIGGER = (
    "DROP TRIGGER IF EXISTS accounts_guardianship_rules ON accounts_guardianship;"
)
DROP_FUNCTION = "DROP FUNCTION IF EXISTS accounts_guardianship_rules();"


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_alter_membership_role"),
    ]

    operations = [
        migrations.RunSQL(sql=FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
