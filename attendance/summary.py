"""A term's registers, counted per child — the three numbers a card carries.

Read **once** at the top of `results.services.release()`'s locked block and
handed down, never once per child. That is the shape issue #60 forced on
`positions.ClassResults` for the reason this module inherits: two reads under
READ COMMITTED are two answers, the lock is on the `ResultSheet` row and not on
the registers, and a mark landing mid-freeze would put one child's attendance on
a card that disagrees with the child beside her.

## Why there is no `days_unmarked` here

`open - present - absent` is the unmarked remainder, and it is computed where it
is read rather than stored, because `days_open` is the school's declared
`Term.school_days` and lives on `Term` — not on this term's registers. A
summary that carried the remainder would be carrying a subtraction against a
number this module has no business knowing, and the three stored columns on
`ReleasedCard` already make it recoverable on the card itself.

What this module refuses to do is guess. A child with no mark on a day is not
absent, and the count returned for her is simply lower — the gap is the school's
and shows up as the remainder, which is the whole of A4.
"""

from dataclasses import dataclass

from django.db.models import Count, Q

from .models import AttendanceMark, AttendanceStatus


@dataclass(frozen=True)
class TermAttendance:
    """One child's term, in the two numbers that were actually observed.

    `days_open` is deliberately **not** here. It is the school's declaration
    about the calendar, not an observation about this child, and joining the two
    in this object would invite a caller to treat the pair as one measurement.
    `results.cards` puts them side by side on the card, where the difference
    between them is the point.
    """

    present: int
    absent: int

    @property
    def marked(self) -> int:
        return self.present + self.absent


#: What a child with no marks at all gets. Zero and zero, **not** null: she was
#: not marked, which is a real answer and a different one from "this card has no
#: attendance on it". The card's renderer tells those apart by `marked == 0`
#: against all three columns being null, and that distinction is why this
#: returns a value for every child asked about rather than omitting her.
NOTHING_MARKED = TermAttendance(present=0, absent=0)


def for_term(term, student_ids) -> dict[int, TermAttendance]:
    """`student_membership_id -> TermAttendance`, for every id asked about.

    One aggregate query over the term's marks, not one per child: a release
    freezes a whole class and per-child reads would be forty-five round trips
    inside a lock that is already held.

    **Every id gets an entry**, including children with no marks. A dict that
    omitted them would make "not marked" indistinguishable from "not asked
    about" at the call site, and `freeze_for_release()` writes a row for every
    child on the roster unconditionally — so a missing key there would be a
    `KeyError` in the middle of a release rather than a zero on a card.

    Counted across every register in the term regardless of which class group
    took it. A child who moved from JSS 1A to JSS 1B in October was marked by
    both, and both halves are her attendance for the term; `Register.class_group`
    records who did the marking, which is a different question and the one D2 is
    about.
    """
    ids = list(student_ids)
    if not ids:
        return {}

    counted = (
        AttendanceMark.objects.filter(
            register__term=term, student_membership_id__in=ids
        )
        .values("student_membership_id")
        .annotate(
            present=Count("pk", filter=Q(status=AttendanceStatus.PRESENT)),
            absent=Count("pk", filter=Q(status=AttendanceStatus.ABSENT)),
        )
    )
    found = {
        row["student_membership_id"]: TermAttendance(
            present=row["present"], absent=row["absent"]
        )
        for row in counted
    }
    return {sid: found.get(sid, NOTHING_MARKED) for sid in ids}


__all__ = ["NOTHING_MARKED", "TermAttendance", "for_term"]
