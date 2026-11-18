"""An admission number names one child per school. Audit finding G-14.

Three steps, in this order, and the order is the point:

1. **Look for numbers already shared, and stop with all of them listed.**
   Adding the index over duplicates fails anyway, but Postgres names only the
   first pair it meets (`Key (school_id, lower(reference))=(3, jss/014) is
   duplicated`), so an operator would fix one, migrate, and meet the next. This
   names every school, every number and every child holding it, and says how to
   fix them. `python manage.py admission_number_clashes` prints the same list
   without migrating. Nothing is changed when it stops: no number is rewritten
   or blanked to make the index fit, because which child keeps a number is the
   school's decision, not a migration's.
2. **Trim surrounding spaces** from student numbers, and say how many. The
   index compares `lower(reference)`, and the services store numbers trimmed,
   so a stored "JSS/014 " would otherwise sit beside "JSS/014". Step 1 already
   compared trimmed numbers, so this cannot create a clash.
3. **Add the index.**

`accounts.admission_numbers` holds the rule and the query; this calls it with
the migration's own cursor.
"""

import django.db.models.functions.text
from django.db import migrations, models


def stop_on_shared_numbers(apps, schema_editor):
    from accounts import admission_numbers

    with schema_editor.connection.cursor() as cursor:
        found = admission_numbers.clashes(cursor)
        if found:
            raise RuntimeError(admission_numbers.clash_report(found))
        spaced = admission_numbers.surrounding_spaces(cursor)
        if spaced:
            cursor.execute(
                "UPDATE accounts_membership SET reference = btrim(reference) "
                "WHERE role = 'student' AND reference <> btrim(reference)"
            )
            print(f"\n  Trimmed surrounding spaces from {spaced} admission number(s).")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0020_password_reset"),
        ("schools", "0013_school_short_name"),
    ]

    operations = [
        migrations.RunPython(stop_on_shared_numbers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="membership",
            constraint=models.UniqueConstraint(
                models.F("school"),
                django.db.models.functions.text.Lower("reference"),
                condition=models.Q(("role", "student"), models.Q(("reference", ""), _negated=True)),
                name="an_admission_number_names_one_child_per_school",
            ),
        ),
    ]
