"""A class's report cards as one PDF: "Print report cards". `docs/class-print.md`.

One press on the results page, for one class and one term, makes one file:
every card (or the children chosen) one after another, each starting on a new
A4 page, in the school's own template, drawn by the renderer the single card
uses (`results.pdf`), so a page of this file is the card a family downloads.

## Released, or a preview, and a preview cannot pass for a card

- **Released**: each card is the file that went home. The stored file
  (`ReleasedCardPdf`, the family's copy, never the copy with health) is used
  where it exists, and rendered from the frozen card where it does not yet.
- **Not released**: a **preview**. The cards are frozen exactly as a release
  would freeze them, inside a transaction that is then rolled back, so they say
  what the cards would say if the class were released now, and nothing of them
  is kept. Every page of the file is then stamped "PREVIEW, NOT RELEASED"
  across its middle and above and below it. The stamp is in the page itself,
  not a note beside it or a layer a viewer can hide.

## Who, asked on every request

`may_print()`: a principal, a vice principal (academic) or an administrator
for any class; a class teacher for the class they are class teacher of that
term; nobody else, a subject teacher and a parent included. It is asked when
the job is started, again on every status read, and again before the file is
sent, so a teacher taken off a class cannot fetch the file they made for it.

## Off the request, card by card

`build()` runs in a worker (`results.tasks.build_class_cards`). Each card is
rendered on its own and written to disk before the next is started, and the
parts are joined at the end (pikepdf), so memory is a card at a time plus the
joining, not a class of layouts. Progress is written after every card, and
that write is also the job's heartbeat: the queue can hand a long job to a
second worker after five minutes (`settings.CELERY_BROKER_TRANSPORT_OPTIONS`),
and the second one finds the heartbeat fresh and leaves the job alone
(`claim()`). A heartbeat that has gone stale is a worker that died, and a
status read asks for the job again.

## Kept for a day, for one person

The file goes through the upload service's store (`files.service.keep_made`),
private, with no readers on the generic route, and is sent by this module's
route only to the person who asked (`print_api`). It is removed by the hourly
check a day after it was made, and refused from that moment even before then.
The job row stays: it is the print log.
"""

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Role

from .models import ClassCardPrint, PdfState, PrintState, ReleasedCard, ReleasedCardPdf, ResultSheet, SheetState

logger = logging.getLogger(__name__)

#: Who may print any class's cards. A class teacher may print their own.
PRINTING_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)

#: The name of the one variant the stored file has.
VARIANT = "class-cards.pdf"

#: The words on every page of a preview.
WATERMARK = "PREVIEW, NOT RELEASED"

#: A job building with no heartbeat for this long is one whose worker died.
#: Several times the slowest card, and well under the broker's five minutes.
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


# -- who ------------------------------------------------------------------------


def may_print(actor, school, class_group, term) -> bool:
    """May `actor` print `class_group`'s cards for `term`, at `school`?

    Asked of `actor.roles_at(school)`, which is this school's roles only: being
    a principal at another school gives nothing here (`test_class_print`
    breaks this to prove it).
    """
    if school is None or not getattr(actor, "is_authenticated", False):
        return False
    roles = set(actor.roles_at(school))
    if roles & PRINTING_ROLES:
        return True
    if Role.TEACHER.value not in roles:
        return False
    from academics import services as academics

    membership_id = actor.membership_id_at(school, Role.TEACHER)
    return membership_id is not None and academics.is_class_teacher(membership_id, class_group, term)


def may_print_any(actor, school) -> bool:
    """Could `actor` print some class's cards here? The cheap first question."""
    if school is None or not getattr(actor, "is_authenticated", False):
        return False
    roles = set(actor.roles_at(school))
    return bool(roles & (PRINTING_ROLES | {Role.TEACHER.value}))


# -- what -----------------------------------------------------------------------


def sheet_of(class_group, term):
    return ResultSheet.objects.filter(class_group=class_group, term=term).first()


def is_released(sheet) -> bool:
    return sheet is not None and sheet.state == SheetState.RELEASED


def released_cards(sheet):
    """Each child's card from this sheet, as a family is served it, by name.

    A card is the one `cards.card_for()` names, the rule the family's own page
    and file use: the earliest release, then its latest version. A child whose
    card went home with another class (moved, and released twice) is not in
    this class's print, because her card is not this class's.
    """
    from . import cards

    latest = (
        ReleasedCard.objects.filter(sheet=sheet)
        .order_by("student_membership_id", "-version", "-id")
        .distinct("student_membership_id")
    )
    chosen = []
    for card in latest:
        theirs = cards.card_for(card.student_membership_id, sheet.term)
        if theirs is not None and theirs.pk == card.pk:
            chosen.append(card)
    return sorted(chosen, key=lambda c: (c.student_name.casefold(), c.student_membership_id))


def roster(class_group, term):
    """`(preview, [(student_membership_id, name)])`: who could be printed now."""
    sheet = sheet_of(class_group, term)
    if is_released(sheet):
        return False, [(c.student_membership_id, c.student_name) for c in released_cards(sheet)]
    from . import positions
    from .cards import _student_names

    ids = positions.roster_ids(class_group, term)
    names = _student_names(ids)
    children = sorted(((i, names.get(i, "")) for i in ids), key=lambda c: (c[1].casefold(), c[0]))
    return True, children


# -- starting -------------------------------------------------------------------


def start(actor, school, class_group, term, student_ids=None) -> ClassCardPrint:
    """Ask for a class's cards. Returns the job, queued once this commits.

    `student_ids` None or empty is the whole class. Every id must be a child
    who could be printed (`roster()`); one that is not is refused with a
    sentence rather than quietly left out, because a count that silently comes
    back short is a missing card nobody notices until a parent asks.

    Pressing twice is not two jobs: the same person asking for the same cards
    while one is still being made gets that one back.
    """
    if not may_print(actor, school, class_group, term):
        raise NotAllowedToPrint(_MAY_NOT_PRINT)
    preview, children = roster(class_group, term)
    if not children:
        raise NothingToPrint(f"{class_group} has no children with results for {term}, so there are no cards to print.")
    on_roll = {i for i, _ in children}
    wanted = sorted(set(int(i) for i in (student_ids or [])))
    stray = [i for i in wanted if i not in on_roll]
    if stray:
        raise NotInTheClass(
            f"{len(stray)} of the children chosen {'is' if len(stray) == 1 else 'are'} not in "
            f"{class_group} for {term}. Reload the page and choose again."
        )

    from audit.log import name_of

    with transaction.atomic():
        running = (
            ClassCardPrint.objects.select_for_update()
            .filter(
                class_group=class_group, term=term, requested_by_id=actor.pk,
                state__in=[PrintState.PENDING, PrintState.BUILDING], student_ids=wanted,
            )
            .first()
        )
        if running is not None:
            return running
        job = ClassCardPrint.objects.create(
            class_group=class_group,
            term=term,
            class_group_name=str(class_group)[:255],
            term_label=str(term)[:255],
            requested_by_id=actor.pk,
            requested_by_name=name_of(actor)[:255],
            requested_by_roles=",".join(sorted(actor.roles_at(school)))[:100],
            student_ids=wanted,
            preview=None,
            total=len(wanted) if wanted else len(children),
            last_enqueued_at=timezone.now(),
        )
        schema, job_id = connection.schema_name, job.pk
        transaction.on_commit(lambda: _enqueue(schema, job_id))
    logger.info(
        "Report cards asked for: %s %s, %s cards, by user %s (%s).",
        job.class_group_name, job.term_label, job.total, actor.pk, "preview" if preview else "released",
    )
    return job


_MAY_NOT_PRINT = (
    "Report cards for a class are printed by its class teacher, the vice "
    "principal (academic), the principal and the school's administrator."
)


def _enqueue(schema, job_id):
    """Publish one job. A broker that is down loses nothing: the row stays
    `pending`, and the next status read asks again (`nudge()`)."""
    from .tasks import build_class_cards

    try:
        build_class_cards.apply_async(args=[schema, job_id], retry=False)
    except Exception:  # noqa: BLE001 — after the commit; the row says it is owed
        logger.exception("Could not queue report-card print %s; it stays pending and is asked for again.", job_id)


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
    claimed = ClassCardPrint.objects.filter(pk=job.pk).filter(stale | dead).update(last_enqueued_at=now)
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
    taken = ClassCardPrint.objects.filter(pk=job_id).filter(
        Q(state=PrintState.PENDING)
        | (Q(state=PrintState.BUILDING) & (Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lte=now - STALE_AFTER)))
    ).update(state=PrintState.BUILDING, heartbeat_at=now, done=0)
    return ClassCardPrint.objects.get(pk=job_id) if taken else None


def _progress(job, done, total=None):
    fields = {"done": done, "heartbeat_at": timezone.now()}
    if total is not None:
        fields["total"] = total
    ClassCardPrint.objects.filter(pk=job.pk, state=PrintState.BUILDING).update(**fields)


def build(job_id) -> ClassCardPrint | None:
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
        sheet = sheet_of(job.class_group, job.term)
        wanted = set(job.student_ids or [])
        preview = not is_released(sheet)
        if preview:
            parts = _preview_parts(job, sheet, wanted, workdir)
        else:
            parts = _released_parts(job, sheet, wanted, workdir)
        if not parts:
            raise NothingToPrint("There were no cards to print.")
        out = workdir / VARIANT
        pages = merge(parts, out, preview=preview, title=_title(job, preview))
        stored = service.keep_made(Kind.CLASS_CARDS, out, VARIANT, by_id=job.requested_by_id, pages=pages)
        ClassCardPrint.objects.filter(pk=job.pk).update(
            state=PrintState.READY,
            preview=preview,
            card_count=len(parts),
            done=len(parts),
            total=len(parts),
            file_key=stored.key,
            error="",
            finished_at=timezone.now(),
        )
        logger.info(
            "Report cards printed: %s %s, %s cards, %s, by user %s.",
            job.class_group_name, job.term_label, len(parts), "preview" if preview else "released", job.requested_by_id,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return ClassCardPrint.objects.get(pk=job.pk)


def record_failure(job_id, exc):
    """The job could not be made: say so on the row, for the page and for whoever debugs it."""
    ClassCardPrint.objects.filter(pk=job_id).exclude(state=PrintState.READY).update(
        state=PrintState.FAILED,
        error=(f"{type(exc).__name__}: {exc}"[:2000] or "Failed"),
        finished_at=timezone.now(),
    )


def _released_parts(job, sheet, wanted, workdir):
    """The released cards, one file each, written to disk one at a time."""
    from . import pdf

    chosen = [c for c in released_cards(sheet) if not wanted or c.student_membership_id in wanted]
    _progress(job, 0, len(chosen))
    parts = []
    for index, card in enumerate(chosen):
        path = workdir / f"{index:04d}.pdf"
        # The family's copy: `content`, and never `health_content`, which
        # carries a child's health record and goes to four people only.
        stored = (
            ReleasedCardPdf.objects.filter(card=card, state=PdfState.BUILT).values_list("content", flat=True).first()
        )
        path.write_bytes(bytes(stored) if stored else pdf.render(card))
        del stored
        parts.append((card.student_name, path))
        _progress(job, index + 1)
    return parts


def preview_html(class_group, term, wanted=None, *, sheet=None, by_id=None):
    """`[(name, html)]` for the cards this class would get if released now.

    Freezes them exactly as `services.release()` does, from one read of the
    class, then **rolls the whole thing back**: nothing of a preview is kept,
    no card, no section and no file marker, and nothing is queued. Only the
    HTML leaves the transaction.
    """
    return list(_preview_html(class_group, term, wanted or set(), sheet=sheet, by_id=by_id))


def _preview_html(class_group, term, wanted, *, sheet=None, by_id=None, write=None):
    from attendance import summary as attendance_summary

    from . import cards, comments, pdf, positions, ratings, sessions

    out = []
    with transaction.atomic():
        if sheet is None:
            sheet = ResultSheet.objects.create(class_group=class_group, term=term)
        results = positions.class_results(class_group, term)
        attendance = attendance_summary.for_term(term, results.student_ids)
        card_by_student = cards.freeze_for_release(sheet, results, attendance=attendance, by=by_id)
        ratings.freeze_for_release(sheet, card_by_student)
        comments.freeze_for_release(sheet, card_by_student)
        sessions.freeze_for_release(sheet, card_by_student, results)
        chosen = [c for sid, c in card_by_student.items() if not wanted or sid in wanted]
        chosen.sort(key=lambda c: (c.student_name.casefold(), c.student_membership_id))
        for index, card in enumerate(chosen):
            html = pdf.html_for(card)
            out.append((card.student_name, write(index, html) if write else html))
        transaction.set_rollback(True)
    return out


def _preview_parts(job, sheet, wanted, workdir):
    """The preview: HTML from the rolled-back freeze, then one render at a time."""
    from weasyprint import HTML

    def write(index, html):
        path = workdir / f"{index:04d}.html"
        path.write_text(html, encoding="utf-8")
        return path

    pages = _preview_html(job.class_group, job.term, wanted, sheet=sheet, by_id=job.requested_by_id, write=write)
    _progress(job, 0, len(pages))
    parts = []
    for index, (name, html_path) in enumerate(pages):
        path = workdir / f"{index:04d}.pdf"
        HTML(string=html_path.read_text(encoding="utf-8")).write_pdf(path)
        html_path.unlink()
        parts.append((name, path))
        _progress(job, index + 1)
    return parts


def _title(job, preview):
    title = f"Report cards, {job.class_group_name}, {job.term_label}"
    return f"{title} ({WATERMARK})" if preview else title


def filename(job) -> str:
    words = ["report cards", job.class_group_name, job.term_label.replace("/", "-")]
    if job.preview:
        words.append("preview not released")
    return f"{slugify(' '.join(words))}.pdf"


# -- joining, and the stamp -------------------------------------------------------


def merge(parts, out_path: Path, *, preview: bool, title: str) -> int:
    """Join the cards' files into one, with a bookmark per child. Returns pages.

    Each card keeps its own pages, so each starts on a new page. A preview is
    stamped on every page (`_stamp()`).
    """
    import pikepdf

    sources = []
    out = pikepdf.new()
    try:
        with out.open_outline() as outline:
            for name, path in parts:
                source = pikepdf.open(path)
                sources.append(source)
                first = len(out.pages)
                out.pages.extend(source.pages)
                outline.root.append(pikepdf.OutlineItem(name or "A child with no name on record", first))
        if preview:
            stamp = _stamp(out)
            for page in out.pages:
                page.add_overlay(stamp, pikepdf.Rectangle(*[float(v) for v in page.mediabox]))
        out.docinfo["/Title"] = title
        out.docinfo["/Producer"] = "Classnode"
        out.save(out_path)
        return len(out.pages)
    finally:
        out.close()
        for source in sources:
            source.close()


#: Helvetica-Bold's widths (per 1000 em) for the letters the stamp uses, so the
#: words can be centred without a font file. Helvetica is one of the fonts
#: every PDF reader has, so nothing is embedded and the words stay as text.
_WIDTHS = {
    "P": 667, "R": 722, "E": 667, "V": 667, "I": 278, "W": 944, ",": 278, " ": 278,
    "N": 722, "O": 778, "T": 611, "L": 611, "A": 722, "S": 667, "D": 722,
}


def _width(text, size):
    return sum(_WIDTHS.get(ch, 722) for ch in text) * size / 1000


def _stamp(pdf):
    """One A4 Form XObject: the words three times on the diagonal, in red.

    A third opaque, so the card under it stays readable and the words cannot be
    missed. It is drawn into each page's content, so a viewer cannot switch it
    off the way it can hide an annotation or a layer.
    """
    import math

    import pikepdf

    width, height = 595.28, 841.89
    angle = math.atan2(height, width)
    cos, sin = math.cos(angle), math.sin(angle)
    lines = []
    for size, offset in ((56, 0), (30, 230), (30, -230)):
        across = _width(WATERMARK, size)
        # Centre of the line, moved along the other diagonal by `offset`.
        cx, cy = width / 2 - sin * offset, height / 2 + cos * offset
        x = cx - cos * across / 2 + sin * size * 0.35
        y = cy - sin * across / 2 - cos * size * 0.35
        lines.append(
            f"BT /F1 {size} Tf {cos:.5f} {sin:.5f} {-sin:.5f} {cos:.5f} {x:.2f} {y:.2f} Tm "
            f"({WATERMARK}) Tj ET"
        )
    content = "q /GS1 gs 0.80 0.05 0.05 rg " + " ".join(lines) + " Q"
    font = pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name("/Helvetica-Bold"),
        Encoding=pikepdf.Name.WinAnsiEncoding,
    )
    resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(F1=font),
        ExtGState=pikepdf.Dictionary(GS1=pikepdf.Dictionary(Type=pikepdf.Name.ExtGState, ca=0.33, CA=0.33)),
    )
    stamp = pikepdf.Stream(pdf, content.encode("ascii"))
    stamp.Type = pikepdf.Name.XObject
    stamp.Subtype = pikepdf.Name.Form
    stamp.BBox = [0, 0, width, height]
    stamp.Resources = resources
    #: So a reader of the file (and a test) can tell the stamp from the card.
    stamp.ClassnodePreview = True
    return stamp


__all__ = [
    "PRINTING_ROLES",
    "VARIANT",
    "WATERMARK",
    "NotAllowedToPrint",
    "NotInTheClass",
    "NothingToPrint",
    "PrintError",
    "build",
    "claim",
    "filename",
    "is_released",
    "may_print",
    "may_print_any",
    "merge",
    "nudge",
    "preview_html",
    "record_failure",
    "released_cards",
    "roster",
    "sheet_of",
    "start",
]
