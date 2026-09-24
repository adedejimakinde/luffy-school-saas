"""The register: the fact one was taken, and one child's entry in it.

**Two tables, and that is the decision this module turns on.** A single table
keyed on `(student, date)` cannot tell "nobody took a register" from "a
register was taken and this child was somehow skipped" — a missing row means
both, and the ambiguity is unresolvable afterwards. `results.TermAbsence`
already made this decision for session averages and made it in these words:
collapsing the causes into a bare `None` "would make a marking backlog look
exactly like a mid-session transfer". Here the same conflation would report a
school's own admin gap as a child's truancy, on a card that goes home to that
child's parents.

So `Register` is the fact somebody took one, and `AttendanceMark` hangs off it.
It is the shape this codebase already uses twice for the same reason:
`ResultSheet` exists before any `Score` does, and `ReleasedCard` before any
`ReleasedSubjectResult`.

Neither table is append-only, and that is also deliberate. A teacher who marks a
child absent and then watches her walk in must be able to fix it; a register
corrected on the day is a register, not a falsified record. What must not move
is the *card*, and the card does not move — `results.ReleasedCard` is
append-only at two layers and the attendance numbers are frozen into it at
release. Immutability belongs to the artefact, which is the rule
`docs/results.md` sets for every other section of a card. See `docs/attendance.md`.
"""

from django.db import models
from django.db.models import Q


class AttendanceStatus(models.TextChoices):
    """What a register says about one child. Two entries, and that is on purpose.

    **This is not a claim that schools keep only two.** It is the observation
    that adding `LATE` or `EXCUSED` is one entry here plus a migration, while
    deciding whether a late child counts toward `days_present` is *arithmetic on
    a number a parent reads* — and that decision cannot be made well by
    guessing. Shipping four statuses now would ship a guess about the card's
    arithmetic and discover it was wrong after cards had gone home. A2 in
    `docs/attendance.md` is the question that settles it, and it has not been
    put to a school yet.

    The third state is structural rather than a status, which is why it is not
    here: a child with no `AttendanceMark` in a register was not marked, and a
    day with no `Register` at all was not taken. Neither is an absence, and a
    `NOT_MARKED` member would invite exactly the row that says otherwise.
    """

    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"


class RegisterQuerySet(models.QuerySet):
    def for_term(self, term):
        return self.filter(term=term)

    def on_day(self, class_group, on):
        """This group's register for this date. At most one, by constraint."""
        return self.filter(class_group=class_group, taken_on=on)


class Register(models.Model):
    """One group, one date: the fact that somebody marked.

    ## It carries the class group rather than looking one up

    `academics.ClassPlacement` is **current state, not history**.
    `academics.services.move_student()` mutates `class_group` on the existing
    row and saves it, `remove_placement()` deletes the row outright, and
    `one_class_placement_per_student_per_term` is the constraint that forces
    that shape. A child who moves from JSS 1A to JSS 1B in January leaves
    nothing behind saying where she sat in November.

    So the group is stored here, at the moment the register is taken. Resolving
    it through `ClassPlacement` at read time would file that child's first-half
    attendance under her second-half class — silently, months later, against a
    number already printed on a card. `ClassPlacement` is still exactly the
    right read for *whom to show the teacher*; it is the wrong read for what a
    register meant afterwards.

    ## The term is stored, not derived from the date

    Nothing prevents two `Term` rows overlapping. The constraints on `Term` are
    that it ends after it starts, that the next term begins after this one ends,
    and that `school_days` fits inside the span — none of which makes a date
    resolve to exactly one term. Deriving it would be a range query per read
    that is also not guaranteed to give one answer, and the summary that feeds a
    report card groups on precisely this column.

    ## One register a day, and the day's verdict is that register

    This table carried a `period` ordinal when it was built, for a design that
    stored per period and showed per day. A1 settled the grain **after** the
    code existed — attendance is marked once a day — and the column went with
    it.

    **The forward-compatibility argument for keeping it did not survive being
    looked at.** It was that grain cannot be retrofitted onto history. True, and
    beside the point: under a once-a-day practice nothing writes a second
    period, so every row would carry the same `1` and the column would hold no
    history to lose. Re-adding it is therefore lossless — the value every
    existing row needs is exactly the default — which is what makes dropping it
    the cheap direction rather than the brave one, and what makes it safe to do
    on an assumption the school has not confirmed.

    Nothing in this repository models a school day, a period, a timetable or a
    lesson, and now nothing gestures at one either. What replaces the rollup
    rule is the constraint below: a day has at most one register, so the day's
    verdict *is* that register — held by Postgres rather than by a function
    somebody has to remember to call. See `docs/attendance.md` D4, which was
    rewritten rather than deleted.
    """

    class_group = models.ForeignKey(
        "academics.ClassGroup", related_name="registers", on_delete=models.PROTECT
    )

    #: Stored rather than derived — see the class docstring. `PROTECT` for the
    #: reason every other relation into `academics` uses it: a term with
    #: registers under it is not a term anybody may delete by accident.
    term = models.ForeignKey(
        "academics.Term", related_name="registers", on_delete=models.PROTECT
    )

    #: The school day this register is for, which is **not** the day it was
    #: entered. A form teacher catching up on Friday for Wednesday is entering a
    #: Wednesday register, and `created_at` is where "when was this typed" lives.
    taken_on = models.DateField()


    #: A bare id pointing at the marker's membership in the shared `accounts`
    #: app — the policy `docs/tenancy.md` settles and `fees.FeeLedgerEntry`,
    #: `gradebook.Score`, `academics.ClassPlacement` and `academics.ClassTeacher`
    #: all follow: `on_delete` resolves against whichever schema the connection
    #: is on, so a real relation here would `PROTECT` nothing.
    #:
    #: Nullable for the reason `ReleasedCard.released_by_id` is: a register can
    #: arrive from an import with no person behind it, and naming a fictional
    #: one is worse than naming none.
    taken_by_id = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RegisterQuerySet.as_manager()

    class Meta:
        ordering = ["taken_on", "id"]
        # No `indexes` entry. The unique constraint below already builds a btree
        # led by `(class_group, taken_on)`, which is every read this table has —
        # one group's day, one group's term, and the existence check a second
        # take makes. A declared index on the same columns in the same order
        # would answer no query that constraint cannot, and would be a second
        # btree per tenant schema, one per school on the platform, maintained on
        # every insert for nothing. `academics.ClassTeacher.Meta` and
        # `results.ResultSheetTransition.Meta` record the same decision, and
        # `results.tests.test_ratings.NoIndexIsBuiltTwiceTests` is the rule.
        #
        # Django's automatic per-`ForeignKey` index on `term_id` stays, because
        # no constraint here leads with it. The one on `class_group_id` is a
        # strict prefix of the constraint and is redundant by the same argument
        # — it is left alone anyway, because turning a foreign key's index off
        # is a `db_index=False` decision about delete-time lookups that belongs
        # to the whole repository rather than to this table. That is issue #32.
        constraints = [
            # One register per group per day, and it does more work than it
            # looks like. It is the backstop for the race — two teachers opening
            # the same register and submitting at the same instant both find no
            # row and both insert, and this is what stops the second succeeding;
            # `services.take_register()` turns the resulting IntegrityError into
            # the amendment it actually was. It is *also* what makes the day's
            # attendance unambiguous, which used to be a named rollup rule and
            # is now a thing the database will not let be otherwise.
            models.UniqueConstraint(
                fields=["class_group", "taken_on"],
                name="one_register_per_group_per_day",
            ),
        ]

    def __str__(self):
        return f"{self.class_group} on {self.taken_on}"


class AttendanceMarkQuerySet(models.QuerySet):
    def for_term(self, term):
        return self.filter(register__term=term)

    def for_student(self, student_membership_id):
        return self.filter(student_membership_id=student_membership_id)


class AttendanceMark(models.Model):
    """One child's entry in one register.

    A row exists only once somebody marked, which is the same decision
    `gradebook.Score` records: a nullable status would let a row mean "not
    marked yet", and that is the conflation this module's docstring is about.
    Clearing a mark deletes the row rather than blanking it.
    """

    #: `PROTECT`, not `CASCADE`, and deliberately — the rest of this codebase
    #: protects every relation and deleting a register with marks under it
    #: should have to be meant. `services.discard_register()` is the path that
    #: takes both, in one transaction, in the right order.
    register = models.ForeignKey(
        Register, related_name="marks", on_delete=models.PROTECT
    )

    #: A bare id, not a `ForeignKey` — the `docs/tenancy.md` policy, and the
    #: sixth table to follow it. Unlike the others, nothing here checks the id
    #: with `accounts.students.why_not_a_student_here()`, and deliberately so:
    #: `take_register()` only ever writes ids that survive intersection with the
    #: roster, and the roster is `ClassPlacement`, whose rows
    #: `academics.services.place_student()` already checked. The comment above
    #: `take_register()` in `attendance/services.py` has the argument.
    student_membership_id = models.PositiveBigIntegerField(db_index=True)

    #: NOT NULL. See `AttendanceStatus` for why there is no third member and no
    #: null: "not marked" is the absence of this row, and "no register" is the
    #: absence of its parent.
    status = models.CharField(max_length=16, choices=AttendanceStatus.choices)

    #: Who marked this child, where `Register.taken_by_id` is who took the
    #: register. Usually the same person and not necessarily: a register
    #: amended a day later by the office is one row changed by somebody who did
    #: not take it, and a single column would lose that.
    marked_by_id = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AttendanceMarkQuerySet.as_manager()

    class Meta:
        ordering = ["register", "student_membership_id"]
        # No declared index, for the reason `Register.Meta` gives: the unique
        # constraint below leads with `register_id`, which is the read this
        # table has — one register's marks, and the `PROTECT` check asking
        # whether any mark references a register.
        constraints = [
            models.UniqueConstraint(
                fields=["register", "student_membership_id"],
                name="one_mark_per_student_per_register",
            ),
        ]

    def __str__(self):
        return (
            f"membership {self.student_membership_id} "
            f"{self.get_status_display().lower()} at {self.register}"
        )


class AbsenceSettings(models.Model):
    """What "too often absent" means at this school. One row per schema.

    Decided 2026-09-24 (OPEN-2): a child is on the principal's list when their
    absences are at least `threshold_percent` of the days they were **marked**,
    once at least `min_marked_days` have been. Unmarked days count for nothing —
    A4's rule, that a day with no register is not an absence — and the floor
    keeps a child marked twice and absent once from reading as 50%.

    A per-school setting because schools differ; defaults of 10% and 10 days.
    Pinned to `id = 1` like `results.ReportCardSettings`, and `load()` returns
    an unsaved default rather than writing on a read path.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    threshold_percent = models.PositiveSmallIntegerField(
        default=10, help_text="Absent on at least this share of the days marked."
    )
    min_marked_days = models.PositiveSmallIntegerField(
        default=10, help_text="Only once at least this many days have been marked."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(id=1), name="absence_settings_is_one_row"
            ),
            models.CheckConstraint(
                condition=Q(threshold_percent__gte=1) & Q(threshold_percent__lte=100),
                name="absence_threshold_is_a_percentage",
            ),
            models.CheckConstraint(
                condition=Q(min_marked_days__gte=1),
                name="absence_floor_is_at_least_one_day",
            ),
        ]

    @classmethod
    def load(cls):
        return cls.objects.filter(pk=1).first() or cls()

    def __str__(self):
        return f"{self.threshold_percent}% of at least {self.min_marked_days} marked days"
