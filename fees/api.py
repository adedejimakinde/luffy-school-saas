"""HTTP for the school's books: balances, one child's account, a payment, a
discount, a reversal and a receipt (B1); and a class's bill, charging it, and a
child's concessions (B2, from "B2: bills and concessions" down).

**Two refusals, and which one a caller gets is the disclosure decision.**
Anybody who may not read the books — a teacher, a parent, a student — gets a
flat 404 before anything is looked up, the answer the broadsheet and the
absence list give: "you may not" must read the same as "there is no such
child", or the routes are a directory of the school's children and their
debts. The principal and the vice principal (academic) read the books, so they
already know a child's account exists; when they try to *write*, they are told
so in a sentence (403).

**The child is looked up with `school=` in the query.** `student_membership_id`
is a bare id into the shared `Membership` table, so a lookup without the school
would find another school's child — and answer with her name — on this school's
host. The services refuse to *post* against her
(`accounts.students.why_not_a_student_here()`), but by then the read would
already have told the caller who she is.

**Money arrives as the naira somebody typed** and is turned into kobo by
`fees.money`, which refuses rather than rounds. It leaves as integer kobo: the
page formats it, and a float never touches it on either side.
"""

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.utils import timezone
from ninja import Query, Router, Schema

from academics.models import ClassGroup, ClassPlacement, Term
from accounts.models import Membership, Role, User
from accounts.session import session_auth

from . import billing, schedules, services
from .authority import may_read, may_write, receipt_number
from .models import (
    FeeConcession,
    FeeEntryKind,
    FeeLedgerEntry,
    FeeSchedule,
    FeeScheduleLine,
    PaymentMethod,
)
from .money import NotAnAmount, kobo_from_naira

router = Router(auth=session_auth)


# -- shapes -------------------------------------------------------------------


class MessageOut(Schema):
    detail: str


class TermChoiceOut(Schema):
    term_id: int
    term: str
    is_current: bool


class ClassSummaryOut(Schema):
    class_group_id: int
    class_group: str
    children: int


class BooksOut(Schema):
    """The way in: which term, and which classes have children in it."""

    terms: List[TermChoiceOut]
    term_id: Optional[int]
    term: Optional[str]
    may_write: bool
    classes: List[ClassSummaryOut]
    #: The bursar or an administrator, at a school that sends fee reminders
    #: (docs/messaging.md D10). The page offers "Remind families" only then.
    may_remind: bool = False


class ChildBalanceOut(Schema):
    student_membership_id: int
    student: str
    reference: str
    #: The whole account, every term — what the school is owed by this family
    #: today, which is the number withholding reads too. Positive is owed;
    #: negative is in credit; the page says which in words.
    balance_kobo: int


class ClassBalancesOut(Schema):
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    children: List[ChildBalanceOut]
    may_remind: bool = False


class EntryOut(Schema):
    entry_id: int
    kind: str
    kind_label: str
    amount_kobo: int
    narration: str
    reference: str
    method: str
    method_label: str
    effective_on: date
    term: str
    reverses_id: Optional[int]
    reversed_by_id: Optional[int]
    #: Payments only. The number the receipt carries.
    receipt_number: Optional[str]
    may_reverse: bool


class MethodOut(Schema):
    value: str
    label: str


class AccountOut(Schema):
    student_membership_id: int
    student: str
    reference: str
    balance_kobo: int
    may_write: bool
    terms: List[TermChoiceOut]
    methods: List[MethodOut]
    entries: List[EntryOut]


class PaymentIn(Schema):
    """One payment, as the form sends it.

    `amount` is the naira typed, as text — "15,000.50" — so that the one
    parser that turns it into kobo is the server's (`fees.money`). `form_key`
    is minted by the page each time it draws the form; the same key twice is
    one payment (`services.record_payment_once()`).
    """

    term_id: int
    amount: str
    method: str
    reference: str = ""
    effective_on: date
    form_key: UUID


class PostedOut(Schema):
    entry: EntryOut
    #: False when this form had already posted and `entry` is what it posted.
    posted: bool
    balance_kobo: int


class DiscountIn(Schema):
    """A discount given by hand, as the form sends it. `reason` becomes the
    entry's narration; `form_key` does what it does for a payment. No date: a
    discount is given the day it is recorded."""

    term_id: int
    amount: str
    reason: str
    form_key: UUID


class ReversalIn(Schema):
    reason: str


class ReversedOut(Schema):
    entry: EntryOut
    balance_kobo: int


class ReversedNoteOut(Schema):
    on: date
    reason: str


class ReceiptOut(Schema):
    """What the payment entry recorded — with one exception, below.

    The name and admission number are the entry's frozen snapshot, not the
    child's live row: a receipt reprinted next year must say what it said
    when it was issued. **`received_by` is not**: it is read live from the
    recorder's login, so a reprint after that name changes prints the new one.
    Issue #143. `reversed` is set when the payment has since been
    undone, and the page prints that across the receipt — a reprint of a
    reversed payment that looked like a good receipt would be the one document
    in this system a parent could use against the school.
    """

    receipt_number: str
    school: str
    student: str
    student_reference: str
    amount_kobo: int
    method_label: str
    payment_reference: str
    effective_on: date
    term: str
    narration: str
    received_by: str
    reversed: Optional[ReversedNoteOut]


# -- the pieces every route needs --------------------------------------------


def _school_of(request):
    """The school whose schema this request is on. `None` is the portal, where
    the ledger tables do not exist — the same flat 404 as a refusal."""
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No books on this host.")
    return school


def _require_reader(actor, school):
    """The flat 404, before any read, so the refusal cannot depend on whether
    the child or the entry asked about exists."""
    if not may_read(actor, school):
        raise Http404("No such account.")


#: One sentence for a reader who may not write. Not the flat 404: they read
#: the books, so the account's existence is not news to them.
_MAY_NOT_WRITE = (
    "Payments, discounts and reversals are recorded by the bursar or an administrator."
)


def _refuse_non_writer(actor, school):
    if not may_write(actor, school):
        return 403, MessageOut(detail=_MAY_NOT_WRITE)
    return None


def _student_here(school, membership_id) -> Membership:
    """The child's STUDENT membership **at this school**, or the flat 404.

    Ended memberships included: a child who has left still has books, and a
    school still has to be able to read what she owed and what she paid.
    """
    child = (
        Membership.objects.select_related("user")
        .filter(pk=membership_id, school=school, role=Role.STUDENT.value)
        .first()
    )
    if child is None:
        raise Http404("No such account.")
    return child


def _terms():
    return list(Term.objects.order_by("-starts_on", "-pk"))


def _term_choices(terms):
    return [TermChoiceOut(term_id=t.pk, term=str(t), is_current=t.is_current) for t in terms]


def _balance_of(membership_id) -> int:
    return FeeLedgerEntry.objects.for_student(membership_id).balance()


def _entry_out(school, entry, *, reversed_by_id=None, term=None) -> EntryOut:
    is_payment = entry.kind == FeeEntryKind.PAYMENT
    return EntryOut(
        entry_id=entry.pk,
        kind=entry.kind,
        kind_label=entry.get_kind_display(),
        amount_kobo=entry.amount_kobo,
        narration=entry.narration,
        reference=entry.reference,
        method=entry.method,
        method_label=entry.get_method_display() if entry.method else "",
        effective_on=entry.effective_on,
        term=str(term or entry.term),
        reverses_id=entry.reverses_id,
        reversed_by_id=reversed_by_id,
        receipt_number=receipt_number(school, entry.pk) if is_payment else None,
        may_reverse=entry.kind != FeeEntryKind.REVERSAL and reversed_by_id is None,
    )


# -- reading ------------------------------------------------------------------


@router.get("/classes/", response=BooksOut)
def books(request, term_id: Optional[int] = None):
    """The terms, and every class with children placed in the chosen one."""
    school = _school_of(request)
    _require_reader(request.user, school)

    terms = _terms()
    if term_id is not None:
        term = next((t for t in terms if t.pk == term_id), None)
        if term is None:
            raise Http404("No such account.")
    else:
        term = next((t for t in terms if t.is_current), terms[0] if terms else None)

    classes = []
    if term is not None:
        classes = [
            ClassSummaryOut(class_group_id=g.pk, class_group=str(g), children=g.children)
            for g in ClassGroup.objects.annotate(
                children=Count("placements", filter=Q(placements__term=term))
            )
            .filter(children__gt=0)
            .order_by("level", "name")
        ]
    return BooksOut(
        terms=_term_choices(terms),
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        may_write=may_write(request.user, school),
        classes=classes,
        may_remind=_may_remind(request.user, school),
    )


@router.get("/classes/{int:class_group_id}/", response=ClassBalancesOut)
def class_balances(request, class_group_id: int, term_id: int):
    """Every child placed in the class this term, with what their account
    stands at. Three reads whatever the size of the class: the placements, the
    balances (one aggregate), the names."""
    school = _school_of(request)
    _require_reader(request.user, school)
    group = ClassGroup.objects.filter(pk=class_group_id).first()
    term = Term.objects.filter(pk=term_id).first()
    if group is None or term is None:
        raise Http404("No such account.")

    ids = list(
        ClassPlacement.objects.filter(class_group=group, term=term).values_list(
            "student_membership_id", flat=True
        )
    )
    balances = dict(
        FeeLedgerEntry.objects.filter(student_membership_id__in=ids)
        .values("student_membership_id")
        .annotate(total=Sum("amount_kobo"))
        .values_list("student_membership_id", "total")
    )
    children = [
        ChildBalanceOut(
            student_membership_id=row["pk"],
            student=row["display_name"] or row["user__full_name"] or "",
            reference=row["reference"],
            balance_kobo=balances.get(row["pk"], 0),
        )
        for row in Membership.objects.filter(
            pk__in=ids, school=school, role=Role.STUDENT.value
        ).values("pk", "display_name", "user__full_name", "reference")
    ]
    children.sort(key=lambda c: (c.student.lower(), c.student_membership_id))
    return ClassBalancesOut(
        class_group_id=group.pk,
        class_group=str(group),
        term_id=term.pk,
        term=str(term),
        children=children,
        may_remind=_may_remind(request.user, school),
    )


@router.get("/students/{int:membership_id}/", response=AccountOut)
def account(request, membership_id: int):
    """One child's account: every entry, newest first, and the balance."""
    school = _school_of(request)
    _require_reader(request.user, school)
    child = _student_here(school, membership_id)

    entries = list(
        FeeLedgerEntry.objects.for_student(child.pk).select_related("term")
    )
    reversed_by = dict(
        FeeLedgerEntry.objects.filter(reverses__in=[e.pk for e in entries]).values_list(
            "reverses_id", "pk"
        )
    )
    return AccountOut(
        student_membership_id=child.pk,
        student=child.name,
        reference=child.reference,
        balance_kobo=sum(e.amount_kobo for e in entries),
        may_write=may_write(request.user, school),
        terms=_term_choices(_terms()),
        methods=[MethodOut(value=v, label=l) for v, l in PaymentMethod.choices],
        entries=[
            _entry_out(school, e, reversed_by_id=reversed_by.get(e.pk)) for e in entries
        ],
    )


@router.get("/entries/{int:entry_id}/receipt/", response=ReceiptOut)
def receipt(request, entry_id: int):
    """A payment's receipt. Any other kind of entry is the flat 404: there is
    no receipt for a charge."""
    school = _school_of(request)
    _require_reader(request.user, school)
    entry = (
        FeeLedgerEntry.objects.select_related("term")
        .filter(pk=entry_id, kind=FeeEntryKind.PAYMENT)
        .first()
    )
    if entry is None:
        raise Http404("No such account.")

    undone = FeeLedgerEntry.objects.filter(reverses=entry).first()
    received_by = (
        User.objects.filter(pk=entry.recorded_by_id).values_list("full_name", flat=True).first()
        if entry.recorded_by_id
        else None
    )
    return ReceiptOut(
        receipt_number=receipt_number(school, entry.pk),
        school=school.name,
        student=entry.student_name,
        student_reference=entry.student_reference,
        amount_kobo=-entry.amount_kobo,
        method_label=entry.get_method_display(),
        payment_reference=entry.reference,
        effective_on=entry.effective_on,
        term=str(entry.term),
        narration=entry.narration,
        received_by=received_by or "",
        reversed=(
            ReversedNoteOut(on=undone.effective_on, reason=undone.narration) if undone else None
        ),
    )


# -- writing ------------------------------------------------------------------


@router.post(
    "/students/{int:membership_id}/payments/",
    response={201: PostedOut, 200: PostedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def pay(request, membership_id: int, payload: PaymentIn):
    """Record a payment. 201 when this posts one; **200 when this form already
    had**, with the entry it posted — so a retried request tells the page the
    truth, which is that the payment is in the books once."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    child = _student_here(school, membership_id)

    term = Term.objects.filter(pk=payload.term_id).first()
    if term is None:
        return 422, MessageOut(detail="Choose the term this payment is for.")
    if payload.effective_on > timezone.localdate():
        return 422, MessageOut(detail="A payment cannot be dated after today.")
    try:
        amount_kobo = kobo_from_naira(payload.amount)
    except NotAnAmount as exc:
        return 422, MessageOut(detail=str(exc))

    try:
        entry, posted = services.record_payment_once(
            child,
            term,
            amount_kobo,
            method=payload.method,
            reference=payload.reference.strip(),
            effective_on=payload.effective_on,
            recorded_by=request.user,
            form_key=payload.form_key,
        )
    except services.NotThisSchoolsStudent:
        # Unreachable while `_student_here()` scopes its lookup; if it ever
        # stops, the service's own check still refuses, with the same 404.
        raise Http404("No such account.")
    except services.NoMethod as exc:
        return 422, MessageOut(detail=str(exc))
    except services.FormAlreadyUsed as exc:
        return 409, MessageOut(detail=str(exc))

    return (201 if posted else 200), PostedOut(
        entry=_entry_out(school, entry, term=term),
        posted=posted,
        balance_kobo=_balance_of(child.pk),
    )


@router.post(
    "/students/{int:membership_id}/discounts/",
    response={201: PostedOut, 200: PostedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def give_discount(request, membership_id: int, payload: DiscountIn):
    """Give a discount by hand, with the reason — decided 2026-09-24 (fees
    2(a)). The same people as a payment, the same refusals in the same order,
    and the same form key: 201 posted, 200 already posted by this form.

    Not a concession. A concession (B2) is a standing instruction a schedule
    applies every term; this is one entry, once, for one term.
    """
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    child = _student_here(school, membership_id)

    term = Term.objects.filter(pk=payload.term_id).first()
    if term is None:
        return 422, MessageOut(detail="Choose the term this discount is for.")
    try:
        amount_kobo = kobo_from_naira(payload.amount)
    except NotAnAmount as exc:
        return 422, MessageOut(detail=str(exc))

    try:
        entry, posted = services.discount_once(
            child,
            term,
            amount_kobo,
            reason=payload.reason,
            recorded_by=request.user,
            form_key=payload.form_key,
        )
    except services.NotThisSchoolsStudent:
        # Unreachable while `_student_here()` scopes its lookup, as for `pay()`.
        raise Http404("No such account.")
    except services.NoReason as exc:
        return 422, MessageOut(detail=str(exc))
    except services.FormAlreadyUsed as exc:
        return 409, MessageOut(detail=str(exc))

    return (201 if posted else 200), PostedOut(
        entry=_entry_out(school, entry, term=term),
        posted=posted,
        balance_kobo=_balance_of(child.pk),
    )


@router.post(
    "/entries/{int:entry_id}/reversal/",
    response={201: ReversedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def reverse(request, entry_id: int, payload: ReversalIn):
    """Undo an entry, with the reason — decided 2026-09-24 (fees 2(a)). The
    reason is the reversal's narration, and `services.undo()` refuses one
    without it (`NoReason`)."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    entry = FeeLedgerEntry.objects.filter(pk=entry_id).first()
    if entry is None:
        raise Http404("No such account.")


    try:
        reversal = services.undo(entry, reason=payload.reason, recorded_by=request.user)
    except services.NoReason as exc:
        return 422, MessageOut(detail=str(exc))
    except (services.AlreadyReversed, services.CannotReverse) as exc:
        return 409, MessageOut(detail=str(exc))

    return 201, ReversedOut(
        entry=_entry_out(school, reversal),
        balance_kobo=_balance_of(entry.student_membership_id),
    )


# -- B2: bills and concessions ------------------------------------------------
#
# The same people and the same two refusals as B1, decided 2026-09-24: the
# bursar and the administrator set bills and concessions, the principal and the
# vice principal (academic) read them and are told so in a sentence, and
# everybody else gets the flat 404 before any lookup.

_MAY_NOT_BILL = "Bills and concessions are set by the bursar or an administrator."


def _refuse_non_biller(actor, school):
    if not may_write(actor, school):
        return 403, MessageOut(detail=_MAY_NOT_BILL)
    return None


class BillLineOut(Schema):
    line_id: int
    description: str
    amount_kobo: int
    #: Children this line has charged. Not zero means it cannot be removed, and
    #: changing it changes only what the next children are charged.
    charged: int


class BillOut(Schema):
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    may_write: bool
    #: `None` until somebody adds the first line.
    schedule_id: Optional[int]
    lines: List[BillLineOut]
    total_kobo: int
    #: Placed in the class this term — the roster a charge is applied to,
    #: before the skips `apply_to_class()` reports.
    children: int


class BillSummaryOut(Schema):
    class_group_id: int
    class_group: str
    children: int
    schedule_id: Optional[int]
    lines: int
    total_kobo: int


class BillsOut(Schema):
    """The way in to billing: which term, and every class in use, billed or
    not — a bill is set before the children are placed as often as after."""

    terms: List[TermChoiceOut]
    term_id: Optional[int]
    term: Optional[str]
    may_write: bool
    classes: List[BillSummaryOut]


class BillLineIn(Schema):
    """`amount` is the naira typed, as text, as it is for a payment."""

    term_id: int
    description: str
    amount: str


class LineChangeIn(Schema):
    description: str
    amount: str


class ChargeClassIn(Schema):
    term_id: int


class ChildNamedOut(Schema):
    student_membership_id: int
    student: str


class ChargedOut(Schema):
    """What charging the class did — `schedules.AppliedSummary`, and the
    children another class's bill had already charged this term, by name."""

    students: int
    students_skipped: int
    charges_posted: int
    charges_skipped: int
    charged_kobo: int
    discounts_posted: int
    discounts_skipped: int
    discounted_kobo: int
    billed_elsewhere: List[ChildNamedOut]
    summary: str


class RevocationOut(Schema):
    reason: str
    #: The name as it stood when they revoked it — frozen on the row.
    revoked_by: str
    revoked_at: datetime


class ConcessionOut(Schema):
    concession_id: int
    amount_kobo: int
    reason: str
    granted_at: datetime
    revoked: Optional[RevocationOut]


class ConcessionsOut(Schema):
    student_membership_id: int
    student: str
    may_write: bool
    concessions: List[ConcessionOut]


class ConcessionIn(Schema):
    """A standing discount, from a form. `form_key` does what it does for a
    payment: the same form twice grants once."""

    amount: str
    reason: str
    form_key: UUID


class GrantedOut(Schema):
    concession: ConcessionOut
    #: False when this form had already granted it.
    granted: bool


class RevocationIn(Schema):
    reason: str


def _class_and_term(class_group_id, term_id):
    group = ClassGroup.objects.filter(pk=class_group_id).first()
    term = Term.objects.filter(pk=term_id).first()
    if group is None or term is None:
        raise Http404("No such account.")
    return group, term


def _bill_out(request, school, group, term) -> BillOut:
    schedule = billing.bill_for(group, term)
    lines = []
    if schedule is not None:
        lines = [
            BillLineOut(
                line_id=line.pk,
                description=line.description,
                amount_kobo=line.amount_kobo,
                charged=line.charged,
            )
            for line in schedule.lines.annotate(
                charged=Count("entries", filter=Q(entries__kind=FeeEntryKind.CHARGE))
            )
        ]
    return BillOut(
        class_group_id=group.pk,
        class_group=str(group),
        term_id=term.pk,
        term=str(term),
        may_write=may_write(request.user, school),
        schedule_id=schedule.pk if schedule else None,
        lines=lines,
        total_kobo=sum(line.amount_kobo for line in lines),
        children=ClassPlacement.objects.filter(class_group=group, term=term).count(),
    )


def _concession_out(concession) -> ConcessionOut:
    """The times in the school's zone, not UTC, so the date the page prints
    is the day it happened in Lagos — a revocation at 00:30 is not
    yesterday's."""
    revocation = getattr(concession, "revocation", None)
    return ConcessionOut(
        concession_id=concession.pk,
        amount_kobo=concession.amount_kobo,
        reason=concession.reason,
        granted_at=timezone.localtime(concession.granted_at),
        revoked=(
            RevocationOut(
                reason=revocation.reason,
                revoked_by=revocation.revoked_by_name,
                revoked_at=timezone.localtime(revocation.revoked_at),
            )
            if revocation
            else None
        ),
    )


@router.get("/bills/", response=BillsOut)
def bills(request, term_id: Optional[int] = None):
    """Every class in use this term, with its bill's lines and total, if any."""
    school = _school_of(request)
    _require_reader(request.user, school)

    terms = _terms()
    if term_id is not None:
        term = next((t for t in terms if t.pk == term_id), None)
        if term is None:
            raise Http404("No such account.")
    else:
        term = next((t for t in terms if t.is_current), terms[0] if terms else None)

    classes = []
    if term is not None:
        bills_here = {
            s.class_group_id: s
            for s in FeeSchedule.objects.filter(term=term).annotate(
                line_count=Count("lines"), total=Sum("lines__amount_kobo")
            )
        }
        classes = [
            BillSummaryOut(
                class_group_id=g.pk,
                class_group=str(g),
                children=g.children,
                schedule_id=bills_here[g.pk].pk if g.pk in bills_here else None,
                lines=bills_here[g.pk].line_count if g.pk in bills_here else 0,
                total_kobo=(bills_here[g.pk].total or 0) if g.pk in bills_here else 0,
            )
            for g in ClassGroup.objects.filter(is_active=True)
            .annotate(children=Count("placements", filter=Q(placements__term=term)))
            .order_by("level", "name")
        ]
    return BillsOut(
        terms=_term_choices(terms),
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        may_write=may_write(request.user, school),
        classes=classes,
    )


@router.get("/classes/{int:class_group_id}/bill/", response=BillOut)
def bill(request, class_group_id: int, term_id: int):
    """One class's bill for one term, line by line, with what each has charged."""
    school = _school_of(request)
    _require_reader(request.user, school)
    group, term = _class_and_term(class_group_id, term_id)
    return _bill_out(request, school, group, term)


@router.post(
    "/classes/{int:class_group_id}/bill/lines/",
    response={201: BillOut, 200: BillOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def add_bill_line(request, class_group_id: int, payload: BillLineIn):
    """Add a line, starting the bill if there is none. 201 with the bill as it
    now stands; **200 when the bill already had this line at this amount** — a
    double click — and 409 when it has the name at another amount."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_biller(request.user, school)
    if refusal:
        return refusal
    group, term = _class_and_term(class_group_id, payload.term_id)
    try:
        amount_kobo = kobo_from_naira(payload.amount)
    except NotAnAmount as exc:
        return 422, MessageOut(detail=str(exc))
    try:
        # One transaction, so a refused line does not leave the empty bill it
        # would have started behind it — there is no ATOMIC_REQUESTS here.
        with transaction.atomic():
            _, added = billing.add_line(billing.open_bill(group, term), payload.description, amount_kobo)
    except billing.NoDescription as exc:
        return 422, MessageOut(detail=str(exc))
    except billing.LineAlreadyOnBill as exc:
        return 409, MessageOut(detail=str(exc))
    return (201 if added else 200), _bill_out(request, school, group, term)


def _line_or_404(line_id) -> FeeScheduleLine:
    line = (
        FeeScheduleLine.objects.select_related("schedule__class_group", "schedule__term")
        .filter(pk=line_id)
        .first()
    )
    if line is None:
        raise Http404("No such account.")
    return line


@router.put(
    "/bill-lines/{int:line_id}/",
    response={200: BillOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def change_bill_line(request, line_id: int, payload: LineChangeIn):
    """Rename a line or correct its amount. Charges already posted do not move
    — `billing.change_line()` says why — and the page says so beside the line."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_biller(request.user, school)
    if refusal:
        return refusal
    line = _line_or_404(line_id)
    try:
        amount_kobo = kobo_from_naira(payload.amount)
    except NotAnAmount as exc:
        return 422, MessageOut(detail=str(exc))
    try:
        billing.change_line(line, description=payload.description, amount_kobo=amount_kobo)
    except billing.NoDescription as exc:
        return 422, MessageOut(detail=str(exc))
    except billing.LineAlreadyOnBill as exc:
        return 409, MessageOut(detail=str(exc))
    return 200, _bill_out(request, school, line.schedule.class_group, line.schedule.term)


@router.delete(
    "/bill-lines/{int:line_id}/",
    response={200: BillOut, 403: MessageOut, 409: MessageOut},
)
def remove_bill_line(request, line_id: int):
    """Remove a line nobody has been charged by; 409 once somebody has."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_biller(request.user, school)
    if refusal:
        return refusal
    line = _line_or_404(line_id)
    group, term = line.schedule.class_group, line.schedule.term
    try:
        billing.remove_line(line)
    except billing.LineHasCharged as exc:
        return 409, MessageOut(detail=str(exc))
    return 200, _bill_out(request, school, group, term)


@router.post(
    "/classes/{int:class_group_id}/bill/charges/",
    response={200: ChargedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def charge_class(request, class_group_id: int, payload: ChargeClassIn):
    """Charge every child on the roster the bill's lines, and post their
    standing concessions. **Safe to press again**: a child already charged a
    line is skipped for it, and a child another class's bill charged this term
    is skipped and named — `schedules.apply_to_class()`. Always 200, with what
    it did; "0 charged" is an answer, not a refusal."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_biller(request.user, school)
    if refusal:
        return refusal
    group, term = _class_and_term(class_group_id, payload.term_id)
    schedule = billing.bill_for(group, term)
    if schedule is None:
        return 422, MessageOut(detail=f"{group} has no bill for {term} yet. Add a line first.")
    try:
        done = billing.apply(schedule, by=request.user)
    except schedules.EmptySchedule as exc:
        return 422, MessageOut(detail=str(exc))
    except (schedules.UnknownStudent, services.NotThisSchoolsStudent) as exc:
        return 409, MessageOut(detail=str(exc))

    names = {
        row["pk"]: row["display_name"] or row["user__full_name"] or ""
        for row in Membership.objects.filter(
            pk__in=done.billed_elsewhere, school=school, role=Role.STUDENT.value
        ).values("pk", "display_name", "user__full_name")
    }
    return 200, ChargedOut(
        students=done.students,
        students_skipped=done.students_skipped,
        charges_posted=done.charges_posted,
        charges_skipped=done.charges_skipped,
        charged_kobo=done.charged_kobo,
        discounts_posted=done.discounts_posted,
        discounts_skipped=done.discounts_skipped,
        discounted_kobo=done.discounted_kobo,
        billed_elsewhere=[
            ChildNamedOut(student_membership_id=pk, student=names.get(pk, ""))
            for pk in done.billed_elsewhere
        ],
        summary=str(done),
    )


@router.get("/students/{int:membership_id}/concessions/", response=ConcessionsOut)
def concessions(request, membership_id: int):
    """Every concession the child has been granted, revoked ones included —
    with who revoked each, when and why (issue #75)."""
    school = _school_of(request)
    _require_reader(request.user, school)
    child = _student_here(school, membership_id)
    return ConcessionsOut(
        student_membership_id=child.pk,
        student=child.name,
        may_write=may_write(request.user, school),
        concessions=[
            _concession_out(c)
            for c in FeeConcession.objects.filter(student_membership_id=child.pk)
            .select_related("revocation")
            .order_by("-granted_at", "-pk")
        ],
    )


@router.post(
    "/students/{int:membership_id}/concessions/",
    response={201: GrantedOut, 200: GrantedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def grant_concession(request, membership_id: int, payload: ConcessionIn):
    """Grant a standing discount, with its reason. It is given by the next
    application of each term's bill, not now. 201 granted; 200 already granted
    by this form."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_biller(request.user, school)
    if refusal:
        return refusal
    child = _student_here(school, membership_id)
    try:
        amount_kobo = kobo_from_naira(payload.amount)
    except NotAnAmount as exc:
        return 422, MessageOut(detail=str(exc))
    try:
        concession, granted = billing.grant_concession(
            child,
            amount_kobo,
            reason=payload.reason,
            form_key=payload.form_key,
            by=request.user,
        )
    except services.NotThisSchoolsStudent:
        # Unreachable while `_student_here()` scopes its lookup, as for `pay()`.
        raise Http404("No such account.")
    except services.NoReason as exc:
        return 422, MessageOut(detail=str(exc))
    except services.FormAlreadyUsed as exc:
        return 409, MessageOut(detail=str(exc))
    return (201 if granted else 200), GrantedOut(
        concession=_concession_out(concession), granted=granted
    )


@router.post(
    "/concessions/{int:concession_id}/revocation/",
    response={201: ConcessionOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def revoke_concession(request, concession_id: int, payload: RevocationIn):
    """Revoke a concession, with the reason — issue #75. The concession stays
    as it was granted and a revocation row says who, when and why. 422 without
    a reason; 409 when it was revoked already."""
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_biller(request.user, school)
    if refusal:
        return refusal
    concession = FeeConcession.objects.filter(pk=concession_id).first()
    if concession is None:
        raise Http404("No such account.")
    try:
        billing.revoke_concession(concession, reason=payload.reason, by=request.user)
    except services.NoReason as exc:
        return 422, MessageOut(detail=str(exc))
    except billing.AlreadyRevoked as exc:
        return 409, MessageOut(detail=str(exc))
    concession = FeeConcession.objects.select_related("revocation").get(pk=concession.pk)
    return 201, _concession_out(concession)


# -- fee reminders (docs/messaging.md D10) --------------------------------------


def _may_remind(actor, school) -> bool:
    from notices.services import offered

    return may_write(actor, school) and offered().fee_reminders


class ReminderChildOut(Schema):
    student_membership_id: int
    student: str
    reference: str
    #: The whole account, every term, as the ledger folds it now.
    amount_kobo: int
    #: The guardians who receive invoices and will be sent it, by name.
    guardians: List[str] = []
    #: Guardians who receive invoices and have no usable channel.
    unreachable: int = 0


class RemindersOut(Schema):
    """What "Remind families" will send (the preview), or did (the press)."""

    detail: str
    messages: int
    segments: int
    held_until: Optional[str] = None
    unreachable: int = 0
    children: List[ReminderChildOut] = []
    #: Owing, and reminded inside the interval already, so left out.
    recently_reminded: List[ReminderChildOut] = []


class RemindIn(Schema):
    term_id: int
    #: None is the whole school.
    class_group_id: Optional[int] = None
    #: Only these children: "Remind again", from the list of ones not sent.
    children: Optional[List[int]] = None


class NotSentOut(Schema):
    student_membership_id: int
    student: str
    reference: str
    term_id: int
    #: What the reminder would have said, before the account moved.
    stated_kobo: int
    asked_for: datetime
    #: The account now.
    balance_kobo: int


class NotSentListOut(Schema):
    may_remind: bool
    children: List[NotSentOut]


_REMIND_RESPONSES = {200: RemindersOut, 403: MessageOut, 422: MessageOut}
_MAY_NOT_REMIND = "Fee reminders are sent by the bursar or an administrator."


def _reminding(request, term_id, class_group_id, children, act, say):
    """The preview and the press: one lookup and one set of refusals for both."""
    from notices import services as notices_services

    school = _school_of(request)
    _require_reader(request.user, school)
    if _refuse_non_writer(request.user, school) is not None:
        return 403, MessageOut(detail=_MAY_NOT_REMIND)
    term = Term.objects.filter(pk=term_id).first()
    if term is None:
        raise Http404("No such term.")
    group = None
    if class_group_id is not None:
        group = ClassGroup.objects.filter(pk=class_group_id).first()
        if group is None:
            raise Http404("No such class.")
    try:
        answer = act(term, actor=request.user, class_group=group, only=children)
    except notices_services.NotAllowed:
        return 403, MessageOut(detail=_MAY_NOT_REMIND)
    except notices_services.NoticesError as exc:
        return 422, MessageOut(detail=str(exc))
    held = answer["held_until"]
    return 200, RemindersOut(
        detail=say(answer),
        messages=answer["messages"],
        segments=answer["segments"],
        held_until=held.isoformat() if held else None,
        unreachable=answer["unreachable"],
        children=[ReminderChildOut(**c) for c in answer["children"]],
        recently_reminded=[ReminderChildOut(**c) for c in answer["recently_reminded"]],
    )


@router.get("/reminders/", response=_REMIND_RESPONSES)
def preview_reminders(
    request, term_id: int, class_group_id: Optional[int] = None,
    children: List[int] = Query(None),
):
    """The bursar: which children, which guardians, how many messages. D10.

    Writes and queues nothing, and is refused as the press would be, over the
    cap included.
    """
    from notices import reminders

    return _reminding(
        request, term_id, class_group_id, children, reminders.preview_reminders,
        lambda answer: _reminder_sentence(answer, asking=True),
    )


@router.post("/reminders/", response=_REMIND_RESPONSES)
def send_reminders(request, payload: RemindIn):
    """The bursar: remind each family who receives invoices of what the account shows."""
    from notices import reminders

    return _reminding(
        request, payload.term_id, payload.class_group_id, payload.children,
        reminders.send_reminders, lambda answer: _reminder_sentence(answer, asking=False),
    )


@router.get("/reminders/not-sent/", response=NotSentListOut)
def reminders_not_sent(request):
    """Children whose last reminder went nowhere because the account moved.

    Decided 2026-09-25: listed on the bursar's page so she can send again. A
    reader sees the list; only a writer is offered "Remind again".
    """
    from notices import reminders

    school = _school_of(request)
    _require_reader(request.user, school)
    return NotSentListOut(
        may_remind=_may_remind(request.user, school),
        children=[NotSentOut(**row) for row in reminders.not_sent()],
    )


def _plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _reminder_sentence(answer, *, asking):
    """What the bursar reads: before pressing (`asking`) or after."""
    from notices import hours, reminders

    n = answer["messages"]
    children = answer["children"]
    skipped = answer["recently_reminded"]
    days = reminders.interval().days
    if not children and not skipped:
        return "Nobody here owes anything, so there is nobody to remind."
    if not children:
        return f"Everybody here who owes was reminded in the last {days} days."
    if n == 0:
        sentence = "No guardian who receives invoices can be reached for these children."
    else:
        about = _plural(len([c for c in children if c["guardians"]]), "child", "children")
        if asking:
            sentence = f"This will send {_plural(n, 'message')} about {about}"
        elif answer["held_until"]:
            sentence = f"{_plural(n, 'message')} about {about} will be sent"
        else:
            sentence = f"{_plural(n, 'message')} about {about} {'is' if n == 1 else 'are'} being sent"
        if answer["segments"] != n:
            sentence += f" ({_plural(answer['segments'], 'SMS segment')})"
        sentence += "."
        if answer["held_until"]:
            sentence += (
                f" {'These will be sent' if asking else 'They go'} at "
                f"{hours.said(answer['held_until'])}: messages are not sent between 20:00 and 07:00."
            )
    u = answer["unreachable"]
    if u:
        were = "will not be" if asking else ("was not" if u == 1 else "were not")
        sentence += (
            f" {_plural(u, 'guardian')} who receive{'s' if u == 1 else ''} invoices "
            f"{'has' if u == 1 else 'have'} no verified phone or email, and {were} sent anything."
        )
    if skipped:
        sentence += (
            f" {_plural(len(skipped), 'child', 'children')} reminded in the last {days} days "
            f"{'is' if len(skipped) == 1 else 'are'} left out."
        )
    return sentence


__all__ = ["router"]
