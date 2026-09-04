"""Scores a teacher enters, and the two states people confuse.

Tenant-scoped, like `academics` and `fees`: a school's marks are its own.

The whole model turns on one distinction that a gradebook gets wrong by
default. **"Not marked yet" and "scored zero" are different facts**, and a
schema that cannot tell them apart will average them together and print a
number on a report card that nobody can defend. So a `Score` row exists *if and
only if* a teacher has entered a value:

- `value` is `NOT NULL`. There is no such thing as a blank score row.
- Nothing pre-creates rows. Opening a sheet for a class of thirty writes
  nothing; the thirty students with no mark are absent from the table, not
  present with a null.
- Clearing a score deletes the row, rather than writing a zero or a null.

The naive implementation — materialise a row per student when the assessment is
created, fill them in later — is what makes the two states indistinguishable,
and it also makes "how many are still to be marked?" unanswerable.

Two more properties are enforced here rather than left to a screen:

**No total is ever stored.** A total that lives in a column is a total that can
be stale, and "refresh before display" is a rule somebody eventually forgets.
`ScoreQuerySet.total_for()` aggregates on read, exactly as
`fees.FeeLedgerQuerySet.balance()` does, so there is nothing to refresh and
nothing to forget. A test asserts no model here has a stored total.

**Every score carries a `version`.** Two teachers with the same sheet open is
the ordinary case, not an exotic one, and a last-write-wins update silently
discards one of them. `services.set_score()` writes conditionally on the version
it was shown, so the second writer is refused and can be told what changed.
"""

from django.db import models
from django.db.models import Q, Sum


class Subject(models.Model):
    """One thing a school teaches. Per school, because curricula differ."""

    name = models.CharField(max_length=100)
    #: What the school calls it on a timetable — "MTH", "ENG". Its own field
    #: rather than a slug of the name, because schools have their own codes and
    #: a generated one would fight them.
    code = models.CharField(max_length=16)
    is_active = models.BooleanField(
        default=True,
        help_text="A subject no longer taught. Kept, because old scores name it.",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uniq_subject_code"),
            models.UniqueConstraint(fields=["name"], name="uniq_subject_name"),
        ]

    def __str__(self):
        return self.name


class Assessment(models.Model):
    """A thing that was scored: a CA, a mid-term test, an exam.

    Belongs to a (term, subject). Deliberately *not* to a class or a stream.
    Who was scored is answered by which students have a `Score`, which is
    enough for a sheet and a total.

    **The original reason for that has expired; the decision has not.** This
    said "there is no class model in this project yet", and `academics.ClassGroup`
    arrived two days later — read alone, it now sounds like an invitation to add
    a class group here. It is not one. One paper is sat by every class taught
    the subject, which is why `results.positions` builds a broadsheet by taking
    every assessment for the term and slicing it by the class's roster; that
    slice is only necessary because assessments span classes. Class-scoping this
    would fragment one paper into a row per arm, make that slice redundant, and
    leave every existing row needing a value nothing could supply.

    The cost is that a `Score` reaches a class only through
    `academics.ClassPlacement`, which is why `services._require_the_sheet_is_open()`
    joins the placement and inherits the hole that join carries. See
    [issue #27](https://github.com/adedejimakinde/luffy-school-saas/issues/27).
    """

    # Both tenant-local, so both are real foreign keys with real integrity.
    # The cross-schema problem docs/tenancy.md describes does not arise between
    # two tables in the same schema — see fees/models.py for the same note.
    term = models.ForeignKey(
        "academics.Term", related_name="assessments", on_delete=models.PROTECT
    )
    subject = models.ForeignKey(
        Subject, related_name="assessments", on_delete=models.PROTECT
    )
    name = models.CharField(max_length=64, help_text='e.g. "First CA", "Exam".')

    #: Where it prints on the card, smallest first. **Explicit, never
    #: alphabetical** — `name` sorts "Exam, First CA, Second CA", which is
    #: neither the order the papers were sat nor the order a Nigerian report
    #: card prints its columns in. Issue #42.
    #:
    #: The same shape as `results.Trait.position`, including the part that looks
    #: like an oversight: deliberately **not** unique per `(term, subject)`. A
    #: unique constraint there reads tidier and makes the ordinary edit — swap
    #: two papers round — impossible without a temporary value or a deferred
    #: constraint. Duplicates are legal and `Meta.ordering` breaks the tie, so
    #: two papers sharing a position still print in the same order every time.
    #:
    #: Existing rows were numbered by creation order in `0003`, in tens. The
    #: gaps are so that a paper can be inserted between two others without
    #: renumbering the rest.
    position = models.PositiveSmallIntegerField(default=0)

    #: What a perfect score is. Stored per assessment rather than assumed to be
    #: 100, because a CA is commonly out of 20 or 30 and a total that treated
    #: it as a percentage would be wrong by a factor of five.
    max_score = models.PositiveSmallIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # `position` ahead of `name`, which is the whole of issue #42: the last
        # component used to be alphabetical. `id` last so the order is total —
        # `position` is not unique and two papers sharing one, with the same
        # name across subjects, could otherwise swap places between two reads
        # of the same card. `results.Trait.Meta` ends the same way, for the
        # same reason.
        ordering = ["term", "subject__name", "position", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["term", "subject", "name"],
                name="uniq_assessment_term_subject_name",
            ),
            # Zero is not a mark scheme. Guarded because `max_score` is the
            # denominator of every percentage this data produces, and a zero
            # there is a division error somewhere far away from here.
            models.CheckConstraint(
                condition=Q(max_score__gte=1),
                name="an_assessment_is_worth_at_least_one_mark",
            ),
        ]

    def __str__(self):
        return f"{self.subject} — {self.name} ({self.term})"


class ScoreQuerySet(models.QuerySet):
    def for_student(self, membership_id):
        return self.filter(student_membership_id=membership_id)

    def for_term(self, term):
        return self.filter(assessment__term=term)

    def for_subject(self, subject):
        return self.filter(assessment__subject=subject)

    def total_for(self, membership_id) -> dict:
        """What this student scored across these assessments, computed now.

        Returns `{"scored": int, "available": int, "marked": int}` — the marks
        earned, the marks that were on offer *for the assessments they were
        actually marked on*, and how many that was.

        Computed on read and never stored, which is the whole point. A total in
        a column is a total that can be stale, and "refresh it before display"
        is a rule that holds until the day somebody adds a second write path.
        There is nothing here to refresh.

        `available` counts only assessments this student has a score for, on
        purpose. Summing every assessment's `max_score` would silently treat
        "not marked yet" as zero — the exact conflation this module exists to
        prevent — and would drop a child's percentage every time a teacher
        created next week's test.
        """
        totals = self.for_student(membership_id).aggregate(
            scored=Sum("value"),
            available=Sum("assessment__max_score"),
            marked=models.Count("id"),
        )
        return {
            # `Sum` over no rows is NULL, and NULL is not a total: a caller
            # adding it to another number gets a TypeError, and one rendering
            # it prints "None".
            "scored": totals["scored"] or 0,
            "available": totals["available"] or 0,
            "marked": totals["marked"] or 0,
        }


class Score(models.Model):
    """One student's mark on one assessment. Exists only once entered."""

    assessment = models.ForeignKey(
        Assessment, related_name="scores", on_delete=models.PROTECT
    )

    # A bare id, not a ForeignKey, pointing at the student's STUDENT membership
    # in the shared `accounts` app. This follows the policy settled in
    # docs/tenancy.md and first applied by `fees.FeeLedgerEntry`: a tenant table
    # does not reach into `public`, because `on_delete` is resolved against
    # whichever schema the connection is on, so `PROTECT` does not protect and
    # `CASCADE` cascades one school's rows only.
    #
    # `gradebook.services` checks the id names a student *of this school* before
    # anything is written — the check that earns the bare id, and one a foreign
    # key could not have made anyway, since `Membership` is shared and every
    # school's students are in that one table.
    student_membership_id = models.PositiveBigIntegerField(db_index=True)

    #: NOT NULL, and that is the load-bearing line in this file. A nullable
    #: score would let a row mean "no mark yet", which is the conflation the
    #: module docstring is about. Clearing a mark deletes the row.
    value = models.PositiveSmallIntegerField()

    #: Bumped on every write that changes the value. A client is handed this
    #: with the sheet and must hand it back to save; a write carrying a stale
    #: one is refused rather than silently overwriting whoever moved first.
    #: See `services.set_score()`.
    version = models.PositiveIntegerField(default=1)

    # Bare ids again, same reasoning. Nullable because a score can arrive from
    # an import with no person behind it, and naming a fictional one is worse.
    recorded_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    updated_by_id = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScoreQuerySet.as_manager()

    class Meta:
        ordering = ["assessment", "student_membership_id"]
        indexes = [
            models.Index(fields=["assessment", "student_membership_id"]),
        ]
        constraints = [
            # One mark per student per assessment. Also the backstop for the
            # create race: two teachers entering the first score for the same
            # child at the same instant both find no row and both insert, and
            # this is what stops the second one succeeding. `set_score()` turns
            # the resulting IntegrityError into the same "somebody changed this"
            # answer an update conflict gets.
            models.UniqueConstraint(
                fields=["assessment", "student_membership_id"],
                name="one_score_per_student_per_assessment",
            ),
            # A mark cannot exceed what the assessment was out of. Not a
            # formatting nicety: `max_score` is the denominator of every
            # percentage downstream, so a value above it produces a mark over
            # 100% that no report card can explain.
            #
            # A cross-row rule — it compares `Score` to its `Assessment` — so no
            # check constraint can express it and it lives in `clean()` and in
            # `services.set_score()`. Recorded here so the absence reads as a
            # decision rather than an oversight.
        ]

    def __str__(self):
        return f"{self.value}/{self.assessment.max_score} on {self.assessment}"

    @property
    def out_of(self) -> int:
        return self.assessment.max_score

    def clean(self):
        """The rule a check constraint cannot express, because it spans rows."""
        from django.core.exceptions import ValidationError

        if self.assessment_id is None or self.value is None:
            return
        if self.value > self.assessment.max_score:
            raise ValidationError(
                {
                    "value": (
                        f"{self.assessment.name} is out of "
                        f"{self.assessment.max_score}; {self.value} is more than "
                        f"that."
                    )
                }
            )
