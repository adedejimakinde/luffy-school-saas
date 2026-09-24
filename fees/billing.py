"""Bills and concessions, as the bursar sets them on a screen. B2.

`fees.schedules.apply_to_class()` has posted a class's bill since #79, and the
bill and the concessions it reads were rows with no way in but a shell. This
module is the way in, for `fees/api.py` and for anything else that sets them,
so a management command meets the same refusals as the page.

**A bill is a template, and editing it is ordinary.** Adding a line, renaming
one, correcting its amount or removing an unused one changes what the *next*
application posts; charges already posted stand, because they are the record
(`docs/fees.md`, "The template is not the record"). The one refusal is removing
a line that has charged somebody: `FeeLedgerEntry.source_line` is `PROTECT`,
and this says so in a sentence first.

**A concession is not a template any more.** Issue #75, decided 2026-09-24: it
is granted once and never edited or deleted, and revoking it writes a
`FeeConcessionRevocation` saying who, when and why. `revoke_concession()`
refuses without a reason and without a person, and the table's own check
refuses a blank reason from anywhere.

**Who** is not asked here, as `fees.services` does not ask it: the routes ask
`fees.authority` before calling in, and a management command has no actor.
"""

from django.db import IntegrityError, transaction
from django.db.models import Max, ProtectedError

from . import schedules, services
from .models import FeeConcession, FeeConcessionRevocation, FeeSchedule, FeeScheduleLine

_DESCRIPTION_MAX = FeeScheduleLine._meta.get_field("description").max_length


class BillingError(services.FeeLedgerError):
    """Base for this module's refusals. A `FeeLedgerError`, so that `except
    FeeLedgerError` still means "nothing was written"."""


class NoDescription(BillingError):
    """A bill line with nothing to say what it is for. The description becomes
    every charge's narration."""


class LineAlreadyOnBill(BillingError):
    """The bill already has a line of that name, for a different amount.

    The same name and the same amount is a double click, and the answer is the
    line the first click added. A different amount is two answers to "what is
    the PTA levy", and `a_bill_names_each_line_once` holds that at the database.
    """


class LineHasCharged(BillingError):
    """A line that has charged somebody cannot be removed: the charges name it,
    and `FeeLedgerEntry.source_line` is `PROTECT`."""


class AlreadyRevoked(BillingError):
    """The concession was revoked already. A concession is revoked once; to
    give the child one again is a new grant."""


class RevocationNeedsAPerson(BillingError):
    """A revocation with nobody behind it. The table allows a null revoker only
    for the rows its migration backfilled, where nobody had been recorded."""


def _constraint_of(exc):
    cause = getattr(exc, "__cause__", None)
    return getattr(getattr(cause, "diag", None), "constraint_name", None)


# -- the bill -----------------------------------------------------------------


def bill_for(class_group, term):
    """This class's bill for this term, or `None` when nobody has started one."""
    return FeeSchedule.objects.filter(class_group=class_group, term=term).first()


def open_bill(class_group, term):
    """The class's bill for the term, started empty if there is none.

    `get_or_create()`, whose own retry on `IntegrityError` is what makes two
    bursars starting the same bill at once end with one:
    `one_fee_schedule_per_class_per_term` refuses the second insert and the
    loser reads the winner's row.
    """
    schedule, _ = FeeSchedule.objects.get_or_create(class_group=class_group, term=term)
    return schedule


def _require_description(description):
    text = (description or "").strip()
    if not text:
        raise NoDescription("Say what the line is for: \"Tuition\", \"PTA levy\".")
    if len(text) > _DESCRIPTION_MAX:
        raise NoDescription(f"Keep the description under {_DESCRIPTION_MAX} characters.")
    return text


def add_line(schedule, description, amount_kobo):
    """Add a line to the end of the bill. Returns `(line, added)`.

    `added` is False when the bill already had this line at this amount — a
    double click — and the line is that one. The same name at a different
    amount is `LineAlreadyOnBill`.
    """
    description = _require_description(description)
    amount_kobo = services._magnitude(amount_kobo)
    last = schedule.lines.aggregate(last=Max("position"))["last"]
    try:
        with transaction.atomic():
            line = FeeScheduleLine.objects.create(
                schedule=schedule,
                description=description,
                amount_kobo=amount_kobo,
                position=0 if last is None else last + 1,
            )
            return line, True
    except IntegrityError as exc:
        if _constraint_of(exc) != "a_bill_names_each_line_once":
            raise
    line = schedule.lines.get(description=description)
    if line.amount_kobo != amount_kobo:
        raise LineAlreadyOnBill(
            f"This bill already has a line called \"{description}\", for a "
            f"different amount. Change that line instead."
        )
    return line, False


def change_line(line, *, description, amount_kobo):
    """Rename a line or correct its amount, for the next application.

    **Charges already posted do not move**, and the page says so: a child
    charged ₦15,000 for the levy stays charged ₦15,000 when the line becomes
    ₦12,000, and a re-application skips them, because they have this line's
    charge. Correcting them is a reversal and a charge by hand — the practical
    rule `docs/fees.md` gives under "A reversed schedule charge".
    """
    line.description = _require_description(description)
    line.amount_kobo = services._magnitude(amount_kobo)
    try:
        with transaction.atomic():
            line.save(update_fields=["description", "amount_kobo", "updated_at"])
    except IntegrityError as exc:
        if _constraint_of(exc) != "a_bill_names_each_line_once":
            raise
        raise LineAlreadyOnBill(
            f"This bill already has a line called \"{line.description}\"."
        ) from exc
    return line


def remove_line(line):
    """Remove a line nobody has been charged by."""
    refusal = LineHasCharged(
        f"\"{line.description}\" has already charged children on this bill, and "
        f"those charges name it. Undo them first if the line should not have "
        f"been billed, or leave it and change it for whoever is billed next."
    )
    if line.entries.exists():
        raise refusal
    try:
        line.delete()
    except ProtectedError as exc:
        # A charge committed between the check and the delete: Django's
        # collector reads the protected relation again before it deletes.
        raise refusal from exc


def apply(schedule, *, by):
    """Charge the class. `fees.schedules.apply_to_class()`, which says what it
    skips and why; this is only the name the routes call it by."""
    return schedules.apply_to_class(schedule, by=by)


# -- concessions --------------------------------------------------------------


def grant_concession(membership, amount_kobo, *, reason, form_key, by=None):
    """Grant a child a standing discount, from a form. Returns
    `(concession, granted)`.

    The same form twice is one concession — `a_concession_form_grants_once` —
    for the reason a payment form posts once: a double click on "Grant" would
    otherwise discount the child twice every term from now on. The same key
    with different details is `services.FormAlreadyUsed`.
    """
    services._require_student_of_this_school(membership)
    reason = services._require_reason(reason)
    amount_kobo = services._magnitude(amount_kobo)
    try:
        with transaction.atomic():
            concession = FeeConcession.objects.create(
                student_membership_id=membership.pk,
                amount_kobo=amount_kobo,
                reason=reason,
                granted_by_id=getattr(by, "pk", by),
                form_key=form_key,
            )
            return concession, True
    except IntegrityError as exc:
        if _constraint_of(exc) != "a_concession_form_grants_once":
            raise
    earlier = FeeConcession.objects.get(form_key=form_key)
    if (earlier.student_membership_id, earlier.amount_kobo, earlier.reason) != (
        membership.pk,
        amount_kobo,
        reason,
    ):
        raise services.FormAlreadyUsed(
            "This form was already used to grant a different concession. Nothing "
            "new was granted; reload the page and enter it again."
        )
    return earlier, False


def revoke_concession(concession, *, reason, by):
    """Stop a concession, saying why. Issue #75.

    Writes a `FeeConcessionRevocation` — who, when, why — and leaves the
    concession row exactly as it was granted. Discounts already posted stand;
    the next application of a bill gives no more.

    Refused without a reason (`services.NoReason`), without a person
    (`RevocationNeedsAPerson`), and a second time (`AlreadyRevoked`). The
    one-to-one is what holds the last when two bursars revoke at once; the
    check first is what gives the sentence.
    """
    reason = services._require_reason(reason)
    if getattr(by, "pk", None) is None:
        raise RevocationNeedsAPerson(
            "A revocation says who made it. Revoke it signed in as yourself."
        )

    def already():
        earlier = FeeConcessionRevocation.objects.filter(concession=concession).first()
        if earlier is None:
            return None
        return AlreadyRevoked(
            f"This concession was already revoked on "
            f"{earlier.revoked_at:%d %B %Y}: \"{earlier.reason}\". To give the "
            f"child a discount again, grant a new one."
        )

    refusal = already()
    if refusal:
        raise refusal
    try:
        with transaction.atomic():
            return FeeConcessionRevocation.objects.create(
                concession=concession,
                reason=reason,
                revoked_by_id=by.pk,
                revoked_by_name=by.full_name or by.username,
            )
    except IntegrityError:
        refusal = already()
        if refusal is None:
            raise
        raise refusal


__all__ = [
    "AlreadyRevoked",
    "BillingError",
    "LineAlreadyOnBill",
    "LineHasCharged",
    "NoDescription",
    "RevocationNeedsAPerson",
    "add_line",
    "apply",
    "bill_for",
    "change_line",
    "grant_concession",
    "open_bill",
    "remove_line",
    "revoke_concession",
]
