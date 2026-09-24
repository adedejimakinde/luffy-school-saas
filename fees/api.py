"""HTTP for the school's books: balances, one child's account, a payment, a
reversal and a receipt. B1 of the fees work; billing is B2.

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

from datetime import date
from typing import List, Optional
from uuid import UUID

from django.db.models import Count, Q, Sum
from django.http import Http404
from django.utils import timezone
from ninja import Router, Schema

from academics.models import ClassGroup, ClassPlacement, Term
from accounts.models import Membership, Role, User
from accounts.session import session_auth

from . import services
from .authority import may_read, may_write, receipt_number
from .models import FeeEntryKind, FeeLedgerEntry, PaymentMethod
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


class ReversalIn(Schema):
    reason: str


class ReversedOut(Schema):
    entry: EntryOut
    balance_kobo: int


class ReversedNoteOut(Schema):
    on: date
    reason: str


class ReceiptOut(Schema):
    """What the payment entry recorded, and nothing it did not.

    The name and admission number are the entry's frozen snapshot, not the
    child's live row: a receipt reprinted next year must say what it said
    when it was issued. `reversed` is set when the payment has since been
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
_MAY_NOT_WRITE = "Payments and reversals are recorded by the bursar or an administrator."


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


#: The narration column's width, read from the field.
_REASON_MAX = FeeLedgerEntry._meta.get_field("narration").max_length


@router.post(
    "/entries/{int:entry_id}/reversal/",
    response={201: ReversedOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
)
def reverse(request, entry_id: int, payload: ReversalIn):
    """Undo an entry, with the reason — decided 2026-09-24 (fees 2(a)).

    The reason is the reversal's narration: it is what the books say about
    this row, and a reversal that said only "Reversal of: Payment received"
    would tell a reader a year later that something was undone and never why.
    """
    school = _school_of(request)
    _require_reader(request.user, school)
    refusal = _refuse_non_writer(request.user, school)
    if refusal:
        return refusal
    entry = FeeLedgerEntry.objects.filter(pk=entry_id).first()
    if entry is None:
        raise Http404("No such account.")

    reason = payload.reason.strip()
    if not reason:
        return 422, MessageOut(detail="Say why this is being undone.")
    if len(reason) > _REASON_MAX:
        return 422, MessageOut(detail=f"Keep the reason under {_REASON_MAX} characters.")

    try:
        reversal = services.reverse_entry(entry, narration=reason, recorded_by=request.user)
    except (services.AlreadyReversed, services.CannotReverse) as exc:
        return 409, MessageOut(detail=str(exc))

    return 201, ReversedOut(
        entry=_entry_out(school, reversal),
        balance_kobo=_balance_of(entry.student_membership_id),
    )


__all__ = ["router"]
