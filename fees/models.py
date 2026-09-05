"""What a family owes a school, and what they have paid, as a ledger.

Tenant-scoped, like `academics`: fees are the school's own books, and one copy
per schema is the whole point. See docs/tenancy.md.

Three decisions shape everything below, and they are worth reading before the
fields.

**Money is whole kobo, stored as integers.** Never a float, never a Decimal
column. A naira amount is a presentation concern that belongs at the edge, and
the only safe representation in between is a count of the smallest unit. The
column is a *signed* `BigIntegerField`, and the sign carries meaning:

    positive  ->  increases what the family owes   (a charge, a refund)
    negative  ->  reduces it                       (a payment, a discount)

so a balance is `SUM(amount_kobo)` and there is no case analysis to get wrong.
`FeeLedgerQuerySet.balance()` is exactly that sum.

**The ledger is append-only. A correction is a new row.** Nothing here is ever
edited and nothing is ever deleted — a wrong entry is undone by a `REVERSAL`
that names it, and the right entry is then posted fresh. That is not a
convention: `save()` refuses to update an existing row, and a database trigger
refuses `UPDATE` and `DELETE` outright, so a data import, a shell session or a
future service function cannot walk around it either. What the books said last
week is still what they said last week.

**It points at a student by bare id, with no foreign key.** That is the
`docs/tenancy.md` blocker being answered rather than dodged, and the reasoning
is in `student_membership_id` below.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum

#: Kobo in a naira. Here so that no call site has to remember it, and so that
#: the one place it appears is next to the column it describes.
KOBO_PER_NAIRA = 100


class FeeEntryKind(models.TextChoices):
    CHARGE = "charge", "Charge"
    PAYMENT = "payment", "Payment"
    DISCOUNT = "discount", "Discount"
    REVERSAL = "reversal", "Reversal"
    #: Money handed back. Rare, and deliberately not the default answer to a
    #: mid-term withdrawal: a family in credit simply stands at a negative
    #: balance, which needs no machinery at all and is what most schools do.
    #: This kind exists so that a school which *does* return cash can say so
    #: rather than posting a charge and calling it something it is not.
    REFUND = "refund", "Refund"


#: Kinds that increase what a family owes, and kinds that reduce it. Stated once
#: and enforced by check constraints below, so a negative charge or a positive
#: payment is a database error rather than a number nobody notices.
#:
#: **Tuples, not frozensets**, and that is load-bearing rather than a style
#: choice. These go into a `Q(kind__in=...)` inside a check constraint, and a set
#: has no order: `tuple(frozenset)` depends on string hashes, which Python
#: randomises per process. The constraint written into the migration and the one
#: the model computes on the next run therefore compare unequal, and
#: `makemigrations` proposes dropping and recreating it every time — on a
#: different run in a different order, forever. CI runs `makemigrations --check`,
#: so the symptom is a build that is red at random. Membership tests read the
#: same either way.
INCREASES_DEBT = (FeeEntryKind.CHARGE, FeeEntryKind.REFUND)
REDUCES_DEBT = (FeeEntryKind.PAYMENT, FeeEntryKind.DISCOUNT)

#: Which kinds may name a schedule line, and which may name a concession.
#:
#: A `REVERSAL` is in both because it inherits its target's source: undoing a
#: schedule charge produces a row that is still *about* that line, and asking
#: "everything this line did" must return the mistake and the fix together. That
#: is also why the uniqueness constraints below are conditioned on `kind` — see
#: `a_schedule_line_charges_a_child_once`.
#:
#: Tuples, for the reason above. Every one of these goes into a `Q(kind__in=...)`
#: inside a check constraint.
SCHEDULE_SOURCED_KINDS = (FeeEntryKind.CHARGE, FeeEntryKind.REVERSAL)
CONCESSION_SOURCED_KINDS = (FeeEntryKind.DISCOUNT, FeeEntryKind.REVERSAL)


class FeeSchedule(models.Model):
    """One class's bill for one term: what JSS 1A is charged, itemised.

    **A template, not a record.** This is the decision the whole of billing
    turns on, and `docs/fees.md` left it open: *does editing a schedule change
    past charges?* It does not. Applying a schedule posts CHARGE entries that
    freeze the amount and the narration; editing it afterwards changes only what
    a **future** application would post. A school that edits after applying and
    wants the difference reflected reverses and re-posts, which the ledger
    already does.

    So this model and its lines are plain editable rows — no append-only
    `save()`, no trigger. That is `docs/operating-rules.md` rule 8 read in the
    direction that saves work: a decision producing a frozen artefact needs no
    log of its own, and making the template append-only too would be a second,
    weaker copy of a guarantee the entries already hold. It would also stop a
    bursar fixing next term's bill, which is the ordinary thing they need to do.

    Both foreign keys are tenant to tenant, so they are real keys that really
    protect — `FeeLedgerEntry.term` carries the same note. `PROTECT` on both: a
    term or a class with a bill against it is not a row to delete out from
    under it.
    """

    term = models.ForeignKey(
        "academics.Term",
        related_name="fee_schedules",
        on_delete=models.PROTECT,
        help_text="The term this bill is for.",
    )
    class_group = models.ForeignKey(
        "academics.ClassGroup",
        related_name="fee_schedules",
        on_delete=models.PROTECT,
        help_text="The class this bill is for.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # **Own columns only, and `class_group_id` rather than `class_group`.**
        # Commit 034b6b3 is the standing lesson: ordering by a relation makes
        # Django order by the *related* model's `Meta.ordering` and join to get
        # it, and `ClassGroup.Meta.ordering` is `["level", "name"]`. A joined
        # ordering would make `select_for_update()` in `fees.schedules` lock the
        # class group row as well — a billing run taking a lock on a table it
        # never writes. The `id` tiebreak keeps two bills for one class stable
        # between reads, which the constraint below makes impossible anyway and
        # which costs nothing to guarantee.
        ordering = ["class_group_id", "id"]
        constraints = [
            # Two bills for JSS 1A's first term is not a school with options; it
            # is a school about to charge twice, with nothing to say which bill
            # is the real one.
            models.UniqueConstraint(
                fields=["term", "class_group"],
                name="one_fee_schedule_per_class_per_term",
            ),
        ]

    def __str__(self):
        return f"{self.class_group} — {self.term}"

    @property
    def total_kobo(self) -> int:
        """What this bill comes to, in kobo. For display; nothing keys off it."""
        return self.lines.aggregate(total=Sum("amount_kobo"))["total"] or 0


class FeeScheduleLine(models.Model):
    """One item on one bill: "Tuition", "PTA levy", "Uniform".

    **Lines rather than a single amount**, and the argument is not that parents
    like breakdowns. It is that the ledger's only correction is
    reverse-and-repost. With one lumped charge, a school that gets the PTA levy
    wrong must reverse the whole term's charge for every child in the class and
    post it again; with lines they reverse the levy. Itemisation makes a
    correction proportionate to the mistake, which is the reason the reversal
    model exists at all. A school with one line has one line.

    `CASCADE` on `schedule`, because a line has no meaning without its bill.
    That does **not** make a used schedule deletable: `FeeLedgerEntry.source_line`
    is `PROTECT`, and Django resolves the protected relation before the cascade
    completes. A line that has charged nobody stays freely deletable, which is
    the rule a bursar actually needs.
    """

    schedule = models.ForeignKey(
        FeeSchedule, related_name="lines", on_delete=models.CASCADE
    )
    description = models.CharField(
        max_length=255,
        help_text="What this line is for, in the school's words. Becomes the narration.",
    )
    amount_kobo = models.PositiveBigIntegerField(
        help_text="Whole kobo, a magnitude. The ledger applies the sign."
    )
    position = models.PositiveSmallIntegerField(
        default=0, help_text="Print order on the bill, smallest first."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # The `id` tiebreak is not decoration: two lines at the same position
        # must not swap between two reads of one bill, which is the note
        # `academics.Trait.position` already carries.
        ordering = ["position", "id"]
        constraints = [
            # Two "PTA levy" lines on one bill is a typo. Forbidding it is also
            # what makes the idempotency skip in `fees.schedules` legible: the
            # thing a child is charged once is a *line*, and a bill with two
            # lines of the same name has no single answer to "were they charged
            # the levy?".
            models.UniqueConstraint(
                fields=["schedule", "description"],
                name="a_bill_names_each_line_once",
            ),
            # Zero is a placeholder somebody meant to fill in. Negative is a
            # concession wearing a charge's clothes, and concessions have their
            # own table with their own reason field.
            models.CheckConstraint(
                condition=Q(amount_kobo__gt=0),
                name="a_schedule_line_charges_something",
            ),
        ]

    def __str__(self):
        return f"{self.description} ({self.amount_kobo} kobo)"


class FeeConcession(models.Model):
    """A standing instruction to discount one child: a staff child, a bursary.

    **Fixed amounts only.** A percentage needs a rounding rule to the kobo *and*
    an answer to "a percentage of which lines" — two decisions bought for one
    convenience, when a half-fees scholarship is expressible as a fixed amount
    today.

    **The exception is a DISCOUNT, not an override.** A staff child is charged
    the full fee and given a full concession, not billed nothing. `discount()`
    already made this argument for itself: *"we waived it" and "they paid it"
    are different facts*, and an override amount would erase the concession from
    the record entirely. The consequence is the useful part — the per-child
    exception needs no change to the class's bill at all.

    **A live instruction, not a record**, which is why there is no `student_name`
    snapshot here. `FeeLedgerEntry` freezes identity because it *is* a record;
    freezing a name onto this row would be a second, staler answer to a question
    `accounts` already answers. What actually happened is the dated DISCOUNT
    entries, one per term, and they stand whatever becomes of this row.

    **No window and no term key.** A concession applies to every application run
    while `is_active`, and is switched off rather than end-dated. The edge that
    gives up is a school setting up a *future* term with a concession since
    withdrawn; the record of what was actually granted is unaffected.

    **Several concessions per child is allowed, deliberately.** A bursary and a
    sibling discount are two facts and two DISCOUNT entries, so there is no
    unique constraint on the child here — idempotency is keyed on the concession,
    in `FeeLedgerEntry.a_concession_discounts_a_child_once_per_term`.
    """

    # A bare id, pointing at the child's STUDENT membership, for the reason
    # `FeeLedgerEntry.student_membership_id` sets out at length: `Membership` is
    # in `public`, and a foreign key from a tenant schema into it does not
    # protect what it appears to. `fees.schedules` asks
    # `accounts.students.why_not_a_student_here()` before writing anything.
    student_membership_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text=(
            "accounts.Membership id of the student's STUDENT membership. A bare "
            "id and not a ForeignKey — see FeeLedgerEntry and docs/tenancy.md."
        ),
    )

    amount_kobo = models.PositiveBigIntegerField(
        help_text="Whole kobo, a magnitude. The ledger applies the sign."
    )
    reason = models.CharField(
        max_length=255,
        help_text='Why it was granted — "Staff child", "Bursary 2026". Becomes the narration.',
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            "A concession no longer granted. Switched off rather than deleted, "
            "because the entries it produced name it."
        ),
    )

    granted_by_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text="accounts.User id of whoever granted it, where there was one.",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student_membership_id", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_kobo__gt=0),
                name="a_concession_reduces_something",
            ),
            # A regex and **not** `~Q(reason="")`, which is the form
            # `results/models.py` records the reason for: a reason of three
            # spaces passes the empty-string test, is refused by the service,
            # and renders blank on a screen. The regex is the form that agrees
            # with the service.
            models.CheckConstraint(
                condition=Q(reason__regex=r"\S"),
                name="a_concession_says_why",
            ),
        ]

    def __str__(self):
        return f"{self.reason} — membership {self.student_membership_id}"


class LedgerIsAppendOnly(Exception):
    """Something tried to edit or delete a ledger row that already exists."""


class FeeLedgerQuerySet(models.QuerySet):
    def for_student(self, membership_id):
        return self.filter(student_membership_id=membership_id)

    def for_term(self, term):
        return self.filter(term=term)

    def balance(self) -> int:
        """What is outstanding across these entries, in kobo.

        Positive means the family owes; negative means they are in credit, which
        is a real state — a term's fees paid before the charge is posted, or an
        overpayment carried forward.

        A plain sum, and that is the point of the signed column: reversals are
        included with no special handling, because a reversal *is* an amount of
        the opposite sign. There is no "except the cancelled ones" clause to
        forget.
        """
        return self.aggregate(total=Sum("amount_kobo"))["total"] or 0


class FeeLedgerEntry(models.Model):
    """One immutable line in one school's fee book.

    Never updated and never deleted — see the module docstring and `save()`.
    """

    # Tenant-local, so a real foreign key with real integrity: `academics_term`
    # and this table live in the same schema, and the cross-schema problem
    # docs/tenancy.md describes simply does not arise. PROTECT because a term
    # with money against it is not a row anybody should be able to delete.
    term = models.ForeignKey(
        "academics.Term",
        related_name="fee_entries",
        on_delete=models.PROTECT,
        help_text="The term this entry is reckoned against.",
    )

    # A bare id, deliberately, pointing at `accounts.Membership` — the student's
    # STUDENT membership, which pins both the child and their school in one
    # value, exactly as `Guardianship.student` does.
    #
    # No `ForeignKey`, because docs/tenancy.md measured what one does from a
    # tenant schema into `public` and the answer was: `on_delete` is resolved
    # against whichever schema the connection is on, so `PROTECT` does not
    # protect and `CASCADE` cascades only one school's rows, with the breakage
    # surfacing at COMMIT rather than at the delete. For a *financial* record
    # that is the worst of both worlds: the guarantee most worth having here is
    # "this history cannot be destroyed by deleting somebody", and a foreign key
    # is precisely the mechanism that would not deliver it.
    #
    # Keeping the schema self-contained also means a school's books can be
    # dumped, restored and handed over on their own, which for money is a
    # requirement rather than a nicety. And the choice stays cheap to revisit:
    # docs/tenancy.md notes the asymmetry — adding a foreign key later is a
    # migration, removing one once tenant data exists is not.
    student_membership_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text=(
            "accounts.Membership id of the student's STUDENT membership. A bare "
            "id and not a ForeignKey — see the comment above and docs/tenancy.md."
        ),
    )

    # Identity as it stood when the entry was posted, not as it stands now.
    #
    # Not denormalisation for speed — a financial record has to keep saying what
    # it said. If a school corrects a child's name or reissues admission numbers,
    # last term's receipt must still read the way it was issued, and a join to a
    # live row would silently rewrite it. This is also what keeps the books
    # legible when the bare id above points at a membership that has since ended.
    student_name = models.CharField(
        max_length=255,
        help_text="The student's name as it stood when this entry was posted.",
    )
    student_reference = models.CharField(
        max_length=64,
        blank=True,
        help_text="Admission number as it stood when this entry was posted.",
    )

    kind = models.CharField(max_length=16, choices=FeeEntryKind)

    # Signed, in kobo. See the module docstring: positive increases what is
    # owed, negative reduces it, and a balance is the plain sum.
    amount_kobo = models.BigIntegerField(
        help_text=(
            "Whole kobo. Positive increases what the family owes; negative "
            "reduces it. Never a float, never naira."
        )
    )

    narration = models.CharField(
        max_length=255, help_text="What this line is for, in the school's words."
    )
    #: Teller number, receipt number, transfer reference — whatever the school
    #: reconciles against. Free text because every bank and every school does
    #: this differently, and a format guessed now is a format wrong later.
    #:
    #: **Non-unique, and it must stay non-unique.** A parent paying for three
    #: children makes one transfer, and payment is against a child — so that is
    #: three PAYMENT rows sharing one teller number. A future reader will want a
    #: unique index here to stop a receipt being keyed in twice; it would refuse
    #: the ordinary Nigerian case. The duplicate-receipt question, if a school
    #: ever asks it, is a report that finds repeats, not a constraint that
    #: forbids them.
    reference = models.CharField(max_length=64, blank=True)

    # The entry this one undoes. Same table, same schema, so a real foreign key
    # again. PROTECT: an entry that has been reversed is part of the story and
    # cannot be removed — not that anything can remove rows here anyway.
    reverses = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="reversed_by",
        on_delete=models.PROTECT,
        help_text="For a REVERSAL, the entry being undone. Null otherwise.",
    )

    # What produced this entry, where a machine produced it. Both tenant to
    # tenant, so both are real keys.
    #
    # `PROTECT` for `term`'s reason: a schedule line or a concession that has
    # moved money is part of the story and cannot be deleted out from under the
    # rows that name it. The rule this gives a bursar is the one they need — fix
    # next term's bill freely, and never delete the line that billed forty-five
    # families.
    #
    # Null for everything posted by hand, which is most entries.
    source_line = models.ForeignKey(
        FeeScheduleLine,
        null=True,
        blank=True,
        related_name="entries",
        on_delete=models.PROTECT,
        help_text="The schedule line that posted this charge, where one did.",
    )
    source_concession = models.ForeignKey(
        FeeConcession,
        null=True,
        blank=True,
        related_name="entries",
        on_delete=models.PROTECT,
        help_text="The concession that posted this discount, where one did.",
    )

    #: The date the entry counts for, which is not always the date it was typed
    #: in — a payment made on Friday and recorded on Monday belongs to Friday.
    effective_on = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    # Bare id again, and for the same reason as the student. Nullable because an
    # entry can come from an import or a scheduled charge with no person behind
    # it, and naming a fictional one would be worse.
    recorded_by_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text="accounts.User id of whoever posted this, where there was one.",
    )

    objects = FeeLedgerQuerySet.as_manager()

    class Meta:
        # Newest first, then by id so that two entries posted in the same
        # millisecond still have a stable order — a ledger that reorders itself
        # between two reads is a ledger nobody can reconcile.
        ordering = ["-effective_on", "-id"]
        verbose_name_plural = "fee ledger entries"
        indexes = [
            models.Index(fields=["student_membership_id", "term"]),
            models.Index(fields=["term", "kind"]),
        ]
        constraints = [
            # Zero moves no money and states nothing. It is always a mistake,
            # and usually a placeholder somebody meant to fill in.
            models.CheckConstraint(
                condition=~Q(amount_kobo=0),
                name="a_ledger_entry_moves_money",
            ),
            # The sign has meaning, so the kind and the sign must agree. Without
            # this a negative charge and a positive payment both post happily
            # and the balance is quietly wrong in a way no screen would show.
            models.CheckConstraint(
                condition=~Q(kind__in=INCREASES_DEBT) | Q(amount_kobo__gt=0),
                name="a_charge_or_refund_increases_what_is_owed",
            ),
            models.CheckConstraint(
                condition=~Q(kind__in=REDUCES_DEBT) | Q(amount_kobo__lt=0),
                name="a_payment_or_discount_reduces_what_is_owed",
            ),
            # A reversal names what it undoes, and nothing else does. Both
            # halves matter: a reversal pointing at nothing is unauditable, and
            # a charge pointing at another entry is a relationship the ledger
            # has no meaning for.
            models.CheckConstraint(
                condition=(
                    Q(kind=FeeEntryKind.REVERSAL, reverses__isnull=False)
                    | (~Q(kind=FeeEntryKind.REVERSAL) & Q(reverses__isnull=True))
                ),
                name="only_a_reversal_names_what_it_undoes",
            ),
            # An entry is undone once or not at all. Two reversals of one charge
            # would take the balance below where it started and read, to anyone
            # totalling the column, as a refund that never happened.
            models.UniqueConstraint(
                fields=["reverses"],
                condition=Q(reverses__isnull=False),
                name="an_entry_is_reversed_at_most_once",
            ),
            # **The idempotency backstop.** `fees.schedules.apply_to_class()`
            # skips a child who already has this line's charge, so a bursar sees
            # "42 skipped, 3 charged" rather than an error; this is what holds
            # when two of them click at the same instant and both skip-checks
            # pass before either commits.
            #
            # No `term` in the key, deliberately: a line belongs to a schedule
            # which belongs to exactly one term, so `(student, line)` is already
            # term-scoped and adding `term` would be a wider key meaning the
            # same thing.
            #
            # Conditioned on `kind`, which is what lets a reversal keep its
            # `source_line`. Without that half, reversing a schedule charge
            # would collide with the charge it reverses, on the very index meant
            # to stop double-billing.
            #
            # **A reversed schedule charge cannot be re-posted by re-running the
            # application**, and that is correct rather than a limitation. The
            # reversed original still exists — the ledger is append-only, so it
            # always will — and this index still sees it. Deliberately undoing a
            # charge and then wanting it back is exceptional and should take an
            # explicit `charge()`, not a second click on the same button.
            models.UniqueConstraint(
                fields=["student_membership_id", "source_line"],
                condition=Q(source_line__isnull=False, kind=FeeEntryKind.CHARGE),
                name="a_schedule_line_charges_a_child_once",
            ),
            # The concession key *does* name the term, for the mirror-image
            # reason: a concession is standing and applies every term, so
            # without the term a scholarship would be granted once and never
            # again.
            models.UniqueConstraint(
                fields=["student_membership_id", "term", "source_concession"],
                condition=Q(
                    source_concession__isnull=False, kind=FeeEntryKind.DISCOUNT
                ),
                name="a_concession_discounts_a_child_once_per_term",
            ),
            # A source column names what produced the entry, so it has to agree
            # with what the entry *is*. A payment carrying a schedule line would
            # read, to anyone asking what that line did, as the school having
            # billed money it actually received.
            models.CheckConstraint(
                condition=Q(source_line__isnull=True)
                | Q(kind__in=SCHEDULE_SOURCED_KINDS),
                name="a_schedule_line_only_produces_charges",
            ),
            models.CheckConstraint(
                condition=Q(source_concession__isnull=True)
                | Q(kind__in=CONCESSION_SOURCED_KINDS),
                name="a_concession_only_produces_discounts",
            ),
            # One source, or none. An entry produced by both a line and a
            # concession is not a richer record; it is two claims about where
            # one number came from, and every "what did this produce" query
            # would count it twice.
            models.CheckConstraint(
                condition=~Q(
                    source_line__isnull=False, source_concession__isnull=False
                ),
                name="an_entry_has_one_source",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.naira} — {self.student_name}"

    # -- money ---------------------------------------------------------------

    @property
    def naira(self) -> Decimal:
        """The amount in naira, for display only.

        `Decimal`, never `float`: the whole reason the column is kobo is that
        binary floating point cannot hold 0.1, and rendering through a float
        would reintroduce at the last step the error the column exists to avoid.
        Nothing should ever store or compare this — it is for showing a human.
        """
        return Decimal(self.amount_kobo) / KOBO_PER_NAIRA

    # -- append-only ---------------------------------------------------------

    def save(self, *args, **kwargs):
        """Refuse to rewrite a row that already exists.

        The database trigger installed by the initial migration is the rule that
        actually holds — this is the one that produces a readable error, in the
        caller's own language, before Postgres produces a less readable one. Both
        exist on purpose: the trigger is what a data import or a shell session
        runs into, and this is what a developer runs into.
        """
        if self.pk is not None and not self._state.adding:
            raise LedgerIsAppendOnly(
                f"Ledger entry {self.pk} has already been posted and cannot be "
                f"changed. Post a reversal naming it, then post the correct "
                f"entry."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise LedgerIsAppendOnly(
            f"Ledger entry {self.pk} cannot be deleted. Post a reversal naming "
            f"it instead — the books have to keep saying what they said."
        )

    def clean(self):
        """The rules a check constraint cannot express, because they span rows."""
        if self.kind != FeeEntryKind.REVERSAL:
            return
        if self.reverses is None:
            raise ValidationError({"reverses": "A reversal must name the entry it undoes."})
        if self.reverses.kind == FeeEntryKind.REVERSAL:
            raise ValidationError(
                {"reverses": "A reversal cannot itself be reversed; reverse the original."}
            )
        if self.amount_kobo != -self.reverses.amount_kobo:
            raise ValidationError(
                {
                    "amount_kobo": (
                        f"A reversal must undo its entry exactly: expected "
                        f"{-self.reverses.amount_kobo} kobo, got {self.amount_kobo}."
                    )
                }
            )
