"""The result checker's two throttle scopes. `results.checker`, D11."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_a_guardian_holds_one_live_channel_of_each_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signinattempts",
            name="scope",
            field=models.CharField(
                choices=[
                    ("identifier", "Identifier"),
                    ("address", "Network address"),
                    ("channel", "Guardian contact channel"),
                    ("checker_number", "Result checker admission number"),
                    ("checker_address", "Result checker network address"),
                ],
                max_length=16,
            ),
        ),
    ]
