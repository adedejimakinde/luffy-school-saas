"""HTTP for the principal's home: one read, and nothing to write.

Every figure is somebody else's, counted by `summary`. What this module decides
is the door: who may open it, and that the answer is refused **before** a
single table is read, for the oracle reason `results.chain_api.
_refuse_outsiders()` gives. A bursar or a parent is told this page is not
theirs, in the same sentence whatever the school holds.

Nothing on the page acts. Each "waiting" row carries a link, and the link is
the action: a release is taken on the results page, behind the question it
asks there, and never with one tap from here.
"""

from datetime import date
from typing import List, Optional

from django.http import Http404
from ninja import Router, Schema

from academics.models import Term
from accounts.session import session_auth

from . import summary

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class ReleasedOut(Schema):
    released: int
    classes: int


class DayOut(Schema):
    on: date
    present: int
    marked: int


class PresentOut(Schema):
    today: DayOut
    week: List[DayOut]
    registers: int
    classes: int


class FeesOut(Schema):
    #: Whole kobo, both of them, for `fees/money.js`'s reason: the page formats,
    #: and never divides.
    collected_kobo: int
    billed_kobo: int


class AbsentOut(Schema):
    children: int
    threshold_percent: int
    min_marked_days: int


class WaitingOut(Schema):
    kind: str
    class_group_id: int
    class_group: str
    #: Whole days since the sheet reached where it stands, in Lagos days.
    days: Optional[int] = None
    missing: Optional[int] = None
    #: Where the row's button goes. Written here, once, so the page does not
    #: hold a second copy of which screen answers which kind of row.
    href: str


class HappenedOut(Schema):
    at: str
    text: str


class TodayOut(Schema):
    registers: int
    classes: int
    payments: int
    steps: List[HappenedOut]


class HomeOut(Schema):
    school: str
    term_id: Optional[int] = None
    term: Optional[str] = None
    today: date
    #: Null with no current term: each is reckoned against one, and a zero
    #: would read as a term where nothing happened.
    released: Optional[ReleasedOut] = None
    fees: Optional[FeesOut] = None
    absent: Optional[AbsentOut] = None
    present: PresentOut
    waiting: List[WaitingOut]
    happened: TodayOut


_NOT_YOURS = (
    "This page is the principal's and the vice principal's. Your school office "
    "can tell you which pages are yours."
)


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No school on this host.")
    return school


def _href(row) -> str:
    screen = "/comments/" if row.kind == summary.REMARKS else "/results/"
    return f"{screen}?class={row.class_group_id}"


@router.get("/", response={200: HomeOut, 403: MessageOut})
def home(request):
    """Where the school stands this term, and what is waiting on this login."""
    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    if not roles & summary.HOME_ROLES:
        return 403, MessageOut(detail=_NOT_YOURS)

    term = Term.objects.filter(is_current=True).first()
    today = summary.lagos_today()
    present = summary.present(term, today)
    rows = summary.waiting(request.user, roles, term, today)

    return HomeOut(
        school=school.name,
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        today=today,
        released=vars(summary.released(term)) if term else None,
        fees=vars(summary.fees(term)) if term else None,
        absent=vars(summary.absent(school, term)) if term else None,
        present=PresentOut(
            today=vars(present.today),
            week=[vars(d) for d in present.week],
            registers=present.registers,
            classes=present.classes,
        ),
        waiting=[
            WaitingOut(
                kind=row.kind,
                class_group_id=row.class_group_id,
                class_group=row.class_group,
                days=(today - row.since).days if row.since else None,
                missing=row.missing,
                href=_href(row),
            )
            for row in rows
        ],
        happened=_happened(summary.today_at_school(term, today, present)),
    )


def _happened(today):
    return TodayOut(
        registers=today.registers,
        classes=today.classes,
        payments=today.payments,
        steps=[vars(s) for s in today.steps],
    )
