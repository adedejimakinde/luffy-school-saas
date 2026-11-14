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

    **School days are counted, not marks** (audit finding G-11). The database
    holds one mark per child per *register* and one register per class per day,
    and nothing says one mark per child per day: a child marked in JSS 1A in the
    morning and moved to JSS 1B that day, or on JSS 1B's list when its teacher
    fills in last week, has two marks for one day. Counting rows gave that child
    two days, and a term's total could pass the days the school opened. So each
    child's marks are read a day at a time and **a day counts once**: where two
    registers marked the same child on the same day, the mark written last is
    the day's answer (`updated_at`, then the row's id), which is how a
    correction works everywhere else. `take_register()` no longer writes the
    second mark; this is what holds for the ones already written.
    """
    ids = list(student_ids)
    if not ids:
        return {}

    # `DISTINCT ON (child, day)`, keeping the row that sorts first: the mark
    # written last. One query for the class, as before.
    days = (
        AttendanceMark.objects.filter(
            register__term=term, student_membership_id__in=ids
        )
        .order_by(
            "student_membership_id", "register__taken_on", "-updated_at", "-pk"
        )
        .distinct("student_membership_id", "register__taken_on")
        .values_list("student_membership_id", "status")
    )
    present, absent = {}, {}
    for student_id, status in days:
        if status == AttendanceStatus.PRESENT:
            present[student_id] = present.get(student_id, 0) + 1
        elif status == AttendanceStatus.ABSENT:
            absent[student_id] = absent.get(student_id, 0) + 1
    return {
        sid: TermAttendance(present=present.get(sid, 0), absent=absent.get(sid, 0))
        if sid in present or sid in absent
        else NOTHING_MARKED
        for sid in ids
    }


__all__ = ["NOTHING_MARKED", "TermAttendance", "for_term"]
