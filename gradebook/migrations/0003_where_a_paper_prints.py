"""`Assessment.position`, and creation order written into it. Issue #42.

## Why the backfill preserves the existing order instead of improving it

Every card released so far froze its column order at release, copying each
paper's name and place onto `ReleasedAssessmentScore`. That order came from
`cards._assessments_for()`, which sorts by `(subject name, id)` — creation
order. **A frozen order cannot be corrected on cards already issued.**

So any backfill that reshuffles makes newly released cards disagree with cards
already in parents' hands, for the same term and the same child. Numbering by
creation order is the only choice that cannot do that: it writes down what the
order already was, rather than deciding what it should have been.

A name heuristic — "First CA" first, "Exam" last — was considered and rejected
for this reason. It is right only for names that match the pattern it knows, and
silently reorders everything else: "Test 1", "CA1", "Mid-Term", a label in a
language it does not read. That is not a hypothetical class of data; it is the
ordinary contents of the column. Getting a school's existing papers "more right"
at the cost of disagreeing with cards already sent home is a bad trade, and it
is one nobody could undo.

Schools set the order they actually want by editing `position` from here on.
That is a decision they can make and remake; this migration's job is only to
stop the old order being lost in the move.

## In tens

Ten, twenty, thirty — so a paper can be inserted between two others without
renumbering the rest. `position` is not unique (see the field's docstring), so
a collision is legal and `Meta.ordering` still breaks the tie deterministically.
"""

from django.db import migrations, models


def number_papers_by_creation_order(apps, schema_editor):
    """Number each `(term, subject)`'s papers 10, 20, 30… by `id`.

    Grouped by `(term, subject)` because that is the set a card's columns are
    drawn from — `cards._assessments_for()` filters by term and a subject list,
    so numbering across the whole table would be a different ordering wearing
    the same name.
    """
    Assessment = apps.get_model("gradebook", "Assessment")

    counters = {}
    papers = []
    for paper in Assessment.objects.order_by("term_id", "subject_id", "id"):
        key = (paper.term_id, paper.subject_id)
        counters[key] = counters.get(key, 0) + 10
        paper.position = counters[key]
        papers.append(paper)

    if papers:
        Assessment.objects.bulk_update(papers, ["position"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("gradebook", "0002_a_released_mark_stays_released"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessment",
            name="position",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(
            number_papers_by_creation_order,
            # Reversing drops the column immediately afterwards, so there is
            # nothing for a reverse function to put back.
            migrations.RunPython.noop,
        ),
        migrations.AlterModelOptions(
            name="assessment",
            options={"ordering": ["term", "subject__name", "position", "name", "id"]},
        ),
    ]
