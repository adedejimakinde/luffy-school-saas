"""The chain a term's results walk before a parent sees them, and its audit.

Two tables. `ResultSheet` is one class's results for one term and holds *where
they have got to*; `ResultSheetTransition` is the append-only log of how they
got there. The split is the whole design, and it is the opposite of the obvious
one.

**The obvious one is columns.** Put `submitted_by`, `checked_by` and
`approved_by` on the sheet and read them back. It survives exactly until the
first send-back: a vice principal returns the sheet, the teacher fixes a score
and resubmits, and `submitted_by` is overwritten. The sheet then says who
submitted it *this time* and has silently forgotten that it was ever refused,
who refused it, and why. A results system whose whole promise is "this is what
was released, and here is how it came to be released" cannot have a memory that
edits itself.

So every transition is a row, written once and never changed — the same rule
`fees.FeeLedgerEntry` holds, enforced the same two ways: a model that refuses,
for the developer, and a database trigger, for the import and the `psql`
session that never touch the model.

## The states

    draft ──submit──▶ submitted ──check──▶ checked ──approve──▶ approved
      ▲                   │                   │                    │
      └───────────────────┴───────────────────┴────────────────────┘
                        send back (with a reason)
                                                                   │
                                                              release
                                                                   ▼
                                                              released ✱

`released` is terminal, and that is enforced rather than conventional. It takes
**two** guards, on two tables, and it is worth saying why one is not enough:

- `nothing_moves_out_of_released` is a check constraint on the *log*, refusing
  any transition row whose `from_state` is `released`.
- the trigger in migration 0003 is on the *sheet*, refusing an UPDATE that moves
  `state` off `released`.

The first alone was the original design, and it does not hold the rule. It stops
a reversal being *recorded*; it does nothing to stop one being *performed*.
`ResultSheet.objects.filter(state="released").update(state="draft")` — from a
psql session, an import, or a bulk fix — touches no transition row and so meets
no constraint, and the sheet silently reverts with the audit showing nothing at
all. That is worse than an unguarded revert, because the log now reads as though
the result is still released.

A released result is one a parent is holding; correcting it is a *revision*,
which makes a new version and leaves this one standing, and that is built
separately. Neither guard is in a revision's way: a revision never moves this
version out of `released`.

## Cycles, and why the log carries one

`cycle` counts how many times the sheet has been sent back. Every transition
row records the cycle it happened in, and a send-back is the last act of its
cycle — it writes its own row, then bumps the sheet.

It exists to make the same-signatory rule expressible in SQL. The rule is that
one person may not perform two different steps on one sheet: a teacher who is
also the acting vice principal must not both submit and check. As a unique
index on `(sheet, actor)` that would be wrong, because a teacher who submits,
is sent back, and resubmits appears twice quite legitimately. On
`(sheet, cycle, actor)` it is right: within one pass through the chain each
person signs at most once, and a send-back opens a fresh pass.

Only *advancing* steps count as signatures on that index — see
`ADVANCING_STATES` below, which sets out why a send-back and a release are
deliberately not signatures, and what breaks if a send-back is counted as one.
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q, Value


class SheetState(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted by teacher"
    CHECKED = "checked", "Checked by vice principal"
    APPROVED = "approved", "Approved by principal"
    RELEASED = "released", "Released to parents"


#: The states a sheet can be sent back *from*. Not `draft`, which is where a
#: send-back goes, and not `released` — see `nothing_moves_out_of_released`.
#:
#: Holds the same three members as `ADVANCING_STATES` below, and the two are
#: kept apart rather than aliased because they answer different questions: this
#: one is about a `from_state`, that one about a `to_state`, and they would stop
#: agreeing the moment a state is added that can be signed but not returned
#: from, or the reverse.
SENDABLE_BACK_FROM = frozenset(
    {SheetState.SUBMITTED.value, SheetState.CHECKED.value, SheetState.APPROVED.value}
)

#: Arriving at one of these is a **signature**: somebody moved the sheet closer
#: to a parent, on their own authority. These are the steps the same-signatory
#: rule counts, and the reason it counts only these is worth stating.
#:
#: Sending back is not a signature. It is a retraction, and a retraction can
#: only ever *reduce* how far a result has travelled — so letting the same
#: person do it twice, or do it after signing, risks nothing. Counting it would
#: do real harm: at `approved` in a small school the teacher, the vice principal
#: and the principal have all signed that pass, so if a send-back were a
#: signature there would be nobody left who could take one. A sheet with a known
#: wrong score would be stuck, with release as its only exit.
#:
#: Release is not a signature either — it publishes a decision already taken, so
#: the principal who approved may also release.
ADVANCING_STATES = frozenset(
    {SheetState.SUBMITTED.value, SheetState.CHECKED.value, SheetState.APPROVED.value}
)


class TransitionsAreAppendOnly(Exception):
    """Something tried to edit or delete a transition that already exists."""


class ResultSheet(models.Model):
    """One class's results for one term, and where they have got to.

    The unit of approval is `(class_group, term)` rather than a subject or a
    student. A subject-scoped chain would give a report card no single moment of
    release — it would become releasable only once every subject had passed
    independently, and there would be nothing for a snapshot to be frozen
    against. A student-scoped one would make a principal approve forty-five
    times to release a class.
    """

    # Both tenant-local, so both are real foreign keys with real integrity —
    # the note `gradebook.Assessment` and `academics.ClassPlacement` carry.
    class_group = models.ForeignKey(
        "academics.ClassGroup", related_name="result_sheets", on_delete=models.PROTECT
    )
    term = models.ForeignKey(
        "academics.Term", related_name="result_sheets", on_delete=models.PROTECT
    )

    #: Where the results have got to. Guarded in the database by the trigger in
    #: migration 0003, which refuses any UPDATE moving this off `released` — the
    #: log's `nothing_moves_out_of_released` guards the audit, and this guards
    #: the fact the audit is about. See the module docstring for why the log
    #: constraint alone left a released sheet revertible with no trace.
    state = models.CharField(
        max_length=16, choices=SheetState, default=SheetState.DRAFT
    )

    #: How many times this sheet has been sent back. Not history — the history
    #: is in the log — but the number each log row is stamped with, which is
    #: what makes the same-signatory index correct across a resubmission.
    cycle = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["term", "class_group"]
        constraints = [
            # One chain per class per term. Two sheets for one class would mean
            # two answers to "have this term's results been released?", and the
            # snapshot frozen at release would have two things to be frozen
            # from.
            models.UniqueConstraint(
                fields=["class_group", "term"], name="one_result_sheet_per_class_term"
            ),
        ]

    def __str__(self):
        return f"{self.class_group} — {self.term} ({self.get_state_display()})"

    @property
    def is_released(self) -> bool:
        return self.state == SheetState.RELEASED


class ResultSheetTransition(models.Model):
    """One recorded step. Written once, never changed, never deleted.

    Carries `from_state` as well as `to_state` even though the previous row's
    `to_state` implies it. That redundancy is on purpose: it is what lets
    `nothing_moves_out_of_released` be a check constraint on *this row* rather
    than a rule that has to walk the log, and a constraint that needs no context
    is one no future query can get wrong.
    """

    sheet = models.ForeignKey(
        ResultSheet,
        related_name="transitions",
        # PROTECT, not CASCADE. A sheet with an approval history is not a row
        # anybody should be able to delete out from under its own audit — and a
        # cascade would do it silently, which is the failure this table exists
        # to prevent.
        on_delete=models.PROTECT,
    )

    from_state = models.CharField(max_length=16, choices=SheetState)
    to_state = models.CharField(max_length=16, choices=SheetState)

    #: The sheet's cycle when this happened. See the module docstring.
    cycle = models.PositiveIntegerField()

    # A bare id, not a ForeignKey, pointing at the actor's `accounts.User` in
    # the public schema — the policy docs/tenancy.md settles and `Score` and
    # `ClassPlacement` already follow: `on_delete` resolves against whichever
    # schema the connection is on, so a key across the boundary neither
    # protects nor cascades correctly.
    #
    # Not nullable, unlike `Score.recorded_by_id`. A mark can arrive from an
    # import with nobody behind it; an approval cannot. The entire value of this
    # table is that every step names the person who took it.
    actor_id = models.PositiveBigIntegerField(db_index=True)

    #: Why, in the actor's own words. Required on a send-back and optional
    #: elsewhere — a refusal that does not say what is wrong sends the teacher
    #: back to a sheet of forty-five scores with no idea which one to look at.
    reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # `sheet_id`, not `sheet`. Ordering by the *relation* makes Django sort
        # by `ResultSheet.Meta.ordering`, which itself sorts by two more
        # relations — so `history()` and the same-signatory lookup both compiled
        # to a four-table join sorted by the term's session and the class's
        # level. Neither query wants that, and one of them runs inside the row
        # lock, where every joined table lengthens the hold.
        #
        # It also made `history()`'s "oldest first" true only by accident: the
        # leading sort keys were the term and class, constant only because the
        # query happens to be single-sheet. On local columns it is true because
        # it is what the ordering says.
        ordering = ["sheet_id", "created_at", "pk"]
        constraints = [
            # **Release is terminal**, as a rule Postgres holds. Task 8's
            # revision does not violate this: a revision makes a new version
            # rather than moving this one out of `released`.
            models.CheckConstraint(
                condition=~Q(from_state=SheetState.RELEASED),
                name="nothing_moves_out_of_released",
            ),
            # **The same person may not sign twice in one pass through the
            # chain.** The application refuses this first, with a sentence
            # naming what they already did; this is what holds when the refusal
            # is bypassed, and what holds under concurrency where two requests
            # can both read "they have not signed yet".
            #
            # Scoped to `ADVANCING_STATES` — see that constant for why a
            # send-back and a release are deliberately not signatures.
            models.UniqueConstraint(
                fields=["sheet", "cycle", "actor_id"],
                condition=Q(to_state__in=sorted(ADVANCING_STATES)),
                name="one_signature_per_person_per_review_cycle",
            ),
            # One arrival at each state per pass. The backstop for two people
            # approving at the same instant: `select_for_update()` serialises
            # them, and this is what would refuse the second even if it did not.
            models.UniqueConstraint(
                fields=["sheet", "cycle", "to_state"],
                name="one_transition_to_each_state_per_cycle",
            ),
            # There is deliberately no `Meta.indexes` entry for
            # `(sheet, cycle)`. The two unique constraints above already build
            # btrees led by exactly those columns, so an explicit one answers no
            # query they cannot — it is a third index per tenant schema, one per
            # school on the platform, maintained on every insert for nothing.
            # A send-back must say why. Enforced here rather than in a form,
            # because the import and the shell session that skip the service
            # are exactly the callers most likely to leave it blank.
            #
            # The test is "contains a non-whitespace character", not "is not the
            # empty string". `send_back()` compares `reason.strip()`, so a
            # reason of three spaces is refused by the service and — under the
            # first spelling of this constraint, `~Q(reason="")` — accepted by
            # the database. That is the worst of the two: the gap is exactly the
            # caller the constraint exists for, and what reaches the teacher is
            # a send-back whose reason renders blank, which is the failure the
            # rule was written to prevent. The two layers now refuse the same
            # inputs.
            models.CheckConstraint(
                condition=~Q(to_state=SheetState.DRAFT) | Q(reason__regex=r"\S"),
                name="a_send_back_says_why",
            ),
        ]

    def __str__(self):
        return (
            f"{self.sheet_id}: {self.from_state} -> {self.to_state} "
            f"by {self.actor_id}"
        )

    def save(self, *args, **kwargs):
        """Refuse to rewrite a row that already exists.

        The trigger installed by migration 0002 is the rule that actually
        holds; this is the one that produces a readable error before Postgres
        produces a less readable one. Both exist on purpose — the same split
        `fees.FeeLedgerEntry` makes, for the same reason.
        """
        if self.pk is not None and not self._state.adding:
            raise TransitionsAreAppendOnly(
                f"Transition {self.pk} has already been recorded and cannot be "
                f"changed. Record the next step instead — an approval history "
                f"that can be edited is not an approval history."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TransitionsAreAppendOnly(
            f"Transition {self.pk} cannot be deleted. The chain has to keep "
            f"saying what it said."
        )


class TraitGroup(models.TextChoices):
    """The two halves of the conduct section, stored and rendered separately.

    A school may print one, both or neither. They are separate settings rather
    than one because they are separate sections on a real card, with separate
    headings, and a school that prints "Affective Domain" and not "Psychomotor
    Domain" is the ordinary case rather than an edge one.

    Declaration order is the order the sections print in. Not the alphabetical
    order of the stored values, which happens to agree today and would stop
    agreeing the first time a third group is added.
    """

    AFFECTIVE = "affective", "Affective (conduct)"
    PSYCHOMOTOR = "psychomotor", "Psychomotor (skills)"


#: The scale, which is 1-5 for every school. Only the *labels* are
#: configurable — see `RatingScalePoint`. The range is fixed because it is what
#: the stored integer means: a school that moved to 1-10 would silently
#: reinterpret every rating already recorded, including released ones.
LOWEST_RATING = 1
HIGHEST_RATING = 5


class ReportCardSettings(models.Model):
    """Which optional sections this school prints. One row per schema.

    **Both default to off**, and that is the load-bearing default. The affective
    and psychomotor sections are standard on many Nigerian report cards and
    absent from plenty of others, so a school that has never heard of this
    feature must see no trace of it: no section, no heading, and no placeholder
    where one would go.

    "Off" therefore means *absent*, not *blank*. `ratings.card_sections()`
    returns no section at all for a group that is off, rather than a section
    with no rows — a distinction that only shows up in the rendered card, which
    is exactly where it matters.
    """

    #: Pinned to 1 so "the settings" is one row and not a table somebody appends
    #: a second opinion to. Seeded by migration for every school; `load()`
    #: falls back to an unsaved default rather than writing on a read path.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)

    affective_enabled = models.BooleanField(
        default=False,
        help_text="Print the affective (conduct) section on report cards.",
    )
    psychomotor_enabled = models.BooleanField(
        default=False,
        help_text="Print the psychomotor (skills) section on report cards.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    #: Which column holds which group's switch. A map rather than
    #: `getattr(self, f"{group}_enabled")`, because a string built at runtime is
    #: a column name nothing checks: a group renamed in `TraitGroup` would go on
    #: reading a field that no longer exists, and the first sign of it would be
    #: an `AttributeError` on somebody's report card. Here the pair is written
    #: down, and `enabled()` refuses a group it does not know.
    FIELD_FOR = {
        TraitGroup.AFFECTIVE.value: "affective_enabled",
        TraitGroup.PSYCHOMOTOR.value: "psychomotor_enabled",
    }

    class Meta:
        verbose_name_plural = "report card settings"
        constraints = [
            models.CheckConstraint(
                condition=Q(id=1), name="one_report_card_settings_row"
            ),
        ]

    def __str__(self):
        printed = [
            TraitGroup(group).label
            for group, field in self.FIELD_FOR.items()
            if getattr(self, field)
        ]
        return f"Report card sections: {', '.join(printed) or 'none'}"

    def enabled(self, group) -> bool:
        """Does this school print this group's section?"""
        field = self.FIELD_FOR.get(TraitGroup(group).value)
        if field is None:  # pragma: no cover - unreachable while FIELD_FOR is total
            raise KeyError(f"No settings column for trait group {group!r}.")
        return getattr(self, field)


class TraitQuerySet(models.QuerySet):
    def visible(self):
        return self.filter(is_hidden=False)

    def in_group(self, group):
        return self.filter(group=group)


class Trait(models.Model):
    """One line of the conduct section: "Punctuality", "Handwriting".

    **Rows, not choices**, and that is the requirement rather than a preference:
    adding, hiding or reordering a trait must not require a migration. A school
    that wants "Respect for school property" adds a row; a school that never
    grades handwriting hides one. Both are Tuesday-afternoon administration, and
    neither should need a deploy.

    Seeded with the list most Nigerian schools start from, per schema, by
    migration. A seed is a starting point and not a promise: every seeded row is
    editable and hideable, and nothing in the code names one.
    """

    group = models.CharField(max_length=16, choices=TraitGroup)

    name = models.CharField(max_length=64)

    #: Where it prints, smallest first. **Explicit, never alphabetical** — the
    #: order on a report card is the school's own and carries meaning, and
    #: "Attentiveness in class" is not meant to lead the section merely because
    #: A sorts first.
    #:
    #: Deliberately **not** unique per group. A unique `(group, position)` reads
    #: tidier and makes the ordinary edit — swap two traits round — impossible
    #: without a temporary value or a deferred constraint, which is how
    #: reordering code ends up with a hole in the middle of it. Duplicates are
    #: therefore legal and `Meta.ordering` breaks the tie deterministically, so
    #: two traits sharing a position still print in the same order every time.
    position = models.PositiveSmallIntegerField(default=0)

    #: Hidden, not deleted. A trait that has ever been rated is named by those
    #: ratings and by every released card that carried it, so removing the row
    #: is not available — `TraitRating.trait` and `ReleasedTraitRating.trait`
    #: are both PROTECT. Hiding takes it off next term's sheet and leaves every
    #: card that already printed it alone.
    is_hidden = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TraitQuerySet.as_manager()

    class Meta:
        # `id` last, so the order is total. Without it two traits sharing a
        # position and a name — which the constraints below do allow across
        # groups — could swap places between two renders of the same card.
        ordering = ["group", "position", "name", "id"]
        constraints = [
            # Per group, not per school: "Attendance" is a reasonable affective
            # trait and nothing stops a school also wanting it as a psychomotor
            # one. Two rows with one name *inside* one group are the real
            # problem — the section prints the same line twice and a teacher has
            # two boxes to tick for one judgement.
            models.UniqueConstraint(
                fields=["group", "name"], name="uniq_trait_name_per_group"
            ),
            models.CheckConstraint(
                condition=Q(name__regex=r"\S"), name="a_trait_has_a_name"
            ),
        ]

    def __str__(self):
        return self.name


class RatingScalePoint(models.Model):
    """What each of the five numbers is called. Editable; the numbers are not.

    A school prints "5 — Excellent" in the key at the foot of the card, and
    "Excellent" is the school's word: some say "Very Good" where others say
    "Good", and a few use "Exemplary". So the label is a row.

    The **value** is not configurable, and the difference matters. The integer
    is what `TraitRating.score` stores, so changing what 1-5 means would
    reinterpret every rating already recorded, including the ones on cards that
    have gone home. A school wanting a 1-10 scale is asking for a different
    scale, not a relabelled one, and that is a change to make deliberately.
    """

    value = models.PositiveSmallIntegerField(unique=True)
    label = models.CharField(max_length=32)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Highest first: the key on a report card reads 5 down to 1.
        ordering = ["-value"]
        constraints = [
            models.CheckConstraint(
                condition=Q(value__gte=LOWEST_RATING, value__lte=HIGHEST_RATING),
                name="a_scale_point_is_within_the_scale",
            ),
            # Non-whitespace, not merely non-empty — `a_send_back_says_why` in
            # this same app records why the two are different rules, and a label
            # of three spaces renders as a blank key entry.
            models.CheckConstraint(
                condition=Q(label__regex=r"\S"), name="a_scale_point_has_a_label"
            ),
        ]

    def __str__(self):
        return f"{self.value} — {self.label}"


class TraitRatingQuerySet(models.QuerySet):
    def for_student(self, membership_id, term):
        return self.filter(term=term, student_membership_id=membership_id)

    def for_students(self, membership_ids, term):
        return self.filter(term=term, student_membership_id__in=membership_ids)


class TraitRating(models.Model):
    """One class teacher's judgement of one child on one trait, this term.

    **Keyed on (term, student, trait) — the class group is not stored**, and
    that is the decision this table turns on. The spec says a rating is per
    (student, class group, term), and it is: a child sits in exactly one group
    per term, by `academics.ClassPlacement`'s
    `one_class_placement_per_student_per_term`. Storing the group as well would
    be storing a *second* answer to a question the placement already answers,
    and the two disagree the moment a child moves arms in January — the rating
    would stay pinned to JSS 1A while the child, the sheet and the report card
    all moved to JSS 1B, so the new class teacher could neither see the old
    rating nor replace it, and the card would print nothing.

    So the group is derived, on the same reasoning `positions.roster_ids()`
    derives a roster rather than caching one.

    **No row means not rated**, exactly as `gradebook.Score` means it: there is
    no null score and clearing a rating deletes the row. A nullable score would
    let a row mean "not rated yet", which is the conflation that makes a card
    print a blank where a teacher believes they entered something.
    """

    term = models.ForeignKey(
        "academics.Term", related_name="trait_ratings", on_delete=models.PROTECT
    )

    #: PROTECT, so a trait that has been rated cannot be deleted out from under
    #: its ratings. Hiding is what a school wants and what the field above is
    #: for; deleting would take the evidence with it.
    trait = models.ForeignKey(Trait, related_name="ratings", on_delete=models.PROTECT)

    # A bare id into the shared membership table — docs/tenancy.md's policy, and
    # the fifth table to follow it. `ratings.rate()` checks the id names a
    # student of *this* school before anything is written; see
    # `accounts.students.why_not_a_student_here()`.
    student_membership_id = models.PositiveBigIntegerField(db_index=True)

    #: 1-5. The range is checked here as well as against `RatingScalePoint`,
    #: and the two are not the same check: a school can delete or relabel a
    #: scale point, and a rating whose label had gone missing would still have
    #: to be a number between one and five.
    score = models.PositiveSmallIntegerField()

    # Bare ids again. Nullable for the reason `Score.recorded_by_id` is: a
    # rating can arrive from an import of last year's cards with nobody behind
    # it, and naming a fictional rater is worse than naming none.
    #
    # Two columns because they answer two questions, and `rate()` keeps them
    # apart the way `gradebook.services` does: `rated_by_id` is written once, at
    # the insert, and names the teacher whose judgement this is; `updated_by_id`
    # moves on every correction. Stamped on both by the same value the first
    # time, which is why only a later correction tells them apart.
    #
    # **These hold `User` ids, not `Membership` ids** — `rate_as()` stamps the
    # actor, and the actor is a user. The column above holds a membership id,
    # and both are small dense integers, so a screen resolving the wrong one
    # would confidently name an unrelated person rather than fail.
    # `ResultSheetTransition.actor_id` is a user id for the same reason.
    rated_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    updated_by_id = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TraitRatingQuerySet.as_manager()

    class Meta:
        ordering = ["term_id", "student_membership_id", "trait_id"]
        # There is deliberately no `Meta.indexes` entry for
        # `(term, student_membership_id)` — the card read. The unique constraint
        # below builds a btree led by exactly those two columns, so a declared
        # index answers no query it cannot and is a second index per tenant
        # schema, one per school on the platform, maintained on every insert for
        # nothing. `ResultSheetTransition.Meta` in this file made the same call
        # first; this one was written before that note was read.
        constraints = [
            models.UniqueConstraint(
                fields=["term", "student_membership_id", "trait"],
                name="one_rating_per_student_per_trait_per_term",
            ),
            models.CheckConstraint(
                condition=Q(score__gte=LOWEST_RATING, score__lte=HIGHEST_RATING),
                name="a_rating_is_within_the_scale",
            ),
        ]

    def __str__(self):
        return f"membership {self.student_membership_id}: {self.trait_id} = {self.score}"


class RatingsAreFrozenAtRelease(Exception):
    """Something tried to edit or delete a rating a parent is already holding."""


class ReleasedTraitRating(models.Model):
    """The conduct section of one child's card, as it read at the moment of release.

    This is the half of the freeze that task 4 owns. Task 3 freezes the scores,
    the averages and the attendance; the shape here is meant to be extended
    alongside, not replaced — one table per thing frozen, all hung off the
    `ResultSheet` whose release wrote them.

    ## Why a copy, when every field is a join away

    Because every one of those joins goes through a row a school may edit next
    term, and the requirement is the opposite of that: **a released card does
    not change.** Four separate edits would otherwise rewrite a card that has
    already gone home —

    | the school does this | the released card would have |
    | --- | --- |
    | renames "Neatness" to "Tidiness" | a line it never printed |
    | hides "Honesty" | one line fewer |
    | reorders the section | the same lines in a different order |
    | relabels 4 from "Very Good" to "Good" | a worse judgement than the teacher gave |

    None of those are misuse. They are a school tidying its own configuration,
    and every one of them silently reaches backwards through a join into a term
    that is closed. So the name, the position, the score and the label of the
    score are all **copied** here at release, and a released card is rendered
    from this table and nothing else.

    `trait` stays as a real foreign key even though its name is copied, because
    it is in the same schema and PROTECT is the right answer: a trait that has
    been printed on a released card is not a row anybody may delete. The copy is
    what the card renders; the key is provenance, and answers "which trait is
    this line, today" for a school comparing two terms.

    ## One row per (child, trait), including the traits nobody rated

    A row is written for **every visible trait of every enabled group**, rated
    or not, because the frozen thing is the *section* and not merely the marks
    in it. "Which traits existed and in what order" is the part a later edit
    would otherwise rewrite, and it has to be recorded even where the answer is
    a blank line.

    That repeats the trait list once per child — around five hundred short rows
    for a class of forty-five with eleven traits. The alternative, a per-sheet
    list joined to per-child scores, saves those rows and buys a second table
    that can disagree with the first. One table means a released card is exactly
    "these rows, in this order", which is a property that can be looked at.

    ## Append-only

    Enforced the two ways `ResultSheetTransition` and `fees.FeeLedgerEntry` are:
    `save()` and `delete()` refuse, which is the error a developer sees, and a
    trigger refuses, which is the error the import and the `psql` session run
    into. A frozen card that can be edited is not frozen.
    """

    sheet = models.ForeignKey(
        ResultSheet,
        related_name="released_trait_ratings",
        # PROTECT for the reason `ResultSheetTransition.sheet` is PROTECT: a
        # sheet whose release froze a card is not a row to delete from under it.
        on_delete=models.PROTECT,
    )

    student_membership_id = models.PositiveBigIntegerField(db_index=True)

    trait = models.ForeignKey(
        Trait, related_name="released_ratings", on_delete=models.PROTECT
    )

    #: Copied. See the docstring — these four are the card.
    group = models.CharField(max_length=16, choices=TraitGroup)
    trait_name = models.CharField(max_length=64)
    position = models.PositiveSmallIntegerField()

    #: Null where the trait existed and nobody rated it: the line printed blank,
    #: and the frozen card has to print it blank again. This is the one place a
    #: null score is right, and it is right for the opposite reason to
    #: `TraitRating`'s — there, no row means unrated; here, the row *is* the
    #: record that the line existed.
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    score_label = models.CharField(max_length=32, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Local columns, and total. The section order is decided by
        # `TraitGroup`'s declaration order in `ratings.card_sections()`, not by
        # sorting `group` as a string — which agrees today and would stop
        # agreeing the first time a group is added whose value sorts wrong.
        ordering = ["sheet_id", "student_membership_id", "position", "trait_name", "id"]
        # No declared index, for the reason `TraitRating.Meta` gives: the unique
        # constraint below is already a btree on `(sheet, student_membership_id,
        # trait)`, and the card read — every frozen line for one child on one
        # sheet — is its leading pair. `freeze_for_release()` bulk-inserts about
        # five hundred rows per class per release, and each index is paid for on
        # every one of them.
        constraints = [
            models.UniqueConstraint(
                fields=["sheet", "student_membership_id", "trait"],
                name="one_frozen_rating_per_student_per_trait",
            ),
            models.CheckConstraint(
                condition=Q(score__isnull=True)
                | Q(score__gte=LOWEST_RATING, score__lte=HIGHEST_RATING),
                name="a_frozen_rating_is_within_the_scale",
            ),
            # A score and its label travel together. A frozen row with a number
            # and no word for it would print a bare "4" in a column of words;
            # one with a word and no number is a label attached to nothing.
            models.CheckConstraint(
                condition=Q(score__isnull=True, score_label="")
                | (Q(score__isnull=False) & ~Q(score_label="")),
                name="a_frozen_rating_carries_its_label",
            ),
        ]

    def __str__(self):
        return f"{self.trait_name}: {self.score_label or '—'}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise RatingsAreFrozenAtRelease(
                f"Frozen rating {self.pk} is part of a card that has been "
                f"released. It cannot be changed — correcting a released result "
                f"is a revision, which makes a new version and leaves this one "
                f"standing."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RatingsAreFrozenAtRelease(
            f"Frozen rating {self.pk} cannot be deleted. The card has to keep "
            f"saying what it said."
        )


class CommentAuthor(models.TextChoices):
    """The two people who sign a report card, and the order they print in.

    A Nigerian card carries the class teacher's remark and the principal's, one
    under the other, each labelled with whose it is. They are not two rows of
    one list: they are written by different people, refused to different
    people, and read as two different judgements — the teacher's about the term
    they taught, the principal's about the card as a whole.

    Declaration order is print order. Not the alphabetical order of the stored
    values, which agrees today and would stop agreeing the first time a third
    signatory is added.
    """

    CLASS_TEACHER = "class_teacher", "Class teacher's remark"
    PRINCIPAL = "principal", "Principal's remark"


#: How long a remark may be. A limit rather than a `TextField`, because a report
#: card has a box of a fixed size on it and a remark that does not fit is a
#: layout problem discovered at print time. 250 characters is about three lines
#: in the space these cards leave.
#:
#: Published as a constant so the screen can count down against the same number
#: the database enforces. A form that says "250 characters" while the column
#: takes 200 is a truncation nobody sees until a parent reads half a sentence.
MAX_COMMENT_LENGTH = 250


class CommentPhraseQuerySet(models.QuerySet):
    def for_author(self, author):
        return self.filter(author=CommentAuthor(author).value)


class CommentPhrase(models.Model):
    """One canned remark a school offers, for one of the two signatories.

    "Clickable to insert, then edit": a teacher picks a phrase, it lands in the
    box, and they change it. So a phrase is a **starting point for typing**, not
    a value a comment refers to — which is why `ReportCardComment` keeps no
    foreign key back here and stores the text the teacher actually left. Editing
    or deleting a phrase therefore cannot reach a comment already written, let
    alone one on a card that has gone home. The release freeze guards the other
    direction: edits to the comment itself.

    **The two sets are separate, not one pool filtered.** `author` is mandatory
    and every read goes through `for_author()`; there is deliberately no
    accessor that returns both. A teacher choosing a remark must never be shown
    "Has performed creditably this term and should maintain the standard"
    written for a principal to sign, and the way to guarantee that is for the
    question "which phrases exist" to be unanswerable without saying whose.

    Unlike `Trait`, a phrase is **deleted rather than hidden**. Hiding exists
    there because ratings and released cards name the trait row, so removing it
    would take evidence with it. Nothing names a phrase — the text is copied at
    write time — so a school that no longer offers a remark can simply stop
    offering it.
    """

    author = models.CharField(max_length=16, choices=CommentAuthor)

    text = models.CharField(max_length=MAX_COMMENT_LENGTH)

    #: Where it sits in the list the screen shows. Explicit, and not unique per
    #: author, for `Trait.position`'s reasons: swapping two entries round must
    #: not need a temporary value, and `Meta.ordering` breaks the tie.
    position = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CommentPhraseQuerySet.as_manager()

    class Meta:
        # `id` last, so the order is total: two phrases sharing a position and a
        # text cannot swap places between two renders of the same list.
        ordering = ["author", "position", "text", "id"]
        constraints = [
            # Per author, not per school. The same sentence can reasonably be
            # offered to both signatories; two identical entries in *one* list
            # is the real problem, because the screen then shows the same line
            # twice and a teacher has two identical things to click.
            models.UniqueConstraint(
                fields=["author", "text"], name="uniq_comment_phrase_per_author"
            ),
            models.CheckConstraint(
                condition=Q(text__regex=r"\S"), name="a_comment_phrase_says_something"
            ),
        ]

    def __str__(self):
        return self.text


class ReportCardCommentQuerySet(models.QuerySet):
    def for_student(self, membership_id, term):
        return self.filter(term=term, student_membership_id=membership_id)

    def for_students(self, membership_ids, term):
        return self.filter(term=term, student_membership_id__in=membership_ids)


class ReportCardComment(models.Model):
    """One signatory's remark about one child, this term.

    Keyed on **(term, student, author)** and storing no class group, for
    `TraitRating`'s reasons: `academics.ClassPlacement` already holds exactly
    one answer per child per term, and a second copy strands the remark on the
    arm the child left in January.

    **No row means no remark**, and that is the whole of how "empty" is spelled.
    There is no blank body: `a_comment_says_something` refuses whitespace, and
    clearing a comment deletes the row. A card with no teacher's remark prints
    no teacher's remark — not a labelled box with nothing in it, which is what a
    nullable body would eventually render as.

    The two authors are written by two different people and neither may write
    the other's — `comments.write_as()` refuses — but they are one table because
    they are one thing: a remark about a child on a card, differing only in
    whose it is. Two tables would be the same four columns twice, and every
    read, freeze and card render would do its work twice to put them back
    together.
    """

    term = models.ForeignKey(
        "academics.Term", related_name="report_card_comments", on_delete=models.PROTECT
    )

    # A bare id into the shared membership table — docs/tenancy.md's policy.
    # `comments.write()` checks the id names a student of *this* school before
    # anything is written; see `accounts.students.why_not_a_student_here()`.
    student_membership_id = models.PositiveBigIntegerField()

    author = models.CharField(max_length=16, choices=CommentAuthor)

    #: What the teacher actually left, phrase-derived or typed from nothing.
    #: See `CommentPhrase` for why there is no key back to the phrase.
    body = models.CharField(max_length=MAX_COMMENT_LENGTH)

    # Bare ids again, nullable for `Score.recorded_by_id`'s reason: a comment
    # can arrive from an import of last year's cards with nobody behind it, and
    # naming a fictional author is worse than naming none.
    #
    # Two columns because they answer two questions. `written_by_id` is stamped
    # once, at the insert, and names whose remark this is; `updated_by_id` moves
    # on every correction. Stamped with the same value the first time, which is
    # why only a later correction tells them apart.
    #
    # **These hold `User` ids, not `Membership` ids** — `write_as()` stamps the
    # actor, and the actor is a user. The column above holds a membership id,
    # and both are small dense integers, so a screen resolving the wrong one
    # would confidently name an unrelated person rather than fail.
    # `TraitRating.rated_by_id` carries the same note, added after review read
    # this comment's ancestor as saying the opposite.
    written_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    updated_by_id = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ReportCardCommentQuerySet.as_manager()

    class Meta:
        ordering = ["term_id", "student_membership_id", "author"]
        # No declared index. The card read — both remarks for one child this
        # term — is the leading pair of the unique constraint below, so a
        # declared one answers nothing extra and is a second btree per tenant
        # schema, per school, maintained on every write. `TraitRating.Meta` and
        # `ResultSheetTransition.Meta` make the same call, the second of them
        # after review caught the first.
        constraints = [
            models.UniqueConstraint(
                fields=["term", "student_membership_id", "author"],
                name="one_comment_per_author_per_student_per_term",
            ),
            # Non-whitespace, not merely non-empty — `a_send_back_says_why` in
            # this same app records why the two are different rules. A remark of
            # three spaces is a labelled empty box with extra steps.
            models.CheckConstraint(
                condition=Q(body__regex=r"\S"), name="a_comment_says_something"
            ),
        ]

    def __str__(self):
        return f"{CommentAuthor(self.author).label}: {self.body[:40]}"


class CommentsAreFrozenAtRelease(Exception):
    """Something tried to edit or delete a remark a parent is already holding."""


class ReleasedComment(models.Model):
    """The remarks on one child's card, as they read at the moment of release.

    The same half-of-the-snapshot `ReleasedTraitRating` is, and the same
    reasoning: a released card does not change, and every route back to the live
    row is a route a later edit can take. A teacher correcting a remark next
    term must not rewrite the sentence a parent read in March.

    **A child with no remark gets no row**, which is the difference from the
    frozen ratings. There, a row is written even for a trait nobody rated,
    because what is frozen is the *section* — which lines existed and in what
    order — and that survives only if it is recorded. Here there is no list to
    preserve: two authors, fixed in code, and an absent remark prints as absent.
    A row carrying an empty body would be the labelled empty box this design
    refuses everywhere else.

    Append-only, enforced the two ways `ResultSheetTransition`,
    `fees.FeeLedgerEntry` and `ReleasedTraitRating` are: `save()` and `delete()`
    refuse, which is the error a developer sees, and a trigger refuses, which is
    the error a `psql` session, an import or a bulk `.update()` runs into.
    """

    sheet = models.ForeignKey(
        ResultSheet,
        related_name="released_comments",
        # PROTECT for `ResultSheetTransition.sheet`'s reason: a sheet whose
        # release froze a card is not a row to delete from under it.
        on_delete=models.PROTECT,
    )

    student_membership_id = models.PositiveBigIntegerField()

    author = models.CharField(max_length=16, choices=CommentAuthor)

    body = models.CharField(max_length=MAX_COMMENT_LENGTH)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Local columns, and total. Print order is `CommentAuthor`'s declaration
        # order, decided in `comments.card_comments()` rather than by sorting
        # the stored string — which agrees today and would stop agreeing the
        # first time a signatory is added whose value sorts wrong.
        ordering = ["sheet_id", "student_membership_id", "author", "id"]
        # No declared index, for the reason above: the unique constraint below
        # already leads with `(sheet, student_membership_id)`.
        constraints = [
            models.UniqueConstraint(
                fields=["sheet", "student_membership_id", "author"],
                name="one_frozen_comment_per_author_per_student",
            ),
            models.CheckConstraint(
                condition=Q(body__regex=r"\S"),
                name="a_frozen_comment_says_something",
            ),
        ]

    def __str__(self):
        return f"{CommentAuthor(self.author).label}: {self.body[:40]}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise CommentsAreFrozenAtRelease(
                f"Frozen comment {self.pk} is part of a card that has been "
                f"released. It cannot be changed — correcting a released result "
                f"is a revision, which makes a new version and leaves this one "
                f"standing."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise CommentsAreFrozenAtRelease(
            f"Frozen comment {self.pk} cannot be deleted. The card has to keep "
            f"saying what it said."
        )


# ---------------------------------------------------------------------------
# The session: three terms, one average, and one decision about a child's year.
#
# Everything above this line is reckoned per *term*. A Nigerian report card's
# last line is not: it is the average of the year and what the school decided
# to do about it, and both are the school's own arithmetic rather than a
# universal one. See `docs/sessions.md`.
# ---------------------------------------------------------------------------


class SessionAveraging(models.TextChoices):
    """How a school reckons a session average out of its three terms.

    Both are real, and the choice decides promotions, so neither can be
    hardcoded. `EQUAL` is the default because it is the one a school that has
    never thought about it means.
    """

    EQUAL = "equal", "Straight mean of the terms sat"
    WEIGHTED = "weighted", "Weighted (for example 20/20/60)"


class TermAbsence(models.TextChoices):
    """Why a term contributed nothing to a session average.

    **The arithmetic does not branch on this and the reader does.** All three
    causes renormalise identically — an absent term is never a zero, because a
    zero invents a failing grade the child never earned and would drive a wrong
    promotion suggestion. What differs is what a member of staff should do
    about it:

    | cause | what it means | what staff do |
    | --- | --- | --- |
    | `NOT_ENROLLED` | the child was not here that term | nothing; a transfer |
    | `UNMARKED` | the child was here and nobody entered marks | enter the marks |
    | `NO_TERM` | the school has no such term this session | create the term |

    Collapsing them into a bare `None` would make a marking backlog look
    exactly like a mid-session transfer, which is the one thing a head of year
    reading a session sheet most needs to tell apart.

    **Never printed on a parent's card.** It is staff-only, the same rule
    position lives under: a parent reading "no marks were entered" is being
    shown the school's filing, not their child's year.
    """

    NOT_ENROLLED = "not_enrolled", "Not enrolled this term"
    UNMARKED = "unmarked", "Enrolled, but no marks were entered"
    NO_TERM = "no_term", "The school has no such term this session"


class PromotionStatus(models.TextChoices):
    """What the school decided about a child's year.

    There is deliberately **no `UNDECIDED` member**. Undecided is the absence
    of a `PromotionDecision` row, not a value one can hold — the same way
    "not marked" is the absence of a `Score`. A stored `UNDECIDED` would be a
    default somebody could write by accident, and the whole point of the
    recorded/suggested split is that nothing writes a decision except a person.
    """

    PROMOTED = "promoted", "Promoted"
    ON_TRIAL = "on_trial", "Promoted on trial"
    REPEATED = "repeated", "Repeating the class"
    WITHDRAWN = "withdrawn", "Withdrawn"


#: The mark a session average has to reach for `PROMOTED` to be *suggested*.
#: Fifty is the common Nigerian default. It decides a suggestion and never a
#: decision — see `PromotionDecision`.
DEFAULT_PASS_MARK = Decimal("50.00")


def _a_term_is_present_or_explained(prefix):
    """One term's three columns agree, or the row is refused.

    An average, the weight actually applied to it, and a reason it is missing:
    exactly one of "present" and "explained" is true. A row with an average and
    an absence reason is two answers to one question; a row with neither is a
    term that vanished with no account of itself, which is precisely the state
    `TermAbsence` exists to prevent.

    Built by a function because it is the same constraint three times and the
    only thing that differs is which term. Written out longhand it is fifteen
    lines of near-identical `Q`, which is fifteen lines for a reviewer to
    diff by eye.
    """
    average, weight, absence = (
        f"{prefix}_average",
        f"{prefix}_weight_used",
        f"{prefix}_absence",
    )
    return models.CheckConstraint(
        condition=(
            Q(**{f"{average}__isnull": False, f"{weight}__isnull": False, absence: ""})
            | (
                Q(**{f"{average}__isnull": True, f"{weight}__isnull": True})
                & ~Q(**{absence: ""})
            )
        ),
        name=f"the_{prefix}_term_is_present_or_explained",
    )


def _the_term_carried_weight(prefix):
    """`prefix`'s applied weight is a number above nought. **NULL-safe.**

    `weight_used > 0` on its own is NULL for a term the child did not sit, and
    a CHECK whose condition evaluates to NULL *passes* — so the null test is
    not decoration. Without it, a session average with no weighting at all
    behind it, which is the one thing
    `a_session_average_has_a_term_behind_it` exists to refuse, would sail
    through on an unknown.
    """
    field = f"{prefix}_weight_used"
    return Q(**{f"{field}__isnull": False, f"{field}__gt": 0})


def _the_term_carried_nothing(prefix):
    """The exact complement of `_the_term_carried_weight()`: null, or nought.

    Written out rather than negating the other one, for the same NULL reason:
    `~Q(...)` over a nullable column is a three-valued expression that has to
    be read twice to be believed, and this is read by whoever is debugging a
    refused release.
    """
    field = f"{prefix}_weight_used"
    return Q(**{f"{field}__isnull": True}) | Q(**{field: 0})


class SessionSettings(models.Model):
    """How this school reckons a session. One row per schema.

    Two numbers that a school owns and the platform must not assume: how the
    three terms combine into a year's average, and the mark that average has to
    reach before promotion is *suggested*.

    ## The weights are null in `EQUAL` mode, not zero and not 33.33

    A straight mean of three terms is not expressible as three integers summing
    to 100, and 33.33/33.33/33.34 is not a straight mean — it is a weighting
    that quietly favours third term by a hundredth. So the mode is stored, and
    the weights are **absent** when it is `EQUAL`.

    Absent rather than left at their old values, because a stale 20/20/60
    sitting in a row whose mode says `EQUAL` is a field that lies to the next
    reader: it looks like configuration and is not read by anything. The same
    reasoning as `TraitRating` having no row for an unrated child.

    ## Sum to a hundred, in the database

    A weighting that sums to 90 is a school that typed one number wrong, and
    every session average it produces is wrong by a factor nobody would notice
    — the numbers all still look like percentages. `weights_sum_to_one_hundred`
    refuses it, so an import and a `psql` session are refused too.

    Note this is the *configured* weighting. What actually produced any given
    average is the **renormalised** one, which depends on which terms the child
    sat, and is recorded per child on `ReleasedSessionResult`.
    """

    #: Pinned to 1 for `ReportCardSettings`' reason: "the settings" is one row,
    #: not a table somebody appends a second opinion to.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)

    averaging = models.CharField(
        max_length=16,
        choices=SessionAveraging,
        default=SessionAveraging.EQUAL,
        help_text="How the three terms combine into a session average.",
    )

    #: All three null in `EQUAL` mode, all three set and summing to 100 in
    #: `WEIGHTED`. Enforced below; there is no half-configured weighting.
    first_weight = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    second_weight = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    third_weight = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    pass_mark = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=DEFAULT_PASS_MARK,
        help_text=(
            "The session average at which promotion is suggested. A suggestion "
            "only — the decision is a person's."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "session settings"
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="one_session_settings_row"),
            models.CheckConstraint(
                condition=Q(pass_mark__gte=0) & Q(pass_mark__lte=100),
                name="a_pass_mark_is_a_percentage",
            ),
            # `EQUAL` carries no weights; `WEIGHTED` carries three that sum to
            # a hundred. The arithmetic is expressed against `first_weight`
            # rather than as a three-way sum because a CHECK comparing a column
            # to an expression of the other two is one Postgres can evaluate
            # per row with no function call.
            models.CheckConstraint(
                condition=(
                    Q(
                        averaging=SessionAveraging.EQUAL,
                        first_weight__isnull=True,
                        second_weight__isnull=True,
                        third_weight__isnull=True,
                    )
                    | (
                        Q(averaging=SessionAveraging.WEIGHTED)
                        & Q(
                            first_weight__isnull=False,
                            second_weight__isnull=False,
                            third_weight__isnull=False,
                        )
                        & Q(
                            first_weight=Value(Decimal(100))
                            - F("second_weight")
                            - F("third_weight")
                        )
                    )
                ),
                name="weights_sum_to_one_hundred",
            ),
        ]

    def __str__(self):
        if self.averaging == SessionAveraging.EQUAL:
            return f"Session average: straight mean, pass at {self.pass_mark}"
        return (
            f"Session average: {self.first_weight}/{self.second_weight}/"
            f"{self.third_weight}, pass at {self.pass_mark}"
        )


class SessionResultsAreFrozenAtRelease(Exception):
    """A frozen session line was edited or deleted. See `ReleasedSessionResult`."""


class ReleasedSessionResult(models.Model):
    """One child's year, as it read at the moment the third term went home.

    The session half of the freeze `ReleasedTraitRating` does for conduct and
    `ReleasedReportCardComment` does for remarks, written by
    `sessions.freeze_for_release()` inside the transaction that releases the
    **third** term's sheet. First and second term releases write nothing here:
    a session average is not a thing until the year it averages is over.

    ## Why a copy, when the terms are all still in the database

    Because a session average reaches backwards through two years of rows that
    a school may legitimately change:

    | the school does this | the session average would |
    | --- | --- |
    | switches from 20/20/60 to a straight mean | move, on every past session |
    | revises a first-term result (task 8) | move, after the card went home |
    | corrects a placement for a term long closed | gain or lose a whole term |

    None of those are misuse. Every one of them silently rewrites a number a
    parent is holding, and the last line of a report card is the one they read
    first. So the terms' averages, the weighting actually applied and the
    result are copied here, and a released session line is rendered from this
    row and nothing else.

    ## The weighting recorded is the one applied, not the one configured

    A child who sat two terms had the school's weights **renormalised** over the
    terms they actually sat, so `SessionSettings`' configured pair is not what
    produced this number and recording it would misdescribe the arithmetic.
    The `*_weight_used` columns hold what was applied, and they sum to a
    hundred across the present terms — except where the school weights every
    term this child sat at nothing, where they are all `0.00` and there is no
    session average to have weighted. See the columns below.

    They are the weighting **as applied, rounded to two places for reading**,
    and the average is not recomputed from them: it is calculated at full
    precision and rounded once, so a straight mean of three terms is a true
    third each rather than 33.33/33.33/33.34. Recomputing from the stored pair
    can therefore differ in the last penny, and that is the deliberate trade —
    a session average that decides promotions should be the exact mean, not the
    mean of three rounded weights. What the row is a record of is *the
    weighting*, which is what a school changing its mind next session must not
    be able to alter.

    ## An absent term says why

    Not merely that it is absent. `TermAbsence` has the argument; the short
    version is that a marking backlog and a mid-session transfer produce
    identical arithmetic and need opposite responses from staff.
    """

    sheet = models.ForeignKey(
        ResultSheet,
        related_name="released_session_results",
        # PROTECT, like every other frozen table here: the sheet whose release
        # wrote this row is not one to delete from under it.
        on_delete=models.PROTECT,
    )

    student_membership_id = models.PositiveBigIntegerField(db_index=True)

    #: Copied off the term rather than reached through `sheet.term.session`, so
    #: the row answers "which year is this?" without a join — and goes on
    #: answering it if a term is ever re-labelled.
    session = models.CharField(max_length=9)

    #: Each term's own overall average, as `positions.overall_percentages()`
    #: read it at release. Null exactly when the term contributed nothing, in
    #: which case the matching `*_absence` says why and `*_weight_used` is null
    #: too — `the_*_term_is_present_or_explained` enforces the three agreeing.
    first_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    second_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    third_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    first_absence = models.CharField(max_length=16, choices=TermAbsence, blank=True)
    second_absence = models.CharField(max_length=16, choices=TermAbsence, blank=True)
    third_absence = models.CharField(max_length=16, choices=TermAbsence, blank=True)

    #: The weighting **actually applied**, after renormalising over the terms
    #: the child sat. Sums to 100 across the present terms; all three are null
    #: when the child sat none; and all of the present ones are `0.00` when the
    #: school weights every term this child sat at nothing, which is the one
    #: case with no session average beside a recorded weighting. See
    #: `sessions._weigh()`.
    first_weight_used = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    second_weight_used = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    third_weight_used = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    #: The school's mode at release, copied for the same reason the weights are.
    averaging = models.CharField(max_length=16, choices=SessionAveraging)

    #: Null when the child sat no term of this session with any mark in it.
    #: A card printing a blank there is the honest rendering, and it is the
    #: reason this is nullable rather than defaulted to zero.
    session_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Local columns only. `ResultSheet.Meta.ordering` names two relations
        # and has cost this codebase a three-table join in four separate
        # places; nothing here reaches past its own row.
        ordering = ["sheet_id", "student_membership_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sheet", "student_membership_id"],
                name="one_frozen_session_line_per_student",
            ),
            _a_term_is_present_or_explained("first"),
            _a_term_is_present_or_explained("second"),
            _a_term_is_present_or_explained("third"),
            # There is an average exactly when some term carried weight. Both
            # directions matter: an average with nothing behind it is the
            # arithmetic having invented a number, and a term weighted 60 with
            # no average is one the arithmetic dropped.
            #
            # **Weight above zero, not weight recorded.** A term the school
            # counts for nothing is recorded with a `0.00` weight rather than a
            # null — it was sat, it was marked, and the weight applied to it
            # was nought, which is a different fact from "no such term" and the
            # `*_absence` column is where that one is said. So a child whose
            # every sat term is weighted nothing has three weights on the row
            # and no average, and reading "is any weight recorded?" would call
            # that row a lie. Migration `0014` has the release this refused.
            models.CheckConstraint(
                condition=(
                    (
                        Q(session_average__isnull=False)
                        & (
                            _the_term_carried_weight("first")
                            | _the_term_carried_weight("second")
                            | _the_term_carried_weight("third")
                        )
                    )
                    | (
                        Q(session_average__isnull=True)
                        & _the_term_carried_nothing("first")
                        & _the_term_carried_nothing("second")
                        & _the_term_carried_nothing("third")
                    )
                ),
                name="a_session_average_has_a_term_behind_it",
            ),
            models.CheckConstraint(
                condition=Q(session_average__isnull=True)
                | (Q(session_average__gte=0) & Q(session_average__lte=100)),
                name="a_frozen_session_average_is_a_percentage",
            ),
        ]

    def __str__(self):
        shown = "—" if self.session_average is None else f"{self.session_average}"
        return f"{self.session}: {shown}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise SessionResultsAreFrozenAtRelease(
                f"Frozen session line {self.pk} is part of a card that has been "
                f"released. It cannot be changed — correcting a released result "
                f"is a revision, which makes a new version and leaves this one "
                f"standing."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise SessionResultsAreFrozenAtRelease(
            f"Frozen session line {self.pk} cannot be deleted. The card has to "
            f"keep saying what it said."
        )


class PromotionDecisionsAreAppendOnly(Exception):
    """A decision row was edited or deleted. See `PromotionDecision`."""


class PromotionDecision(models.Model):
    """One recorded decision about one child's year. Written once, never changed.

    ## Undecided is the absence of a row

    There is no `UNDECIDED` status and no current-status column anywhere. A
    child nobody has decided about has no row here, and every reader has to
    handle that — which is the point. The alternative, a status column
    defaulting to something, is a school-wide promotion performed by a default
    value: a principal who reviews nothing would promote four hundred children
    without an act, and the audit would show it as decided.

    ## Suggested and recorded are two columns, and the gap between them is the record

    `suggested` is what the arithmetic proposed; `status` is what a person
    decided. They are usually equal and the interesting rows are the ones where
    they are not — a child the numbers promote and the school holds back, or
    the reverse.

    **`suggested` is stored, not recomputed on read**, and that is load-bearing.
    It is a function of the session average, which is a function of a weighting
    the school may change. Recompute it and the same row reads as agreement or
    override depending on when it is asked: a school switching from 20/20/60 to
    a straight mean would retroactively invent overrides no principal ever
    performed, on exactly the rows kept to prove who decided what. So the
    suggestion is frozen with the two things that produced it — the session
    average and the pass mark in force — and the row can be read on its own.

    The *weighting* behind that average is deliberately not copied here. It
    lives on `ReleasedSessionResult`, which is where the arithmetic is
    auditable; this row's job is to explain the suggestion, and the average is
    the suggestion's whole input. Copying the weights too would put a second
    answer to "how was this year averaged?" in a table that is not the
    authority on it.

    ## Append-only, and the latest row wins

    A principal changing their mind writes a second row; both stand. That is
    the approval chain's argument reused: a decision record that edits itself
    has silently forgotten that it was ever different, who changed it and when,
    which is the one thing an appeal from a parent turns on.

    Enforced the two ways this codebase always does it — `save()` and
    `delete()` refuse, which is the error a developer sees, and a trigger
    refuses, which is the error the import and the `psql` session run into.
    """

    student_membership_id = models.PositiveBigIntegerField()

    #: The session decided about, as `Term.session` spells it. A string rather
    #: than a key, because `Term` is per-term and a session is three of them —
    #: there is no session row to point at, which is the same reason
    #: `Term.session` is a string in the first place.
    session = models.CharField(max_length=9)

    #: What the school decided. This is the only column that prints.
    status = models.CharField(max_length=16, choices=PromotionStatus)

    #: What the arithmetic proposed at the moment of the decision. Blank when
    #: no suggestion could be made — a child with no marks in any term of the
    #: session has no average, so there is nothing to compare to a pass mark,
    #: and blank says that rather than guessing `REPEATED`.
    suggested = models.CharField(max_length=16, choices=PromotionStatus, blank=True)

    #: The two inputs to `suggested`, frozen beside it. Null together with a
    #: blank `suggested`.
    session_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    pass_mark_used = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    #: Why, in the principal's words. Not required — most decisions agree with
    #: the suggestion and need no explanation — but the place an override says
    #: what it saw that the arithmetic did not.
    note = models.TextField(blank=True)

    # A bare id, and nullable, for `TraitRating.rated_by_id`'s reasons: a
    # decision can arrive from an import of last year's records with nobody
    # behind it, and naming a fictional principal is worse than naming none.
    #
    # **This holds a `User` id, not a `Membership` id** — `decide_as()` stamps
    # the actor, and the actor is a user. The column above holds a membership
    # id, and both are small dense integers, so a screen resolving the wrong
    # one would confidently name an unrelated person rather than fail.
    decided_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first, and `-id` is not decoration: `auto_now_add` is a
        # timestamp, two decisions in one request can share it to the
        # microsecond, and "the latest decision" resolving arbitrarily between
        # two rows is a promotion status that changes when nothing changed.
        ordering = ["student_membership_id", "session", "-decided_at", "-id"]
        indexes = [
            # The read this table exists for: the latest row for one child in
            # one session. Leading pair is the lookup, and the descending tail
            # is the ordering, so the index answers both halves.
            models.Index(
                fields=["student_membership_id", "session", "-decided_at", "-id"],
                name="the_latest_decision_per_child",
            ),
        ]
        constraints = [
            # Deliberately **no** unique constraint on (student, session): more
            # than one row is the feature, not a fault.
            models.CheckConstraint(
                condition=(
                    Q(suggested="", session_average__isnull=True, pass_mark_used__isnull=True)
                    | (
                        ~Q(suggested="")
                        & Q(session_average__isnull=False, pass_mark_used__isnull=False)
                    )
                ),
                name="a_suggestion_carries_what_produced_it",
            ),
            models.CheckConstraint(
                condition=Q(session_average__isnull=True)
                | (Q(session_average__gte=0) & Q(session_average__lte=100)),
                name="a_decided_session_average_is_a_percentage",
            ),
        ]

    def __str__(self):
        return f"{self.session}: {PromotionStatus(self.status).label}"

    @property
    def overrode_the_suggestion(self) -> bool:
        """Did a person decide against the arithmetic? Staff-only, like position.

        Blank `suggested` is not an override: nothing was proposed, so nothing
        was gone against.
        """
        return bool(self.suggested) and self.suggested != self.status

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise PromotionDecisionsAreAppendOnly(
                f"Promotion decision {self.pk} has been recorded and cannot be "
                f"changed. Record a new decision instead — both stand, and the "
                f"later one is what holds."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PromotionDecisionsAreAppendOnly(
            f"Promotion decision {self.pk} cannot be deleted. A record of who "
            f"decided what has to keep saying it."
        )
