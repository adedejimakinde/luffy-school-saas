"""A dedicated virtual account for each child, made against the school's split.

Where a family pays: one bank account per child, in the child's name, that
settles to the **school's own** bank account through the split
`fees.bank.connect()` made (100% to the school, the school bearing Paystack's
fees). Classnode holds nothing.

- **Needs the school's bank first** (`NoBank`): there is no split to settle
  through until a bursar has connected one.
- **One per child, made once.** The school's row is locked across the Paystack
  calls, so two people pressing the button make one account, and asking again
  returns the account that is there. The account is never edited or deleted.
- **Routed by a public row.** A webhook arrives on the portal with only an
  account number; `schools.PaystackRoute` says whose it is. It is written in the
  same transaction as the school's `VirtualAccount`, so neither exists alone.

If Paystack made the customer and then failed to make the account, the customer
is an orphan at Paystack (no money can reach it) and the next attempt asks again.
"""

from django.conf import settings
from django.db import transaction

from schools.models import PaystackRoute, School

from . import bank, paystack
from .models import VirtualAccount


class VirtualAccountError(Exception):
    """This account was refused, with a sentence for the person. Nothing was made."""


class NoBank(VirtualAccountError):
    def __init__(self):
        super().__init__("Connect the school's bank account before making accounts for children.")


def for_child(student_membership_id):
    return VirtualAccount.objects.filter(student_membership_id=student_membership_id).first()


def _names(full_name):
    parts = (full_name or "").split()
    if not parts:
        return "Student", "Student"
    if len(parts) == 1:
        return parts[0], parts[0]
    return " ".join(parts[:-1]), parts[-1]


def ensure(school, actor, child):
    """`(account, created)` for `child`, a STUDENT membership at `school`."""
    with transaction.atomic():
        School.objects.select_for_update().filter(pk=school.pk).order_by().first()
        existing = for_child(child.pk)
        if existing is not None:
            return existing, False
        connected = bank.current()
        if connected is None:
            raise NoBank()
        first, last = _names(child.name)
        try:
            customer_code = paystack.create_customer(
                email=f"{school.slug}-{child.pk}@{settings.PAYSTACK_CUSTOMER_EMAIL_DOMAIN}",
                first_name=first,
                last_name=last,
            )
            made = paystack.create_dedicated_account(
                customer_code=customer_code,
                split_code=connected.split_code,
                preferred_bank=settings.PAYSTACK_DVA_BANK,
            )
        except paystack.PaystackRefused as exc:
            raise VirtualAccountError(f"Paystack would not make that account: {exc}")
        account = VirtualAccount.objects.create(
            student_membership_id=child.pk,
            customer_code=customer_code,
            account_number=made["account_number"],
            account_name=made["account_name"],
            bank_name=made["bank_name"],
            split_code=connected.split_code,
            created_by_id=actor.pk,
            created_by_name=actor.get_full_name() or str(actor),
        )
        PaystackRoute.objects.create(account_number=account.account_number, school=school)
        return account, True


def pay_into(student_membership_id):
    """`{bank_name, account_number, account_name}` for a child, or None."""
    account = for_child(student_membership_id)
    if account is None:
        return None
    return {
        "bank_name": account.bank_name,
        "account_number": account.account_number,
        "account_name": account.account_name,
    }


def pay_into_sentence(student_membership_id):
    """` Pay into: Wema Bank 1234567890, Ada Bello.` for a message, or `""`.

    Leading space and trailing full stop, so a message can end with it or run on
    from it; nothing at all when the child has no account.
    """
    line = pay_into(student_membership_id)
    if line is None:
        return ""
    return f" Pay into: {line['bank_name']} {line['account_number']}, {line['account_name']}."


#: How many accounts one press makes at most. Each is two calls to Paystack
#: (a customer, then the account) made one after another inside a web request,
#: so a big class is done in batches and the person is told how many are left.
CLASS_BATCH = 20


class ClassResult:
    """What one press of "Create accounts for this class" did."""

    def __init__(self):
        self.made = 0
        self.skipped = 0
        self.failed = []  # [(student_membership_id, student name, sentence)]
        self.remaining = 0
        #: Set when Paystack itself was down or unset, which stops the batch: a sentence, never Paystack's words.
        self.stopped = None


def ensure_for_class(school, actor, group, term, *, limit=None):
    """Make the missing virtual accounts for the children in `group` this `term`.

    **Children who already have one are skipped and counted**, so pressing it twice
    makes nothing twice: `ensure()` is the same idempotent call the child's own page
    makes, one child at a time, each in its own transaction, so a failure for one
    child rolls back that child alone and the rest go on. Every failure is reported
    by name with its sentence.

    At most `limit` are made a press; the rest are `remaining`. If Paystack is
    unreachable, or refuses the platform's key, the batch **stops** (the same call
    would fail for every child) with `stopped` set and the untried children counted
    in `remaining`. Needs the school's bank (`NoBank`) when there is anything to make.
    """
    from academics.models import ClassPlacement
    from accounts.models import Membership, Role

    limit = CLASS_BATCH if limit is None else limit
    ids = ClassPlacement.objects.filter(class_group=group, term=term).values_list(
        "student_membership_id", flat=True
    )
    children = sorted(
        Membership.objects.filter(pk__in=list(ids), school=school, role=Role.STUDENT.value).select_related("user"),
        key=lambda c: (c.name.lower(), c.pk),
    )
    have = set(
        VirtualAccount.objects.filter(student_membership_id__in=[c.pk for c in children]).values_list(
            "student_membership_id", flat=True
        )
    )
    result = ClassResult()
    result.skipped = sum(1 for c in children if c.pk in have)
    pending = [c for c in children if c.pk not in have]
    if not pending:
        return result
    if bank.current() is None:
        raise NoBank()

    batch, result.remaining = pending[:limit], max(len(pending) - limit, 0)
    for position, child in enumerate(batch):
        try:
            _, created = ensure(school, actor, child)
        except VirtualAccountError as exc:
            result.failed.append((child.pk, child.name, str(exc)))
        except (paystack.PaystackUnavailable, paystack.PaystackNotConfigured):
            result.stopped = "Paystack is not available right now, so the rest were not tried."
            result.remaining += len(batch) - position
            break
        else:
            if created:
                result.made += 1
            else:
                result.skipped += 1  # somebody made it a moment ago
    return result


def missing_in_class(school, group, term):
    """How many children in `group` this `term` have no account yet."""
    from academics.models import ClassPlacement
    from accounts.models import Membership, Role

    ids = list(
        ClassPlacement.objects.filter(class_group=group, term=term).values_list("student_membership_id", flat=True)
    )
    students = set(
        Membership.objects.filter(pk__in=ids, school=school, role=Role.STUDENT.value).values_list("pk", flat=True)
    )
    have = set(VirtualAccount.objects.filter(student_membership_id__in=students).values_list("student_membership_id", flat=True))
    return len(students - have)
