"""The freeze is about `(term, student, author)`, not about where the child sits.

`0009` asked "has this remark's term been released **for this child's class**?"
and answered it by joining through `academics_classplacement`. That join reads
the placement the child has *now*, which is a different question from the one
the guarantee is about, and the two answers part company the moment the office
moves anybody.

## The case

Release JSS 1A. Ada's class teacher's remark is frozen and her card goes home.
The office then moves Ada to JSS 3B — a legitimate thing that happens mid-term,
and `academics.move_student()` exists to do it. JSS 3B's sheet is a draft that
nobody has opened.

Asked through the placement, the guard now looks at JSS 3B, finds a draft, and
permits the write. JSS 3B's class teacher rewrites the remark. The frozen card
in the parent's hand says one thing, the school's screen says another, and
nothing anywhere records that they disagree — which is, word for word, what
`0009`'s own docstring says it exists to prevent. It prevented it for a child
who stayed put.

## The fix

Ask the question the guarantee is actually about. A remark that has been frozen
has been released, wherever the child sits today, so the check reads
`results_releasedcomment` for this `(term, student, author)` and refuses if a
row is there. Placement does not enter into it.

**Additive, not a replacement.** The placement join stays, because it answers
something the frozen rows cannot: a class released while a child's card carries
no remark at all freezes nothing for that child, and a school must still not be
able to write one onto that released sheet. Between them the two cover "this
class's term is released" and "a card for this child has already gone home".

**Keyed on the child and the term, not on the author.** The first check asked
`rc.author = subject.author` in an earlier draft of this migration, which was
the same mistake one level down: a card released carrying only the class
teacher's remark freezes no principal's row, so the principal's write found
nothing frozen, and after a move found JSS 3B's draft in the second check — and
landed a remark on a card already in a parent's hand. Measured, in both the
trigger and `comments.py`, before it was changed. The child who stayed in JSS 1A
was refused that same write by the second check, so the two answers disagreed
about where the child was sitting rather than about what had happened.

**One case neither check sees**, written down because an earlier draft claimed
there was none: a child whose card went home carrying no remark of either kind,
who is then moved. Nothing is frozen for them, so the first check finds nothing,
and the second is looking at the new class. Closing it needs a per-child record
that a card was released — which is what the frozen rows already are for every
other child, and which task 3's card work would add.

## The shape, not just this instance

`results/0007` carries the byte-identical join for `TraitRating`, so a released
*rating* has the same hole; `ratings._require_the_sheet_is_open()` and
`comments._require_the_sheet_is_open()` both ask through
`placement.class_group`. That is not fixed here — it is merged task 4 code with
its own tests to write, and folding it in would make this branch's review span
two features. It is
[issue #33](https://github.com/adedejimakinde/luffy-school-saas/issues/33).

Note the fix there is probably *not* a copy of the two checks below. Ratings
freeze a row even for a trait nobody rated — what they freeze is the section —
so the gap the second check covers here does not exist there, and a second check
would put the placement join back into a guard whose point is to be rid of it.

What is worth carrying forward is the rule, because the next write guard will
have to answer the same question:

> **A guard on a released artefact keys off the artefact, not off the child's
> current placement.** Placement answers "whose class is this child in today",
> which is a live fact that changes. Release is an event that happened, and what
> records it is the frozen row.

[Issue #27](https://github.com/adedejimakinde/luffy-school-saas/issues/27)'s
write guard on live marks runs into the same question and should be built on
that sentence rather than on a third copy of the placement join.
"""

from django.db import migrations

# `CREATE OR REPLACE` rather than a drop and a recreate: the trigger declared in
# `0009` goes on pointing at this name, so replacing the body is the whole
# change and there is no window in which the table is unguarded.
#
# Two `SELECT ... INTO` blocks, each with its own check immediately after it,
# and **neither check uses `FOUND`**. Two separate reasons, and the second is
# why the obvious alternative is also wrong:
#
# `FOUND` is global to the block and reset by the *most recent* query of several
# kinds — including `PERFORM`, which does not look like a query that would touch
# it. Proven rather than assumed: a `SELECT` matching nothing followed by
# `PERFORM 1` leaves `FOUND` **true**. Today each `IF FOUND` sits immediately
# after its own `SELECT` so nothing intervenes, but that is an adjacency a
# comment asks for and nothing enforces — one statement inserted between them
# silently inverts the guard.
#
# The obvious fix, testing the selected column for NULL, reintroduces exactly
# what `0007` was corrected on and `0009` documents: `SELECT g.name INTO
# released_group` leaves the variable NULL both when no row matched *and* when a
# row matched whose name is NULL, so the refusal becomes a permit the day
# `academics_classgroup.name` becomes nullable. Measured too: with a matching
# row whose name is NULL, `released_group IS NOT NULL` is **false**.
#
# So each block selects a literal `TRUE` into its own boolean. A literal cannot
# be NULL when a row matched, which is what the nullable column could not
# promise; and a named variable cannot be reset by an intervening statement,
# which is what `FOUND` could not promise. `SELECT INTO` with no matching row
# nulls every target, and `IF <null>` does not fire, so the absent case is right
# without a default.
LIVE_FUNCTION = """
CREATE OR REPLACE FUNCTION results_comments_stop_at_release() RETURNS trigger AS $$
DECLARE
    subject results_reportcardcomment%ROWTYPE;
    released_group text;
    remark_went_home boolean;
    class_is_released boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subject := OLD;
    ELSE
        subject := NEW;
    END IF;

    -- Has a card for this child already been frozen and sent home? Answered
    -- without reference to where the child is placed now, which is the point,
    -- and without reference to the author: a card released carrying only the
    -- class teacher's remark freezes no principal's row, so keying this on
    -- `rc.author` let the principal write onto it after a move.
    SELECT g.name, TRUE INTO released_group, remark_went_home
    FROM results_releasedcomment rc
    JOIN results_resultsheet s
      ON s.id = rc.sheet_id
    JOIN academics_classgroup g
      ON g.id = s.class_group_id
    WHERE s.term_id = subject.term_id
      AND rc.student_membership_id = subject.student_membership_id
    LIMIT 1;

    IF remark_went_home THEN
        RAISE EXCEPTION
            'this card was released to a parent with %; a released card has '
            'to keep saying what it said and % is not allowed. Correcting a '
            'released remark is a revision, which makes a new version.',
            released_group, TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- And is the child's current class released? Still asked, because a card
    -- released without this remark freezes no row above for it to find.
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
            'this term has been released for %; its remarks are part of a card '
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

# The reverse is `0009`'s body verbatim, so a rollback restores the guard as it
# stood rather than dropping it. A `DROP FUNCTION` here would leave `0009`'s
# trigger pointing at nothing and every write failing.
#
# **Keep this in sync if `0009`'s `LIVE_FUNCTION` body ever changes.** It is a
# copy, and nothing checks the two still agree: an edit there would leave this
# rollback quietly restoring a version that never shipped. Applied migrations
# are not normally edited, so this should stay dead — but it is a copy, and
# copies are what the `sheet_for()` finding in this same branch was about.
PREVIOUS_LIVE_FUNCTION = """
CREATE OR REPLACE FUNCTION results_comments_stop_at_release() RETURNS trigger AS $$
DECLARE
    subject results_reportcardcomment%ROWTYPE;
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
            'this term has been released for %; its remarks are part of a card '
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
        ("results", "0009_a_released_remark_stays_released"),
    ]

    operations = [
        migrations.RunSQL(sql=LIVE_FUNCTION, reverse_sql=PREVIOUS_LIVE_FUNCTION),
    ]
