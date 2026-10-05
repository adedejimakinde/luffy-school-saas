"""Admitting a class from a spreadsheet: validate all of it, then write all of it.

## Two passes, and the second only happens if the first was clean

A file that half-applies is worse than one refused outright. The office cannot
tell which children landed without reading the roll against the spreadsheet by
hand, and the natural second attempt — re-upload the whole file — then collides
with everything that did land.

So `check()` returns a verdict on every row and writes nothing, and `admit()`
runs it first and refuses the whole file unless every row passed. The
all-or-nothing rule is the reason this module exists rather than a loop calling
`admit_student_as()`.

## Every bad row is reported, not the first

An office fixing a two-hundred-row file one error per upload is the failure
this design exists to prevent. Each problem carries the **line number in their
file** — the header is line 1, so the first child is line 2 — because "row 14"
is something they can find and "the third error" is not.

## Columns are matched by name, and so are class groups

The header is matched case-insensitively and in any order: a positional format
breaks silently the first time somebody reorders columns in a spreadsheet.

`class_group` is matched by **name** against the groups this school still
teaches. An office preparing a file has "JSS 1A" in front of them, not `11`; a
wrong name is a rejected row where a wrong id would be a silent
mis-enrolment.

## What is generated, and what is not

`username` is optional. Given, it is the school's own handle and is used as
typed. Blank, one is generated — `SLUG/reference` where a reference exists,
else `SLUG/n` — and **every generated handle is reported back**, because a
child cannot be handed a login nobody wrote down.

Handles are compared the way the platform compares them — case-insensitively,
through `User.objects.matching_identifier()` — and not as typed. A check
narrower than `User.save()`'s lets a row through that the save then refuses,
which arrives as a whole-file refusal with no line number on it.

`reference` is the school's admission number. Optional; unique within the
school and within the file when present, because two children sharing one is a
records problem the office wants told about now rather than found in March.

## Siblings share a guardian

Two rows carrying the same contact are **one guardian linked to two children**,
not a duplicate to reject. Contacts are compared after normalisation, so
`0803...`, `803...` and `+234803...` are the same person — which is the whole
reason the normalising happens before the matching rather than after.

Every link is reported by line as **"pending verification"** unless the
guardian is already live *at this school*. Since #135 a link goes live only
when the guardian answers the school that made it, so a guardian verified at
another school is pending here like anybody new — and the report cannot be
used to learn which numbers belong to verified parents elsewhere.

Guardians go through `guardian_contacts.link_by_contact_as()`, the one code
path D10 asks for: the same find-or-create, the same link, and the same channel
recorded as the roll's guardians panel, so an imported guardian has a channel
to verify.

## A CSV or an Excel workbook, read into the same rows

Most offices keep the roll in Excel, and "save as CSV" is a step that loses
leading zeros and mangles names on the way. So `read_upload()` takes either and
hands `check()` the same thing: `(line number, cells)` pairs, where the line is
the row number the office sees in their spreadsheet. Everything after that,
every rule above, is the same code for both.

What decides the format is the file's first bytes, never its name: an
`.xlsx` is a zip, an old `.xls` is refused with a sentence saying how to save
it, and anything else is read as CSV text.

An upload is a file somebody chose, so it is bounded before it is opened: at
most `MAX_FILE_BYTES` sent, at most `MAX_UNPACKED_BYTES` once the workbook's zip
is unpacked (read from the zip's own directory, before anything is inflated),
and at most `MAX_ROWS` children. Formulas are read as the value Excel last
saved, never evaluated.

A row with nothing in any cell is skipped rather than refused: a spreadsheet
often ends in rows that were formatted and never filled, and "line 212: a name
is required" about a row the office cannot see would be a problem invented by
this module.
"""

import csv
import datetime
import io
import zipfile
from dataclasses import dataclass, field

from django.db import transaction

from academics import details
from academics import services as academics
from academics.models import ClassGroup
from accounts import guardian_contacts
from accounts.identifiers import canonical_username
from accounts.models import ContactChannel, GuardianAccount, Membership, Role, User
from accounts.services import admit_student_as

#: The header a file must carry. Two are required of every row; the rest may be
#: absent from the file entirely.
REQUIRED_COLUMNS = ("full_name", "class_group")
OPTIONAL_COLUMNS = (
    "username",
    "reference",
    "guardian_name",
    "guardian_contact",
    "learner_id",
    "sex",
    "date_of_birth",
)

#: The columns in the order the template lays them out, and the heading each
#: carries there. A heading is matched with its spaces read as underscores, so
#: "Full name" and "full_name" are the same column.
TEMPLATE_COLUMNS = (
    ("full_name", "Full name"),
    ("class_group", "Class group"),
    ("reference", "Reference"),
    ("username", "Username"),
    ("guardian_name", "Guardian name"),
    ("guardian_contact", "Guardian contact"),
    ("learner_id", "Learner ID"),
    ("sex", "Sex"),
    ("date_of_birth", "Date of birth"),
)

#: The largest file looked at, in bytes. A school's whole roll as a workbook
#: is a few hundred kilobytes.
MAX_FILE_BYTES = 2 * 1024 * 1024

#: The most a workbook may unpack to, read from its zip directory before any of
#: it is inflated. A zip that claims more is refused unopened.
MAX_UNPACKED_BYTES = 20 * 1024 * 1024

#: The most children one file may admit.
MAX_ROWS = 2000

_ZIP = b"PK\x03\x04"
_OLD_EXCEL = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass
class RowProblem:
    """One thing wrong with one row, and where to find it."""

    line: int
    column: str
    detail: str


@dataclass
class PlannedChild:
    """A row that passed, with everything resolved that the write will need."""

    line: int
    full_name: str
    username: str
    username_was_generated: bool
    reference: str
    class_group: object
    guardian_name: str = ""
    guardian_contact: str = ""
    #: "phone" or "email" (what `read_contact()` made of the contact), or "" with no guardian.
    guardian_channel: str = ""
    learner_id: str = ""
    sex: str = ""
    date_of_birth: object = None

    @property
    def has_details(self) -> bool:
        return bool(self.learner_id or self.sex or self.date_of_birth)


@dataclass
class GuardianLink:
    """One child linked to one guardian, and whether that parent can see them yet."""

    line: int
    guardian_contact: str
    status: str


@dataclass
class NoEmail:
    """A child whose guardian this school has no email for: one who will get no alert or receipt.

    Absence alerts and payment receipts go by email only (`docs/messaging.md` D13), so this is
    how an office learns, at the import, who they will not reach. `why` says which kind of gap.
    """

    line: int
    full_name: str
    class_group: str
    reference: str
    guardian_name: str
    guardian_contact: str
    why: str


@dataclass
class ReadRow:
    """One row as it was read, before any verdict. For the preview."""

    line: int
    values: dict


@dataclass
class Report:
    """What a file would do, or did.

    `problems` empty means the file is admissible. `planned` is in file order,
    so a line number means the line in their spreadsheet.
    """

    problems: list = field(default_factory=list)
    planned: list = field(default_factory=list)
    #: Filled by `check()`: every row read, passed or not, in file order.
    rows: list = field(default_factory=list)
    #: Filled by `admit()`: the handles this school now has to hand out.
    generated: dict = field(default_factory=dict)
    #: Filled by `admit()`: every guardian link made, in file order.
    guardian_links: list = field(default_factory=list)
    #: Filled by `admit()`: the children who will get no email, in file order (`NoEmail`).
    no_email: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


class BulkError(Exception):
    """The file cannot be read at all, or the school is not ready for one."""


def _column_key(heading):
    """"Full name", "full_name" and " FULL_NAME " are one column."""
    return "_".join(str(heading or "").strip().lower().replace("-", " ").split())


def _blank(cells):
    return not any(str(c or "").strip() for c in cells)


def _csv_table(text):
    """CSV text as `(line, cells)` pairs, the line being where the row starts.

    `csv.reader` rather than counting rows, because a quoted cell can hold a
    line break and a blank line is still a line: the number given back has to
    be the one the office's editor shows.
    """
    reader = csv.reader(io.StringIO(text))
    table, last = [], 0
    for cells in reader:
        table.append((last + 1, cells))
        last = reader.line_num
    return table


def _cell_text(value):
    """What a workbook cell says, as the office would have typed it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        # A number typed into a General cell comes back as 100.0.
        return str(int(value))
    if isinstance(value, datetime.datetime):
        return value.date().isoformat() if value.time() == datetime.time() else value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value).strip()


def _xlsx_table(raw):
    """The first sheet that has a roll's header, as `(row number, cells)` pairs."""
    from openpyxl import load_workbook

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        unpacked = sum(entry.file_size for entry in archive.infolist())
    except zipfile.BadZipFile:
        raise BulkError(_UNREADABLE)
    if unpacked > MAX_UNPACKED_BYTES:
        raise BulkError("That workbook is far larger than a roll needs. Save only the students' sheet and try again.")

    try:
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        # openpyxl raises whatever its parser met: a broken zip member, bad
        # XML, a workbook written by something that was not quite Excel. The
        # office can act on "save it again" and on nothing more specific.
        raise BulkError(_UNREADABLE)

    try:
        tables = []
        for sheet in book.worksheets:
            table = []
            start = sheet.min_row or 1
            for number, cells in enumerate(sheet.iter_rows(values_only=True), start=start):
                if len(table) > MAX_ROWS + 1:
                    break
                cells = [_cell_text(c) for c in cells]
                if not _blank(cells):
                    table.append((number, cells))
            header = {_column_key(c) for c in table[0][1]} if table else set()
            if set(REQUIRED_COLUMNS) <= header:
                return table
            tables.append(table)
        # No sheet has the header: read the first, and let `_read()` say which
        # columns it is missing.
        return tables[0] if tables else []
    finally:
        book.close()


_UNREADABLE = (
    "That file is not a spreadsheet this can read. Save it as an Excel "
    "workbook (.xlsx) or as CSV, and try again."
)


def read_upload(raw: bytes):
    """An uploaded file's bytes as the rows `check()` and `admit()` read.

    The format is read from the file's first bytes, not from its name.
    """
    if len(raw) > MAX_FILE_BYTES:
        raise BulkError("That file is over 2 MB. A roll is far smaller: save only the students and try again.")
    if raw.startswith(_ZIP):
        return _xlsx_table(raw)
    if raw.startswith(_OLD_EXCEL):
        raise BulkError(
            "That is an older Excel file (.xls). In Excel choose File, Save As, "
            "Excel Workbook (.xlsx), and choose the new file here."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel on Windows saves "CSV" in the machine's own code page.
        text = raw.decode("cp1252", errors="replace")
    if "\x00" in text:
        raise BulkError(_UNREADABLE)
    return _csv_table(text)


#: What the template's second sheet says, one line to a row.
_HOW_TO = (
    "How to fill in the Students sheet",
    "",
    "One child to a row. Leave the heading row as it is.",
    "Full name: required.",
    "Class group: required. Pick it from the list; it must be a class this school teaches this term.",
    "Reference: the child's admission number. Optional, and never shared by two children.",
    "Username: optional. Leave it blank and one is made from the admission number.",
    "Guardian name and Guardian contact: optional, but give both or neither. "
    "The contact is a phone number or an email address.",
    "Two children with the same guardian contact are siblings: one guardian is linked to both.",
    "Learner ID: optional. The state's ID for the child; never shared by two children here.",
    "Sex: optional. Female or Male (F or M is fine).",
    "Date of birth: optional. Day/month/year, like 31/01/2014.",
    "",
    "Nothing is saved until every row is right. The upload page shows every row "
    "that needs fixing, by its row number here.",
)

#: Rows the template formats as text, so an admission number keeps its
#: leading zeros and a phone number is not turned into 8.03E+09.
_TEMPLATE_ROWS = 1000


def template_workbook(class_names) -> bytes:
    """The workbook an office fills in: this school's classes, and no children.

    The class column is a drop-down of `class_names`, from a hidden sheet, so a
    class is picked rather than typed. The columns that hold numbers a school
    writes with leading zeros are formatted as text before anybody types.
    There is no example row: an example left in would be admitted.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    book = Workbook()
    sheet = book.active
    sheet.title = "Students"
    sheet.append([heading for _, heading in TEMPLATE_COLUMNS])
    sheet.freeze_panes = "A2"
    for index, (key, heading) in enumerate(TEMPLATE_COLUMNS, start=1):
        letter = get_column_letter(index)
        sheet[f"{letter}1"].font = Font(bold=True)
        sheet.column_dimensions[letter].width = max(16, len(heading) + 6)
        if key in ("reference", "username", "guardian_contact", "learner_id"):
            for row in range(2, _TEMPLATE_ROWS + 2):
                sheet[f"{letter}{row}"].number_format = "@"
        if key == "date_of_birth":
            for row in range(2, _TEMPLATE_ROWS + 2):
                sheet[f"{letter}{row}"].number_format = "DD/MM/YYYY"

    names = [name for name in class_names if name]
    if names:
        classes = book.create_sheet("Classes")
        for name in names:
            classes.append([name])
        classes.sheet_state = "hidden"
        column = get_column_letter(1 + [k for k, _ in TEMPLATE_COLUMNS].index("class_group"))
        choice = DataValidation(
            type="list",
            formula1=f"=Classes!$A$1:$A${len(names)}",
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Not a class here",
            error="Choose a class from the list.",
        )
        choice.add(f"{column}2:{column}{_TEMPLATE_ROWS + 1}")
        sheet.add_data_validation(choice)

    sexes = DataValidation(
        type="list",
        formula1='"Female,Male"',
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="Female or Male",
        error="Choose Female or Male, or leave it blank.",
    )
    column = get_column_letter(1 + [k for k, _ in TEMPLATE_COLUMNS].index("sex"))
    sexes.add(f"{column}2:{column}{_TEMPLATE_ROWS + 1}")
    sheet.add_data_validation(sexes)

    notes = book.create_sheet("How to fill it in")
    for line in _HOW_TO:
        notes.append([line])
    notes["A1"].font = Font(bold=True)
    notes.column_dimensions["A"].width = 100

    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _read(source):
    """The file as a list of `(line number, row dict)`, header matched by name.

    `source` is CSV text, or rows already read by `read_upload()`.

    Case-insensitive and order-independent: a spreadsheet somebody reordered is
    still the same file, and a positional format would read the new order as
    the old one and enrol everybody into the wrong class without a word.

    The header is the first row with anything in it, normally line 1, so the
    first child is line 2 — which is what the office sees in their editor.
    """
    table = _csv_table(source) if isinstance(source, str) else list(source)
    table = [(line, cells) for line, cells in table if not _blank(cells)]
    if not table:
        raise BulkError("That file has no header row, so its columns cannot be read.")

    _, header = table[0]
    seen = {}
    for index, heading in enumerate(header):
        key = _column_key(heading)
        if key and key not in seen:
            seen[key] = index
    missing = [c for c in REQUIRED_COLUMNS if c not in seen]
    if missing:
        raise BulkError(
            "That file is missing the column"
            + ("s " if len(missing) > 1 else " ")
            + ", ".join(sorted(missing))
            + "."
        )
    if len(table) == 1:
        # The template, downloaded and sent straight back. Admitting nobody
        # and calling it done would tell the office the roll was in.
        raise BulkError("That file has the headings and no children under them yet.")
    if len(table) - 1 > MAX_ROWS:
        raise BulkError(
            f"That file has more than {MAX_ROWS:,} children in it. Split it into "
            "smaller files and import them one at a time."
        )

    rows = []
    for line, cells in table[1:]:
        row = {
            key: str(cells[index] if index < len(cells) else "").strip()
            for key, index in seen.items()
            if key in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
        }
        rows.append((line, row))
    return rows


def _handle_key(username):
    """A handle as the platform compares it: canonical, and without case."""
    return canonical_username(username).lower()


def _prefix(school):
    return school.slug.upper()


def _handles_in_use(school, planned):
    """Every handle a generated one could collide with, as `_handle_key()`s.

    **The whole file's given handles**, not just the rows before this one:
    generating in file order without them hands line 2 a handle that line 9
    asks for by name, and the database refuses line 9 — a whole-file refusal
    for a file with nothing wrong in it.

    **And every handle already under this school's prefix, in any case**,
    read once. A generated handle is one the office cannot correct, so a
    collision on it has to be stepped around here rather than refused at save.
    """
    taken = {_handle_key(p.username) for p in planned if p.username}
    taken.update(
        username.lower()
        for username in User.objects.filter(
            username__istartswith=_prefix(school) + "/"
        ).values_list("username", flat=True)
    )
    return taken


def _generated_username(school, reference, taken):
    """A handle for a child whose school did not give one.

    `SLUG/reference` where a reference exists — it is the number the school
    already knows this child by — and `SLUG/n` otherwise, counting up past
    anything taken. The slug is the school's own short name, so the handle says
    which school it belongs to without a second table to look it up in.

    `taken` is `_handles_in_use()`, grown by every handle this file claims as
    it goes, so two generated handles in one upload cannot collide either.
    """
    prefix = _prefix(school)
    if reference:
        candidate = f"{prefix}/{reference}"
        if _handle_key(candidate) not in taken:
            return candidate
    n = 1
    while True:
        candidate = f"{prefix}/{n}"
        if _handle_key(candidate) not in taken:
            return candidate
        n += 1


def check(school, source) -> Report:
    """Read a file and say what is wrong with it. **Writes nothing.**

    Every row is checked and every problem reported. Checks run in a fixed
    order per row — required fields, then the handle, then the reference, then
    the class, then the guardian pair — so a row with two faults reports the
    one the office fixes first.
    """
    report = Report()
    groups = {
        g.name.strip().lower(): g
        for g in ClassGroup.objects.filter(is_active=True)
    }
    taken_usernames = set()
    taken_references = set()
    taken_learner_ids = set()

    for line, row in _read(source):
        problems_before = len(report.problems)
        report.rows.append(
            ReadRow(line, {c: row.get(c, "") for c in REQUIRED_COLUMNS + OPTIONAL_COLUMNS})
        )

        full_name = row.get("full_name", "")
        if not full_name:
            report.problems.append(RowProblem(line, "full_name", "A name is required."))

        username = row.get("username", "")
        if username:
            if _handle_key(username) in taken_usernames:
                report.problems.append(
                    RowProblem(line, "username", f"{username!r} appears twice in this file.")
                )
            elif User.objects.matching_identifier(username).exists():
                # Deliberately not naming the holder: the handle is unique
                # across the platform, so saying where it is in use would tell
                # this office which children exist at another school.
                report.problems.append(
                    RowProblem(line, "username", f"{username!r} is already in use.")
                )
            else:
                taken_usernames.add(_handle_key(username))

        reference = row.get("reference", "")
        if reference:
            if reference in taken_references:
                report.problems.append(
                    RowProblem(line, "reference", f"{reference!r} appears twice in this file.")
                )
            elif Membership.objects.filter(
                school=school, role=Role.STUDENT, reference=reference
            ).exists():
                report.problems.append(
                    RowProblem(
                        line,
                        "reference",
                        f"{reference!r} is already an admission number at this school.",
                    )
                )
            else:
                taken_references.add(reference)

        class_name = row.get("class_group", "")
        group = groups.get(class_name.lower()) if class_name else None
        if not class_name:
            report.problems.append(RowProblem(line, "class_group", "A class is required."))
        elif group is None:
            # Named, not id'd — and this is why. A wrong name is a rejected
            # row; a wrong id would have been a silent mis-enrolment.
            report.problems.append(
                RowProblem(
                    line,
                    "class_group",
                    f"{class_name!r} is not a class this school teaches.",
                )
            )

        guardian_name = row.get("guardian_name", "")
        guardian_raw = row.get("guardian_contact", "")
        guardian_contact = guardian_channel = ""
        if guardian_name or guardian_raw:
            if not guardian_name:
                report.problems.append(
                    RowProblem(line, "guardian_name", "A guardian's contact needs a name.")
                )
            if not guardian_raw:
                report.problems.append(
                    RowProblem(line, "guardian_contact", "A guardian's name needs a contact.")
                )
            elif (read := guardian_contacts.read_contact(guardian_raw)) is None:
                report.problems.append(
                    RowProblem(
                        line,
                        "guardian_contact",
                        f"{guardian_raw!r} is neither a phone number nor an email address.",
                    )
                )
            else:
                guardian_channel, guardian_contact = read

        learner_id = sex = ""
        date_of_birth = None
        try:
            learner_id = details.read_learner_id(row.get("learner_id", ""))
        except details.DetailsRefused as exc:
            report.problems.append(RowProblem(line, "learner_id", str(exc)))
        if learner_id:
            if learner_id.lower() in taken_learner_ids:
                report.problems.append(
                    RowProblem(line, "learner_id", f"{learner_id!r} appears twice in this file.")
                )
            elif details.learner_id_holder(learner_id) is not None:
                report.problems.append(
                    RowProblem(
                        line,
                        "learner_id",
                        f"{learner_id!r} is already a learner's ID at this school.",
                    )
                )
            else:
                taken_learner_ids.add(learner_id.lower())
        try:
            sex = details.read_sex(row.get("sex", ""))
        except details.DetailsRefused as exc:
            report.problems.append(RowProblem(line, "sex", str(exc)))
        try:
            date_of_birth = details.read_date_of_birth(row.get("date_of_birth", ""))
        except details.DetailsRefused as exc:
            report.problems.append(RowProblem(line, "date_of_birth", str(exc)))

        if len(report.problems) == problems_before:
            report.planned.append(
                PlannedChild(
                    line=line,
                    full_name=full_name,
                    username=username,
                    username_was_generated=not username,
                    reference=reference,
                    class_group=group,
                    guardian_name=guardian_name,
                    guardian_contact=guardian_contact,
                    guardian_channel=guardian_channel,
                    learner_id=learner_id,
                    sex=sex,
                    date_of_birth=date_of_birth,
                )
            )

    return report


def admit(actor, school, term, source) -> Report:
    """Admit a whole file, or none of it.

    `check()` runs first and the write only starts if it found nothing. That
    ordering *is* the all-or-nothing rule — interleaving the two, writing each
    row as it passes, is exactly the half-applied file this module exists to
    prevent, and it would pass every test that only counts errors.

    One transaction over all of it, so a refusal the check could not foresee —
    a handle claimed by another school between the two passes — takes the whole
    file back out rather than leaving a prefix of it behind.

    **Siblings share a guardian.** Each row goes through
    `link_by_contact_as()`, which finds the `User` the first sibling's row made
    by its normalised contact, so two rows with one number are two children of
    one parent — the ordinary case in a school, and not a duplicate to refuse.
    """
    if term is None:
        raise BulkError(
            "No term is open, so there is no class to place anybody in. Set the "
            "current term before importing a roll."
        )

    report = check(school, source)
    if not report.ok:
        return report

    with transaction.atomic():
        taken = _handles_in_use(school, report.planned)
        for planned in report.planned:
            username = planned.username or _generated_username(
                school, planned.reference, taken
            )
            taken.add(_handle_key(username))
            if planned.username_was_generated:
                # Reported back because a child cannot be handed a login
                # nobody wrote down.
                report.generated[planned.line] = username

            user, membership = admit_student_as(
                actor,
                school,
                planned.full_name,
                username,
                reference=planned.reference,
            )
            academics.place_student_as(
                actor, planned.class_group, term, membership, by=actor
            )
            if planned.has_details:
                # Checked in `check()`; a learner's ID claimed between the two
                # passes is refused here and takes the whole file back out.
                details.record(
                    membership.pk,
                    learner_id=planned.learner_id,
                    sex=planned.sex,
                    date_of_birth=planned.date_of_birth,
                    by=actor,
                )

            link = None
            if planned.guardian_contact:
                link = guardian_contacts.link_by_contact_as(
                    actor,
                    membership,
                    planned.guardian_name,
                    planned.guardian_contact,
                )
                # Read back rather than assumed. New links are INVITED; one to
                # a guardian this school has already confirmed is live, because
                # `grant_membership()` never downgrades a live membership.
                report.guardian_links.append(
                    GuardianLink(
                        line=planned.line,
                        guardian_contact=planned.guardian_contact,
                        status=guardian_contacts.link_status_at(link.guardian, school),
                    )
                )
            why = _why_no_email(planned, link, school)
            if why:
                report.no_email.append(
                    NoEmail(
                        line=planned.line,
                        full_name=planned.full_name,
                        class_group=planned.class_group.name,
                        reference=planned.reference,
                        guardian_name=planned.guardian_name,
                        guardian_contact=planned.guardian_contact,
                        why=why,
                    )
                )

    return report


def _why_no_email(planned, link, school):
    """Why this child's guardian cannot be emailed by this school, or "" if they can.

    **Only what this school may know.** An email typed on the row counts. A phone alone counts
    as no email unless the guardian is already live *here* and holds an email: what a guardian
    holds before they have answered this school is not this school's to read, and a report that
    used it would say which numbers belong to a parent with an email elsewhere (the rule
    `GuardianLink` keeps for "live").
    """
    if not planned.guardian_contact:
        return "No guardian was given."
    if planned.guardian_channel == ContactChannel.EMAIL:
        return ""
    if guardian_contacts.link_status_at(link.guardian, school) == guardian_contacts.LIVE:
        account = GuardianAccount.objects.filter(user=link.guardian).first()
        if account is not None and account.live_contact(ContactChannel.EMAIL) is not None:
            return ""
    return "A phone number only."


__all__ = [
    "BulkError",
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "ReadRow",
    "TEMPLATE_COLUMNS",
    "read_upload",
    "template_workbook",
    "GuardianLink",
    "NoEmail",
    "Report",
    "RowProblem",
    "PlannedChild",
    "REQUIRED_COLUMNS",
    "OPTIONAL_COLUMNS",
    "check",
    "admit",
]
