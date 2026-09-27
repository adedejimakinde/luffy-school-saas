"""What the principal's home counts, each figure asked of the table that owns it.

Every number here is one another page already shows in full: the results chain,
the registers, the fee book, the absences list. This module adds **no rule of
its own** about any of them. Where a rule exists it is called (`absences.
flagged()`, the chain's role sets); where a figure is a plain sum it is written
once, here, with the argument for what it counts.

**The cost does not grow with the school.** Every function below is a fixed
number of queries whatever the roll or the number of classes, and
`test_the_home_does_not_cost_more_as_the_school_grows` holds that. A home page
is the screen a principal opens first and refreshes most.

**Days are Lagos days.** `timezone.localdate()` is the school's calendar date
under `settings.TIME_ZONE`; UTC would call a register taken at 00:30 on Monday
a Sunday one, which is the bug `docs/offline.md` S1 fixed in the register page.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from academics.models import ClassGroup, ClassPlacement
from accounts.models import Role
from attendance import absences
from attendance.models import AbsenceSettings, AttendanceMark, AttendanceStatus, Register
from fees.models import FeeEntryKind, FeeLedgerEntry
from results import services as chain
from results.models import (
    CommentAuthor,
    ReportCardComment,
    ResultSheet,
    ResultSheetTransition,
    SheetState,
)

#: Who the home is for. Both hold every reading role each figure below needs,
#: and `test_every_figure_is_readable_by_everyone_the_home_admits` holds that,
#: so no figure has to be withheld card by card.
HOME_ROLES = frozenset({Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value})


def lagos_today() -> date:
    return timezone.localdate()


# -- the four figures --------------------------------------------------------


@dataclass(frozen=True)
class Released:
    released: int
    classes: int


def released(term) -> Released:
    """Classes whose results have gone home this term, out of every active class.

    Over class groups and not over sheets, on `chain_api`'s reasoning: a class
    nobody has opened has no sheet and is still a class whose results have not
    gone home.
    """
    groups = ClassGroup.objects.filter(is_active=True)
    return Released(
        released=ResultSheet.objects.filter(
            term=term, state=SheetState.RELEASED, class_group__in=groups
        ).count(),
        classes=groups.count(),
    )


@dataclass(frozen=True)
class Day:
    on: date
    present: int
    marked: int


@dataclass(frozen=True)
class Present:
    today: Day
    #: Monday to today, school days with a register only. A day nobody took a
    #: register is left out rather than drawn as a zero, which would read as a
    #: day every child stayed at home.
    week: list = field(default_factory=list)
    registers: int = 0
    classes: int = 0


def present(term, today: date) -> Present:
    """Who was marked present today, out of who was marked, and this week so far.

    **Out of the children marked, never out of the roll.** A class whose
    register nobody has taken yet has not had anybody absent; counting its
    children as not present would make every morning look like a truancy
    crisis until nine. `registers` and `classes` say how much of the school the
    percentage covers, so the reader can see that too.
    """
    monday = today - timedelta(days=today.weekday())
    by_day = {}
    for row in (
        AttendanceMark.objects.filter(register__taken_on__range=(monday, today))
        .values("register__taken_on")
        .annotate(
            marked=Count("id"),
            present=Count("id", filter=Q(status=AttendanceStatus.PRESENT)),
        )
    ):
        by_day[row["register__taken_on"]] = Day(
            on=row["register__taken_on"], present=row["present"], marked=row["marked"]
        )
    classes = (
        ClassPlacement.objects.filter(term=term, class_group__is_active=True)
        .values("class_group_id")
        .distinct()
        .count()
        if term
        else 0
    )
    return Present(
        today=by_day.get(today, Day(on=today, present=0, marked=0)),
        week=[by_day[d] for d in sorted(by_day)],
        registers=Register.objects.filter(taken_on=today).count(),
        classes=classes,
    )


@dataclass(frozen=True)
class Fees:
    collected_kobo: int
    billed_kobo: int


def fees(term) -> Fees:
    """What this term's bills asked of families, and what the school received.

    **Billed** is charges net of their reversals, less discounts net of theirs:
    what families were actually asked for. A scholarship is not money the school
    is waiting on.

    **Collected** is payments net of their reversals, less refunds net of
    theirs: money that stayed with the school. A reversed payment was a
    mistake, not cash; a refund is cash that went back.

    A reversal counts as the kind it undoes, which is one hop: a reversal of a
    reversal is refused (`fees.services.CannotReverse`). Both figures are
    reckoned against `FeeLedgerEntry.term`, the same key the fee book reads.
    """
    sums = dict.fromkeys(FeeEntryKind.values, 0)
    for row in (
        FeeLedgerEntry.objects.filter(term=term)
        .annotate(counts_as=Coalesce(F("reverses__kind"), F("kind")))
        .values("counts_as")
        .annotate(total=Sum("amount_kobo"))
    ):
        sums[row["counts_as"]] = row["total"] or 0
    return Fees(
        collected_kobo=-(sums[FeeEntryKind.PAYMENT] + sums[FeeEntryKind.REFUND]),
        billed_kobo=sums[FeeEntryKind.CHARGE] + sums[FeeEntryKind.DISCOUNT],
    )


@dataclass(frozen=True)
class Absent:
    children: int
    threshold_percent: int
    min_marked_days: int


def absent(school, term) -> Absent:
    """How many children the absences list names. `absences.flagged()` decides."""
    settings = AbsenceSettings.load()
    return Absent(
        children=len(absences.flagged(school, term, settings)),
        threshold_percent=settings.threshold_percent,
        min_marked_days=settings.min_marked_days,
    )


# -- waiting for you ---------------------------------------------------------


#: What each kind of row says, and where its link goes. The link is the whole
#: action: nothing is done from the home page. Releasing cannot be taken back,
#: so it happens only on the results page, behind its own question.
RELEASE, APPROVE, CHECK, REMARKS, SENT_BACK = (
    "release", "approve", "check", "remarks", "sent_back",
)



@dataclass(frozen=True)
class Waiting:
    kind: str
    class_group_id: int
    class_group: str
    #: The day the sheet reached where it stands. None for a class whose sheet
    #: has no recorded step, which a row here never is, but the type says so.
    since: Optional[date]
    #: Children still without a principal's remark, for a REMARKS row.
    missing: Optional[int] = None


def waiting(user, roles, term, today: date) -> list:
    """What is waiting on this login, oldest first.

    Read off the same role sets the chain enforces, so a row here is a step the
    results page will offer. The chain still asks again when the step is taken.

    - **release**: approved, and this login may release.
    - **approve**: checked, and this login may approve.
    - **check**: submitted, and this login may check.
    - **sent_back**: back in draft because *this person* sent it back. Theirs
      to watch for; nobody else's.
    - **remarks**: for the principal, a class whose sheet is open (draft,
      including one sent back) with children still lacking a principal's
      remark. **Only while it is open**, because that is the only time a
      remark can be written: once the sheet is submitted its remarks are part
      of what is being reviewed and `comments.write()` refuses them
      (`CommentsLocked`). A row that opened a page where nothing could be done
      would be a false remedy. Reported, never enforced: `comments.missing()`
      says why. A class nobody has opened has no sheet and no row here; its
      marks have not started either.

    Four queries whatever the size of the school: sheets, each sheet's latest
    step, the open sheets' rosters and the principal's remarks for them.
    """
    if term is None:
        return []
    sheets = list(
        ResultSheet.objects.filter(term=term, class_group__is_active=True)
        .select_related("class_group")
        .order_by("class_group__level", "class_group__name")
    )
    latest = {
        t.sheet_id: t
        for t in ResultSheetTransition.objects.filter(sheet__in=sheets)
        .order_by("sheet_id", "-created_at", "-id")
        .distinct("sheet_id")
    }

    def since(sheet):
        # A draft nobody has moved yet has waited since it was opened.
        step = latest.get(sheet.pk)
        return timezone.localtime(step.created_at if step else sheet.created_at).date()

    rows = []
    for sheet in sheets:
        kind = None
        if sheet.state == SheetState.APPROVED and roles & chain.RELEASING_ROLES:
            kind = RELEASE
        elif sheet.state == SheetState.CHECKED and roles & chain.APPROVING_ROLES:
            kind = APPROVE
        elif sheet.state == SheetState.SUBMITTED and roles & chain.CHECKING_ROLES:
            kind = CHECK
        elif sheet.state == SheetState.DRAFT:
            step = latest.get(sheet.pk)
            if step and step.to_state == SheetState.DRAFT and step.actor_id == user.pk:
                kind = SENT_BACK
        if kind:
            rows.append(
                Waiting(kind, sheet.class_group_id, sheet.class_group.name, since(sheet))
            )

    if Role.PRINCIPAL.value in roles:
        rows.extend(_remarks_missing(term, [s for s in sheets if s.state == SheetState.DRAFT], since))

    return sorted(rows, key=lambda r: (r.since or today, r.class_group))


def _remarks_missing(term, sheets, since):
    """Open classes with children the principal has not written for yet."""
    if not sheets:
        return []
    by_group = {s.class_group_id: s for s in sheets}
    roster = list(
        ClassPlacement.objects.filter(term=term, class_group_id__in=by_group).values_list(
            "class_group_id", "student_membership_id"
        )
    )
    written = set(
        ReportCardComment.objects.filter(
            term=term,
            author=CommentAuthor.PRINCIPAL,
            student_membership_id__in=[sid for _, sid in roster],
        ).values_list("student_membership_id", flat=True)
    )
    missing = {}
    for group_id, sid in roster:
        if sid not in written:
            missing[group_id] = missing.get(group_id, 0) + 1
    return [
        Waiting(
            REMARKS,
            group_id,
            by_group[group_id].class_group.name,
            since(by_group[group_id]),
            missing=n,
        )
        for group_id, n in missing.items()
    ]


# -- today -------------------------------------------------------------------


#: How a step reads in "Today". The sheet's own labels describe where a sheet
#: stands ("Checked by vice principal"); these say what happened.
_DID = {
    SheetState.SUBMITTED: "submitted",
    SheetState.CHECKED: "checked",
    SheetState.APPROVED: "approved",
    SheetState.RELEASED: "released to families",
    SheetState.DRAFT: "sent back",
}


@dataclass(frozen=True)
class Happened:
    at: str
    text: str


@dataclass(frozen=True)
class Today:
    registers: int
    classes: int
    payments: int
    steps: list


def today_at_school(term, today: date, present_today: Present) -> Today:
    """Registers, payments and results steps, today.

    No calendar of events exists, so this is only what the school's own records
    say happened. A list of assemblies and meetings would need a table nobody
    has asked for yet.
    """
    start = timezone.make_aware(datetime.combine(today, time.min))
    end = start + timedelta(days=1)
    steps = [
        Happened(
            at=timezone.localtime(t.created_at).strftime("%H:%M"),
            text=f"{t.sheet.class_group.name} {_DID[t.to_state]}",
        )
        for t in ResultSheetTransition.objects.filter(
            created_at__gte=start, created_at__lt=end, sheet__term=term
        )
        .select_related("sheet__class_group")
        .order_by("created_at", "id")
    ] if term else []
    return Today(
        registers=present_today.registers,
        classes=present_today.classes,
        payments=FeeLedgerEntry.objects.filter(
            kind=FeeEntryKind.PAYMENT, recorded_at__gte=start, recorded_at__lt=end
        ).count(),
        steps=steps,
    )
