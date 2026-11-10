from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schools", "0012_each_school_has_a_storage_quota"),
    ]

    operations = [
        migrations.AddField(
            model_name="school",
            name="short_name",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
    ]
