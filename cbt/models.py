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


# -- Phase 2 step 3: question banks and tests -----------------------------------------
#
# `docs/cbt.md`, "Banks and questions" and "Tests". A bank is a school's own, per subject
# and class level; a test draws from one bank, for classes at that level, and its
# questions are **copied into it** when it is sent for approval (`TestItem`), so an edit
# to the bank never reaches a test somebody has reviewed (operating rule 2). The
# triggers that keep a set test as it was are in migration 0002, named for their rules.

#: The longest text each part of a question takes, read by the services and the
#: constraints alike (operating rule 3: one answer, not two that drift).
MAX_STEM = 1000
MAX_OPTION = 300
MAX_EXPLANATION = 1000
MAX_TOPIC = 60
MAX_IMAGE_ALT = 200
MAX_TITLE = 120
#: Marks one question may carry.
MAX_MARKS = 10
#: The late window's ceiling (`docs/cbt.md`, "Late window": default 2 minutes, at most 5).
MAX_LATE_WINDOW = 5
DEFAULT_LATE_WINDOW = 2
#: The longest a class test may give each student, in minutes.
MAX_DURATION = 300


class QuestionBank(models.Model):
    """The school's questions for one subject at one class level.

    "Level" is `ClassGroup.level`, the number the arms of one year share: JSS 2A and
    JSS 2B are one level, so a bank serves both. Unique on the pair, per school (each
    school's schema has its own table).

    Seen by its subject's teachers at that level this term (`gradebook.SubjectTeacher`,
    read through `cbt.access`), the vice principal (to read) and the principal. **Never
    by the administrator**, nor a bursar, a parent or a student (`docs/cbt.md`, "Who sees
    what"). Made the first time somebody writes a question into it.
    """

    subject = models.ForeignKey("gradebook.Subject", related_name="question_banks", on_delete=models.PROTECT)
    level = models.PositiveSmallIntegerField()
    created_by_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["level", "subject__name"]
        constraints = [
            models.UniqueConstraint(fields=["subject", "level"], name="one_question_bank_per_subject_and_level"),
        ]

    def __str__(self):
        return f"{self.subject} bank, level {self.level}"


class Question(models.Model):
    """One multiple-choice question: a stem, four or five options, one of them right.

    Plain text only (`docs/cbt.md`, "Left for later": typesetting). An optional picture
    is a `files.StoredFile` of kind `question_image`, named by its key and sent only by
    `cbt`'s own route, to those who may read this bank.

    **Saving makes a new version** (`version`), and a test already set keeps the copy
    it was given. A question a test has used is **retired, not deleted** (`retired_at`):
    `TestItem.origin_question` protects it, so old papers keep their questions.

    `source` is `school` for every question in this step. `provider` is designed and
    off (`docs/cbt.md`, "External question banks"): such a row refuses UPDATE in the
    database (`a_provider_question_is_read_only`), and nothing writes one.
    """

    class Source(models.TextChoices):
        SCHOOL = "school", "The school"
        PROVIDER = "provider", "A licensed provider"

    bank = models.ForeignKey(QuestionBank, related_name="questions", on_delete=models.PROTECT)
    stem = models.TextField()
    image_key = models.CharField(max_length=32, blank=True, default="")
    image_alt = models.CharField(max_length=MAX_IMAGE_ALT, blank=True, default="")
    explanation = models.TextField(blank=True, default="")
    topic = models.CharField(max_length=MAX_TOPIC, blank=True, default="")
    option_count = models.PositiveSmallIntegerField(default=4)
    correct_index = models.PositiveSmallIntegerField()
    marks = models.PositiveSmallIntegerField(default=1)
    version = models.PositiveIntegerField(default=1)
    retired_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=8, choices=Source, default=Source.SCHOOL)
    provider_slug = models.CharField(max_length=40, blank=True, default="")
    provider_ref = models.CharField(max_length=80, blank=True, default="")
    created_by_id = models.PositiveBigIntegerField()
    created_by_name = models.CharField(max_length=255)
    updated_by_id = models.PositiveBigIntegerField()
    updated_by_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["bank_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(option_count__in=[4, 5]), name="a_question_has_four_or_five_options"),
            models.CheckConstraint(
                condition=Q(correct_index__lt=models.F("option_count")),
                name="a_questions_answer_is_one_of_its_options",
            ),
            models.CheckConstraint(
                condition=Q(marks__gte=1, marks__lte=MAX_MARKS), name="a_question_carries_one_to_ten_marks"
            ),
            models.CheckConstraint(condition=Q(source__in=["school", "provider"]), name="a_question_is_the_schools_or_a_providers"),
            models.CheckConstraint(
                condition=Q(source="school", provider_slug="", provider_ref="") | Q(source="provider") & ~Q(provider_slug=""),
                name="only_a_provider_question_names_a_provider",
            ),
            models.CheckConstraint(condition=~Q(stem=""), name="a_question_has_a_stem"),
        ]

    @property
    def is_retired(self) -> bool:
        return self.retired_at is not None

    def __str__(self):
        return f"question {self.pk} v{self.version}: {self.stem[:40]}"


class QuestionOption(models.Model):
    """One option of a question, at its position (0 is A). The question's own, rewritten on save."""

    question = models.ForeignKey(Question, related_name="options", on_delete=models.CASCADE)
    position = models.PositiveSmallIntegerField()
    text = models.CharField(max_length=MAX_OPTION)

    class Meta:
        ordering = ["question_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["question", "position"], name="one_option_per_position"),
            models.CheckConstraint(condition=Q(position__lt=5), name="an_option_is_a_to_e"),
            models.CheckConstraint(condition=~Q(text=""), name="an_option_has_text"),
        ]

    def __str__(self):
        return f"{'ABCDE'[self.position]}. {self.text}"


class Test(models.Model):
    """A test a teacher sets for their classes, from one bank. `docs/cbt.md`, "Tests".

    **States.** `draft` while the teacher writes it; `submitted` once they send it for
    approval, when its questions are drawn from the bank and copied into `TestItem`;
    `published` once the principal approves it; `closed` after it (step 5). Sending it
    back, or the teacher withdrawing it, returns it to `draft` and discards the copy.
    Each move is a `TestStateChange` row, and the database refuses any other move.

    **Once it leaves draft, what the paper is cannot change** (trigger
    `a_set_test_keeps_its_paper`): the window, the time, the settings, the sign-in.
    Who sits it can (`TestAudience`), and every change is logged
    (`TestAudienceChange`).

    **Sign-in.** `require_pin` off means option A of `docs/cbt.md` ("Student sign-in"),
    and then `may_send_to_ca` is off too: the constraint
    `a_test_without_the_exam_pin_never_sends_to_ca` refuses the other combination.
    `code_digest` is the test code, set when the sitting starts (step 4); empty here.

    **CA.** Nothing here names a CA column: the teacher picks one when they send scores,
    after marking (`docs/cbt.md`, "How scores reach CA", step 5). No score is stored.
    """

    class Kind(models.TextChoices):
        CLASS = "class", "Class test"
        UTME_STYLE = "utme_style", "UTME-style practice"
        WASSCE_STYLE = "wassce_style", "WASSCE-style objectives"

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Waiting for approval"
        PUBLISHED = "published", "Approved"
        CLOSED = "closed", "Closed"

    title = models.CharField(max_length=MAX_TITLE)
    kind = models.CharField(max_length=16, choices=Kind, default=Kind.CLASS)
    term = models.ForeignKey(Term, related_name="tests", on_delete=models.PROTECT)
    state = models.CharField(max_length=16, choices=State, default=State.DRAFT)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    #: Minutes each student has, from when they start.
    duration = models.PositiveSmallIntegerField()
    #: Minutes an answer saved before time may take to arrive (0 turns it off).
    late_window = models.PositiveSmallIntegerField(default=DEFAULT_LATE_WINDOW)
    shuffle_questions = models.BooleanField(default=True)
    shuffle_options = models.BooleanField(default=True)
    can_go_back = models.BooleanField(default=True)
    grid = models.BooleanField(default=True)
    calculator = models.BooleanField(default=False)
    require_pin = models.BooleanField(default=True)
    may_send_to_ca = models.BooleanField(default=True)
    code_digest = models.CharField(max_length=64, blank=True, default="")
    created_by_id = models.PositiveBigIntegerField()
    created_by_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-opens_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=["class", "utme_style", "wassce_style"]), name="a_test_is_of_a_known_kind"
            ),
            models.CheckConstraint(
                condition=Q(state__in=["draft", "submitted", "published", "closed"]), name="a_test_is_in_a_known_state"
            ),
            models.CheckConstraint(condition=Q(closes_at__gt=models.F("opens_at")), name="a_test_closes_after_it_opens"),
            models.CheckConstraint(
                condition=Q(duration__gte=1, duration__lte=MAX_DURATION), name="a_test_gives_one_to_300_minutes"
            ),
            models.CheckConstraint(
                condition=Q(late_window__lte=MAX_LATE_WINDOW), name="a_late_window_is_at_most_five_minutes"
            ),
            models.CheckConstraint(
                condition=Q(require_pin=True) | Q(may_send_to_ca=False),
                name="a_test_without_the_exam_pin_never_sends_to_ca",
            ),
            models.CheckConstraint(condition=~Q(title=""), name="a_test_has_a_title"),
        ]

    def __str__(self):
        return f"{self.title} ({self.state})"


class TestSection(models.Model):
    """Where a test's questions come from: a bank and how many. One for a class test."""

    test = models.ForeignKey(Test, related_name="sections", on_delete=models.CASCADE)
    bank = models.ForeignKey(QuestionBank, related_name="sections", on_delete=models.PROTECT)
    question_count = models.PositiveSmallIntegerField()
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["test_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["test", "position"], name="one_test_section_per_position"),
            models.CheckConstraint(
                condition=Q(question_count__gte=1, question_count__lte=200),
                name="a_test_section_has_one_to_200_questions",
            ),
        ]


class TestAudience(models.Model):
    """One class that may sit a test. Added and removed; every change is a `TestAudienceChange`."""

    test = models.ForeignKey(Test, related_name="audience", on_delete=models.CASCADE)
    class_group = models.ForeignKey(ClassGroup, related_name="test_audiences", on_delete=models.PROTECT)

    class Meta:
        ordering = ["test_id", "class_group__level", "class_group__name"]
        constraints = [
            models.UniqueConstraint(fields=["test", "class_group"], name="a_class_is_in_a_tests_audience_once"),
        ]


class TestAudienceChange(models.Model):
    """A class added to or removed from a test, who did it and when. Append-only.

    Access is what this guards (`docs/cbt.md`, "TestAudience"): a removal leaves
    nothing in `TestAudience`, so its record has to be somewhere that cannot be removed
    (operating rule 8).
    """

    class Kind(models.TextChoices):
        ADDED = "added", "Added"
        REMOVED = "removed", "Removed"

    test = models.ForeignKey(Test, related_name="audience_changes", on_delete=models.PROTECT)
    class_group = models.ForeignKey(ClassGroup, related_name="test_audience_changes", on_delete=models.PROTECT)
    class_group_name = models.CharField(max_length=64)
    kind = models.CharField(max_length=8, choices=Kind)
    #: The test's state when the change was made: a change to a published test's
    #: classes is the one the page asks twice about.
    test_state = models.CharField(max_length=16)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["added", "removed"]), name="an_audience_change_adds_or_removes"),
        ]


class TestStateChange(models.Model):
    """One move of a test from state to state, who made it, when and why. Append-only.

    `from_state` as well as `to_state`, as `ResultSheetTransition` carries both
    (operating rule 4): the row says what it moved from without reading the one before.
    A send-back carries the reviewer's note.
    """

    test = models.ForeignKey(Test, related_name="state_changes", on_delete=models.PROTECT)
    from_state = models.CharField(max_length=16)
    to_state = models.CharField(max_length=16)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    note = models.CharField(max_length=200, blank=True, default="")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(from_state="draft", to_state="submitted")
                | Q(from_state="submitted", to_state="draft")
                | Q(from_state="submitted", to_state="published")
                | Q(from_state="published", to_state="closed"),
                name="a_test_moves_only_along_its_chain",
            ),
        ]


class TestItem(models.Model):
    """One question as a test carries it: **copied** from the bank when the test was sent
    for approval, and never changed after (trigger `a_published_item_is_frozen`).

    Text, options, answer, marks and picture are the copy's own (operating rule 2), so a
    bank edit, a retired question or a renamed topic never reaches a test already set.
    `origin_question` and `origin_version` say which question, at which version, it was
    copied from; the key protects that question from deletion.

    `correct_index` and `explanation` are **never** sent to a student's device
    (`cbt.paper.for_device()`).
    """

    test = models.ForeignKey(Test, related_name="items", on_delete=models.PROTECT)
    section = models.ForeignKey(TestSection, related_name="items", on_delete=models.PROTECT)
    position = models.PositiveSmallIntegerField()
    stem = models.TextField()
    image_key = models.CharField(max_length=32, blank=True, default="")
    image_alt = models.CharField(max_length=MAX_IMAGE_ALT, blank=True, default="")
    #: `["text of A", "text of B", ...]`, four or five, in the bank's order.
    options = models.JSONField()
    correct_index = models.PositiveSmallIntegerField()
    marks = models.PositiveSmallIntegerField()
    explanation = models.TextField(blank=True, default="")
    topic = models.CharField(max_length=MAX_TOPIC, blank=True, default="")
    attribution = models.CharField(max_length=200, blank=True, default="")
    origin_question = models.ForeignKey(Question, related_name="test_items", on_delete=models.PROTECT)
    origin_version = models.PositiveIntegerField()

    class Meta:
        ordering = ["test_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["test", "position"], name="one_test_item_per_position"),
            models.UniqueConstraint(fields=["test", "origin_question"], name="a_question_is_in_a_test_once"),
            models.CheckConstraint(
                condition=Q(marks__gte=1, marks__lte=MAX_MARKS), name="a_test_item_carries_one_to_ten_marks"
            ),
        ]

    def __str__(self):
        return f"item {self.position + 1} of test {self.test_id}"
