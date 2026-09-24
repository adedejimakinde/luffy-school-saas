"""Posting to the fee ledger. The only supported way to write one.

Four functions, one per thing that can happen to a family's account: they are
charged, they pay, they are given a discount, or somebody made a mistake and it
is undone. There is deliberately no general "adjust" — see `reverse_entry()`.

Everything here takes the caller's *student membership id* rather than a
`Membership` object, because the ledger stores a bare id and the two must not
drift apart. `snapshot_student()` is the one place that turns a live membership
into the frozen identity an entry carries.

No screens, no HTTP. This is the data layer; `fees/api.py` is the bursar's
routes and calls it, and keeping the rules here rather than in a view is what
makes them true for an import and a management command too.
"""

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from accounts.students import why_not_a_student_here

from .models import (
    FeeEntryKind,
    FeeLedgerEntry,
    LedgerIsAppendOnly,
    PaymentMethod,
)


class FeeLedgerError(Exception):
    """A ledger entry could not be posted as asked.

    One base class for the whole module, for the same reason
    `schools.models.InvitationError` is one for the invitation flow: a caller
    that writes `except FeeLedgerError` should catch every refusal this module
    makes, not the half it happened to import.
    """


class NotPositive(FeeLedgerError):
    """An amount was zero or negative where a magnitude was wanted.

    Every function here takes the amount as a plain positive number of kobo and
    applies the sign itself. Letting a caller pass a negative to `charge()`
    would make the sign a caller's choice, and the sign is the ledger's whole
    grammar.
    """


class AlreadyReversed(FeeLedgerError):
    """That entry has been undone once already."""


class CannotReverse(FeeLedgerError):
    """That entry is not one that can be undone."""


class NotThisTermsLine(FeeLedgerError):
    """The schedule line named belongs to a different term than the charge.

    `a_schedule_line_charges_a_child_once` is keyed on
    `(student_membership_id, source_line)` and carries no term, on the argument
    that a line belongs to a schedule which belongs to exactly one term, so the
    pair is already term-scoped. That is true of the *line* and false of the
    *caller*: nothing stopped a hand-typed charge naming this term and last
    term's line. The index then reads that entry as this line's charge for the
    child, and the next `apply_to_class()` run reports their tuition as
    **skipped** and never bills it -- silent under-billing, discovered when a
    parent asks why their invoice is short.

    No constraint can express this: the rule spans `FeeLedgerEntry`,
    `FeeScheduleLine` and `FeeSchedule`, so it has to be asked in code.
    """


class NotThisStudentsConcession(FeeLedgerError):
    """The concession named belongs to a different child than the discount.

    The mirror of `NotThisTermsLine` on the other new column, and the one that
    corrupts a *question* rather than a balance:
    `a_concession_discounts_a_child_once_per_term` is keyed per student, so
    Chidi's bursary posted against Ada's account is accepted by the index, and
    "everything this concession did" then answers with two children -- while
    Chidi's own discount still posts later, because that pair is untaken.

    `_require_student_of_this_school()` already guards the child half of every
    entry this carefully. This is the same guard for the source half.
    """


class NotThisSchoolsStudent(FeeLedgerError):
    """The membership named is not a student of the school whose books these are.

    This is the check that earns the bare id. `student_membership_id` has no
    foreign key — see docs/tenancy.md for why — which means the database will
    happily store *any* integer there, including the id of a child at another
    school entirely. Nothing about that would be visible: the entry would sit in
    St Mary's ledger, count towards a St Mary's balance, and name a student St
    Mary's has never taught.

    A foreign key would not have caught it either, note. `Membership` is shared,
    so a foreign key into it constrains only that the row *exists* — every
    school's students are in the same table. The school half of the question has
    to be asked in code whichever way the column is declared.
    """


class NoMethod(FeeLedgerError):
    """Money moved and the entry does not say how, or says it in a way the
    school cannot reconcile: no method, a method not on the list, or a bank
    transfer with no reference.

    Asked here as well as by `a_method_on_money_that_moved_and_nowhere_else`
    and `a_bank_transfer_names_its_reference`, so a caller gets a sentence and
    a `FeeLedgerError` rather than an `IntegrityError` from Postgres. The
    constraints are what hold; this is what reads.
    """


class FormAlreadyUsed(FeeLedgerError):
    """A form key already posted an entry, and not this one.

    The same key twice with the same details is a double click, and the answer
    is the entry the first click posted. The same key with different details is
    a page that reused a key it should have replaced — answering with the first
    entry would tell the bursar a payment was recorded that was not.
    """


class NoReason(FeeLedgerError):
    """A discount or an undo given by hand without saying why.

    Decided 2026-09-24 (fees 2(a)). The reason becomes the entry's narration —
    what the books say about the row a year later — so it is refused rather
    than filled in: an undo left to `reverse_entry()`'s default would say only
    "Reversal of: Payment received", which records that something was undone
    and never why. Asked by `discount_once()` and `undo()`, the two ways a
    person does either, and not by the primitives beneath them, which a
    schedule and a concession call with narrations of their own. Since B2,
    `fees.billing` asks it too, of a concession's grant and its revocation
    (issue #75).
    """


def _require_reason(reason):
    text = (reason or "").strip()
    if not text:
        raise NoReason("Say why, in a few words. The books keep the reason.")
    if len(text) > _NARRATION_MAX:
        raise NoReason(f"Keep the reason under {_NARRATION_MAX} characters.")
    return text


def _require_method(method, reference):
    if method not in PaymentMethod.values:
        raise NoMethod(
            f"Say how the money moved: one of {', '.join(PaymentMethod.labels)}."
        )
    if method == PaymentMethod.BANK_TRANSFER and not (reference or "").strip():
        raise NoMethod(
            "A bank transfer needs its teller or transfer reference, so the "
            "school can find it on its statement."
        )
    return method


def _require_student_of_this_school(membership):
    """Refuse a membership that is not a student here, before anything is written.

    The rule itself now lives in `accounts.students` — see the note on
    `NotThisSchoolsStudent` above, which said it would move there once a third
    tenant app asked the same question. What stays here is the *raising*, so
    that `except FeeLedgerError` still means "the entry was not posted".
    """
    reason = why_not_a_student_here(
        membership, subject="a fee entry", holder="books"
    )
    if reason:
        raise NotThisSchoolsStudent(reason)
    return membership


def snapshot_student(membership):
    """The identity fields an entry freezes, taken from a live membership.

    Kept in one place because getting it wrong is silent: an entry posted with
    a blank name is unreadable a year later, and one posted by joining to the
    live row rewrites itself when a school corrects a spelling.
    """
    return {
        "student_membership_id": membership.pk,
        "student_name": membership.name,
        "student_reference": membership.reference,
    }


#: The partial unique index `a_concession_discounts_a_child_once_per_term`,
#: written as an `ON CONFLICT` **inference clause** rather than a constraint name.
#:
#: `ON CONFLICT ON CONSTRAINT <name>` cannot be used here and the reason is not a
#: style choice: a Django `UniqueConstraint` carrying a `condition` is created as
#: a *partial unique index*, not a table constraint, and Postgres answers
#: `constraint "..." for table "..." does not exist` when asked to name one.
#: Inference by columns-plus-predicate is the form that reaches a partial index.
#:
#: **Naming the index rather than writing a bare `DO NOTHING` is the whole
#: narrowing**, and it is what `_is_the_concession_colliding()` used to do in
#: Python. A bare `ON CONFLICT DO NOTHING` swallows *every* unique violation this
#: table can raise, so the day somebody adds a second index reachable from a
#: discount, every row it refuses becomes a silently skipped discount — the shape
#: of bug that never gets reported. Targeted, that row still raises. Proven by
#: `test_a_different_unique_violation_is_still_raised`, not merely intended.
#:
#: Foreign-key failures are **not** conflicts and are unaffected by `DO NOTHING`:
#: a concession deleted underneath a run still aborts it, which is correct and is
#: the asymmetry issue #85 asks to preserve. `test_do_nothing_does_not_hide_a_
#: foreign_key_failure` asks Postgres directly rather than taking it on trust —
#: if `DO NOTHING` ever covered this, a discount pointing at a deleted concession
#: would come back as `None` and be counted as a skip, and the run would report a
#: bursary as already posted when it was posted by nobody.
#:
#: Two qualifications, both measured rather than assumed. `full_clean()` refuses
#: that entry a step earlier — `ForeignKey.validate()` looks the row up before any
#: INSERT is issued — so in practice it surfaces as `ValidationError`. And the FK
#: itself is `DEFERRABLE INITIALLY DEFERRED`, as Django creates every foreign key,
#: so were `full_clean()` ever bypassed the violation would fire at **COMMIT**
#: rather than at this statement. Both still kill the run, which is the property
#: that matters: the class is one transaction, so nobody is billed. Neither is
#: "the INSERT fails", which is what the comments here used to say.
#:
#: The backstop is still the one that has to hold: this path is the only one in
#: the module that writes without going through `Model.save()`.
_CONCESSION_ONCE_PER_TERM = (
    '("student_membership_id", "term_id", "source_concession_id") '
    "WHERE \"source_concession_id\" IS NOT NULL AND \"kind\" = 'discount'"
)


def _insert_or_skip(entry, *, conflict_target):
    """INSERT one entry; answer False if `conflict_target` already holds its row.

    The point of doing this rather than catching `IntegrityError` is that
    catching one requires a savepoint to roll back to, and a savepoint per
    concession is issue #85. Postgres declines the row without raising, so there
    is nothing to roll back and no subtransaction to open.

    The column list is read from the model rather than written out, so a field
    added to `FeeLedgerEntry` cannot be silently dropped from this path — which
    is the failure a hand-written INSERT invites.

    **This goes around `Model.save()`, and that is safe here for one reason
    only**: the entry is always new. `FeeLedgerEntry.save()` exists to refuse a
    rewrite of a row that already exists, and an object built two lines above in
    `_post()` has no pk to rewrite. The rule that actually holds is the
    `fees_ledger_append_only` trigger, which fires `BEFORE UPDATE OR DELETE` and
    so is not on this path at all. There are no signals on this model.

    **The `_state` bookkeeping below is not decoration.** `Model.save_base()`
    sets both after every write, and without them the entry handed back would
    still claim to be unsaved — so `save()` called on it later would see
    `_state.adding` and quietly let the rewrite through, defeating the
    append-only guard on exactly the objects this path returns.
    """
    meta = entry._meta
    fields = [f for f in meta.local_concrete_fields if not f.primary_key]
    quote = connection.ops.quote_name
    sql = (
        f"INSERT INTO {quote(meta.db_table)} "
        f"({', '.join(quote(f.column) for f in fields)}) "
        f"VALUES ({', '.join(['%s'] * len(fields))}) "
        f"ON CONFLICT {conflict_target} DO NOTHING "
        f"RETURNING {quote(meta.pk.column)}"
    )
    values = [
        f.get_db_prep_save(f.pre_save(entry, True), connection) for f in fields
    ]
    with connection.cursor() as cursor:
        cursor.execute(sql, values)
        row = cursor.fetchone()
    if row is None:
        return False
    entry.pk = row[0]
    entry._state.adding = False
    entry._state.db = connection.alias
    return True


def _post(*, membership, term, kind, amount_kobo, narration, effective_on,
          reference="", method="", form_key=None, recorded_by=None, reverses=None,
          source_line=None, source_concession=None, skip_on_conflict=None):
    """Create one entry. Every public function below funnels through here.

    `skip_on_conflict` is an `ON CONFLICT` inference clause. Passed, the insert
    declines rather than raises when that index already holds the row, and this
    returns `None` instead of an entry — which is how `_discount()` skips a
    concession another bill already posted without opening a savepoint to roll
    back to. `full_clean()` still runs either way: the funnel is the invariant,
    and the conflict-tolerant path is a different *insert*, not a different
    validation.
    """
    _require_student_of_this_school(membership)
    entry = FeeLedgerEntry(
        term=term,
        kind=kind,
        amount_kobo=amount_kobo,
        narration=narration,
        reference=reference,
        method=method,
        form_key=form_key,
        effective_on=effective_on or timezone.localdate(),
        recorded_by_id=getattr(recorded_by, "pk", recorded_by),
        reverses=reverses,
        source_line=source_line,
        source_concession=source_concession,
        **snapshot_student(membership),
    )
    # `full_clean()` rather than a bare save: the cross-row rules for a reversal
    # live in `Model.clean()` because no check constraint can express "equal and
    # opposite to another row". Excluding nothing, so the field-level rules are
    # asked here too rather than only at the database.
    entry.full_clean(exclude=None, validate_unique=False, validate_constraints=False)
    if skip_on_conflict is not None:
        if not _insert_or_skip(entry, conflict_target=skip_on_conflict):
            return None
        return entry
    entry.save()
    return entry


def _magnitude(amount_kobo):
    if not isinstance(amount_kobo, int) or isinstance(amount_kobo, bool):
        raise NotPositive(
            f"Amounts are whole kobo as an int, not {type(amount_kobo).__name__}. "
            f"A float cannot hold a naira amount exactly, which is the reason "
            f"this column is kobo in the first place."
        )
    if amount_kobo <= 0:
        raise NotPositive(
            f"Pass the amount as a positive number of kobo; the ledger applies "
            f"the sign. Got {amount_kobo}."
        )
    return amount_kobo


class NotInATransaction(transaction.TransactionManagementError):
    """`_charge()` or `_discount()` was called in autocommit, where the missing
    savepoint bites.

    **Deliberately not a `FeeLedgerError`.** Every other refusal in this module
    is one, so that `except FeeLedgerError` means "that entry was not posted,
    carry on if you can". This is not a refusal of an entry; it is a caller in
    the wrong shape, and carrying on is the one thing that must not happen -- a
    loop billing forty-five children in autocommit, catching `FeeLedgerError`
    and continuing past the failure, is the partly-billed class issue #82
    rejected as its option 3. Under `FeeLedgerError` this would be swallowed by
    exactly the handler `charge()`'s docstring sends that caller to.

    **`_discount()` raises it for the same reason and not merely by symmetry.**
    Its skip is an `ON CONFLICT` that declines a row; in autocommit each entry it
    *does* write commits as it is written, so a failure part-way down the
    concession list leaves some families discounted and the rest not, with the
    run's own transaction no longer there to undo it.

    `TransactionManagementError` is Django's own type for this mistake --
    `transaction.set_rollback()` outside an atomic block raises it -- so a
    caller that already handles transaction misuse handles this, and nothing
    has to learn a new name to catch it.
    """


def _charge(membership, term, amount_kobo, *, narration, effective_on=None,
            reference="", recorded_by=None, source_line=None):
    """`charge()` without the savepoint. **`fees.schedules` only.**

    Issue #82. `charge()` is `@transaction.atomic`, so every call inside
    `apply_to_class()`'s one transaction opened and released a savepoint, and a
    45-child three-line bill opened **135 subtransactions**. PostgreSQL caches
    64 subtransaction ids per backend; past that the backend overflows and every
    *other* backend's visibility check against those xids falls back to
    `pg_subtrans`, for as long as the transaction stays open. Measured on a
    45-child class, holding the transaction open and scanning from a second
    connection: **135 subtransactions cost that reader 39.45us per scan and
    8,100,003 `Subtrans` SLRU lookups; zero cost it 12.29us and 1.**

    **The second row is a control, not this function.** It wrote the same 135
    rows in one statement, which is how the row count was held fixed while the
    subxid count changed. This function writes 135 statements and opens no
    savepoints, and it was not timed -- deliberately: the reader pays per subxid
    its writer left uncached, and this function leaves none, so the count is the
    mechanism and the count is what the tests assert. Do not read 12.29us as a
    measurement of this path.

    **The savepoint bought the charge loop nothing**, and that is structural
    rather than a judgement: the loop catches nothing, so an `IntegrityError`
    here rolls back to the savepoint and then keeps propagating out of
    `apply_to_class()`'s own atomic block, which aborts everything the savepoint
    was protecting. Rolling back to a savepoint you are about to discard is not
    a guarantee.

    **`charge()` keeps its decorator, and this is why there are two functions**
    rather than one with the decorator removed. A caller that is inside a larger
    transaction, catches `FeeLedgerError` and carries on needs the failed entry
    rolled back without poisoning what it is wrapped in. `apply_to_class()` does
    not — it is the transaction — but `charge()`'s docstring has said since the
    schedule work that *"the second caller is the one that will not know"*, and
    that caller must find the safe function under the obvious name.

    **`fees.schedules.apply_to_class()` is the only supported caller**, and it
    holds the schedule row lock. Anything else wanting a charge wants `charge()`.

    **That precondition is checked below, not merely written here.** A docstring
    cannot stop a caller in autocommit, and in autocommit the missing savepoint
    stops being a saving and becomes a partly-billed class: each entry commits
    as it is written, so a failure on the fortieth child leaves thirty-nine
    families charged and the rest not -- option 3 again, arriving with no
    exception to catch and nothing red. This is not a new rule, so it is not a
    behaviour change either: a caller the check refuses was already broken. And
    `charge()` cannot trip it, its decorator having opened the block before it
    delegates.
    """
    if not transaction.get_connection().in_atomic_block:
        raise NotInATransaction(
            "_charge() opens no savepoint and has no transaction of its own, so "
            "in autocommit every entry commits as it is written and a failure "
            "part-way through a class bills some of it -- the outcome issue #82 "
            "rejected as option 3. Call it inside a transaction the caller owns "
            "(`schedules.apply_to_class()` is @transaction.atomic and is the "
            "only supported caller), or call charge(), which opens one."
        )
    if source_line is not None and source_line.schedule.term_id != term.pk:
        raise NotThisTermsLine(
            f"Line {source_line.pk} belongs to {source_line.schedule}, which is "
            f"another term's bill; this charge is for {term}. Charging it here "
            f"would fill that child's slot in "
            f"a_schedule_line_charges_a_child_once, and the run that should "
            f"bill them would report a skip instead."
        )
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.CHARGE,
        amount_kobo=_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        reference=reference,
        recorded_by=recorded_by,
        source_line=source_line,
    )


@transaction.atomic
def charge(membership, term, amount_kobo, *, narration, effective_on=None,
           reference="", recorded_by=None, source_line=None):
    """Bill a student. Increases what the family owes.

    `source_line` is passed by `fees.schedules` and left null by every hand-typed
    charge. It is what makes "everything this line of the bill did" a question
    with an answer, and what the idempotency index keys on.

    **A caller passing `source_line` must hold the schedule's row lock**, the way
    `schedules.apply_to_class()` does. `a_schedule_line_charges_a_child_once`
    refuses a second charge for one child and line, and outside that lock two
    writers can both pass a skip-check and one will meet the index. Today this
    module has exactly one such caller, so the race is not reachable; the note is
    here because the second caller is the one that will not know.

    Raises `NotThisTermsLine` if the line belongs to another term's bill.

    The savepoint this decorator opens is the whole difference between this and
    `_charge()`: it is what lets a caller inside a larger transaction catch a
    refusal and carry on. `apply_to_class()` is the one caller that provably
    does not need it, and issue #82 is what that savepoint cost.

    **The term check is no longer below.** It moved into `_charge()` with the
    body, so both functions ask it and the caller that skips this decorator
    still gets it. It is asked in Python rather than left to a constraint
    because no constraint can reach across three tables to ask it, and it is
    free on the hot path -- which is now `_charge()`'s, not this one's:
    `apply_to_class()` reads its lines through `locked.lines.all()`, and a
    reverse manager primes each line's `schedule` from the instance it came
    from, so this compares two integers already in memory.
    """
    return _charge(
        membership,
        term,
        amount_kobo,
        narration=narration,
        effective_on=effective_on,
        reference=reference,
        recorded_by=recorded_by,
        source_line=source_line,
    )


@transaction.atomic
def record_payment(membership, term, amount_kobo, *, method, narration="Payment received",
                   effective_on=None, reference="", recorded_by=None, form_key=None):
    """Record money received. Reduces what the family owes.

    `method` is required, and a bank transfer needs its `reference` — see
    `NoMethod`. A caller posting from a form passes its `form_key`, and wants
    `record_payment_once()`, which turns the second click into the first
    click's entry.
    """
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.PAYMENT,
        amount_kobo=-_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        reference=reference,
        method=_require_method(method, reference),
        form_key=form_key,
        recorded_by=recorded_by,
    )


def _is_the_form_key_colliding(exc) -> bool:
    """Did `a_form_posts_once` fire, or something else?

    `academics.services._is_the_placement_colliding()` has the long version:
    `IntegrityError` says a rule refused the row and not which, and only one
    of them means "this form was already posted".
    """
    cause = getattr(exc, "__cause__", None)
    diag = getattr(cause, "diag", None)
    return getattr(diag, "constraint_name", None) == "a_form_posts_once"


def _once(post, *, form_key, what, **same):
    """Post from a form at most once. Returns `(entry, posted)`.

    `post` is the atomic poster, bound to everything but the key. `same` is
    what the earlier entry must match for a second submission to be the first
    one again — a double click, or a retry of a request whose answer never
    arrived — rather than a page that reused a key it should have replaced.

    **The unique index is the whole mechanism**, not a read-then-write: two
    submissions racing each other both pass any read, and only the index sees
    them both. The poster's savepoint is what lets the refused insert roll back
    without taking the caller's transaction with it — one savepoint per form,
    which is not issue #82's shape (that was one per child in a loop).
    """
    try:
        return post(form_key=form_key), True
    except IntegrityError as exc:
        if not _is_the_form_key_colliding(exc):
            raise
    earlier = FeeLedgerEntry.objects.get(form_key=form_key)
    if any(getattr(earlier, field) != value for field, value in same.items()):
        raise FormAlreadyUsed(
            f"This form was already used to record a different {what}. Nothing "
            f"new was recorded; reload the page and enter it again."
        )
    return earlier, False


def record_payment_once(membership, term, amount_kobo, *, method, form_key,
                        effective_on=None, reference="", recorded_by=None):
    """`record_payment()` for a form: the same form twice is one payment.

    Returns `(entry, posted)`; `posted` is False when this form had already
    posted, and the entry is the one the first submission posted. Raises
    `FormAlreadyUsed` when the key posted a *different* payment. See `_once()`.
    """
    return _once(
        lambda form_key: record_payment(
            membership,
            term,
            amount_kobo,
            method=method,
            effective_on=effective_on,
            reference=reference,
            recorded_by=recorded_by,
            form_key=form_key,
        ),
        form_key=form_key,
        what="payment",
        kind=FeeEntryKind.PAYMENT,
        student_membership_id=membership.pk,
        term_id=term.pk,
        amount_kobo=-amount_kobo,
        method=method,
        reference=reference,
    )


def discount_once(membership, term, amount_kobo, *, reason, form_key,
                  recorded_by=None):
    """A discount given by hand, from a form: the same form twice is one.

    Decided 2026-09-24 (fees 2(a) and 4): it says why — `reason`, required,
    becomes the narration (`NoReason`) — and it is kept from a double click
    exactly as a payment is, because a second copy of the same discount is
    money the school did not mean to waive.
    """
    narration = _require_reason(reason)
    return _once(
        lambda form_key: discount(
            membership,
            term,
            amount_kobo,
            narration=narration,
            recorded_by=recorded_by,
            form_key=form_key,
        ),
        form_key=form_key,
        what="discount",
        kind=FeeEntryKind.DISCOUNT,
        student_membership_id=membership.pk,
        term_id=term.pk,
        amount_kobo=-amount_kobo,
        narration=narration,
    )


def _discount(membership, term, amount_kobo, *, narration, effective_on=None,
              recorded_by=None, source_concession=None):
    """`discount()` without the savepoint. **`fees.schedules` only.**

    Issue #85, and the residual issue #82 deliberately left behind. `discount()`
    is `@transaction.atomic`, so calling it once per concession inside
    `apply_to_class()`'s one transaction opened one subtransaction per
    concession. PostgreSQL caches 64 subtransaction ids per backend; past that
    the backend overflows and every *other* backend's visibility check against
    those xids falls back to `pg_subtrans` for as long as the transaction is
    open.

    **The savepoint here was load-bearing, which is why #82 could not simply
    delete it the way it deleted the charge loop's.** The collision handler at
    the foot of the discount loop caught the unique violation from
    `a_concession_discounts_a_child_once_per_term` and needed the failed entry
    rolled back to a savepoint so the run survived as a skip — without it one
    collision killed the whole run and a class went unbilled.

    So the savepoint goes only because the *catch* goes: `_insert_or_skip()`
    asks Postgres to decline the row instead of refusing it, and a row that was
    never refused needs nothing rolled back. The skip is preserved exactly; what
    is gone is the subtransaction that used to pay for it.

    Measured on this hardware, a transaction held open while a second backend
    scanned 20,000 times, with a committer thread running so the subxids sat
    below the reader's snapshot and each arm paired against a control writing
    **the same number of rows** in one statement:

    | subxids | reader us/scan | control us/scan | `Subtrans` blks_hit |
    |---|---|---|---|
    | 45 | 7.22 | 6.39 | **0** |
    | 66 | 16.36 | 6.84 | 2,640,000 |
    | 90 | 19.06 | 8.83 | 3,600,000 |
    | 135 | 25.48 | 8.63 | 5,400,000 |

    **It is a step at 64, not a slope**: 45 subtransactions cost a concurrent
    reader nothing measurable and produce no SLRU lookups at all, and 66 cost it
    2.4x its control. `blks_read` was 0 throughout — these are in-memory SLRU
    lookups, not disk I/O, and reporting them as I/O overstates the damage.

    **This function was not timed and the control column is not a timing of
    it.** The control is what held the row count fixed while the subxid count
    moved. The mechanism is the count, and the count is what the tests assert.

    **How many there can be is bounded by nothing.** `FeeConcession` has no
    unique constraint on `student_membership_id` and `fees/models.py:246` says so
    deliberately — a bursary and a sibling discount are two facts and two
    DISCOUNT entries. So the count is measured in concessions granted, not in
    children, and the roster caps it no more than it caps anything else. **This
    fix was chosen against what the schema permits, not against a measured
    distribution of concessions per child: no school data exists yet.** See
    issue #85.

    **`discount()` keeps its decorator**, for the reason `_charge()`'s docstring
    gives: a caller inside a larger transaction that catches `FeeLedgerError` and
    carries on needs the failed entry rolled back without poisoning what it is
    wrapped in. `apply_to_class()` does not, because it *is* the transaction.

    Returns the posted entry, or **`None` if another bill in this term already
    posted this child's discount for this concession** — which is a skip and not
    a failure. `discount()` cannot return `None`.
    """
    if not transaction.get_connection().in_atomic_block:
        raise NotInATransaction(
            "_discount() opens no savepoint and has no transaction of its own, "
            "so in autocommit every entry commits as it is written and a failure "
            "part-way through a class discounts some of it. Call it inside a "
            "transaction the caller owns (`schedules.apply_to_class()` is "
            "@transaction.atomic and is the only supported caller), or call "
            "discount(), which opens one."
        )
    if (
        source_concession is not None
        and source_concession.student_membership_id != membership.pk
    ):
        raise NotThisStudentsConcession(
            f"Concession {source_concession.pk} belongs to membership "
            f"{source_concession.student_membership_id}, not to {membership.pk}. "
            f"The index is keyed per student, so this would post, and "
            f"'everything this concession did' would answer with two children."
        )
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.DISCOUNT,
        amount_kobo=-_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        recorded_by=recorded_by,
        source_concession=source_concession,
        skip_on_conflict=_CONCESSION_ONCE_PER_TERM,
    )


@transaction.atomic
def discount(membership, term, amount_kobo, *, narration, effective_on=None,
             recorded_by=None, source_concession=None, form_key=None):
    """Reduce what is owed without money changing hands.

    A bursary, a staff child's concession, a sibling discount. Its own kind
    rather than a negative charge, because "we waived it" and "they paid it" are
    different facts and a school's books have to be able to tell them apart.

    Raises `NotThisStudentsConcession` if the concession is another child's.
    """
    if (
        source_concession is not None
        and source_concession.student_membership_id != membership.pk
    ):
        raise NotThisStudentsConcession(
            f"Concession {source_concession.pk} belongs to membership "
            f"{source_concession.student_membership_id}, not to {membership.pk}. "
            f"The index is keyed per student, so this would post, and "
            f"'everything this concession did' would answer with two children."
        )
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.DISCOUNT,
        amount_kobo=-_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        recorded_by=recorded_by,
        source_concession=source_concession,
        form_key=form_key,
    )


@transaction.atomic
def refund(membership, term, amount_kobo, *, method, narration="Refund",
           effective_on=None, reference="", recorded_by=None):
    """Hand money back. Increases what the family owes, back towards zero.

    The sign is the surprising half and it is right: a family sitting at −₦50,000
    who are handed ₦50,000 in cash are square, not −₦100,000. A refund moves the
    balance the same direction a charge does, which is why `INCREASES_DEBT` names
    both.

    **Not the default answer to a mid-term withdrawal.** Money is carried, not
    returned: the credit simply stands against the child, which needs no
    machinery at all and is what most schools do. This exists so that a school
    which *does* return cash can say so, rather than posting a REVERSAL of a
    payment that was genuinely received — those are different facts, the same way
    a discount and a payment are.

    A school that pro-rates a withdrawal posts a REVERSAL or a DISCOUNT by hand.
    The ledger records what happened; it holds no refund policy.
    """
    return _post(
        membership=membership,
        term=term,
        kind=FeeEntryKind.REFUND,
        amount_kobo=_magnitude(amount_kobo),
        narration=narration,
        effective_on=effective_on,
        reference=reference,
        method=_require_method(method, reference),
        recorded_by=recorded_by,
    )


#: The narration column's own width, read from the field so the two cannot
#: drift apart.
_NARRATION_MAX = FeeLedgerEntry._meta.get_field("narration").max_length


def _inherited_narration(narration):
    """`"Reversal of: X"`, trimmed to the column rather than failing to save.

    `FeeScheduleLine.description` and `FeeLedgerEntry.narration` are both 255,
    and `apply_to_class()` copies one into the other verbatim -- so a line
    described in 243 characters or more posts a charge whose reversal is
    thirteen characters too long. That was unreachable while every narration was
    hand-typed, and this PR made it reachable.

    It matters more than a truncation usually would, because of *how* it failed:
    `full_clean()` raises `ValidationError`, which is not a `FeeLedgerError`. A
    caller writing `except FeeLedgerError` -- the contract this module's
    docstring insists on -- would not have caught it, and the charge simply
    could not be undone. Trimming keeps the prefix, which is the part a reader
    needs, and marks the cut so nobody reads the tail as the whole description.
    """
    inherited = f"Reversal of: {narration}"
    if len(inherited) <= _NARRATION_MAX:
        return inherited
    return inherited[: _NARRATION_MAX - 1] + "\u2026"


def undo(entry, *, reason, recorded_by=None):
    """`reverse_entry()` as a person does it: with the reason, which becomes
    the reversal's narration. Raises `NoReason` without one, before anything
    is written."""
    return reverse_entry(entry, narration=_require_reason(reason), recorded_by=recorded_by)


@transaction.atomic
def reverse_entry(entry, *, narration=None, effective_on=None, recorded_by=None,
                  membership=None):
    """Undo `entry` by posting its exact opposite. Returns the new entry.

    The only correction there is, and deliberately the only one. There is no
    "edit the amount" and no free-form adjustment: a charge raised for the wrong
    amount is reversed in full and the right one posted fresh, which leaves both
    the mistake and the fix legible a year later. An adjustment of "-30,000
    because the first number was wrong" tells a reader the difference and never
    what actually happened.

    The identity snapshot is taken from `entry` rather than from a live lookup,
    unless a `membership` is passed. A reversal is part of the original story and
    should read the way the original read — including when the student has since
    left and their membership has ended.

    **And it inherits the source**, for the same reason it inherits `reference`:
    a reversal of a schedule charge is still *about* that line of the bill, so
    "everything this line did" has to return the mistake and the fix together.
    The uniqueness indexes are conditioned on `kind` precisely so that carrying
    the source across does not collide with the entry being undone.
    """
    # Locked and re-read before deciding, because "has this been reversed
    # already?" is a question about the present, and two bursars clicking undo
    # on the same charge is exactly the race this guards. `select_for_update()`
    # on the entry itself; `.order_by()` is not needed here because
    # `FeeLedgerEntry.Meta.ordering` sorts by its own columns and joins nothing —
    # the trap docs/membership.md records for `Membership` does not apply.
    #
    # **And no `select_related("term")`.** `select_for_update()` locks every
    # table it joins, so that took `FOR UPDATE` on the `academics_term` row.
    # Issue #78 scoped the joined lock as waste; `apply_to_class()` is what turns
    # it into contention. Every entry that run inserts takes `FOR KEY SHARE` on
    # the same term row for its foreign-key check and holds it to commit, and
    # `FOR KEY SHARE` conflicts with `FOR UPDATE`: one bursar clicking undo on an
    # unrelated payment blocks for the length of a forty-five-child billing run,
    # and in the other order the billing run stalls on its first insert. The
    # reversal needs the term's *id*, which the locked row already carries, so
    # the join bought nothing at all.
    locked = FeeLedgerEntry.objects.select_for_update().get(pk=entry.pk)

    if locked.kind == FeeEntryKind.REVERSAL:
        raise CannotReverse(
            "That entry is itself a reversal. Reverse the original entry, or "
            "post a fresh one — undoing an undo is a way to lose track of what "
            "actually happened."
        )
    if FeeLedgerEntry.objects.filter(reverses=locked).exists():
        raise AlreadyReversed(
            f"Ledger entry {locked.pk} has already been reversed. Post a new "
            f"entry if something further needs correcting."
        )

    if membership is not None:
        identity = {}
        snapshot = membership
    else:
        identity = {
            "student_membership_id": locked.student_membership_id,
            "student_name": locked.student_name,
            "student_reference": locked.student_reference,
        }
        snapshot = None

    reversal = FeeLedgerEntry(
        # `term_id`, not `term`: the id is already on the locked row, and
        # touching `.term` would spend a query fetching a row nothing here reads.
        term_id=locked.term_id,
        kind=FeeEntryKind.REVERSAL,
        amount_kobo=-locked.amount_kobo,
        narration=narration or _inherited_narration(locked.narration),
        reference=locked.reference,
        source_line_id=locked.source_line_id,
        source_concession_id=locked.source_concession_id,
        effective_on=effective_on or timezone.localdate(),
        recorded_by_id=getattr(recorded_by, "pk", recorded_by),
        reverses=locked,
        **(identity if snapshot is None else snapshot_student(snapshot)),
    )
    reversal.full_clean(exclude=None, validate_unique=False, validate_constraints=False)
    reversal.save()
    return reversal


__all__ = [
    "AlreadyReversed",
    "CannotReverse",
    "FeeLedgerError",
    "FormAlreadyUsed",
    "LedgerIsAppendOnly",
    "NoMethod",
    "NoReason",
    "NotPositive",
    "NotThisSchoolsStudent",
    "NotThisStudentsConcession",
    "NotThisTermsLine",
    "charge",
    "discount",
    "discount_once",
    "record_payment",
    "record_payment_once",
    "refund",
    "reverse_entry",
    "snapshot_student",
    "undo",
]
