"""Whether a membership is a member of staff *of the school being written to*.

The sibling of `accounts.students.why_not_a_student_here()`, and it exists for
the same reason that one does: a tenant table is about to store a bare
membership id, that column carries no foreign key (docs/tenancy.md), and the
school half of "is this the right person" has to be asked in code however the
column is declared.

Read that module's docstring for the full argument, including why a foreign key
would not have helped — `Membership` is shared, so a key into it constrains only
that the row exists, and every school's staff are in that one table.

Kept in its own module rather than added to `students.py`, because the two
questions are asked by different callers about different people and the file
names are how a reader finds the right one.
"""

from django.db import connection

from .models import Role


def why_not_a_teacher_here(membership, *, subject: str, holder: str) -> str | None:
    """Why `membership` may not hold `subject` here, or `None` if it may.

    "Here" is the schema the connection is on, read from the connection rather
    than passed in — the load-bearing detail
    `students.why_not_a_student_here()` sets out, and for the identical reason:
    the tenant row about to be written has already been chosen by the
    `search_path`, so a school passed in as an argument is a second opinion that
    can disagree with it.

    Two questions, because they fail differently:

    1. **Is this a TEACHER membership?** A class-teacher assignment naming a
       parent's or a bursar's membership is not a near miss. The TEACHER
       membership is what pins both the person and their school.
    2. **Is that teacher ours?** The column will accept any integer, including a
       teacher at another school, and nothing about the resulting row would look
       wrong afterwards: it would sit in St Mary's tables and name somebody St
       Mary's has never employed.

    `subject` and `holder` are the nouns the caller phrases it with — "a class
    teacher" and "the class register" — so the refusal reads like the app that
    made it.
    """
    if membership.role != Role.TEACHER:
        return (
            f"{membership} is not a teacher membership. {subject.capitalize()} "
            f"is keyed on a TEACHER membership, which is what pins both the "
            f"person and their school."
        )

    if membership.school.schema_name != connection.schema_name:
        return (
            f"{membership.user} teaches at {membership.school}, and this is "
            f"another school's {holder}. {subject.capitalize()} belongs to the "
            f"school the teacher works at."
        )

    return None


__all__ = ["why_not_a_teacher_here"]
