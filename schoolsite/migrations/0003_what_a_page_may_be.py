# PR 3b: the rules about pages and sections, in Postgres, so no path can break
# them however it writes (`docs/operating-rules.md` rule 3):
#
# - a page is one of the six fixed pages (a key, no address, no slot) or one the
#   school made (an address under /pages/, no key, a slot from 1 to 14), so a
#   school has at most 20 pages;
# - each fixed page once, each address once, each slot once;
# - one page per place in the menu, Home first and always on;
# - at most 15 sections on a page, one per place.
#
# The two "one per place" rules are deferred to the end of the transaction, so
# a reorder can pass through a moment where two share a place.

import django.db.models.constraints
from django.db import migrations, models

FIXED = ["home", "about", "admissions", "news", "gallery", "contact"]


class Migration(migrations.Migration):

    dependencies = [("schoolsite", "0002_a_page_of_the_schools_own")]

    operations = [
        migrations.AddConstraint(
            model_name="page",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("key__in", FIXED), ("kind", "fixed"), ("slot__isnull", True), ("slug", "")),
                    models.Q(
                        ("key", ""), ("kind", "custom"), ("slot__gte", 1), ("slot__isnull", False), ("slot__lte", 14),
                        ("slug__regex", "^[a-z0-9]+(-[a-z0-9]+)*$"),
                        models.Q(("slug__in", FIXED), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="a_page_is_fixed_or_the_schools_own",
            ),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.UniqueConstraint(
                condition=models.Q(kind="fixed"), fields=("key",), name="a_fixed_page_appears_once"
            ),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.UniqueConstraint(
                condition=models.Q(kind="custom"), fields=("slug",), name="a_custom_page_has_its_own_address"
            ),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.UniqueConstraint(fields=("slot",), name="a_custom_page_takes_its_own_slot"),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.UniqueConstraint(
                deferrable=django.db.models.constraints.Deferrable["DEFERRED"],
                fields=("menu_position",),
                name="a_menu_place_holds_one_page",
            ),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.CheckConstraint(
                condition=models.Q(models.Q(("key", "home"), _negated=True), ("menu_position", 0), _connector="OR"),
                name="the_home_page_comes_first_in_the_menu",
            ),
        ),
        migrations.AddConstraint(
            model_name="section",
            constraint=models.UniqueConstraint(
                deferrable=django.db.models.constraints.Deferrable["DEFERRED"],
                fields=("page", "position"),
                name="a_place_on_a_page_holds_one_section",
            ),
        ),
        migrations.AddConstraint(
            model_name="section",
            constraint=models.CheckConstraint(
                condition=models.Q(position__lt=15), name="a_page_holds_at_most_fifteen_sections"
            ),
        ),
    ]
