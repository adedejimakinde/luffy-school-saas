"""The Ogun State template: choosing it, and what choosing it sets up.

`docs/ogun-template.md` is the description. A school picks the template on the
setup page; `set_template_as()` records the choice and, when it is Ogun,
applies the sheet's presets in the same transaction:

- **Assessments**, per subject, for the current term and every term after it:
  1st Test 10, 2nd Test 10, Assignment 10, Exam 70. The three continuous
  assessments make the sheet's "Cont. Assess Scores (30)" and the exam its
  "Exam Scores (70)".
- **Traits**: the six affective and six psychomotor lines of the sheet, in its
  order, with both sections switched on.
- **The scale's words**: 5 Excellent, 4 Good, 3 Average, 2 Below Average,
  1 Unsatisfactory.

## Never over a mark or a rating

The one rule, and every branch below is a case of it.

- A subject whose assessments in a term already carry **a mark** keeps them
  as they are: nothing renamed, re-weighted or removed. That covers a released
  term too: a released card's subject lines exist only where the class was
  marked, and a released term's marks cannot be deleted
  (`gradebook/0002_a_released_mark_stays_released`). It is reported as kept. A subject with assessments and no marks has
  them replaced by the four, because nothing anybody entered is lost.
  The subject's assessments are locked (`SELECT ... FOR UPDATE`) before the
  marks are counted, and a mark being entered takes a key-share lock on its
  assessment, so the two cannot interleave: a mark that lands first keeps its
  subject; one that comes after finds the Ogun papers.
- A trait that has **ever been rated** is never hidden, even when the sheet
  does not print it: hiding it would take a rating off a card still to be
  released. It is reported as kept. Traits are renamed to the sheet's spelling
  only where they are the same line (`RENAMES`), and a rename never touches a
  rating: the value stays, and a released card keeps its frozen name.
- The scale's words are labels; the numbers ratings store do not move.

Applying twice changes nothing the second time. Switching back to Standard
changes the card's layout only and undoes none of this.
"""

from dataclasses import dataclass, field

from django.db import transaction

from academics.models import Term
from academics.services import can_set_up
from gradebook.models import Assessment, Score, Subject

from . import ratings
from .models import (
    CardTemplate,
    ReportCardSettings,
    Trait,
    TraitGroup,
    TraitRating,
)

#: The sheet's papers, in print order: (name, out of).
ASSESSMENTS = (
    ("1st Test", 10),
    ("2nd Test", 10),
    ("Assignment", 10),
    ("Exam", 70),
)

AFFECTIVE = (
    "Punctuality",
    "Neatness",
    "Honesty",
    "Self-Control",
    "Attentiveness in Class",
    "Leadership",
)

PSYCHOMOTOR = (
    "Handwriting",
    "Games & Sports",
    "Fluency",
    "Handling of Tools",
    "Drawing & Painting",
    "Crafts",
)

TRAITS = {TraitGroup.AFFECTIVE.value: AFFECTIVE, TraitGroup.PSYCHOMOTOR.value: PSYCHOMOTOR}

#: Lines already on a school's sheet (the seeded list, `results/0006`) that are
#: the sheet's line under another spelling. Renamed rather than hidden, so a
#: rating already made against one stays on the card.
RENAMES = {
    TraitGroup.AFFECTIVE.value: {"attentiveness in class": "Attentiveness in Class"},
    TraitGroup.PSYCHOMOTOR.value: {
        "games/sports": "Games & Sports",
        "handling of tools and equipment": "Handling of Tools",
    },
}

SCALE = (
    (5, "Excellent"),
    (4, "Good"),
    (3, "Average"),
    (2, "Below Average"),
    (1, "Unsatisfactory"),
)


class NotAllowedToChooseTheTemplate(Exception):
    pass


class TemplateRefused(Exception):
    """Not a template this prints. The message is for the person."""


@dataclass
class Applied:
    """What `apply_presets()` did, for the page to say."""

    #: "Mathematics, First term 2025/2026" for each subject given the papers.
    assessments_set: list = field(default_factory=list)
    #: The same, for each subject that kept its own because marks were in.
    assessments_kept: list = field(default_factory=list)
    traits_added: list = field(default_factory=list)
    traits_renamed: list = field(default_factory=list)
    traits_hidden: list = field(default_factory=list)
    #: Traits the sheet does not print and that stay, because they were rated.
    traits_kept: list = field(default_factory=list)


def _row() -> ReportCardSettings:
    row, _ = ReportCardSettings.objects.select_for_update().get_or_create(pk=1)
    return row


def is_ogun() -> bool:
    row = ReportCardSettings.objects.filter(pk=1).only("template").first()
    return bool(row and row.template == CardTemplate.OGUN)


# -- assessments --------------------------------------------------------------


def terms_from_now():
    """The current term and every term starting after it.

    With no current term, every term that has not ended. A finished term is
    history: its papers were what they were.
    """
    from django.utils import timezone

    current = Term.objects.filter(is_current=True).first()
    if current is not None:
        return list(Term.objects.filter(starts_on__gte=current.starts_on).order_by("starts_on"))
    return list(Term.objects.filter(ends_on__gte=timezone.localdate()).order_by("starts_on"))


def _is_ogun_set(papers) -> bool:
    return [(a.name, a.max_score) for a in papers] == list(ASSESSMENTS)


def apply_assessments(term, applied: Applied):
    """The sheet's four papers for every active subject in `term`. See the module."""
    for subject in Subject.objects.filter(is_active=True).order_by("name"):
        label = f"{subject.name}, {term}"
        papers = list(
            Assessment.objects.select_for_update()
            .filter(term=term, subject=subject)
            .order_by("position", "name", "id")
        )
        ids = [a.pk for a in papers]
        if ids and Score.objects.filter(assessment_id__in=ids).exists():
            if not _is_ogun_set(papers):
                applied.assessments_kept.append(label)
            continue
        if _is_ogun_set(papers):
            continue
        Assessment.objects.filter(pk__in=ids).delete()
        Assessment.objects.bulk_create(
            Assessment(term=term, subject=subject, name=name, max_score=out_of, position=position)
            for position, (name, out_of) in enumerate(ASSESSMENTS)
        )
        applied.assessments_set.append(label)


# -- traits and the scale ---------------------------------------------------------


def apply_traits(applied: Applied):
    rated = set(TraitRating.objects.values_list("trait_id", flat=True).distinct())
    for group, wanted in TRAITS.items():
        ratings.set_group_enabled(group, True)
        existing = list(Trait.objects.in_group(group))
        by_name = {t.name.lower(): t for t in existing}
        for old, new in RENAMES[group].items():
            trait = by_name.get(old)
            if trait is not None and new.lower() not in by_name:
                applied.traits_renamed.append(f"{trait.name} → {new}")
                trait.name = new
                trait.save(update_fields=["name", "updated_at"])
                by_name[new.lower()] = by_name.pop(old)

        order = []
        for name in wanted:
            trait = by_name.get(name.lower())
            if trait is None:
                trait = Trait.objects.create(group=group, name=name)
                applied.traits_added.append(name)
            else:
                if trait.name != name:
                    trait.name = name
                if trait.is_hidden:
                    trait.is_hidden = False
                trait.save(update_fields=["name", "is_hidden", "updated_at"])
            order.append(trait.pk)

        wanted_lower = {n.lower() for n in wanted}
        for trait in Trait.objects.in_group(group).filter(is_hidden=False):
            if trait.name.lower() in wanted_lower:
                continue
            if trait.pk in rated:
                applied.traits_kept.append(trait.name)
                order.append(trait.pk)
                continue
            trait.is_hidden = True
            trait.save(update_fields=["is_hidden", "updated_at"])
            applied.traits_hidden.append(trait.name)
        ratings.reorder(group, order)


def apply_scale():
    for value, label in SCALE:
        ratings.set_scale_label(value, label)


@transaction.atomic
def apply_presets() -> Applied:
    """Everything the sheet sets up, in one transaction. No authority asked."""
    _row()  # Two presses at once take turns here.
    applied = Applied()
    for term in terms_from_now():
        apply_assessments(term, applied)
    apply_traits(applied)
    apply_scale()
    return applied


# -- choosing ---------------------------------------------------------------------


def _require_authority(actor, school):
    if not can_set_up(actor, school):
        raise NotAllowedToChooseTheTemplate(
            "The report card template is chosen by a principal or an administrator of the school."
        )


@transaction.atomic
def set_template_as(actor, school, template: str):
    """Choose the card. Ogun applies its presets as it is chosen.

    Returns `(settings row, Applied or None)`. Choosing Ogun again applies the
    presets again, which is how a school that added a subject or opened a term
    since gets them, and changes nothing that is already right.
    """
    _require_authority(actor, school)
    if template not in CardTemplate.values:
        raise TemplateRefused("Choose the Standard card or the Ogun State card.")
    row = _row()
    row.template = template
    row.save(update_fields=["template", "updated_at"])
    applied = apply_presets() if template == CardTemplate.OGUN else None
    return row, applied


def after_term_opened(term):
    """An Ogun school's new term gets the sheet's papers as it is opened."""
    if is_ogun():
        with transaction.atomic():
            apply_assessments(term, Applied())


__all__ = [
    "AFFECTIVE",
    "ASSESSMENTS",
    "Applied",
    "NotAllowedToChooseTheTemplate",
    "PSYCHOMOTOR",
    "SCALE",
    "TemplateRefused",
    "after_term_opened",
    "apply_presets",
    "is_ogun",
    "set_template_as",
    "terms_from_now",
]
