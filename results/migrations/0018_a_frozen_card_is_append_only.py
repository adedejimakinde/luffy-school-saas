"""The three snapshot tables refuse UPDATE and DELETE, in the database.

`0016` created them; this is the half that makes them mean anything. A frozen
card that can be edited is not frozen, and `save()`/`delete()` on the model
catch only the developer — the import, the `psql` session and the bulk
`.update()` never go near a model method, and every one of those is a real way a
school's data gets edited in anger.

Same pattern as `0007` (ratings), `0009` (remarks) and `0013` (session lines and
promotion decisions). Three functions rather than one shared with a generic
message, because the refusal a person reads should name the thing they tried to
change.

## On UPDATE and DELETE, never on INSERT

`0013` states the rule and it holds here for the same reason: these tables are
written exactly once, by the code that owns them, inside the release
transaction. Refusing INSERT would refuse the write that creates the row.

Note the contrast with `results_ratings_stop_at_release`, which *does* guard
INSERT — that one protects a **live** table where a late insert is the hazard.
These are artefacts, not working tables.

## Correcting a released card

Not by editing one. Task 8 makes a new version: `ReleasedCard.version` is
already on the row for exactly that, and both versions stand. The refusal
messages say so, because "you cannot change this" without "here is what you do
instead" is the kind of error that gets worked around with a `psql` session.
"""

from django.db import migrations

CARD_FUNCTION = """
CREATE OR REPLACE FUNCTION results_frozen_cards_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_releasedcard is append-only; % is not allowed. A released card '
        'has to keep saying what it said — correct it with a revision, which '
        'makes a new version and leaves this one standing.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

CARD_TRIGGER = """
CREATE TRIGGER results_cards_are_append_only
BEFORE UPDATE OR DELETE ON results_releasedcard
FOR EACH ROW EXECUTE FUNCTION results_frozen_cards_are_append_only();
"""

SUBJECT_FUNCTION = """
CREATE OR REPLACE FUNCTION results_frozen_subject_lines_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_releasedsubjectresult is append-only; % is not allowed. This is '
        'a line on a card that has gone home — correct it with a revision, which '
        'makes a new version of the whole card.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

SUBJECT_TRIGGER = """
CREATE TRIGGER results_subject_lines_are_append_only
BEFORE UPDATE OR DELETE ON results_releasedsubjectresult
FOR EACH ROW EXECUTE FUNCTION results_frozen_subject_lines_are_append_only();
"""

SCORE_FUNCTION = """
CREATE OR REPLACE FUNCTION results_frozen_score_cells_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_releasedassessmentscore is append-only; % is not allowed. This '
        'is a mark printed on a card that has gone home — correct it with a '
        'revision, which makes a new version of the whole card.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

SCORE_TRIGGER = """
CREATE TRIGGER results_score_cells_are_append_only
BEFORE UPDATE OR DELETE ON results_releasedassessmentscore
FOR EACH ROW EXECUTE FUNCTION results_frozen_score_cells_are_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS results_cards_are_append_only ON results_releasedcard;
DROP TRIGGER IF EXISTS results_subject_lines_are_append_only ON results_releasedsubjectresult;
DROP TRIGGER IF EXISTS results_score_cells_are_append_only ON results_releasedassessmentscore;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0017_every_frozen_row_hangs_off_a_card"),
    ]

    operations = [
        migrations.RunSQL(sql=CARD_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=CARD_TRIGGER, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=SUBJECT_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=SUBJECT_TRIGGER, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=SCORE_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=SCORE_TRIGGER, reverse_sql=DROP),
    ]
