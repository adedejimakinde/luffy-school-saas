"""HTTP for "Print report cards": who can be printed, start, watch, download.

`results.class_print` holds every rule; this is its door. `docs/class-print.md`.

    GET  /api/results/print-cards/<class>/<term>/   who could be printed, and whether a preview
    POST /api/results/print-cards/<class>/<term>/   start a job: the whole class, or `student_ids`
    GET  /api/results/print-jobs/<job>/             how far it has got
    GET  /api/results/print-jobs/<job>/pdf/         the file, to the person who asked, for a day

**Who may is asked on every one of them**, on the server, of the school this
host is: `class_print.may_print()`. A page that hid the button would be a
restriction anybody could step round with a request.

The two class routes answer **403** to somebody with no standing to print any
class, asked before either lookup so that the answer does not say whether a
class exists, and 403 again to a teacher asking for a class that is not theirs,
in the sentence the chain uses. The two job routes answer a flat **404** to
anybody who is not the person who asked, and to that person once they may no
longer print that class: a job id is a number, and a 403 would say it exists.
A file past its day is a **410**, to its owner only, with a sentence.
"""

from datetime import datetime
from typing import List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import ClassGroup, Term
from accounts.session import session_auth

from . import class_print
from .models import ClassCardPrint, PrintState

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class ChildOut(Schema):
    student_membership_id: int
    name: str


class PrintableOut(Schema):
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    #: True when the class is not released: the file will be a preview,
    #: stamped "PREVIEW, NOT RELEASED" on every page.
    preview: bool
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
    #: Null until the job has looked: whether the file is a preview.
    preview: Optional[bool] = None
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
        raise Http404("No results on this host.")
    return school


def _class_and_term(request, class_group_id, term_id):
    school = _school_of(request)
    if not class_print.may_print_any(request.user, school):
        return school, None, None, (403, MessageOut(detail=class_print._MAY_NOT_PRINT))
    group = get_object_or_404(ClassGroup, pk=class_group_id)
    term = get_object_or_404(Term, pk=term_id)
    if not class_print.may_print(request.user, school, group, term):
        return school, group, term, (403, MessageOut(detail=class_print._MAY_NOT_PRINT))
    return school, group, term, None


@router.get(
    "/print-cards/{int:class_group_id}/{int:term_id}/",
    response={200: PrintableOut, 403: MessageOut},
    tags=["results"],
)
def printable(request, class_group_id: int, term_id: int):
    """Who could be printed for this class and term, for choosing some of them."""
    _, group, term, refused = _class_and_term(request, class_group_id, term_id)
    if refused is not None:
        return refused
    preview, children = class_print.roster(group, term)
    return PrintableOut(
        class_group_id=group.pk,
        class_group=str(group),
        term_id=term.pk,
        term=str(term),
        preview=preview,
        children=[ChildOut(student_membership_id=i, name=name) for i, name in children],
    )


@router.post(
    "/print-cards/{int:class_group_id}/{int:term_id}/",
    response={202: JobOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
    tags=["results"],
)
def start(request, class_group_id: int, term_id: int, payload: PrintIn):
    """Start making the file. Answers at once; the page then watches the job."""
    school, group, term, refused = _class_and_term(request, class_group_id, term_id)
    if refused is not None:
        return refused
    try:
        job = class_print.start(request.user, school, group, term, payload.student_ids)
    except class_print.NotAllowedToPrint as exc:
        return 403, MessageOut(detail=str(exc))
    except class_print.NothingToPrint as exc:
        return 409, MessageOut(detail=str(exc))
    except class_print.NotInTheClass as exc:
        return 422, MessageOut(detail=str(exc))
    return 202, _job_out(job)


def _my_job(request, job_id):
    """The job, if it is this person's and they may still print its class. Else 404."""
    school = _school_of(request)
    job = (
        ClassCardPrint.objects.select_related("class_group", "term")
        .filter(pk=job_id, requested_by_id=request.user.pk)
        .first()
    )
    if job is None or not class_print.may_print(request.user, school, job.class_group, job.term):
        raise Http404("No such print.")
    return job


@router.get("/print-jobs/{int:job_id}/", response={200: JobOut}, tags=["results"])
def job_status(request, job_id: int):
    """How far the job has got. A job whose message was lost is asked for again."""
    job = _my_job(request, job_id)
    if job.state in (PrintState.PENDING, PrintState.BUILDING):
        class_print.nudge(job)
    return _job_out(job)


@router.get(
    "/print-jobs/{int:job_id}/pdf/",
    response={200: None, 409: MessageOut, 410: MessageOut},
    tags=["results"],
)
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
    return send(stored, class_print.VARIANT, cache_control=PRIVATE, download_name=class_print.filename(job))


_GONE = (
    "This file was removed a day after it was made, as every printed class is. "
    "Print the report cards again to make a new one."
)


def _expires_at(job):
    from files.service import KEEP_MADE_FOR

    # The stored file's clock starts when it is made, which is when the job
    # finished (`files.service.keep_made`).
    return job.finished_at + KEEP_MADE_FOR if job.finished_at else None


def _job_out(job) -> JobOut:
    from django.utils import timezone

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
        preview=job.preview,
        card_count=job.card_count,
        created_at=job.created_at,
        expires_at=expires_at,
        download_url=f"/api/results/print-jobs/{job.pk}/pdf/" if ready else None,
        detail=_sentence(job, gone),
    )


def _sentence(job, gone):
    if job.state == PrintState.PENDING:
        return "Waiting to start. This page will show progress."
    if job.state == PrintState.BUILDING:
        return f"Making the cards: {job.done} of {job.total} done."
    if job.state == PrintState.FAILED:
        return "The cards could not be made. Try again, and tell Classnode if it keeps happening."
    if gone:
        return _GONE
    count = job.card_count or 0
    cards = f"{count} report card{'' if count == 1 else 's'}"
    if job.preview:
        return (
            f"{cards} ready, as a preview: these results are not released, so every page "
            "says PREVIEW, NOT RELEASED. The file is kept for a day."
        )
    return f"{cards} ready to download and print. The file is kept for a day."


__all__ = ["router"]
