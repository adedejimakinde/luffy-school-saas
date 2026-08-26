"""A mark on a released card is not editable, and the table says so.

The approval chain and the gradebook were built in the right order and never
introduced. `results` spends two database guards and a long docstring making
release terminal — `nothing_moves_out_of_released` on the log, and `0003`'s
trigger on the sheet — and until now neither was in the way of the write that
actually changes what a card says. The chain's promise is "this is what was
released"; it held for the sheet's **state** and not for its **contents**.

## Narrow on purpose

`released` only, matching `results` `0003` rather than the service guard that
lands alongside this. `released` is terminal and has no legitimate exception,
while `submitted` and `checked` are a rule about a review in progress that an
import fixing a mistyped batch may legitimately need to work around. A guard
broader than its rule is one somebody eventually turns off wholesale — and the
service is where the broader rule belongs, because it can be told to stand down
for one import without a migration.

It fires on INSERT as well as UPDATE and DELETE: a *new* mark for a released
term is as wrong as an edited one, and likelier — a teacher entering marks for
a term that closed while their screen was open.

## Why it joins through the placement, knowing what that costs

`Score` reaches a class only through `academics_classplacement`. `Assessment`
belongs to a `(term, subject)` and deliberately not to a class, because one
paper is sat by every class taught that subject — `results/positions.py` builds
a broadsheet by taking every assessment for the term and slicing it by the
class's roster, and that slice is only necessary because assessments span
classes.

So this asks where the child sits, which `0010` and `0011` have just spent two
migrations removing from the guards on remarks and ratings. **It is the wrong
key and it is the only key available here.** Those two could stop asking it
because a frozen per-child artefact existed to ask instead; nothing freezes
marks until task 3.

**The hole this leaves, stated rather than discovered later:** release JSS 1A,
move the child to JSS 3B, and this finds JSS 3B's draft and permits the write.
The child who stayed put is refused. That is the same inconsistency `0010` and
`0011` closed, left open here for want of an artefact — and it closes with the
unconditional per-child "a card went home" marker required by task 3 in
[issue #34](https://github.com/adedejimakinde/luffy-school-saas/issues/34).
When that lands, the first check to add here is the one that reads it, and this
placement join becomes the fallback rather than the whole guard.

Guarding the stayed-put case is still worth doing on its own: it is the common
case by far, and leaving the table open because it cannot be closed completely
is how a guarantee becomes a comment.

## The spelling

A named boolean rather than `IF FOUND`, for the reasons `0011` sets out at
length: `FOUND` is global to the block and reset by the most recent query of
several kinds, `PERFORM` among them, so the adjacency that makes it correct is
something a comment asks for and nothing enforces. Testing the selected column
for NULL instead breaks the day `academics_classgroup.name` becomes nullable.
A literal `TRUE` in its own variable is immune to both, and `SELECT INTO` with
no matching row nulls every target so `IF <null>` does not fire.
"""

from django.db import migrations

LIVE_FUNCTION = """
CREATE OR REPLACE FUNCTION gradebook_scores_stop_at_release() RETURNS trigger AS $$
DECLARE
    subject gradebook_score%ROWTYPE;
    released_group text;
    class_is_released boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subject := OLD;
    ELSE
        subject := NEW;
    END IF;

    SELECT g.name, TRUE INTO released_group, class_is_released
    FROM gradebook_assessment a
    JOIN results_resultsheet s
      ON s.term_id = a.term_id
    JOIN academics_classplacement p
      ON p.class_group_id = s.class_group_id AND p.term_id = s.term_id
    JOIN academics_classgroup g
      ON g.id = s.class_group_id
    WHERE a.id = subject.assessment_id
      AND p.student_membership_id = subject.student_membership_id
      AND s.state = 'released'
    LIMIT 1;

    IF class_is_released THEN
        RAISE EXCEPTION
            'this term has been released for %; its marks are part of a card '
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
CREATE TRIGGER gradebook_scores_stop_at_release
BEFORE INSERT OR UPDATE OR DELETE ON gradebook_score
FOR EACH ROW EXECUTE FUNCTION gradebook_scores_stop_at_release();
"""

DROP_TRIGGER = (
    "DROP TRIGGER IF EXISTS gradebook_scores_stop_at_release ON gradebook_score;"
)
DROP_FUNCTION = "DROP FUNCTION IF EXISTS gradebook_scores_stop_at_release();"


class Migration(migrations.Migration):

    dependencies = [
        ("gradebook", "0001_initial"),
        # The trigger body names `results_resultsheet`,
        # `academics_classplacement` and `academics_classgroup`, so all three
        # have to exist before it is created. Postgres does not resolve those
        # names until the function runs, so without these the migration would
        # apply cleanly and fail at the first mark entered.
        ("results", "0001_initial"),
        ("academics", "0003_classgroup_classplacement"),
    ]

    operations = [
        migrations.RunSQL(sql=LIVE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=LIVE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
