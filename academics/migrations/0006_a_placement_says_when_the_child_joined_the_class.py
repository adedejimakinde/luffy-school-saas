"""A placement says when the child joined the class. Audit finding G-13.

`class_since` is set when a child is placed and again when they are moved, and
by nothing else. A bill reads it to charge a child who moved class mid-term the
lines their new class added after they arrived (`fees.schedules`).

Existing rows take `updated_at`, the best record there is: a move saves the row
with `update_fields` that include it (`services.move_student()`), and nothing
else in the application writes a placement after it is made.
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0005_a_child_has_details_beyond_a_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="classplacement",
            name="class_since",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.RunSQL(
            sql="UPDATE academics_classplacement SET class_since = updated_at;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
