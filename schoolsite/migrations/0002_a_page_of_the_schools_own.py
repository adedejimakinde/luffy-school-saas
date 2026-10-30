# PR 3b (`docs/school-sites.md` §2.1.1): a school's own pages beside the six
# fixed ones, and one menu order for them all. Additive: the six fixed rows every
# school has become `kind="fixed"`, in the menu order the site drew them in
# before, Home first. The rules about what a page may be are added in 0003, on
# their own, after the rows they hold have their values.

from django.db import migrations, models

#: The order PR 3 drew the menu in, which becomes each fixed page's place.
PAGES = ("home", "about", "admissions", "news", "gallery", "contact")


def place_the_fixed_pages(apps, schema_editor):
    Page = apps.get_model("schoolsite", "Page")
    for position, key in enumerate(PAGES):
        Page.objects.filter(key=key).update(kind="fixed", menu_position=position)


class Migration(migrations.Migration):

    dependencies = [("schoolsite", "0001_the_draft_and_what_was_published")]

    operations = [
        migrations.RemoveConstraint(model_name="page", name="a_page_is_one_of_the_fixed_six"),
        migrations.AddField(
            model_name="page",
            name="kind",
            field=models.CharField(
                choices=[("fixed", "Fixed"), ("custom", "The school's own")], default="fixed", max_length=8
            ),
        ),
        migrations.AlterField(
            model_name="page",
            name="key",
            field=models.CharField(
                blank=True,
                choices=[("home", "Home"), ("about", "About"), ("admissions", "Admissions"), ("news", "News"),
                         ("gallery", "Gallery"), ("contact", "Contact")],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="page", name="slug", field=models.CharField(blank=True, default="", max_length=40)
        ),
        migrations.AddField(
            model_name="page", name="slot", field=models.PositiveSmallIntegerField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="page",
            name="menu_position",
            field=models.PositiveSmallIntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(model_name="page", name="ever_published", field=models.BooleanField(default=False)),
        migrations.AlterModelOptions(name="page", options={"ordering": ["menu_position", "id"]}),
        migrations.RunPython(place_the_fixed_pages, migrations.RunPython.noop),
    ]
