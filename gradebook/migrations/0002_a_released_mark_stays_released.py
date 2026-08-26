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
service is where the broader rule belongs, because relaxing it there is a code
change rather than a migration.

**No stand-down exists today, and `ANY_VERSION` is not one.** An earlier draft
of this file justified the narrowness by saying the service "can be told to
stand down for one import", which described a feature nothing implements:
`ANY_VERSION` is a *version* sentinel, and `set_score()` runs the state guard
before it dispatches on it, so the bulk-import path is refused with everything
else. The narrowness above stands on its own argument and does not need that
one — `released` is terminal, and `submitted` and `checked` are a rule about a
review in progress. If a real import hatch is ever wanted, the service is where
it goes, and this trigger is the floor it cannot go under.

It fires on INSERT as well as UPDATE and DELETE: a *new* mark for a released
term is as wrong as an edited one, and likelier — a teacher entering marks for
a term that closed while their screen was open.

## Two checks, and the first one is the right key

The first asks **has a card for this child already gone home**, off
`results_releasedtraitrating` — the frozen conduct section, one row per child
per visible trait, written inside the transaction that releases the sheet. That
is a fact about the child and about an event that happened, so a class move
cannot move it. It is the same key `0011` uses one table over, and the same
sentence: a guard on a released artefact keys off the artefact.

An earlier draft of this file did not have that check, on the reasoning that
"nothing freezes marks until task 3". That conflated two claims. The marks are
indeed not frozen — task 3's job — but the guarantee wanted here is *a card went
home*, and the ratings freeze answers it for any school with the conduct section
on, whether or not the marks are in it.

The second asks whether the child's **current** class is released, and is still
needed, because `Score` reaches a class only through
`academics_classplacement`. `Assessment` belongs to a `(term, subject)` and
deliberately not to a class, because one paper is sat by every class taught that
subject — `results/positions.py` builds a broadsheet by taking every assessment
for the term and slicing it by the class's roster, and that slice is only
necessary because assessments span classes.

**What is left, stated rather than discovered later:** a school with the conduct
section *off* freezes no rows at all, so for that school the first check finds
nothing and a child moved after release is looked up against the new class's
draft and permitted. It is a per-school gap rather than a per-child one, it is
the same residue `0011` records, and it closes with the unconditional per-child
"a card went home" marker required by task 3 in
[issue #34](https://github.com/adedejimakinde/luffy-school-saas/issues/34) —
after which the first check reads that marker instead and the placement join
becomes a fallback.

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
    card_went_home boolean;
    class_is_released boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subject := OLD;
    ELSE
        subject := NEW;
    END IF;

    -- Has a card for this child already been frozen and sent home? Answered
    -- without reference to where the child is placed now, which is the point:
    -- a class move rewrites the placement and cannot touch this.
    SELECT g.name, TRUE INTO released_group, card_went_home
    FROM gradebook_assessment a
    JOIN results_resultsheet s
      ON s.term_id = a.term_id
    JOIN results_releasedtraitrating rt
      ON rt.sheet_id = s.id
    JOIN academics_classgroup g
      ON g.id = s.class_group_id
    WHERE a.id = subject.assessment_id
      AND rt.student_membership_id = subject.student_membership_id
    LIMIT 1;

    IF card_went_home THEN
        RAISE EXCEPTION
            'this card was released to a parent with %; a released card has to '
            'keep saying what it said and % is not allowed. Correcting a '
            'released mark is a revision, which makes a new version.',
            released_group, TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- And is the child's current class released? Still asked, because a school
    -- with the conduct section off froze no rows above for this to find.
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
        # `results_releasedtraitrating`, `academics_classplacement` and
        # `academics_classgroup`, so all four have to exist before it is
        # created. Postgres does not resolve those
        # names until the function runs, so without these the migration would
        # apply cleanly and fail at the first mark entered.
        # `results_releasedtraitrating` arrives in `0005`, and the first
        # check in the body reads it.
        ("results", "0005_conduct_and_skills_ratings"),
        ("academics", "0003_classgroup_classplacement"),
    ]

    operations = [
        migrations.RunSQL(sql=LIVE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=LIVE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
