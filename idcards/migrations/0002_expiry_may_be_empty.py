from django.db import migrations, models


class Migration(migrations.Migration):
    """A card printed while its session has no third term has no date yet: it says its session."""

    dependencies = [("idcards", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="idcard",
            name="expires_on",
            field=models.DateField(blank=True, null=True),
        ),
    ]
