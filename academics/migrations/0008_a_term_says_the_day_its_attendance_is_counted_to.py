"""A term says the last day whose registers count on its report cards.

Audit finding G-10, as decided: registers are never locked, and the card's
attendance is counted to a cut-off the school sets (blank is the term's last
day) and frozen at release. A nullable column, so every existing term counts to
its last day, which is what every card released so far was counted to; and a
check that the day is one of the term's.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0007_a_leaver_is_written_down"),
    ]

    operations = [
        migrations.AddField(
            model_name="term",
            name="attendance_cutoff",
            field=models.DateField(
                blank=True,
                help_text="The last day whose registers count on the report card. Blank means the term's last day.",
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("attendance_cutoff__isnull", True),
                    models.Q(
                        ("attendance_cutoff__gte", models.F("starts_on")),
                        ("attendance_cutoff__lte", models.F("ends_on")),
                    ),
                    _connector="OR",
                ),
                name="the_attendance_cutoff_is_a_day_of_the_term",
                violation_error_message="The day the card's attendance is counted to has to be a day of the term, from its first day to its last.",
            ),
        ),
    ]
