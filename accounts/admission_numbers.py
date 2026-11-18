"""An admission number names one child at one school. Audit finding G-14.

A child's admission number is `Membership.reference` on their STUDENT row. Until
G-14 nothing held it unique: the roll import checked it case-sensitively, the
one-at-a-time admission did not check at all, and a transfer carried the
sending school's number across without looking. Every door that takes a number
(`cbt/sitting.py`, `cbt/pins.py`, `results/checker.py`) matches it **without
case**, so "jss/014" and "JSS/014" were two numbers to the import and one to the
doors, and a no-PIN test opened for neither child.

## The rule, in one sentence

**At one school, no two STUDENT memberships hold the same non-blank admission
number, compared without case and without surrounding spaces.** Every status
counts, ended included: a number given to a child who has left is not handed to
the next child, because their cards, receipts and exam slips still carry it.

Blank is not a number. A school that does not use admission numbers has every
child blank, and that is fine.

## Where it is held

- **The database.** `an_admission_number_names_one_child_per_school`, a partial
  unique index on `(school_id, lower(reference))` for student rows with a
  non-blank reference (`accounts/migrations/0021_...`). It is what refuses two
  admissions that pass the check at the same instant, and anything that writes
  the table without coming through here: a shell, a data migration, a
  `QuerySet.update()`.
- **Here**, so that every path that writes a number refuses in a sentence first:
  `services.enroll_student()` (one admission, and the roll import through it),
  `services.set_admission_number_as()` (the edit), and
  `services.transfer_student()` (a number carried from another school). A
  collision the check could not see arrives from the index, and
  `services.grant_membership()` and the edit turn it into the same refusal.

Numbers are stored stripped of surrounding spaces (`clean()`), because the doors
strip what a child types, and an index on `lower(reference)` would otherwise let
"JSS/014 " sit beside "JSS/014".

## Existing rows

The migration that adds the index first looks for numbers already shared and,
if there are any, stops with every one of them listed: school, number, and each
child holding it. Postgres's own refusal would name only the first pair it hit.
`python manage.py admission_number_clashes` prints the same list without
migrating, so a server can be checked before a deploy.
"""

from django.db import connection
from django.db.models.functions import Lower

#: The index's name: what `is_the_clash()` asks the database about, and what the
#: tests assert on (operating rule 5: assert on the constraint's name).
CONSTRAINT = "an_admission_number_names_one_child_per_school"


def clean(reference) -> str:
    """The number as it is stored and compared: surrounding spaces gone."""
    return (reference or "").strip()


def holder(school, reference, *, excluding=None):
    """The STUDENT membership at `school` holding `reference`, any status, or None.

    Compared as the index compares: without case, after `clean()`. `excluding` is
    the membership being written, which may of course already hold its own
    number.
    """
    from .models import Membership, Role

    reference = clean(reference)
    if not reference:
        return None
    rows = (
        Membership.objects.annotate(_number=Lower("reference"))
        .filter(
            school_id=getattr(school, "pk", school),
            role=Role.STUDENT,
            _number=reference.lower(),
        )
        .select_related("user")
        .order_by("pk")
    )
    if excluding is not None:
        rows = rows.exclude(pk=getattr(excluding, "pk", excluding))
    return rows.first()


def refusal(reference, held_by) -> str:
    """The sentence a clash is refused with. Names the child: it is this school's own roll."""
    from .models import LIVE_STATUSES

    name = held_by.display_name or held_by.user.full_name or held_by.user.username
    if held_by.status in LIVE_STATUSES:
        return (
            f"{clean(reference)!r} is already the admission number of {name} at this "
            "school. Each child needs their own."
        )
    return (
        f"{clean(reference)!r} was the admission number of {name}, who has left this "
        "school. A number is not given to a second child: their records still carry it."
    )


def require_free(school, reference, *, excluding=None):
    """Raise `AdmissionNumberTaken` if `reference` is another child's here."""
    from .services import AdmissionNumberTaken

    held_by = holder(school, reference, excluding=excluding)
    if held_by is not None:
        raise AdmissionNumberTaken(refusal(reference, held_by))


def is_the_clash(exc) -> bool:
    """Was this `IntegrityError` the admission-number index, and nothing else?"""
    diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    return getattr(diag, "constraint_name", None) == CONSTRAINT


#: Every number held by more than one student at a school. Raw SQL, because the
#: migration runs it against the historical schema and the command against the
#: live one, and the question is the same in both.
_CLASHES = """
SELECT s.name, s.schema_name, lower(btrim(m.reference)) AS number,
       json_agg(json_build_array(m.id, coalesce(nullif(m.display_name, ''), u.full_name, u.username),
                                 m.reference, m.status) ORDER BY m.id)
FROM accounts_membership m
JOIN schools_school s ON s.id = m.school_id
JOIN accounts_user u ON u.id = m.user_id
WHERE m.role = 'student' AND btrim(m.reference) <> ''
GROUP BY s.name, s.schema_name, m.school_id, lower(btrim(m.reference))
HAVING count(*) > 1
ORDER BY s.name, number
"""


def clashes(cursor=None) -> list:
    """`[(school name, schema, number, [(membership id, name, as typed, status)])]`."""
    import json

    def run(cur):
        cur.execute(_CLASHES)
        return [
            (name, schema, number, [tuple(r) for r in (holders if isinstance(holders, list) else json.loads(holders))])
            for name, schema, number, holders in cur.fetchall()
        ]

    if cursor is not None:
        return run(cursor)
    with connection.cursor() as cur:
        return run(cur)


def clash_report(found) -> str:
    """`clashes()` as the text an operator reads: every school, number and child."""
    lines = [
        f"{sum(len(h) for *_, h in found)} children share {len(found)} admission "
        "number(s). Each must be given its own before the unique index can be added:",
    ]
    for name, schema, number, holders in found:
        lines.append(f"  {name} ({schema}), number {number!r}:")
        for membership_id, child, typed, status in holders:
            lines.append(f"    membership {membership_id}: {child}, typed {typed!r}, {status}")
    lines.append(
        "Change all but one with PUT /api/enrolment/roll/<membership id>/admission-number/ "
        "(or services.set_admission_number_as()), then migrate again. "
        "`python manage.py admission_number_clashes` lists them without migrating."
    )
    return "\n".join(lines)


def surrounding_spaces(cursor=None) -> int:
    """Student numbers stored with surrounding spaces, which the migration trims."""
    sql = (
        "SELECT count(*) FROM accounts_membership "
        "WHERE role = 'student' AND reference <> btrim(reference)"
    )
    if cursor is not None:
        cursor.execute(sql)
        return cursor.fetchone()[0]
    with connection.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


__all__ = [
    "CONSTRAINT",
    "clash_report",
    "clashes",
    "clean",
    "holder",
    "is_the_clash",
    "refusal",
    "require_free",
]
