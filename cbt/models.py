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
    `published` once the principal or the vice principal approves it; `closed` after it (step 5). Sending it
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


# -- Phase 2 step 4: sitting a test ---------------------------------------------------
#
# `docs/cbt.md`, "Sitting", "Offline" and "Power cuts and resuming". A student signs in
# at `/sit/` with the test code, their admission number and their exam PIN, and sits
# one `Attempt`. Every time here is the **server's**. Each table is append-only, or
# takes exactly one change once (an attempt is closed once, a session ended once), and
# the triggers that hold that are in migration 0003, named for their rules (operating
# rule 3). **No score is stored**: marking is step 5, read from the answers on demand.

#: The most extra minutes one grant may give.
MAX_EXTRA_MINUTES = 120
#: A reason, for extra time, a retake, opening or closing a sitting by hand.
MAX_REASON = 200


class TestCodeChange(models.Model):
    """The test code set or changed: who and when. **Never the code itself.** Append-only.

    The code is kept only as `Test.code_digest` (`cbt.sittings.code_digest()`); changing
    it replaces the digest and writes this row (`docs/cbt.md`, "Change a test code"). A
    student already inside an attempt is not signed out: the code is a gate to start and
    to resume, not to continue.
    """

    test = models.ForeignKey(Test, related_name="code_changes", on_delete=models.PROTECT)
    #: `set` for the first, `changed` after.
    kind = models.CharField(max_length=8)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    role = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["set", "changed"]), name="a_test_code_is_set_or_changed"),
        ]


class SittingControl(models.Model):
    """A sitting opened or closed by hand, for one class of one test. Append-only.

    A sitting is a test open to a class. The test's window (`opens_at`, `closes_at`) is
    the plan and is never rewritten; a row here overrides it, and **the latest row for
    the (test, class) decides** whether that class's students can start. Closing never
    discards an answer: an attempt in progress goes on to its own deadline unless
    `end_attempts` says to end it now, and each attempt so ended is logged on it.
    """

    class Kind(models.TextChoices):
        OPENED = "opened", "Opened"
        CLOSED = "closed", "Closed"

    test = models.ForeignKey(Test, related_name="sitting_controls", on_delete=models.PROTECT)
    class_group = models.ForeignKey(ClassGroup, related_name="sitting_controls", on_delete=models.PROTECT)
    class_group_name = models.CharField(max_length=64)
    kind = models.CharField(max_length=8, choices=Kind)
    end_attempts = models.BooleanField(default=False)
    reason = models.CharField(max_length=MAX_REASON)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    role = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["opened", "closed"]), name="a_sitting_is_opened_or_closed"),
            models.CheckConstraint(condition=~Q(reason=""), name="a_sitting_opened_or_closed_by_hand_says_why"),
            models.CheckConstraint(
                condition=Q(kind="closed") | Q(end_attempts=False), name="only_a_close_ends_attempts"
            ),
        ]


class Attempt(models.Model):
    """One student's sitting of one test. `docs/cbt.md`, "Sitting".

    **Times are the server's.** `base_deadline` is fixed when they start:
    `min(started_at + duration, closes_at)`, or `started_at + duration` for a sitting
    opened by hand after the window closed. Extra time is never written here: the
    deadline a student has is `base_deadline` plus the minutes of their
    `TimeExtension` rows (`cbt.sitting.deadline_of()`), so the record of who gave how
    much, and why, is the only place it lives (operating rule 4).

    The paper's order is derived from `seed` (`cbt.paper.for_device()`), so a student who
    signs in again on another computer gets the same paper in the same order.

    **Closed once** (`an_attempt_is_closed_once`): `submitted_at` and `ended_by` go from
    empty to set together, once, and nothing else of the row ever changes; it is never
    deleted. One attempt per student per test, unless a `RetakeGrant` names the next
    number.
    """

    class EndedBy(models.TextChoices):
        STUDENT = "student", "The student submitted"
        CLOCK = "clock", "Time ran out"
        TEACHER = "teacher", "Ended when the sitting was closed"

    test = models.ForeignKey(Test, related_name="attempts", on_delete=models.PROTECT)
    student_membership_id = models.PositiveBigIntegerField()
    #: As they read when the attempt started (rule 2).
    student_name = models.CharField(max_length=255)
    admission_number = models.CharField(max_length=64)
    class_group = models.ForeignKey(ClassGroup, related_name="attempts", on_delete=models.PROTECT)
    class_group_name = models.CharField(max_length=64)
    number = models.PositiveSmallIntegerField(default=1)
    seed = models.CharField(max_length=32)
    started_at = models.DateTimeField()
    base_deadline = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.CharField(max_length=8, blank=True, default="")

    class Meta:
        ordering = ["test_id", "student_name", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["test", "student_membership_id", "number"], name="one_attempt_per_student_per_number"
            ),
            models.CheckConstraint(condition=Q(number__gte=1), name="an_attempt_number_starts_at_one"),
            models.CheckConstraint(
                condition=Q(base_deadline__gt=models.F("started_at")), name="an_attempt_ends_after_it_starts"
            ),
            models.CheckConstraint(
                condition=Q(submitted_at__isnull=True, ended_by="")
                | Q(submitted_at__isnull=False, ended_by__in=["student", "clock", "teacher"]),
                name="a_closed_attempt_says_how_it_ended",
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.submitted_at is None

    def __str__(self):
        return f"attempt {self.number} of {self.student_name} at test {self.test_id}"


class AttemptSession(models.Model):
    """One computer holding an attempt. **At most one open per attempt** (the partial
    unique index `one_computer_holds_an_attempt`). Signing in on a second computer ends
    this one (`ended_by = replaced`) in the same transaction.

    The device holds a random token in a cookie scoped to `/sit/`; only its digest is
    kept. `sync_offset_ms` is the server's clock minus the device's at sign-in, as the
    device measured it, kept so a teacher can see how far a seat's clock was out.
    `last_seen_at` is the latest heartbeat or sync: the server notes a gap in it as a
    `disconnect` on the attempt, and the gap, not this column, is the record.
    """

    class EndedBy(models.TextChoices):
        STUDENT = "student", "Not me"
        REPLACED = "replaced", "Another computer signed in"
        SUBMIT = "submit", "Submitted"
        CLOCK = "clock", "Time ran out"
        TEACHER = "teacher", "Ended when the sitting was closed"

    attempt = models.ForeignKey(Attempt, related_name="sessions", on_delete=models.PROTECT)
    token_digest = models.CharField(max_length=64, unique=True)
    #: A short description of the seat, from the browser, shown in the sitting log.
    seat = models.CharField(max_length=80, blank=True, default="")
    signed_in_at = models.DateTimeField()
    sync_offset_ms = models.IntegerField(default=0)
    last_seen_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.CharField(max_length=8, blank=True, default="")

    class Meta:
        ordering = ["attempt_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt"], condition=Q(ended_at__isnull=True), name="one_computer_holds_an_attempt"
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True, ended_by="")
                | Q(ended_at__isnull=False, ended_by__in=["student", "replaced", "submit", "clock", "teacher"]),
                name="an_ended_session_says_why",
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.ended_at is None


class TimeExtension(models.Model):
    """Extra minutes for one student, with a reason. Append-only. `docs/cbt.md`, "Extra time".

    Given before they start (`attempt` empty: it applies to their attempt `number` when
    it starts), while they sit, or after a power cut; never after the attempt is closed,
    which is a retake. It moves that student's deadline and nobody else's.
    """

    test = models.ForeignKey(Test, related_name="time_extensions", on_delete=models.PROTECT)
    student_membership_id = models.PositiveBigIntegerField()
    student_name = models.CharField(max_length=255)
    #: The attempt number it applies to.
    number = models.PositiveSmallIntegerField(default=1)
    attempt = models.ForeignKey(Attempt, related_name="extensions", null=True, blank=True, on_delete=models.PROTECT)
    minutes = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=MAX_REASON)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    role = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["test", "student_membership_id", "number"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(minutes__gte=1, minutes__lte=MAX_EXTRA_MINUTES), name="extra_time_is_1_to_120_minutes"
            ),
            models.CheckConstraint(condition=~Q(reason=""), name="extra_time_says_why"),
        ]


class RetakeGrant(models.Model):
    """A student may sit a test again, as attempt `number`, for a reason. Append-only."""

    test = models.ForeignKey(Test, related_name="retake_grants", on_delete=models.PROTECT)
    student_membership_id = models.PositiveBigIntegerField()
    student_name = models.CharField(max_length=255)
    number = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=MAX_REASON)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    role = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["test", "student_membership_id", "number"], name="one_retake_grant_per_attempt_number"
            ),
            models.CheckConstraint(condition=Q(number__gte=2), name="a_retake_is_a_second_attempt_or_later"),
            models.CheckConstraint(condition=~Q(reason=""), name="a_retake_says_why"),
        ]


class AnswerEvent(models.Model):
    """One choice a device sent, accepted or refused. **Append-only.**

    `(session, client_seq)` is the idempotency key: a resend of the same choice is the
    same row, and the device is told so. `chosen` is the **original** option index
    (`TestItem.options`), never a letter, or empty for a cleared answer. `chosen_at` is
    the server's time as the device estimated it (its sync offset plus its own
    monotonic clock, never its wall clock).

    **The answer that counts for an item is the one chosen later** (`docs/cbt.md`,
    "Power cuts"). Nothing is updated to say so: each row, when it arrives, names the row
    it replaced (`supersedes`) or the row it lost to (`superseded_by`), so the counted
    answer is the accepted row nobody superseded and that lost to nobody
    (`cbt.sitting.counted_answers()`). A refused row (`late`, `after_submit`) is kept,
    and counts for nothing.
    """

    class Refusal(models.TextChoices):
        NONE = "", "Accepted"
        LATE = "late", "Arrived after the deadline and its late window"
        AFTER_TIME = "after_time", "Chosen after time ran out"
        AFTER_SUBMIT = "after_submit", "Arrived after the attempt was closed"

    attempt = models.ForeignKey(Attempt, related_name="answers", on_delete=models.PROTECT)
    session = models.ForeignKey(AttemptSession, related_name="answers", on_delete=models.PROTECT)
    item = models.ForeignKey(TestItem, related_name="answers", on_delete=models.PROTECT)
    chosen = models.PositiveSmallIntegerField(null=True, blank=True)
    client_seq = models.PositiveIntegerField()
    chosen_at = models.DateTimeField()
    received_at = models.DateTimeField()
    accepted = models.BooleanField()
    refusal = models.CharField(max_length=16, blank=True, default="")
    supersedes = models.ForeignKey(
        "self", related_name="superseded_rows", null=True, blank=True, on_delete=models.PROTECT
    )
    superseded_by = models.ForeignKey(
        "self", related_name="losers", null=True, blank=True, on_delete=models.PROTECT
    )
    #: Settled by `received_at` because the two choices were too close to call.
    tie = models.BooleanField(default=False)

    class Meta:
        ordering = ["attempt_id", "received_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["session", "client_seq"], name="one_answer_event_per_device_sequence"),
            models.CheckConstraint(
                condition=Q(accepted=True, refusal="")
                | Q(accepted=False, refusal__in=["late", "after_time", "after_submit"]),
                name="an_answer_is_accepted_or_refused_for_a_reason",
            ),
            models.CheckConstraint(
                condition=Q(supersedes__isnull=True) | Q(superseded_by__isnull=True),
                name="an_answer_wins_or_loses_not_both",
            ),
            models.CheckConstraint(
                condition=Q(accepted=True) | Q(supersedes__isnull=True, superseded_by__isnull=True),
                name="a_refused_answer_replaces_nothing",
            ),
            models.CheckConstraint(condition=Q(chosen__isnull=True) | Q(chosen__lt=5), name="an_answer_is_a_to_e_or_none"),
        ]


class AttemptEvent(models.Model):
    """What happened in a sitting, by whose word, when. **Append-only.** The sitting log.

    `said_by` is `server` for what the server saw (a start, a gap in the heartbeat, a
    replaced computer, a late answer refused, extra time) and `device` for what the
    student's computer reported when it could (its offline spans, the student leaving
    the exam's tab or window). `attempt` is empty for what happened before one started
    ("This is not me" at the door, extra time given ahead).

    **Never an answer, an item or an option** in `detail`: the administrator reads this
    log (`docs/cbt.md`, "The administrator").
    """

    class Kind(models.TextChoices):
        START = "start", "Started"
        NOT_ME = "not_me", "Said “This is not me”"
        RESUME = "resume", "Signed in again"
        REPLACED = "replaced", "Another computer took over"
        DISCONNECT = "disconnect", "Lost the connection"
        RECONNECT = "reconnect", "Back online"
        LEFT_PAGE = "left_page", "Left the test's tab or window"
        SUBMIT = "submit", "Submitted"
        CLOCK_SUBMIT = "clock_submit", "Time ran out"
        TEACHER_SUBMIT = "teacher_submit", "Ended when the sitting was closed"
        LATE_REFUSED = "late_refused", "An answer arrived too late"
        EXTRA_TIME = "extra_time", "Given extra time"
        RETAKE = "retake", "Allowed a retake"

    class SaidBy(models.TextChoices):
        SERVER = "server", "The school's server"
        DEVICE = "device", "The student's computer"

    test = models.ForeignKey(Test, related_name="attempt_events", on_delete=models.PROTECT)
    student_membership_id = models.PositiveBigIntegerField()
    attempt = models.ForeignKey(Attempt, related_name="events", null=True, blank=True, on_delete=models.PROTECT)
    session = models.ForeignKey(AttemptSession, related_name="events", null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind)
    said_by = models.CharField(max_length=8, choices=SaidBy, default=SaidBy.SERVER)
    at = models.DateTimeField()
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["test", "student_membership_id"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    kind__in=[
                        "start", "not_me", "resume", "replaced", "disconnect", "reconnect", "left_page", "submit",
                        "clock_submit", "teacher_submit", "late_refused", "extra_time", "retake",
                    ]
                ),
                name="an_attempt_event_is_of_a_known_kind",
            ),
            models.CheckConstraint(condition=Q(said_by__in=["server", "device"]), name="an_attempt_event_says_who_said_it"),
        ]


# -- Phase 2 step 5: marking, key corrections, CA and release --------------------------
#
# `docs/cbt.md`, "Release and CA" and "How scores reach CA". **No live score is stored**:
# a score is computed from the counted answers (`cbt.sitting.counted_answers()`) and the
# keys on read (`cbt.marking`). What is kept is what happened: each key correction, each
# send to CA and its lines, each release and the scores it froze, and each restore. Every
# table here is append-only, by a trigger in migration 0004 named for its rule.

#: Why a key was corrected, a release restored.
MAX_WHY = 200



class KeyCorrection(models.Model):
    """A wrong key put right: one item's correct option, from `old_index` to `new_index`.

    **Never an edit to the item** (`TestItem` is frozen, `a_published_item_is_frozen`):
    the key an attempt is marked against is the item's own, or the latest correction's
    (`cbt.marking.keys_of()`), so every attempt is marked again the moment this row exists.
    Only before release: the database refuses a correction while any class of the test has
    a release that has not been restored (`a_key_is_corrected_only_before_release`).

    `changes` is what the correction did, written in the same transaction (rule 8): each
    student whose score moved, with their score before and after. It is the list the
    teacher is shown, and it is kept because the scores themselves are never stored.
    """

    test = models.ForeignKey(Test, related_name="key_corrections", on_delete=models.PROTECT)
    item = models.ForeignKey(TestItem, related_name="key_corrections", on_delete=models.PROTECT)
    old_index = models.PositiveSmallIntegerField()
    new_index = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=MAX_WHY)
    #: `[{"student_id", "name", "class_name", "before", "after"}]`, and the paper's marks.
    changes = models.JSONField(default=list, blank=True)
    out_of = models.PositiveIntegerField()
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    role = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
        constraints = [
            models.CheckConstraint(condition=~Q(reason=""), name="a_key_correction_says_why"),
            models.CheckConstraint(
                condition=~Q(old_index=models.F("new_index")), name="a_key_correction_changes_the_key"
            ),
            models.CheckConstraint(condition=Q(new_index__lt=5), name="a_corrected_key_is_a_to_e"),
        ]


class TestRelease(models.Model):
    """One class's scores of one test, released: final, like a results release.

    The scores are frozen beside it as `ReleasedTestScore` rows in the same transaction, and
    those, never live marks, are all a student's or a parent's page reads. **A release is
    live until a `TestReleaseRestore` names it**; a later release of the same class is a new
    row with its own frozen scores, so nothing frozen is ever edited.
    """

    test = models.ForeignKey(Test, related_name="releases", on_delete=models.PROTECT)
    class_group = models.ForeignKey(ClassGroup, related_name="test_releases", on_delete=models.PROTECT)
    class_group_name = models.CharField(max_length=64)
    #: How many scores it froze.
    count = models.PositiveIntegerField()
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    role = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]


class TestReleaseRestore(models.Model):
    """A release undone, by the principal, with a reason. Append-only, one per release.

    It hides that release's scores from the student and the parent again and shows the
    teacher why. Its frozen rows are not deleted or edited; a CA mark already sent is not
    touched (`docs/cbt.md`, "Release and CA").
    """

    release = models.OneToOneField(TestRelease, related_name="restore", on_delete=models.PROTECT)
    reason = models.CharField(max_length=MAX_WHY)
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
        constraints = [models.CheckConstraint(condition=~Q(reason=""), name="a_restore_says_why")]


class ReleasedTestScore(models.Model):
    """One student's score as it was released. **Append-only**, names copied (rules 1, 2).

    The only thing a student's or a parent's score page reads. `corrections` is the
    student's own paper as they saw it (their numbering and letters, from the attempt's
    seed), with what they chose, the right answer and its explanation: the "corrections"
    a student is shown, and **never** served to a parent.
    """

    release = models.ForeignKey(TestRelease, related_name="scores", on_delete=models.PROTECT)
    test = models.ForeignKey(Test, related_name="released_scores", on_delete=models.PROTECT)
    student_membership_id = models.PositiveBigIntegerField(db_index=True)
    student_name = models.CharField(max_length=255)
    admission_number = models.CharField(max_length=64, blank=True, default="")
    class_group_name = models.CharField(max_length=64)
    test_title = models.CharField(max_length=MAX_TITLE)
    subject_name = models.CharField(max_length=64)
    attempt_number = models.PositiveSmallIntegerField()
    score = models.PositiveIntegerField()
    out_of = models.PositiveIntegerField()
    #: Questions right, and questions on the paper.
    right = models.PositiveIntegerField()
    questions = models.PositiveIntegerField()
    corrections = models.JSONField(default=list, blank=True)
    released_by_name = models.CharField(max_length=255)
    released_at = models.DateTimeField()

    class Meta:
        ordering = ["-released_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["release", "student_membership_id"], name="one_released_score_per_student"),
            models.CheckConstraint(condition=Q(score__lte=models.F("out_of")), name="a_released_score_is_at_most_its_marks"),
        ]


class CaTransfer(models.Model):
    """One send of a test's scores into a CA column. Append-only.

    `docs/cbt.md`, "How scores reach CA": each mark is `round_half_up(score / out_of x
    max_score)` and goes through `gradebook.services.set_score_as()`, never a second write
    path. `existing` is what the sender chose for a student who already had a mark: keep
    it, or replace it with the one they were shown. `number` counts this test's sends.
    """

    class Existing(models.TextChoices):
        KEEP = "keep", "Keep their mark"
        REPLACE = "replace", "Replace it with the test mark"

    test = models.ForeignKey(Test, related_name="ca_transfers", on_delete=models.PROTECT)
    assessment = models.ForeignKey("gradebook.Assessment", related_name="cbt_transfers", on_delete=models.PROTECT)
    assessment_name = models.CharField(max_length=64)
    max_score = models.PositiveSmallIntegerField()
    out_of = models.PositiveIntegerField()
    #: The rule each mark was made by.
    rounding = models.CharField(max_length=16, default="half_up")
    existing = models.CharField(max_length=8, choices=Existing)
    number = models.PositiveIntegerField()
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    role = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["test", "number"], name="one_ca_transfer_per_number"),
            models.CheckConstraint(condition=Q(existing__in=["keep", "replace"]), name="a_ca_transfer_keeps_or_replaces"),
        ]


class CaTransferLine(models.Model):
    """What one send did for one student. Append-only.

    Four of five outcomes write nothing to the gradebook, so the line is their only record
    (rule 8): `written` (through `set_score_as()`), `kept` (they had a mark, and the send
    said keep), `not_sat` (no closed attempt: **no mark, never a zero**), `locked` (the
    gradebook refused: the class's results are submitted or released), `changed_meanwhile`
    (a mark was typed after the preview, so it was not overwritten).
    """

    class Outcome(models.TextChoices):
        WRITTEN = "written", "Written"
        KEPT = "kept", "Kept as it was"
        NOT_SAT = "not_sat", "Did not sit, no mark"
        LOCKED = "locked", "Results locked, not sent"
        CHANGED_MEANWHILE = "changed_meanwhile", "Changed since the preview, not sent"

    transfer = models.ForeignKey(CaTransfer, related_name="lines", on_delete=models.PROTECT)
    student_membership_id = models.PositiveBigIntegerField()
    student_name = models.CharField(max_length=255)
    class_group_name = models.CharField(max_length=64)
    test_score = models.PositiveIntegerField(null=True, blank=True)
    mark = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome)
    #: The mark in the column before, and its version, as the preview showed them.
    previous_value = models.PositiveSmallIntegerField(null=True, blank=True)
    previous_version = models.PositiveIntegerField(null=True, blank=True)
    detail = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["transfer_id", "class_group_name", "student_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["transfer", "student_membership_id"], name="one_ca_line_per_student"),
            models.CheckConstraint(
                condition=Q(outcome__in=["written", "kept", "not_sat", "locked", "changed_meanwhile"]),
                name="a_ca_line_has_a_known_outcome",
            ),
            models.CheckConstraint(
                condition=~Q(outcome="not_sat") | Q(mark__isnull=True, test_score__isnull=True),
                name="a_student_who_did_not_sit_gets_no_mark",
            ),
            models.CheckConstraint(
                condition=~Q(outcome="written") | Q(mark__isnull=False), name="a_written_line_names_its_mark"
            ),
        ]
