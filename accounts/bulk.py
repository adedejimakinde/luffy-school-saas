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
"""

import csv
import io
from dataclasses import dataclass, field

from django.db import transaction

from academics import services as academics
from academics.models import ClassGroup
from accounts import guardian_contacts
from accounts.identifiers import canonical_username
from accounts.models import Membership, Role, User
from accounts.services import admit_student_as

#: The header a file must carry. Two are required of every row; the rest may be
#: absent from the file entirely.
REQUIRED_COLUMNS = ("full_name", "class_group")
OPTIONAL_COLUMNS = ("username", "reference", "guardian_name", "guardian_contact")


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


@dataclass
class GuardianLink:
    """One child linked to one guardian, and whether that parent can see them yet."""

    line: int
    guardian_contact: str
    status: str


@dataclass
class Report:
    """What a file would do, or did.

    `problems` empty means the file is admissible. `planned` is in file order,
    so a line number means the line in their spreadsheet.
    """

    problems: list = field(default_factory=list)
    planned: list = field(default_factory=list)
    #: Filled by `admit()`: the handles this school now has to hand out.
    generated: dict = field(default_factory=dict)
    #: Filled by `admit()`: every guardian link made, in file order.
    guardian_links: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


class BulkError(Exception):
    """The file cannot be read at all, or the school is not ready for one."""


def _read(text):
    """The file as a list of `(line number, row dict)`, header matched by name.

    Case-insensitive and order-independent: a spreadsheet somebody reordered is
    still the same file, and a positional format would read the new order as
    the old one and enrol everybody into the wrong class without a word.

    The header is line 1, so the first child is line 2 — which is what the
    office sees in their editor.
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise BulkError("That file has no header row, so its columns cannot be read.")

    seen = {(name or "").strip().lower(): name for name in reader.fieldnames}
    missing = [c for c in REQUIRED_COLUMNS if c not in seen]
    if missing:
        raise BulkError(
            "That file is missing the column"
            + ("s " if len(missing) > 1 else " ")
            + ", ".join(sorted(missing))
            + "."
        )

    rows = []
    for offset, raw in enumerate(reader, start=2):
        row = {
            key: (raw.get(original) or "").strip()
            for key, original in seen.items()
            if key in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
        }
        rows.append((offset, row))
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


def check(school, text) -> Report:
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

    for line, row in _read(text):
        problems_before = len(report.problems)

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
        guardian_contact = ""
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
                guardian_contact = read[1]

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
                )
            )

    return report


def admit(actor, school, term, text) -> Report:
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

    report = check(school, text)
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

    return report


__all__ = [
    "BulkError",
    "GuardianLink",
    "Report",
    "RowProblem",
    "PlannedChild",
    "REQUIRED_COLUMNS",
    "OPTIONAL_COLUMNS",
    "check",
    "admit",
]
