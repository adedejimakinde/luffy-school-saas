"""A promotion decision may say "graduated".

Audit finding G-04. Graduating and leaving are the principal's decision like
promoting and repeating, and end-of-session promotion carries out only what was
decided. A new choice on two columns: no column changes, and no row is written.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0040_a_term_counts_only_through_its_released_card"),
    ]

    operations = [
        migrations.AlterField(
            model_name="promotiondecision",
            name="status",
            field=models.CharField(
                choices=[
                    ("promoted", "Promoted"),
                    ("on_trial", "Promoted on trial"),
                    ("repeated", "Repeating the class"),
                    ("graduated", "Graduated"),
                    ("withdrawn", "Withdrawn"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="promotiondecision",
            name="suggested",
            field=models.CharField(
                blank=True,
                choices=[
                    ("promoted", "Promoted"),
                    ("on_trial", "Promoted on trial"),
                    ("repeated", "Repeating the class"),
                    ("graduated", "Graduated"),
                    ("withdrawn", "Withdrawn"),
                ],
                max_length=16,
            ),
        ),
    ]
