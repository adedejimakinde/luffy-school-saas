"""A submit, a check and an approve write down how many papers were unmarked.

Audit finding F-05. Null on rows written before this, and on a send-back and a
release, which count nothing. The table stays append-only: the number is
written on the INSERT and `0002`'s trigger refuses any change to it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0038_a_broadsheet_is_a_kind_of_print"),
    ]

    operations = [
        migrations.AddField(
            model_name="resultsheettransition",
            name="unmarked_papers",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
