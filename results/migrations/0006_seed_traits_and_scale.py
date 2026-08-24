"""Give every school a trait list and a scale to start from — and both sections off.

Runs **per schema**, because `results` is a tenant app: `migrate_schemas` walks
every school and runs this inside each one, and a school created next year gets
it as part of `CREATE SCHEMA`. That is what makes a seed the right mechanism
here rather than a management command somebody has to remember to run.

## A seed is a starting point, not a promise

Every row written here is editable, hideable and reorderable by the school, and
**nothing in the code names any of them**. There is no `Trait.PUNCTUALITY`
anywhere, no lookup by name, and no test that asserts a particular seeded trait
exists by name in a school's schema. That is deliberate: the moment a code path
depends on a seeded row, hiding it — the very thing the feature promises a
school it may do — breaks something.

The list is the one most Nigerian secondary schools print. Schools differ, which
is exactly why it is rows.

## The settings row is seeded off

`affective_enabled` and `psychomotor_enabled` both default to `False`, and the
row is created so that turning a section on is an `UPDATE` a school makes rather
than an `INSERT` it discovers. A school that never touches this has eleven trait
rows and five scale rows in its schema and prints nothing at all — the traits
cost a few hundred bytes and buy a school that later says yes a list already
there to edit.

## Idempotent

`get_or_create` on the natural key, not `bulk_create`. Re-running a migration is
not supposed to happen, but a schema built by `migrate_schemas --tenant` after a
partial failure is a real thing, and a seed that doubles the trait list on a
second pass is a bad way to find out.
"""

from django.db import migrations

#: (group, name, position). Position is explicit and starts at zero, and the
#: order below is the order a card prints — not alphabetical, which would lead
#: the affective section with "Attendance" and the psychomotor one with
#: "Drawing/Craft" for no reason anybody could explain to a school.
AFFECTIVE = [
    "Punctuality",
    "Attendance",
    "Neatness",
    "Politeness",
    "Honesty",
    "Attentiveness in class",
    "Relationship with others",
]

PSYCHOMOTOR = [
    "Handwriting",
    "Games/Sports",
    "Drawing/Craft",
    "Handling of tools and equipment",
]

#: 5 down to 1, the way the key at the foot of a report card reads.
SCALE = [
    (5, "Excellent"),
    (4, "Very Good"),
    (3, "Good"),
    (2, "Fair"),
    (1, "Poor"),
]


def seed(apps, schema_editor):
    Trait = apps.get_model("results", "Trait")
    RatingScalePoint = apps.get_model("results", "RatingScalePoint")
    ReportCardSettings = apps.get_model("results", "ReportCardSettings")

    for group, names in (("affective", AFFECTIVE), ("psychomotor", PSYCHOMOTOR)):
        for position, name in enumerate(names):
            Trait.objects.get_or_create(
                group=group, name=name, defaults={"position": position}
            )

    for value, label in SCALE:
        RatingScalePoint.objects.get_or_create(value=value, defaults={"label": label})

    # Both sections off. The whole point of the default.
    ReportCardSettings.objects.get_or_create(pk=1)


def unseed(apps, schema_editor):
    """Take back only what was never used.

    A trait that has been rated is protected by its ratings and by any released
    card that printed it, so this cannot pull the rug out from under real data —
    it would raise. Rather than let a reverse migration fail halfway through,
    it deletes only the rows nothing points at, and leaves the rest.
    """
    Trait = apps.get_model("results", "Trait")
    RatingScalePoint = apps.get_model("results", "RatingScalePoint")
    ReportCardSettings = apps.get_model("results", "ReportCardSettings")

    Trait.objects.filter(
        name__in=AFFECTIVE + PSYCHOMOTOR, ratings__isnull=True, released_ratings__isnull=True
    ).delete()
    RatingScalePoint.objects.filter(value__in=[value for value, _ in SCALE]).delete()
    ReportCardSettings.objects.filter(
        pk=1, affective_enabled=False, psychomotor_enabled=False
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0005_conduct_and_skills_ratings"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
