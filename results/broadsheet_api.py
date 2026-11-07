"""HTTP for the master broadsheet: read it, and ask for it as a PDF or Excel file.

`results.broadsheet` holds the numbers and the rule for who may, and
`results.broadsheet_files` makes the files. `docs/broadsheet.md`.

    GET  /api/results/master-broadsheet/<class>/<term>/        the table
    POST /api/results/master-broadsheet/<class>/<term>/files/  start a PDF (A3 or A4) or an Excel file

A started file is watched and downloaded through the report-card print routes
(`results.print_api`): the same job row, the same status, the same download
that only the person who asked can use and only for a day.

**Who may is asked on every route, on the server** (`broadsheet.may_see`): the
principal, the vice principal (academic) and the administrator for any class, a
class teacher for their own. The routes answer **403** to somebody with no
standing to see any class, asked before either lookup so the answer does not say
whether a class exists, and 403 again for a teacher asking about a class that is
not theirs.

**The position is left out of the payload, not hidden by the page**, when the
school hides positions: a field omitted from a screen that the JSON still
carries is the same leak with an extra step (`results.api`).
"""

from typing import List, Optional

from django.http import Http404
from ninja import Router, Schema

from academics.models import ClassGroup, Term
from accounts.session import session_auth

from . import broadsheet, broadsheet_files, class_print
from .print_api import JobOut, MessageOut, _job_out

router = Router(auth=session_auth)


class ColumnOut(Schema):
    subject_id: int
    subject: str
    #: "paper" (an Ogun component), "ca", "exam" or "pct".
    key: str
    label: str
    out_of: Optional[int] = None


class RowOut(Schema):
    student_membership_id: int
    name: str
    #: One entry per column; null is a paper not marked, shown as "-".
    cells: List[Optional[str]]
    total: Optional[str]
    average: Optional[str]
    #: Absent (null) for everybody when the school hides positions.
    position: Optional[int] = None
    #: `{"A": 3, "B": 5}` for every letter in `grade_letters`; null for a
    #: child with no graded subject.
    grades: Optional[dict] = None
    promotion: Optional[str]


class FooterOut(Schema):
    label: str
    cells: List[Optional[str]]


class BroadsheetOut(Schema):
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    school: str
    #: True when the class is not released: these figures are live.
    preview: bool
    #: "ogun" or "standard", which decides whether components get columns.
    template: str
    show_position: bool
    ranked: int
    columns: List[ColumnOut]
    grade_letters: List[str]
    rows: List[RowOut]
    footer: List[FooterOut]


class FileIn(Schema):
    #: "pdf" or "xlsx".
    format: str
    #: "A3" or "A4" for a PDF; ignored for Excel.
    paper: str = ""


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No results on this host.")
    return school


def _may(request, class_group_id, term_id):
    """`(school, class, term, None)` or `(..., (403, MessageOut))`.

    Standing first, so somebody with none learns nothing about any class. Then
    the lookups, and for anybody who is not office staff a class or term that
    does not exist is the same 403 as one that is not theirs: a class teacher
    must not be able to list the school's classes by trying ids. The office may
    open any class, so a 404 tells them nothing they cannot see.
    """
    school = _school_of(request)
    if not broadsheet.may_see_any(request.user, school):
        return school, None, None, (403, MessageOut(detail=broadsheet.MAY_NOT_SEE))
    refused = (403, MessageOut(detail=broadsheet.MAY_NOT_SEE))
    group = ClassGroup.objects.filter(pk=class_group_id).first()
    term = Term.objects.filter(pk=term_id).first()
    if group is None or term is None:
        if set(request.user.roles_at(school)) & class_print.PRINTING_ROLES:
            raise Http404("No such class or term.")
        return school, group, term, refused
    if not broadsheet.may_see(request.user, school, group, term):
        return school, group, term, refused
    return school, group, term, None


def _text(value):
    return None if value is None else broadsheet.text(value)


def payload(sheet) -> BroadsheetOut:
    letters = list(sheet.letters)
    return BroadsheetOut(
        class_group_id=sheet.class_group_id,
        class_group=sheet.class_group,
        term_id=sheet.term_id,
        term=sheet.term,
        school=sheet.school,
        preview=sheet.preview,
        template="ogun" if sheet.ogun else "standard",
        show_position=sheet.show_position,
        ranked=sheet.ranked,
        columns=[
            ColumnOut(subject_id=c.subject_id, subject=c.subject, key=c.key, label=c.label, out_of=c.out_of)
            for c in sheet.columns
        ],
        grade_letters=letters,
        rows=[
            RowOut(
                student_membership_id=r.student_id,
                name=r.name,
                cells=[_text(v) for v in r.values],
                total=_text(r.total),
                average=_text(r.average),
                position=r.position if sheet.show_position else None,
                grades={letter: r.grades.get(letter, 0) for letter in letters} if r.graded else None,
                promotion=r.promotion,
            )
            for r in sheet.rows
        ],
        footer=[FooterOut(label=label, cells=[_text(v) for v in values]) for label, values in sheet.footer],
    )


@router.get(
    "/master-broadsheet/{int:class_group_id}/{int:term_id}/",
    response={200: BroadsheetOut, 403: MessageOut},
    tags=["results"],
)
def master_broadsheet(request, class_group_id: int, term_id: int):
    """The class's table for the term: released from the cards, otherwise live."""
    _, group, term, refused = _may(request, class_group_id, term_id)
    if refused is not None:
        return refused
    return payload(broadsheet.build(group, term))


@router.post(
    "/master-broadsheet/{int:class_group_id}/{int:term_id}/files/",
    response={202: JobOut, 403: MessageOut, 409: MessageOut, 422: MessageOut},
    tags=["results"],
)
def master_broadsheet_file(request, class_group_id: int, term_id: int, payload_in: FileIn):
    """Start the PDF or the Excel file. Answers at once; the page then watches the job."""
    school, group, term, refused = _may(request, class_group_id, term_id)
    if refused is not None:
        return refused
    try:
        job = broadsheet_files.start(request.user, school, group, term, payload_in.format, payload_in.paper)
    except class_print.NotAllowedToPrint as exc:
        return 403, MessageOut(detail=str(exc))
    except class_print.NothingToPrint as exc:
        return 409, MessageOut(detail=str(exc))
    except broadsheet_files.BadChoice as exc:
        return 422, MessageOut(detail=str(exc))
    return 202, _job_out(job)


__all__ = ["router"]
