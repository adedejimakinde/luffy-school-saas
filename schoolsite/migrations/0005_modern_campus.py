"""Modern Campus takes the starter theme's place, and a hero's picture becomes a slideshow.

`docs/school-sites-theme-modern.md`, PR A. On every school's draft, with no
step by hand:

- **The theme.** "starter" becomes "modern", the one designed theme. Its options
  move with it, and gain what Modern Campus draws with: the demo's accent,
  detail and dark-band colours (decided 1 November 2026), the school's own main
  colour kept, and all five animated backgrounds switched on.
- **The hero.** The one picture a hero held (`image`) becomes a slideshow of one
  (`slides`); the hero's own focal point, unused since pictures got theirs in
  PR 5, is dropped.

Published revisions are records and are never rewritten (their trigger refuses
it): `render` draws an older snapshot the same way, "starter" as "modern" and an
`image` as one slide, and `services.comparable` compares them as they draw, so
no school is told it has something new to publish.

The values are written out here rather than imported from `schoolsite.themes`,
so this migration means the same thing whatever that module says later.
"""

from django.db import migrations, models

DEMO_COLOURS = {"accent": "#FFD66B", "detail": "#C9A24A", "dark": "#0F1B33"}
ANIMATIONS = ("hero", "academics", "student_life", "admissions", "contact")


def _modern_options(options):
    options = dict(options or {})
    # The starter theme's own header style and font pairing are not Modern Campus's.
    options.pop("header_style", None)
    options.pop("font_pairing", None)
    options["colours"] = {**DEMO_COLOURS, **(options.get("colours") or {})}
    options["animations"] = {**{name: True for name in ANIMATIONS}, **(options.get("animations") or {})}
    return options


def forwards(apps, schema_editor):
    SiteSettings = apps.get_model("schoolsite", "SiteSettings")
    Section = apps.get_model("schoolsite", "Section")
    for settings in SiteSettings.objects.all():
        options = dict(settings.theme_options or {})
        options["modern"] = _modern_options(options.pop("starter", options.get("modern")))
        settings.theme_options = options
        if settings.theme == "starter":
            settings.theme = "modern"
        settings.save(update_fields=["theme", "theme_options"])
    for section in Section.objects.filter(kind="hero"):
        data = dict(section.data or {})
        image = data.pop("image", None)
        data.pop("focal", None)
        if "slides" not in data:
            data["slides"] = [{"picture": image}] if image else []
        section.data = data
        section.save(update_fields=["data"])


def backwards(apps, schema_editor):
    SiteSettings = apps.get_model("schoolsite", "SiteSettings")
    Section = apps.get_model("schoolsite", "Section")
    for settings in SiteSettings.objects.all():
        options = dict(settings.theme_options or {})
        modern = dict(options.pop("modern", {}))
        modern.pop("animations", None)
        colours = {k: v for k, v in (modern.get("colours") or {}).items() if k not in ("detail", "dark")}
        modern["colours"] = colours
        options["starter"] = modern
        settings.theme_options = options
        if settings.theme == "modern":
            settings.theme = "starter"
        settings.save(update_fields=["theme", "theme_options"])
    for section in Section.objects.filter(kind="hero"):
        data = dict(section.data or {})
        slides = data.pop("slides", None) or []
        data["image"] = slides[0]["picture"] if slides else None
        data.setdefault("focal", None)
        section.data = data
        section.save(update_fields=["data"])


class Migration(migrations.Migration):

    dependencies = [
        ("schoolsite", "0004_pictures_and_albums"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sitesettings",
            name="theme",
            field=models.CharField(default="modern", max_length=32),
        ),
        migrations.RunPython(forwards, backwards),
    ]
