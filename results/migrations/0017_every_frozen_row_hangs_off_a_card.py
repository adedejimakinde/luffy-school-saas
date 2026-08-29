"""Backfill the card each frozen section belongs to, then require it.

`0016` added `card` nullable to `results_releasedtraitrating`,
`results_releasedcomment` and `results_releasedsessionresult`. This fills it in
and makes it NOT NULL, so that from here there is exactly **one** answer to
"did a card go home for this child?" rather than four.

## The backfill invents cards, and that is correct

Every one of those tables already keys on `(sheet, student_membership_id)` —
the same pair `ReleasedCard` is unique on — so the mapping is direct. Where no
card exists for a pair that has a frozen row, one is created: a frozen rating
*is* the record that a card went home for that child, so the card row is not
fabricated, it is the fact written down in the place it now belongs.

Those backfilled cards carry the sections and nothing else. Their marks,
totals, averages and positions are left at their defaults and their
`own_average` is null, because the marks that produced them were never frozen —
task 3 is the first release that freezes marks at all, and reconstructing a
past card from today's live scores would be exactly the thing this whole
snapshot exists to prevent. A backfilled card asserts one thing only, which is
the thing it is for: **this child's card went home on this release.**

`student_name`, `school_name` and `class_group_name` are filled from the rows
as they read *now*. That is not a copy at release — the release has already
happened and the moment is gone — and it is the honest best available. Nothing
downstream may treat a backfilled card's name as evidence of what was printed.

## It has to switch the append-only guards off to do it

`results_releasedtraitrating`, `results_releasedcomment` and
`results_releasedsessionresult` each carry a `BEFORE UPDATE OR DELETE` trigger
whose entire body is `RAISE EXCEPTION` — `0007`, `0009` and `0013`. Filling in
`card_id` on rows that pre-date the column is an UPDATE, so without suspending
them this migration cannot run at all on any database that has ever released a
card. It fails at the first `bulk_update` with `restrict_violation`.

**An empty database hides this completely**, which is why it is worth spelling
out here: with no released rows there are no pairs to link, the backfill returns
before it writes anything, and every test suite and every fresh install migrates
cleanly. The only databases it breaks are the ones with results in them.

The suspension is narrow and it is honest: this migration writes `card_id` and
nothing else, so no card changes what it says. See `_suspend_append_only()` for
why the drop is safe in a way it does not look.

## Reversing

`0016` will drop the column, so this leaves the invented cards behind rather
than deleting them: a `ReleasedCard` is append-only from `0018` onwards, and a
reverse migration that deletes released artefacts would be the one thing this
table exists to refuse. Reversing is therefore not symmetric, deliberately.
"""

from django.db import migrations, models
import django.db.models.deletion

#: The three frozen tables this migration fills in, each with the append-only
#: trigger that guards it and the function that trigger calls.
#:
#: `0007`, `0009` and `0013` each put a `BEFORE UPDATE OR DELETE` trigger on one
#: of these tables whose whole body is `RAISE EXCEPTION` — a released card keeps
#: saying what it said, and the database refuses any UPDATE rather than trusting
#: the application not to try one. **This migration is the one legitimate
#: exception**, and it is legitimate because it changes nothing a card says: it
#: writes `card_id`, a column that did not exist until `0016`, onto rows that
#: pre-date it. Every other column is left exactly as released.
#:
#: The functions are left alone and only the triggers are dropped and recreated,
#: so the definitions here stay in step with `0007`, `0009` and `0013` without
#: copying their bodies.
APPEND_ONLY_GUARDS = (
    (
        "results_releasedtraitrating",
        "results_frozen_ratings_append_only",
        "results_frozen_ratings_are_append_only",
    ),
    (
        "results_releasedcomment",
        "results_frozen_comments_append_only",
        "results_frozen_comments_are_append_only",
    ),
    (
        "results_releasedsessionresult",
        "results_frozen_sessions_append_only",
        "results_frozen_sessions_are_append_only",
    ),
)


def _suspend_append_only(cursor):
    """Drop the three frozen-table triggers. Only ever with `_restore` after it.

    Safe despite how it reads, and the reason is Postgres-specific: DDL is
    transactional, and a Django migration runs inside one transaction. No other
    session ever observes a moment when these triggers are missing — the drop
    and the recreate commit together with the UPDATE between them, or none of
    them do. Doing this as two sibling `RunSQL` operations around the
    `RunPython` would be the same transaction and read more conventionally, but
    it would let a later edit reorder the three; keeping them in one function
    means the window cannot be widened by accident.
    """
    for table, trigger, _ in APPEND_ONLY_GUARDS:
        cursor.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table};")


def _restore_append_only(cursor):
    """Put them back, pointing at the functions `0007`, `0009` and `0013` wrote."""
    for table, trigger, function in APPEND_ONLY_GUARDS:
        cursor.execute(
            f"CREATE TRIGGER {trigger} "
            f"BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}();"
        )


def backfill(apps, schema_editor):
    """One card per (sheet, student) that has any frozen section, then link them.

    Ordered so the reads are cheap and the writes are two `bulk_create`-shaped
    passes rather than a query per row: a school with three years of releases
    behind it has hundreds of thousands of frozen ratings.

    The linking pass runs with the three append-only triggers suspended, because
    they refuse UPDATE unconditionally and linking is an UPDATE. The module
    docstring has the argument for why that is allowed here.
    """
    ReleasedCard = apps.get_model("results", "ReleasedCard")
    ReleasedTraitRating = apps.get_model("results", "ReleasedTraitRating")
    ReleasedComment = apps.get_model("results", "ReleasedComment")
    ReleasedSessionResult = apps.get_model("results", "ReleasedSessionResult")
    ResultSheet = apps.get_model("results", "ResultSheet")
    Membership = apps.get_model("accounts", "Membership")
    School = apps.get_model("schools", "School")

    tables = (ReleasedTraitRating, ReleasedComment, ReleasedSessionResult)

    pairs = set()
    for table in tables:
        pairs.update(
            table.objects.values_list("sheet_id", "student_membership_id").distinct()
        )
    if not pairs:
        return

    known = {
        (card.sheet_id, card.student_membership_id): card
        for card in ReleasedCard.objects.filter(version=1)
    }

    sheets = {
        sheet.pk: sheet
        for sheet in ResultSheet.objects.filter(
            pk__in={sheet_id for sheet_id, _ in pairs}
        ).select_related("term", "class_group")
    }
    names = {
        row["pk"]: row["user__full_name"] or ""
        for row in Membership.objects.filter(
            pk__in={student_id for _, student_id in pairs}
        ).values("pk", "user__full_name")
    }

    # The school this schema belongs to, read once. `cards._school_name()` does
    # the same lookup at release; it is not imported here because a data
    # migration that calls application code starts failing the day that code
    # moves, and the whole point of `apps.get_model` is to be immune to that.
    #
    # Defensive about finding nothing rather than raising. A schema with no
    # `School` row is not a state this migration can fix, and refusing to
    # migrate over it would block the deploy on a row that has nothing to do
    # with report cards. An empty name is what `0016` would have left anyway.
    school = School.objects.filter(
        schema_name=schema_editor.connection.schema_name
    ).first()
    school_name = school.name if school else ""

    missing = []
    for sheet_id, student_id in sorted(pairs):
        if (sheet_id, student_id) in known:
            continue
        sheet = sheets.get(sheet_id)
        if sheet is None:
            # A frozen row whose sheet has gone is a broken row, and a data
            # migration is not the place to decide what to do about it. Leaving
            # `card` null means the `AlterField` below fails loudly with the
            # count, which is the right outcome: somebody has to look.
            continue
        missing.append(
            ReleasedCard(
                sheet_id=sheet_id,
                student_membership_id=student_id,
                term_id=sheet.term_id,
                version=1,
                session=sheet.term.session,
                term_name=sheet.term.name,
                class_group_id=sheet.class_group_id,
                # `.name`, not `str(...)`. `cards._card_for()` uses `str()`
                # and is right to: on the live model `ClassGroup.__str__`
                # returns the name. The model here is not that model — a
                # migration's models are rebuilt from migration state and carry
                # fields, not methods — so `str()` here is
                # `Model.__str__`, and every backfilled card in the country
                # would have gone home saying `ClassGroup object (3)`.
                class_group_name=sheet.class_group.name,
                school_name=school_name,
                student_name=names.get(student_id, ""),
            )
        )

    if missing:
        ReleasedCard.objects.bulk_create(missing, batch_size=500)

    known = {
        (card.sheet_id, card.student_membership_id): card.pk
        for card in ReleasedCard.objects.filter(version=1)
    }

    # Linking a frozen row to its card is an UPDATE, and all three of these
    # tables refuse UPDATE outright — see `APPEND_ONLY_GUARDS`. Suspend the
    # triggers for the width of these writes and put them straight back.
    #
    # Deliberately not wrapped in `try`/`finally`. The whole migration is one
    # transaction, so a failure here rolls the `DROP TRIGGER` back with
    # everything else and the guards are never really gone; a `finally` would
    # only issue more SQL on an already-aborted transaction and replace the real
    # error with "current transaction is aborted", which is the error that
    # explains nothing.
    with schema_editor.connection.cursor() as cursor:
        _suspend_append_only(cursor)

        for table in tables:
            rows = []
            for row in table.objects.filter(card__isnull=True).only(
                "id", "sheet_id", "student_membership_id"
            ):
                card_pk = known.get((row.sheet_id, row.student_membership_id))
                if card_pk is None:
                    continue
                row.card_id = card_pk
                rows.append(row)
            if rows:
                table.objects.bulk_update(rows, ["card_id"], batch_size=500)

        _restore_append_only(cursor)


def leave_the_cards(apps, schema_editor):
    """Reversing drops the column; the cards stay. See the module docstring."""


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0016_the_report_card_snapshot"),
        ("accounts", "0001_initial"),
        ("schools", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill, leave_the_cards),
        migrations.AlterField(
            model_name="releasedtraitrating",
            name="card",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="trait_ratings",
                to="results.releasedcard",
            ),
        ),
        migrations.AlterField(
            model_name="releasedcomment",
            name="card",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="comments",
                to="results.releasedcard",
            ),
        ),
        migrations.AlterField(
            model_name="releasedsessionresult",
            name="card",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="session_results",
                to="results.releasedcard",
            ),
        ),
    ]
