"""Who may do what in CBT: steps 2 and 3. `docs/cbt.md`, "Who sees what".

One module so that every route and every service asks the same question, and the menu
reads the same role sets (`menu.py`). Each answer reads the roles the login holds **at
this school** (`User.roles_at()`), this school's own `ExamOfficerGrant` rows for an exam
officer, and this school's own `SubjectTeacher` rows for a teacher's reach, so a role,
a grant or an assignment at one school is nothing at another.

| | exam slips | exam officers | banks and questions | tests |
| --- | --- | --- | --- | --- |
| Principal | prints, any class | names and ends | reads and writes all | sets any; **approves** |
| Vice principal | no, unless named | no | reads all | reads all, and their questions |
| Teacher | no, unless named | no | reads and writes their own subjects at their own levels | sets and reads their own subjects for their own classes |
| Administrator | prints, any class | sees who they are | **never**, named officer or not | title, classes, window, size and code state; **never a question** |
| Exam officer (named) | prints, any class | sees who they are | nothing beyond their own as a teacher | nothing beyond their role, in this step |
| Bursar, parent, student | no | no | never | never |

**A teacher's own** are the (subject, class) pairs the principal gave them this term
(`gradebook.assignments.pairs_of()`); their banks are those subjects at those classes'
levels. A teacher with no assignment this term has no bank and no test. The marking
switch ("Open marking to all teachers") opens marking, not banks.

**Approving** a test is the principal's. The vice principal reads every bank and every
test, and their questions, so they can review one, and approves nothing:
`docs/cbt.md` gives the vice principal "All tests (read)".

**A login holding the administrator role never reads a bank or a question**, whatever
else it holds, and being named exam officer adds nothing (decided 20 October 2026).
"""

from django.db import connection
from django.db.models import QuerySet

from dataclasses import dataclass, field

from accounts.models import Membership, Role

from .models import ExamOfficerGrant

#: Who prints exam slips by their role alone. An exam officer prints them too.
PRINTING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})

#: Who names and ends exam officers: the principal alone.
NAMING_ROLES = frozenset({Role.PRINCIPAL.value})

#: Whom the principal may name: a teacher, the vice principal or the administrator.
OFFICER_ROLES = frozenset(
    {Role.TEACHER.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)

#: Who reads question banks, each within their own reach (`reach()`): the
#: principal and the vice principal all, a teacher their own. **Never the
#: administrator**, who runs sittings and not their content (decided 20 October 2026),
#: and being named exam officer does not change that.
BANK_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.TEACHER.value}
)


def _roles(actor, school) -> set:
    if not getattr(actor, "is_authenticated", False):
        return set()
    return set(actor.roles_at(school))


def _here(school) -> bool:
    """Is the connection on this school's schema? The grants read are the connection's."""
    return school is not None and connection.schema_name == school.schema_name


def officer_memberships(membership_ids) -> set:
    """Which of these memberships' latest grant, in this schema, names them an exam officer.

    `membership_ids` is a list or a query of ids. One statement either way: Postgres's
    DISTINCT ON keeps each membership's newest row, and a query is a subquery.
    """
    if isinstance(membership_ids, QuerySet):
        ids = membership_ids
    else:
        ids = list(membership_ids)
        if not ids:
            return set()
    latest = (
        ExamOfficerGrant.objects.filter(membership_id__in=ids)
        .order_by("membership_id", "-id")
        .distinct("membership_id")
        .values_list("membership_id", "kind")
    )
    return {mid for mid, kind in latest if kind == ExamOfficerGrant.Kind.NAMED}


def _officer_ids_of(actor, school):
    """The actor's memberships here that a grant could name and that can act now, as a query."""
    return (
        Membership.objects.with_access()
        .filter(user=actor, school=school, role__in=OFFICER_ROLES)
        .values("pk")
    )


def is_exam_officer(actor, school) -> bool:
    """Has the principal named one of this login's memberships here, and not ended it?

    A membership that is suspended or ended is no officer while it is so: `with_access()`
    leaves it out, as `roles_at()` does.
    """
    if not getattr(actor, "is_authenticated", False) or not _here(school):
        return False
    return bool(officer_memberships(_officer_ids_of(actor, school)))


def can_print(actor, school) -> bool:
    """May this login print exam slips here? The principal, the administrator, an exam officer."""
    if _roles(actor, school) & PRINTING_ROLES:
        return True
    return is_exam_officer(actor, school)


def can_name(actor, school) -> bool:
    """May this login name and end exam officers here? The principal alone."""
    return bool(_roles(actor, school) & NAMING_ROLES)


def can_read_banks(actor, school) -> bool:
    """Could this login read a question bank here, by its roles? Never a login holding the
    administrator role, and being named exam officer adds nothing.

    The role half of the rule. Which banks is `reach()`: a teacher with no assignment
    this term holds the role and reads none.
    """
    roles = _roles(actor, school)
    if Role.ADMIN.value in roles:
        return False
    return bool(roles & BANK_ROLES)


#: Who opens the Tests page at all: everybody who reads banks, and the administrator,
#: who sees what is set and when, and never a question.
TEST_ROLES = BANK_ROLES | frozenset({Role.ADMIN.value})

#: Who writes into banks and sets tests, each within their reach.
WRITING_ROLES = frozenset({Role.PRINCIPAL.value, Role.TEACHER.value})

#: Who approves a test, which publishes it: the principal alone.
APPROVING_ROLES = frozenset({Role.PRINCIPAL.value})


@dataclass(frozen=True)
class Reach:
    """What one login reaches in banks and tests here, for one term. Ask it, never the roles.

    `class_pairs` are the (subject id, class group id) pairs the login teaches that
    term, and `bank_pairs` the (subject id, level) pairs those make. A principal reads
    and writes all; a vice principal reads all; an administrator, a bursar, a parent and
    a student reach nothing, and `sees_tests` says whether the administrator's summary
    of the tests is theirs.
    """

    reads_all: bool = False
    writes_all: bool = False
    approves: bool = False
    #: The administrator: the Tests page, with no question on it.
    sees_test_summaries: bool = False
    class_pairs: frozenset = field(default_factory=frozenset)
    bank_pairs: frozenset = field(default_factory=frozenset)

    @property
    def reads_any_bank(self) -> bool:
        return self.reads_all or bool(self.bank_pairs)

    @property
    def opens_tests(self) -> bool:
        return self.reads_any_bank or self.sees_test_summaries or self.writes_all

    @property
    def writes_any(self) -> bool:
        return self.writes_all or bool(self.bank_pairs)

    def reads_bank(self, subject_id, level) -> bool:
        return self.reads_all or (subject_id, level) in self.bank_pairs

    def writes_bank(self, subject_id, level) -> bool:
        return self.writes_all or (subject_id, level) in self.bank_pairs

    def teaches(self, subject_id, class_group_id) -> bool:
        """May this login set a test of this subject for this class?"""
        return self.writes_all or (subject_id, class_group_id) in self.class_pairs


NOBODY = Reach()


def may_open_tests(actor, school) -> bool:
    """Does this login hold a role the Tests page answers? Roles only; no query."""
    return _here(school) and bool(_roles(actor, school) & TEST_ROLES)


def reach(actor, school, term) -> Reach:
    """What this login reaches in banks and tests here, in `term` (the test's own term).

    A login holding the administrator role reaches no bank and no question whatever else
    it holds, and only the tests' summaries. Asks the database only for a teacher's
    assignments, and only when the login holds the teacher role.
    """
    roles = _roles(actor, school)
    if not _here(school) or not roles & TEST_ROLES:
        return NOBODY
    if Role.ADMIN.value in roles:
        return Reach(sees_test_summaries=True)
    principal = Role.PRINCIPAL.value in roles
    reads_all = principal or Role.VICE_PRINCIPAL_ACADEMIC.value in roles
    class_pairs = frozenset()
    bank_pairs = frozenset()
    if Role.TEACHER.value in roles and not principal and term is not None:
        from academics.models import ClassGroup
        from gradebook import assignments

        class_pairs = frozenset(assignments.pairs_of(actor, school, term))
        levels = dict(
            ClassGroup.objects.filter(pk__in={c for _, c in class_pairs}).values_list("pk", "level")
        )
        bank_pairs = frozenset((s, levels[c]) for s, c in class_pairs if c in levels)
    return Reach(
        reads_all=reads_all,
        writes_all=principal,
        approves=bool(roles & APPROVING_ROLES),
        class_pairs=class_pairs,
        bank_pairs=bank_pairs,
    )


def menu_keys(roles, actor, school) -> frozenset:
    """Links a login holds by a permission rather than a role: the exam slips page for an
    exam officer whose roles alone would not show it (`menu.py`).

    Asks the database only for a login that could be named and does not already print
    by role, so the principal, the administrator, a bursar and a parent cost nothing.
    """
    roles = set(roles)
    if not roles & OFFICER_ROLES or roles & PRINTING_ROLES:
        return frozenset()
    return frozenset({"exam-slips"}) if is_exam_officer(actor, school) else frozenset()


__all__ = [
    "APPROVING_ROLES",
    "BANK_ROLES",
    "NOBODY",
    "Reach",
    "TEST_ROLES",
    "WRITING_ROLES",
    "NAMING_ROLES",
    "OFFICER_ROLES",
    "PRINTING_ROLES",
    "can_name",
    "can_print",
    "can_read_banks",
    "is_exam_officer",
    "may_open_tests",
    "menu_keys",
    "officer_memberships",
    "reach",
]
