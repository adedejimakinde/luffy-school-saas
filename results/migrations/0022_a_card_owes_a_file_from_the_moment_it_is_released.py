"""Every released card carries a row saying where its file has got to. Issue #56.

Task 7 gave `ReleasedCardPdf` one row per *rendered* card. The absence of a row
therefore meant two different things — "not released yet" and "released, and
nobody ever asked for the file" — and the second is the one that reaches a
parent, weeks later, as a report card that will not open. `PdfState` and this
migration make the second a positive fact somebody can query for.

Four operations, and the order between them is the whole of the risk.

## The old constraint has to go before the column arrives

`a_card_pdf_is_a_file_or_a_reason_and_not_both` says every row holds a file or a
reason. A `PENDING` row holds neither, so the constraint that refused it is
dropped first and the per-state one is added last — with the data put right in
between, while no constraint is watching. Adding the new one first would refuse
the very rows the backfill exists to write; adding it before the states are set
would refuse every row this table already holds, because `state` defaults to
`PENDING` and each of those rows has bytes or a reason.

## What the backfill does to rows that already exist

Every one of them was written by a job that ran, so each is `BUILT` or `FAILED`
already in everything but name: the dropped constraint permitted no third shape.
`content IS NOT NULL` is the test, and it is exact rather than nearly so.

`last_enqueued_at` is left null for them, which is true — nothing recorded when
those renders were asked for, and inventing `built_at` as the answer would put a
made-up time into the column the download route debounces on.

## And to the cards that have no row at all

They get one, `PENDING`, one `INSERT … SELECT` per schema. django-tenants runs
this migration in each school's schema with the search path set, so the
unqualified names below are that school's tables and the join never crosses a
tenant.

This is the half that turns old data into data the platform can act on: a card
released last term with no file becomes a `PENDING` row, and the download route
enqueues a render the first time somebody asks for it. Without it, every card
released before today would need a second branch in that route — "no row" — for
ever, and the invariant `ReleasedCardPdf` now states in its own docstring
(*every released card has a row*) would be false on every real database on the
platform while being true on every test one.

`built_at` on a backfilled row is when the marker was written, not when a file
was made, because there is no file. The column is `auto_now` and NOT NULL, so it
has to say something; `PdfState.PENDING` beside it is what stops it being read
as a claim that a render happened.

## Reversing this deletes the markers, and it must

Run backwards, this migration re-adds the old constraint — and a `PENDING` row
would violate it, so the reverse deletes those rows before the column that
identifies them is dropped. Operations reverse in reverse order, which puts the
delete after the new constraint comes off and before the old one goes back on.
The rows deleted are exactly the ones that carry no file and no reason: nothing
a school would miss, and nothing that cannot be written again by rolling
forward.
"""

from django.db import migrations, models


def name_the_state_of_every_row(apps, schema_editor):
    """`BUILT` where there are bytes, `FAILED` where there is a reason, then the markers."""
    ReleasedCardPdf = apps.get_model("results", "ReleasedCardPdf")

    ReleasedCardPdf.objects.filter(content__isnull=False).update(state="built")
    ReleasedCardPdf.objects.filter(content__isnull=True).update(state="failed")

    # `INSERT … SELECT` rather than reading every card into Python: a school
    # with several years of releases has tens of thousands of them, and the
    # rows being written carry nothing that has to be computed. `NOT EXISTS`
    # over `NOT IN` because the subquery stops at the first match per card.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO results_releasedcardpdf
                (card_id, content, byte_size, error, state,
                 last_enqueued_at, built_at)
            SELECT c.id, NULL, NULL, '', 'pending', NULL, now()
              FROM results_releasedcard AS c
             WHERE NOT EXISTS (
                   SELECT 1 FROM results_releasedcardpdf AS p
                    WHERE p.card_id = c.id
             )
            """
        )


def drop_the_markers(apps, schema_editor):
    """See the module docstring: the old constraint refuses what `PENDING` is."""
    ReleasedCardPdf = apps.get_model("results", "ReleasedCardPdf")
    ReleasedCardPdf.objects.filter(state="pending").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0021_the_rendered_card"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="releasedcardpdf",
            name="a_card_pdf_is_a_file_or_a_reason_and_not_both",
        ),
        migrations.AddField(
            model_name="releasedcardpdf",
            name="last_enqueued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="releasedcardpdf",
            name="state",
            field=models.CharField(
                choices=[
                    ("pending", "Not built yet"),
                    ("built", "Built"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.RunPython(name_the_state_of_every_row, drop_the_markers),
        migrations.AddConstraint(
            model_name="releasedcardpdf",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("content__isnull", True), ("error", ""), ("state", "pending")
                    ),
                    models.Q(
                        ("content__isnull", False), ("error", ""), ("state", "built")
                    ),
                    models.Q(
                        ("content__isnull", True),
                        ("state", "failed"),
                        models.Q(("error", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="a_card_pdf_is_pending_a_file_or_a_reason",
            ),
        ),
    ]
