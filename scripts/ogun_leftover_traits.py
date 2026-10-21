# Read-only: which schools got the Ogun sheet's trait lines *and* their old ones.
#
# Run inside `manage.py shell` (docs/ogun-template.md, "Schools that picked the
# template before 2026-10-20"):
#
#   docker compose run --rm -T web python manage.py shell < scripts/ogun_leftover_traits.py
#
# Until #280 (2026-10-20) choosing the Ogun template kept every affective and
# psychomotor line that had ever been rated and the sheet does not print, so a
# school with a rated Standard list ended with the sheet's twelve lines plus its
# own leftovers. This lists, for every school, the lines on its card that are
# not the sheet's and whether a rating was ever made against each.
#
# AFFECTED: all twelve of the sheet's lines are showing, so the template's
# presets were applied, and at least one other line is showing as well. That is
# true whether the school's card is Ogun or went back to Standard afterwards
# (switching back undoes none of the presets). A school with leftovers and
# fewer than twelve of the sheet's lines never applied the presets: its list is
# its own and is printed under "own list", not flagged.
#
# Every school is read inside a READ ONLY transaction, so a write anywhere in
# this file would be refused by Postgres. Nothing is changed, and nothing is
# printed about a child.

from django.db import connection, transaction
from django_tenants.utils import schema_context

from results import ogun
from results.models import ReportCardSettings, Trait, TraitGroup, TraitRating
from schools.models import School


def _sheet():
    lines = {TraitGroup.AFFECTIVE.value: ogun.AFFECTIVE, TraitGroup.PSYCHOMOTOR.value: ogun.PSYCHOMOTOR}
    renames = getattr(ogun, "RENAMES", {})
    return {
        group: {name.lower() for name in names} | set(renames.get(group, {}))
        for group, names in lines.items()
    }


def _read(school, sheet):
    with schema_context(school.schema_name), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        row = ReportCardSettings.objects.filter(pk=1).only("template").first()
        rated = set(TraitRating.objects.values_list("trait_id", flat=True).distinct())
        shown = list(Trait.objects.filter(is_hidden=False).values_list("pk", "group", "name"))
    on_sheet = sum(1 for _, group, name in shown if name.lower() in sheet.get(group, ()))
    others = [
        (group, name, pk in rated)
        for pk, group, name in sorted(shown, key=lambda r: (r[1], r[0]))
        if name.lower() not in sheet.get(group, ())
    ]
    return (row.template if row else "standard"), on_sheet, others


sheet = _sheet()
wanted = len(ogun.AFFECTIVE) + len(ogun.PSYCHOMOTOR)
affected = []
print(f"{'school':<28}{'card':<10}{'sheet lines':<13}other lines showing")
for school in School.objects.exclude(schema_name="public").order_by("slug"):
    template, on_sheet, others = _read(school, sheet)
    flag = "AFFECTED" if on_sheet == wanted and others else ("own list" if others else "")
    if flag == "AFFECTED":
        affected.append(school.slug)
    shown = ", ".join(f"{name} [{group}, {'rated' if was_rated else 'never rated'}]" for group, name, was_rated in others)
    print(f"{school.slug:<28}{template:<10}{on_sheet}/{wanted:<10}{flag:<10}{shown}")
connection.set_schema_to_public()
print()
print("Affected: " + (", ".join(affected) if affected else "none"))
