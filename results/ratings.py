"""Conduct and skills ratings: configuring them, entering them, printing them.

**Off by default**, and that is the first thing to know about this module. A
school that has never turned it on has seeded trait rows sitting in its schema
and prints nothing at all: `card_sections()` returns no section, not an empty
one, so there is no heading, no rule across the page and no row of empty boxes
for a parent to wonder about. Off means *absent*, not *blank*.

Three kinds of function, answering to three different people:

1. **Configuration** — which sections print, what the traits are, and what the
   five numbers are called. An office act, so `CONFIGURING_ROLES` is the
   principal and the administrator: the set that already decides who teaches
   which class.
2. **Rating** — the judgement itself, and **the class teacher of that group
   alone**. Narrower than `services.SUBMITTING_ROLES`, which admits an
   administrator; `_require_the_class_teacher()` sets out why the two differ.
3. **Reading** — the section as it prints. From the freeze if the sheet has been
   released, from live configuration if it has not, and those are not the same
   query.

The primitive / `_as()` split is `academics.services`': the plain functions keep
the data honest and ask nothing about who is calling, which is what lets an
import use them, and anything with a request behind it goes through the `_as()`
sibling. `results.services` deliberately has no such split because every act in
the chain is somebody's signature; here the split is right, because a school's
trait list can legitimately arrive from a setup script with no person behind it.

## Where the class group comes from

Nowhere in this module is it stored. A rating is keyed on
`(term, student, trait)`, and the group is read off
`academics.ClassPlacement` — which already holds exactly one answer per child
per term, by constraint. `TraitRating`'s docstring has the argument; the short
version is that a stored copy strands the rating on the arm the child left.

## What is frozen, and what task 3 will add

`freeze_for_release()` writes the conduct section of every card in the class at
the moment of release, and `results.services.release()` calls it inside the same
transaction that writes the release row. This is task 4's half of the snapshot;
scores, averages and attendance are task 3's, and the shape here is meant to be
extended alongside rather than replaced.
"""

from dataclasses import dataclass

from django.db import transaction

from academics import services as academics
from accounts.models import Role
from accounts.students import why_not_a_student_here

from . import positions
from .models import (
    LOWEST_RATING,
    RatingScalePoint,
    ReleasedTraitRating,
    ReportCardSettings,
    ResultSheet,
    SheetState,
    Trait,
    TraitGroup,
    TraitRating,
    HIGHEST_RATING,
)
from .services import ResultsError, school_on_this_connection


class RatingsError(ResultsError):
    """A rating could not be configured, entered or read as asked.

    Subclasses `results.services.ResultsError` rather than starting a hierarchy
    of its own: this is one app publishing one thing, and a caller wrapping
    "get this class's results out" in `except ResultsError` should not have to
    know that the conduct section keeps its refusals somewhere else.
    """


class NotAllowedToRate(RatingsError):
    """The actor is not the class teacher of the group this child sits in."""


class NotAllowedToConfigureRatings(RatingsError):
    """The actor may not change what this school prints, or what it calls it."""


class SectionNotEnabled(RatingsError):
    """This school does not print this section, so there is nothing to rate."""


class TraitIsHidden(RatingsError):
    """The trait is not on this school's sheet any more."""


class NotThisSchoolsStudent(RatingsError):
    """The membership named is not a student of the school being written to.

    Its own type in this module for the reason `fees` and `gradebook` each keep
    one: `accounts.students.why_not_a_student_here()` defines the rule and
    returns a sentence, and each app raises it in its own words and its own
    hierarchy.
    """


class NotPlacedThisTerm(RatingsError):
    """The child sits in no class group this term, so there is nobody to rate them.

    Not an edge case to paper over. A rating is per (student, class group,
    term); with no placement there is no group, so there is no class teacher
    with standing to make the judgement and no sheet for it to be submitted on.
    """


class RatingsLocked(RatingsError):
    """The sheet has left `draft`, so its ratings are part of what is being checked.

    Carries `state` — where the sheet actually is — so the caller can say
    whether this is "the vice principal has it" or "this went home in March".
    """

    def __init__(self, message, state=None):
        super().__init__(message)
        self.state = state


#: Who may say what this school prints and what it calls it.
#:
#: The same set as `academics.services.CLASS_TEACHER_ROLES` and
#: `PLACEMENT_ROLES`, and for the same reason: this is an office act. Changing
#: the trait list changes every card the school issues from then on, which is
#: not one teacher's decision about one class. A teacher who could add a trait
#: could also hide the one they had been rated poorly against.
CONFIGURING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})


# ---------------------------------------------------------------------------
# Settings: which sections this school prints.
# ---------------------------------------------------------------------------


def settings() -> ReportCardSettings:
    """This school's card settings. Never writes.

    Falls back to an **unsaved default** where the row is missing, rather than
    creating it. Two reasons, and the second is the real one: reading a report
    card should not write to the database, and the unsaved default has both
    sections off — which is the answer a school with no settings row should get
    anyway. Migration `0006` seeds the row for every schema; this is what holds
    if a schema is ever created around it.
    """
    return ReportCardSettings.objects.filter(pk=1).first() or ReportCardSettings()


def is_enabled(group) -> bool:
    return settings().enabled(group)


def enabled_groups() -> list[str]:
    """The groups this school prints, in the order they print.

    `TraitGroup`'s declaration order, not the alphabetical order of the stored
    values — which agrees with it today and would stop agreeing the first time a
    third group is added.
    """
    current = settings()
    return [group.value for group in TraitGroup if current.enabled(group.value)]


def set_group_enabled(group, on: bool) -> ReportCardSettings:
    """Turn one section on or off. Returns the settings row."""
    group = TraitGroup(group).value
    row, _ = ReportCardSettings.objects.get_or_create(pk=1)
    setattr(row, ReportCardSettings.FIELD_FOR[group], bool(on))
    row.save(update_fields=[ReportCardSettings.FIELD_FOR[group], "updated_at"])
    return row


# ---------------------------------------------------------------------------
# The trait list, and what the five numbers are called.
# ---------------------------------------------------------------------------


def traits(group=None, *, include_hidden=False):
    """The traits this school rates, in the order they print."""
    rows = Trait.objects.all()
    if group is not None:
        rows = rows.in_group(TraitGroup(group).value)
    if not include_hidden:
        rows = rows.visible()
    return rows


def add_trait(group, name, *, position=None) -> Trait:
    """Add a line to a section. No migration, which is the requirement.

    `position` defaults to the end of the group rather than to zero: a school
    adding "Respect for school property" means it to appear after what is
    already there, and a default of zero would silently put it first.
    """
    group = TraitGroup(group).value
    if position is None:
        last = (
            Trait.objects.in_group(group)
            .order_by("-position")
            .values_list("position", flat=True)
            .first()
        )
        position = 0 if last is None else last + 1
    return Trait.objects.create(group=group, name=name.strip(), position=position)


def rename_trait(trait, name) -> Trait:
    """Change what a trait is called from now on.

    Does **not** reach backwards. Every released card that printed the old name
    keeps printing it, because `ReleasedTraitRating.trait_name` is a copy taken
    at release rather than a join to this row.
    """
    trait.name = name.strip()
    trait.save(update_fields=["name", "updated_at"])
    return trait


def set_trait_hidden(trait, hidden: bool = True) -> Trait:
    """Take a trait off the sheet, or put it back. Never deletes.

    A trait that has been rated is named by those ratings and by every card that
    printed it — both foreign keys are PROTECT — so deleting is not on offer.
    Hiding is what a school actually wants: the trait leaves next term's sheet
    and every card already issued is untouched.
    """
    trait.is_hidden = bool(hidden)
    trait.save(update_fields=["is_hidden", "updated_at"])
    return trait


def reorder(group, trait_ids) -> int:
    """Put this group's traits in this order. Returns how many rows moved.

    Takes the ids in the order wanted rather than a map of positions, because
    that is what a drag-and-drop hands back and it cannot express a duplicate
    position or a gap.

    **The whole group is renumbered, 0 upwards** — the named traits first, in
    the order given, then the rest of the group in the order it was already
    printing. Renumbering only the named ones is the version that looks right
    and is not: `position` is not unique per group, so a trait left where it was
    interleaves with the new numbers rather than following them. Sending
    ["Honesty", "Neatness", "Punctuality"] against a seeded list would put
    Honesty at 0 and Neatness at 1 — and leave Attendance at 1 too, where
    `Meta.ordering` breaks the tie by name and prints it *between* the two
    traits the school had just put next to each other.

    So a screen that sends only the page it is showing still gets what it meant:
    those traits, in that order, at the top, and everything else after them in
    its existing relative order. Hidden traits are renumbered along with the
    rest — they are part of the group's order and come back where the numbering
    left them if the school shows one again.

    Ids belonging to another group are ignored rather than moved into this one:
    reordering is not a way to change what section a trait is in. So are ids
    naming a trait twice, and ids of rows that no longer exist.
    """
    group = TraitGroup(group).value
    # Iterated in `Meta.ordering`, so `known` — and therefore `rest` below — is
    # in the order the group prints today.
    known = {trait.pk: trait for trait in Trait.objects.in_group(group)}

    named, seen = [], set()
    for trait_id in trait_ids:
        trait = known.get(trait_id)
        if trait is None or trait.pk in seen:
            continue
        seen.add(trait.pk)
        named.append(trait)
    rest = [trait for trait in known.values() if trait.pk not in seen]

    moved = []
    for position, trait in enumerate(named + rest):
        if trait.position == position:
            continue
        trait.position = position
        moved.append(trait)
    if moved:
        Trait.objects.bulk_update(moved, ["position"])
    return len(moved)


def scale():
    """The five points, highest first, as a report card's key prints them."""
    return RatingScalePoint.objects.all()


def scale_labels() -> dict[int, str]:
    return dict(RatingScalePoint.objects.values_list("value", "label"))


def set_scale_label(value: int, label: str) -> RatingScalePoint:
    """Rename one point of the scale. The number it stands for does not move."""
    point, _ = RatingScalePoint.objects.update_or_create(
        value=value, defaults={"label": label.strip()}
    )
    return point


# ---------------------------------------------------------------------------
# Entering a rating.
# ---------------------------------------------------------------------------


def _require_student_of_this_school(membership):
    reason = why_not_a_student_here(
        membership, subject="a conduct rating", holder="report card"
    )
    if reason:
        raise NotThisSchoolsStudent(reason)
    return membership


def _require_placed(membership, term):
    placement = academics.placement_of(membership.pk, term)
    if placement is None:
        raise NotPlacedThisTerm(
            f"{membership.name or membership.user} is in no class group for "
            f"{term}, so there is no class teacher to rate them and no sheet to "
            f"submit the rating on. Place them first."
        )
    return placement


def _require_a_ratable_trait(trait):
    """The trait, re-read from this school's schema. Returns the row.

    **Decided on the row rather than on the instance handed in**, which is the
    distinction `results.services._locked()` was corrected on: the checks below
    read `is_hidden` and `group`, and the write uses `pk` alone, so trusting the
    argument authorises one trait and rates against another. A `Trait` read in
    another school's schema, deserialised from a cache, or built by hand carries
    whatever those two fields say — while the foreign key lands on whichever row
    holds that `pk` *here*.

    Nothing legitimate is lost by re-reading: every caller has just fetched the
    row anyway, and this is one indexed lookup on the write path.
    """
    try:
        trait = Trait.objects.get(pk=trait.pk)
    except Trait.DoesNotExist:
        raise TraitIsHidden(
            f"There is no trait {trait.pk!r} on this school's sheet, so there is "
            f"nothing to rate. A trait belongs to the school whose schema it was "
            f"read in."
        ) from None

    if trait.is_hidden:
        raise TraitIsHidden(
            f"“{trait.name}” is no longer on this school's sheet, so it cannot "
            f"be rated. Show it again first if that was not meant."
        )
    if not is_enabled(trait.group):
        raise SectionNotEnabled(
            f"This school does not print the "
            f"{TraitGroup(trait.group).label.lower()} section, so there is "
            f"nothing to rate. A principal or an administrator turns it on."
        )
    return trait


def _require_a_score_on_the_scale(score):
    if not isinstance(score, int) or isinstance(score, bool):
        raise RatingsError(f"A rating is a whole number, not {score!r}.")
    if not LOWEST_RATING <= score <= HIGHEST_RATING:
        raise RatingsError(
            f"{score} is not on the scale. A rating is "
            f"{LOWEST_RATING} to {HIGHEST_RATING}."
        )


def sheet_for(class_group, term):
    """The chain's sheet for this group and term, or `None` if never opened.

    The read path's copy, taking no lock: `card_sections()` asks it to decide
    whether to render the freeze or live configuration, and rendering a card
    must not lock the row a principal is trying to release.
    """
    return ResultSheet.objects.filter(class_group=class_group, term=term).first()


def _locked_sheet_for(class_group, term):
    """The same sheet, re-read under a row lock. `None` if the chain has not started.

    `.get()`, not `.filter().first()`, and that is not a style choice.
    `ResultSheet.Meta.ordering` is `["term", "class_group"]` — two relations — so
    a `select_for_update()` that inherits it compiles to a three-table join and
    Postgres locks a row in `academics_term` and `academics_classgroup` too,
    neither of which a rating writes. `QuerySet.get()` clears ordering itself,
    which is the property `results.services._locked()` documents and
    `test_approval_concurrency.LockScopeTests` pins.

    Must be called inside `transaction.atomic()`; Django refuses `FOR UPDATE`
    outside one.
    """
    try:
        return ResultSheet.objects.select_for_update().get(
            class_group=class_group, term=term
        )
    except ResultSheet.DoesNotExist:
        return None


def _require_the_sheet_is_open(class_group, term):
    """Ratings are editable while the sheet is in `draft`, and not after.

    They are part of what gets submitted, checked and approved — the task says
    so, and it has to mean something. If a rating could change after submission
    then what the vice principal checked and what the principal approved are not
    the same document, and the chain's signatures are attached to a thing that
    moved underneath them.

    A send-back returns the sheet to `draft`, so a teacher told to fix a rating
    can fix it. That is the whole reason `draft` is the test rather than "has
    never been submitted".

    A sheet that does not exist yet is open: the chain has not started, and
    rating before anybody opens the class's sheet is the ordinary order of
    events.

    **The sheet is locked, not merely read**, and the caller writes the rating
    in the same transaction. Unlocked, this is a check followed by an act on
    what it checked — the stale-read shape this codebase has been bitten by in
    `schools.Invitation.accept()` and again in `_require_class_teacher_scope()`.
    A teacher pressing save while the vice principal presses submit would find
    the sheet in `draft`, and commit a rating into a document that was submitted
    a millisecond later: the signature would then be attached to a sheet nobody
    signed. Taking the same lock `_move()` takes orders the two — whichever
    arrives second sees what the first did.

    Postgres alone will not do it here. The trigger in migration `0007` refuses
    a rating for a **released** term, which is the terminal case with no
    legitimate exception; `submitted` and `checked` are a rule about a review in
    progress, which is this function's to hold.

    **`gradebook.Score` has no equivalent rule and that is a live gap**, not a
    precedent — a mark can still be changed after release. It is
    [issue #27](https://github.com/adedejimakinde/luffy-school-saas/issues/27),
    filed rather than fixed here because it is a change to the gradebook's write
    path with its own design question about which way the dependency runs.
    """
    sheet = _locked_sheet_for(class_group, term)
    if sheet is None or sheet.state == SheetState.DRAFT:
        return sheet

    if sheet.state == SheetState.RELEASED:
        raise RatingsLocked(
            f"{class_group} — {term} has been released to parents. Its ratings "
            f"are part of a card somebody is holding, and correcting one is a "
            f"revision rather than an edit.",
            state=sheet.state,
        )
    raise RatingsLocked(
        f"{class_group} — {term} is {sheet.get_state_display().lower()}, so its "
        f"ratings are part of what is being reviewed and cannot be changed. Ask "
        f"for the sheet to be sent back if one is wrong.",
        state=sheet.state,
    )


def _stamp(by):
    return getattr(by, "pk", by)


def rate(term, trait, membership, score, *, by=None) -> TraitRating:
    """Record one judgement of one child on one trait. Returns the row.

    An upsert: rating a child a 4 where they were a 3 is a correction, not a
    second opinion, and `one_rating_per_student_per_trait_per_term` would refuse
    the second row anyway.

    The two writers of one rating are the same person in two tabs — `rate_as()`
    admits the class teacher of that group and nobody else — so last write wins,
    deliberately.

    **There is no `except IntegrityError` retry here, and that is on purpose.**
    One stood here, reading every refusal as "the other tab inserted first" and
    re-running the write as an `UPDATE`. It was wrong twice over. Django's own
    `update_or_create()` takes the row lock and recovers from that insert race
    itself — `get_or_create()` catches the unique violation and re-reads — so
    the branch never saw the race it was written for. What it did see was every
    *other* way this table refuses a row: the `CHECK` behind `rated_by_id`,
    the foreign key onto a trait deleted meanwhile, and migration `0007`'s
    trigger, which raises `restrict_violation` and therefore also arrives as
    `IntegrityError`. Each was retried as an `UPDATE` matching nothing and then
    re-read, so the caller got `TraitRating.DoesNotExist` where the database had
    just said, in a sentence written for them, what was actually wrong.
    `gradebook.services` narrows its equivalent catch rather than dropping it,
    because there the collision genuinely reaches the caller; here nothing does.
    """
    _require_student_of_this_school(membership)
    placement = _require_placed(membership, term)
    trait = _require_a_ratable_trait(trait)
    _require_a_score_on_the_scale(score)

    stamp = _stamp(by)
    # Its own atomic block, for the reason `place_student()` gives: an
    # IntegrityError marks the enclosing transaction unusable, so without a
    # savepoint here a caller rating a whole class inside one `atomic()` could
    # not go on to the next child after one refused row.
    #
    # The state check is *inside* it, holding the sheet's row lock across the
    # write — see `_require_the_sheet_is_open()`. Checking outside and writing
    # inside is two transactions with a submission free to land between them.
    with transaction.atomic():
        _require_the_sheet_is_open(placement.class_group, term)
        rating, _ = TraitRating.objects.update_or_create(
            term=term,
            student_membership_id=membership.pk,
            trait=trait,
            # Two sets, and the difference is the whole point of the second
            # column. `rated_by_id` is who made this judgement; it is written
            # once, at the insert, and never rewritten. Passing it in `defaults`
            # too — which is what one dict does, because `defaults` is used for
            # both paths — would have every later correction overwrite the
            # original rater with whoever last touched the row, leaving two
            # columns that always agree and no record of who rated the child.
            defaults={"score": score, "updated_by_id": stamp},
            create_defaults={
                "score": score,
                "updated_by_id": stamp,
                "rated_by_id": stamp,
            },
        )
        return rating


def clear_rating(term, trait, membership) -> bool:
    """Unrate. True if there was a rating.

    Deletes the row rather than nulling the score, for the reason
    `gradebook.Score` deletes: no row is how "not rated" is spelled, and a
    nullable score would make a blank on the card ambiguous between "the teacher
    has not got to this yet" and "the teacher looked and left it empty".
    """
    _require_student_of_this_school(membership)
    placement = _require_placed(membership, term)

    with transaction.atomic():
        _require_the_sheet_is_open(placement.class_group, term)
        deleted, _ = TraitRating.objects.filter(
            term=term, student_membership_id=membership.pk, trait=trait
        ).delete()
    return bool(deleted)


def ratings_for(membership_id, term) -> dict[int, int]:
    """`trait id -> score` for one child this term. One query."""
    return dict(
        TraitRating.objects.for_student(membership_id, term).values_list(
            "trait_id", "score"
        )
    )


def unrated(class_group, term) -> dict[int, list[str]]:
    """`student membership id -> the traits nobody has rated them on`.

    For a screen that wants to say "eleven still to do" before a teacher
    submits. Deliberately **not** a rule: a card with a blank conduct line is a
    school's business, and blocking release on a missing rating would be this
    module inventing a policy nobody asked it for. It reports; the school
    decides.
    """
    printable = list(traits().filter(group__in=enabled_groups()))
    if not printable:
        return {}

    students = positions.roster_ids(class_group, term)
    rated = {
        (row.student_membership_id, row.trait_id)
        for row in TraitRating.objects.for_students(students, term).only(
            "student_membership_id", "trait_id"
        )
    }
    missing = {}
    for student_id in students:
        names = [
            trait.name
            for trait in printable
            if (student_id, trait.pk) not in rated
        ]
        if names:
            missing[student_id] = names
    return missing


# ---------------------------------------------------------------------------
# What prints.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraitLine:
    """One line of the section: the trait, and what the teacher said about it."""

    trait_id: int
    name: str
    score: int | None
    label: str

    @property
    def is_rated(self) -> bool:
        return self.score is not None


@dataclass(frozen=True)
class CardSection:
    """One heading and its lines. Never produced empty — see `card_sections()`."""

    group: str
    heading: str
    lines: tuple[TraitLine, ...]


def card_sections(membership_id, class_group, term) -> list[CardSection]:
    """The conduct section of one child's card, as it should print.

    **Two sources, and which one is used is not a preference.** If the sheet has
    been released, this reads the frozen rows and nothing else: the card is what
    was published, and no later edit to the school's configuration may reach it.
    If it has not, it composes from live configuration, because a draft card is
    supposed to follow the school's current sheet.

    A group that is off produces **no section**. Not a section with no lines —
    the caller loops over what it is given, so an empty section is a heading and
    a rule across the page with nothing under it, which is exactly what a school
    that does not print conduct must not see. A group that is on but has no
    visible traits produces no section either, for the same reason.
    """
    sheet = sheet_for(class_group, term)
    if sheet is not None and sheet.is_released:
        return _frozen_sections(sheet, membership_id)
    return _live_sections(membership_id, term)


def _frozen_sections(sheet, membership_id) -> list[CardSection]:
    rows = ReleasedTraitRating.objects.filter(
        sheet=sheet, student_membership_id=membership_id
    )
    by_group = {}
    for row in rows:
        by_group.setdefault(row.group, []).append(
            TraitLine(
                trait_id=row.trait_id,
                name=row.trait_name,
                score=row.score,
                label=row.score_label,
            )
        )
    # `TraitGroup`'s order, not the order the rows came back in and not the
    # alphabetical order of the stored value.
    return [
        CardSection(group=group.value, heading=group.label, lines=tuple(lines))
        for group in TraitGroup
        if (lines := by_group.get(group.value))
    ]


def _live_sections(membership_id, term) -> list[CardSection]:
    groups = enabled_groups()
    if not groups:
        return []

    scores = ratings_for(membership_id, term)
    labels = scale_labels()
    printable = list(traits().filter(group__in=groups))

    sections = []
    for group in TraitGroup:
        if group.value not in groups:
            continue
        lines = tuple(
            TraitLine(
                trait_id=trait.pk,
                name=trait.name,
                score=scores.get(trait.pk),
                label=_label_for(scores.get(trait.pk), labels),
            )
            for trait in printable
            if trait.group == group.value
        )
        if lines:
            sections.append(
                CardSection(group=group.value, heading=group.label, lines=lines)
            )
    return sections


def _label_for(score, labels) -> str:
    """The school's word for this number, or the number itself.

    The fallback is not decoration. `a_frozen_rating_carries_its_label` refuses
    a frozen row with a score and no label, so a scale point deleted out from
    under a rating — which no function here does, but a `psql` session can —
    must not be able to stop a release.
    """
    if score is None:
        return ""
    return labels.get(score) or str(score)


# ---------------------------------------------------------------------------
# The freeze.
# ---------------------------------------------------------------------------


def freeze_for_release(sheet) -> int:
    """Copy this class's conduct sections as they read now. Returns rows written.

    Called by `results.services.release()` **inside the transaction that writes
    the release row**, so a sheet that says `released` always has the card that
    was released sitting behind it.

    Writes a row for every child on the roster × every visible trait of every
    enabled group — including the traits nobody rated, whose row carries a null
    score. The unrated ones matter as much as the rest: what is being frozen is
    the *section*, and "which traits existed, and in what order" is precisely
    what a later edit would otherwise rewrite.

    Silent about a school with the feature off: no enabled group means no rows,
    which is what makes a released card of such a school render with no section
    rather than an empty one, for ever, however the school later configures
    itself.
    """
    groups = enabled_groups()
    if not groups:
        return 0

    printable = list(traits().filter(group__in=groups))
    students = positions.roster_ids(sheet.class_group, sheet.term)
    if not printable or not students:
        return 0

    labels = scale_labels()
    scores = {
        (row.student_membership_id, row.trait_id): row.score
        for row in TraitRating.objects.for_students(students, sheet.term)
    }

    rows = [
        ReleasedTraitRating(
            sheet=sheet,
            student_membership_id=student_id,
            trait=trait,
            group=trait.group,
            trait_name=trait.name,
            position=trait.position,
            score=scores.get((student_id, trait.pk)),
            score_label=_label_for(scores.get((student_id, trait.pk)), labels),
        )
        for student_id in students
        for trait in printable
    ]
    # `bulk_create`, which does not call `save()` — and does not need to. The
    # model's `save()` refuses *edits*; inserting is the one thing a frozen row
    # is allowed to do, and it happens exactly once, here.
    ReleasedTraitRating.objects.bulk_create(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Actor-checked entry points.
# ---------------------------------------------------------------------------


def can_configure_ratings(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & CONFIGURING_ROLES)


def _require_configuring_authority(actor):
    school = school_on_this_connection()
    if not can_configure_ratings(actor, school):
        raise NotAllowedToConfigureRatings(
            f"{actor} may not change what {school} prints on its report cards. "
            f"The trait list, the scale and the sections are set by a principal "
            f"or an administrator of the school."
        )
    return school


def _require_the_class_teacher(actor, placement, term):
    """Only the class teacher of that child's group may rate them.

    **Narrower than submitting the sheet, on purpose.**
    `results.services.SUBMITTING_ROLES` admits an administrator, on the stated
    reasoning that entering and submitting a paper sheet is office work in most
    schools — transcription, where the judgement was made on paper by somebody
    else and the office is copying it in. A conduct rating has no such paper
    behind it. It is a judgement about a child made by the person who taught
    them all term, and there is no clerical version of it.

    So there is no administrator exemption here, and no principal one either. If
    a school genuinely wants the office to key in ratings from a paper sheet,
    that is a change to make deliberately, in a PR that says so.
    """
    school = school_on_this_connection()
    if not getattr(actor, "is_authenticated", False):
        raise NotAllowedToRate("Signing in is required to rate a child.")

    membership_id = actor.membership_id_at(school, Role.TEACHER)
    if academics.is_class_teacher(membership_id, placement.class_group, term):
        return school

    if academics.class_teacher_of(placement.class_group, term) is None:
        raise NotAllowedToRate(
            f"{placement.class_group} has no class teacher for {term}, so nobody "
            f"may rate its children yet. A principal or an administrator assigns "
            f"one."
        )
    raise NotAllowedToRate(
        f"{actor} is not the class teacher of {placement.class_group} for "
        f"{term}, so may not rate its children. A conduct rating is the class "
        f"teacher's own judgement, which is why it is not the office's to enter."
    )


def rate_as(actor, term, trait, membership, score, *, by=None) -> TraitRating:
    """`rate()` for a caller with a request behind it.

    Authority is asked at the school on the connection, like every other write
    in this app, and the placement is read before it — because "may you rate
    this child" is a question about the group they sit in, and there is no
    answer to it until we know which group that is.
    """
    _require_student_of_this_school(membership)
    placement = _require_placed(membership, term)
    _require_the_class_teacher(actor, placement, term)
    return rate(term, trait, membership, score, by=actor if by is None else by)


def clear_rating_as(actor, term, trait, membership) -> bool:
    """`clear_rating()` for a caller with a request behind it."""
    _require_student_of_this_school(membership)
    placement = _require_placed(membership, term)
    _require_the_class_teacher(actor, placement, term)
    return clear_rating(term, trait, membership)


def set_group_enabled_as(actor, group, on: bool) -> ReportCardSettings:
    _require_configuring_authority(actor)
    return set_group_enabled(group, on)


def add_trait_as(actor, group, name, *, position=None) -> Trait:
    _require_configuring_authority(actor)
    return add_trait(group, name, position=position)


def rename_trait_as(actor, trait, name) -> Trait:
    _require_configuring_authority(actor)
    return rename_trait(trait, name)


def set_trait_hidden_as(actor, trait, hidden: bool = True) -> Trait:
    _require_configuring_authority(actor)
    return set_trait_hidden(trait, hidden)


def reorder_as(actor, group, trait_ids) -> int:
    _require_configuring_authority(actor)
    return reorder(group, trait_ids)


def set_scale_label_as(actor, value, label) -> RatingScalePoint:
    _require_configuring_authority(actor)
    return set_scale_label(value, label)


__all__ = [
    "CONFIGURING_ROLES",
    "CardSection",
    "NotAllowedToConfigureRatings",
    "NotAllowedToRate",
    "NotPlacedThisTerm",
    "NotThisSchoolsStudent",
    "RatingsError",
    "RatingsLocked",
    "SectionNotEnabled",
    "TraitIsHidden",
    "TraitLine",
    "add_trait",
    "add_trait_as",
    "can_configure_ratings",
    "card_sections",
    "clear_rating",
    "clear_rating_as",
    "enabled_groups",
    "freeze_for_release",
    "is_enabled",
    "rate",
    "rate_as",
    "ratings_for",
    "rename_trait",
    "rename_trait_as",
    "reorder",
    "reorder_as",
    "scale",
    "scale_labels",
    "set_group_enabled",
    "set_group_enabled_as",
    "set_scale_label",
    "set_scale_label_as",
    "set_trait_hidden",
    "set_trait_hidden_as",
    "settings",
    "sheet_for",
    "traits",
    "unrated",
]
