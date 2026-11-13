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
school and within the file when present, compared **without case** as the
doors compare it (G-14, `accounts.admission_numbers`), because two children
sharing one is a records problem the office wants told about now rather than
found in March.

## Sending a file twice admits nobody twice (G-15)

Every row is first matched against the children already on the roll, by the
first thing it carries that names a child (`_match()` has the rules in full):

1. its **admission number**, held by a child here;
2. else its **username**, the login of a child here;
3. else, or when the number and handle are nobody's yet, its **name**: one
   enrolled child of that name, in the row's class this term or in none, who
   does not carry a different admission number.

A matched row is that child. **The import adds; it never changes or removes
what the roll already says**: it fills only what the roll has nothing for (a
number, a class this term, a learner's ID, sex, date of birth, a guardian not
yet linked) and the row is `UPDATED`; with nothing to fill it is `SKIPPED`.
What the row says differently is left as the roll has it and listed in the
row's notes. An unmatched row is `NEW`. A row that could be two children (the
same name in another class, a name two children share, a number that is a
different child's) is refused with a sentence saying what to add, so a file is
never guessed at.

So the same file sent twice, with admission numbers or without, admits the
second time nobody: every row is `SKIPPED`. A double press or a retry is the
same file twice at once, and `admit()` holds one import per school at a time
(`_lock_the_roll()`) and checks the file inside that hold, so the second is
checked against what the first wrote. The preview (`/roll/import/check/`)
shows each row's outcome before anything is written. `docs/roll-import.md`
says the same for an office.

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
from accounts import admission_numbers, guardian_contacts
from accounts.identifiers import canonical_username
from accounts.models import ContactChannel, GuardianAccount, Guardianship, Membership, Role, User
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
    #: `NEW`, `UPDATED` or `SKIPPED`: what the import does with this row (G-15).
    outcome: str = "new"
    #: The child already on the roll this row is, for `UPDATED` and `SKIPPED`.
    existing: object = None
    #: How the row was matched to `existing`: "admission number", "username" or "name".
    matched_by: str = ""
    #: What an `UPDATED` row fills in, in words, in the order it is written.
    fills: list = field(default_factory=list)
    #: What the file says that the roll says otherwise, and is left as the roll has it.
    notes: list = field(default_factory=list)
    #: For an `UPDATED` row, which of the fills to write.
    set_reference: bool = False
    place: bool = False
    link_guardian: bool = False
    details_to_fill: dict = field(default_factory=dict)

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

    def count(self, outcome) -> int:
        return sum(1 for p in self.planned if p.outcome == outcome)


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


NEW = "new"
UPDATED = "updated"
SKIPPED = "skipped"


def _name_key(name):
    """A name as the import compares it: no case, one space between words."""
    return " ".join(str(name or "").split()).casefold()


def _name_of(membership):
    return membership.display_name or membership.user.full_name or membership.user.username


class _Roll:
    """Who is on this school's roll, read once per check: the matching rules' input.

    Every STUDENT membership at the school, ended ones included, because an
    admission number or a handle held by a child who has left still names that
    child. A name only ever matches a child still enrolled.
    """

    def __init__(self, school, term):
        from academics.models import ClassPlacement
        from accounts.models import LIVE_STATUSES

        students = list(
            Membership.objects.filter(school=school, role=Role.STUDENT)
            .select_related("user")
            .order_by("pk")
        )
        self.by_number = {}
        self.by_user = {}
        self.by_name = {}
        for m in students:
            self.by_user[m.user_id] = m
            number = admission_numbers.clean(m.reference).lower()
            if number:
                self.by_number.setdefault(number, m)
            if m.status in LIVE_STATUSES:
                self.by_name.setdefault(_name_key(_name_of(m)), []).append(m)
        self.placed = {}
        if term is not None:
            self.placed = dict(
                ClassPlacement.objects.filter(term=term).values_list(
                    "student_membership_id", "class_group_id"
                )
            )


def check(school, source, term=None) -> Report:
    """Read a file and say what it would do, row by row. **Writes nothing.**

    Every row is checked and every problem reported. Checks run in a fixed
    order per row — required fields, then who the row is (`_match()`), then the
    handle and the admission number of a new child, then the class, then the
    guardian pair, then the details — so a row with two faults reports the one
    the office fixes first.

    `term` is the term children are placed in; with it, a row matched to a child
    already on the roll is compared with their class this term. Every row that
    passes is in `planned`, with its `outcome`: `NEW`, `UPDATED` or `SKIPPED`
    (G-15, and `docs/roll-import.md` for the rules).
    """
    report = Report()
    groups = {
        g.name.strip().lower(): g
        for g in ClassGroup.objects.filter(is_active=True)
    }
    roll = _Roll(school, term)
    taken_usernames = set()
    taken_references = set()
    taken_learner_ids = set()
    #: Children already claimed by a row of this file, so two rows are never one child.
    claimed = {}
    #: New children named with neither a number nor a handle, by (name, class).
    unnamed_new = {}

    for line, row in _read(source):
        problems_before = len(report.problems)
        report.rows.append(
            ReadRow(line, {c: row.get(c, "") for c in REQUIRED_COLUMNS + OPTIONAL_COLUMNS})
        )

        full_name = row.get("full_name", "")
        if not full_name:
            report.problems.append(RowProblem(line, "full_name", "A name is required."))

        class_name = row.get("class_group", "")
        group = groups.get(class_name.lower()) if class_name else None
        username = row.get("username", "")
        reference = admission_numbers.clean(row.get("reference", ""))

        existing, matched_by = (None, "")
        before_match = len(report.problems)
        if full_name:
            existing, matched_by = _match(
                report, line, roll, full_name, username, reference, group
            )
        # Refused as somebody else's: the handle and number are not asked again.
        identity_refused = len(report.problems) > before_match
        if existing is not None:
            earlier = claimed.get(existing.pk)
            if earlier is not None:
                report.problems.append(
                    RowProblem(
                        line,
                        "full_name",
                        f"Line {earlier} is already {_name_of(existing)}, who is on the roll. "
                        "One child, one row.",
                    )
                )
            else:
                claimed[existing.pk] = line

        if username and existing is None and not identity_refused:
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

        # Compared as the doors and the index compare it: without case (G-14).
        if reference and not identity_refused and (existing is None or not existing.reference):
            if reference.lower() in taken_references:
                report.problems.append(
                    RowProblem(line, "reference", f"{reference!r} appears twice in this file.")
                )
            elif (held := roll.by_number.get(reference.lower())) is not None and held is not existing:
                report.problems.append(
                    RowProblem(line, "reference", admission_numbers.refusal(reference, held))
                )
            else:
                taken_references.add(reference.lower())

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

        if existing is None and full_name and group is not None and not username and not reference:
            key = (_name_key(full_name), group.pk)
            if key in unnamed_new:
                report.problems.append(
                    RowProblem(
                        line,
                        "full_name",
                        f"{full_name} in {group.name} appears twice in this file (line "
                        f"{unnamed_new[key]}). Give each child an admission number if these "
                        "are two children.",
                    )
                )
            else:
                unnamed_new[key] = line

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
            holder_id = details.learner_id_holder(learner_id)
            if learner_id.lower() in taken_learner_ids:
                report.problems.append(
                    RowProblem(line, "learner_id", f"{learner_id!r} appears twice in this file.")
                )
            elif holder_id is not None and (existing is None or holder_id != existing.pk):
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
                    username=username if existing is None else existing.user.username,
                    username_was_generated=existing is None and not username,
                    reference=reference,
                    class_group=group,
                    guardian_name=guardian_name,
                    guardian_contact=guardian_contact,
                    guardian_channel=guardian_channel,
                    learner_id=learner_id,
                    sex=sex,
                    date_of_birth=date_of_birth,
                    existing=existing,
                    matched_by=matched_by,
                )
            )

    _decide_what_matched_rows_do(report, roll, school, username_by_line={
        r.line: r.values.get("username", "") for r in report.rows
    })
    return report


def _match(report, line, roll, full_name, username, reference, group):
    """Which child already on the roll this row is, if any: `(membership, how)`.

    **The matching rules** (G-15), first key the row carries wins:

    1. **An admission number** names the child at this school holding it, without
       case. Held by a child who has left, or by a child of another name, the row
       is refused: the number is theirs.
    2. **A username** (no number) names the child here whose login it is. Held by a
       child of another name, or who has left, the row is refused. A handle
       somebody else on the platform holds is refused by the caller, as before.
    3. **The name**, for a row whose number and handle nobody holds (or that has
       neither): an enrolled child here of the same name, compared without case or
       extra spaces, who is in the row's class this term or in no class, and does
       not carry a different admission number from the row's. In another class it
       is refused ("give an admission number if this is a different child"), and
       so is a name two enrolled children share.

    Refusals are added to `report.problems`; the answer is then `(None, "")`.
    """
    from accounts.models import LIVE_STATUSES

    wanted = _name_key(full_name)

    if reference:
        held = roll.by_number.get(reference.lower())
        if held is not None:
            if held.status not in LIVE_STATUSES:
                report.problems.append(
                    RowProblem(line, "reference", admission_numbers.refusal(reference, held))
                )
                return None, ""
            if _name_key(_name_of(held)) != wanted:
                report.problems.append(
                    RowProblem(
                        line,
                        "reference",
                        f"{reference!r} is already an admission number at this school, "
                        f"{_name_of(held)}'s, and this row names {full_name}.",
                    )
                )
                return None, ""
            if username:
                handles = list(User.objects.matching_identifier(username)[:2])
                if handles and all(u.pk != held.user_id for u in handles):
                    report.problems.append(
                        RowProblem(line, "username", f"{username!r} is already in use.")
                    )
                    return None, ""
            return held, "admission number"

    if username:
        handles = list(User.objects.matching_identifier(username)[:2])
        mine = [roll.by_user[u.pk] for u in handles if u.pk in roll.by_user]
        if len(handles) == 1 and mine:
            held = mine[0]
            if held.status not in LIVE_STATUSES:
                report.problems.append(
                    RowProblem(
                        line,
                        "username",
                        f"{username!r} is the username of {_name_of(held)}, who has left "
                        "this school.",
                    )
                )
                return None, ""
            if _name_key(_name_of(held)) != wanted:
                report.problems.append(
                    RowProblem(
                        line,
                        "username",
                        f"{username!r} is the username of {_name_of(held)}, and this row "
                        f"names {full_name}.",
                    )
                )
                return None, ""
            return held, "username"
        if handles:
            # Somebody else's handle: refused by the caller, without naming them.
            return None, ""

    same_name = [
        m
        for m in roll.by_name.get(wanted, [])
        if not (reference and m.reference and admission_numbers.clean(m.reference).lower() != reference.lower())
    ]
    if not same_name:
        return None, ""
    if len(same_name) > 1:
        report.problems.append(
            RowProblem(
                line,
                "full_name",
                f"{len(same_name)} children called {full_name} are on the roll. Give this "
                "row the admission number of the one it is, or a new one if it is a "
                "different child.",
            )
        )
        return None, ""
    held = same_name[0]
    placed_in = roll.placed.get(held.pk)
    if placed_in is not None and group is not None and placed_in != group.pk:
        from academics.models import ClassGroup as Group

        where = Group.objects.filter(pk=placed_in).values_list("name", flat=True).first()
        report.problems.append(
            RowProblem(
                line,
                "full_name",
                f"A child called {full_name} is already on the roll, in {where}. Give this "
                "row an admission number if it is a different child; to move them, use "
                "the roll.",
            )
        )
        return None, ""
    return held, "name"


def _decide_what_matched_rows_do(report, roll, school, *, username_by_line):
    """Mark each matched row `UPDATED` or `SKIPPED`, and say what and why.

    **The import adds; it never changes or removes what the roll already says.**
    A matched row fills only what the roll has nothing for: an admission number,
    a class this term, a learner's ID, sex or date of birth, a guardian not yet
    linked. Anything the row says differently from the roll is left as the roll
    has it and listed in `notes`, so the preview shows it. A row with nothing to
    fill is `SKIPPED`: sending the same file twice changes nothing.
    """
    matched = [p for p in report.planned if p.existing is not None]
    if not matched:
        return
    recorded = details.details_for(p.existing.pk for p in matched)
    from academics.models import ClassGroup as Group

    names = dict(Group.objects.values_list("pk", "name"))
    for planned in matched:
        child = planned.existing
        planned.notes.append(f"Already on the roll as {_name_of(child)} (matched by {planned.matched_by}).")
        if planned.reference and not child.reference:
            planned.set_reference = True
            planned.fills.append(f"admission number {planned.reference}")
        elif planned.reference and admission_numbers.clean(child.reference).lower() != planned.reference.lower():
            planned.notes.append(f"Admission number kept as {child.reference}.")
        given = username_by_line.get(planned.line, "")
        if given and _handle_key(given) != _handle_key(child.user.username):
            planned.notes.append(f"Username kept as {child.user.username}.")

        placed_in = roll.placed.get(child.pk)
        if placed_in is None:
            planned.place = True
            planned.fills.append(f"class {planned.class_group.name} this term")
        elif placed_in != planned.class_group.pk:
            planned.notes.append(f"Kept in {names.get(placed_in, 'their class')}; move them on the roll.")

        row = recorded.get(child.pk)
        for field_name, label, value in (
            ("learner_id", "learner's ID", planned.learner_id),
            ("sex", "sex", planned.sex),
            ("date_of_birth", "date of birth", planned.date_of_birth),
        ):
            if not value:
                continue
            have = getattr(row, field_name, None) if row else None
            if not have:
                planned.details_to_fill[field_name] = value
                planned.fills.append(label)
            elif str(have).lower() != str(value).lower():
                planned.notes.append(f"{label.capitalize()} kept as recorded.")

        if planned.guardian_contact:
            linked = Guardianship.objects.filter(
                student=child,
                guardian__in=User.objects.matching_identifier(planned.guardian_contact),
            ).exists()
            if not linked:
                planned.link_guardian = True
                planned.fills.append(f"guardian {planned.guardian_name}")

        planned.outcome = UPDATED if planned.fills else SKIPPED


def _lock_the_roll(school):
    """One import at a time per school, until the transaction ends.

    The second press of a double press, or a retry after a slow answer, waits
    here and then checks the file against the roll the first one wrote, so every
    row comes back `SKIPPED` rather than admitted twice. Keyed on the school, so
    two schools never wait on each other.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"roll-import:{school.pk}"])


def admit(actor, school, term, source) -> Report:
    """Admit a whole file, or none of it; and never the same child twice (G-15).

    `check()` runs first and the write only starts if it found nothing. That
    ordering *is* the all-or-nothing rule — interleaving the two, writing each
    row as it passes, is exactly the half-applied file this module exists to
    prevent, and it would pass every test that only counts errors.

    **The check runs inside the transaction, after `_lock_the_roll()`**, so two
    imports of one file at one school are one after the other, and the second
    is checked against what the first wrote. One transaction over all of it, so
    a refusal the check could not foresee — a handle claimed by another school
    between the two passes — takes the whole file back out rather than leaving a
    prefix of it behind.

    Each row does what `check()` said: a `NEW` row admits, places and links; an
    `UPDATED` row fills what the roll had nothing for; a `SKIPPED` row writes
    nothing.

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

    with transaction.atomic():
        _lock_the_roll(school)
        report = check(school, source, term)
        if not report.ok:
            return report

        taken = _handles_in_use(school, [p for p in report.planned if p.outcome == NEW])
        for planned in report.planned:
            if planned.outcome == SKIPPED:
                continue
            if planned.outcome == UPDATED:
                _fill(actor, school, term, planned, report)
                continue

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
            _link_and_report(actor, school, membership, planned, report)

    return report


def _fill(actor, school, term, planned, report):
    """Write what an `UPDATED` row fills in, and nothing else."""
    from accounts.services import set_admission_number_as

    child = planned.existing
    if planned.set_reference:
        set_admission_number_as(actor, child, planned.reference)
    if planned.place:
        academics.place_student_as(actor, planned.class_group, term, child, by=actor)
    if planned.details_to_fill:
        row = details.details_for([child.pk]).get(child.pk)
        details.record(
            child.pk,
            learner_id=planned.details_to_fill.get("learner_id", getattr(row, "learner_id", "") or ""),
            sex=planned.details_to_fill.get("sex", getattr(row, "sex", "") or ""),
            date_of_birth=planned.details_to_fill.get(
                "date_of_birth", getattr(row, "date_of_birth", None) if row else None
            ),
            by=actor,
        )
    if planned.link_guardian:
        _link_and_report(actor, school, child, planned, report)


def _link_and_report(actor, school, membership, planned, report):
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
    if planned.outcome != NEW:
        return
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
    "NEW",
    "SKIPPED",
    "UPDATED",
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
