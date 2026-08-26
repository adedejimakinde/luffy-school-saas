"""The freeze is about `(term, student)`, not about where the child sits.

`0007` asked "has this rating's term been released **for this child's class**?"
and answered it by joining through `academics_classplacement`. That join reads
the placement the child has *now*, which is a different question from the one
the guarantee is about, and the two answers part company the moment the office
moves anybody. `0010` made this correction for remarks; this is the same
correction for ratings, and the last placement join in a release guard.

## The case

Release JSS 1A. Ada's ratings freeze into `results_releasedtraitrating` and her
card goes home. The office then moves Ada to JSS 3B — legitimate, mid-term, and
what `academics.move_student()` is for. JSS 3B's sheet is a draft nobody has
opened. Her class teacher there rates her on the same trait.

`0007` looks for a released sheet joined to Ada's placement: that is now JSS 3B,
whose sheet is a draft, so it finds nothing and permits the write. The frozen
card says one thing and the school's screen another, and nothing records that
they disagree. It was refused for the child who stayed in JSS 1A, so the two
children got different answers about what had happened to their cards because
they were sitting in different rooms.

**A guard on a released artefact keys off the artefact, not off the child's
current placement.** Placement is a live fact that changes; release is an event
that happened, and what records it is the frozen row.

## Additive, and the second check is not the second half of a pair

The first check now asks the frozen rows directly. Unlike `0010`'s pair, it does
almost all the work on its own: `ratings.freeze_for_release()` writes a row for
every child on the roster × every visible trait, including the traits nobody
rated, so every child of a ratings-enabled release has rows for this to find.
There is no per-child gap of the kind that makes both of `0010`'s checks
load-bearing.

The placement check is kept for a per-*school* gap instead. `freeze_for_release()`
returns early when no group is enabled, and again when no trait is visible, so
such a release freezes nothing for anybody. `ratings.rate()` cannot be reached
while the section is off — `_require_a_ratable_trait()` raises `SectionNotEnabled`
first — but a school that switches it on *after* a term was released makes it
reachable, and the first check has nothing to find. The child who stayed put is
refused by the second check; dropping it would make the two children disagree
again, which is the bug this migration exists to remove.

## One case neither check sees

That same ratings-disabled release, for a child who is then moved. Nothing was
frozen, so the first check finds nothing, and the second is looking at the new
class. It is written down rather than denied, the way `0010` writes down its own.

Closing it needs a per-child record that a card went home, written at release
whatever the configuration says. That is recorded as a **requirement** on task 3
in [issue #34](https://github.com/adedejimakinde/luffy-school-saas/issues/34),
and it is deliberately not built here: it is the heart of that phase, and
building it inside a bug fix would design it with no review gate. It cannot be
reconstructed from placement either — `academics.ClassPlacement` constrains one
group per child per term, so a move *rewrites* the row and the record of where
the child sat at release is destroyed rather than superseded.

Until then the divergence is bounded to a school that published a card with no
conduct section at all, and `ratings.card_sections()` still prints none for it:
a child with no frozen rows whose class sheet is released renders no section.
"""

from django.db import migrations

# On DELETE, NEW is null, so the row being asked about is OLD. Both rows carry
# the same term and student, so either answers the question — but reading the
# wrong one is a null-guarded no-op, which is a trigger that silently permits
# the thing it was written to refuse.
#
# `CREATE OR REPLACE` under the name `0007` already created. The trigger that
# `0007` declared goes on pointing at this name, so replacing the body is the
# whole change and there is no window in which the table is unguarded.
#
# Two `SELECT ... INTO` blocks, each with its own check immediately after it,
# and **neither check uses `FOUND`** — the spelling `0007` used and `0010`
# replaced, for two reasons that are worth keeping together:
#
# `FOUND` is global to the block and reset by the *most recent* query of several
# kinds, `PERFORM` among them, which does not look like a query that would touch
# it. Proven rather than assumed: a `SELECT` matching nothing followed by
# `PERFORM 1` leaves `FOUND` **true**. With one check that hazard was latent;
# with two it is one inserted statement away from inverting a guard.
#
# And the obvious alternative — testing the selected column for NULL — is what
# `0007`'s own comment rejected, correctly: `SELECT g.name INTO released_group`
# leaves the variable NULL both when no row matched *and* when a row matched
# whose name is NULL, so the refusal becomes a permit the day
# `academics_classgroup.name` becomes nullable. Measured: with a matching row
# whose name is NULL, `released_group IS NOT NULL` is **false**.
#
# So each block selects a literal `TRUE` into its own boolean. A literal cannot
# be NULL when a row matched, which is what the nullable column could not
# promise; and a named variable cannot be reset by an intervening statement,
# which is what `FOUND` could not promise. `SELECT INTO` with no matching row
# nulls every target, and `IF <null>` does not fire, so the absent case is right
# without a default.
LIVE_FUNCTION = """
CREATE OR REPLACE FUNCTION results_ratings_stop_at_release() RETURNS trigger AS $$
DECLARE
    subject results_traitrating%ROWTYPE;
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
    -- without reference to where the child is placed now, which is the point.
    -- Every child of a ratings-enabled release has rows here, including for the
    -- traits nobody rated, so this is the check that carries the guarantee.
    SELECT g.name, TRUE INTO released_group, card_went_home
    FROM results_releasedtraitrating rt
    JOIN results_resultsheet s
      ON s.id = rt.sheet_id
    JOIN academics_classgroup g
      ON g.id = s.class_group_id
    WHERE s.term_id = subject.term_id
      AND rt.student_membership_id = subject.student_membership_id
    LIMIT 1;

    IF card_went_home THEN
        RAISE EXCEPTION
            'this card was released to a parent with %; a released card has to '
            'keep saying what it said and % is not allowed. Correcting a '
            'released rating is a revision, which makes a new version.',
            released_group, TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- And is the child's current class released? Still asked, because a school
    -- that had the section off at release froze no rows above for this to find,
    -- and turning the section back on afterwards makes rating reachable again.
    SELECT g.name, TRUE INTO released_group, class_is_released
    FROM results_resultsheet s
    JOIN academics_classplacement p
      ON p.class_group_id = s.class_group_id AND p.term_id = s.term_id
    JOIN academics_classgroup g
      ON g.id = s.class_group_id
    WHERE s.term_id = subject.term_id
      AND p.student_membership_id = subject.student_membership_id
      AND s.state = 'released'
    LIMIT 1;

    IF class_is_released THEN
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

# The reverse is `0007`'s body verbatim, so a rollback restores the guard as it
# stood rather than dropping it. A `DROP FUNCTION` here would leave `0007`'s
# trigger pointing at nothing and every rating failing.
#
# **Keep this in sync if `0007`'s `LIVE_FUNCTION` body ever changes.** It is a
# copy, and nothing checks the two still agree: an edit there would leave this
# rollback quietly restoring a version that never shipped. Applied migrations
# are not normally edited, so this should stay dead — but it is a copy, and
# copies going out of sync is what the `sheet_for()` finding was about.
PREVIOUS_LIVE_FUNCTION = """
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

    IF FOUND THEN
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


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0010_a_released_remark_outlives_a_class_move"),
    ]

    operations = [
        migrations.RunSQL(sql=LIVE_FUNCTION, reverse_sql=PREVIOUS_LIVE_FUNCTION),
    ]
