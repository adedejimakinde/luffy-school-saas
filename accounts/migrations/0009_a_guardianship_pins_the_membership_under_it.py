"""A membership a guardianship points at stays a student, and stays somebody else's child.

Issue #96, second slice, and the one that closes it. The first slice
(`0008_guardianship_rules_are_a_trigger`) put both of `Guardianship.clean()`'s
rules behind a trigger on `accounts_guardianship`, which closed `bulk_create()`
and `QuerySet.update()`. It could not close the third path, because that path
writes nothing to `accounts_guardianship`:

    Membership.objects.filter(pk=child.pk).update(role=Role.BURSAR)

Both rules read *through* `Guardianship.student` into `accounts_membership` —
rule 1 reads `role`, rule 2 reads `user_id`. Change either column underneath a
live link and the link is invalid, with no row of `accounts_guardianship`
written for any trigger on that table to fire on. So the guard has to sit here.

## This is not the `*_stop_at_release` pattern, and copying it would get this wrong

The near miss is real and worth naming, because it is what the next person will
find first. `gradebook_scores_stop_at_release`,
`results_comments_stop_at_release` and `results_ratings_stop_at_release` each
sit on one table and *read* another to decide — the sheet through
`academics_classplacement`, the frozen ratings in `results_releasedtraitrating`.
That looks like this file and is a different thing:

    *_stop_at_release   read another table's state, refuse YOUR OWN row's rule
    this trigger        refuse your own row because it would break ANOTHER
                        TABLE'S rule

In the first, the invariant and the refused row belong to the same table: a
`Score` may not change once its card is released, and "is it released?" is
merely a question asked elsewhere. Every one of the repo's other 13 triggers is
that shape too — `BEFORE ... ON <the table whose rows it protects>`.

Here the refused row is a `Membership` and the invariant is `Guardianship`'s.
Three consequences that shape everything below:

1. **The error arrives on a statement that never mentions guardianship.** An
   admin fixing a data-entry mistake with one `UPDATE` is refused by a table
   they did not name. The messages therefore say which guardianship row
   blocked it, and what to call to clear it. That is not politeness; a refusal
   the reader cannot connect to anything reads as a platform bug.
2. **It is a coupling from `accounts_membership` to `accounts_guardianship`
   that exists nowhere in the model layer.** `Membership` has no field, no
   `clean()` rule and no service that mentions guardianship. Its docstring now
   names this trigger, because the migration alone is not somewhere a reader
   of `Membership` looks.
3. **Dropping or re-scoping `Guardianship` later has to drop a trigger on a
   different table.** Said here and in `Membership`'s docstring; there is no
   third place it would be found.

## Narrow, and narrow twice over — which the control run is how we know

What must keep working is `release_student()`. It ends an enrolment — `status`,
`ended_on`, `updated_at` — while deliberately **keeping** every guardianship row
pointing at the now-ended membership, because those rows are the only record of
who the child's guardians were and the receiving school re-links from them. A
guard that refused any update to a linked membership would refuse a transfer.
`grant_membership()` reviving an ended row is the other side of it: a plain
`save()`, so the UPDATE carries every column including `role`, with the same
value.

There are **two independent reasons** neither of those is refused, and the
honest statement is that either one alone would be enough:

1. `NEW.role <> 'student'`, which is not a narrowing at all — it is the rule.
   Release and revive both leave `role = 'student'`.
2. The change detection, `IS DISTINCT FROM` plus the early return. Release
   writes three columns and none of them is `role`; revive writes `role` with
   the value it already had.

**Measured, because the first draft of this paragraph claimed (1) did not exist
and (2) was load-bearing, and both halves were wrong.** Removing the early
return alone left the whole of `accounts.tests.test_membership` green — 103
tests, `OK`. Removing `NEW.role <> 'student'` alone, same. Removing **both** at
once produced 16 errors and a failure, taking down `release_student()`,
`transfer_student()` and both of this file's own width tests with them. So the
redundancy is real, and it is what the tests actually assert; no test
distinguishes the two, and none can, because the application never produces a
statement the two disagree about.

Which leaves the early return as **an optimisation with one behavioural
consequence**, stated rather than discovered later:

* Two index probes are skipped on every membership UPDATE that touches neither
  column, which is nearly all of them — every status change, every
  `display_name` or `reference` edit, every `end()`.
* A row that is *already* in breach — a non-student membership that somehow has
  a guardianship — stays editable. Without the early return, any UPDATE to such
  a row would be refused, including one trying to fix it. No such row can be
  created any more, so nothing tests this; it is the reason to prefer the early
  return rather than a reason it is required.

And the application changes neither column. `grant_membership()` creates one row
per role, and no code path in this repo reassigns `role` or `user`, which makes
this a floor under hand-written and bulk statements rather than a rule the
services have to work around.

## INSERT as well as UPDATE, and why that is not scope creep

`BEFORE INSERT OR UPDATE`. The UPDATE half is the path #96 names. The INSERT
half closes a hole that was measured while building this one, and it costs one
index probe on a column that has an index.

Every foreign key in this project is `DEFERRABLE INITIALLY DEFERRED`, so within
one transaction a guardianship row may be inserted *before* the membership it
points at. `0008`'s trigger handles that by design: its `SELECT` finds no
membership, it returns `NEW`, and it lets the foreign key own referential
integrity. The foreign key then asks only "does a row exist?", and at COMMIT one
does — so the pair commits with neither rule ever applied to it. Measured:
inserting a guardianship against an id that does not exist yet and then
inserting a `role='bursar'` membership at that id succeeds, and leaves a bursar
carrying a guardianship.

Guarding INSERT here answers it from the side that *can* see both rows. It is
not reachable through the ORM in normal use — a generated id has nothing
pointing at it — so the probe is false for every membership the application
creates.

## DELETE is not here, and does not need to be

Checked rather than assumed, twice over:

* `Guardianship.student` is `on_delete=models.PROTECT`, so the ORM refuses with
  `ProtectedError` before any statement is sent — including through
  `QuerySet.delete()`, which routes through the same collector.
* A raw `DELETE FROM accounts_membership` past the ORM is refused by the
  foreign key `accounts_guardianshi_student_id_092b3a78_fk_accounts_` — as
  `IntegrityError`, at COMMIT, because it is deferred.

A DELETE branch here would refuse something already refused, and would report a
referential-integrity failure under a guardianship rule's name. That is the same
argument `0008` makes for its `NOT FOUND` branch: the foreign key owns this, and
dressing its refusal up as a role violation makes the message worse rather than
better.

Worth knowing the shape of the one difference: the FK's refusal is *deferred* to
COMMIT, so a raw delete inside a long transaction is accepted statement-by-
statement and fails at the end. That is a property of every FK in this schema,
not of guardianship, and it is not this migration's to change.

## ERRCODE, and the two identifiers

`restrict_violation` is SQLSTATE 23001, integrity-constraint-violation class,
which Django surfaces as `IntegrityError`. Every `RAISE EXCEPTION` in this
repo's migrations carries it and `tests/refusals.py`'s `assertRefusedBy` depends
on it.

**Keep `USING ERRCODE = 'restrict_violation'` on one line.**
`tests/test_refusals_are_constraints.py` walks every migration's SQL literals
and requires that exact contiguous string in each `RAISE` statement, so wrapping
after `USING` — which is legal plpgsql and reads better next to a three-part
message — fails it. That is the guard behaving correctly and was measured here:
the first draft of this file wrapped, and the suite refused it. Do not loosen
the matcher to accommodate a line break; a repo-wide convention is worth more
than this file's indentation.

Each message opens with a stable rule identifier, per issue #89. The two here
are deliberately **not** the two `0008` raises, even though rule 1 is
word-for-word the same rule:

    accounts_guardianship  guardianship_student_must_be_a_student
                           guardianship_guardian_is_not_the_student
    accounts_membership    membership_role_is_pinned_by_a_guardianship
                           membership_user_is_pinned_by_a_guardianship

Sharing an identifier would leave a test unable to say *which table's trigger*
refused, which is exactly the indistinguishable-refusal problem #89 is about —
and here the two tables are the whole point of the slice.

## The messages

Three parts each, because Postgres has three and folding them into one line
loses the distinction: `MESSAGE` is the refusal, `DETAIL` is which row caused
it, `HINT` is what to do. `psycopg2` puts all three into the string Django
wraps, so `assertRefusedBy` matches against any of them.

The child is named the way `Membership.name` names them —
`display_name` first, falling back to `user.full_name` — because a school may
know a child by an admission name rather than the one on the login. That is
the same distinction `docs/operating-rules.md` rule 2 records as having been
got wrong once already on a released card.

## Shared app, so one trigger for the whole platform

`accounts` is in `SHARED_APPS` only. This runs once against `public` and guards
every school's rows at once, exactly as `0008` does and unlike the tenant-app
triggers, which `migrate_schemas` creates once per school schema. A reader who
knows the tenant pattern should not assume this follows it.
"""

from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION accounts_membership_guardianship_rules() RETURNS trigger AS $$
DECLARE
    role_changed boolean := TRUE;
    user_changed boolean := TRUE;
    link_id bigint;
    link_guardian_id bigint;
    guardian_name text;
    child_name text;
    link_count integer;
BEGIN
    -- OLD is unassigned on INSERT, and reading a field of it there raises
    -- rather than yielding NULL -- so this cannot be folded into the condition
    -- below however the AND is ordered, because PL/pgSQL evaluates the whole
    -- expression's parameters before any short-circuit. Both flags stay TRUE
    -- for an INSERT, which is the right answer: every column of a new row is
    -- new.
    IF TG_OP = 'UPDATE' THEN
        role_changed := NEW.role IS DISTINCT FROM OLD.role;
        user_changed := NEW.user_id IS DISTINCT FROM OLD.user_id;
    END IF;

    -- Neither rule reads any other column, and release_student() writes
    -- status, ended_on and updated_at under live links.
    IF NOT role_changed AND NOT user_changed THEN
        RETURN NEW;
    END IF;

    IF role_changed AND NEW.role <> 'student' THEN
        SELECT g.id, g.guardian_id, u.full_name
          INTO link_id, link_guardian_id, guardian_name
        FROM accounts_guardianship g
        JOIN accounts_user u ON u.id = g.guardian_id
        WHERE g.student_id = NEW.id
        ORDER BY g.id
        LIMIT 1;

        -- A named id rather than IF FOUND: FOUND is global to the block and
        -- reset by the next query of several kinds, so the adjacency that
        -- makes it correct is something a comment asks for and nothing
        -- enforces. The same reasoning as gradebook 0002 and results 0011.
        IF link_id IS NOT NULL THEN
            SELECT count(*) INTO link_count
            FROM accounts_guardianship WHERE student_id = NEW.id;

            -- display_name first, exactly as Membership.name resolves it: a
            -- school may know a child by an admission name rather than the one
            -- on the login, and naming the wrong one is a mistake this project
            -- has already made once on a released card (rule 2).
            SELECT COALESCE(NULLIF(NEW.display_name, ''), u.full_name)
              INTO child_name
            FROM accounts_user u WHERE u.id = NEW.user_id;

            RAISE EXCEPTION
                'membership_role_is_pinned_by_a_guardianship: membership % (%) '
                'is the student on % guardianship row(s), so this % cannot set '
                'its role to %. A membership a guardianship points at stays a '
                'STUDENT membership.',
                NEW.id, COALESCE(child_name, '?'), link_count, TG_OP, NEW.role
                USING ERRCODE = 'restrict_violation',
                    DETAIL = format(
                        'Guardianship %s links guardian %L (user %s) to this '
                        'membership, and accounts_guardianship requires every '
                        'link to point at a STUDENT membership. This statement '
                        'wrote no guardianship row: the rule it breaks belongs '
                        'to that table, one table over, which is why nothing '
                        'in the statement names it.',
                        link_id, guardian_name, link_guardian_id
                    ),
                    HINT = format(
                        'Call accounts.services.unlink_guardian(guardian, '
                        'student) for each of the %s link(s) first -- it drops '
                        'the link, and ends that parent''s PARENT membership at '
                        'the school if it was their last child there -- then '
                        'change the role.',
                        link_count
                    );
        END IF;
    END IF;

    IF user_changed THEN
        SELECT g.id, u.full_name INTO link_id, guardian_name
        FROM accounts_guardianship g
        JOIN accounts_user u ON u.id = g.guardian_id
        WHERE g.student_id = NEW.id AND g.guardian_id = NEW.user_id
        LIMIT 1;

        IF link_id IS NOT NULL THEN
            RAISE EXCEPTION
                'membership_user_is_pinned_by_a_guardianship: membership % '
                'cannot be handed to user %, who is a guardian of it.',
                NEW.id, NEW.user_id
                USING ERRCODE = 'restrict_violation',
                    DETAIL = format(
                        'Guardianship %s links guardian %L (user %s) to this '
                        'membership, and accounts_guardianship does not allow '
                        'a student to be their own guardian. This statement '
                        'wrote no guardianship row: the rule it breaks belongs '
                        'to that table, one table over.',
                        link_id, guardian_name, NEW.user_id
                    ),
                    HINT =
                        'Call accounts.services.unlink_guardian(guardian, '
                        'student) for that link first, then move the '
                        'membership.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER accounts_membership_guardianship_rules
BEFORE INSERT OR UPDATE ON accounts_membership
FOR EACH ROW EXECUTE FUNCTION accounts_membership_guardianship_rules();
"""

DROP_TRIGGER = (
    "DROP TRIGGER IF EXISTS accounts_membership_guardianship_rules "
    "ON accounts_membership;"
)
DROP_FUNCTION = "DROP FUNCTION IF EXISTS accounts_membership_guardianship_rules();"


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_guardianship_rules_are_a_trigger"),
    ]

    operations = [
        migrations.RunSQL(sql=FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
