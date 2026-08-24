"""Two triggers, doing two different jobs. Both about a card that has gone home.

`results/migrations/0003` made "a released sheet stays released" a rule Postgres
holds rather than one the service holds. These do the same for what the sheet
*says*, which is the half that actually reaches a parent.

## 1. A frozen rating is append-only

The shape `results/0002` and `fees/0002` use, and copied rather than factored
out for the reason `0002` gives: two tables in different apps with different
migration histories, and a helper imported across app boundaries to save eight
lines couples them forever.

`ReleasedTraitRating.save()` and `.delete()` already refuse, which is the error
a developer sees. This is the one a `psql` session, a data import or a bulk
`.update()` runs into — and a bulk `.update()` is the one that matters, because
it never goes near the model at all:

    ReleasedTraitRating.objects.filter(sheet=sheet).update(score=5)

would silently rewrite every child's conduct section on a card already issued,
with nothing anywhere recording that it had happened.

## 2. A released term's live ratings stop being editable

A different rule, on a different table, and it is worth being clear about what
it is *not* for. The frozen rows above are what a released card renders from, so
editing a live `TraitRating` after release **cannot change what a parent is
holding** — that is what the freeze is for, and it holds with or without this
trigger.

What this stops is the two disagreeing. Without it, a school's own screens would
happily show a rating of 5 for a child whose card, correctly and permanently,
says 3 — with nothing to say which is real. Somebody would then "fix" the card
to match the screen. Correcting a released result is a *revision*, which makes a
new version and leaves this one standing (task 8); it is not an UPDATE to the
row the old version was reckoned from.

### Why it has to look the sheet up

`TraitRating` deliberately stores no class group — `TraitRating`'s docstring
says why — so "has this rating's term been released for this child's class?" is
a join through `academics_classplacement` to `results_resultsheet`. A trigger
can do that, and this one does. The alternative was a denormalised
`class_group_id` on every rating, kept correct by nothing, which is a worse
answer to a smaller problem.

### Deliberately narrow: released only

Not "anything past draft". The service refuses those, and it should — a rating
must not move under a vice principal who is checking it — but that is a rule
about a review in progress, which an import fixing a mistyped batch may
legitimately need to work around, and a guard broader than its rule is one
somebody eventually turns off wholesale. `released` is terminal and has no
legitimate exception, which is exactly the line `0003` drew for the sheet.

Fires on INSERT as well as UPDATE and DELETE, unlike the append-only trigger
above: a *new* rating for a released term is as wrong as an edited one, and it
is the likelier mistake — a teacher rating a child in a term that closed while
their screen was open.
"""

from django.db import migrations

FROZEN_FUNCTION = """
CREATE OR REPLACE FUNCTION results_frozen_ratings_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_releasedtraitrating is append-only; % is not allowed. '
        'A released card has to keep saying what it said — correct it with a '
        'revision, which makes a new version.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

FROZEN_TRIGGER = """
CREATE TRIGGER results_frozen_ratings_append_only
BEFORE UPDATE OR DELETE ON results_releasedtraitrating
FOR EACH ROW EXECUTE FUNCTION results_frozen_ratings_are_append_only();
"""

# COALESCE(NEW, OLD): on DELETE, NEW is null. Both rows carry the same term and
# student, so either answers the question — but reading the wrong one is a
# null-guarded no-op, which is a trigger that silently permits the thing it was
# written to refuse.
LIVE_FUNCTION = """
CREATE OR REPLACE FUNCTION results_ratings_stop_at_release() RETURNS trigger AS $$
DECLARE
    subject results_traitrating%ROWTYPE;
    released_group text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subject := OLD;
    ELSE
        subject := NEW;
    END IF;

    SELECT g.name INTO released_group
    FROM results_resultsheet s
    JOIN academics_classplacement p
      ON p.class_group_id = s.class_group_id AND p.term_id = s.term_id
    JOIN academics_classgroup g
      ON g.id = s.class_group_id
    WHERE s.term_id = subject.term_id
      AND p.student_membership_id = subject.student_membership_id
      AND s.state = 'released'
    LIMIT 1;

    IF released_group IS NOT NULL THEN
        RAISE EXCEPTION
            'this term has been released for %; its ratings are part of a card '
            'somebody is holding and % is not allowed. Correcting a released '
            'result is a revision, which makes a new version.',
            released_group, TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

LIVE_TRIGGER = """
CREATE TRIGGER results_ratings_stop_at_release
BEFORE INSERT OR UPDATE OR DELETE ON results_traitrating
FOR EACH ROW EXECUTE FUNCTION results_ratings_stop_at_release();
"""

DROP_FROZEN_TRIGGER = (
    "DROP TRIGGER IF EXISTS results_frozen_ratings_append_only "
    "ON results_releasedtraitrating;"
)
DROP_FROZEN_FUNCTION = (
    "DROP FUNCTION IF EXISTS results_frozen_ratings_are_append_only();"
)
DROP_LIVE_TRIGGER = (
    "DROP TRIGGER IF EXISTS results_ratings_stop_at_release ON results_traitrating;"
)
DROP_LIVE_FUNCTION = "DROP FUNCTION IF EXISTS results_ratings_stop_at_release();"


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0006_seed_traits_and_scale"),
    ]

    operations = [
        migrations.RunSQL(sql=FROZEN_FUNCTION, reverse_sql=DROP_FROZEN_FUNCTION),
        migrations.RunSQL(sql=FROZEN_TRIGGER, reverse_sql=DROP_FROZEN_TRIGGER),
        migrations.RunSQL(sql=LIVE_FUNCTION, reverse_sql=DROP_LIVE_FUNCTION),
        migrations.RunSQL(sql=LIVE_TRIGGER, reverse_sql=DROP_LIVE_TRIGGER),
    ]
