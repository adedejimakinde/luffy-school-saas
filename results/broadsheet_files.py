"""The master broadsheet as a landscape PDF or an Excel file, made off the request.

`docs/broadsheet.md`. This is the report-card print path (`docs/class-print.md`)
with a different thing in the file, not a second path:

- the job is a `ClassCardPrint` row (`kind` says what it makes), so the print
  log, the heartbeat, the double-press guard and the "ask again" for a lost
  message are `class_print`'s, not copies of them;
- it runs in the same Celery task (`results.tasks.build_class_cards`), which
  hands a broadsheet to `make()` once `class_print.claim()` has let it through;
- the file is kept by the same upload service (`files.service.keep_made`),
  private, for the one person who asked, and removed a day later by the same
  hourly sweep; the route that sends it asks who they are again
  (`results.print_api`);
- an unreleased class's PDF is stamped PREVIEW, NOT RELEASED on every page by
  the same stamp (`class_print.stamp_pages`), drawn into the page itself.

An Excel file is made by the same job for the same reasons: it is logged, kept
private and removed after a day like the PDF. It has the same columns, because
both draw `broadsheet.Sheet`.
"""

import logging
import shutil

from django.db import connection, transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from . import broadsheet, class_print
from .models import ClassCardPrint, PrintKind, PrintState

logger = logging.getLogger(__name__)

PDF, XLSX = "pdf", "xlsx"
FORMATS = (PDF, XLSX)

#: Paper for the PDF, always landscape, in millimetres (width, height).
PAPERS = {"A4": (297, 210), "A3": (420, 297)}
DEFAULT_PAPER = "A4"

VARIANTS = {PrintKind.BROADSHEET_PDF: "class-broadsheet.pdf", PrintKind.BROADSHEET_XLSX: "class-broadsheet.xlsx"}


class BadChoice(class_print.PrintError):
    """A format or a paper that is not one of the two each. For the person asking."""


def kinds() -> tuple:
    return (PrintKind.BROADSHEET_PDF, PrintKind.BROADSHEET_XLSX)


def is_broadsheet(job) -> bool:
    return job.kind in kinds()


# -- starting ---------------------------------------------------------------------


def start(actor, school, class_group, term, fmt, paper="") -> ClassCardPrint:
    """Ask for the class's broadsheet as a PDF (on `paper`) or an Excel file.

    Returns the job, queued once this commits. Who may is asked here again,
    whatever the page showed. Pressing twice is one job, as for the cards.
    """
    if not broadsheet.may_see(actor, school, class_group, term):
        raise class_print.NotAllowedToPrint(broadsheet.MAY_NOT_SEE)
    if fmt not in FORMATS:
        raise BadChoice("A broadsheet is made as a PDF or as an Excel file.")
    if fmt == PDF:
        paper = (paper or DEFAULT_PAPER).upper()
        if paper not in PAPERS:
            raise BadChoice("A broadsheet PDF is printed on A3 or A4 paper, landscape.")
        kind = PrintKind.BROADSHEET_PDF
    else:
        paper, kind = "", PrintKind.BROADSHEET_XLSX

    _, children = class_print.roster(class_group, term)
    if not children:
        raise class_print.NothingToPrint(
            f"{class_group} has no children with results for {term}, so there is no broadsheet to make."
        )

    from audit.log import name_of

    with transaction.atomic():
        running = (
            ClassCardPrint.objects.select_for_update()
            .filter(
                class_group=class_group, term=term, requested_by_id=actor.pk, kind=kind, paper=paper,
                state__in=[PrintState.PENDING, PrintState.BUILDING],
            )
            .first()
        )
        if running is not None:
            return running
        job = ClassCardPrint.objects.create(
            class_group=class_group,
            term=term,
            kind=kind,
            paper=paper,
            class_group_name=str(class_group)[:255],
            term_label=str(term)[:255],
            requested_by_id=actor.pk,
            requested_by_name=name_of(actor)[:255],
            requested_by_roles=",".join(sorted(actor.roles_at(school)))[:100],
            student_ids=[],
            preview=None,
            total=len(children),
            last_enqueued_at=timezone.now(),
        )
        schema, job_id = connection.schema_name, job.pk
        transaction.on_commit(lambda: class_print._enqueue(schema, job_id))
    logger.info(
        "Broadsheet asked for: %s %s, %s%s, by user %s.",
        job.class_group_name, job.term_label, fmt, f" {paper}" if paper else "", actor.pk,
    )
    return job


# -- in the worker ------------------------------------------------------------------


def make(job) -> ClassCardPrint:
    """Make the file for a claimed broadsheet job. Runs in the school's schema, off the request."""
    from files import service, storage
    from files.kinds import Kind

    workdir = storage.building_dir(connection.schema_name)
    variant = VARIANTS[job.kind]
    try:
        sheet = broadsheet.build(job.class_group, job.term)
        if not sheet.rows:
            raise class_print.NothingToPrint("There were no children to put on the broadsheet.")
        class_print._progress(job, 0, len(sheet.rows))
        out = workdir / variant
        if job.kind == PrintKind.BROADSHEET_PDF:
            pages = write_pdf(sheet, job.paper or DEFAULT_PAPER, out, title=_title(job, sheet))
        else:
            write_xlsx(sheet, out, title=_title(job, sheet))
            pages = None
        stored = service.keep_made(Kind.CLASS_BROADSHEET, out, variant, by_id=job.requested_by_id, pages=pages)
        ClassCardPrint.objects.filter(pk=job.pk).update(
            state=PrintState.READY,
            preview=sheet.preview,
            card_count=len(sheet.rows),
            done=len(sheet.rows),
            total=len(sheet.rows),
            file_key=stored.key,
            error="",
            finished_at=timezone.now(),
        )
        logger.info(
            "Broadsheet printed: %s %s, %s children, %s, %s, by user %s.",
            job.class_group_name, job.term_label, len(sheet.rows),
            "xlsx" if job.kind == PrintKind.BROADSHEET_XLSX else f"pdf {job.paper}",
            "preview" if sheet.preview else "released", job.requested_by_id,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return ClassCardPrint.objects.get(pk=job.pk)


def _title(job, sheet) -> str:
    title = f"Broadsheet, {job.class_group_name}, {job.term_label}"
    return f"{title} ({class_print.WATERMARK})" if sheet.preview else title


def filename(job) -> str:
    extension = "xlsx" if job.kind == PrintKind.BROADSHEET_XLSX else "pdf"
    words = ["broadsheet", job.class_group_name, job.term_label.replace("/", "-")]
    if job.paper:
        words.append(job.paper)
    if job.preview:
        words.append("preview not released")
    return f"{slugify(' '.join(words))}.{extension}"


# -- the PDF --------------------------------------------------------------------------


def _em_width(sheet) -> float:
    """About how wide the table is, in ems, so the type can be sized to the page."""
    width = 15.0  # the name
    for column in sheet.columns:
        width += 3.7 if column.key == "pct" else 3.1
    width += 3.6 + 3.9  # total, average
    width += 3.4 if sheet.show_position else 0
    width += 2.4 * len(sheet.letters)
    width += 11.0  # promotion
    return width


def font_pt(sheet, paper) -> float:
    """The type size at which every column fits the paper's width, between 4 and 9 pt."""
    page_mm = PAPERS[paper][0] - 16
    available_pt = page_mm / 25.4 * 72
    return round(max(4.0, min(9.0, available_pt / _em_width(sheet))), 2)


def html_for(sheet, paper) -> str:
    from . import look, pdf

    columns, spans = [], sheet.subjects()
    previous = None
    for column in sheet.columns:
        columns.append(
            {"label": column.label, "out_of": column.out_of, "first": column.subject_id != previous}
        )
        previous = column.subject_id
    firsts = [c["first"] for c in columns]

    def cells(values):
        return [(broadsheet.text(v), firsts[i]) for i, v in enumerate(values)]

    rows = []
    for row in sheet.rows:
        rows.append(
            {
                "name": row.name,
                "values": cells(row.values),
                "total": broadsheet.text(row.total),
                "average": broadsheet.text(row.average),
                "position": broadsheet.text(row.position),
                "grades": [
                    (broadsheet.text(row.grades.get(letter, 0) if row.graded else None), i == 0)
                    for i, letter in enumerate(sheet.letters)
                ],
                "promotion": row.promotion or "-",
            }
        )
    return render_to_string(
        "results/broadsheet_print.html",
        {
            "sheet": sheet,
            "paper": paper,
            "font_pt": font_pt(sheet, paper),
            "subject_spans": spans,
            "header_columns": columns,
            "printed_rows": rows,
            "printed_footer": [(label, cells(values)) for label, values in sheet.footer],
            "trailing": 2 + (1 if sheet.show_position else 0) + len(sheet.letters) + 1,
            "look": look.for_card(sheet.school),
            "fonts": pdf.FONTS.as_uri(),
        },
    )


def write_pdf(sheet, paper, out_path, *, title) -> int:
    """Draw the sheet on `paper`, landscape, and stamp it if it is a preview. Returns pages."""
    from weasyprint import HTML

    raw = out_path.with_name("raw.pdf")
    HTML(string=html_for(sheet, paper)).write_pdf(raw)
    return class_print.stamp_pages(raw, out_path, preview=sheet.preview, title=title)


# -- the Excel file ----------------------------------------------------------------------

#: The rows above the children: a title, a line saying released or not, the
#: subjects, and the column headers. The header the file is read by is the last.
TITLE_ROW, STATUS_ROW, SUBJECT_ROW, HEADER_ROW = 1, 2, 3, 4


def header_labels(sheet) -> list:
    """The column headings of the file's header row, in order, as the cells hold them."""
    labels = ["Name"]
    for column in sheet.columns:
        labels.append(f"{column.label} ({column.out_of})" if column.out_of and column.key != "pct" else column.label)
    labels += ["Total", "Average"]
    if sheet.show_position:
        labels.append("Position")
    labels += list(sheet.letters)
    labels.append("Promotion")
    return labels


def write_xlsx(sheet, out_path, *, title) -> None:
    """The sheet as .xlsx: the same columns, the children, then the three footer rows.

    Figures are numbers, so the school can add to them; a paper not marked is
    the text "-", never a zero. Text is written as text, so a name that begins
    with "=" is a name and not a formula.
    """
    from decimal import Decimal

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.properties import PageSetupProperties

    book = Workbook()
    ws = book.active
    ws.title = "Broadsheet"
    book.properties.title = title
    book.properties.creator = "Classnode"

    def put(row, col, value, *, bold=False, number=None, align=None, fill=None):
        cell = ws.cell(row=row, column=col)
        if isinstance(value, str):
            cell.value = value
            cell.data_type = "s"
        elif isinstance(value, Decimal):
            cell.value = float(value)
            cell.number_format = "0.00"
        else:
            cell.value = value
            if number:
                cell.number_format = number
        if bold:
            cell.font = Font(bold=True)
        if align:
            cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        return cell

    def figure(value):
        return "-" if value is None else value

    put(TITLE_ROW, 1, f"{sheet.school}: master broadsheet, {sheet.class_group}, {sheet.term}", bold=True)
    put(
        STATUS_ROW, 1,
        f"{class_print.WATERMARK}: these figures are live and may change." if sheet.preview else "Released results.",
        bold=sheet.preview,
    )

    labels = header_labels(sheet)
    for index, label in enumerate(labels, start=1):
        put(HEADER_ROW, index, label, bold=True, align="center", fill="F0F0F2")
    col = 2
    for name, span in sheet.subjects():
        put(SUBJECT_ROW, col, name, bold=True, align="center", fill="F0F0F2")
        if span > 1:
            ws.merge_cells(start_row=SUBJECT_ROW, start_column=col, end_row=SUBJECT_ROW, end_column=col + span - 1)
        col += span

    def tail(row):
        values = [figure(row.total), figure(row.average)]
        if sheet.show_position:
            values.append(figure(row.position))
        values += [figure(row.grades.get(letter, 0) if row.graded else None) for letter in sheet.letters]
        values.append(row.promotion or "-")
        return values

    first = HEADER_ROW + 1
    for offset, row in enumerate(sheet.rows):
        r = first + offset
        put(r, 1, row.name or "A child with no name on record")
        values = [figure(v) for v in row.values] + tail(row)
        for index, value in enumerate(values, start=2):
            put(r, index, value, align="center" if index < len(values) + 1 else "left")

    footer_first = first + len(sheet.rows)
    for offset, (label, values) in enumerate(sheet.footer):
        r = footer_first + offset
        put(r, 1, label, bold=True, fill="F7F7F9")
        for index, value in enumerate([figure(v) for v in values], start=2):
            put(r, index, value, bold=True, align="center", fill="F7F7F9")

    ws.column_dimensions["A"].width = 28
    for index in range(2, len(labels) + 1):
        ws.column_dimensions[get_column_letter(index)].width = 18 if index == len(labels) else 8
    ws.freeze_panes = ws.cell(row=first, column=2)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 8  # A3; the sheet is wide
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToHeight = 0
    if sheet.preview:
        ws.oddHeader.center.text = class_print.WATERMARK
    book.save(out_path)


__all__ = [
    "BadChoice",
    "DEFAULT_PAPER",
    "FORMATS",
    "PAPERS",
    "filename",
    "header_labels",
    "is_broadsheet",
    "make",
    "start",
    "write_pdf",
    "write_xlsx",
]
