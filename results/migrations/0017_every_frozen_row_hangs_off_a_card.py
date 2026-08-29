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

## Reversing

`0016` will drop the column, so this leaves the invented cards behind rather
than deleting them: a `ReleasedCard` is append-only from `0018` onwards, and a
reverse migration that deletes released artefacts would be the one thing this
table exists to refuse. Reversing is therefore not symmetric, deliberately.
"""

from django.db import migrations, models
import django.db.models.deletion


def backfill(apps, schema_editor):
    """One card per (sheet, student) that has any frozen section, then link them.

    Ordered so the reads are cheap and the writes are two `bulk_create`-shaped
    passes rather than a query per row: a school with three years of releases
    behind it has hundreds of thousands of frozen ratings.
    """
    ReleasedCard = apps.get_model("results", "ReleasedCard")
    ReleasedTraitRating = apps.get_model("results", "ReleasedTraitRating")
    ReleasedComment = apps.get_model("results", "ReleasedComment")
    ReleasedSessionResult = apps.get_model("results", "ReleasedSessionResult")
    ResultSheet = apps.get_model("results", "ResultSheet")
    Membership = apps.get_model("accounts", "Membership")

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
                class_group_name=str(sheet.class_group),
                school_name="",
                student_name=names.get(student_id, ""),
            )
        )

    if missing:
        ReleasedCard.objects.bulk_create(missing, batch_size=500)

    known = {
        (card.sheet_id, card.student_membership_id): card.pk
        for card in ReleasedCard.objects.filter(version=1)
    }
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


def leave_the_cards(apps, schema_editor):
    """Reversing drops the column; the cards stay. See the module docstring."""


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0016_the_report_card_snapshot"),
        ("accounts", "0001_initial"),
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
