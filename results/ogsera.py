"""Filling in the spreadsheet OGSERA sends a school, from what Classnode holds.

`docs/ogun-template.md` part 6. Ogun State template schools only.

The office downloads a template from OGSERA for one class (and one subject,
when the template is per subject), and uploads it here. Three steps, and the
file is sent again with each one: nothing is stored but the mapping.

1. **Headings.** The template's header row is found and listed. The first
   time, the office says which Classnode value each column holds (`FIELDS`,
   and each visible trait). The mapping is saved per school
   (`OgseraMapping`, in the school's own schema) and edited whenever a
   template changes. A column with no mapping is left alone.
2. **Check.** Every row of the table (down to its first empty row) is matched to a child **by learner's ID**, against the
   class's roster this term. The check lists rows whose ID matches nobody in
   the class, rows with no ID, children of the class missing from the file,
   children with no learner's ID in Classnode, and marks or ratings not yet
   entered. The filled file can be downloaded only when no row is unmatched
   and none is missing its ID.
3. **Fill.** Only mapped cells of matched rows are written, with openpyxl, so
   the file's formatting, sheets, formulas and validation stay as OGSERA made
   them. **A cell that already holds anything (a value or a formula) is left
   as it is**, unless the office ticks "replace existing values".

What is filled comes from the current term: the four Ogun papers by name
(`ogun.ASSESSMENTS`), their CA total and grand total, the ratings, and the
register. Never the health record: it is no column OGSERA asks for, and
`results.health` serves it to four readers only.
"""

import io
import zipfile
from dataclasses import dataclass, field

from django.db import transaction

from academics.models import ClassPlacement, StudentDetails, Term
from accounts.models import Membership, Role
from gradebook.models import Assessment, Score

from . import ogun, ratings
from .models import OgseraMapping, TraitRating

#: The values a column can hold, besides one per trait.
FIELDS = {
    "learner_id": "Learner's ID",
    "name": "Learner's name",
    "test1": "1st Test",
    "test2": "2nd Test",
    "assignment": "Assignment",
    "ca_total": "CA total (30)",
    "exam": "Exam",
    "total": "Total (100)",
    "times_opened": "Times school opened",
    "times_present": "Times present",
    "times_absent": "Times absent",
}

#: The Ogun papers each mark field reads, by the preset's own names.
PAPERS = {"test1": "1st Test", "test2": "2nd Test", "assignment": "Assignment", "exam": "Exam"}
MARK_FIELDS = set(PAPERS) | {"ca_total", "total"}

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNPACKED_BYTES = 40 * 1024 * 1024
#: How far down a header row is looked for: OGSERA puts a title block above it.
HEADER_SEARCH_ROWS = 30


class OgseraRefused(Exception):
    """The file, the class or the mapping cannot be used. The message is for the person."""


class NotAllowed(Exception):
    pass


def heading_key(text) -> str:
    """"1st  Test (10)" and "1ST TEST (10)" are one heading."""
    return " ".join(str(text or "").split()).lower()


# -- who, and where --------------------------------------------------------------


def require_office_at_an_ogun_school(actor, school):
    from academics.services import can_set_up

    if not can_set_up(actor, school):
        raise NotAllowed("OGSERA templates are filled in by a principal or an administrator of the school.")
    if not ogun.is_ogun():
        raise OgseraRefused(
            "Filling OGSERA templates is part of the Ogun State template. Choose it on the setup page first."
        )


# -- the mapping ---------------------------------------------------------------


def field_choices():
    """Every value a column may be mapped to: `(key, label)`."""
    choices = list(FIELDS.items())
    for group in ratings.enabled_groups() or []:
        for trait in ratings.traits(group):
            choices.append((f"trait:{trait.pk}", trait.name))
    return choices


def mapping() -> OgseraMapping:
    return OgseraMapping.objects.filter(pk=1).first() or OgseraMapping()


def save_mapping_as(actor, school, columns: dict, headings: dict) -> OgseraMapping:
    """`columns`: heading as typed -> field key, or blank to leave it unmapped."""
    require_office_at_an_ogun_school(actor, school)
    known = {key for key, _ in field_choices()}
    cleaned, shown = {}, {}
    for heading, key in (columns or {}).items():
        if not key:
            continue
        if key not in known:
            raise OgseraRefused(f"{key!r} is not a value Classnode can fill.")
        cleaned[heading_key(heading)] = key
        shown[heading_key(heading)] = str((headings or {}).get(heading, heading))
    if list(cleaned.values()).count("learner_id") != 1:
        raise OgseraRefused("Map exactly one column to the learner's ID: it is how rows are matched to children.")
    with transaction.atomic():
        row, _ = OgseraMapping.objects.select_for_update().get_or_create(pk=1)
        row.columns, row.headings, row.updated_by_id = cleaned, shown, actor.pk
        row.save()
    return row


# -- reading the file -------------------------------------------------------------


def open_workbook(raw: bytes):
    """The uploaded workbook, for reading and writing, after the size checks."""
    from openpyxl import load_workbook

    if len(raw) > MAX_FILE_BYTES:
        raise OgseraRefused("That file is over 5 MB. An OGSERA template is far smaller.")
    if not raw.startswith(b"PK\x03\x04"):
        raise OgseraRefused("That is not an Excel workbook (.xlsx). Upload the file OGSERA gave you.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        unpacked = sum(entry.file_size for entry in archive.infolist())
    except zipfile.BadZipFile:
        raise OgseraRefused("That workbook cannot be read. Save it again in Excel and try once more.")
    if unpacked > MAX_UNPACKED_BYTES:
        raise OgseraRefused("That workbook is far larger than a template needs.")
    try:
        return load_workbook(io.BytesIO(raw))
    except Exception:
        raise OgseraRefused("That workbook cannot be read. Save it again in Excel and try once more.")


@dataclass
class Header:
    sheet: object
    row: int
    #: Column number -> the heading as written.
    columns: dict


def _text_cells(sheet, row):
    found = {}
    for cell in sheet[row]:
        if isinstance(cell.value, str) and cell.value.strip():
            found[cell.column] = " ".join(cell.value.split())
    return found


def find_header(book, mapped: dict) -> Header:
    """The header row: the first row naming a mapped heading, else the wordiest.

    Looked for on every sheet within `HEADER_SEARCH_ROWS`, because OGSERA's
    templates carry a title block (the ministry, the school, the class) above
    the row of headings.
    """
    best = None
    for sheet in book.worksheets:
        for row in range(1, min(sheet.max_row, HEADER_SEARCH_ROWS) + 1):
            cells = _text_cells(sheet, row)
            hits = sum(1 for text in cells.values() if heading_key(text) in mapped)
            if mapped and hits:
                score = (2, hits)
            else:
                score = (1, len(cells))
            if len(cells) >= 2 and (best is None or score > best[0]):
                best = (score, Header(sheet, row, cells))
    if best is None:
        raise OgseraRefused("No row of headings was found in that workbook.")
    return best[1]


def headings(actor, school, raw: bytes) -> "Check":
    """Step 1: the header row, each heading with what it is mapped to now."""
    from openpyxl.utils import get_column_letter

    require_office_at_an_ogun_school(actor, school)
    mapped = mapping().columns
    header = find_header(open_workbook(raw), mapped)
    check = Check(sheet_name=header.sheet.title, header_row=header.row)
    for column, text in sorted(header.columns.items()):
        check.headings.append(
            {"column": get_column_letter(column), "heading": text, "field": mapped.get(heading_key(text), "")}
        )
    return check


# -- what Classnode holds ------------------------------------------------------------


def _roster(group, term):
    ids = ClassPlacement.objects.student_ids(group, term)
    members = {
        m.pk: m for m in Membership.objects.filter(pk__in=ids, role=Role.STUDENT).select_related("user")
    }
    learner_ids = dict(
        StudentDetails.objects.filter(student_membership_id__in=ids)
        .exclude(learner_id="")
        .values_list("student_membership_id", "learner_id")
    )
    return members, learner_ids


def _marks(term, subject, ids):
    if subject is None:
        return {}
    # A paper is the sheet's only when it has the sheet's name **and** its maximum. A
    # school that chose the Ogun template after marking has an "Exam" out of 60 still
    # (presets never overwrite a marked paper), and writing its 26 into a column headed
    # "Exam (70)" would send OGSERA a mark the child did not score.
    out_of = dict(ogun.ASSESSMENTS)
    papers = {
        a.name: a
        for a in Assessment.objects.filter(term=term, subject=subject)
        if out_of.get(a.name) == a.max_score
    }
    scores = {}
    for score in Score.objects.filter(assessment__in=papers.values(), student_membership_id__in=ids):
        scores[(score.student_membership_id, score.assessment.name)] = score.value
    values = {}
    for sid in ids:
        row = {}
        for key, name in PAPERS.items():
            row[key] = scores.get((sid, name)) if name in papers else None
        cas = [row["test1"], row["test2"], row["assignment"]]
        row["ca_total"] = sum(cas) if all(v is not None for v in cas) else None
        row["total"] = row["ca_total"] + row["exam"] if row["ca_total"] is not None and row["exam"] is not None else None
        values[sid] = row
    return values


def _attendance(term, ids):
    from attendance import summary

    found = summary.for_term(term, list(ids)) or {}
    return {
        sid: {
            "times_opened": term.school_days,
            "times_present": marks.present,
            "times_absent": marks.absent,
        }
        for sid, marks in found.items()
    }


def _ratings(term, ids):
    return {
        (r.student_membership_id, r.trait_id): r.score
        for r in TraitRating.objects.filter(term=term, student_membership_id__in=ids)
    }


# -- the check, and the fill -----------------------------------------------------------


@dataclass
class Check:
    sheet_name: str = ""
    header_row: int = 0
    #: Every heading in the header row: `{"column": "C", "heading": ..., "field": key or ""}`.
    headings: list = field(default_factory=list)
    #: `{"row": 7, "learner_id": "OG/99"}`: an ID that is no child of this class.
    unmatched: list = field(default_factory=list)
    #: `{"row": 9, "name": "..."}`: a row with a name and no learner's ID.
    missing_id: list = field(default_factory=list)
    #: Children of the class the file does not list.
    not_in_file: list = field(default_factory=list)
    #: Children of the class with no learner's ID in Classnode.
    no_learner_id: list = field(default_factory=list)
    #: "Ada Obi: no Exam mark" and the like.
    missing_values: list = field(default_factory=list)
    matched: int = 0
    filled: int = 0
    kept: int = 0

    @property
    def may_download(self) -> bool:
        return not self.unmatched and not self.missing_id


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def run(actor, school, raw: bytes, *, class_group, subject=None, replace=False, fill=False):
    """Check the file, and with `fill` write it. Returns `(Check, bytes or None)`."""
    from openpyxl.utils import get_column_letter

    require_office_at_an_ogun_school(actor, school)
    term = Term.objects.filter(is_current=True).first()
    if term is None:
        raise OgseraRefused("No term is open, so there is nothing to fill in.")
    mapped = mapping().columns
    book = open_workbook(raw)
    header = find_header(book, mapped)

    check = Check(sheet_name=header.sheet.title, header_row=header.row)
    by_column = {}
    for column, text in sorted(header.columns.items()):
        key = mapped.get(heading_key(text), "")
        check.headings.append({"column": get_column_letter(column), "heading": text, "field": key})
        if key:
            by_column[column] = key
    if not mapped:
        return check, None
    id_column = next((c for c, k in by_column.items() if k == "learner_id"), None)
    if id_column is None:
        raise OgseraRefused("No column of this file is mapped to the learner's ID. Map it before checking.")
    if subject is None and any(k in MARK_FIELDS for k in by_column.values()):
        raise OgseraRefused("This file has columns for marks. Choose the subject it is for.")
    name_column = next((c for c, k in by_column.items() if k == "name"), None)

    members, learner_ids = _roster(class_group, term)
    by_learner_id = {lid.lower(): sid for sid, lid in learner_ids.items()}
    names = {sid: m.display_name or m.user.full_name for sid, m in members.items()}
    ids = list(members)
    marks = _marks(term, subject, ids)
    present = _attendance(term, ids)
    rated = _ratings(term, ids)

    seen = set()
    sheet = header.sheet
    for row in range(header.row + 1, sheet.max_row + 1):
        # The table ends at its first empty row: a signature line or a note
        # under it is nobody.
        if all(_is_blank(sheet.cell(row=row, column=c).value) for c in header.columns):
            break
        raw_id = sheet.cell(row=row, column=id_column).value
        learner_id = "" if _is_blank(raw_id) else str(raw_id).strip()
        name = sheet.cell(row=row, column=name_column).value if name_column else None
        if not learner_id:
            if not _is_blank(name):
                check.missing_id.append({"row": row, "name": str(name).strip()})
            continue
        sid = by_learner_id.get(learner_id.lower())
        if sid is None:
            check.unmatched.append({"row": row, "learner_id": learner_id})
            continue
        seen.add(sid)
        check.matched += 1
        for column, key in by_column.items():
            if key == "learner_id":
                continue
            value = _value_for(key, sid, names, marks, present, rated)
            if value is None:
                label = FIELDS.get(key) or _trait_name(key)
                check.missing_values.append(f"{names[sid]}: no {label}")
                continue
            cell = sheet.cell(row=row, column=column)
            if not _is_blank(cell.value) and not replace:
                check.kept += 1
                continue
            if fill:
                cell.value = value
            check.filled += 1

    check.not_in_file = sorted(names[sid] for sid in members if sid not in seen and sid in learner_ids)
    check.no_learner_id = sorted(names[sid] for sid in members if sid not in learner_ids)
    if not fill:
        return check, None
    if not check.may_download:
        raise OgseraRefused("Every row has to be matched to a child of the class before the file can be filled.")
    out = io.BytesIO()
    book.save(out)
    return check, out.getvalue()



def _trait_name(key) -> str:
    from .models import Trait

    trait = Trait.objects.filter(pk=int(key.split(":", 1)[1])).first()
    return trait.name if trait else key


def _value_for(key, sid, names, marks, present, rated):
    if key == "name":
        return names.get(sid)
    if key in MARK_FIELDS:
        return (marks.get(sid) or {}).get(key)
    if key.startswith("times_"):
        return (present.get(sid) or {}).get(key)
    if key.startswith("trait:"):
        return rated.get((sid, int(key.split(":", 1)[1])))
    return None


__all__ = [
    "Check",
    "FIELDS",
    "NotAllowed",
    "OgseraRefused",
    "field_choices",
    "find_header",
    "heading_key",
    "headings",
    "mapping",
    "run",
    "save_mapping_as",
]
