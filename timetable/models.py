"""The school's periods, and who teaches what in each of them. T1.

Decided 2026-09-24:

- **One bell schedule per school** — `Period`, a start and an end. The same
  periods every weekday. A break is the gap between two periods, not a row.
- **A timetable per term**: for each class, each weekday and each period, a
  subject and a teacher — `TimetableSlot`. A double period is two slots; a free
  period is no slot at all.
- **A clash is refused unless it is the same subject.** A teacher may stand in
  front of two classes at once only when both are having the same lesson — a
  combined class. Two different lessons at once is a clash, and the database
  refuses it (`a_teacher_teaches_one_subject_at_a_time`).
- Copying last term's timetable is `services.copy_last_term()`.

The timetable is **the record of who teaches which subject to which class**
(timetable decision 4(a)), which is what #142 will gate marks entry on.

It is a working record, not a released artefact: a school corrects it in
place, and nothing here freezes. The teacher is a bare membership id, as every
tenant table's reference into `accounts` is (docs/tenancy.md); `subject`,
`term`, `class_group` and `period` are tenant tables in the same schema, so
they are real foreign keys, and `PROTECT` there really does protect.
"""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import DateTimeField, Func, Q

from academics.models import ClassGroup, Term
from gradebook.models import Subject


class Weekday(models.IntegerChoices):
    """Monday to Friday. The school week this platform schedules; a Saturday
    lesson would be a sixth value and a change to `a_weekday_is_a_school_day`,
    not a second table."""

    MONDAY = 1, "Monday"
    TUESDAY = 2, "Tuesday"
    WEDNESDAY = 3, "Wednesday"
    THURSDAY = 4, "Thursday"
    FRIDAY = 5, "Friday"


class ClockSpan(Func):
    """`[starts_at, ends_at)` as a `tsrange` on one fixed day, so two periods
    can be compared with `&&`.

    Postgres has no range type over `time`. Pinning both ends to the same
    arbitrary date makes a `tsrange` whose overlap is exactly the overlap of the
    two times, and a range needs no `btree_gist` to be excluded on.

    A subclass with class attributes, not a `Func(...)` built with `template=`,
    for the reason `academics.models.DaysBetween` gives: as `**extra` the
    template would enter the expression's identity, and `makemigrations` would
    propose rebuilding the constraint on every run.
    """

    template = "tsrange(DATE '2000-01-03' + %(expressions)s, '[)')"
    arg_joiner = ", DATE '2000-01-03' + "
    output_field = DateTimeField()


class Period(models.Model):
    """One period in the school's day: when it starts and when it ends.

    Ordered by when it starts; there is no stored number, because a number
    would be a second answer to "which comes first" that could disagree with
    the clock. A school that adds an early-morning period does not renumber
    anything.
    """

    starts_at = models.TimeField()
    ends_at = models.TimeField()
    #: What the school calls it, if anything — "Period 1", "Assembly". Printed
    #: beside the times; never used to order or to match.
    label = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="a_period_ends_after_it_starts",
            ),
            # Two periods at once would be two answers to "what is on now".
            ExclusionConstraint(
                name="periods_do_not_overlap",
                expressions=[(ClockSpan("starts_at", "ends_at"), RangeOperators.OVERLAPS)],
            ),
        ]

    def __str__(self):
        times = f"{self.starts_at:%H:%M}–{self.ends_at:%H:%M}"
        return f"{self.label} ({times})" if self.label else times


class TimetableSlot(models.Model):
    """One lesson: this class, this term, this weekday and period — this
    subject, taught by this teacher."""

    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="+")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, related_name="+")
    weekday = models.PositiveSmallIntegerField(choices=Weekday)
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="slots")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="+")
    #: The teacher's TEACHER membership at this school. A bare id, checked by
    #: `accounts.students.why_not_a_teacher_here()` before it is written.
    teacher_membership_id = models.PositiveBigIntegerField(db_index=True)

    set_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["term", "class_group", "weekday", "period__starts_at"]
        constraints = [
            # A class has one lesson at a time. A double period is two of
            # these, one per period; a free period is none.
            models.UniqueConstraint(
                fields=["term", "class_group", "weekday", "period"],
                name="one_lesson_per_class_per_slot",
            ),
            models.CheckConstraint(
                condition=Q(weekday__gte=Weekday.MONDAY) & Q(weekday__lte=Weekday.FRIDAY),
                name="a_weekday_is_a_school_day",
            ),
            # The clash rule. Two rows conflict when they share the term, the
            # weekday, the period and the teacher **and differ in subject** —
            # so the same teacher in two classes at once is refused unless it
            # is one lesson taught to both (a combined class). `<>` on an
            # integer needs `btree_gist`, which migration 0001 installs into
            # `public` once for every school.
            ExclusionConstraint(
                name="a_teacher_teaches_one_subject_at_a_time",
                expressions=[
                    ("term", RangeOperators.EQUAL),
                    ("weekday", RangeOperators.EQUAL),
                    ("period", RangeOperators.EQUAL),
                    ("teacher_membership_id", RangeOperators.EQUAL),
                    ("subject", RangeOperators.NOT_EQUAL),
                ],
            ),
        ]

    def __str__(self):
        return (
            f"{self.term} {self.class_group} {self.get_weekday_display()} "
            f"{self.period}: {self.subject}"
        )


__all__ = ["ClockSpan", "Period", "TimetableSlot", "Weekday"]
