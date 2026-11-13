"""HTTP for "Print ID cards": the page's data, the roll to choose from, start, watch, download.

`idcards.printing` holds the rules and `idcards.access` the one rule about who;
this is their door. `docs/id-cards.md`.

    GET  /api/id-cards/                                   the term, its classes, and the print log
    GET  /api/id-cards/classes/<class>/<term>/            who could be printed, to choose some
    POST /api/id-cards/classes/<class>/<term>/print/      start a job: the whole class, or `student_ids`
    GET  /api/id-cards/jobs/<job>/                        how far it has got
    GET  /api/id-cards/jobs/<job>/pdf/                    the file, to the person who asked, for a day

**Who may is asked first, on every one of them**, on the server, of the school
this host is. A page that hid the button would be a restriction anybody could
step round with a request. The class routes answer **403** to a login with no
standing to print, before any lookup, so that the answer does not say whether a
class exists. The two job routes answer a flat **404** to anybody who is not the
person who asked, and to that person once they may no longer print: a job id is a
number, and a 403 would say it exists. A file past its day is a **410**, to its
owner only.
"""

from datetime import datetime
from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema

from academics.models import ClassGroup, ClassPlacement, Term
from accounts.models import LIVE_STATUSES, Membership, Role
from accounts.session import session_auth

from . import cards, printing
from .access import MAY_NOT_PRINT, may_print
from .models import IdCardPrint, PrintState

router = Router(auth=session_auth)

#: How many of the school's latest prints the page lists.
LOG_LENGTH = 15


class MessageOut(Schema):
    detail: str


class TermOut(Schema):
    id: int
    label: str
    is_current: bool


class ChosenTermOut(Schema):
    id: int
    label: str
    session: str
    #: The date every card printed for this term says it is valid until.
    expires_on: Optional[str] = None


class ClassOut(Schema):
    id: int
    name: str
    students: int


class PrintLineOut(Schema):
    id: int
    class_group: str
    term: str
    card_count: Optional[int] = None
    by: str
    at: str
    state: str
    state_label: str
    #: Whether this login asked for it and the file can still be downloaded.
    mine_to_download: bool = False


class OverviewOut(Schema):
    terms: List[TermOut]
    term: Optional[ChosenTermOut] = None
    classes: List[ClassOut]
    #: False when the school has no phone on record: the cards then say
    #: "contact the school office" and the page says to set one.
    phone_set: bool
    prints: List[PrintLineOut]


class ChildOut(Schema):
    student_membership_id: int
    name: str
    admission_number: str


class RosterOut(Schema):
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    children: List[ChildOut]


class PrintIn(Schema):
    #: The children to print, by membership id. Empty for the whole class.
    student_ids: List[int] = []


class JobOut(Schema):
    id: int
    state: str
    state_label: str
    class_group: str
    term: str
    done: int
    total: int
    card_count: Optional[int] = None
    created_at: datetime
    #: Until when the file can be downloaded. Null until it is made.
    expires_at: Optional[datetime] = None
    #: Where to download it, while it can be. Null otherwise.
    download_url: Optional[str] = None
    detail: str


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No ID cards on this host.")
    return school


def _refused(request):
    """`(school, None)`, or `(school, the 403)` for a login that may not print here."""
    school = _school_of(request)
    if not may_print(request.user, school):
        return school, (403, MessageOut(detail=MAY_NOT_PRINT))
    return school, None


def _chosen_term(term_id):
    if term_id is not None:
        return get_object_or_404(Term, pk=term_id)
    return Term.objects.filter(is_current=True).first() or Term.objects.order_by("-starts_on").first()


def _counts(school, term):
    """`{class id: children placed this term who are on the roll}`: the same children a print would hold."""
    placed = list(ClassPlacement.objects.filter(term=term).values_list("class_group_id", "student_membership_id"))
    live = set(
        Membership.objects.filter(
            pk__in=[m for _, m in placed], school=school, role=Role.STUDENT, status__in=LIVE_STATUSES
        ).values_list("pk", flat=True)
    )
    counts = {}
    for group_id, membership_id in placed:
        if membership_id in live:
            counts[group_id] = counts.get(group_id, 0) + 1
    return counts


def _when(moment) -> str:
    return timezone.localtime(moment).strftime("%-d %b %Y, %H:%M")


@router.get("/", response={200: OverviewOut, 403: MessageOut}, tags=["id-cards"])
def overview(request, term_id: Optional[int] = None):
    """The page: the term chosen (the current one unless `term_id` says), its classes, and the log."""
    school, refused = _refused(request)
    if refused is not None:
        return refused
    term = _chosen_term(term_id)
    terms = [TermOut(id=t.pk, label=str(t), is_current=t.is_current) for t in Term.objects.order_by("-starts_on")]
    classes = []
    if term is not None:
        counts = _counts(school, term)
        classes = [
            ClassOut(id=g.pk, name=g.name, students=counts.get(g.pk, 0))
            for g in ClassGroup.objects.filter(is_active=True)
        ]
    prints = [_line(p, request.user) for p in IdCardPrint.objects.all()[:LOG_LENGTH]]
    ends = cards.session_ends_on(term.session) if term is not None else None
    return OverviewOut(
        terms=terms,
        term=(
            ChosenTermOut(
                id=term.pk, label=str(term), session=term.session, expires_on=ends.isoformat() if ends else None
            )
            if term is not None
            else None
        ),
        classes=classes,
        phone_set=bool((school.phone or "").strip()),
        prints=prints,
    )


def _line(job, user) -> PrintLineOut:
    expires_at = _expires_at(job)
    live = job.state == PrintState.READY and expires_at is not None and expires_at > timezone.now()
    return PrintLineOut(
        id=job.pk,
        class_group=job.class_group_name,
        term=job.term_label,
        card_count=job.card_count,
        by=job.requested_by_name,
        at=_when(job.created_at),
        state=job.state,
        state_label=PrintState(job.state).label,
        mine_to_download=bool(live and job.requested_by_id == user.pk),
    )


@router.get(
    "/classes/{int:class_group_id}/{int:term_id}/",
    response={200: RosterOut, 403: MessageOut},
    tags=["id-cards"],
)
def roster(request, class_group_id: int, term_id: int):
    """Who could be printed for this class and term, for choosing some of them."""
    school, refused = _refused(request)
    if refused is not None:
        return refused
    group = get_object_or_404(ClassGroup, pk=class_group_id)
    term = get_object_or_404(Term, pk=term_id)
    return RosterOut(
        class_group_id=group.pk,
        class_group=str(group),
        term_id=term.pk,
        term=str(term),
        children=[
            ChildOut(student_membership_id=c["id"], name=c["name"], admission_number=c["admission_number"])
            for c in cards.students_of(school, group, term)
        ],
    )


@router.post(
    "/classes/{int:class_group_id}/{int:term_id}/print/",
    response={202: JobOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
    tags=["id-cards"],
)
def start(request, class_group_id: int, term_id: int, payload: PrintIn):
    """Start making the file. Answers at once; the page then watches the job."""
    school, refused = _refused(request)
    if refused is not None:
        return refused
    group = get_object_or_404(ClassGroup, pk=class_group_id)
    term = get_object_or_404(Term, pk=term_id)
    try:
        job = printing.start(request.user, school, group, term, payload.student_ids)
    except printing.NotAllowedToPrint as exc:
        return 403, MessageOut(detail=str(exc))
    except printing.NothingToPrint as exc:
        return 409, MessageOut(detail=str(exc))
    except printing.NotInTheClass as exc:
        return 422, MessageOut(detail=str(exc))
    return 202, _job_out(job)


def _my_job(request, job_id):
    """The job, if it is this person's and they may still print. Else 404."""
    school = _school_of(request)
    job = IdCardPrint.objects.filter(pk=job_id, requested_by_id=request.user.pk).first()
    if job is None or not may_print(request.user, school):
        raise Http404("No such print.")
    return job


@router.get("/jobs/{int:job_id}/", response={200: JobOut}, tags=["id-cards"])
def job_status(request, job_id: int):
    """How far the job has got. A job whose message was lost is asked for again."""
    job = _my_job(request, job_id)
    if job.state in (PrintState.PENDING, PrintState.BUILDING):
        printing.nudge(job)
    return _job_out(job)


@router.get("/jobs/{int:job_id}/pdf/", response={200: None, 409: MessageOut, 410: MessageOut}, tags=["id-cards"])
def job_pdf(request, job_id: int):
    """The file, through the upload service's sending (`files.views.send`)."""
    from files import service
    from files.views import PRIVATE, send

    job = _my_job(request, job_id)
    if job.state != PrintState.READY:
        return 409, MessageOut(detail="The file is not ready yet.")
    stored = service.find(job.file_key)
    if stored is None or service.is_expired(stored) or stored.uploaded_by_id != request.user.pk:
        return 410, MessageOut(detail=_GONE)
    return send(stored, printing.VARIANT, cache_control=PRIVATE, download_name=printing.filename(job))


_GONE = (
    "This file was removed a day after it was made, as every printed class is. "
    "Print the ID cards again to make a new one: the cards will have the same QR codes."
)


def _expires_at(job):
    from files.service import KEEP_MADE_FOR

    # The stored file's clock starts when it is made, which is when the job
    # finished (`files.service.keep_made`).
    return job.finished_at + KEEP_MADE_FOR if job.finished_at else None


def _job_out(job) -> JobOut:
    expires_at = _expires_at(job) if job.state == PrintState.READY else None
    gone = expires_at is not None and expires_at <= timezone.now()
    ready = job.state == PrintState.READY and not gone
    return JobOut(
        id=job.pk,
        state=job.state,
        state_label=PrintState(job.state).label,
        class_group=job.class_group_name,
        term=job.term_label,
        done=job.done,
        total=job.total,
        card_count=job.card_count,
        created_at=job.created_at,
        expires_at=expires_at,
        download_url=f"/api/id-cards/jobs/{job.pk}/pdf/" if ready else None,
        detail=_sentence(job, gone),
    )


def _sentence(job, gone) -> str:
    if job.state == PrintState.PENDING:
        return "Waiting to start. This page will show progress."
    if job.state == PrintState.BUILDING:
        return f"Making the cards: {job.done} of {job.total} done."
    if job.state == PrintState.FAILED:
        return "The cards could not be made. Try again, and tell Classnode if it keeps happening."
    if gone:
        return _GONE
    count = job.card_count or 0
    cards_ = f"{count} ID card{'' if count == 1 else 's'}"
    return (
        f"{cards_} ready: ten to an A4 sheet, each sheet of fronts followed by its backs. "
        "Print double-sided, flipped on the long edge, at 100% (not fit to page), and cut along the marks. "
        "The file is kept for a day."
    )


__all__ = ["router"]
