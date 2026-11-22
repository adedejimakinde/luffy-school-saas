"""A class's ID cards as one PDF: "Print ID cards". `docs/id-cards.md`.

One press for one class and term makes one file: every child (or the children
chosen), ten to an A4 sheet, each sheet of fronts followed by its backs. It is
`results.class_print`'s twin and uses what that one uses:

- **A worker, off the request.** `idcards.tasks.build_id_cards` renders ten
  children at a time and writes each sheet to disk before the next, so memory
  is a sheet and not a class. Progress is written after every sheet, and the
  write is also the job's heartbeat: the queue can hand a long job to a second
  worker after five minutes, which finds the heartbeat fresh and leaves the job
  alone (`claim()`). A heartbeat gone stale is a worker that died, and a status
  read asks for the job again (`nudge()`).
- **A private file, for one person.** It goes through the upload service's store
  (`files.service.keep_made`, `Kind.ID_CARDS`), with no readers on the generic
  route, and is sent by `idcards.api` only to the person who asked.
- **Kept a day.** The hourly check (`files.service.sweep`) removes it a day
  after it was made, and the route refuses it from that moment, before the
  check has run. The job row stays: it is the print log.

## Who, asked on the server

`access.may_print()`: the principal, the vice principal (academic) and the
administrator. It is asked when a job is started, on every status read, and
again before the file is sent, so a person whose role has been taken away
cannot fetch a file they made.
"""

import logging
import shutil
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from . import cards, render
from .access import MAY_NOT_PRINT, may_print
from .models import IdCardPrint, PrintState

logger = logging.getLogger(__name__)

#: The name of the one variant the stored file has.
VARIANT = "id-cards.pdf"

#: A job building with no heartbeat for this long is one whose worker died.
STALE_AFTER = timedelta(seconds=120)
#: A job still waiting this long after it was queued is asked for again.
RE_ENQUEUE_AFTER = timedelta(seconds=60)


class PrintError(Exception):
    """A print that cannot be started. The message is for the person who asked."""


class NotAllowedToPrint(PrintError):
    pass


class NothingToPrint(PrintError):
    pass


class NotInTheClass(PrintError):
    pass


# -- starting -------------------------------------------------------------------


def start(actor, school, class_group, term, student_ids=None) -> IdCardPrint:
    """Ask for a class's cards. Returns the job, queued once this commits.

    `student_ids` None or empty is the whole class. Every id must be a child on
    this class's roll for this term; one that is not is refused with a sentence
    rather than quietly left out, because a count that comes back short is a
    missing card nobody notices until a child is at the gate without one.

    Pressing twice is not two jobs: the same person asking for the same cards
    while one is still being made gets that one back.
    """
    if not may_print(actor, school):
        raise NotAllowedToPrint(MAY_NOT_PRINT)
    children = cards.students_of(school, class_group, term)
    if not children:
        raise NothingToPrint(f"{class_group} has no children placed for {term}, so there are no cards to print.")
    on_roll = {c["id"] for c in children}
    wanted = sorted({int(i) for i in (student_ids or [])})
    stray = [i for i in wanted if i not in on_roll]
    if stray:
        raise NotInTheClass(
            f"{len(stray)} of the children chosen {'is' if len(stray) == 1 else 'are'} not in "
            f"{class_group} for {term}. Reload the page and choose again."
        )
    try:
        cards.require_address()
    except cards.NoAddress as exc:
        raise NothingToPrint(str(exc))

    from audit.log import name_of

    with transaction.atomic():
        running = (
            IdCardPrint.objects.select_for_update()
            .filter(
                class_group=class_group, term=term, requested_by_id=actor.pk,
                state__in=[PrintState.PENDING, PrintState.BUILDING], student_ids=wanted,
            )
            .first()
        )
        if running is not None:
            return running
        job = IdCardPrint.objects.create(
            class_group=class_group,
            term=term,
            class_group_name=str(class_group)[:255],
            term_label=str(term)[:255],
            session=term.session,
            requested_by_id=actor.pk,
            requested_by_name=name_of(actor)[:255],
            requested_by_roles=",".join(sorted(actor.roles_at(school)))[:100],
            student_ids=wanted,
            total=len(wanted) if wanted else len(children),
            last_enqueued_at=timezone.now(),
        )
        schema, job_id = connection.schema_name, job.pk
        transaction.on_commit(lambda: _enqueue(schema, job_id))
    logger.info(
        "ID cards asked for: %s %s, %s cards, by user %s.", job.class_group_name, job.term_label, job.total, actor.pk
    )
    return job


def _enqueue(schema, job_id):
    """Publish one job. A broker that is down loses nothing: the row stays
    `pending`, and the next status read asks again (`nudge()`)."""
    from .tasks import build_id_cards

    try:
        build_id_cards.apply_async(args=[schema, job_id], retry=False)
    except Exception:  # noqa: BLE001 — after the commit; the row says it is owed
        logger.exception("Could not queue ID card print %s; it stays pending and is asked for again.", job_id)


def nudge(job) -> bool:
    """Ask again for a job whose message was lost or whose worker died."""
    now = timezone.now()
    stale = Q(state=PrintState.PENDING) & (
        Q(last_enqueued_at__isnull=True) | Q(last_enqueued_at__lte=now - RE_ENQUEUE_AFTER)
    )
    dead = (
        Q(state=PrintState.BUILDING)
        & (Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lte=now - STALE_AFTER))
        & (Q(last_enqueued_at__isnull=True) | Q(last_enqueued_at__lte=now - STALE_AFTER))
    )
    claimed = IdCardPrint.objects.filter(pk=job.pk).filter(stale | dead).update(last_enqueued_at=now)
    if claimed:
        schema, job_id = connection.schema_name, job.pk
        transaction.on_commit(lambda: _enqueue(schema, job_id))
    return bool(claimed)


# -- in the worker ----------------------------------------------------------------


def claim(job_id, now=None):
    """Take the job, or return None if somebody else has it or it is done.

    One conditional `UPDATE`: two workers holding the same message both run it,
    and Postgres re-checks the `WHERE` against the newer row, so exactly one of
    them matches. A building job is taken over only when its heartbeat is stale.
    """
    now = now or timezone.now()
    taken = IdCardPrint.objects.filter(pk=job_id).filter(
        Q(state=PrintState.PENDING)
        | (Q(state=PrintState.BUILDING) & (Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lte=now - STALE_AFTER)))
    ).update(state=PrintState.BUILDING, heartbeat_at=now, done=0)
    return IdCardPrint.objects.get(pk=job_id) if taken else None


def _progress(job, done, total=None):
    fields = {"done": done, "heartbeat_at": timezone.now()}
    if total is not None:
        fields["total"] = total
    IdCardPrint.objects.filter(pk=job.pk, state=PrintState.BUILDING).update(**fields)


def build(job_id) -> IdCardPrint | None:
    """Make the file for one job. Runs inside the school's schema, off the request.

    Safe to run twice: `claim()` lets only one run through, and a finished job
    is left as it is.
    """
    from files import service, storage
    from files.kinds import Kind

    job = claim(job_id)
    if job is None:
        return None
    workdir = storage.building_dir(connection.schema_name)
    try:
        school = connection.tenant
        children = cards.students_of(school, job.class_group, job.term, only=set(job.student_ids or []))
        if not children:
            raise NothingToPrint("There were no cards to print.")
        parts = _sheets(job, school, children, workdir)
        out = workdir / VARIANT
        pages = merge(parts, out, title=f"ID cards, {job.class_group_name}, {job.term_label}")
        stored = service.keep_made(Kind.ID_CARDS, out, VARIANT, by_id=job.requested_by_id, pages=pages)
        IdCardPrint.objects.filter(pk=job.pk).update(
            state=PrintState.READY,
            card_count=len(children),
            done=len(children),
            total=len(children),
            file_key=stored.key,
            error="",
            finished_at=timezone.now(),
        )
        logger.info(
            "ID cards printed: %s %s, %s cards, by user %s.",
            job.class_group_name, job.term_label, len(children), job.requested_by_id,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return IdCardPrint.objects.get(pk=job.pk)


def _sheets(job, school, children, workdir):
    """`[(label, path)]`: one file per sheet of ten (its fronts and backs), written one at a time."""
    expires_on = cards.session_ends_on(job.session)
    look = cards.school_face(school)
    class_name = str(job.class_group.name)
    runs = [children[i : i + render.PER_SHEET] for i in range(0, len(children), render.PER_SHEET)]
    _progress(job, 0, len(children))
    parts, done = [], 0
    for number, run in enumerate(runs, start=1):
        faces = [
            cards.face_for(c, class_name=class_name, session=job.session, expires_on=expires_on, by_id=job.requested_by_id)
            for c in run
        ]
        html = render.html_for(look, class_name, faces, first_sheet=number, total_sheets=len(runs))
        path = workdir / f"{number:04d}.pdf"
        render.write_pdf(html, path)
        parts.append((f"Sheet {number}: {run[0]['name']} to {run[-1]['name']}", path))
        del faces, html
        done += len(run)
        _progress(job, done)
    return parts


def record_failure(job_id, exc):
    """The job could not be made: say so on the row, for the page and for whoever debugs it."""
    IdCardPrint.objects.filter(pk=job_id).exclude(state=PrintState.READY).update(
        state=PrintState.FAILED,
        error=(f"{type(exc).__name__}: {exc}"[:2000] or "Failed"),
        finished_at=timezone.now(),
    )


def merge(parts, out_path, *, title: str) -> int:
    """Join the sheets' files into one, with a bookmark per sheet. Returns pages."""
    import pikepdf

    sources = []
    out = pikepdf.new()
    try:
        with out.open_outline() as outline:
            for label, path in parts:
                source = pikepdf.open(path)
                sources.append(source)
                first = len(out.pages)
                out.pages.extend(source.pages)
                outline.root.append(pikepdf.OutlineItem(label, first))
        out.docinfo["/Title"] = title
        out.docinfo["/Producer"] = "Classnode"
        out.save(out_path)
        return len(out.pages)
    finally:
        out.close()
        for source in sources:
            source.close()


def filename(job) -> str:
    """What the person's browser saves it as."""
    words = ["id cards", job.class_group_name, job.term_label.replace("/", "-")]
    return f"{slugify(' '.join(words))}.pdf"


__all__ = [
    "VARIANT",
    "NotAllowedToPrint",
    "NotInTheClass",
    "NothingToPrint",
    "PrintError",
    "build",
    "claim",
    "filename",
    "merge",
    "nudge",
    "record_failure",
    "start",
]
