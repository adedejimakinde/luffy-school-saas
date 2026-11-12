"""A term absent from a session line can say "its results were not released".

Audit finding G-02. The year's summary is built from each term's released card
and nothing else, so a term the child was in a class for, whose results never
reached release, counts for nothing and has its own reason. A new choice on
three columns: no column changes, so nothing is written to the frozen table.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0039_a_step_records_the_papers_still_unmarked"),
    ]

    operations = [
        migrations.AlterField(
            model_name="releasedsessionresult",
            name="first_absence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("not_enrolled", "Not enrolled this term"),
                    ("unmarked", "Enrolled, but no marks were entered"),
                    (
                        "not_released",
                        "Enrolled, but the term's results were not released",
                    ),
                    ("no_term", "The school has no such term this session"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="releasedsessionresult",
            name="second_absence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("not_enrolled", "Not enrolled this term"),
                    ("unmarked", "Enrolled, but no marks were entered"),
                    (
                        "not_released",
                        "Enrolled, but the term's results were not released",
                    ),
                    ("no_term", "The school has no such term this session"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="releasedsessionresult",
            name="third_absence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("not_enrolled", "Not enrolled this term"),
                    ("unmarked", "Enrolled, but no marks were entered"),
                    (
                        "not_released",
                        "Enrolled, but the term's results were not released",
                    ),
                    ("no_term", "The school has no such term this session"),
                ],
                max_length=16,
            ),
        ),
    ]
