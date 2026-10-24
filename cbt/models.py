"""Computer-based tests: Phase 2 step 2, exam officers and the students' exam PINs.

`docs/cbt.md` is the design. What is here is the part a sitting needs before any test
exists: who besides the principal and the administrator may print exam slips (an exam
officer, named by the principal), and the PIN each slip carries, which `/sit/` will ask
for in step 4 beside the test code and the admission number.

Every table lives in the school's own schema. People are named by their platform-wide
membership id, a bare integer with no foreign key, as everywhere else
(`docs/tenancy.md`), and by their names as they read at the time (operating rule 2), so
the record survives a rename. Each "never changes" is a trigger in the migration named
for its rule (rule 3).
"""

from django.db import models
from django.db.models import Q

from academics.models import ClassGroup, Term


class ExamOfficerGrant(models.Model):
    """The principal names somebody an exam officer, or ends it. Append-only.

    **Not a role** (`docs/cbt.md`, "Settled in interpretation"): a permission held by a
    teacher, the vice principal or the administrator, so a membership keeps one role per
    school. The latest row for a membership decides (`access.officer_memberships()`):
    `named` makes them one, `ended` makes them one no longer. Nothing is ever edited or
    deleted, so the record of who named whom, and who ended it, is the table.

    An exam officer prints exam slips for any class in the school (decided 24 October
    2026). Step 4 adds extra time and retakes, step 6 cross-subject practice; nothing
    else, and never a bank: an exam officer's banks are their own as a teacher.
    """

    class Kind(models.TextChoices):
        NAMED = "named", "Named"
        ENDED = "ended", "Ended"

    membership_id = models.PositiveBigIntegerField(db_index=True)
    kind = models.CharField(max_length=8, choices=Kind)
    #: Their name and role here as they read when this row was written.
    membership_name = models.CharField(max_length=255)
    role = models.CharField(max_length=16)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    note = models.CharField(max_length=200, blank=True, default="")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=["named", "ended"]),
                name="an_exam_officer_grant_is_named_or_ended",
            ),
        ]

    def __str__(self):
        return f"{self.membership_name} {self.kind} exam officer by {self.by_name}"


class PinSlipPrint(models.Model):
    """One press of Print: a class's slips, or one student's. Append-only.

    The record of an act whose other effects are a set of digests nobody can read and
    the cancelling of earlier PINs (rule 8): who printed, when, for which class and
    term, how many slips came out, and how many live PINs it cancelled. The PDF itself
    is never kept; it is rendered in the request and handed over once.
    """

    class Kind(models.TextChoices):
        CLASS = "class", "A class"
        STUDENT = "student", "One student"

    term = models.ForeignKey(Term, related_name="pin_slip_prints", on_delete=models.PROTECT)
    class_group = models.ForeignKey(ClassGroup, related_name="pin_slip_prints", on_delete=models.PROTECT)
    class_group_name = models.CharField(max_length=64)
    kind = models.CharField(max_length=8, choices=Kind)
    #: The one student, for a lost slip; empty for a class.
    student_membership_id = models.PositiveBigIntegerField(null=True, blank=True)
    student_name = models.CharField(max_length=255, blank=True, default="")
    #: Slips printed, each with a new PIN.
    count = models.PositiveIntegerField()
    #: Live PINs this press cancelled.
    cancelled_count = models.PositiveIntegerField()
    #: Students on the roster with no admission number, who got no slip.
    without_a_number = models.PositiveIntegerField(default=0)
    printed_by_id = models.PositiveBigIntegerField()
    printed_by_name = models.CharField(max_length=255)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="class", student_membership_id__isnull=True)
                | Q(kind="student", student_membership_id__isnull=False),
                name="a_slip_print_is_a_class_or_one_named_student",
            ),
        ]

    def __str__(self):
        return f"{self.count} exam slips for {self.class_group_name} by {self.printed_by_name}"


class ExamPin(models.Model):
    """One student's exam PIN for one term, kept only as a keyed digest.

    Printed once, on the slip, and never stored: `digest` is an HMAC under a server
    secret (`settings.EXAM_PIN_KEY`) of the PIN bound to this school, this student and
    this term (`pins.digest()`), so a copy of the database alone cannot be searched for
    a PIN, and the same eight digits at two schools, or for two students, are two
    unrelated digests.

    **At most one live PIN per student per term** (`one_live_exam_pin_per_student_per_term`).
    A new slip cancels the old PIN in the same transaction (`pins.print_class_as()`,
    `pins.print_student_as()`). Cancelling is the one change a row ever takes, and only
    once, naming the print that did it; every other column is fixed at insert and the
    row is never deleted (`an_exam_pin_is_only_ever_cancelled`).
    """

    student_membership_id = models.PositiveBigIntegerField()
    term = models.ForeignKey(Term, related_name="exam_pins", on_delete=models.PROTECT)
    #: The class the slip was printed for, as it was then. A student who moves class
    #: keeps a working PIN until somebody prints again.
    class_group = models.ForeignKey(ClassGroup, related_name="exam_pins", on_delete=models.PROTECT)
    digest = models.CharField(max_length=64)
    issued_by_print = models.ForeignKey(PinSlipPrint, related_name="issued", on_delete=models.PROTECT)
    issued_by_id = models.PositiveBigIntegerField()
    issued_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_print = models.ForeignKey(
        PinSlipPrint, related_name="cancelled", null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        ordering = ["term_id", "student_membership_id", "-id"]
        indexes = [models.Index(fields=["term", "student_membership_id"])]
        constraints = [
            models.UniqueConstraint(
                fields=["student_membership_id", "term"],
                condition=Q(cancelled_at__isnull=True),
                name="one_live_exam_pin_per_student_per_term",
            ),
            models.CheckConstraint(
                condition=Q(cancelled_at__isnull=True, cancelled_by_print__isnull=True)
                | Q(cancelled_at__isnull=False, cancelled_by_print__isnull=False),
                name="a_cancelled_exam_pin_names_the_print_that_cancelled_it",
            ),
        ]

    @property
    def is_live(self) -> bool:
        return self.cancelled_at is None

    def __str__(self):
        state = "live" if self.is_live else "cancelled"
        return f"exam PIN for membership {self.student_membership_id}, term {self.term_id} ({state})"
